from __future__ import annotations

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import CONFIG
from .db import connect, init_db, stats

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
def run_cmd(source: str, dry_run: bool) -> None:
    """Scrape one or all sources and push new listings through the pipeline."""
    console.print(f"[bold]Run[/bold] source={source} dry_run={dry_run}")
    console.print("[yellow]Scraper sources are not implemented yet — Phase 2 onward.[/yellow]")
    # TODO Phase 2+: dispatch to source scrapers, normalize, dedupe, upsert, sync sheet, draft outreach.


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


if __name__ == "__main__":
    cli()
