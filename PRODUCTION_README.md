# Rental Listings Scraper - Production Deployment

## Overview
This scraper monitors Wåhlin Fastigheter's rental listings and sends email notifications when new apartments become available.

## Features
- ✅ **Continuous monitoring**: Runs 8 AM - 10 PM CET, Monday-Friday
- ✅ **New listing alerts**: Instant email when new apartments are found
- ✅ **Daily summaries**: End-of-day status reports via email
- ✅ **Duplicate prevention**: Tracks known listings to avoid spam
- ✅ **Error monitoring**: Reports system issues and failures

## Email Notifications

### New Listings (Real-time)
- **Trigger**: When new apartments are discovered
- **Content**: Professional HTML with apartment details and direct links
- **Example Subject**: "New Rental Listings Found - 3 new apartments"

### Daily Summary (End of Day)
- **Trigger**: Sent at ~10 PM CET each workday
- **Content**: System health and performance statistics
- **Includes**:
  - Total scrapes performed
  - Successful vs failed operations
  - New listings discovered
  - Emails sent
  - Error count and details
  - System uptime

## Files Structure
```
/app/
├── rental_scheduler.py    # Main continuous scraper
├── config.yaml           # Gmail & schedule configuration
├── requirements.txt      # Python dependencies
├── deploy-docker.sh     # Docker deployment script
├── query_database.py    # Database query utility
├── data/                # Persistent storage (created automatically)
│   ├── rentals.db       # SQLite database with full listing details
│   └── known_listings.json # Legacy file (can be removed)
└── src/                 # Source code
    ├── scraper.py       # Website scraping
    ├── models.py        # Data structures
    ├── change_detector.py # New listing detection
    ├── email_notifications.py # Email functionality
    └── database.py      # SQLite database management
```

## Deployment

### 🚀 Quick Docker Deployment (Recommended)

The easiest way to deploy is using Docker - no server configuration needed!

#### 1. Server Setup
```bash
# Choose a VPS with Docker support (Hetzner, DigitalOcean, etc.)
# Ubuntu 22.04+ recommended

# Install Docker and Docker Compose
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo apt-get install -y docker-compose-plugin

# Add your user to docker group (optional)
sudo usermod -aG docker $USER
```

#### 2. Deploy with Docker
```bash
# Clone your repository
git clone https://github.com/yourusername/rental-updates.git
cd rental-updates

# Configure your email settings
vim config.yaml  # Update sender_email, sender_password, recipient_email

# Build and start the container
docker-compose up -d

# Check that it's running
docker-compose ps
docker-compose logs -f rental-scraper
```

#### 3. Monitor & Manage
```bash
# View logs
docker-compose logs -f rental-scraper

# Check container health
docker-compose ps

# Update the application
docker-compose pull && docker-compose up -d

# Stop the service
docker-compose down

# Backup data (optional)
docker-compose --profile backup run --rm backup
```

### 🏗️ Manual Setup (Alternative)

If you prefer not to use Docker:

#### 1. Server Setup
```bash
# Install Python and dependencies
sudo apt update
sudo apt install -y python3 python3-pip python3-venv

# Clone repository
git clone https://github.com/yourusername/rental-updates.git
cd rental-updates

# Create virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

#### 2. Manual Setup (Alternative)
If you prefer not to use Docker:

```bash
# Install Python dependencies
pip3 install -r requirements.txt

# Run directly
python3 rental_scheduler.py

# Or set up systemd manually (advanced)
# See rental-scheduler.service for configuration
```

## 📊 Monitoring & Logs

### Docker Logs
```bash
# View recent logs
docker-compose logs rental-scraper

# Follow logs in real-time
docker-compose logs -f rental-scraper

# View logs with timestamps
docker-compose logs -t rental-scraper

# Check container health
docker stats rental-scraper
```

### Systemd Logs (Manual Setup)
```bash
# View recent logs
sudo journalctl -u rental-scheduler -n 50

# Follow logs in real-time
sudo journalctl -u rental-scheduler -f

# View logs from today
sudo journalctl -u rental-scheduler --since today
```

### Application Logs
```bash
# Log files are automatically rotated at 10MB with 5 backup files kept
tail -f logs/scheduler.log
ls -la logs/  # See all log files
```

## Configuration

Edit `config.yaml` to customize:

```yaml
scheduling:
  timezone: "Europe/Stockholm"  # CET/CEST
  start_time: "08:00"           # Business hours start
  end_time: "22:00"             # Business hours end
  interval_minutes: 15          # Check frequency
  weekdays_only: true           # Monday-Friday only

email:
  enabled: true
  sender_email: "your-email@gmail.com"
  sender_password: "your-gmail-app-password"
  recipient_email: "your-email@gmail.com"
  subject_template: "New Rental Listings Found - {count} new apartments"
```

## System Monitoring

### Daily Summary Email Includes:
- **Total Scrapes**: How many times the website was checked
- **Success Rate**: Percentage of successful operations
- **New Listings**: Apartments discovered that day
- **Emails Sent**: Notification emails dispatched
- **Errors**: Any system issues encountered
- **Uptime**: Hours the system was operational

### Log Files:
- `scheduler.log`: Detailed operation logs
- `data/known_listings.json`: Tracks seen apartments

## Troubleshooting

### Common Issues:

1. **No emails received**:
   - Verify Gmail App Password is correct
   - Check 2FA is enabled on Gmail account
   - Ensure server has internet access

2. **No listings found**:
   - Website structure may have changed
   - Check `scheduler.log` for error details
   - Daily summary will report this as an error

3. **Scheduler stops**:
   - Check system resources (memory/disk)
   - Review logs for crash details
   - Restart: `python rental_scheduler.py`

### Emergency Stop:
```bash
pkill -f rental_scheduler.py
```

## Performance
- **Memory usage**: ~50MB
- **CPU usage**: Minimal (scrapes every 15 min)
- **Network**: ~1 request per 15 minutes
- **Storage**: ~1KB per known listing

## Database Features

The scraper now uses SQLite to store complete listing details:

### Stored Data
- **URL**: Direct link to listing
- **Area**: Neighborhood location
- **Street**: Full address
- **Rooms**: Number of rooms (e.g., "3 rok")
- **Rent**: Monthly cost (e.g., "13 531 kr")
- **Size**: Square meters (e.g., "87 kvm")
- **Timestamps**: First seen and last seen dates

### Database Operations
```bash
# Query the database
python3 query_database.py

# Manual database queries
sqlite3 data/rentals.db "SELECT * FROM listings WHERE area = 'Huvudsta';"
```

### Automatic Cleanup
- Removes listings older than 14 days (configurable)
- Runs daily after end-of-day summary
- Keeps database size manageable

## Security
- Gmail App Passwords (not regular passwords)
- No sensitive data stored
- HTTPS communication only
- Minimal system access required
