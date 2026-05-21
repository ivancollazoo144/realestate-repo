from __future__ import annotations

import base64
from email.mime.text import MIMEText

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


def create_gmail_draft(
    creds: Credentials,
    to_email: str,
    subject: str,
    body: str,
    from_email: str | None = None,
) -> str:
    """Create a draft in the authenticated user's Gmail. Returns the draft ID.

    The draft lands in the Drafts folder of whichever Gmail account these creds
    belong to — for this project, the dedicated outreach account. Nothing is
    sent; manual review and send is the whole point.
    """
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    msg = MIMEText(body, "plain", "utf-8")
    msg["to"] = to_email
    msg["subject"] = subject
    if from_email:
        msg["from"] = from_email

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    draft = service.users().drafts().create(
        userId="me", body={"message": {"raw": raw}}
    ).execute()
    return str(draft["id"])
