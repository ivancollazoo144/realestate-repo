# Real Estate Lead Scraper — PR

## Goal
Surface for-sale-by-owner (FSBO, $150k+) and for-rent-by-owner (FRBO, $1,500/mo+) listings in Puerto Rico from **Zillow**, **Clasificados Online**, and **Facebook Marketplace**. Push each new listing into a Google Sheet with contact info, then generate **SMS + email outreach drafts for manual review and send**.

## Stack
- **Python 3.11+**, managed with `uv`
- **Playwright** (headed when needed) for Zillow + Facebook
- **httpx + selectolax** for Clasificados Online (no JS-heavy anti-bot)
- **SQLite** for raw + normalized listings, dedup history, contact log
- **gspread** for Google Sheets, **google-api-python-client** for Gmail drafts
- **launchd** plist for scheduling on macOS (every 6 hours)
- Twilio deferred — SMS drafts initially live in a sheet tab, copy/paste into Messages

## Required infrastructure (none of this exists yet)
| Item | Purpose | Cost |
|---|---|---|
| Google Cloud project with Sheets + Gmail API enabled, OAuth desktop client | Sheet sync, draft emails | Free |
| Residential proxy service (Brightdata / Smartproxy / IPRoyal) | Zillow at any meaningful rate | $75–$200/mo |
| Burner Facebook account | FB Marketplace requires login; expect bans | Free, plus a SIM for verification |
| Twilio (Phase 5+, optional) | Only if SMS auto-send added later | ~$1/mo per number |

## Repo layout
```
realestate-repo/
├── .env.example
├── pyproject.toml
├── README.md
├── PLAN.md
├── src/realestate/
│   ├── sources/
│   │   ├── base.py            # Listing dataclass + Scraper protocol
│   │   ├── clasificados.py
│   │   ├── zillow.py
│   │   └── facebook.py
│   ├── normalize.py           # source-specific → common schema
│   ├── dedupe.py              # phone + fuzzy address match
│   ├── enrich.py              # regex phone/email out of descriptions
│   ├── outreach/
│   │   ├── templates_es.py    # Spanish templates (primary for PR)
│   │   ├── templates_en.py
│   │   └── drafter.py         # Gmail drafts + SMS draft sheet rows
│   ├── sheets.py              # gspread upsert
│   ├── db.py                  # SQLite schema, migrations, queries
│   └── cli.py                 # `realestate run`, `realestate stats`
├── scripts/
│   └── com.ivan.realestate.plist
└── tests/
```

## Common listing schema (one row per listing in the sheet)
```
listing_id  (source:native_id, e.g. zillow:1234567)
source      (zillow | clasificados | facebook)
type        (sale | rent)
price
beds, baths, sqft, lot_sqft
address, city, zip, lat, lng
url
scraped_at, first_seen, listed_at
owner_name, phone, email
description
outreach_status   (none | drafted | sent | replied | dead)
last_contacted_at
notes
```

## Build phases

### Phase 1 — Foundation
- `uv` project skeleton, `.env` handling, pre-commit (ruff + mypy)
- SQLite schema + migration script
- `sources/base.py` — `Listing` dataclass + `Scraper` protocol (`fetch_index() → list[RawListing]`, `fetch_detail(raw) → Listing`)
- Sheets sync that creates the workbook on first run and upserts by `listing_id`
- CLI scaffolding (`realestate run --source X`, `realestate stats`)

**Done when:** a hand-crafted fake `Listing` flows through normalize → dedupe → sheet → Gmail draft.

### Phase 2 — Clasificados Online  *(ship this first)*

**URL structure discovered 2026-05-20:**
- Sale index: `/RealEstate.asp` — surfaces ~30 unique FSBO listings via `/UDRealEstateDetail.asp?ID={id}` links. All sampled IDs returned live, rich pages (100–280KB).
- Rental index: `/Rentals.asp` — `/UDRentalsDetail.asp?ID={id}` links exist (100 of them) but **every sampled ID redirects to the NoAdID placeholder**. Effectively zero live FRBO inventory on Clasificados Online.
- Broker-only URL pattern: `/PartnersListingREID.asp` (sale) and `/PartnersListingREFRID.asp` (rent) — skip these; we want owner-direct only.
- Encoding: iso-8859-1 (force on httpx response).

**Scope adjustment:** Phase 2 ships **sales only** from Clasificados. FRBO will come from Zillow Rentals + FB Marketplace in Phases 3 and 4. Plan-locked filter list adjusted accordingly.

**Sale scrape implementation:**
- Scrape `/RealEstate.asp`, extract all unique `/UDRealEstateDetail.asp?ID=` links (~30 unique).
- Fetch each detail page, throttled ~1 req/3s, randomized order.
- Detail page fields: title, type (Casa/Apartamento/Finca/Terreno), city, region (e.g. "Carolina - Isla Verde"), beds (`Cuartos`), baths (`Baños`), price (`$X,XXX`), sqft (`X p/c -ft2`), subdivision (`Urbanizacion - ...`), seller name, seller phone (`(xxx) xxx-xxxx`).
- FSBO filter: reject seller-name strings containing `Realty`, `Real Estate`, `Realtor`, `Lic#`, `Corredor`, `LLC`, `Inc`, `.com`, `Group`. Sample showed 2/3 of UD listings are actually brokers using the owner-direct URL.
- Phone extraction regex: `(\(?\d{3}\)?[-. ]?\d{3}[-. ]?\d{4})` — handle PR (787/939) and US (305 etc.) formats; seller may live off-island.
- Email regex from description.

**Done when:** Daily run produces a populated sheet with at least 10 real FSBO sale listings (post-broker-filter) and a >70% phone-extraction rate.

### Phase 3 — Zillow PR
- Playwright with `firefox` channel + residential proxy session per run
- URL-based FSBO filter: `…/puerto-rico/fsbo/` (Zillow's For Sale By Owner filter)
- Rate limit: 1 navigation per 8s, randomize between 6–12s; max 1 worker
- Phone numbers usually masked → outreach is "Contact form" text rather than SMS
- Capture screenshots on parse failures into `./debug/zillow/` for re-tuning

**Done when:** 50 consecutive runs without a Cloudflare/PerimeterX block. If we can't hit that, fall back to RapidAPI Zillow as a paid alternative.

### Phase 4 — Facebook Marketplace
- Playwright with persistent `storage_state.json` (logged-in burner session)
- Searches near major PR metros: San Juan, Bayamón, Carolina, Ponce, Caguas, Mayagüez
- Spanish queries: `"casa venta dueño"`, `"se vende casa por dueño"`, `"alquiler dueño directo"`
- Phones rarely in listing → output is the Messenger URL + a drafted opening message you send manually
- Expect to rebuild every 2–3 months — FB changes selectors often
- Daily session health check; if login expired, send Ivan an email and stop the run

**Done when:** Daily run pulls 5+ unique listings without the burner account getting checkpointed.

### Phase 5 — Outreach drafting
- Spanish (primary) + English templates, two flavors each: sale (intro buyer interest) and rent (intro tenant interest)
- Gmail API creates drafts in Ivan's inbox; subject + body + To address from the listing
- SMS drafts: append to a "SMS Drafts" tab in the workbook (`phone, message, listing_url, drafted_at, status`)
- **Hard rules baked in:**
  - Never draft a second message to the same phone or email within 14 days
  - Never draft if `outreach_status` is already `sent`, `replied`, or `dead`
  - Templates include an explicit opt-out line ("Reply STOP and I won't reach out again")

### Phase 6 — Scheduling & monitoring
- launchd plist runs the full pipeline every 6 hours
- Daily 8am summary email: new listings per source, errors, FB session health, dedup stats
- Failure alerts: if a source returns 0 listings for 2 consecutive runs, email Ivan
- Weekly housekeeping: archive listings older than 60 days with `outreach_status = none`

## What we are NOT building (and why)
- **No auto-send SMS or email.** Drafts only. Re-confirm before changing.
- **No CRM features** (pipelines, kanban, contact merging beyond dedup). The sheet is the UI.
- **No mainland US expansion** until PR pipeline is stable and producing leads.
- **No custom Claude Code skills or agents.** This is straightforward Python — Claude Code interactively is enough. The one place an agent could earn its keep later is **Phase 7: a lead-scorer that reads description + photos and ranks deal quality** (motivated-seller language, fixer signals, mispriced). Defer until volume warrants triage.

## Risks to acknowledge before starting
1. **Zillow & FB ToS prohibit scraping.** Risk is account/IP bans, not legal action against an individual, but it's real. Keep volume low.
2. **FB will eventually ban the burner.** Don't use a phone number tied to your identity for SIM verification; budget a couple of replacement accounts per year.
3. **PR FSBO inventory is thin.** Realistic expectation: 5–30 new *sale* listings/week across all three sources combined; rentals will be 3–5× that.
4. **Manual review is the bottleneck.** Even with drafts, 50 leads/day is more than you'll work. Build [[lead-scorer]] sooner if drafts pile up.

## Decisions (locked 2026-05-20)
1. **Rent threshold:** $1,500/month and up. Sale threshold: $150,000 and up.
2. **Zillow scope:** Use the FSBO filter **and** also scrape regular Zillow PR results, filtering realtor listings out via description/name heuristics (keywords like "Realtor", "Broker", "MLS#", "Inc.", "LLC" in seller name; phone matching known brokerage prefixes). Expect false positives — log all rejections to a `zillow_filtered` table for tuning.
3. **Gmail for drafts:** Dedicated account, **to be created** by Ivan. Suggested name: something like `ivancollazo.re@gmail.com` or similar. Drafts will only land in this account; primary inbox stays clean.
4. **PR coverage:** Whole island. For FB Marketplace, run searches centered on the six largest metros (San Juan, Bayamón, Carolina, Ponce, Caguas, Mayagüez) with 40-mile radius each — overlaps cover the rest of the island.

## Suggested next steps (in order)
1. Ivan creates the dedicated Gmail account for outreach drafts.
2. Set up the Google Cloud project (Sheets + Gmail OAuth using that account) — I can walk you through it.
3. I scaffold Phase 1 in this repo (skeleton, DB, base interfaces, fake-listing end-to-end test).
4. Phase 2 Clasificados scraper — first real listings hitting the sheet within ~2 sessions.
