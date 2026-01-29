from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime

@dataclass
class RentalListing:
    """Data model for a rental listing"""
    area: str
    street: str
    number_of_rooms: str  # e.g., "3 rok"
    rent_cost: str  # e.g., "13 531 kr"
    size: str  # e.g., "87 kvm"
    url: Optional[str] = None
    scraped_at: Optional[datetime] = None
    source: Optional[str] = None  # Track which website this listing came from

    def __post_init__(self):
        if self.scraped_at is None:
            self.scraped_at = datetime.now()

    @property
    def rent_amount(self) -> Optional[int]:
        """Extract numeric rent amount"""
        try:
            # Handle various formats: "13 531 kr", "13531kr", "13531"
            cleaned = self.rent_cost.replace(" ", "").replace("kr", "").replace(":-", "")
            return int(cleaned) if cleaned.isdigit() else None
        except (ValueError, AttributeError):
            return None

    @property
    def size_sqm(self) -> Optional[int]:
        """Extract numeric size in square meters"""
        try:
            # Handle various formats: "87 kvm", "87,5 kvm", "87kvm"
            cleaned = self.size.replace(" ", "").replace("kvm", "").replace(",", ".")
            return int(float(cleaned)) if cleaned.replace(".", "").isdigit() else None
        except (ValueError, AttributeError):
            return None

    @property
    def rooms_count(self) -> Optional[int]:
        """Extract numeric room count"""
        try:
            # Handle various formats: "3 rok", "3rum", "3"
            cleaned = self.number_of_rooms.replace(" ", "").replace("rok", "").replace("rum", "")
            return int(cleaned) if cleaned.isdigit() else None
        except (ValueError, AttributeError):
            return None

    def dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'source': self.source,
            'area': self.area,
            'street': self.street,
            'number_of_rooms': self.number_of_rooms,
            'rent_cost': self.rent_cost,
            'size': self.size,
            'url': self.url,
            'scraped_at': self.scraped_at.isoformat() if self.scraped_at else None
        }
