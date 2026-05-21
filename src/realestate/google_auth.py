from __future__ import annotations

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from .config import CONFIG, Config

SCOPES: list[str] = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/gmail.compose",
]


def get_credentials(config: Config = CONFIG) -> Credentials:
    """Load cached creds, refresh if expired, or run the OAuth flow on first use.

    First call opens a browser window asking the user to sign in to the dedicated
    Gmail account and grant the requested scopes. After consent the refresh token
    is cached to config.google_token_path; subsequent calls are silent.
    """
    creds: Credentials | None = None
    token_path = config.google_token_path

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not config.google_credentials_path.exists():
                raise FileNotFoundError(
                    f"OAuth client file not found at {config.google_credentials_path}. "
                    "Download it from Google Cloud Console → APIs & Services → Credentials."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(config.google_credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())

    return creds
