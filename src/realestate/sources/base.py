from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

ListingType = Literal["sale", "rent"]
Source = Literal["clasificados", "zillow", "facebook"]
OutreachStatus = Literal["none", "drafted", "sent", "replied", "dead"]


@dataclass
class RawListing:
    """Pre-normalization payload from a source. The scraper produces this; normalize.py turns it into a Listing."""

    source: Source
    native_id: str
    url: str
    raw_html: str | None = None
    raw_json: dict | None = None
    fetched_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Listing:
    """Canonical listing schema — one row per listing in the sheet and DB."""

    listing_id: str  # f"{source}:{native_id}"
    source: Source
    type: ListingType
    price: int | None
    beds: float | None
    baths: float | None
    sqft: int | None
    lot_sqft: int | None
    address: str | None
    city: str | None
    zip_code: str | None
    lat: float | None
    lng: float | None
    url: str
    scraped_at: datetime
    first_seen: datetime
    listed_at: datetime | None
    owner_name: str | None
    phone: str | None
    email: str | None
    description: str | None
    outreach_status: OutreachStatus = "none"
    last_contacted_at: datetime | None = None
    notes: str | None = None

    @classmethod
    def make_id(cls, source: Source, native_id: str) -> str:
        return f"{source}:{native_id}"


@runtime_checkable
class Scraper(Protocol):
    """Each source implements this. fetch_index() returns shallow listing IDs; fetch_detail() enriches."""

    source: Source

    def fetch_index(self) -> list[RawListing]:
        """Return RawListings discovered from the source's search/listing pages. May have raw_html/json set."""
        ...

    def fetch_detail(self, raw: RawListing) -> RawListing:
        """Fetch and attach the detail page for a single listing. Returns the same RawListing with more data."""
        ...
