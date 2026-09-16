"""Rental Listings Scheduler.

One poller thread per source, each on its own interval, so a slow or failing
site never delays the others. New listings are handed to the notifier queue
the moment they are detected.

The main thread supervises: it restarts a poller whose thread died, alerts
when a source has had no successful poll for too long, pings an optional
external heartbeat (dead man's switch), and sends the daily summary.
"""

import logging
import re
import signal
import sys
import threading
import time
from datetime import datetime, time as dt_time
from typing import Callable, Dict, List, Optional

import pytz
import requests
import yaml

from .logging import setup_logging
from .scraper import SCRAPERS, ScrapeResult
from .detector import ChangeDetector
from .notify import Notifier

setup_logging()
logger = logging.getLogger(__name__)

stop_event = threading.Event()

DEFAULT_INTERVALS = {
    'wahlin_arena': 20,   # system of record for Wåhlin; short-lived listings appear here
    'wallfast': 20,       # ads published weekdays 11-14, can vanish within minutes
    'wahlin': 300,        # daily mirror of Arena; fallback only
    'heimstaden': 3600,   # 2.5 MB nationwide response; allocation by registration date, so hourly is enough
}

DEFAULT_HEALTH = {
    'alert_after_consecutive_failures': 5,  # generic failures (network, parse) before alerting
    'stale_after_seconds': 180,             # no successful poll for this long -> alert
    'block_status_codes': [401, 403, 429],  # alert on the FIRST occurrence: looks like a ban
    'max_backoff_seconds': 300,             # cap for backoff after failures
    'alert_cooldown_seconds': 3600,         # repeat "still down" alerts at most this often
    'heartbeat_url': '',                    # e.g. https://hc-ping.com/<uuid>; pinged every minute while healthy
}


def signal_handler(_signum, _frame):
    logger.info("Shutting down...")
    stop_event.set()


# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

def load_config(path: str = 'config.yaml') -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)
    return normalize_config(raw)


def normalize_config(raw: dict) -> dict:
    """Accept both the v2 layout and the original v1 layout."""
    cfg = dict(raw)
    schedule = cfg.get('schedule') or {}
    cfg['timezone'] = cfg.get('timezone') or schedule.get('timezone') or 'Europe/Stockholm'
    cfg['summary_time'] = cfg.get('summary_time') or schedule.get('end') or '23:59'
    cfg['database'] = cfg.get('database') or 'data/rentals.db'
    # Retention: 0 (default) keeps every listing ever seen; the data is tiny and
    # the first/last-seen history is what tells us how each landlord publishes.
    cfg['cleanup_days'] = int(cfg.get('cleanup_days') or 0)
    cfg['dedupe_days'] = int(cfg.get('dedupe_days') or 14)   # cross-source duplicate window
    backup = cfg.get('backup') or {}
    cfg['backup'] = {
        'enabled': bool(backup.get('enabled', True)),
        'dir': backup.get('dir') or 'data/backups',
        'keep': int(backup.get('keep', 14)),
    }
    default_interval = int(cfg.get('poll_interval_seconds', 20))

    # Sources
    sources = {}
    if isinstance(cfg.get('sources'), dict):
        for name, s in cfg['sources'].items():
            if isinstance(s, bool):
                s = {'enabled': s}
            sources[name] = {
                'enabled': bool((s or {}).get('enabled', True)),
                'interval_seconds': int((s or {}).get('interval_seconds',
                                                      DEFAULT_INTERVALS.get(name, default_interval))),
                'exclude_areas': [str(a) for a in ((s or {}).get('exclude_areas') or [])],
                'include_areas': [str(a) for a in ((s or {}).get('include_areas') or [])],
            }
    elif isinstance(cfg.get('scrapers'), dict):
        # v1 layout: scrapers: {wahlin: true, wallfast: true}
        legacy = cfg['scrapers']
        if legacy.get('wahlin', True):
            sources['wahlin_arena'] = {'enabled': True, 'interval_seconds': DEFAULT_INTERVALS['wahlin_arena']}
            sources['wahlin'] = {'enabled': True, 'interval_seconds': DEFAULT_INTERVALS['wahlin']}
        if legacy.get('wallfast', True):
            sources['wallfast'] = {'enabled': True, 'interval_seconds': DEFAULT_INTERVALS['wallfast']}
    else:
        sources = {name: {'enabled': True, 'interval_seconds': iv} for name, iv in DEFAULT_INTERVALS.items()}
    cfg['sources'] = sources

    # Filters: listings in excluded areas are recorded but never notified.
    filters = cfg.get('filters') or {}
    cfg['filters'] = {'exclude_areas': [str(a) for a in (filters.get('exclude_areas') or [])]}

    # Notifications (v1 had a top-level email block)
    notifications = dict(cfg.get('notifications') or {})
    if 'email' not in notifications and isinstance(cfg.get('email'), dict):
        notifications['email'] = cfg['email']
    cfg['notifications'] = notifications

    health = dict(DEFAULT_HEALTH)
    health.update({k: v for k, v in (cfg.get('health') or {}).items() if v is not None})
    health['block_status_codes'] = [int(c) for c in (health.get('block_status_codes') or [])]
    health['heartbeat_url'] = (health.get('heartbeat_url') or '').strip()
    cfg['health'] = health

    # Optional active window (v1 "schedule" block). Default: around the clock.
    cfg['window'] = {
        'start': schedule.get('start', '00:00'),
        'end': schedule.get('end', '23:59'),
        'weekdays_only': bool(schedule.get('weekdays_only', False)),
    }
    return cfg


def is_within_window(config: dict, now: datetime) -> bool:
    w = config['window']
    if w['weekdays_only'] and now.weekday() >= 5:
        return False
    start = dt_time.fromisoformat(w['start'])
    end = dt_time.fromisoformat(w['end'])
    current = now.time()
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------

class Stats:
    def __init__(self, tz):
        self.tz = tz
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        with self._lock:
            self.start_time = datetime.now(self.tz)
            self.date = self.start_time.date()
            self.summary_sent = False
            self.sources = {}

    def _src(self, name):
        return self.sources.setdefault(name, {'polls': 0, 'failures': 0, 'new_listings': 0,
                                              'last_ok': None, 'last_error': None})

    def record(self, result: ScrapeResult, new_count: int):
        with self._lock:
            s = self._src(result.source)
            s['polls'] += 1
            if result.ok:
                s['last_ok'] = datetime.now(self.tz).isoformat(timespec='seconds')
                s['new_listings'] += new_count
            else:
                s['failures'] += 1
                s['last_error'] = result.error

    def snapshot(self) -> dict:
        with self._lock:
            now = datetime.now(self.tz)
            return {
                'date': now.strftime('%Y-%m-%d'),
                'uptime_hours': (now - self.start_time).total_seconds() / 3600,
                'total_polls': sum(s['polls'] for s in self.sources.values()),
                'new_listings': sum(s['new_listings'] for s in self.sources.values()),
                'errors': sum(s['failures'] for s in self.sources.values()),
                'sources': {k: dict(v) for k, v in self.sources.items()},
            }


# --------------------------------------------------------------------------
# Poller
# --------------------------------------------------------------------------

class SourcePoller(threading.Thread):
    def __init__(self, name: str, scraper, interval: int, config: dict,
                 detector: ChangeDetector, notifier: Notifier, stats: Stats, tz,
                 clock: Callable[[], float] = time.monotonic):
        super().__init__(name=f"poll-{name}", daemon=True)
        self.source = name
        self.scraper = scraper
        self.interval = max(5, int(interval))
        self.config = config
        self.detector = detector
        self.notifier = notifier
        self.stats = stats
        self.tz = tz
        self.clock = clock
        self.health = config['health']
        self.exclude_areas = (config.get('filters', {}).get('exclude_areas', [])
                              + config['sources'].get(name, {}).get('exclude_areas', []))
        # include_areas: only listings in these areas are even considered (not stored, not notified).
        self.include_areas = config['sources'].get(name, {}).get('include_areas', [])
        self.consecutive_failures = 0
        self.backoff = 0.0
        self.down = False                    # an alert has been raised and not yet cleared
        self.last_success_at = clock()       # treated as "fresh" at start
        self.last_error: Optional[str] = None

    # -- thread body -----------------------------------------------------------

    def run(self):
        logger.info(f"[{self.source}] polling every {self.interval}s"
                    + (f", only areas: {', '.join(self.include_areas)}" if self.include_areas else "")
                    + (f", not notifying for areas: {', '.join(self.exclude_areas)}" if self.exclude_areas else ""))
        while not stop_event.is_set():
            started = self.clock()
            if is_within_window(self.config, datetime.now(self.tz)):
                self.tick()
            elapsed = self.clock() - started
            stop_event.wait(max(0.0, self.interval + self.backoff - elapsed))
        logger.info(f"[{self.source}] stopped")

    def tick(self):
        """One poll, guaranteed not to raise, so the thread never dies silently."""
        try:
            self.poll_once()
        except Exception as e:
            logger.exception(f"[{self.source}] unexpected error in poll")
            self._on_failure(ScrapeResult(self.source, ok=False, error=f"internal error: {e}"))

    @staticmethod
    def _area_matches(area: str, names) -> bool:
        return any(re.search(rf'(?<!\w){re.escape(x)}(?!\w)', area or '', re.IGNORECASE) for x in names)

    def is_excluded(self, listing) -> bool:
        return self._area_matches(listing.area, self.exclude_areas)

    def is_included(self, listing) -> bool:
        return not self.include_areas or self._area_matches(listing.area, self.include_areas)

    def poll_once(self):
        result = self.scraper.fetch()
        new = []
        if result.ok:
            listings = [l for l in result.listings if self.is_included(l)]
            if self.include_areas:
                logger.debug(f"[{self.source}] {len(listings)} of {len(result.listings)} listings in wanted areas")
            new = self.detector.detect_new_listings(listings)
            if new:
                wanted = []
                for l in new:
                    if self.is_excluded(l):
                        logger.info(f"[{self.source}] skipped (area {l.area}): {l.street} {l.url}")
                        continue
                    logger.info(f"[{self.source}] NEW: {l.street}, {l.area} {l.rent_cost} {l.url}")
                    wanted.append(l)
                if wanted:
                    self.notifier.notify_listings(wanted)
                new = wanted
            else:
                logger.debug(f"[{self.source}] {len(result.listings)} listings, nothing new "
                             f"({result.elapsed:.2f}s)")
            self._on_success()
        else:
            self._on_failure(result)
        self.stats.record(result, len(new))

    # -- outcome handling --------------------------------------------------------

    @property
    def seconds_since_success(self) -> float:
        return self.clock() - self.last_success_at

    @property
    def stale_threshold(self) -> float:
        """How long without a success counts as stale for THIS source.

        A source polled every 5 minutes is not stale after 3; it is simply
        between polls. Allow three missed intervals plus any current backoff.
        """
        return max(float(self.health['stale_after_seconds']), 3 * self.interval + self.backoff)

    def _on_success(self):
        if self.consecutive_failures:
            logger.info(f"[{self.source}] recovered after {self.consecutive_failures} failures")
        if self.down:
            self.notifier.alert(f"{self.source}:recovered", f"{self.source} recovered",
                                f"{self.source} is polling normally again.")
            self.notifier.clear_alert(f"{self.source}:down")
            self.down = False
        self.consecutive_failures = 0
        self.backoff = 0.0
        self.last_success_at = self.clock()
        self.last_error = None

    def _on_failure(self, result: ScrapeResult):
        self.consecutive_failures += 1
        self.last_error = result.error
        status = result.status_code
        max_backoff = float(self.health['max_backoff_seconds'])
        if status == 429 or (status or 0) >= 500:
            # Server asked us to slow down: exponential backoff, generous cap.
            self.backoff = min(max_backoff, max(self.interval, self.backoff * 2))
        else:
            # Network blip or parse problem: modest backoff.
            self.backoff = min(max_backoff, self.interval * min(self.consecutive_failures, 6))
        logger.warning(f"[{self.source}] poll failed ({self.consecutive_failures}x): {result.error}; "
                       f"next try in {self.interval + self.backoff:.0f}s")

        blocked = status in self.health['block_status_codes']
        threshold = int(self.health['alert_after_consecutive_failures'])
        stale = self.seconds_since_success >= self.stale_threshold

        if result.shape_changed:
            title = f"{self.source}: page/API structure changed"
            body = (f"The scraper for {self.source} no longer recognises the response. This is what a "
                    f"login wall, a bot-challenge page or a site redesign looks like.\n"
                    f"Error: {result.error}\nURL: {self.scraper.url()}")
        elif blocked:
            title = f"{self.source}: HTTP {status} - we may be blocked"
            body = (f"{self.source} answered HTTP {status}. That is what a rate limit or IP ban looks like.\n"
                    f"URL: {self.scraper.url()}\nBacking off to {self.interval + self.backoff:.0f}s between tries.")
        elif self.consecutive_failures >= threshold or stale:
            title = f"{self.source}: down ({self.consecutive_failures} failures, " \
                    f"{self.seconds_since_success / 60:.0f} min since last success)"
            body = f"Last error: {result.error}\nURL: {self.scraper.url()}"
        else:
            return

        # One key per source: the cooldown turns repeated failures into hourly reminders.
        self.down = True
        self.notifier.alert(f"{self.source}:down", title, body)


# --------------------------------------------------------------------------
# Supervisor: restarts dead pollers, detects stale ones, pings heartbeat
# --------------------------------------------------------------------------

class Supervisor:
    def __init__(self, make_poller: Callable[[str], SourcePoller], config: dict,
                 notifier: Notifier, tz, clock: Callable[[], float] = time.monotonic):
        self.make_poller = make_poller
        self.config = config
        self.notifier = notifier
        self.tz = tz
        self.clock = clock
        self.health = config['health']
        self.pollers: Dict[str, SourcePoller] = {}
        self.last_heartbeat = 0.0
        self.restarts = 0

    def start(self, names: List[str]):
        for name in names:
            p = self.make_poller(name)
            self.pollers[name] = p
            p.start()

    def check(self) -> bool:
        """Restart dead pollers, alert on stale ones. Returns overall health."""
        healthy = True
        in_window = is_within_window(self.config, datetime.now(self.tz))

        for name, p in list(self.pollers.items()):
            if not p.is_alive():
                healthy = False
                self.restarts += 1
                logger.error(f"[{name}] poller thread died; restarting")
                self.notifier.alert(f"{name}:crashed", f"{name}: poller thread died, restarting",
                                    f"Last error: {p.last_error}")
                fresh = self.make_poller(name)
                self.pollers[name] = fresh
                fresh.start()
                continue

            if in_window and p.seconds_since_success >= p.stale_threshold:
                healthy = False
                if not p.down:
                    p.down = True
                minutes = p.seconds_since_success / 60
                self.notifier.alert(f"{name}:down", f"{name}: no successful poll for {minutes:.0f} min",
                                    f"Last error: {p.last_error}\nURL: {p.scraper.url()}")

        self.heartbeat(healthy)
        return healthy

    def heartbeat(self, healthy: bool):
        url = self.health.get('heartbeat_url')
        if not url or self.clock() - self.last_heartbeat < 60:
            return
        self.last_heartbeat = self.clock()
        target = url if healthy else url.rstrip('/') + '/fail'
        detail = "" if healthy else "\n".join(
            f"{n}: {p.last_error or 'stale'}" for n, p in self.pollers.items() if p.down or not p.is_alive())
        try:
            requests.post(target, data=detail.encode('utf-8'), timeout=10)
        except requests.RequestException as e:
            logger.warning(f"heartbeat ping failed: {e}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def send_test_notification(config_path: str = 'config.yaml') -> bool:
    """Send a sample listing through every enabled channel, synchronously."""
    from .models import RentalListing

    config = load_config(config_path)
    notifier = Notifier(config['notifications'], config['health']['alert_cooldown_seconds'])
    if not notifier.enabled_channels:
        logger.error("No notification channels enabled in config; nothing to test")
        return False

    sample = RentalListing(
        area="Solna", street="Testgatan 1 (this is a test)", number_of_rooms="2 rok",
        rent_cost="11 545 kr", size="68 kvm", url="https://wahlinfastigheter.se/hyr-av-oss/lediga-objekt/",
        source="test", key="test", published_until="2026-12-31 23:59", lottery=True, move_in="2027-01-01",
    )
    logger.info(f"Sending test notification via: {', '.join(c.name for c in notifier.enabled_channels)}")
    ok = notifier.send_now(('listings', [sample]))
    logger.info("Test notification sent" if ok else "Test notification FAILED on every channel")
    return ok


def maybe_send_summary(config, stats: Stats, detector: ChangeDetector, notifier: Notifier, tz):
    now = datetime.now(tz)
    if stats.summary_sent and now.date() != stats.date:
        logger.info("New day, resetting stats")
        stats.reset()
        return
    if stats.summary_sent or now.time() < dt_time.fromisoformat(config['summary_time']):
        return

    snap = stats.snapshot()
    day_start = datetime.combine(now.date(), dt_time.min)
    snap['seen_today'] = detector.db.listings_first_seen_since(day_start)
    logger.info("Sending daily summary...")
    notifier.daily_summary(snap)
    stats.summary_sent = True

    if config['backup']['enabled']:
        path = detector.db.backup_to(config['backup']['dir'], config['backup']['keep'])
        if path:
            logger.info(f"Database backed up to {path}")

    if config['cleanup_days'] > 0:
        cleaned = detector.cleanup_old_listings(config['cleanup_days'])
        if cleaned:
            logger.info(f"Cleaned {cleaned} listings not seen for {config['cleanup_days']} days")


def main(config_path: str = 'config.yaml'):
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    config = load_config(config_path)
    tz = pytz.timezone(config['timezone'])
    logger.info("Config loaded")

    detector = ChangeDetector(config['database'], cross_source_days=config['dedupe_days'])
    notifier = Notifier(config['notifications'], config['health']['alert_cooldown_seconds'])
    stats = Stats(tz)

    enabled = []
    for name, s in config['sources'].items():
        if not s['enabled']:
            continue
        if name not in SCRAPERS:
            logger.error(f"Unknown source '{name}' (known: {', '.join(SCRAPERS)})")
            continue
        enabled.append(name)
    if not enabled:
        logger.error("No sources enabled")
        sys.exit(1)

    def make_poller(name: str) -> SourcePoller:
        return SourcePoller(name, SCRAPERS[name](), config['sources'][name]['interval_seconds'],
                            config, detector, notifier, stats, tz)

    supervisor = Supervisor(make_poller, config, notifier, tz)

    logger.info(f"Known listings: {detector.get_known_count()}")
    notifier.start()
    supervisor.start(enabled)
    logger.info("Started pollers: " + ", ".join(
        f"{n}@{config['sources'][n]['interval_seconds']}s" for n in enabled)
        + (f". Heartbeat: {config['health']['heartbeat_url']}" if config['health']['heartbeat_url'] else "")
        + ". Ctrl+C to stop.")

    while not stop_event.is_set():
        try:
            supervisor.check()
            maybe_send_summary(config, stats, detector, notifier, tz)
        except Exception as e:
            logger.exception(f"Error in supervisor loop: {e}")
        # Short waits keep Ctrl+C responsive on Windows, where a blocking
        # Event.wait() is not interrupted by signals.
        for _ in range(30):
            if stop_event.wait(1):
                break

    for p in supervisor.pollers.values():
        p.join(timeout=5)
    notifier.stop()
    logger.info("Stopped")
