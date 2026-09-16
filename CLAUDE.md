# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Monitors Swedish rental landlords (Wåhlin, Wallfast) for new apartments and notifies within seconds. Listings are sometimes visible for only 3-5 minutes, so each source is polled on its own thread at a short interval (default 20 s) around the clock. No push channel exists on either site; see README for why.

## Commands

```bash
pip install -r requirements.txt
python3 run.py               # Run the monitor (reads config.yaml)
python -m pytest             # Offline test suite
docker-compose up -d         # Docker
```

## Structure

```
run.py              # Entry point
src/
├── scheduler.py    # SourcePoller threads, backoff, alerts, daily summary, config normalization
├── scraper.py      # BaseScraper + WahlinArenaScraper (JSON), WahlinRentalScraper, WallfastRentalScraper
├── detector.py     # ChangeDetector: key-based dedup + cross-source suppression by object_id
├── database.py     # SQLite; migrates v1 (url PK) to v2 (key PK) automatically
├── notify.py       # Notifier queue/worker; ntfy and Telegram channels
├── email.py        # Email channel + HTML templates
├── models.py       # RentalListing (key, object_id, published_until, lottery, move_in)
└── logging.py      # Logging setup
tests/              # pytest; no network access needed
```

## Key facts about the sources

- `wahlin_arena`: `GET https://minasidor.wahlinfastigheter.se/rentalobject/Listapartment/published?sortOrder=&timestamp=<ms>` returns a JSON list (sometimes wrapped as `{"data": "<json>"}`), no auth. Listing key is `wahlin:<Id>:<ShowDateStart date>` so a re-publication is reported again.
- `wahlin`: WordPress page synced from Arena daily at ~08:08; object id is parsed from the URL slug for de-duplication against Arena.
- `wallfast`: SiteVision page; `li.sv-channel-item` entries. Ads posted weekdays 11:00-14:00.
- Both landlords allocate web-advertised apartments by lottery with a deadline; the notification includes the deadline when known.

## Operations

- `deploy/auto-update.sh` runs from cron on the server every minute (installed by `deploy/install-autoupdate.sh`): fetches origin/main, builds, runs pytest inside the image, then `docker compose up -d`. A failing commit is skipped and reported via ntfy, so a push to main is a production deploy: keep tests green.
- `Supervisor` in scheduler.py restarts dead poller threads, alerts on stale sources, and pings `health.heartbeat_url` (healthchecks.io style, `/fail` when unhealthy).
- Alerts use one key per source (`<source>:down`) so the notifier's cooldown turns a continuing outage into hourly reminders; recovery clears the key.

## Conventions

- A scraper returns `ScrapeResult`; `ok=False` must never be treated as "zero listings". Raise `ShapeChanged` in `_parse()` when the response is not recognised so the scheduler alerts.
- Never block a poller thread on notification I/O; use `Notifier` (queue-backed).
- `config.example.yaml` documents the config; `normalize_config()` in scheduler.py also accepts the original v1 layout (`schedule`/`email`/`scrapers`).

## Adding a Scraper

1. Subclass `BaseScraper` in `src/scraper.py`; implement `url()` and `_parse()`.
2. Set a stable `key` per listing and `object_id` when available.
3. Register in `SCRAPERS`, add a default interval in `scheduler.DEFAULT_INTERVALS`, document in config.
