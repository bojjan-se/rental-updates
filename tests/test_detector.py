import sqlite3
from datetime import datetime, timedelta

from src.detector import ChangeDetector
from src.database import RentalDatabase
from src.models import RentalListing
from src.scheduler import normalize_config


def listing(key, source="wahlin_arena", object_id=None, url=None):
    return RentalListing(area="Märsta", street=f"Street {key}", number_of_rooms="2 rok",
                         rent_cost="10 000 kr", size="50 kvm", url=url or f"https://x/{key}",
                         source=source, key=key, object_id=object_id)


def test_new_then_known(tmp_path):
    d = ChangeDetector(str(tmp_path / "t.db"))
    assert [l.key for l in d.detect_new_listings([listing("a"), listing("b")])] == ["a", "b"]
    assert d.detect_new_listings([listing("a"), listing("b"), listing("c")]) and \
        [l.key for l in d.detect_new_listings([listing("a")])] == []
    assert d.get_known_count() == 3


def test_survives_restart(tmp_path):
    path = str(tmp_path / "t.db")
    ChangeDetector(path).detect_new_listings([listing("a")])
    d2 = ChangeDetector(path)
    assert d2.detect_new_listings([listing("a")]) == []


def test_republication_with_new_key_is_reported(tmp_path):
    d = ChangeDetector(str(tmp_path / "t.db"))
    first = listing("wahlin:502-204:2026-09-01", object_id="502-204")
    again = listing("wahlin:502-204:2026-10-01", object_id="502-204")
    assert d.detect_new_listings([first])
    assert d.detect_new_listings([again])  # same source, new publication -> report


def test_cross_source_duplicate_suppressed(tmp_path):
    d = ChangeDetector(str(tmp_path / "t.db"))
    arena = listing("wahlin:502-204:2026-09-16", source="wahlin_arena", object_id="502-204")
    web = listing("https://wahlinfastigheter.se/lediga-objekt/sodergatan-1-f-502-204/",
                  source="wahlin", object_id="502-204")
    assert d.detect_new_listings([arena])
    assert d.detect_new_listings([web]) == []
    # ...but it is recorded, so it will not be reported later either
    assert d.detect_new_listings([web]) == []


def test_cross_source_only_suppresses_recent(tmp_path):
    path = str(tmp_path / "t.db")
    d = ChangeDetector(path, cross_source_days=14)
    web = listing("https://wahlinfastigheter.se/lediga-objekt/x-502-204/", source="wahlin", object_id="502-204")
    d.detect_new_listings([web])
    old = (datetime.now() - timedelta(days=30)).isoformat(sep=' ')
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE listings SET first_seen = ?, last_seen = ?", (old, old))
    arena = listing("wahlin:502-204:2026-10-01", source="wahlin_arena", object_id="502-204")
    assert d.detect_new_listings([arena])


def test_cleanup_uses_last_seen(tmp_path):
    path = str(tmp_path / "t.db")
    d = ChangeDetector(path)
    d.detect_new_listings([listing("old"), listing("stillup")])
    old = (datetime.now() - timedelta(days=30)).isoformat(sep=' ')
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE listings SET first_seen = ?", (old,))          # both first seen long ago
        conn.execute("UPDATE listings SET last_seen = ? WHERE key = 'old'", (old,))
    assert d.cleanup_old_listings(14) == 1
    assert d.detect_new_listings([listing("stillup")]) == []  # still known: not re-reported
    assert d.detect_new_listings([listing("old")])            # forgotten: reported if it comes back


def test_v1_database_is_migrated(tmp_path):
    path = tmp_path / "v1.db"
    with sqlite3.connect(path) as conn:
        conn.execute('''CREATE TABLE listings (url TEXT PRIMARY KEY, source TEXT, area TEXT NOT NULL,
                        street TEXT NOT NULL, number_of_rooms TEXT NOT NULL, rent_cost TEXT NOT NULL,
                        size TEXT NOT NULL, first_seen TIMESTAMP NOT NULL, last_seen TIMESTAMP NOT NULL)''')
        now = datetime.now().isoformat(sep=' ')
        conn.execute("INSERT INTO listings VALUES (?,?,?,?,?,?,?,?,?)",
                     ("https://wallfast.com/a", "wallfast", "Solna", "A", "N/A", "N/A", "N/A", now, now))
    db = RentalDatabase(str(path))
    assert db.get_known_keys() == {"https://wallfast.com/a"}
    d = ChangeDetector(str(path))
    assert d.detect_new_listings([listing("https://wallfast.com/a", source="wallfast")]) == []


def test_visibility_report(tmp_path):
    d = ChangeDetector(str(tmp_path / "t.db"))
    d.detect_new_listings([listing("a")])
    rows = d.db.listings_first_seen_since(datetime.now() - timedelta(minutes=1))
    assert len(rows) == 1 and rows[0]['visible_minutes'] >= 0


def test_v1_config_is_normalized():
    cfg = normalize_config({
        'schedule': {'timezone': 'Europe/Stockholm', 'start': '00:00', 'end': '23:59', 'interval_minutes': 5},
        'email': {'enabled': True, 'sender': 's', 'password': 'p', 'recipient': 'r'},
        'scrapers': {'wahlin': True, 'wallfast': False},
    })
    assert set(cfg['sources']) == {'wahlin_arena', 'wahlin'}
    assert cfg['sources']['wahlin_arena']['interval_seconds'] == 20
    assert cfg['notifications']['email']['sender'] == 's'
    assert cfg['timezone'] == 'Europe/Stockholm'


def test_v2_config_is_normalized():
    cfg = normalize_config({'sources': {'wallfast': {'interval_seconds': 15}, 'wahlin': False}})
    assert cfg['sources'] == {'wallfast': {'enabled': True, 'interval_seconds': 15},
                              'wahlin': {'enabled': False, 'interval_seconds': 300}}
    assert cfg['health']['alert_after_consecutive_failures'] == 5
    assert cfg['health']['block_status_codes'] == [401, 403, 429]
    assert cfg['health']['heartbeat_url'] == ''
