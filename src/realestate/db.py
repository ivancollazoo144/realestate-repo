from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from .config import CONFIG
from .sources.base import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    listing_id        TEXT PRIMARY KEY,
    source            TEXT NOT NULL,
    type              TEXT NOT NULL,
    price             INTEGER,
    beds              REAL,
    baths             REAL,
    sqft              INTEGER,
    lot_sqft          INTEGER,
    address           TEXT,
    city              TEXT,
    zip_code          TEXT,
    lat               REAL,
    lng               REAL,
    url               TEXT NOT NULL,
    scraped_at        TEXT NOT NULL,
    first_seen        TEXT NOT NULL,
    listed_at         TEXT,
    owner_name        TEXT,
    phone             TEXT,
    email             TEXT,
    description       TEXT,
    outreach_status   TEXT NOT NULL DEFAULT 'none',
    last_contacted_at TEXT,
    notes             TEXT
);
CREATE INDEX IF NOT EXISTS idx_listings_source ON listings(source);
CREATE INDEX IF NOT EXISTS idx_listings_phone  ON listings(phone);
CREATE INDEX IF NOT EXISTS idx_listings_email  ON listings(email);
CREATE INDEX IF NOT EXISTS idx_listings_first_seen ON listings(first_seen);

CREATE TABLE IF NOT EXISTS raw_listings (
    source       TEXT NOT NULL,
    native_id    TEXT NOT NULL,
    url          TEXT NOT NULL,
    raw_html     TEXT,
    raw_json     TEXT,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (source, native_id, fetched_at)
);

CREATE TABLE IF NOT EXISTS outreach_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id        TEXT NOT NULL,
    channel           TEXT NOT NULL CHECK (channel IN ('sms', 'email')),
    contact_value     TEXT NOT NULL,  -- phone or email actually used
    template_name     TEXT NOT NULL,
    message_body      TEXT NOT NULL,
    drafted_at        TEXT NOT NULL,
    sent_at           TEXT,           -- set manually after user sends
    status            TEXT NOT NULL DEFAULT 'drafted',
    FOREIGN KEY (listing_id) REFERENCES listings(listing_id)
);
CREATE INDEX IF NOT EXISTS idx_outreach_contact ON outreach_log(contact_value, drafted_at);

CREATE TABLE IF NOT EXISTS zillow_filtered (
    native_id    TEXT PRIMARY KEY,
    url          TEXT NOT NULL,
    reason       TEXT NOT NULL,        -- e.g. "realtor_keyword:LLC"
    seller_name  TEXT,
    filtered_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
"""

CURRENT_VERSION = 1


@contextmanager
def connect(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    path = db_path or CONFIG.db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)
        cur = conn.execute("SELECT MAX(version) FROM schema_version")
        current = cur.fetchone()[0]
        if current is None or current < CURRENT_VERSION:
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (CURRENT_VERSION, datetime.utcnow().isoformat()),
            )


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def upsert_listing(conn: sqlite3.Connection, listing: Listing) -> bool:
    """Insert if new, else update mutable fields. Returns True if this was a new listing."""
    cur = conn.execute("SELECT 1 FROM listings WHERE listing_id = ?", (listing.listing_id,))
    is_new = cur.fetchone() is None
    conn.execute(
        """
        INSERT INTO listings (
            listing_id, source, type, price, beds, baths, sqft, lot_sqft,
            address, city, zip_code, lat, lng, url,
            scraped_at, first_seen, listed_at,
            owner_name, phone, email, description,
            outreach_status, last_contacted_at, notes
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(listing_id) DO UPDATE SET
            price             = excluded.price,
            beds              = excluded.beds,
            baths             = excluded.baths,
            sqft              = excluded.sqft,
            lot_sqft          = excluded.lot_sqft,
            address           = COALESCE(excluded.address, listings.address),
            city              = COALESCE(excluded.city, listings.city),
            zip_code          = COALESCE(excluded.zip_code, listings.zip_code),
            lat               = COALESCE(excluded.lat, listings.lat),
            lng               = COALESCE(excluded.lng, listings.lng),
            url               = excluded.url,
            scraped_at        = excluded.scraped_at,
            listed_at         = COALESCE(excluded.listed_at, listings.listed_at),
            owner_name        = COALESCE(excluded.owner_name, listings.owner_name),
            phone             = COALESCE(excluded.phone, listings.phone),
            email             = COALESCE(excluded.email, listings.email),
            description       = COALESCE(excluded.description, listings.description)
        """,
        (
            listing.listing_id, listing.source, listing.type, listing.price,
            listing.beds, listing.baths, listing.sqft, listing.lot_sqft,
            listing.address, listing.city, listing.zip_code, listing.lat, listing.lng, listing.url,
            _iso(listing.scraped_at), _iso(listing.first_seen), _iso(listing.listed_at),
            listing.owner_name, listing.phone, listing.email, listing.description,
            listing.outreach_status, _iso(listing.last_contacted_at), listing.notes,
        ),
    )
    return is_new


def recent_contact_exists(conn: sqlite3.Connection, contact_value: str, cooldown_days: int) -> bool:
    """Returns True if we drafted/sent to this phone or email within the cooldown window."""
    cur = conn.execute(
        """
        SELECT 1 FROM outreach_log
        WHERE contact_value = ?
          AND drafted_at >= datetime('now', ?)
        LIMIT 1
        """,
        (contact_value, f"-{cooldown_days} days"),
    )
    return cur.fetchone() is not None


def log_outreach(
    conn: sqlite3.Connection,
    listing_id: str,
    channel: str,
    contact_value: str,
    template_name: str,
    message_body: str,
) -> None:
    conn.execute(
        """
        INSERT INTO outreach_log (listing_id, channel, contact_value, template_name, message_body, drafted_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (listing_id, channel, contact_value, template_name, message_body, datetime.utcnow().isoformat()),
    )


def _parse_dt(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


def all_listings(conn: sqlite3.Connection) -> list["Listing"]:
    cur = conn.execute("SELECT * FROM listings ORDER BY first_seen DESC")
    return [
        Listing(
            listing_id=r["listing_id"],
            source=r["source"],
            type=r["type"],
            price=r["price"],
            beds=r["beds"],
            baths=r["baths"],
            sqft=r["sqft"],
            lot_sqft=r["lot_sqft"],
            address=r["address"],
            city=r["city"],
            zip_code=r["zip_code"],
            lat=r["lat"],
            lng=r["lng"],
            url=r["url"],
            scraped_at=_parse_dt(r["scraped_at"]) or datetime.utcnow(),
            first_seen=_parse_dt(r["first_seen"]) or datetime.utcnow(),
            listed_at=_parse_dt(r["listed_at"]),
            owner_name=r["owner_name"],
            phone=r["phone"],
            email=r["email"],
            description=r["description"],
            outreach_status=r["outreach_status"],
            last_contacted_at=_parse_dt(r["last_contacted_at"]),
            notes=r["notes"],
        )
        for r in cur.fetchall()
    ]


def delete_listings(conn: sqlite3.Connection, listing_ids: list[str]) -> int:
    if not listing_ids:
        return 0
    placeholders = ",".join("?" for _ in listing_ids)
    cur = conn.execute(
        f"DELETE FROM listings WHERE listing_id IN ({placeholders})",
        listing_ids,
    )
    # Also drop their outreach log entries
    conn.execute(
        f"DELETE FROM outreach_log WHERE listing_id IN ({placeholders})",
        listing_ids,
    )
    return cur.rowcount


def stats(conn: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    out["total_listings"] = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    for src in ("clasificados", "zillow", "facebook"):
        out[f"{src}_listings"] = conn.execute(
            "SELECT COUNT(*) FROM listings WHERE source = ?", (src,)
        ).fetchone()[0]
    out["drafted_outreach"] = conn.execute(
        "SELECT COUNT(*) FROM outreach_log WHERE status = 'drafted'"
    ).fetchone()[0]
    return out
