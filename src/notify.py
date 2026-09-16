"""Notification dispatch.

All sends run on a background worker thread fed by a queue, so a slow SMTP
handshake never delays the next poll. Channels: email (Gmail SMTP), ntfy
(phone push, no account needed) and Telegram (bot API).
"""

import logging
import queue
import threading
import time
from typing import List, Optional

import requests

from .models import RentalListing
from .email import EmailNotifier

logger = logging.getLogger(__name__)


def listings_text(listings: List[RentalListing]) -> str:
    lines = []
    for l in listings:
        parts = [f"{l.street}, {l.area}", l.number_of_rooms, l.size, l.rent_cost]
        parts = [p for p in parts if p and p != "N/A"]
        extras = []
        if l.published_until:
            extras.append(f"apply by {l.published_until}")
        if l.lottery:
            extras.append("lottery")
        if l.move_in:
            extras.append(f"move in {l.move_in}")
        line = " · ".join(parts)
        if extras:
            line += f" ({', '.join(extras)})"
        lines.append(line)
        if l.url:
            lines.append(l.url)
    return "\n".join(lines)


class NtfyChannel:
    """https://ntfy.sh - subscribe to a topic in the phone app, POST to publish."""
    name = "ntfy"

    def __init__(self, config: dict):
        self.enabled = config.get('enabled', False)
        self.server = (config.get('server') or 'https://ntfy.sh').rstrip('/')
        self.topic = config.get('topic')
        self.token = config.get('token')
        self.priority = str(config.get('priority', 'high'))
        if self.enabled and not self.topic:
            logger.warning("ntfy enabled but no topic configured; disabling")
            self.enabled = False

    def _post(self, title: str, body: str, click: Optional[str] = None, priority: Optional[str] = None,
              tags: str = "house") -> bool:
        if not self.enabled:
            return False
        headers = {
            'Title': title.encode('utf-8').decode('latin-1', 'replace'),
            'Priority': priority or self.priority,
            'Tags': tags,
        }
        if click:
            headers['Click'] = click
        if self.token:
            headers['Authorization'] = f'Bearer {self.token}'
        try:
            r = requests.post(f"{self.server}/{self.topic}", data=body.encode('utf-8'),
                              headers=headers, timeout=10)
            r.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"ntfy failed: {e}")
            return False

    def send_listings(self, listings: List[RentalListing]) -> bool:
        first = listings[0]
        title = (f"New listing: {first.street}" if len(listings) == 1
                 else f"{len(listings)} new listings")
        return self._post(title, listings_text(listings), click=first.url, priority='urgent')

    def send_text(self, title: str, body: str) -> bool:
        # Operational alerts (site down, blocked, structure changed) must be noticed.
        if 'recovered' in title.lower():
            return self._post(title, body, priority='default', tags='white_check_mark')
        return self._post(title, body, priority='high', tags='rotating_light')

    def send_summary(self, stats: dict) -> bool:
        body = (f"{stats.get('new_listings', 0)} new listings, {stats.get('total_polls', 0)} polls, "
                f"{stats.get('errors', 0)} errors")
        return self._post(f"Daily summary {stats.get('date', '')}", body, priority='low', tags='bar_chart')


class TelegramChannel:
    name = "telegram"

    def __init__(self, config: dict):
        self.enabled = config.get('enabled', False)
        self.bot_token = config.get('bot_token')
        self.chat_id = config.get('chat_id')
        if self.enabled and not (self.bot_token and self.chat_id):
            logger.warning("telegram enabled but bot_token/chat_id missing; disabling")
            self.enabled = False

    def _send(self, text: str) -> bool:
        if not self.enabled:
            return False
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={'chat_id': self.chat_id, 'text': text, 'disable_web_page_preview': True},
                timeout=10)
            r.raise_for_status()
            return True
        except requests.RequestException as e:
            logger.error(f"telegram failed: {e}")
            return False

    def send_listings(self, listings: List[RentalListing]) -> bool:
        header = "New listing" if len(listings) == 1 else f"{len(listings)} new listings"
        return self._send(f"{header}\n\n{listings_text(listings)}")

    def send_text(self, title: str, body: str) -> bool:
        return self._send(f"{title}\n\n{body}")

    def send_summary(self, stats: dict) -> bool:
        return self._send(f"Daily summary {stats.get('date', '')}: {stats.get('new_listings', 0)} new, "
                          f"{stats.get('total_polls', 0)} polls, {stats.get('errors', 0)} errors")


class Notifier:
    """Queue-backed fan-out to every enabled channel."""

    def __init__(self, notifications_config: dict, alert_cooldown_seconds: int = 3600):
        cfg = notifications_config or {}
        self.channels = [
            EmailNotifier(cfg.get('email') or {}),
            NtfyChannel(cfg.get('ntfy') or {}),
            TelegramChannel(cfg.get('telegram') or {}),
        ]
        self.enabled_channels = [c for c in self.channels if c.enabled]
        self.alert_cooldown = alert_cooldown_seconds
        self._last_alert = {}
        self._queue: "queue.Queue" = queue.Queue()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, name="notifier", daemon=True)
        self.sent = 0
        self.failed = 0

    def start(self):
        self._thread.start()
        logger.info(f"Notifier channels: {[c.name for c in self.enabled_channels] or 'none'}")

    def stop(self, drain_seconds: float = 10.0):
        self._stop.set()
        self._queue.put(None)
        self._thread.join(timeout=drain_seconds)

    # -- public API (non-blocking) -------------------------------------------

    def notify_listings(self, listings: List[RentalListing]):
        if listings:
            self._queue.put(('listings', listings))

    def alert(self, key: str, title: str, body: str):
        """Operational alert with a per-key cooldown so a broken site does not spam you."""
        now = time.monotonic()
        last = self._last_alert.get(key)
        if last is not None and now - last < self.alert_cooldown:
            return
        self._last_alert[key] = now
        self._queue.put(('text', title, body))

    def clear_alert(self, key: str):
        self._last_alert.pop(key, None)

    def daily_summary(self, stats: dict):
        self._queue.put(('summary', stats))

    def send_now(self, job) -> bool:
        """Synchronous send; used by the worker and by tests."""
        kind = job[0]
        ok_any = False
        for channel in self.enabled_channels:
            try:
                if kind == 'listings':
                    ok = channel.send_listings(job[1])
                elif kind == 'text':
                    ok = channel.send_text(job[1], job[2])
                elif kind == 'summary':
                    ok = channel.send_summary(job[1])
                else:
                    ok = False
            except Exception as e:
                logger.error(f"{channel.name} raised: {e}")
                ok = False
            if ok:
                logger.info(f"Sent {kind} via {channel.name}")
                ok_any = True
            else:
                logger.error(f"Failed to send {kind} via {channel.name}")
        return ok_any

    # -- worker ----------------------------------------------------------------

    def _worker(self):
        while True:
            job = self._queue.get()
            if job is None:
                break
            if self.send_now(job):
                self.sent += 1
            else:
                self.failed += 1
            self._queue.task_done()
