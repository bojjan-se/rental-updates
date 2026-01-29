#!/usr/bin/env python3
"""
Rental Listings Scraper for Wåhlin Fastigheter and Wallfast
A standalone tool for scraping rental property listings.

The SQLite database (data/rentals.db) is the single source of truth.
This tool scrapes listings and stores them in the database.
Use query_database.py to inspect the data.
"""

import argparse
import logging
import sys
from pathlib import Path

from .models import RentalListing
from .scraper import WahlinRentalScraper, WallfastRentalScraper
from .database import RentalDatabase

# Configure logging
import logging.handlers
import os

# Ensure logs directory exists
os.makedirs('../logs', exist_ok=True)

# Create formatters
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Create handlers
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)

# Rotating file handler (10MB max, keep 5 backups)
file_handler = logging.handlers.RotatingFileHandler(
    '../logs/scraper.log',
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5
)
file_handler.setFormatter(formatter)

# Setup root logger
logging.basicConfig(
    level=logging.INFO,
    handlers=[console_handler, file_handler]
)

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Scrape rental listings and store in database')
    parser.add_argument('--delay', '-d', type=float, default=1.0,
                       help='Delay between requests in seconds (default: 1.0)')
    parser.add_argument('--sources', '-s', nargs='+',
                       choices=['wahlin', 'wallfast', 'all'], default=['all'],
                       help='Sources to scrape (default: all)')
    parser.add_argument('--db-path', default='data/rentals.db',
                       help='Database file path (default: data/rentals.db)')

    args = parser.parse_args()

    # Initialize database
    db = RentalDatabase(args.db_path)

    # Initialize scrapers
    scrapers = []
    sources_to_scrape = args.sources if 'all' not in args.sources else ['wahlin', 'wallfast']

    if 'wahlin' in sources_to_scrape:
        scrapers.append(('wahlin', WahlinRentalScraper(delay=args.delay)))

    if 'wallfast' in sources_to_scrape:
        scrapers.append(('wallfast', WallfastRentalScraper(delay=args.delay)))

    if not scrapers:
        logger.error("No valid sources specified!")
        sys.exit(1)

    total_scraped = 0
    total_new = 0

    # Scrape from each source
    for source_name, scraper in scrapers:
        logger.info(f"Starting {source_name} rental listings scrape...")
        listings = scraper.scrape_listings()

        if listings:
            logger.info(f"Found {len(listings)} listings from {source_name}")

            # Store in database
            new_count = 0
            for listing in listings:
                if db.add_listing(listing):
                    new_count += 1

            logger.info(f"Added {new_count} new listings from {source_name} to database")
            total_scraped += len(listings)
            total_new += new_count
        else:
            logger.warning(f"No listings found from {source_name}")

    if total_scraped == 0:
        logger.error("No listings found from any source!")
        sys.exit(1)

    # Print summary
    logger.info(f"Scraping completed successfully!")
    logger.info(f"Total listings scraped: {total_scraped}")
    logger.info(f"New listings added: {total_new}")

    # Show database stats
    stats = db.get_stats()
    logger.info(f"Database now contains: {stats.get('total_listings', 0)} total listings")

    # Show stats by source
    if stats.get('listings_by_source'):
        logger.info("Listings by source in database:")
        for source, count in sorted(stats['listings_by_source'].items()):
            logger.info(f"  {source}: {count}")

    logger.info("Use 'python3 query_database.py' to inspect the data")

if __name__ == '__main__':
    main()
