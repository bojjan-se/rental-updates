# Rental Listings Monitor

Watches Swedish rental landlords for new apartments and pushes a notification
within seconds. Built for listings that are sometimes visible for only a few
minutes.

## How it works

Neither landlord offers a feed, webhook or any other push channel, so the
monitor polls. What makes it fast enough is *what* it polls and *how*:

| Source | What is polled | Default interval |
|---|---|---|
| `wahlin_arena` | Wåhlin's tenant portal JSON (Vitec Arena). The public website is synced from this once a day, so short-lived listings appear here first, and possibly only here. | 20 s |
| `wallfast` | Wallfast's listings page. Web-let apartments are posted weekdays 11:00-14:00 and can be taken down within minutes. | 20 s |
| `wahlin` | Wåhlin's public website. Fallback only; anything already reported via the portal is suppressed. | 5 min |
| `heimstaden` | Heimstaden's tenant portal JSON (same Vitec Arena product). One 2.5 MB response for all of Sweden, filtered by `include_areas`. Allocation is by registration date, so hourly is enough. | 1 h |

- Each source runs on its own thread, so a slow site never delays another.
- New listings are handed to a notifier queue immediately; sending happens on
  a separate thread so SMTP latency never blocks polling.
- A failed or unrecognised fetch is never mistaken for "no listings". Pollers
  back off on 429/5xx and alert you if a site keeps failing or changes shape.
- First-seen / last-seen times are stored per listing, and the daily summary
  reports how long each listing was actually visible.

Both landlords allocate web-advertised apartments by lottery, so the aim is
to get you into the draw before the ad closes, not to be first.

## Setup

```bash
git clone https://github.com/bojjan-se/rental-updates.git
cd rental-updates
pip install -r requirements.txt
cp config.example.yaml config.yaml
# Edit config.yaml
python3 run.py
```

## Notifications

Configure any combination under `notifications:` in `config.yaml`:

- **email** – Gmail SMTP with an [App Password](https://support.google.com/accounts/answer/185833).
- **ntfy** – phone push with no account: install the [ntfy](https://ntfy.sh) app,
  subscribe to a secret topic name, set `topic`. Delivers in about a second.
- **telegram** – create a bot with @BotFather, set `bot_token` and `chat_id`.

Email alone is usually too slow to notice for a 3-minute window; enable ntfy
or Telegram as well.

Check delivery before waiting for a real listing:

```bash
python3 run.py --test-notify
```

## Never falling silent

Being blocked, or the process dying, must never look like "no listings".
Every one of these produces a phone alert:

| Situation | What happens |
|---|---|
| HTTP 401/403/429 from a site | Alert on the **first** response. Backs off, keeps retrying, alerts again hourly while it lasts, sends an all-clear on recovery. |
| Login wall, bot challenge, redesign | The scraper no longer recognises the response: immediate "structure changed" alert. |
| Network errors, timeouts | Alert after 5 in a row, or after 3 minutes without a successful poll, whichever comes first. |
| A poller thread dies | The supervisor restarts it and alerts. |
| The whole process or server dies | Only an outside observer can catch this: set `health.heartbeat_url` to a free [healthchecks.io](https://healthchecks.io) check (period 1 min, grace 5 min) with its ntfy integration pointed at your topic. The monitor pings it every minute while healthy and pings `/fail` while a source is down. |

## Data lifecycle

- **Listings database** (`data/rentals.db`): one row per listing with first-seen and
  last-seen timestamps. Kept forever by default (`cleanup_days: 0`); a year of
  history is well under a megabyte, and it is what reveals when each landlord
  publishes. A consistent copy is written nightly to `data/backups/` (14 kept).
- **Logs**: `logs/scheduler.log` rotates at 10 MB x 5; Docker's stdout log is capped
  in `docker-compose.yml`; `logs/autoupdate.log` gets a few lines per deploy.
- **Docker images and build cache**: pruned after every successful auto-deploy.
- **Notifications**: ntfy.sh keeps messages 12 hours; the phone app keeps them until cleared.
- **Secrets**: only `config.yaml` (gitignored) holds the ntfy topic.

## Docker

```bash
docker compose up -d
docker compose logs -f rental-scraper
```

## Automatic deploys on the server

`deploy/auto-update.sh` checks `origin/main` once a minute. When it has
moved, the script pulls, builds the image, runs the test suite inside the new
image, and only then swaps the running container. A commit that fails to
build or test is reported to your ntfy topic and skipped; the old container
keeps running. Successful deploys are announced too.

One-time setup on the server, inside the cloned repo:

```bash
bash deploy/install-autoupdate.sh
```

After that, `git push` is the whole release process. Progress is logged to
`logs/autoupdate.log`.

## Tests

```bash
python -m pytest
```

## Structure

```
run.py              # Entry point
src/
├── scheduler.py    # One poller thread per source, backoff, alerts, daily summary
├── scraper.py      # Scrapers: WahlinArenaScraper (JSON), WahlinRentalScraper, WallfastRentalScraper
├── detector.py     # New-listing detection and cross-source de-duplication
├── database.py     # SQLite (auto-migrates v1 databases)
├── notify.py       # Notification queue + ntfy / Telegram channels
├── email.py        # Email channel and HTML formatting
├── models.py       # RentalListing
└── logging.py      # Logging setup
tests/              # pytest suite (offline; uses fixtures)
```

## Adding a source

1. Subclass `BaseScraper` in `src/scraper.py`; implement `url()` and `_parse()`.
   Raise `ShapeChanged` when the response is not what you expect, so the
   scheduler alerts instead of silently reporting "no listings".
2. Give each listing a stable `key` (defaults to the URL) and, if the landlord
   exposes it, an `object_id` so duplicates across sources are merged.
3. Register it in `SCRAPERS` and add it under `sources:` in the config.

## License

MIT
