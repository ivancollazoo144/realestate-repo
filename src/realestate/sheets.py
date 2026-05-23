from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable

import gspread
from gspread.exceptions import SpreadsheetNotFound, WorksheetNotFound

from .config import CONFIG, Config
from .google_auth import get_credentials
from .sources.base import Listing  # noqa: F401 — used in rebuild_listings_grouped type hint

LISTING_HEADERS: list[str] = [
    "listing_id", "source", "type", "price", "beds", "baths", "sqft", "lot_sqft",
    "address", "city", "zip_code", "lat", "lng", "url",
    "scraped_at", "first_seen", "listed_at",
    "owner_name", "phone", "email", "description",
    "outreach_status", "last_contacted_at", "notes",
]

SMS_HEADERS: list[str] = [
    "listing_id", "phone", "message", "listing_url", "drafted_at", "status",
]


def _col_letter(n: int) -> str:
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


def _to_cell(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _listing_to_row(listing: Listing) -> list[str]:
    return [
        _to_cell(listing.listing_id), _to_cell(listing.source), _to_cell(listing.type),
        _to_cell(listing.price), _to_cell(listing.beds), _to_cell(listing.baths),
        _to_cell(listing.sqft), _to_cell(listing.lot_sqft),
        _to_cell(listing.address), _to_cell(listing.city), _to_cell(listing.zip_code),
        _to_cell(listing.lat), _to_cell(listing.lng), _to_cell(listing.url),
        _to_cell(listing.scraped_at), _to_cell(listing.first_seen), _to_cell(listing.listed_at),
        _to_cell(listing.owner_name), _to_cell(listing.phone), _to_cell(listing.email),
        _to_cell(listing.description),
        _to_cell(listing.outreach_status), _to_cell(listing.last_contacted_at),
        _to_cell(listing.notes),
    ]


class SheetsClient:
    def __init__(self, config: Config = CONFIG):
        self.config = config
        self.creds = get_credentials(config)
        self.gc = gspread.authorize(self.creds)
        self.wb = self._ensure_workbook()
        self.listings_ws = self._ensure_worksheet(
            config.sheet_tab_listings, LISTING_HEADERS
        )
        self.sms_ws = self._ensure_worksheet(
            config.sheet_tab_sms_drafts, SMS_HEADERS
        )

    @property
    def workbook_url(self) -> str:
        return self.wb.url

    def _ensure_workbook(self) -> gspread.Spreadsheet:
        name = self.config.sheet_workbook_name
        try:
            return self.gc.open(name)
        except SpreadsheetNotFound:
            return self.gc.create(name)

    def _ensure_worksheet(self, title: str, headers: list[str]) -> gspread.Worksheet:
        try:
            ws = self.wb.worksheet(title)
        except WorksheetNotFound:
            ws = self.wb.add_worksheet(title=title, rows=1000, cols=max(len(headers), 10))
            ws.update(values=[headers], range_name="A1")
            ws.freeze(rows=1)
            return ws
        first_row = ws.row_values(1)
        if not first_row:
            ws.update(values=[headers], range_name="A1")
            ws.freeze(rows=1)
        return ws

    def _listing_row_index(self) -> dict[str, int]:
        col_a = self.listings_ws.col_values(1)
        return {lid: i for i, lid in enumerate(col_a[1:], start=2) if lid}

    def upsert_listings(self, listings: Iterable[Listing]) -> tuple[int, int]:
        """Insert new listings, update existing ones. Returns (inserted, updated)."""
        index = self._listing_row_index()
        new_rows: list[list[str]] = []
        update_batches: list[dict[str, Any]] = []
        inserted = updated = 0
        last_col = _col_letter(len(LISTING_HEADERS))

        for listing in listings:
            row = _listing_to_row(listing)
            if listing.listing_id in index:
                row_num = index[listing.listing_id]
                update_batches.append({
                    "range": f"A{row_num}:{last_col}{row_num}",
                    "values": [row],
                })
                updated += 1
            else:
                new_rows.append(row)
                inserted += 1

        if update_batches:
            self.listings_ws.batch_update(update_batches, value_input_option="USER_ENTERED")
        if new_rows:
            self.listings_ws.append_rows(new_rows, value_input_option="USER_ENTERED")

        return inserted, updated

    def append_sms_drafts(self, drafts: Iterable[dict[str, Any]]) -> int:
        rows = [[_to_cell(d.get(h)) for h in SMS_HEADERS] for d in drafts]
        if rows:
            self.sms_ws.append_rows(rows, value_input_option="USER_ENTERED")
        return len(rows)

    def clear_listings_data(self) -> int:
        """Delete all data rows in the Listings tab. Headers stay. Returns rows removed."""
        last = len(self.listings_ws.col_values(1))
        if last > 1:
            self.listings_ws.delete_rows(2, last)
            return last - 1
        return 0

    def rebuild_listings_grouped(self, listings: list[Listing]) -> tuple[int, int]:
        """Clear the Listings tab and rewrite, grouped by first_seen date.

        Newest date appears first. Within each day group, sorted by source
        then by price desc. A divider row separates each date group.

        Returns (date_groups, total_rows_written) — total includes dividers.
        """
        self.clear_listings_data()

        if not listings:
            return 0, 0

        by_date: dict[str, list[Listing]] = {}
        for l in listings:
            key = l.first_seen.date().isoformat() if l.first_seen else "(unknown)"
            by_date.setdefault(key, []).append(l)

        rows: list[list[str]] = []
        for date_key in sorted(by_date.keys(), reverse=True):
            group = sorted(
                by_date[date_key],
                key=lambda x: (x.source, -(x.price or 0)),
            )
            divider_text = f"═══  {date_key}  —  {len(group)} listings  ═══"
            divider_row = [divider_text] + [""] * (len(LISTING_HEADERS) - 1)
            rows.append(divider_row)
            for l in group:
                rows.append(_listing_to_row(l))

        if rows:
            self.listings_ws.append_rows(rows, value_input_option="USER_ENTERED")

        return len(by_date), len(rows)
