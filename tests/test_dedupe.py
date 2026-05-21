from datetime import datetime

from realestate.dedupe import filter_multi_listing_sellers
from realestate.sources.base import Listing


def _make(listing_id: str, phone: str | None = None, email: str | None = None) -> Listing:
    now = datetime.utcnow()
    return Listing(
        listing_id=listing_id, source="clasificados", type="sale", price=200_000,  # type: ignore[arg-type]
        beds=3, baths=2, sqft=1200, lot_sqft=None,
        address=f"addr {listing_id}", city="San Juan", zip_code=None, lat=None, lng=None,
        url=f"https://example.invalid/{listing_id}",
        scraped_at=now, first_seen=now, listed_at=None,
        owner_name=f"Owner {listing_id}", phone=phone, email=email,
        description=None, outreach_status="none", last_contacted_at=None, notes=None,
    )


def test_multi_phone_rejected():
    listings = [
        _make("a", phone="787-555-0100"),
        _make("b", phone="787-555-0100"),
        _make("c", phone="787-555-0200"),
        _make("d", phone=None),
    ]
    result = filter_multi_listing_sellers(listings)
    kept_ids = sorted(l.listing_id for l in result.kept)
    assert kept_ids == ["c", "d"]
    assert len(result.rejected) == 2


def test_multi_email_rejected():
    listings = [
        _make("a", email="x@example.com"),
        _make("b", email="x@example.com"),
        _make("c", email="y@example.com"),
    ]
    result = filter_multi_listing_sellers(listings)
    kept_ids = sorted(l.listing_id for l in result.kept)
    assert kept_ids == ["c"]


def test_no_contact_passes_through():
    """Zillow listings have no phone or email — should not be filtered."""
    listings = [
        _make("a", phone=None, email=None),
        _make("b", phone=None, email=None),
        _make("c", phone=None, email=None),
    ]
    result = filter_multi_listing_sellers(listings)
    assert len(result.kept) == 3
    assert len(result.rejected) == 0
