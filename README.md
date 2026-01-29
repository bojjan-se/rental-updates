# Rental Listings Scraper

Monitors Swedish rental websites and sends email notifications for new apartments.

## Setup

```bash
git clone https://github.com/yourusername/rental-updates.git
cd rental-updates
pip install -r requirements.txt
cp config.example.yaml config.yaml
# Edit config.yaml with your credentials
python3 run.py
```

## Configuration

Edit `config.yaml`:

```yaml
email:
  sender_email: "your-email@gmail.com"
  sender_password: "your-gmail-app-password"
  recipient_email: "recipient@example.com"
```

Use a [Gmail App Password](https://support.google.com/accounts/answer/185833).

## Docker

```bash
docker-compose up -d
docker-compose logs -f rental-scraper
```

## Structure

```
run.py              # Entry point
src/
├── scheduler.py    # Main loop
├── scraper.py      # Web scrapers
├── detector.py     # New listing detection
├── database.py     # SQLite
├── email.py        # Notifications
├── models.py       # Data models
└── logging.py      # Logging
```

## License

MIT
