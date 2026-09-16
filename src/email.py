"""Email channel (Gmail SMTP)."""

import html
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List

from .models import RentalListing

logger = logging.getLogger(__name__)


def listing_rows_html(listings: List[RentalListing]) -> str:
    cell = 'padding:12px;border-bottom:1px solid #eee'
    rows = []
    for l in listings:
        badges = []
        if l.published_until:
            badges.append(f'<span style="color:#c62828">Apply by {html.escape(l.published_until)}</span>')
        if l.lottery:
            badges.append('<span style="color:#666">lottery</span>')
        if l.move_in:
            badges.append(f'<span style="color:#666">move in {html.escape(l.move_in)}</span>')
        badge_html = ' &middot; '.join(badges)
        rows.append(f"""
            <tr>
                <td style="{cell}">
                    <strong>{html.escape(l.street)}</strong><br>
                    <span style="color:#666">{html.escape(l.area)}</span>
                    <span style="color:#999;font-size:12px"> &middot; {html.escape(l.source or '')}</span>
                    {'<br><small>' + badge_html + '</small>' if badge_html else ''}
                </td>
                <td style="{cell}">{html.escape(l.number_of_rooms)}</td>
                <td style="{cell}">{html.escape(l.size)}</td>
                <td style="{cell};color:#2e7d32;font-weight:bold">{html.escape(l.rent_cost)}</td>
                <td style="{cell}"><a href="{html.escape(l.url or '#')}" style="color:#1976d2">Apply &rarr;</a></td>
            </tr>""")
    return "".join(rows)


def listings_html(listings: List[RentalListing]) -> str:
    n = len(listings)
    return f"""
    <div style="font-family:system-ui,sans-serif;max-width:700px;margin:0 auto">
        <h2 style="color:#333;border-bottom:2px solid #1976d2;padding-bottom:10px">
            {n} New Listing{'s' if n > 1 else ''}
        </h2>
        <table style="width:100%;border-collapse:collapse">
            <tr style="background:#f5f5f5">
                <th style="padding:12px;text-align:left">Address</th>
                <th style="padding:12px;text-align:left">Rooms</th>
                <th style="padding:12px;text-align:left">Size</th>
                <th style="padding:12px;text-align:left">Rent</th>
                <th></th>
            </tr>
            {listing_rows_html(listings)}
        </table>
    </div>"""


def listings_subject(listings: List[RentalListing]) -> str:
    first = listings[0]
    if len(listings) == 1:
        return f"New listing: {first.street}, {first.area} ({first.source})"
    return f"{len(listings)} new listings ({', '.join(sorted({l.source or '' for l in listings}))})"


def summary_html(stats: dict) -> str:
    errors = stats.get('errors', 0)
    per_source = stats.get('sources', {})
    source_rows = "".join(
        f"<tr><td style='padding:6px 0;color:#666'>{html.escape(name)}</td>"
        f"<td style='text-align:right'>{s.get('polls', 0)} polls, {s.get('failures', 0)} failures, "
        f"{s.get('new_listings', 0)} new</td></tr>"
        for name, s in per_source.items()
    )
    seen = stats.get('seen_today', [])
    seen_rows = "".join(
        f"<tr><td style='padding:6px 0'>{html.escape(r['street'])} <span style='color:#999'>({html.escape(r['source'])})</span></td>"
        f"<td style='text-align:right'>{r['first_seen'][11:16]} &rarr; {r['last_seen'][11:16]} "
        f"({r['visible_minutes']:.0f} min)</td></tr>"
        for r in seen
    )
    return f"""
    <div style="font-family:system-ui,sans-serif;max-width:560px;margin:0 auto">
        <h2 style="color:#333;border-bottom:2px solid #1976d2;padding-bottom:10px">
            Daily Summary &mdash; {stats.get('date', 'Unknown')}
        </h2>
        <table style="width:100%">
            <tr><td style="padding:8px 0;color:#666">Polls</td><td style="text-align:right"><strong>{stats.get('total_polls', 0)}</strong></td></tr>
            <tr><td style="padding:8px 0;color:#666">New Listings</td><td style="text-align:right"><strong>{stats.get('new_listings', 0)}</strong></td></tr>
            <tr><td style="padding:8px 0;color:#666">Errors</td><td style="text-align:right;color:{'#c62828' if errors else '#2e7d32'}"><strong>{errors}</strong></td></tr>
            <tr><td style="padding:8px 0;color:#666">Uptime</td><td style="text-align:right"><strong>{stats.get('uptime_hours', 0):.1f}h</strong></td></tr>
        </table>
        <h3 style="color:#333;margin-top:20px">Per source</h3>
        <table style="width:100%">{source_rows}</table>
        <h3 style="color:#333;margin-top:20px">Listings seen today (visible for)</h3>
        <table style="width:100%">{seen_rows or "<tr><td style='color:#999'>none</td></tr>"}</table>
    </div>"""


class EmailNotifier:
    name = "email"

    def __init__(self, config: dict):
        self.enabled = config.get('enabled', False)
        self.sender = config.get('sender')
        self.password = config.get('password')
        self.recipient = config.get('recipient')
        self.smtp_host = config.get('smtp_host', 'smtp.gmail.com')
        self.smtp_port = int(config.get('smtp_port', 587))
        if self.enabled and not all([self.sender, self.password, self.recipient]):
            logger.warning("Email enabled but sender/password/recipient incomplete; disabling")
            self.enabled = False

    def _send(self, subject: str, body_html: str) -> bool:
        if not self.enabled:
            return False
        try:
            msg = MIMEMultipart()
            msg['From'] = self.sender
            msg['To'] = self.recipient
            msg['Subject'] = subject
            msg.attach(MIMEText(body_html, 'html'))

            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=20) as server:
                server.starttls()
                server.login(self.sender, self.password)
                server.sendmail(self.sender, self.recipient, msg.as_string())
            return True
        except Exception as e:
            logger.error(f"Email failed: {e}")
            return False

    def send_listings(self, listings: List[RentalListing]) -> bool:
        if not listings:
            return False
        return self._send(listings_subject(listings), listings_html(listings))

    def send_text(self, title: str, body: str) -> bool:
        body_html = f"<div style='font-family:system-ui,sans-serif'><pre style='white-space:pre-wrap'>{html.escape(body)}</pre></div>"
        return self._send(title, body_html)

    def send_summary(self, stats: dict) -> bool:
        return self._send(f"Daily Summary - {stats.get('date', '')}", summary_html(stats))

    # Backwards-compatible names.
    send_new_listings_notification = send_listings
    send_daily_summary = send_summary
