"""Web scrapers for rental listings."""

import re
import time
import logging
from abc import ABC, abstractmethod
from typing import List, Optional
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .models import RentalListing

logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    BASE_URL: str = ""
    LISTINGS_URL: str = ""
    SOURCE_NAME: str = ""

    def __init__(self, delay: float = 1.0):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'

    def _get(self, url: str) -> Optional[requests.Response]:
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def scrape_listings(self) -> List[RentalListing]:
        logger.info(f"Scraping {self.SOURCE_NAME}...")
        response = self._get(self.LISTINGS_URL)
        if not response:
            return []

        try:
            soup = BeautifulSoup(response.content, 'html.parser')
            listings = self._parse_listings(soup)
            logger.info(f"Found {len(listings)} listings from {self.SOURCE_NAME}")
            return listings
        except Exception as e:
            logger.error(f"Parse error: {e}")
            return []

    @abstractmethod
    def _parse_listings(self, soup: BeautifulSoup) -> List[RentalListing]:
        pass


class WahlinRentalScraper(BaseScraper):
    BASE_URL = "https://wahlinfastigheter.se"
    LISTINGS_URL = "https://wahlinfastigheter.se/hyr-av-oss/objekt/lagenhet/"
    SOURCE_NAME = "wahlin"

    def _parse_listings(self, soup: BeautifulSoup) -> List[RentalListing]:
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
                url = urljoin(self.BASE_URL, url_link['href']) if url_link else None

                if url:
                    listings.append(RentalListing(
                        area=area,
                        street=street,
                        number_of_rooms=details.get('Antal rum', 'N/A'),
                        rent_cost=details.get('Hyra (kr/mån)', 'N/A'),
                        size=details.get('Area', 'N/A'),
                        url=url,
                        source=self.SOURCE_NAME
                    ))
            except Exception as e:
                logger.error(f"Error parsing listing: {e}")

        return listings


class WallfastRentalScraper(BaseScraper):
    BASE_URL = "https://wallfast.com"
    LISTINGS_URL = "https://wallfast.com/lediga-objekt"
    SOURCE_NAME = "wallfast"

    def _parse_listings(self, soup: BeautifulSoup) -> List[RentalListing]:
        listings = []
        items = soup.find_all('li', class_=lambda c: c and 'sv-channel-item' in c)

        for item in items:
            try:
                heading = item.find('div', class_='men-startpage--newslist-item--heading')
                if not heading:
                    continue

                link = heading.find('a')
                if not link:
                    continue

                title = link.get_text(strip=True)
                url = urljoin(self.BASE_URL, link.get('href', ''))

                # Parse size from title
                size_match = re.search(r'(\d+(?:,\d+)?)\s*kvm', title, re.IGNORECASE)
                size = f"{size_match.group(1)} kvm" if size_match else "N/A"

                # Parse area from title (last word)
                parts = title.split()
                area = parts[-1] if len(parts) > 1 and not parts[-1].lower().endswith('kvm') else "Stockholm"

                listings.append(RentalListing(
                    area=area,
                    street=title,
                    number_of_rooms="N/A",
                    rent_cost="N/A",
                    size=size,
                    url=url,
                    source=self.SOURCE_NAME
                ))
            except Exception as e:
                logger.error(f"Error parsing listing: {e}")

        return listings
