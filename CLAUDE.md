# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A rental listings scraper that monitors Swedish rental property websites (Wåhlin Fastigheter, Wallfast) and sends email notifications when new apartments become available. Runs as a scheduled service during business hours (8 AM - 10 PM CET, Mon-Fri).

## Commands

```bash
# Run the scheduler (main entry point)
python3 rental_scheduler.py

# Run a one-time scrape
python3 -m src.main --sources all

# Query the database
python3 query_database.py

# Docker deployment
docker-compose up -d
docker-compose logs -f rental-scraper
```

## Architecture

```
rental_scheduler.py          # Main scheduler loop - coordinates scraping, change detection, emails
├── src/scraper.py           # Website scrapers (WahlinRentalScraper, WallfastRentalScraper)
├── src/change_detector.py   # Tracks known listings, detects new ones via database
├── src/database.py          # SQLite persistence (RentalDatabase class)
├── src/email_notifications.py # SMTP email sending (EmailNotifier class)
└── src/models.py            # RentalListing dataclass
```

**Data flow:** Scheduler → Scrapers → ChangeDetector → Database + EmailNotifier

## Key Files

- `config.yaml` - Schedule, email settings, scraping config, website URLs
- `data/rentals.db` - SQLite database (single source of truth for listings)
- `logs/scheduler.log` - Rotating log file (10MB max, 5 backups)

## Adding a New Scraper

1. Create a new scraper class in `src/scraper.py` following `WahlinRentalScraper` pattern
2. Implement `scrape_listings() -> List[RentalListing]`
3. Add website config to `config.yaml` under `websites:`
4. Initialize scraper in `rental_scheduler.py` based on config

## Configuration

Email uses Gmail SMTP with App Passwords (not regular passwords). The scheduler uses `pytz` for CET/CEST timezone handling. Listings older than 14 days are automatically cleaned up.
