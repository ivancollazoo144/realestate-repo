from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime

import httpx
from selectolax.parser import HTMLParser

from .base import RawListing, Source

logger = logging.getLogger(__name__)


class ClasificadosScraper:
    """Scrape FSBO sale listings from Clasificados Online PR.

    Rentals are not scraped — all live FRBO inventory on the site funnels through
    broker partner pages; UD rental detail URLs return placeholder pages. See PLAN.md.
    """

    source: Source = "clasificados"
    BASE = "https://www.clasificadosonline.com"
    SALES_INDEX = "/RealEstate.asp"
    UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    )

    def __init__(
        self,
        throttle_seconds: float = 3.0,
        jitter_seconds: float = 2.0,
        max_listings: int | None = None,
    ) -> None:
        self.throttle_seconds = throttle_seconds
        self.jitter_seconds = jitter_seconds
        self.max_listings = max_listings
        self.client = httpx.Client(
            headers={"User-Agent": self.UA},
            timeout=30.0,
            follow_redirects=True,
        )

    def __enter__(self) -> "ClasificadosScraper":
        return self

    def __exit__(self, *_: object) -> None:
        self.client.close()

    def _sleep(self) -> None:
        delay = self.throttle_seconds + random.uniform(0, self.jitter_seconds)
        time.sleep(delay)

    def _fetch(self, path_or_url: str, referer: str | None = None) -> httpx.Response:
        url = path_or_url if path_or_url.startswith("http") else self.BASE + path_or_url
        headers: dict[str, str] = {}
        if referer:
            headers["Referer"] = referer
        r = self.client.get(url, headers=headers)
        r.raise_for_status()
        r.encoding = "iso-8859-1"
        return r

    def fetch_index(self) -> list[RawListing]:
        r = self._fetch(self.SALES_INDEX)
        tree = HTMLParser(r.text)
        ids: dict[str, None] = {}
        for a in tree.css("a"):
            href = a.attributes.get("href", "") or ""
            if "UDRealEstateDetail" not in href:
                continue
            m = re.search(r"ID=(\d+)", href)
            if m:
                ids.setdefault(m.group(1), None)

        unique_ids = list(ids.keys())
        if self.max_listings is not None:
            unique_ids = unique_ids[: self.max_listings]

        now = datetime.utcnow()
        return [
            RawListing(
                source=self.source,
                native_id=nid,
                url=f"{self.BASE}/UDRealEstateDetail.asp?ID={nid}",
                fetched_at=now,
            )
            for nid in unique_ids
        ]

    def fetch_detail(self, raw: RawListing) -> RawListing:
        self._sleep()
        r = self._fetch(raw.url, referer=self.BASE + self.SALES_INDEX)
        if len(r.content) < 50_000:
            # NoAdID placeholder page — listing expired or removed.
            logger.info("listing %s appears to be a placeholder (%d bytes)", raw.native_id, len(r.content))
            raw.raw_html = r.text
            return raw
        raw.raw_html = r.text
        raw.fetched_at = datetime.utcnow()
        return raw
