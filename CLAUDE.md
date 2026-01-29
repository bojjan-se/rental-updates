# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Rental listings scraper for Swedish rental websites. Sends email notifications for new apartments. Runs 8-22 CET, Mon-Fri.

## Commands

```bash
pip install -r requirements.txt
python3 run.py               # Run scheduler
docker-compose up -d         # Docker
```

## Structure

```
run.py              # Entry point
src/
├── scheduler.py    # Main loop
├── scraper.py      # BaseScraper + site scrapers
├── detector.py     # New listing detection
├── database.py     # SQLite
├── email.py        # Notifications
├── models.py       # RentalListing
└── logging.py      # Logging setup
```

## Adding a Scraper

1. Extend `BaseScraper` in `src/scraper.py`
2. Set `BASE_URL`, `LISTINGS_URL`, `SOURCE_NAME`
3. Implement `_parse_listings(soup)`
4. Add to config and scheduler
