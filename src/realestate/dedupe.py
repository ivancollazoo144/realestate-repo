from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from .sources.base import Listing


@dataclass
class DedupeResult:
    kept: list[Listing]
    rejected: list[Listing]
    rejected_phones: set[str]
    rejected_emails: set[str]


def filter_multi_listing_sellers(listings: list[Listing]) -> DedupeResult:
    """Reject all listings whose contact (phone or email) appears on >1 listing.

    A phone or email that shows up on multiple listings in the same batch is
    very likely a small broker, agent, or property manager rather than an
    individual owner. Listings with no phone and no email pass through
    unchanged (Zillow listings have neither — they were already filtered on
    the API's `brokerage` field).
    """
    phone_counts: Counter[str] = Counter(l.phone for l in listings if l.phone)
    email_counts: Counter[str] = Counter(l.email for l in listings if l.email)

    multi_phones = {p for p, n in phone_counts.items() if n > 1}
    multi_emails = {e for e, n in email_counts.items() if n > 1}

    kept: list[Listing] = []
    rejected: list[Listing] = []
    for l in listings:
        if (l.phone and l.phone in multi_phones) or (l.email and l.email in multi_emails):
            rejected.append(l)
        else:
            kept.append(l)

    return DedupeResult(
        kept=kept,
        rejected=rejected,
        rejected_phones=multi_phones,
        rejected_emails=multi_emails,
    )
