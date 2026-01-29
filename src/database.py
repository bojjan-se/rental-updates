"""SQLite database for rental listings."""

import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

from .models import RentalListing

logger = logging.getLogger(__name__)


class RentalDatabase:
    def __init__(self, db_path: str = "data/rentals.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS listings (
                    url TEXT PRIMARY KEY,
                    source TEXT,
                    area TEXT NOT NULL,
                    street TEXT NOT NULL,
                    number_of_rooms TEXT NOT NULL,
                    rent_cost TEXT NOT NULL,
                    size TEXT NOT NULL,
                    first_seen TIMESTAMP NOT NULL,
                    last_seen TIMESTAMP NOT NULL
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_first_seen ON listings(first_seen)')

    def add_listing(self, listing: RentalListing) -> bool:
        """Add listing. Returns True if new, False if existing."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                now = datetime.now()

                existing = conn.execute(
                    'SELECT url FROM listings WHERE url = ?', (listing.url,)
                ).fetchone()

                if existing:
                    conn.execute(
                        'UPDATE listings SET last_seen = ? WHERE url = ?',
                        (now, listing.url)
                    )
                    return False

                conn.execute('''
                    INSERT INTO listings (url, source, area, street, number_of_rooms, rent_cost, size, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (listing.url, listing.source, listing.area, listing.street,
                      listing.number_of_rooms, listing.rent_cost, listing.size, now, now))
                return True

        except Exception as e:
            logger.error(f"Database error: {e}")
            return False

    def get_known_urls(self) -> set:
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute('SELECT url FROM listings').fetchall()
                return {row[0] for row in rows}
        except Exception as e:
            logger.error(f"Database error: {e}")
            return set()

    def cleanup_old(self, days: int = 14) -> int:
        """Remove listings older than N days."""
        try:
            cutoff = datetime.now() - timedelta(days=days)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute('DELETE FROM listings WHERE first_seen < ?', (cutoff,))
                return cursor.rowcount
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            return 0
