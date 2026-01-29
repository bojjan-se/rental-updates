"""Rental Listings Scheduler."""

import logging
import random
import signal
import sys
import time
from datetime import datetime, time as dt_time

import pytz
import yaml

from .logging import setup_logging
from .scraper import WahlinRentalScraper, WallfastRentalScraper
from .detector import ChangeDetector
from .email import EmailNotifier

setup_logging()
logger = logging.getLogger(__name__)

running = True


def signal_handler(_signum, _frame):
    global running
    logger.info("Shutting down...")
    running = False


def load_config(path: str = 'config.yaml') -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        sys.exit(1)


def is_within_schedule(config: dict) -> bool:
    schedule = config['schedule']
    tz = pytz.timezone(schedule['timezone'])
    now = datetime.now(tz)

    if schedule.get('weekdays_only', False) and now.weekday() >= 5:
        return False

    start = dt_time.fromisoformat(schedule['start'])
    end = dt_time.fromisoformat(schedule['end'])
    current = now.time()

    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def perform_scrape(scrapers, detector, notifier, stats):
    logger.info("Starting scrape...")
    stats['total_scrapes'] += 1
    all_new = []

    for name, scraper in scrapers.items():
        logger.info(f"Scraping {name}...")
        listings = scraper.scrape_listings()

        if not listings:
            logger.warning(f"No listings from {name}")
            stats['errors'] += 1
            continue

        new = detector.detect_new_listings(listings)
        if new:
            logger.info(f"Found {len(new)} new from {name}")
            all_new.extend(new)

    if all_new:
        logger.info(f"Total new: {len(all_new)}")
        stats['new_listings'] += len(all_new)

        if notifier.send_new_listings_notification(all_new):
            logger.info("Email sent")
        else:
            logger.error("Email failed")
            stats['errors'] += 1
    else:
        logger.info("No new listings")


def wait_for_next(config, stats, notifier, detector):
    schedule = config['schedule']
    interval = schedule['interval_minutes'] * 60
    tz = pytz.timezone(schedule['timezone'])
    now = datetime.now(tz)

    # Daily summary at end time
    end_time = dt_time.fromisoformat(schedule['end'])
    if now.time() >= end_time and not stats.get('summary_sent'):
        logger.info("Sending daily summary...")
        if stats.get('start_time'):
            stats['uptime_hours'] = (now - stats['start_time']).total_seconds() / 3600
        stats['date'] = now.strftime('%Y-%m-%d')

        if notifier.send_daily_summary(stats):
            stats['summary_sent'] = True
            cleanup_days = config.get('cleanup_days', 14)
            cleaned = detector.cleanup_old_listings(cleanup_days)
            if cleaned:
                logger.info(f"Cleaned {cleaned} old listings")

    jitter = random.uniform(-60, 60)
    sleep_time = max(10, interval + jitter)
    logger.info(f"Next check in {sleep_time:.0f}s")
    time.sleep(sleep_time)


def create_stats(tz):
    return {
        'total_scrapes': 0,
        'new_listings': 0,
        'errors': 0,
        'start_time': datetime.now(tz),
        'summary_sent': False,
        'date_obj': datetime.now(tz).date()
    }


def main():
    global running

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    config = load_config()
    logger.info("Config loaded")

    tz = pytz.timezone(config['schedule']['timezone'])

    # Initialize scrapers
    scrapers = {}
    scraper_config = config.get('scrapers', {})

    if scraper_config.get('wahlin', True):
        scrapers['wahlin'] = WahlinRentalScraper()
    if scraper_config.get('wallfast', True):
        scrapers['wallfast'] = WallfastRentalScraper()

    if not scrapers:
        logger.error("No scrapers enabled")
        sys.exit(1)

    detector = ChangeDetector(config.get('database', 'data/rentals.db'))
    notifier = EmailNotifier(config)
    stats = create_stats(tz)

    logger.info(f"Known listings: {detector.get_known_count()}")
    logger.info("Started. Ctrl+C to stop.")

    while running:
        try:
            now = datetime.now(tz)

            if stats['summary_sent'] and now.date() != stats['date_obj']:
                logger.info("New day, resetting stats")
                stats = create_stats(tz)

            if is_within_schedule(config):
                perform_scrape(scrapers, detector, notifier, stats)
            else:
                logger.debug("Outside schedule")

            if running:
                wait_for_next(config, stats, notifier, detector)

        except KeyboardInterrupt:
            running = False
        except Exception as e:
            logger.error(f"Error: {e}")
            time.sleep(60)

    logger.info("Stopped")
