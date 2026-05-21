from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parents[2]


def _path(env_key: str, default: str) -> Path:
    raw = os.getenv(env_key, default)
    p = Path(raw)
    return p if p.is_absolute() else REPO_ROOT / p


def _bool(env_key: str, default: bool) -> bool:
    return os.getenv(env_key, str(default)).strip().lower() in {"1", "true", "yes", "y"}


def _int(env_key: str, default: int) -> int:
    raw = os.getenv(env_key)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Config:
    google_credentials_path: Path
    google_token_path: Path
    outreach_gmail_address: str

    sheet_workbook_name: str
    sheet_tab_listings: str
    sheet_tab_sms_drafts: str

    db_path: Path

    pr_focus_municipios: tuple[str, ...]
    min_sale_price: int
    min_rent_price: int

    zillow_proxy_url: str | None
    fb_storage_state_path: Path

    outreach_cooldown_days: int
    enable_gmail_drafts: bool

    @classmethod
    def from_env(cls) -> "Config":
        municipios_raw = os.getenv("PR_FOCUS_MUNICIPIOS", "").strip()
        municipios = tuple(m.strip() for m in municipios_raw.split(",") if m.strip())

        proxy = os.getenv("ZILLOW_PROXY_URL", "").strip() or None

        return cls(
            google_credentials_path=_path("GOOGLE_CREDENTIALS_PATH", "./credentials.json"),
            google_token_path=_path("GOOGLE_TOKEN_PATH", "./token.json"),
            outreach_gmail_address=os.getenv("OUTREACH_GMAIL_ADDRESS", "").strip(),
            sheet_workbook_name=os.getenv("SHEET_WORKBOOK_NAME", "PR Real Estate Leads"),
            sheet_tab_listings=os.getenv("SHEET_TAB_LISTINGS", "Listings"),
            sheet_tab_sms_drafts=os.getenv("SHEET_TAB_SMS_DRAFTS", "SMS Drafts"),
            db_path=_path("DB_PATH", "./data/realestate.db"),
            pr_focus_municipios=municipios,
            min_sale_price=_int("MIN_SALE_PRICE", 150_000),
            min_rent_price=_int("MIN_RENT_PRICE", 1_500),
            zillow_proxy_url=proxy,
            fb_storage_state_path=_path("FB_STORAGE_STATE_PATH", "./storage_state.json"),
            outreach_cooldown_days=_int("OUTREACH_COOLDOWN_DAYS", 14),
            enable_gmail_drafts=_bool("ENABLE_GMAIL_DRAFTS", False),
        )


CONFIG = Config.from_env()
