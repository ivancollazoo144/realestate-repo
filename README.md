# realestate

Puerto Rico FSBO/FRBO real estate lead scraper. Pulls listings from **Clasificados Online**, **Zillow PR**, and **Facebook Marketplace**, dedupes them, pushes to a Google Sheet, and produces SMS + email outreach **drafts only** for manual review.

See [`PLAN.md`](./PLAN.md) for the full project plan, phases, and risks.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install firefox

cp .env.example .env
# Fill in GOOGLE_CREDENTIALS_PATH, OUTREACH_GMAIL_ADDRESS, etc.

realestate init-db
realestate run --source clasificados  # first source to ship
```

## Status

Phase 1 (foundation) in progress. See `PLAN.md` for the roadmap.

## Hard rules

1. **Drafts only.** No automatic sending of SMS or email. The pipeline ends at "draft created in Gmail" / "row written to SMS Drafts tab".
2. **Per-contact cooldown** is `OUTREACH_COOLDOWN_DAYS` (default 14) — never re-contact the same phone/email inside that window.
3. **No real-account FB scraping.** Use a burner account for `storage_state.json`.
