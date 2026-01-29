#!/usr/bin/env python3
"""
Query the rental listings database
"""

import sys
from pathlib import Path
import sqlite3
from datetime import datetime, timedelta

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.database import RentalDatabase

def main():
    db = RentalDatabase("data/rentals.db")

    print("🏠 Rental Listings Database Query")
    print("=" * 40)

    # Get stats
    stats = db.get_stats()
    print("📊 Database Statistics:")
    print(f"   Total listings: {stats.get('total_listings', 0)}")
    print(f"   Recent (7 days): {stats.get('recent_listings_7d', 0)}")
    if stats.get('oldest_listing'):
        oldest = datetime.fromisoformat(stats['oldest_listing'])
        print(f"   Oldest listing: {oldest.strftime('%Y-%m-%d %H:%M')}")
    if stats.get('newest_listing'):
        newest = datetime.fromisoformat(stats['newest_listing'])
        print(f"   Newest listing: {newest.strftime('%Y-%m-%d %H:%M')}")
    print()

    # Show recent listings
    recent = db.get_recent_listings(1)
    print(f"📅 Recent Listings (24 hours): {len(recent)}")
    for listing in recent[:3]:  # Show first 3
        print(f"   • {listing.street} - {listing.area}")
        print(f"     {listing.number_of_rooms}, {listing.size}, {listing.rent_cost}")
        print(f"     First seen: {listing.scraped_at.strftime('%H:%M') if listing.scraped_at else 'Unknown'}")
    print()

    # Show listings by area
    print("📍 Listings by Area:")
    with sqlite3.connect("data/rentals.db") as conn:
        areas = conn.execute("""
            SELECT area, COUNT(*) as count
            FROM listings
            GROUP BY area
            ORDER BY count DESC
        """).fetchall()

        for area, count in areas:
            print(f"   • {area}: {count} listings")
    print()

    # Test cleanup (simulation - does not actually delete)
    print("🧹 Database Cleanup Test:")
    print("   Would remove listings older than 14 days")
    old_count = db.count_old_listings(14)  # Count without deleting
    print(f"   Would clean up {old_count} old listings")

    # Show current stats (no cleanup performed)
    current_stats = db.get_stats()
    print(f"   Current total listings: {current_stats.get('total_listings', 0)}")

if __name__ == '__main__':
    main()
