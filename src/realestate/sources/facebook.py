from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime

from ..config import CONFIG
from .base import RawListing, Source

logger = logging.getLogger(__name__)

PRICE_RE = re.compile(r"\$\s*([\d,]+)")
ITEM_ID_RE = re.compile(r"/marketplace/item/(\d+)/")

# Slug → display name. FB Marketplace city slugs are lowercase, no accents.
PR_CITIES: tuple[tuple[str, str], ...] = (
    ("sanjuan", "San Juan"),
    ("bayamon", "Bayamón"),
    ("carolina", "Carolina"),
    ("ponce", "Ponce"),
    ("caguas", "Caguas"),
    ("mayaguez", "Mayagüez"),
)

# Title must contain at least one of these to be considered real estate (and
# not a swimming pool / stove / generator that landed in /propertyforsale).
PROPERTY_TYPE_KEYWORDS: tuple[str, ...] = (
    "casa", "apartamento", "apartment", "apt", "house", "home",
    "condo", "condominio", "estudio", "studio", "loft", "townhouse",
    "duplex", "triplex", "finca", "terreno", "land", "lote", "solar",
    "villa", "penthouse", " ph ", "ph#", "ph-",
    "habitacion", "habitación", "cuarto", "bedroom", "br ", "br/",
    "alquilo", "alquiler", "rento", "renta", "for rent", "for sale",
    "se vende", "venta", "se renta",
)


class FacebookScraper:
    """Anonymous Playwright Firefox scrape of FB Marketplace PR property listings.

    Hits /marketplace/{city}/propertyforsale and /propertyrentals for the six
    largest PR municipios. Extracts listing cards directly from the index page —
    title, price, location, item URL. Pre-filters by price floor and property-
    type keyword in title before any per-listing detail fetch.

    Does NOT fetch detail pages by default (FB anonymously hides owner contact
    info anyway, and detail fetches dramatically increase bot-detection
    exposure). Description, if needed, comes in a later phase.
    """

    source: Source = "facebook"
    BASE = "https://www.facebook.com"

    def __init__(
        self,
        throttle_seconds: float = 3.0,
        jitter_seconds: float = 2.0,
        max_per_city_per_type: int = 24,
        headless: bool = True,
    ) -> None:
        self.throttle_seconds = throttle_seconds
        self.jitter_seconds = jitter_seconds
        self.max_per_city_per_type = max_per_city_per_type
        self.headless = headless

    def __enter__(self) -> "FacebookScraper":
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def _sleep(self) -> None:
        time.sleep(self.throttle_seconds + random.uniform(0, self.jitter_seconds))

    @staticmethod
    def _extract_item_id(url: str) -> str | None:
        m = ITEM_ID_RE.search(url)
        return m.group(1) if m else None

    @staticmethod
    def _extract_price(text: str) -> int | None:
        m = PRICE_RE.search(text)
        if not m:
            return None
        try:
            return int(m.group(1).replace(",", ""))
        except ValueError:
            return None

    @staticmethod
    def _looks_like_property(text: str) -> bool:
        lower = text.lower()
        return any(kw in lower for kw in PROPERTY_TYPE_KEYWORDS)

    def fetch_index(self) -> list[RawListing]:
        from playwright.sync_api import sync_playwright

        results: list[RawListing] = []
        seen_item_ids: set[str] = set()
        now = datetime.utcnow()

        with sync_playwright() as p:
            browser = p.firefox.launch(headless=self.headless)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:131.0) "
                    "Gecko/20100101 Firefox/131.0"
                ),
                viewport={"width": 1440, "height": 900},
                locale="en-US",
            )
            page = ctx.new_page()

            for city_slug, city_name in PR_CITIES:
                for list_type in ("propertyforsale", "propertyrentals"):
                    listing_type = "sale" if list_type == "propertyforsale" else "rent"
                    threshold = (
                        CONFIG.min_sale_price if listing_type == "sale" else CONFIG.min_rent_price
                    )
                    url = f"{self.BASE}/marketplace/{city_slug}/{list_type}"

                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=20000)
                        page.wait_for_timeout(2500)
                    except Exception as e:
                        logger.warning("fb index failed for %s: %s", url, e)
                        continue

                    cards = page.eval_on_selector_all(
                        'a[href*="/marketplace/item/"]',
                        "els => els.map(a => ({href: a.href, text: (a.innerText || '').trim()}))",
                    )

                    accepted_for_this_page = 0
                    for card in cards:
                        if accepted_for_this_page >= self.max_per_city_per_type:
                            break
                        item_id = self._extract_item_id(card["href"])
                        if not item_id or item_id in seen_item_ids:
                            continue

                        text = card["text"]
                        price = self._extract_price(text)
                        if price is None or price < threshold:
                            continue
                        if not self._looks_like_property(text):
                            continue

                        seen_item_ids.add(item_id)
                        accepted_for_this_page += 1

                        clean_url = card["href"].split("?")[0]

                        results.append(RawListing(
                            source=self.source,
                            native_id=item_id,
                            url=clean_url,
                            raw_json={
                                "_index_text": text,
                                "_index_price": price,
                                "_list_type": list_type,
                                "_listing_type": listing_type,
                                "_city": city_name,
                                "_city_slug": city_slug,
                            },
                            fetched_at=now,
                        ))

                    self._sleep()

            browser.close()

        return results

    def fetch_detail(self, raw: RawListing) -> RawListing:
        # No detail fetch in v1: index already has price + title + location,
        # and FB anonymously hides owner contact info on detail pages.
        return raw
