"""SQLite storage for rental listings.

Schema v2 keys rows by `key` (a stable identity chosen by the scraper) instead
of by URL, so a re-publication of the same apartment can be reported again.
Existing v1 databases (url primary key) are migrated in place on startup.
"""

import sqlite3
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Set

from .models import RentalListing

logger = logging.getLogger(__name__)


class RentalDatabase:
    def __init__(self, db_path: str = "data/rentals.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            columns = {row['name'] for row in conn.execute("PRAGMA table_info(listings)")}
            if columns and 'key' not in columns:
                self._migrate_v1(conn)
            conn.execute('''
                CREATE TABLE IF NOT EXISTS listings (
                    key TEXT PRIMARY KEY,
                    url TEXT,
                    source TEXT,
                    object_id TEXT,
                    area TEXT NOT NULL,
                    street TEXT NOT NULL,
                    number_of_rooms TEXT NOT NULL,
                    rent_cost TEXT NOT NULL,
                    size TEXT NOT NULL,
                    published_until TEXT,
                    lottery INTEGER,
                    move_in TEXT,
                    first_seen TIMESTAMP NOT NULL,
                    last_seen TIMESTAMP NOT NULL
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_first_seen ON listings(first_seen)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_last_seen ON listings(last_seen)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_object_id ON listings(object_id)')
            self._backfill_object_ids(conn)

    def _backfill_object_ids(self, conn: sqlite3.Connection):
        """Rows migrated from v1 have no object_id. Derive it from the URL where
        possible so cross-source de-duplication also covers old rows."""
        from .scraper import WahlinRentalScraper  # local import: avoid a circular import at module load
        rows = conn.execute(
            "SELECT key, url FROM listings WHERE object_id IS NULL AND url LIKE '%wahlinfastigheter.se/lediga-objekt/%'"
        ).fetchall()
        updated = 0
        for r in rows:
            m = WahlinRentalScraper.OBJECT_ID_RE.search(r['url'] or '')
            if m:
                conn.execute('UPDATE listings SET object_id = ? WHERE key = ?', (m.group(1), r['key']))
                updated += 1
        if updated:
            logger.info(f"Backfilled object_id on {updated} listings")

    def _migrate_v1(self, conn: sqlite3.Connection):
        logger.info("Migrating listings table from v1 (url key) to v2 (stable key)")
        conn.execute('ALTER TABLE listings RENAME TO listings_v1')
        conn.execute('''
            CREATE TABLE listings (
                key TEXT PRIMARY KEY,
                url TEXT,
                source TEXT,
                object_id TEXT,
                area TEXT NOT NULL,
                street TEXT NOT NULL,
                number_of_rooms TEXT NOT NULL,
                rent_cost TEXT NOT NULL,
                size TEXT NOT NULL,
                published_until TEXT,
                lottery INTEGER,
                move_in TEXT,
                first_seen TIMESTAMP NOT NULL,
                last_seen TIMESTAMP NOT NULL
            )
        ''')
        conn.execute('''
            INSERT OR IGNORE INTO listings
                (key, url, source, area, street, number_of_rooms, rent_cost, size, first_seen, last_seen)
            SELECT url, url, source, area, street, number_of_rooms, rent_cost, size, first_seen, last_seen
            FROM listings_v1
        ''')
        conn.execute('DROP TABLE listings_v1')

    def upsert(self, listing: RentalListing) -> bool:
        """Insert the listing or refresh last_seen. Returns True if it was new."""
        if not listing.key:
            return False
        try:
            with self._lock, self._connect() as conn:
                now = datetime.now().isoformat(sep=' ')
                existing = conn.execute(
                    'SELECT key FROM listings WHERE key = ?', (listing.key,)
                ).fetchone()

                if existing:
                    conn.execute(
                        'UPDATE listings SET last_seen = ?, published_until = COALESCE(?, published_until) WHERE key = ?',
                        (now, listing.published_until, listing.key)
                    )
                    return False

                conn.execute('''
                    INSERT INTO listings (key, url, source, object_id, area, street, number_of_rooms,
                                          rent_cost, size, published_until, lottery, move_in, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (listing.key, listing.url, listing.source, listing.object_id, listing.area,
                      listing.street, listing.number_of_rooms, listing.rent_cost, listing.size,
                      listing.published_until,
                      None if listing.lottery is None else int(listing.lottery),
                      listing.move_in, now, now))
                return True
        except Exception as e:
            logger.error(f"Database error: {e}")
            return False

    # Backwards-compatible name.
    add_listing = upsert

    def get_known_keys(self) -> Set[str]:
        try:
            with self._connect() as conn:
                return {row['key'] for row in conn.execute('SELECT key FROM listings')}
        except Exception as e:
            logger.error(f"Database error: {e}")
            return set()

    get_known_urls = get_known_keys

    def recently_seen_object(self, object_id: str, days: int, exclude_source: Optional[str] = None) -> bool:
        """True if another source already reported this object number recently."""
        if not object_id:
            return False
        try:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat(sep=' ')
            with self._connect() as conn:
                row = conn.execute(
                    'SELECT 1 FROM listings WHERE object_id = ? AND first_seen >= ? '
                    'AND (? IS NULL OR source != ?) LIMIT 1',
                    (object_id, cutoff, exclude_source, exclude_source)
                ).fetchone()
                return row is not None
        except Exception as e:
            logger.error(f"Database error: {e}")
            return False

    def listings_first_seen_since(self, since: datetime) -> List[dict]:
        """Listings discovered since `since`, with how long they have been visible."""
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    'SELECT source, street, area, url, first_seen, last_seen FROM listings '
                    'WHERE first_seen >= ? ORDER BY first_seen', (since.isoformat(sep=' '),)
                ).fetchall()
            out = []
            for r in rows:
                first = datetime.fromisoformat(r['first_seen'])
                last = datetime.fromisoformat(r['last_seen'])
                out.append({**dict(r), 'visible_minutes': (last - first).total_seconds() / 60})
            return out
        except Exception as e:
            logger.error(f"Database error: {e}")
            return []

    def cleanup_old(self, days: int = 14) -> int:
        """Remove listings that have not been seen for N days.

        Deleting by last_seen (not first_seen) means a listing that stays
        published for longer than N days is not re-reported as new.
        """
        try:
            cutoff = (datetime.now() - timedelta(days=days)).isoformat(sep=' ')
            with self._lock, self._connect() as conn:
                cursor = conn.execute('DELETE FROM listings WHERE last_seen < ?', (cutoff,))
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            return 0
