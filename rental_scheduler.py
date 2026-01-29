#!/usr/bin/env python3
"""
Continuous Rental Listings Scheduler
Runs during specified hours and sends email notifications for new listings.
"""

import time
import logging
import signal
import sys
import random
from datetime import datetime, time as dt_time, date
from pathlib import Path
import pytz
from collections import defaultdict

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from src.scraper import WahlinRentalScraper, WallfastRentalScraper
from src.change_detector import ChangeDetector
from src.email_notifications import EmailNotifier

# Global flag for graceful shutdown
running = True

# Setup logging
import logging.handlers
import os

# Ensure logs directory exists
os.makedirs('logs', exist_ok=True)

# Create formatters
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Create handlers
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(formatter)

# Rotating file handler (10MB max, keep 5 backups)
file_handler = logging.handlers.RotatingFileHandler(
    'logs/scheduler.log',
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

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    global running
    logger.info("Received shutdown signal, stopping scheduler...")
    running = False

def load_config(config_file='config.yaml'):
    """Load configuration from YAML file"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load config file {config_file}: {e}")
        sys.exit(1)

def is_within_schedule(config, current_time=None):
    """Check if current time is within scheduled hours and days"""
    if current_time is None:
        current_time = datetime.now(pytz.timezone(config['scheduling']['timezone']))

    # Check if weekdays only is enabled
    if config['scheduling'].get('weekdays_only', False):
        # Monday = 0, Sunday = 6
        if current_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return False

    start_time = dt_time.fromisoformat(config['scheduling']['start_time'])
    end_time = dt_time.fromisoformat(config['scheduling']['end_time'])

    current_time_only = current_time.time()

    # Handle overnight schedules (e.g., 22:00 to 06:00)
    if start_time <= end_time:
        return start_time <= current_time_only <= end_time
    else:
        return current_time_only >= start_time or current_time_only <= end_time

def wait_until_next_check(config, daily_stats, email_notifier):
    """Wait until next scheduled check and send daily summary if end of day"""
    interval_seconds = config['scheduling']['interval_minutes'] * 60
    timezone = pytz.timezone(config['scheduling']['timezone'])
    current_time = datetime.now(timezone)

    # Check if we've reached the end of the workday (22:00 CET)
    end_of_day = dt_time(22, 0)  # 10 PM
    current_time_only = current_time.time()

    # If it's past end of day and we haven't sent today's summary yet
    if current_time_only >= end_of_day and not daily_stats.get('summary_sent', False):
        logger.info("End of workday reached, sending daily summary...")

        # Calculate uptime
        start_time = daily_stats.get('start_time')
        if start_time:
            uptime_seconds = (current_time - start_time).total_seconds()
            daily_stats['uptime_hours'] = uptime_seconds / 3600

        daily_stats['date'] = current_time.strftime('%Y-%m-%d')

        # Send daily summary
        if email_notifier.send_daily_summary(daily_stats):
            logger.info("Daily summary email sent successfully")
            daily_stats['summary_sent'] = True

            # Perform database cleanup after successful summary
            cleanup_days = config['storage'].get('cleanup_days', 14)
            cleaned_count = change_detector.cleanup_old_listings(cleanup_days)
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} old listings from database")

        else:
            logger.error("Failed to send daily summary email")

    # Add jitter to avoid predictable timing patterns (±60 seconds)
    jitter = random.uniform(-60, 60)
    sleep_time = max(10, interval_seconds + jitter)  # Minimum 10 seconds to avoid too frequent checks
    logger.info(f"Waiting {sleep_time:.1f} seconds until next check (jitter: {jitter:+.1f}s)...")
    time.sleep(sleep_time)

def perform_scrape_check(config, scrapers, change_detector, email_notifier, daily_stats):
    """Perform one scrape check and handle new listings"""
    try:
        logger.info("Starting scheduled scrape check...")
        current_time = datetime.now(pytz.timezone(config['scheduling']['timezone']))

        # Update daily stats
        daily_stats['total_scrapes'] += 1

        all_new_listings = []

        # Scrape from all enabled websites
        for name, scraper in scrapers.items():
            logger.info(f"Scraping {name}...")
            current_listings = scraper.scrape_listings()

            if not current_listings:
                logger.warning(f"No listings found for {name}")
                daily_stats['errors'] += 1
                daily_stats['error_details'].append(f"{current_time.strftime('%H:%M')}: No listings found for {name}")
                continue

            # Update successful scrapes
            daily_stats['successful_scrapes'] += 1

            # Detect new listings
            new_listings = change_detector.detect_new_listings(current_listings)

            if new_listings:
                logger.info(f"Found {len(new_listings)} new listings from {name}!")
                all_new_listings.extend(new_listings)

        if all_new_listings:
            logger.info(f"Total new listings found: {len(all_new_listings)}")
            daily_stats['new_listings'] += len(all_new_listings)

            # Send email notification
            if email_notifier.send_new_listings_notification(all_new_listings):
                logger.info("Email notification sent successfully")
                daily_stats['emails_sent'] += 1
            else:
                logger.error("Failed to send email notification")
                daily_stats['errors'] += 1
                daily_stats['error_details'].append(f"{current_time.strftime('%H:%M')}: Failed to send email notification")
        else:
            logger.info("No new listings found")

    except Exception as e:
        logger.error(f"Error during scrape check: {e}")
        daily_stats['errors'] += 1
        daily_stats['error_details'].append(f"{datetime.now(pytz.timezone(config['scheduling']['timezone'])).strftime('%H:%M')}: {str(e)}")

def main():
    global running

    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Load configuration
    config = load_config()
    logger.info("Configuration loaded successfully")

    # Initialize scrapers for enabled websites
    scrapers = {}
    websites_config = config.get('websites', {})

    if websites_config.get('wahlin', {}).get('enabled', True):
        scrapers['wahlin'] = WahlinRentalScraper(delay=config['scraping']['delay_seconds'])

    if websites_config.get('wallfast', {}).get('enabled', True):
        scrapers['wallfast'] = WallfastRentalScraper(delay=config['scraping']['delay_seconds'])

    if not scrapers:
        logger.error("No scrapers enabled!")
        sys.exit(1)

    # Initialize components
    change_detector = ChangeDetector(config['storage']['database_file'])
    email_notifier = EmailNotifier(config)

    # Initialize daily statistics
    daily_stats = {
        'total_scrapes': 0,
        'successful_scrapes': 0,
        'new_listings': 0,
        'emails_sent': 0,
        'errors': 0,
        'error_details': [],
        'start_time': datetime.now(pytz.timezone(config['scheduling']['timezone'])),
        'summary_sent': False
    }

    logger.info(f"Known listings: {change_detector.get_known_count()}")
    logger.info("Scheduler started. Press Ctrl+C to stop.")

    # Main scheduler loop
    while running:
        try:
            current_time = datetime.now(pytz.timezone(config['scheduling']['timezone']))

            # Reset daily stats at start of new day (if summary was already sent)
            if daily_stats.get('summary_sent', False) and current_time.date() != daily_stats.get('date_obj', current_time.date()):
                logger.info("New day started, resetting daily statistics")
                daily_stats = {
                    'total_scrapes': 0,
                    'successful_scrapes': 0,
                    'new_listings': 0,
                    'emails_sent': 0,
                    'errors': 0,
                    'error_details': [],
                    'start_time': current_time,
                    'summary_sent': False
                }
                daily_stats['date_obj'] = current_time.date()

            # Check if we're within scheduled hours
            if is_within_schedule(config):
                perform_scrape_check(config, scrapers, change_detector, email_notifier, daily_stats)
            else:
                logger.debug("Outside scheduled hours, skipping check")

            # Wait until next check (unless shutting down)
            if running:
                wait_until_next_check(config, daily_stats, email_notifier)

        except KeyboardInterrupt:
            logger.info("Scheduler interrupted by user")
            running = False
        except Exception as e:
            logger.error(f"Unexpected error in scheduler loop: {e}")
            time.sleep(60)  # Wait a bit before retrying

    logger.info("Scheduler stopped")

if __name__ == '__main__':
    main()
