"""Detects new rental listings. Safe to call from several poller threads."""

import logging
import threading
from typing import List

from .models import RentalListing
from .database import RentalDatabase

logger = logging.getLogger(__name__)


class ChangeDetector:
    def __init__(self, db_path: str = "data/rentals.db", cross_source_days: int = 14):
        self.db = RentalDatabase(db_path)
        self.known_keys = self.db.get_known_keys()
        self.cross_source_days = cross_source_days
        self._lock = threading.Lock()

    def detect_new_listings(self, listings: List[RentalListing]) -> List[RentalListing]:
        """Record the listings and return the ones that should be reported.

        Callers must only pass listings from a *successful* fetch; an empty
        list from a failed fetch must never reach here, otherwise nothing
        is lost but nothing is learned either.
        """
        new = []
        with self._lock:
            for listing in listings:
                if not listing.key:
                    continue
                if listing.key in self.known_keys:
                    self.db.upsert(listing)
                    continue

                if not self.db.upsert(listing):
                    continue
                self.known_keys.add(listing.key)

                # The same apartment can appear via two sources (e.g. Wåhlin's
                # portal and the daily-synced website). Report it once.
                if listing.object_id and self.db.recently_seen_object(
                        listing.object_id, self.cross_source_days, exclude_source=listing.source):
                    logger.info(f"Suppressing {listing.source} duplicate of object {listing.object_id}")
                    continue

                new.append(listing)
        return new

    def get_known_count(self) -> int:
        return len(self.known_keys)

    def cleanup_old_listings(self, days: int = 14) -> int:
        with self._lock:
            deleted = self.db.cleanup_old(days)
            self.known_keys = self.db.get_known_keys()
        return deleted
