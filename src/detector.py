"""Detects new rental listings."""

import logging
from typing import List

from .models import RentalListing
from .database import RentalDatabase

logger = logging.getLogger(__name__)


class ChangeDetector:
    def __init__(self, db_path: str = "data/rentals.db"):
        self.db = RentalDatabase(db_path)
        self.known_urls = self.db.get_known_urls()

    def detect_new_listings(self, listings: List[RentalListing]) -> List[RentalListing]:
        """Returns list of new listings."""
        new = []
        for listing in listings:
            if listing.url and listing.url not in self.known_urls:
                if self.db.add_listing(listing):
                    new.append(listing)
                    self.known_urls.add(listing.url)
            else:
                self.db.add_listing(listing)
        return new

    def get_known_count(self) -> int:
        return len(self.known_urls)

    def cleanup_old_listings(self, days: int = 14) -> int:
        deleted = self.db.cleanup_old(days)
        self.known_urls = self.db.get_known_urls()
        return deleted
