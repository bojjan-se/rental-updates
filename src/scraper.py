import requests
from bs4 import BeautifulSoup
from typing import List, Optional
import logging
import time
from urllib.parse import urljoin

from .models import RentalListing

logger = logging.getLogger(__name__)

class WahlinRentalScraper:
    """Scraper for Wåhlin Fastigheter rental listings"""

    BASE_URL = "https://wahlinfastigheter.se"
    LISTINGS_URL = "https://wahlinfastigheter.se/hyr-av-oss/objekt/lagenhet/"

    def __init__(self, delay: float = 1.0, max_retries: int = 3):
        self.delay = delay
        self.max_retries = max_retries
        self.session = requests.Session()
        # Set a realistic user agent
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

    def _make_request(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Make HTTP request with retry logic"""
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, timeout=30, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                if attempt == self.max_retries - 1:
                    logger.error(f"Failed to fetch {url} after {self.max_retries} attempts: {e}")
                    return None
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                time.sleep(self.delay * (attempt + 1))  # Exponential backoff
        return None

    def scrape_listings(self) -> List[RentalListing]:
        """Scrape all rental listings from the main page"""
        logger.info(f"Starting scrape of {self.LISTINGS_URL}")

        response = self._make_request(self.LISTINGS_URL)
        if not response:
            return []

        try:
            soup = BeautifulSoup(response.content, 'html.parser')
            listings = self._parse_listings(soup)

            logger.info(f"Successfully scraped {len(listings)} listings")
            return listings

        except Exception as e:
            logger.error(f"Failed to parse listings: {e}")
            return []

    def _parse_listings(self, soup: BeautifulSoup) -> List[RentalListing]:
        """Parse rental listings from BeautifulSoup object"""
        listings = []

        # Find all article elements containing listings
        articles = soup.find_all('article', class_=lambda classes: classes and 'flex' in classes and 'overflow-hidden' in classes and 'flex-col' in classes and 'group/item' in classes)

        for article in articles:
            listing = self._parse_single_listing(article)
            if listing:
                listings.append(listing)
                # Only sleep if we're going to make additional requests
                # For now, we don't sleep here since we're parsing from one page

        return listings

    def _parse_single_listing(self, article) -> Optional[RentalListing]:
        """Parse a single rental listing from an article element"""
        try:
            # Extract area (neighborhood)
            area_link = article.find('a', href=lambda href: href and '/omrade/' in href)
            area = area_link.get_text(strip=True) if area_link else None

            # Extract street address
            street_elem = article.find('h2')
            street = street_elem.get_text(strip=True) if street_elem else None

            # Extract details from dl/dt/dd structure
            details = {}
            dl = article.find('dl')
            if dl:
                dts = dl.find_all('dt')
                dds = dl.find_all('dd')

                for dt, dd in zip(dts, dds):
                    key = dt.get_text(strip=True)
                    value = dd.get_text(strip=True)
                    details[key] = value

            # Extract specific fields
            rooms = details.get('Antal rum')
            rent = details.get('Hyra (kr/mån)')
            size = details.get('Area')

            # Extract URL if available
            url = None
            read_more_link = article.find('a', href=lambda href: href and '/lediga-objekt/' in href)
            if read_more_link:
                url = urljoin(self.BASE_URL, read_more_link['href'])

            # Use defaults for missing data to be more lenient
            if not area:
                area = "Unknown"
            if not street:
                street = "Unknown Address"
            if not rooms:
                rooms = "N/A"
            if not rent:
                rent = "N/A"
            if not size:
                size = "N/A"

            # Only skip if we have no basic identifying information
            if not url and street == "Unknown Address":
                logger.warning(f"Skipping listing with no URL and no address: {area}")
                return None

            return RentalListing(
                area=area,
                street=street,
                number_of_rooms=rooms,
                rent_cost=rent,
                size=size,
                url=url,
                source="wahlin"
            )

        except Exception as e:
            logger.error(f"Error parsing listing: {e}")
            return None


class WallfastRentalScraper:
    """Scraper for Wallfast rental listings"""

    BASE_URL = "https://wallfast.com"
    LISTINGS_URL = "https://wallfast.com/lediga-objekt"

    def __init__(self, delay: float = 1.0, max_retries: int = 3):
        self.delay = delay
        self.max_retries = max_retries
        self.session = requests.Session()
        # Set a realistic user agent
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

    def _make_request(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Make HTTP request with retry logic"""
        for attempt in range(self.max_retries):
            try:
                response = self.session.get(url, timeout=30, **kwargs)
                response.raise_for_status()
                return response
            except requests.RequestException as e:
                if attempt == self.max_retries - 1:
                    logger.error(f"Failed to fetch {url} after {self.max_retries} attempts: {e}")
                    return None
                logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
                time.sleep(self.delay * (attempt + 1))  # Exponential backoff
        return None

    def scrape_listings(self) -> List[RentalListing]:
        """Scrape all rental listings from Wallfast"""
        logger.info(f"Starting scrape of {self.LISTINGS_URL}")

        response = self._make_request(self.LISTINGS_URL)
        if not response:
            return []

        try:
            soup = BeautifulSoup(response.content, 'html.parser')
            listings = self._parse_listings(soup)

            logger.info(f"Successfully scraped {len(listings)} listings")
            return listings

        except Exception as e:
            logger.error(f"Failed to parse listings: {e}")
            return []

    def _parse_listings(self, soup: BeautifulSoup) -> List[RentalListing]:
        """Parse rental listings from BeautifulSoup object"""
        listings = []

        # Find the listings container
        listings_ul = soup.find('ul', class_='sv-channel sv-defaultlist')
        if not listings_ul:
            logger.warning("No listings container found")
            return listings

        # Find all list items containing listings
        listing_items = listings_ul.find_all('li', class_=lambda classes: classes and 'sv-channel-item' in classes)

        for item in listing_items:
            listing = self._parse_single_listing(item)
            if listing:
                listings.append(listing)
                # Sleep between processing items to be respectful
                time.sleep(self.delay)

        return listings

    def _parse_single_listing(self, item) -> Optional[RentalListing]:
        """Parse a single rental listing from a list item"""
        try:
            # Find the main listing container
            listing_div = item.find('div', class_='men-startpage--newslist-item')
            if not listing_div:
                return None

            # Extract date
            date_elem = listing_div.find('time')
            date_published = None
            if date_elem and date_elem.get('datetime'):
                # Parse the datetime attribute (ISO format)
                from datetime import datetime
                try:
                    date_published = datetime.fromisoformat(date_elem['datetime'].replace('Z', '+00:00'))
                except:
                    pass

            # Extract title and URL
            heading_div = listing_div.find('div', class_='men-startpage--newslist-item--heading')
            if not heading_div:
                return None

            title_link = heading_div.find('a')
            if not title_link:
                return None

            title = title_link.get_text(strip=True)
            relative_url = title_link.get('href')
            if relative_url:
                url = urljoin(self.BASE_URL, relative_url)
            else:
                url = None

            # For Wallfast, parse the title to extract meaningful data
            parsed_data = self._parse_title(title)

            if not parsed_data:
                logger.warning(f"Could not parse title: {title}")
                return None

            # Wallfast doesn't provide detailed room/rent/size info on main page
            # Use parsed data or defaults
            area = parsed_data.get('area', 'Wallfast')
            street = parsed_data.get('street', title)
            rooms = parsed_data.get('rooms', 'N/A')
            rent = parsed_data.get('rent', 'N/A')
            size = parsed_data.get('size', 'N/A')

            # Try to get more details from the individual listing page
            if url:
                detailed_data = self._scrape_listing_details(url)
                if detailed_data:
                    rooms = detailed_data.get('rooms', rooms)
                    rent = detailed_data.get('rent', rent)
                    size = detailed_data.get('size', size)

            return RentalListing(
                area=area,
                street=street,
                number_of_rooms=rooms,
                rent_cost=rent,
                size=size,
                url=url,
                source="wallfast"
            )

        except Exception as e:
            logger.error(f"Error parsing listing: {e}")
            return None

    def _parse_title(self, title: str) -> Optional[dict]:
        """Parse listing title to extract structured data"""
        # Wallfast titles vary in format. Common patterns:
        # "Radhus och lägenheter Munsö" -> area: "Munsö", type: "Radhus och lägenheter"
        # "Ledigt förråd 4,2 kvm" -> type: "Förråd", size: "4,2 kvm"

        try:
            result = {}

            # Look for size information (e.g., "4,2 kvm", "87 kvm")
            import re
            size_match = re.search(r'(\d+(?:,\d+)?)\s*kvm', title, re.IGNORECASE)
            if size_match:
                result['size'] = f"{size_match.group(1)} kvm"

            # Extract location/area (usually at the end)
            # Split by common delimiters and take the last meaningful part
            parts = re.split(r'[-\s]+', title.strip())
            if len(parts) > 1:
                # Last part is often the location
                potential_area = parts[-1]
                if len(potential_area) > 2 and not potential_area.isdigit():
                    result['area'] = potential_area
                else:
                    result['area'] = 'Stockholm'

            result['street'] = title  # Use full title as street description

            return result

        except Exception as e:
            logger.error(f"Error parsing title '{title}': {e}")
            return None

    def _scrape_listing_details(self, url: str) -> Optional[dict]:
        """Scrape additional details from individual listing page"""
        try:
            time.sleep(self.delay)  # Be respectful
            response = self._make_request(url)
            if not response:
                return None

            soup = BeautifulSoup(response.content, 'html.parser')

            details = {}

            # Look for structured data in the page content
            # Wallfast might have different page structures, so we'll be flexible

            # Try to find text content that looks like rental details
            text_content = soup.get_text()

            # Look for room count patterns
            import re
            room_match = re.search(r'(\d+)\s*rum|(\d+)\s*rok', text_content, re.IGNORECASE)
            if room_match:
                rooms = room_match.group(1) or room_match.group(2)
                details['rooms'] = f"{rooms} rok"

            # Look for rent patterns
            rent_match = re.search(r'(\d+(?:\s*\d+)*)\s*kr|hyra:?\s*(\d+(?:\s*\d+)*)', text_content, re.IGNORECASE)
            if rent_match:
                rent = (rent_match.group(1) or rent_match.group(2)).replace(' ', '')
                details['rent'] = f"{rent} kr"

            # Look for size patterns (if not already found in title)
            if 'size' not in details:
                size_match = re.search(r'(\d+(?:,\d+)?)\s*kvm|area:?\s*(\d+(?:,\d+)?)', text_content, re.IGNORECASE)
                if size_match:
                    size = size_match.group(1) or size_match.group(2)
                    details['size'] = f"{size} kvm"

            return details if details else None

        except Exception as e:
            logger.error(f"Error scraping details from {url}: {e}")
            return None
