import logging
from typing import List
from .models import RentalListing
from .database import RentalDatabase

logger = logging.getLogger(__name__)

class ChangeDetector:
    """Tracks known listings and detects new ones using SQLite database"""

    def __init__(self, db_path: str = "data/rentals.db"):
        self.database = RentalDatabase(db_path)
        self.known_urls = self.database.get_known_urls()
        logger.info(f"Loaded {len(self.known_urls)} known listing URLs from database")

    def detect_new_listings(self, current_listings: List[RentalListing]) -> List[RentalListing]:
        """Detect which listings are new compared to known ones"""
        new_listings = []

        for listing in current_listings:
            if listing.url and listing.url not in self.known_urls:
                # Add to database and mark as new
                if self.database.add_listing(listing):
                    new_listings.append(listing)
                    self.known_urls.add(listing.url)
            else:
                # Update last_seen timestamp for existing listings
                self.database.add_listing(listing)

        logger.info(f"Detected {len(new_listings)} new listings out of {len(current_listings)} total")
        return new_listings

    def get_known_count(self) -> int:
        """Get count of known listings"""
        return len(self.known_urls)

    def get_recent_listings(self, days: int = 7) -> List[RentalListing]:
        """Get listings from the last N days"""
        return self.database.get_recent_listings(days)

    def cleanup_old_listings(self, days_to_keep: int = 14) -> int:
        """Remove listings older than specified days"""
        deleted_count = self.database.cleanup_old_listings(days_to_keep)
        # Refresh known URLs after cleanup
        self.known_urls = self.database.get_known_urls()
        return deleted_count

    def get_stats(self) -> dict:
        """Get database statistics"""
        return self.database.get_stats()

    def optimize_db(self):
        """Optimize database performance"""
        self.database.optimize_db()
