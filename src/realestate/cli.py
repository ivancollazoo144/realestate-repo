from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from datetime import datetime

from . import __version__
from .config import CONFIG
from .db import connect, init_db, stats
from .sources.base import Listing

console = Console()

VALID_SOURCES = ("clasificados", "zillow", "facebook", "all")


@click.group()
@click.version_option(__version__, prog_name="realestate")
def cli() -> None:
    """PR FSBO/FRBO lead scraper. See PLAN.md for the project plan."""


@cli.command("init-db")
def init_db_cmd() -> None:
    """Create the SQLite database and tables if they don't exist."""
    init_db()
    console.print(f"[green]Database ready[/green] at {CONFIG.db_path}")


@cli.command("run")
@click.option(
    "--source",
    type=click.Choice(VALID_SOURCES),
    default="all",
    help="Which source to scrape. 'all' runs every source.",
)
@click.option("--dry-run", is_flag=True, help="Scrape and normalize, but do not write to sheet or draft outreach.")
@click.option("--max", "max_listings", type=int, default=None, help="Cap listings fetched (useful for testing).")
def run_cmd(source: str, dry_run: bool, max_listings: int | None) -> None:
    """Scrape one or all sources and push new listings through the pipeline."""
    from collections import Counter

    from .db import connect, init_db, upsert_listing
    from .normalize import normalize_clasificados, normalize_facebook, normalize_zillow
    from .sheets import SheetsClient
    from .sources.base import RawListing
    from .sources.clasificados import ClasificadosScraper
    from .sources.facebook import FacebookScraper
    from .sources.zillow import ZillowScraper

    init_db()

    sources_to_run: list[str] = []
    if source == "all":
        sources_to_run = ["clasificados", "zillow", "facebook"]
    elif source in ("clasificados", "zillow", "facebook"):
        sources_to_run = [source]
    else:
        console.print(f"[yellow]Source {source!r} not implemented yet.[/yellow]")
        return

    accepted_listings: list = []
    rejection_reasons: Counter = Counter()
    rejection_examples: dict[str, str] = {}

    for src in sources_to_run:
        console.print(f"\n[bold]Running {src} scraper[/bold] dry_run={dry_run} max={max_listings}")
        if src == "clasificados":
            ctx = ClasificadosScraper(max_listings=max_listings)
            normalizer = normalize_clasificados
            needs_detail = True
        elif src == "facebook":
            ctx = FacebookScraper()
            normalizer = normalize_facebook
            needs_detail = False
        else:  # zillow
            ctx = ZillowScraper()
            normalizer = normalize_zillow
            needs_detail = False

        with ctx as scraper:
            raws = scraper.fetch_index()
            if max_listings is not None and src in ("zillow", "facebook"):
                raws = raws[:max_listings]
            console.print(f"  index: {len(raws)} unique listings")

            for raw in raws:
                if needs_detail:
                    try:
                        raw = scraper.fetch_detail(raw)
                    except Exception as e:
                        rejection_reasons[f"{src}:fetch_error"] += 1
                        console.print(f"  [red]fetch error[/red] {raw.native_id}: {e}")
                        continue

                result = normalizer(raw)
                if result.rejected:
                    bucket = f"{src}:" + (result.reason or "unknown").split(":", 1)[0]
                    rejection_reasons[bucket] += 1
                    if bucket not in rejection_examples and result.reason:
                        rejection_examples[bucket] = result.reason
                    continue

                assert result.listing is not None
                accepted_listings.append(result.listing)
                console.print(
                    f"  [green]✓[/green] [{src}] {raw.native_id} "
                    f"${result.listing.price or 0:,} "
                    f"{(result.listing.address or '')!r} in {result.listing.city or '?'} "
                    f"({result.listing.owner_name or 'no name'}, {result.listing.phone or 'no phone'})"
                )

    console.print(f"\n[bold]Scrape summary:[/bold] accepted={len(accepted_listings)}")
    for bucket, n in rejection_reasons.most_common():
        ex = rejection_examples.get(bucket, "")
        console.print(f"  rejected {bucket}: {n}" + (f"  e.g. {ex[:60]}" if ex else ""))

    # Post-scrape dedup: reject sellers whose phone/email shows up on >1 listing
    from .dedupe import filter_multi_listing_sellers
    dedup = filter_multi_listing_sellers(accepted_listings)
    if dedup.rejected:
        console.print(
            f"\n[yellow]Multi-listing dedup:[/yellow] rejected {len(dedup.rejected)} listings "
            f"({len(dedup.rejected_phones)} phones, {len(dedup.rejected_emails)} emails)"
        )
        for l in dedup.rejected[:5]:
            console.print(f"  − {l.listing_id} {l.owner_name!r} {l.phone or l.email}")
        if len(dedup.rejected) > 5:
            console.print(f"  ... and {len(dedup.rejected) - 5} more")
    accepted_listings = dedup.kept

    if dry_run:
        console.print("[yellow]Dry run — skipping DB and Sheets writes.[/yellow]")
        return

    if not accepted_listings:
        console.print("[yellow]Nothing to write.[/yellow]")
        return

    with connect() as conn:
        new_count = sum(1 for l in accepted_listings if upsert_listing(conn, l))
    console.print(f"[cyan]DB[/cyan] upserted {len(accepted_listings)} ({new_count} new)")

    # Upsert into the sheet preserving cell formatting on existing rows.
    # New listings appear under a divider for today's date at the top.
    sheets = SheetsClient()
    inserted, updated = sheets.upsert_with_daily_group(accepted_listings)
    console.print(f"[cyan]Sheet[/cyan] inserted={inserted} (under today's date divider) updated={updated}")
    console.print(f"[cyan]Sheet URL[/cyan] {sheets.workbook_url}")


@cli.command("stats")
def stats_cmd() -> None:
    """Show counts of listings and outreach drafts in the local DB."""
    with connect() as conn:
        data = stats(conn)
    table = Table(title="realestate stats")
    table.add_column("metric", style="cyan")
    table.add_column("value", justify="right", style="magenta")
    for k, v in data.items():
        table.add_row(k, str(v))
    console.print(table)


@cli.command("config")
def config_cmd() -> None:
    """Print effective config (with secrets redacted)."""
    redacted = {
        "google_credentials_path": str(CONFIG.google_credentials_path),
        "outreach_gmail_address": CONFIG.outreach_gmail_address or "(unset)",
        "sheet_workbook_name": CONFIG.sheet_workbook_name,
        "db_path": str(CONFIG.db_path),
        "min_sale_price": CONFIG.min_sale_price,
        "min_rent_price": CONFIG.min_rent_price,
        "pr_focus_municipios": list(CONFIG.pr_focus_municipios) or "(whole island)",
        "zillow_proxy_url": "(set)" if CONFIG.zillow_proxy_url else "(unset)",
        "outreach_cooldown_days": CONFIG.outreach_cooldown_days,
        "enable_gmail_drafts": CONFIG.enable_gmail_drafts,
    }
    table = Table(title="effective config")
    table.add_column("key", style="cyan")
    table.add_column("value", style="white")
    for k, v in redacted.items():
        table.add_row(k, str(v))
    console.print(table)


@cli.command("e2e-test")
def e2e_test_cmd() -> None:
    """End-to-end smoke test: DB upsert → dedup check → Sheet upsert → Gmail draft → SMS row.

    Proves the Phase 1 foundation works before any real scraping. Idempotent.
    Set ENABLE_GMAIL_DRAFTS=true in .env to actually create the Gmail draft;
    otherwise the draft step is skipped with a log line.
    """
    from .db import connect, init_db, log_outreach, recent_contact_exists, upsert_listing
    from .gmail_draft import create_gmail_draft
    from .google_auth import get_credentials
    from .sheets import SheetsClient

    init_db()

    now = datetime.utcnow()
    fake = Listing(
        listing_id="test:e2e-1",
        source="clasificados",  # type: ignore[arg-type]
        type="sale",
        price=210_000,
        beds=3,
        baths=2,
        sqft=1600,
        lot_sqft=4000,
        address="42 Calle Falsa",
        city="Bayamón",
        zip_code="00956",
        lat=None,
        lng=None,
        url="https://example.invalid/listing/e2e-1",
        scraped_at=now,
        first_seen=now,
        listed_at=None,
        owner_name="Juan Owner",
        phone="787-555-0142",
        email=CONFIG.outreach_gmail_address or "owner@example.invalid",
        description="E2E test listing — proves DB → Sheet → Gmail draft pipeline.",
    )

    # 1) DB upsert + dedup check
    with connect() as conn:
        is_new = upsert_listing(conn, fake)
        cooldown_hit_before = recent_contact_exists(
            conn, fake.email or "", CONFIG.outreach_cooldown_days
        )
    console.print(f"[cyan]DB[/cyan] inserted_as_new={is_new} cooldown_hit_before={cooldown_hit_before}")

    # 2) Sheet upsert
    sheets = SheetsClient()
    inserted, updated = sheets.upsert_listings([fake])
    console.print(f"[cyan]Sheet[/cyan] inserted={inserted} updated={updated}")
    console.print(f"[cyan]Sheet URL[/cyan] {sheets.workbook_url}")

    # 3) Outreach: render templates inline (Phase 5 will replace with proper modules)
    subject = f"Interés en su propiedad — {fake.address}, {fake.city}"
    body = (
        f"Hola,\n\n"
        f"Vi su anuncio en {fake.source} ({fake.url}) y me interesa conocer más "
        f"sobre la propiedad en {fake.address}, {fake.city}. ¿Sigue disponible? "
        f"Me gustaría coordinar una visita.\n\n"
        f"Gracias,\nIvan\n\n"
        f"(Si prefiere que no le escriba más, conteste con STOP y no le contactaré de nuevo.)"
    )
    sms_body = (
        f"Hola, vi su anuncio en {fake.city}. ¿Sigue disponible? — Ivan. (STOP para no recibir más.)"
    )

    if cooldown_hit_before:
        console.print("[yellow]Skipping outreach — contact in cooldown window.[/yellow]")
    else:
        # Email draft (only actually create if enabled)
        if CONFIG.enable_gmail_drafts:
            creds = get_credentials()
            draft_id = create_gmail_draft(creds, fake.email or "", subject, body)
            console.print(f"[green]Gmail draft created[/green] id={draft_id}")
        else:
            console.print(
                "[yellow]ENABLE_GMAIL_DRAFTS=false — skipping actual Gmail draft creation. "
                "Set it to true in .env to test the draft step.[/yellow]"
            )

        # SMS draft row
        sheets.append_sms_drafts([{
            "listing_id": fake.listing_id,
            "phone": fake.phone,
            "message": sms_body,
            "listing_url": fake.url,
            "drafted_at": now.isoformat(),
            "status": "drafted",
        }])
        console.print("[green]SMS draft appended[/green] to sheet")

        # Log to DB so cooldown engages on rerun
        with connect() as conn:
            log_outreach(conn, fake.listing_id, "email", fake.email or "", "e2e_template_es", body)
            log_outreach(conn, fake.listing_id, "sms", fake.phone or "", "e2e_sms_es", sms_body)

    with connect() as conn:
        cooldown_hit_after = recent_contact_exists(
            conn, fake.email or "", CONFIG.outreach_cooldown_days
        )
    console.print(f"[cyan]Cooldown engaged after run[/cyan] {cooldown_hit_after}")
    console.print("[bold green]E2E test complete.[/bold green]")


@cli.command("sheet-test")
def sheet_test_cmd() -> None:
    """Authenticate with Google and write one fake listing to the workbook.

    First run opens a browser window for OAuth consent. After auth, creates the
    workbook (if missing) and appends a single fake listing. Idempotent — running
    it again updates the same row instead of duplicating.
    """
    from .sheets import SheetsClient

    console.print("[bold]Initializing Sheets client…[/bold]")
    console.print(
        "[yellow]If this is the first run, a browser window will open asking you to "
        f"sign in as {CONFIG.outreach_gmail_address or 'the dedicated Gmail'} and "
        "authorize the app.[/yellow]"
    )
    client = SheetsClient()
    console.print(f"[green]Workbook ready:[/green] {client.workbook_url}")

    now = datetime.utcnow()
    fake = Listing(
        listing_id="test:smoke-1",
        source="clasificados",  # type: ignore[arg-type]
        type="sale",
        price=185_000,
        beds=3,
        baths=2,
        sqft=1450,
        lot_sqft=None,
        address="123 Fake St",
        city="San Juan",
        zip_code="00907",
        lat=None,
        lng=None,
        url="https://example.invalid/listing/smoke-1",
        scraped_at=now,
        first_seen=now,
        listed_at=None,
        owner_name="Smoke Test Owner",
        phone="787-555-0100",
        email="smoke@example.invalid",
        description="Fake listing used by sheet-test to verify the pipeline end to end.",
    )
    inserted, updated = client.upsert_listings([fake])
    console.print(f"[green]Done.[/green] inserted={inserted} updated={updated}")


@cli.command("reorganize")
def reorganize_cmd() -> None:
    """Sort the Listings tab oldest → newest (top → bottom) and rebuild day dividers.

    Uses Google Sheets' native sort, which preserves cell formatting on
    listing rows — your highlights, colors, and manual annotations move
    with their rows and are not lost. Existing date dividers are removed
    and re-created in the correct positions.
    """
    from .sheets import SheetsClient
    sheets = SheetsClient()
    console.print("[bold]Reorganizing Listings tab — this preserves your highlights.[/bold]")
    groups, listings_count = sheets.reorganize_oldest_first()
    console.print(f"[green]Done.[/green] {listings_count} listings sorted, {groups} day groups.")
    console.print(f"[cyan]Sheet URL[/cyan] {sheets.workbook_url}")


@cli.command("clean")
@click.option("--dry-run", is_flag=True, help="Report what would be removed without changing anything.")
def clean_cmd(dry_run: bool) -> None:
    """Re-apply current filters against everything in the DB+Sheet and prune.

    Use after tightening the broker/realtor heuristic or dedup rules. Loads all
    listings, re-runs looks_like_realtor on owner_name, then runs the
    multi-listing dedup across the full set. Rejected rows are deleted from
    the DB and the Listings sheet is rewritten from scratch (headers preserved).
    """
    from .db import all_listings, connect, delete_listings
    from .dedupe import filter_multi_listing_sellers
    from .enrich import looks_like_realtor
    from .sheets import SheetsClient

    with connect() as conn:
        listings = all_listings(conn)
    console.print(f"Loaded [bold]{len(listings)}[/bold] listings from DB")

    rejected_realtor: list[tuple] = []
    after_realtor = []
    for l in listings:
        is_r, kw = looks_like_realtor(l.owner_name)
        if is_r:
            rejected_realtor.append((l, kw or "unknown"))
        else:
            after_realtor.append(l)

    dedup = filter_multi_listing_sellers(after_realtor)
    kept = dedup.kept

    console.print(f"\n[bold]Re-applied filters[/bold]")
    console.print(f"  kept:                {len(kept)}")
    console.print(f"  realtor name match:  {len(rejected_realtor)}")
    console.print(f"  multi-listing dedup: {len(dedup.rejected)}")

    if rejected_realtor:
        console.print("\n[yellow]Realtor-name rejections (showing up to 10):[/yellow]")
        for l, kw in rejected_realtor[:10]:
            console.print(f"  − {l.listing_id} {l.owner_name!r}  [{kw}]")

    if dedup.rejected:
        console.print("\n[yellow]Multi-listing rejections (showing up to 10):[/yellow]")
        for l in dedup.rejected[:10]:
            key = l.phone or l.email or "?"
            console.print(f"  − {l.listing_id} {l.owner_name!r}  shared={key}")

    rejected_ids = [l.listing_id for l, _ in rejected_realtor] + [l.listing_id for l in dedup.rejected]

    if dry_run:
        console.print(f"\n[yellow]Dry run — would delete {len(rejected_ids)} from DB, then rebuild sheet to match.[/yellow]")
        return

    if rejected_ids:
        with connect() as conn:
            deleted = delete_listings(conn, rejected_ids)
        console.print(f"\n[cyan]DB[/cyan] deleted {deleted} rows")
    else:
        console.print(f"\n[cyan]DB[/cyan] no listings to remove")

    # `clean` intentionally rebuilds the sheet from scratch, which DOES wipe
    # cell formatting. Use only when you want a full re-sync (e.g. after
    # tightening filters). Normal scrape runs use the format-preserving path.
    sheets = SheetsClient()
    groups, total_rows = sheets.rebuild_listings_grouped(kept)
    console.print(f"[cyan]Sheet[/cyan] rebuilt — {groups} date groups, {total_rows} rows (incl. dividers)")
    console.print(f"[yellow]Note: `clean` wipes cell formatting (highlights, colors). Use sparingly.[/yellow]")
    console.print(f"[cyan]Sheet URL[/cyan] {sheets.workbook_url}")


if __name__ == "__main__":
    cli()
