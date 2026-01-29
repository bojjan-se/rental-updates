import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from typing import List
from .models import RentalListing

logger = logging.getLogger(__name__)

class EmailNotifier:
    """Handles email notifications for new rental listings"""

    def __init__(self, config):
        self.config = config
        self.email_config = config.get('email', {})

    def send_new_listings_notification(self, new_listings: List[RentalListing]) -> bool:
        """Send email notification about newly discovered listings"""
        if not self.email_config.get('enabled', False) or not new_listings:
            return False

        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.email_config['sender_email']
            msg['To'] = self.email_config['recipient_email']

            subject = self.email_config['subject_template'].format(count=len(new_listings))
            msg['Subject'] = subject

            # Create HTML body
            html_body = self._create_html_body(new_listings)
            msg.attach(MIMEText(html_body, 'html'))

            # Send email
            server = smtplib.SMTP(self.email_config['smtp_server'], self.email_config['smtp_port'])
            server.starttls()
            server.login(self.email_config['sender_email'], self.email_config['sender_password'])
            text = msg.as_string()
            server.sendmail(self.email_config['sender_email'], self.email_config['recipient_email'], text)
            server.quit()

            logger.info(f"Sent email notification for {len(new_listings)} new listings")
            return True

        except Exception as e:
            logger.error(f"Failed to send email notification: {e}")
            return False

    def _create_html_body(self, listings: List[RentalListing]) -> str:
        """Create HTML email body with listing details"""
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .listing {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
                .header {{ background-color: #f8f9fa; padding: 10px; margin: -15px -15px 15px -15px; border-radius: 5px 5px 0 0; }}
                .details {{ margin: 10px 0; }}
                .price {{ font-size: 18px; font-weight: bold; color: #28a745; }}
                .url {{ margin-top: 10px; }}
                .url a {{ color: #007bff; text-decoration: none; }}
                .url a:hover {{ text-decoration: underline; }}
            </style>
        </head>
        <body>
            <h2>New Rental Listings Found!</h2>
            <p>We discovered {len(listings)} new rental listing{'s' if len(listings) > 1 else ''}.</p>

            {"".join(self._create_listing_html(listing) for listing in listings)}

            <p><em>This is an automated message from your rental listings scraper.</em></p>
        </body>
        </html>
        """
        return html

    def _create_listing_html(self, listing: RentalListing) -> str:
        """Create HTML for a single listing"""
        return f"""
        <div class="listing">
            <div class="header">
                <h3>{listing.street}</h3>
                <p><strong>{listing.area}</strong></p>
            </div>
            <div class="details">
                <p><strong>Rooms:</strong> {listing.number_of_rooms}</p>
                <p><strong>Size:</strong> {listing.size}</p>
                <p class="price"><strong>Rent:</strong> {listing.rent_cost} per month</p>
            </div>
            <div class="url">
                <a href="{listing.url}">View Listing</a>
            </div>
        </div>
        """

    def send_daily_summary(self, daily_stats: dict) -> bool:
        """Send daily summary email with system status"""
        if not self.email_config.get('enabled', False):
            return False

        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = self.email_config['sender_email']
            msg['To'] = self.email_config['recipient_email']
            msg['Subject'] = "Daily Rental Scraper Summary"

            # Create HTML body
            html_body = self._create_daily_summary_html(daily_stats)
            msg.attach(MIMEText(html_body, 'html'))

            # Send email
            server = smtplib.SMTP(self.email_config['smtp_server'], self.email_config['smtp_port'])
            server.starttls()
            server.login(self.email_config['sender_email'], self.email_config['sender_password'])
            text = msg.as_string()
            server.sendmail(self.email_config['sender_email'], self.email_config['recipient_email'], text)
            server.quit()

            logger.info("Daily summary email sent successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to send daily summary email: {e}")
            return False

    def _create_daily_summary_html(self, stats: dict) -> str:
        """Create HTML for daily summary email"""
        status_emoji = "✅" if stats.get('errors', 0) == 0 else "⚠️"
        status_text = "All systems operational" if stats.get('errors', 0) == 0 else f"{stats.get('errors', 0)} errors detected"

        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background-color: #f8f9fa; padding: 20px; border-radius: 5px; margin-bottom: 20px; }}
                .stats {{ display: flex; flex-wrap: wrap; gap: 20px; margin: 20px 0; }}
                .stat-card {{ background: white; border: 1px solid #ddd; border-radius: 8px; padding: 15px; min-width: 150px; }}
                .stat-number {{ font-size: 24px; font-weight: bold; color: #007bff; }}
                .stat-label {{ color: #666; font-size: 14px; margin-top: 5px; }}
                .errors {{ background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 20px 0; }}
                .success {{ background-color: #d4edda; border: 1px solid #c3e6cb; padding: 15px; border-radius: 5px; margin: 20px 0; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🏢 Daily Rental Scraper Report</h1>
                <p><strong>Date:</strong> {stats.get('date', 'Unknown')}</p>
                <p><strong>Status:</strong> {status_emoji} {status_text}</p>
            </div>

            <div class="stats">
                <div class="stat-card">
                    <div class="stat-number">{stats.get('total_scrapes', 0)}</div>
                    <div class="stat-label">Total Scrapes</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats.get('successful_scrapes', 0)}</div>
                    <div class="stat-label">Successful</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats.get('new_listings', 0)}</div>
                    <div class="stat-label">New Listings</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats.get('emails_sent', 0)}</div>
                    <div class="stat-label">Emails Sent</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats.get('errors', 0)}</div>
                    <div class="stat-label">Errors</div>
                </div>
                <div class="stat-card">
                    <div class="stat-number">{stats.get('uptime_hours', 0):.1f}h</div>
                    <div class="stat-label">Uptime</div>
                </div>
            </div>

            {"".join([f"<div class='errors'>⚠️ {error}</div>" for error in stats.get('error_details', [])])}

            <div class="success">
                <p><strong>System Health:</strong> All monitoring systems operational</p>
                <p><strong>Next check:</strong> Tomorrow at 08:00 CET (Monday-Friday only)</p>
            </div>

            <p><em>This is an automated daily summary from your rental listings scraper.</em></p>
        </body>
        </html>
        """
        return html
