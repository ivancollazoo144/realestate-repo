from __future__ import annotations

import re

PHONE_RE = re.compile(
    r"""
    (?<![\d-])                  # don't start mid-number
    (?:\+?1[\s.-]?)?            # optional country code
    \(?(\d{3})\)?               # area code, optional parens
    [\s.-]?
    (\d{3})
    [\s.-]?
    (\d{4})
    (?!\d)                      # don't run into more digits
    """,
    re.VERBOSE,
)

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
)

PR_AREA_CODES = {"787", "939"}

REALTOR_KEYWORDS = (
    "realty", "real estate", "realtor", "lic#", "lic.", "lic ",
    "corredor", "broker", "agent", "agencia",
    "llc", "inc", "corp", "group", ".com",
    "homes 4 sale", "property", "properties",
    # Property management — owner is not the seller
    "management", "manager", "administrador", "administracion", "rentals",
    # Major brokerages that may not include "realty" in their displayed name
    "keller williams", "remax", "re/max", "century 21", "coldwell",
    "exp realty", "exp ", "berkshire hathaway", "sotheby",
    "compass ", "douglas elliman",
)

# PR realtor license numbers look like "L-1234" or "E-1234" (commercial)
REALTOR_LICENSE_RE = re.compile(r"\b[LE]-\d{3,6}\b")

# Standalone broker abbreviations as separate words (e.g. "KW Boricua")
BROKER_ABBREV_RE = re.compile(r"\b(KW|RE/MAX|C21)\b", re.IGNORECASE)


def canonicalize_phone(area: str, prefix: str, line: str) -> str:
    """Return phone as 'xxx-xxx-xxxx'."""
    return f"{area}-{prefix}-{line}"


def extract_phones(text: str) -> list[str]:
    """Return unique canonical phones found in text, order preserved."""
    seen: dict[str, None] = {}
    for m in PHONE_RE.finditer(text):
        area, prefix, line = m.group(1), m.group(2), m.group(3)
        if area.startswith("0") or area.startswith("1"):
            continue
        canonical = canonicalize_phone(area, prefix, line)
        seen.setdefault(canonical, None)
    return list(seen.keys())


def extract_emails(text: str) -> list[str]:
    """Return unique lowercase emails found in text, order preserved."""
    seen: dict[str, None] = {}
    for m in EMAIL_RE.finditer(text):
        seen.setdefault(m.group(0).lower(), None)
    return list(seen.keys())


def is_pr_phone(phone: str) -> bool:
    """Check if a canonical phone is a PR number (area code 787 or 939)."""
    return phone.split("-", 1)[0] in PR_AREA_CODES


def looks_like_realtor(seller_name: str | None) -> tuple[bool, str | None]:
    """Heuristic: does this seller-name string suggest a realtor/brokerage rather than FSBO?

    Returns (is_realtor, matched_keyword_or_None).
    """
    if not seller_name:
        return False, None
    lowered = seller_name.lower()
    for kw in REALTOR_KEYWORDS:
        if kw in lowered:
            return True, kw
    m = REALTOR_LICENSE_RE.search(seller_name)
    if m:
        return True, f"license:{m.group(0)}"
    m2 = BROKER_ABBREV_RE.search(seller_name)
    if m2:
        return True, f"abbrev:{m2.group(0).upper()}"
    return False, None
