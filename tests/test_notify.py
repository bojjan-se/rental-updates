import time

from src.notify import Notifier, listings_text
from src.models import RentalListing


class FakeChannel:
    name = "fake"
    enabled = True

    def __init__(self):
        self.calls = []

    def send_listings(self, listings):
        self.calls.append(('listings', [l.key for l in listings]))
        return True

    def send_text(self, title, body):
        self.calls.append(('text', title))
        return True

    def send_summary(self, stats):
        self.calls.append(('summary', stats.get('date')))
        return True


def make_listing(key):
    return RentalListing(area="Solna", street=f"Street {key}", number_of_rooms="2 rok",
                         rent_cost="11 545 kr", size="68 kvm", url=f"https://x/{key}",
                         source="wahlin_arena", key=key, published_until="2026-09-16 00:00",
                         lottery=True, move_in="2026-10-01")


def notifier_with_fake(cooldown=3600):
    n = Notifier({}, alert_cooldown_seconds=cooldown)
    fake = FakeChannel()
    n.enabled_channels = [fake]
    return n, fake


def test_listings_are_dispatched_from_worker_thread():
    n, fake = notifier_with_fake()
    n.start()
    n.notify_listings([make_listing("a"), make_listing("b")])
    n.notify_listings([])  # ignored
    n.stop()
    assert fake.calls == [('listings', ['a', 'b'])]
    assert n.sent == 1 and n.failed == 0


def test_alert_cooldown_and_clear():
    n, fake = notifier_with_fake(cooldown=3600)
    n.alert("wallfast:failing", "t1", "b")
    n.alert("wallfast:failing", "t2", "b")   # suppressed by cooldown
    n.alert("wahlin:failing", "t3", "b")     # different key, goes through
    n.clear_alert("wallfast:failing")
    n.alert("wallfast:failing", "t4", "b")   # allowed again after clear
    n.start(); n.stop()
    assert [c[1] for c in fake.calls] == ["t1", "t3", "t4"]


def test_no_channels_counts_as_failure():
    n = Notifier({'email': {'enabled': False}})
    assert n.enabled_channels == []
    assert n.send_now(('listings', [make_listing("a")])) is False


def test_channel_exception_does_not_kill_worker():
    n, fake = notifier_with_fake()

    class Boom(FakeChannel):
        def send_listings(self, listings):
            raise RuntimeError("smtp down")
    n.enabled_channels = [Boom(), fake]
    n.start()
    n.notify_listings([make_listing("a")])
    n.stop()
    assert fake.calls == [('listings', ['a'])]
    assert n.sent == 1  # at least one channel succeeded


def test_listings_text_includes_deadline_and_url():
    text = listings_text([make_listing("a")])
    assert "apply by 2026-09-16 00:00" in text
    assert "lottery" in text
    assert "https://x/a" in text
    assert "N/A" not in text


def test_disabled_channels_with_missing_config_do_not_crash():
    n = Notifier({'ntfy': {'enabled': True}, 'telegram': {'enabled': True, 'bot_token': 'x'}})
    assert n.enabled_channels == []
