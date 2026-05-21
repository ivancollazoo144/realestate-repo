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

Phases 0–4 shipped. `realestate run --source all` scrapes Clasificados + Zillow + FB Marketplace; current sheet has ~107 leads. See `PLAN.md` for the roadmap.

## Daily scheduled run (macOS launchd)

```bash
# install
cp scripts/com.ivan.realestate.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.ivan.realestate.plist

# verify it's registered (should print the label and exit code 0 once it's run)
launchctl list | grep realestate

# trigger a test run on demand (don't wait until 8am)
launchctl start com.ivan.realestate
tail -f logs/realestate.out.log

# disable
launchctl unload ~/Library/LaunchAgents/com.ivan.realestate.plist
rm ~/Library/LaunchAgents/com.ivan.realestate.plist
```

Default schedule: **08:00 PR time, daily**. Edit `Hour`/`Minute` in the plist, then reload (unload + load) to change.

Logs in `logs/`:
- `realestate.out.log` — stdout (scrape summaries, sheet URLs)
- `realestate.err.log` — stderr (tracebacks if anything breaks)

If the Mac is asleep at the scheduled time, launchd fires the job when the Mac wakes. If the Mac is off / laptop closed, that day's run is skipped.

## Hard rules

1. **Drafts only.** No automatic sending of SMS or email. The pipeline ends at "draft created in Gmail" / "row written to SMS Drafts tab".
2. **Per-contact cooldown** is `OUTREACH_COOLDOWN_DAYS` (default 14) — never re-contact the same phone/email inside that window.
3. **No real-account FB scraping.** Use a burner account for `storage_state.json`.
