"""Scrapers for rental listings.

Each scraper fetches one source and returns a ScrapeResult. A result with
ok=False means the fetch or parse failed and the caller must NOT treat the
(empty) listing set as "no listings" - it should back off and retry instead.
"""

import json
import re
import time
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .models import RentalListing

logger = logging.getLogger(__name__)

USER_AGENT = 'rental-updates/2.0 (personal listing monitor; +https://github.com/bojjan-se/rental-updates)'


class ShapeChanged(Exception):
    """The response was received but does not look like the page/API we expect."""


class FetchError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class ScrapeResult:
    source: str
    ok: bool
    listings: List[RentalListing] = field(default_factory=list)
    error: Optional[str] = None
    status_code: Optional[int] = None
    shape_changed: bool = False
    elapsed: float = 0.0


class BaseScraper(ABC):
    SOURCE_NAME: str = ""
    BASE_URL: str = ""

    def __init__(self, timeout: float = 15.0):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': USER_AGENT,
            'Accept-Language': 'sv-SE,sv;q=0.9,en;q=0.5',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
        })

    @abstractmethod
    def url(self) -> str:
        """URL to fetch for this poll (may include cache-busting)."""

    @abstractmethod
    def _parse(self, response: requests.Response) -> List[RentalListing]:
        """Turn a successful response into listings. Raise ShapeChanged if the
        response is well-formed HTTP but not the structure we expect."""

    def _get(self, url: str) -> requests.Response:
        try:
            response = self.session.get(url, timeout=self.timeout)
        except requests.RequestException as e:
            raise FetchError(f"request failed: {e}") from e
        if response.status_code >= 400:
            raise FetchError(f"HTTP {response.status_code}", status_code=response.status_code)
        return response

    def fetch(self) -> ScrapeResult:
        started = time.monotonic()
        url = self.url()
        try:
            response = self._get(url)
        except FetchError as e:
            return ScrapeResult(self.SOURCE_NAME, ok=False, error=str(e),
                                status_code=e.status_code, elapsed=time.monotonic() - started)

        try:
            listings = self._parse(response)
        except ShapeChanged as e:
            return ScrapeResult(self.SOURCE_NAME, ok=False, error=f"unexpected structure: {e}",
                                status_code=response.status_code, shape_changed=True,
                                elapsed=time.monotonic() - started)
        except Exception as e:
            return ScrapeResult(self.SOURCE_NAME, ok=False, error=f"parse error: {e}",
                                status_code=response.status_code, elapsed=time.monotonic() - started)

        for listing in listings:
            listing.source = self.SOURCE_NAME
        return ScrapeResult(self.SOURCE_NAME, ok=True, listings=listings,
                            status_code=response.status_code, elapsed=time.monotonic() - started)

    # Backwards-compatible helper used by older callers/tests.
    def scrape_listings(self) -> List[RentalListing]:
        return self.fetch().listings


# --------------------------------------------------------------------------
# Wåhlin - Vitec Arena tenant portal (system of record, JSON, no auth)
# --------------------------------------------------------------------------

class WahlinArenaScraper(BaseScraper):
    """Polls the JSON endpoint behind minasidor.wahlinfastigheter.se.

    This is the system the public WordPress site is synced from (once a day),
    so short-lived listings show up here first, and possibly only here.
    """
    SOURCE_NAME = "wahlin_arena"
    BASE_URL = "https://minasidor.wahlinfastigheter.se"
    LIST_PATH = "/rentalobject/Listapartment/published"
    REQUIRED_FIELDS = ("Id", "Adress1", "DetailsUrl")

    def __init__(self, timeout: float = 15.0):
        super().__init__(timeout)
        self.session.headers.update({
            'Accept': 'application/json, text/javascript, */*',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': f'{self.BASE_URL}/ledigt/lagenhet',
        })

    def url(self) -> str:
        return f"{self.BASE_URL}{self.LIST_PATH}?sortOrder=&timestamp={int(time.time() * 1000)}"

    def _parse(self, response: requests.Response) -> List[RentalListing]:
        try:
            data = response.json()
        except ValueError as e:
            raise ShapeChanged(f"not JSON ({e}); first bytes: {response.text[:80]!r}")
        return self.parse_objects(data)

    @classmethod
    def parse_objects(cls, data) -> List[RentalListing]:
        # The endpoint sometimes wraps the list as {"data": "<json string>"}.
        if isinstance(data, dict) and 'data' in data:
            data = data['data']
        if isinstance(data, str):
            data = json.loads(data)
        if not isinstance(data, list):
            raise ShapeChanged(f"expected a list, got {type(data).__name__}")

        listings = []
        for obj in data:
            if not isinstance(obj, dict) or any(f not in obj for f in cls.REQUIRED_FIELDS):
                raise ShapeChanged(f"object missing required fields {cls.REQUIRED_FIELDS}")
            try:
                listings.append(cls._to_listing(obj))
            except Exception as e:
                logger.error(f"Error converting Arena object {obj.get('Id')}: {e}")
        return listings

    @classmethod
    def _to_listing(cls, obj: dict) -> RentalListing:
        object_id = str(obj['Id'])
        show_start = (obj.get('ShowDateStart') or '')[:10]
        show_end = (obj.get('ShowDateEnd') or '')[:16].replace('T', ' ')
        move_in = (obj.get('MoveInDate') or obj.get('AvailableDate') or '')[:10]

        cost = obj.get('TotalCost') or obj.get('Cost')
        rent = f"{int(cost):,}".replace(',', ' ') + " kr" if isinstance(cost, (int, float)) else "N/A"
        rooms = obj.get('NoOfRooms')
        rooms_str = f"{rooms:g} rok" if isinstance(rooms, (int, float)) else "N/A"
        size = obj.get('Size')
        size_str = f"{size:g} kvm" if isinstance(size, (int, float)) else "N/A"

        area = obj.get('AreaName') or (obj.get('Adress3') or 'Unknown').title()
        street = obj['Adress1']
        flat = obj.get('FlatNumber')
        if flat:
            street = f"{street} (lgh {flat})"

        details = obj['DetailsUrl'] or f"/ledigt/detalj/id/{object_id}"
        return RentalListing(
            area=area,
            street=street,
            number_of_rooms=rooms_str,
            rent_cost=rent,
            size=size_str,
            url=urljoin(cls.BASE_URL, details),
            source=cls.SOURCE_NAME,
            # A re-publication of the same apartment gets a new ShowDateStart,
            # and must be reported again, so the date is part of the identity.
            key=f"wahlin:{object_id}:{show_start}",
            object_id=object_id,
            published_until=show_end or None,
            lottery=bool(obj.get('ShowRandomSort')) if obj.get('ShowRandomSort') is not None else None,
            move_in=move_in or None,
        )


# --------------------------------------------------------------------------
# Wåhlin - public WordPress site (daily mirror of Arena; kept as fallback)
# --------------------------------------------------------------------------

class WahlinRentalScraper(BaseScraper):
    SOURCE_NAME = "wahlin"
    BASE_URL = "https://wahlinfastigheter.se"
    LISTINGS_URL = "https://wahlinfastigheter.se/hyr-av-oss/objekt/lagenhet/"
    THEME_MARKER = "wp-content/themes/wahlinfastigheter"
    # Slugs end with the object number, optionally followed by "-N" for re-publications.
    OBJECT_ID_RE = re.compile(r'/(?:[a-z0-9-]+?-)?(\d{3}-(?:\d-)?\d{3,4})(?:-\d+)?/?$')

    def url(self) -> str:
        return self.LISTINGS_URL

    def _parse(self, response: requests.Response) -> List[RentalListing]:
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        listings = self.parse_html(soup)
        if not listings and self.THEME_MARKER not in html:
            raise ShapeChanged("no listings and theme marker missing")
        return listings

    @classmethod
    def parse_html(cls, soup: BeautifulSoup) -> List[RentalListing]:
        listings = []
        articles = soup.find_all('article', class_=lambda c: c and 'group/item' in c)

        for article in articles:
            try:
                area_link = article.find('a', href=lambda h: h and '/omrade/' in h)
                area = area_link.get_text(strip=True) if area_link else "Unknown"

                street_elem = article.find('h2')
                street = street_elem.get_text(strip=True) if street_elem else "Unknown"

                details = {}
                dl = article.find('dl')
                if dl:
                    for dt, dd in zip(dl.find_all('dt'), dl.find_all('dd')):
                        details[dt.get_text(strip=True)] = dd.get_text(strip=True)

                url_link = article.find('a', href=lambda h: h and '/lediga-objekt/' in h)
                url = urljoin(cls.BASE_URL, url_link['href']) if url_link else None
                if not url:
                    continue

                m = cls.OBJECT_ID_RE.search(url)
                listings.append(RentalListing(
                    area=area,
                    street=street,
                    number_of_rooms=details.get('Antal rum', 'N/A'),
                    rent_cost=details.get('Hyra (kr/mån)', 'N/A'),
                    size=details.get('Area', 'N/A'),
                    url=url,
                    source=cls.SOURCE_NAME,
                    object_id=m.group(1) if m else None,
                ))
            except Exception as e:
                logger.error(f"Error parsing listing: {e}")

        return listings


# --------------------------------------------------------------------------
# Wallfast - SiteVision site (apartments let via the web are published
# weekdays 11:00-14:00 and can disappear within minutes)
# --------------------------------------------------------------------------

class WallfastRentalScraper(BaseScraper):
    SOURCE_NAME = "wallfast"
    BASE_URL = "https://wallfast.com"
    LISTINGS_URL = "https://wallfast.com/lediga-objekt"

    def url(self) -> str:
        return self.LISTINGS_URL

    def _parse(self, response: requests.Response) -> List[RentalListing]:
        html = response.text
        soup = BeautifulSoup(html, 'html.parser')
        listings = self.parse_html(soup)
        if not listings:
            title = (soup.title.get_text() if soup.title else '').lower()
            if 'lediga objekt' not in title and 'sv-channel' not in html:
                raise ShapeChanged(f"no listings and page title is {title!r}")
        return listings

    @classmethod
    def parse_html(cls, soup: BeautifulSoup) -> List[RentalListing]:
        listings = []
        items = soup.find_all('li', class_=lambda c: c and 'sv-channel-item' in c)

        for item in items:
            try:
                heading = item.find('div', class_='men-startpage--newslist-item--heading')
                link = heading.find('a') if heading else item.find('a', href=True)
                if not link:
                    continue

                title = link.get_text(strip=True)
                url = urljoin(cls.BASE_URL, link.get('href', ''))

                size_match = re.search(r'(\d+(?:,\d+)?)\s*kvm', title, re.IGNORECASE)
                size = f"{size_match.group(1)} kvm" if size_match else "N/A"

                parts = title.split()
                area = parts[-1] if len(parts) > 1 and not parts[-1].lower().endswith('kvm') else "Stockholm"

                listings.append(RentalListing(
                    area=area,
                    street=title,
                    number_of_rooms="N/A",
                    rent_cost="N/A",
                    size=size,
                    url=url,
                    source=cls.SOURCE_NAME,
                    lottery=True,  # Wallfast draws lots for apartments advertised on the web
                ))
            except Exception as e:
                logger.error(f"Error parsing listing: {e}")

        return listings


SCRAPERS = {
    WahlinArenaScraper.SOURCE_NAME: WahlinArenaScraper,
    WahlinRentalScraper.SOURCE_NAME: WahlinRentalScraper,
    WallfastRentalScraper.SOURCE_NAME: WallfastRentalScraper,
}
