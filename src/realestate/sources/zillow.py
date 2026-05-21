from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Iterable

import httpx

from ..config import CONFIG
from .base import RawListing, Source

logger = logging.getLogger(__name__)


class ZillowScraper:
    """Fetch FSBO sale + FRBO rent listings for PR from a RapidAPI Zillow endpoint.

    Calls the /bylocation endpoint with location=puerto-rico, separately for
    listType=for-sale and listType=for-rent. The API's free tier returns up to
    41 results per call and pagination does not appear to work, so we capture
    what the single call gives us and apply our own FSBO/FRBO filter on the
    `brokerage` field in normalize.py.
    """

    source: Source = "zillow"
    HOST = "zillow-com-live-data-scraper-api.p.rapidapi.com"
    URL = f"https://{HOST}/bylocation"
    LOCATION = "puerto-rico"

    def __init__(
        self,
        api_key: str | None = None,
        list_types: Iterable[str] = ("for-sale", "for-rent"),
        max_pages: int = 1,
    ) -> None:
        self.api_key = api_key or CONFIG.rapidapi_key
        if not self.api_key:
            raise RuntimeError("RAPIDAPI_KEY is not set in .env")
        self.list_types = tuple(list_types)
        self.max_pages = max_pages
        self.client = httpx.Client(
            timeout=30.0,
            headers={
                "x-rapidapi-key": self.api_key,
                "x-rapidapi-host": self.HOST,
            },
        )

    def __enter__(self) -> "ZillowScraper":
        return self

    def __exit__(self, *_: object) -> None:
        self.client.close()

    @staticmethod
    def _native_id(item: dict, url: str) -> str:
        zpid = item.get("zpid")
        if zpid is not None:
            return str(zpid)
        # /b/<slug>/ — apartment-building URLs. Use the whole slug for uniqueness;
        # the trailing token alone collides (e.g. "pr" state code).
        m = re.search(r"/b/([^/]+)/", url)
        if m:
            return f"b:{m.group(1)}"
        return url.rstrip("/").rsplit("/", 1)[-1] or url

    def fetch_index(self) -> list[RawListing]:
        results: list[RawListing] = []
        now = datetime.utcnow()
        seen_ids: set[str] = set()

        for list_type in self.list_types:
            min_price = (
                CONFIG.min_sale_price if list_type == "for-sale" else CONFIG.min_rent_price
            )
            for page in range(1, self.max_pages + 1):
                try:
                    r = self.client.get(
                        self.URL,
                        params={
                            "location": self.LOCATION,
                            "listType": list_type,
                            "page": page,
                            "minPrice": min_price,
                        },
                    )
                except httpx.HTTPError as e:
                    logger.error("zillow API error (%s, page %d): %s", list_type, page, e)
                    break

                if r.status_code != 200:
                    logger.error(
                        "zillow API non-200 (%s, page %d): %d %s",
                        list_type, page, r.status_code, r.text[:200],
                    )
                    break

                try:
                    data = r.json()
                except Exception as e:
                    logger.error("zillow API non-JSON response: %s", e)
                    break

                items = data.get("results") or []
                if not items:
                    break

                for item in items:
                    native_id = self._native_id(item, item.get("url", ""))
                    if native_id in seen_ids:
                        continue
                    seen_ids.add(native_id)
                    results.append(RawListing(
                        source=self.source,
                        native_id=native_id,
                        url=item.get("url", ""),
                        raw_json={"_list_type": list_type, **item},
                        fetched_at=now,
                    ))

        return results

    def fetch_detail(self, raw: RawListing) -> RawListing:
        return raw
