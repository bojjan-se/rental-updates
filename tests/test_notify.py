import time

from src.notify import (Notifier, NtfyChannel, listings_text, listing_headline, listing_details,
                        nice_deadline)
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
    assert text.splitlines()[0] == "Solna · 2 rok · 68 kvm · 11 545 kr"
    assert "Apply by Wed 16 Sep 00:00 (lottery)" in text
    assert "https://x/a" in text
    assert "N/A" not in text


def test_headline_skips_missing_fields():
    l = RentalListing(area="Solna", street="Lediga garageplatser", number_of_rooms="N/A",
                      rent_cost="N/A", size="N/A", url="https://x/g", key="g", lottery=True)
    assert listing_headline(l) == "Solna"
    assert listing_details(l) == "Lediga garageplatser\nLottery\nhttps://x/g"


def test_nice_deadline_formats():
    assert nice_deadline("2026-09-19 23:59") == "Sat 19 Sep 23:59"
    assert nice_deadline("2026-09-19") == "Sat 19 Sep"
    assert nice_deadline("soon") == "soon"
    assert nice_deadline(None) is None


def test_ntfy_sends_one_notification_per_listing(monkeypatch):
    posts = []

    class R:
        def raise_for_status(self):
            pass
    monkeypatch.setattr("src.notify.requests.post",
                        lambda url, data, headers, timeout: posts.append((url, data, headers)) or R())
    ch = NtfyChannel({'enabled': True, 'topic': 't', 'server': 'https://ntfy.example'})
    assert ch.send_listings([make_listing("a"), make_listing("b")]) is True
    assert len(posts) == 2
    url, data, headers = posts[0]
    assert url == "https://ntfy.example/t"
    assert headers['Title'] == "Solna · 2 rok · 68 kvm · 11 545 kr"
    assert headers['Click'] == "https://x/a" and headers['Actions'].endswith("https://x/a")
    assert headers['Priority'] == "urgent"
    assert data.decode('utf-8').splitlines() == ["Street a", "Apply by Wed 16 Sep 00:00 (lottery)", "https://x/a"]


def test_disabled_channels_with_missing_config_do_not_crash():
    n = Notifier({'ntfy': {'enabled': True}, 'telegram': {'enabled': True, 'bot_token': 'x'}})
    assert n.enabled_channels == []
