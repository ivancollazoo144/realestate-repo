from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from selectolax.parser import HTMLParser

from typing import Any

from .config import CONFIG
from .enrich import extract_emails, extract_phones, looks_like_realtor
from .sources.base import Listing, RawListing

PRICE_RE = re.compile(r"\$\s*([\d,]+)")
SQFT_RE = re.compile(r"([\d,]+)\s*p/c", re.IGNORECASE)
LISTING_ID_LABEL = "Clasificado #"
CONTACT_ANCHOR = "Contacta al vendedor"
CALL_PREFIX = "Llamar"

PROPERTY_TYPES = {"Casa", "Apartamento", "Finca", "Terreno", "Solar", "Multi-Familiar", "Estudio"}


@dataclass
class ParseResult:
    """Either a Listing, or a structured rejection (e.g. broker-listed)."""

    listing: Listing | None
    rejected: bool = False
    reason: str | None = None
    seller_name: str | None = None


def _lines(html: str) -> list[str]:
    tree = HTMLParser(html)
    if not tree.body:
        return []
    text = tree.body.text(separator="\n")
    return [l.strip() for l in text.splitlines() if l.strip()]


def _find_anchor(lines: list[str], substr: str) -> int | None:
    for i, l in enumerate(lines):
        if substr in l:
            return i
    return None


def _parse_number_after(lines: list[str], idx: int, label: str) -> float | None:
    """Pattern: 'Cuartos' on line idx, '- 3' or '- 3+' on idx+1. Returns float (3.0)."""
    if idx is None or idx >= len(lines):
        return None
    nxt = lines[idx + 1] if idx + 1 < len(lines) else ""
    m = re.search(r"-\s*(\d+)(?:\s*1/2)?(?:\s*\+)?", nxt)
    if not m:
        return None
    base = float(m.group(1))
    if "1/2" in nxt:
        base += 0.5
    return base


def normalize_clasificados(raw: RawListing) -> ParseResult:
    """Parse a Clasificados Online UD detail page into a Listing.

    Returns a ParseResult — either a populated Listing, or a rejection (broker-listed
    or unparseable). Caller should log rejections to the zillow_filtered table
    equivalent (or skip for now).
    """
    html = raw.raw_html or ""
    if len(html) < 50_000:
        return ParseResult(listing=None, rejected=True, reason="placeholder_page")

    lines = _lines(html)
    if not lines:
        return ParseResult(listing=None, rejected=True, reason="empty_body")

    # Anchor on the contact block
    contact_idx = _find_anchor(lines, CONTACT_ANCHOR)
    if contact_idx is None:
        return ParseResult(listing=None, rejected=True, reason="no_contact_block")

    listing_id_idx = _find_anchor(lines, LISTING_ID_LABEL)

    # Title — first line that looks like content after nav. Use the line before "en" + city sequence.
    title = None
    city = None
    en_idx = None
    for i, l in enumerate(lines[: contact_idx]):
        if l == "en" and i + 2 < len(lines) and lines[i + 2] == "Puerto Rico":
            en_idx = i
            city = lines[i + 1]
            # Title is the line just before the "," / "en" group
            if i >= 2:
                title = lines[i - 2] if lines[i - 1] == "," else lines[i - 1]
            break

    # Property type — line after "Puerto Rico"
    prop_type = None
    if en_idx is not None:
        for j in range(en_idx + 3, min(en_idx + 8, contact_idx)):
            if lines[j] in PROPERTY_TYPES:
                prop_type = lines[j]
                break

    # Beds / baths
    beds = _parse_number_after(lines, _find_anchor(lines[:contact_idx], "Cuartos"), "Cuartos")
    baths = _parse_number_after(lines, _find_anchor(lines[:contact_idx], "Baños"), "Baños")

    # Price — first line with $ pattern, scanning forward from city to contact block
    price: int | None = None
    for l in lines[en_idx or 0 : contact_idx]:
        m = PRICE_RE.search(l)
        if m:
            try:
                price = int(m.group(1).replace(",", ""))
                break
            except ValueError:
                pass

    # Sqft
    sqft: int | None = None
    for l in lines[en_idx or 0 : contact_idx + 5]:
        m = SQFT_RE.search(l)
        if m:
            try:
                sqft = int(m.group(1).replace(",", ""))
                break
            except ValueError:
                pass

    # Realtor/company name: line directly before contact anchor sometimes holds it
    realtor_company = None
    if contact_idx >= 1:
        candidate = lines[contact_idx - 1]
        if candidate not in {",", "Y"} and len(candidate) > 2:
            is_r, _ = looks_like_realtor(candidate)
            if is_r:
                realtor_company = candidate

    # Seller name — line after contact anchor
    seller_name = lines[contact_idx + 1] if contact_idx + 1 < len(lines) else None

    # Phone — line starting with "Llamar"
    phone = None
    for l in lines[contact_idx : contact_idx + 6]:
        if l.startswith(CALL_PREFIX):
            phones = extract_phones(l)
            if phones:
                phone = phones[0]
                break

    # Description — block after listing ID, before next sponsor/footer marker
    description = None
    if listing_id_idx is not None and listing_id_idx + 2 < len(lines):
        desc_start = listing_id_idx + 2
        if lines[desc_start] == seller_name and desc_start + 1 < len(lines):
            desc_start += 1
        desc_lines: list[str] = []
        for l in lines[desc_start : desc_start + 50]:
            if any(stop in l for stop in ("Evite el Fraude", "Anuncios Similares", "Reportar")):
                break
            desc_lines.append(l)
        description = "\n".join(desc_lines).strip() or None

    # Look for email anywhere in description
    email = None
    if description:
        emails = extract_emails(description)
        if emails:
            email = emails[0]

    # Realtor filter — either pre-anchor company line OR seller name heuristic
    seller_is_realtor, kw = looks_like_realtor(seller_name)
    if realtor_company:
        return ParseResult(
            listing=None,
            rejected=True,
            reason=f"realtor_company:{realtor_company[:80]}",
            seller_name=seller_name,
        )
    if seller_is_realtor:
        return ParseResult(
            listing=None,
            rejected=True,
            reason=f"realtor_keyword:{kw}",
            seller_name=seller_name,
        )

    if price is not None and price < CONFIG.min_sale_price:
        return ParseResult(
            listing=None,
            rejected=True,
            reason=f"below_min_price:${price:,}",
            seller_name=seller_name,
        )

    now = raw.fetched_at or datetime.utcnow()
    listing_type = "sale"  # /UDRealEstateDetail.asp is sales-only

    listing = Listing(
        listing_id=Listing.make_id(raw.source, raw.native_id),
        source=raw.source,
        type=listing_type,
        price=price,
        beds=beds,
        baths=baths,
        sqft=sqft,
        lot_sqft=None,
        address=title,
        city=city,
        zip_code=None,
        lat=None,
        lng=None,
        url=raw.url,
        scraped_at=now,
        first_seen=now,
        listed_at=None,
        owner_name=seller_name,
        phone=phone,
        email=email,
        description=description,
        outreach_status="none",
        last_contacted_at=None,
        notes=None if not prop_type else f"type={prop_type}",
    )
    return ParseResult(listing=listing)


PR_ADDRESS_RE = re.compile(r",\s*([^,]+),\s*PR\s*(\d{5})?\s*$", re.IGNORECASE)


def _parse_pr_address(address: str) -> tuple[str | None, str | None, str | None]:
    """Split 'Carr 103 Camino, Cabo Rojo, PR 00623' into (street, city, zip)."""
    if not address:
        return None, None, None
    m = PR_ADDRESS_RE.search(address)
    if m:
        city = m.group(1).strip()
        zip_code = m.group(2)
        street = address[: m.start()].strip().rstrip(",")
        return street or None, city or None, zip_code
    # Fallback: split on commas
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) >= 2:
        return parts[0], parts[1], None
    return address, None, None


def normalize_zillow(raw: RawListing) -> ParseResult:
    """Parse a Zillow RapidAPI search-result item into a Listing.

    FSBO/FRBO filter: brokerage field empty == owner-listed. Anything else is a
    brokerage we want to skip.
    """
    data: dict[str, Any] | None = raw.raw_json
    if not data:
        return ParseResult(listing=None, rejected=True, reason="no_data")

    brokerage = (data.get("brokerage") or "").strip()
    if brokerage:
        return ParseResult(
            listing=None,
            rejected=True,
            reason=f"brokered_by:{brokerage[:60]}",
            seller_name=brokerage,
        )

    list_type = data.get("_list_type", "for-sale")
    listing_type = "rent" if list_type == "for-rent" else "sale"

    price = None
    raw_price = data.get("price")
    if raw_price is not None:
        try:
            price = int(float(raw_price))
        except (TypeError, ValueError):
            pass

    threshold = CONFIG.min_rent_price if listing_type == "rent" else CONFIG.min_sale_price
    if price is not None and price < threshold:
        return ParseResult(
            listing=None,
            rejected=True,
            reason=f"below_min_price:${price:,}",
        )

    street, city, zip_code = _parse_pr_address(data.get("address", ""))

    def _num(key: str, cast: type) -> float | int | None:
        v = data.get(key)
        if v is None:
            return None
        try:
            return cast(v)
        except (TypeError, ValueError):
            return None

    now = raw.fetched_at or datetime.utcnow()
    listing = Listing(
        listing_id=Listing.make_id(raw.source, raw.native_id),
        source=raw.source,
        type=listing_type,  # type: ignore[arg-type]
        price=price,
        beds=_num("beds", float),
        baths=_num("baths", float),
        sqft=_num("sqft", int),
        lot_sqft=None,
        address=street,
        city=city,
        zip_code=zip_code,
        lat=_num("latitude", float),
        lng=_num("longitude", float),
        url=raw.url,
        scraped_at=now,
        first_seen=now,
        listed_at=None,
        owner_name=None,  # Zillow API does not expose owner contact
        phone=None,
        email=None,
        description=None,
        outreach_status="none",
        last_contacted_at=None,
        notes=f"property_type={data.get('property_type')}" if data.get("property_type") else None,
    )
    return ParseResult(listing=listing)
