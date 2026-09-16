"""Failure handling: a ban, a dead site or a dead thread must always raise an alert."""

import pytz

from src.scheduler import SourcePoller, Supervisor, Stats, normalize_config
from src.scraper import ScrapeResult
from src.models import RentalListing


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class FakeScraper:
    SOURCE_NAME = "fake"

    def __init__(self, results):
        self.results = list(results)

    def url(self):
        return "https://example.test/list"

    def fetch(self):
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeDetector:
    def __init__(self):
        self.seen = set()

    def detect_new_listings(self, listings):
        new = [l for l in listings if l.key not in self.seen]
        self.seen.update(l.key for l in new)
        return new


class FakeNotifier:
    def __init__(self):
        self.alerts = []      # (key, title)
        self.listings = []
        self.cleared = []

    def alert(self, key, title, body):
        self.alerts.append((key, title))

    def clear_alert(self, key):
        self.cleared.append(key)

    def notify_listings(self, listings):
        self.listings.append([l.key for l in listings])


def ok(*keys):
    return ScrapeResult("fake", ok=True, listings=[
        RentalListing(area="A", street=k, number_of_rooms="1", rent_cost="1", size="1", url=f"u/{k}", key=k)
        for k in keys])


def fail(error="boom", status=None, shape=False):
    return ScrapeResult("fake", ok=False, error=error, status_code=status, shape_changed=shape)


def make_poller(results, clock=None, health_overrides=None):
    cfg = normalize_config({'health': health_overrides or {}})
    clock = clock or FakeClock()
    notifier = FakeNotifier()
    tz = pytz.timezone("Europe/Stockholm")
    p = SourcePoller("fake", FakeScraper(results), 20, cfg, FakeDetector(), notifier, Stats(tz), tz, clock=clock)
    return p, notifier, clock


def test_new_listings_are_notified_immediately_and_once():
    p, n, _ = make_poller([ok("a"), ok("a", "b")])
    p.tick(); p.tick()
    assert n.listings == [["a"], ["b"]]
    assert n.alerts == []


def test_block_status_alerts_on_first_occurrence():
    p, n, _ = make_poller([fail("HTTP 403", status=403)])
    p.tick()
    assert len(n.alerts) == 1
    key, title = n.alerts[0]
    assert key == "fake:down" and "403" in title and "blocked" in title
    assert p.down


def test_rate_limit_backs_off_exponentially_and_alerts():
    p, n, _ = make_poller([fail("HTTP 429", status=429), fail("HTTP 429", status=429), fail("HTTP 429", status=429)])
    p.tick(); b1 = p.backoff
    p.tick(); b2 = p.backoff
    p.tick(); b3 = p.backoff
    assert b1 == 20 and b2 == 40 and b3 == 80
    assert n.alerts and "429" in n.alerts[0][1]


def test_generic_failures_alert_after_threshold():
    p, n, _ = make_poller([fail("timeout")] * 5, health_overrides={'alert_after_consecutive_failures': 5,
                                                                    'stale_after_seconds': 99999})
    for _ in range(4):
        p.tick()
    assert n.alerts == []
    p.tick()
    assert len(n.alerts) == 1 and n.alerts[0][0] == "fake:down"


def test_stale_source_alerts_even_below_failure_threshold():
    p, n, clock = make_poller([fail("timeout"), fail("timeout")],
                              health_overrides={'alert_after_consecutive_failures': 50, 'stale_after_seconds': 180})
    p.tick()
    assert n.alerts == []
    clock.advance(200)
    p.tick()
    assert len(n.alerts) == 1 and "min since last success" in n.alerts[0][1]


def test_shape_change_alerts_immediately():
    p, n, _ = make_poller([fail("unexpected structure: not JSON", shape=True)])
    p.tick()
    assert len(n.alerts) == 1 and "structure changed" in n.alerts[0][1]


def test_recovery_sends_all_clear_and_resets():
    p, n, _ = make_poller([fail("HTTP 403", status=403), ok("a")])
    p.tick(); p.tick()
    assert [k for k, _ in n.alerts] == ["fake:down", "fake:recovered"]
    assert n.cleared == ["fake:down"]
    assert not p.down and p.consecutive_failures == 0 and p.backoff == 0


def test_tick_survives_unexpected_exception():
    p, n, _ = make_poller([RuntimeError("bug in scraper"), ok("a")])
    p.tick()          # must not raise
    assert p.consecutive_failures == 1 and "internal error" in p.last_error
    p.tick()
    assert n.listings == [["a"]]


class DeadPoller:
    def __init__(self):
        self.last_error = "died"
        self.down = False
        self.started = False

    def is_alive(self):
        return False


class LivePoller:
    def __init__(self, seconds_since_success=0.0):
        self.seconds_since_success = seconds_since_success
        self.last_error = None
        self.down = False
        self.scraper = FakeScraper([])
        self.started = False

    def is_alive(self):
        return True

    def start(self):
        self.started = True


def test_supervisor_restarts_dead_poller_and_alerts():
    cfg = normalize_config({})
    n = FakeNotifier()
    made = []

    def factory(name):
        p = LivePoller()
        made.append(p)
        return p
    s = Supervisor(factory, cfg, n, pytz.timezone("Europe/Stockholm"), clock=FakeClock())
    s.pollers = {"wallfast": DeadPoller()}
    healthy = s.check()
    assert healthy is False
    assert n.alerts == [("wallfast:crashed", "wallfast: poller thread died, restarting")]
    assert made and made[0].started and s.pollers["wallfast"] is made[0]


def test_supervisor_flags_stale_poller():
    cfg = normalize_config({'health': {'stale_after_seconds': 180}})
    n = FakeNotifier()
    s = Supervisor(lambda name: LivePoller(), cfg, n, pytz.timezone("Europe/Stockholm"), clock=FakeClock())
    s.pollers = {"wahlin_arena": LivePoller(seconds_since_success=600), "wallfast": LivePoller()}
    assert s.check() is False
    assert [k for k, _ in n.alerts] == ["wahlin_arena:down"]
    assert s.pollers["wahlin_arena"].down is True


def test_supervisor_heartbeat_only_with_url(monkeypatch):
    calls = []
    monkeypatch.setattr("src.scheduler.requests.post", lambda url, **kw: calls.append(url))
    cfg = normalize_config({'health': {'heartbeat_url': 'https://hc-ping.com/abc'}})
    clock = FakeClock()
    s = Supervisor(lambda name: LivePoller(), cfg, FakeNotifier(), pytz.timezone("Europe/Stockholm"), clock=clock)
    s.pollers = {"wallfast": LivePoller()}
    s.check()
    assert calls == ["https://hc-ping.com/abc"]
    s.check()                                # within 60 s: no second ping
    assert len(calls) == 1
    clock.advance(61)
    s.pollers["wallfast"].seconds_since_success = 999
    s.check()
    assert calls[-1] == "https://hc-ping.com/abc/fail"

    cfg2 = normalize_config({})
    s2 = Supervisor(lambda name: LivePoller(), cfg2, FakeNotifier(), pytz.timezone("Europe/Stockholm"), clock=clock)
    s2.pollers = {"wallfast": LivePoller()}
    s2.check()
    assert len(calls) == 2                   # no heartbeat URL configured: nothing sent
