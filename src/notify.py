"""Notification dispatch.

All sends run on a background worker thread fed by a queue, so a slow SMTP
handshake never delays the next poll. Channels: email (Gmail SMTP), ntfy
(phone push, no account needed) and Telegram (bot API).
"""

import logging
import queue
import threading
import time
from datetime import datetime
from typing import List, Optional

import requests

from .models import RentalListing
from .email import EmailNotifier

logger = logging.getLogger(__name__)


def _present(value: Optional[str]) -> Optional[str]:
    return value if value and value != "N/A" else None


def nice_deadline(value: Optional[str]) -> Optional[str]:
    """'2026-09-19 23:59' -> 'Sat 19 Sep 23:59'; anything unparseable is returned as is."""
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%a %d %b %H:%M") if fmt.endswith("%M") else dt.strftime("%a %d %b")
        except ValueError:
            continue
    return value


def listing_headline(l: RentalListing) -> str:
    """One glanceable line: area · rooms · size · rent."""
    parts = [l.area, _present(l.number_of_rooms), _present(l.size), _present(l.rent_cost)]
    return " · ".join(p for p in parts if p)


def listing_details(l: RentalListing) -> str:
    """Address, deadline, link - one per line."""
    lines = [l.street]
    deadline = nice_deadline(l.published_until)
    if deadline:
        lines.append(f"Apply by {deadline}" + (" (lottery)" if l.lottery else ""))
    elif l.lottery:
        lines.append("Lottery")
    if l.url:
        lines.append(l.url)
    return "\n".join(lines)


def listings_text(listings: List[RentalListing]) -> str:
    return "\n\n".join(f"{listing_headline(l)}\n{listing_details(l)}" for l in listings)


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
            # ntfy headers are Latin-1; Swedish letters fit, anything else is replaced.
            'Title': title.encode('latin-1', 'replace').decode('latin-1'),
            'Priority': priority or self.priority,
            'Tags': tags,
        }
        if click:
            headers['Click'] = click
            headers['Actions'] = f'view, Open listing, {click}'
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
        """One notification per listing, so each can be judged from its title line."""
        ok = True
        for l in listings:
            ok = self._post(listing_headline(l), listing_details(l), click=l.url,
                            priority='urgent', tags='house') and ok
        return ok

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
