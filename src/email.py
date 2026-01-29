"""Email notifications."""

import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List

from .models import RentalListing

logger = logging.getLogger(__name__)


class EmailNotifier:
    def __init__(self, config: dict):
        email = config.get('email', {})
        self.enabled = email.get('enabled', False)
        self.sender = email.get('sender')
        self.password = email.get('password')
        self.recipient = email.get('recipient')

    def _send(self, subject: str, html: str) -> bool:
        if not self.enabled or not all([self.sender, self.password, self.recipient]):
            return False

        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender
            msg['To'] = self.recipient
            msg['Subject'] = subject
            msg.attach(MIMEText(html, 'html'))

            with smtplib.SMTP('smtp.gmail.com', 587) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipient, msg.as_string())
            return True
        except Exception as e:
            logger.error(f"Email failed: {e}")
            return False

    def send_new_listings_notification(self, listings: List[RentalListing]) -> bool:
        if not listings:
            return False

        rows = "".join(f"""
            <tr>
                <td style="padding:12px;border-bottom:1px solid #eee">
                    <strong>{l.street}</strong><br>
                    <span style="color:#666">{l.area}</span>
                </td>
                <td style="padding:12px;border-bottom:1px solid #eee">{l.number_of_rooms}</td>
                <td style="padding:12px;border-bottom:1px solid #eee">{l.size}</td>
                <td style="padding:12px;border-bottom:1px solid #eee;color:#2e7d32;font-weight:bold">{l.rent_cost}</td>
                <td style="padding:12px;border-bottom:1px solid #eee">
                    <a href="{l.url}" style="color:#1976d2">View →</a>
                </td>
            </tr>""" for l in listings)

        html = f"""
        <div style="font-family:system-ui,sans-serif;max-width:700px;margin:0 auto">
            <h2 style="color:#333;border-bottom:2px solid #1976d2;padding-bottom:10px">
                {len(listings)} New Listing{'s' if len(listings) > 1 else ''}
            </h2>
            <table style="width:100%;border-collapse:collapse">
                <tr style="background:#f5f5f5">
                    <th style="padding:12px;text-align:left">Address</th>
                    <th style="padding:12px;text-align:left">Rooms</th>
                    <th style="padding:12px;text-align:left">Size</th>
                    <th style="padding:12px;text-align:left">Rent</th>
                    <th></th>
                </tr>
                {rows}
            </table>
        </div>"""

        if self._send(f"New Listings - {len(listings)} found", html):
            logger.info(f"Sent notification for {len(listings)} listings")
            return True
        return False

    def send_daily_summary(self, stats: dict) -> bool:
        errors = stats.get('errors', 0)

        html = f"""
        <div style="font-family:system-ui,sans-serif;max-width:500px;margin:0 auto">
            <h2 style="color:#333;border-bottom:2px solid #1976d2;padding-bottom:10px">
                Daily Summary — {stats.get('date', 'Unknown')}
            </h2>
            <table style="width:100%">
                <tr><td style="padding:8px 0;color:#666">Scrapes</td><td style="text-align:right"><strong>{stats.get('total_scrapes', 0)}</strong></td></tr>
                <tr><td style="padding:8px 0;color:#666">New Listings</td><td style="text-align:right"><strong>{stats.get('new_listings', 0)}</strong></td></tr>
                <tr><td style="padding:8px 0;color:#666">Errors</td><td style="text-align:right;color:{'#c62828' if errors else '#2e7d32'}"><strong>{errors}</strong></td></tr>
                <tr><td style="padding:8px 0;color:#666">Uptime</td><td style="text-align:right"><strong>{stats.get('uptime_hours', 0):.1f}h</strong></td></tr>
            </table>
        </div>"""

        if self._send("Daily Summary", html):
            logger.info("Daily summary sent")
            return True
        return False
