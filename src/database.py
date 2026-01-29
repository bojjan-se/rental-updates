import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional
import logging
from pathlib import Path

from .models import RentalListing

logger = logging.getLogger(__name__)

class RentalDatabase:
    """SQLite database manager for rental listings"""

    def __init__(self, db_path: str = "data/rentals.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database tables"""
        with sqlite3.connect(self.db_path) as conn:
            # Check if we need to migrate the schema
            cursor = conn.execute("PRAGMA table_info(listings)")
            columns = [row[1] for row in cursor.fetchall()]

            if 'source' not in columns:
                logger.info("Migrating database schema to include source column...")
                try:
                    conn.execute('ALTER TABLE listings ADD COLUMN source TEXT')
                    logger.info("Database schema migrated successfully")
                except sqlite3.OperationalError:
                    logger.info("Source column already exists or migration not needed")

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

            # Create indexes for faster queries
            conn.execute('CREATE INDEX IF NOT EXISTS idx_first_seen ON listings(first_seen)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_area ON listings(area)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_source ON listings(source)')

            logger.info("Database initialized successfully")

    def add_listing(self, listing: RentalListing) -> bool:
        """Add a new listing to the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                now = datetime.now()

                # Check if listing already exists
                existing = conn.execute(
                    'SELECT url FROM listings WHERE url = ?',
                    (listing.url,)
                ).fetchone()

                if existing:
                    # Update last_seen timestamp
                    conn.execute(
                        'UPDATE listings SET last_seen = ? WHERE url = ?',
                        (now, listing.url)
                    )
                    logger.debug(f"Updated existing listing: {listing.url}")
                    return False  # Not new
                else:
                    # Insert new listing
                    conn.execute('''
                        INSERT INTO listings (url, source, area, street, number_of_rooms, rent_cost, size, first_seen, last_seen)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        listing.url,
                        listing.source,
                        listing.area,
                        listing.street,
                        listing.number_of_rooms,
                        listing.rent_cost,
                        listing.size,
                        now,
                        now
                    ))
                    logger.info(f"Added new listing to database: {listing.street}")
                    return True  # New listing

        except Exception as e:
            logger.error(f"Error adding listing to database: {e}")
            return False

    def get_known_urls(self) -> set:
        """Get all known listing URLs"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                urls = conn.execute('SELECT url FROM listings').fetchall()
                return {row[0] for row in urls}
        except Exception as e:
            logger.error(f"Error getting known URLs: {e}")
            return set()

    def get_listing_by_url(self, url: str) -> Optional[RentalListing]:
        """Get a listing by URL"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute('''
                    SELECT url, source, area, street, number_of_rooms, rent_cost, size, first_seen, last_seen
                    FROM listings WHERE url = ?
                ''', (url,)).fetchone()

                if row:
                    return RentalListing(
                        url=row[0],
                        source=row[1],
                        area=row[2],
                        street=row[3],
                        number_of_rooms=row[4],
                        rent_cost=row[5],
                        size=row[6],
                        scraped_at=datetime.fromisoformat(row[7]) if row[7] else None
                    )
        except Exception as e:
            logger.error(f"Error getting listing by URL: {e}")

        return None

    def get_recent_listings(self, days: int = 7) -> List[RentalListing]:
        """Get listings from the last N days"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days)
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute('''
                    SELECT url, source, area, street, number_of_rooms, rent_cost, size, first_seen, last_seen
                    FROM listings
                    WHERE first_seen >= ?
                    ORDER BY first_seen DESC
                ''', (cutoff_date,)).fetchall()

                listings = []
                for row in rows:
                    listings.append(RentalListing(
                        url=row[0],
                        source=row[1],
                        area=row[2],
                        street=row[3],
                        number_of_rooms=row[4],
                        rent_cost=row[5],
                        size=row[6],
                        scraped_at=datetime.fromisoformat(row[7]) if row[7] else None
                    ))

                return listings

        except Exception as e:
            logger.error(f"Error getting recent listings: {e}")
            return []

    def count_old_listings(self, days_to_keep: int = 14) -> int:
        """Count listings older than specified days (without deleting)"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'SELECT COUNT(*) FROM listings WHERE first_seen < ?',
                    (cutoff_date,)
                )
                count = cursor.fetchone()[0]
                return count

        except Exception as e:
            logger.error(f"Error counting old listings: {e}")
            return 0

    def cleanup_old_listings(self, days_to_keep: int = 14) -> int:
        """Remove listings older than specified days"""
        try:
            cutoff_date = datetime.now() - timedelta(days=days_to_keep)
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    'DELETE FROM listings WHERE first_seen < ?',
                    (cutoff_date,)
                )
                deleted_count = cursor.rowcount
                logger.info(f"Cleaned up {deleted_count} old listings (older than {days_to_keep} days)")
                return deleted_count

        except Exception as e:
            logger.error(f"Error cleaning up old listings: {e}")
            return 0

    def get_stats(self) -> dict:
        """Get database statistics"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Total listings
                total = conn.execute('SELECT COUNT(*) FROM listings').fetchone()[0]

                # Recent listings (last 7 days)
                week_ago = datetime.now() - timedelta(days=7)
                recent = conn.execute(
                    'SELECT COUNT(*) FROM listings WHERE first_seen >= ?',
                    (week_ago,)
                ).fetchone()[0]

                # Oldest listing
                oldest = conn.execute(
                    'SELECT MIN(first_seen) FROM listings'
                ).fetchone()[0]

                # Newest listing
                newest = conn.execute(
                    'SELECT MAX(first_seen) FROM listings'
                ).fetchone()[0]

                # Stats by source
                source_stats = conn.execute('''
                    SELECT source, COUNT(*) FROM listings
                    WHERE source IS NOT NULL
                    GROUP BY source
                ''').fetchall()

                return {
                    'total_listings': total,
                    'recent_listings_7d': recent,
                    'oldest_listing': oldest,
                    'newest_listing': newest,
                    'listings_by_source': dict(source_stats)
                }

        except Exception as e:
            logger.error(f"Error getting database stats: {e}")
            return {}

    def optimize_db(self):
        """Optimize database performance"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute('VACUUM')
                conn.execute('ANALYZE')
            logger.info("Database optimized")
        except Exception as e:
            logger.error(f"Error optimizing database: {e}")
