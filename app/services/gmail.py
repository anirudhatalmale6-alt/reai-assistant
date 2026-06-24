"""
Gmail API service for searching, reading, and sending emails.
"""

import base64
import logging
from email.mime.text import MIMEText

from googleapiclient.discovery import build

from app.services.google_auth import get_credentials

logger = logging.getLogger(__name__)


def _get_gmail_service():
    """Build and return a Gmail API service instance."""
    creds = get_credentials()
    if not creds:
        raise RuntimeError(
            "Google credentials not found. Please connect your Google account first."
        )
    return build("gmail", "v1", credentials=creds)


def search_emails(query: str, max_results: int = 10) -> list[dict]:
    """
    Search emails using Gmail search syntax.

    Args:
        query: Gmail search query (e.g. "from:john subject:listing is:unread")
        max_results: Maximum number of results to return (default 10)

    Returns:
        List of dicts with keys: id, subject, from, date, snippet
    """
    service = _get_gmail_service()

    try:
        results = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )
    except Exception as e:
        logger.error("Gmail search failed: %s", e)
        return []

    messages = results.get("messages", [])
    if not messages:
        return []

    emails = []
    for msg_ref in messages:
        try:
            msg = (
                service.users()
                .messages()
                .get(userId="me", id=msg_ref["id"], format="metadata",
                     metadataHeaders=["Subject", "From", "Date"])
                .execute()
            )

            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

            emails.append({
                "id": msg["id"],
                "subject": headers.get("Subject", "(no subject)"),
                "from": headers.get("From", ""),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
            })
        except Exception as e:
            logger.warning("Failed to fetch message %s: %s", msg_ref["id"], e)

    return emails


def read_email(message_id: str) -> dict:
    """
    Read the full content of an email by its message ID.

    Args:
        message_id: Gmail message ID

    Returns:
        Dict with keys: id, subject, from, to, date, body
    """
    service = _get_gmail_service()

    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )

    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}

    body = _extract_body(msg.get("payload", {}))

    return {
        "id": msg["id"],
        "subject": headers.get("Subject", "(no subject)"),
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "date": headers.get("Date", ""),
        "body": body,
    }


def _extract_body(payload: dict) -> str:
    """
    Extract the text body from a Gmail message payload.
    Handles both simple and multipart messages.
    """
    # Simple message with body data directly
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    # Multipart message - look for text/plain first, then text/html
    parts = payload.get("parts", [])
    text_body = ""
    html_body = ""

    for part in parts:
        mime_type = part.get("mimeType", "")

        if mime_type == "text/plain" and part.get("body", {}).get("data"):
            text_body = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                "utf-8", errors="replace"
            )
        elif mime_type == "text/html" and part.get("body", {}).get("data"):
            html_body = base64.urlsafe_b64decode(part["body"]["data"]).decode(
                "utf-8", errors="replace"
            )
        elif mime_type.startswith("multipart/"):
            # Recurse into nested multipart
            nested = _extract_body(part)
            if nested:
                text_body = text_body or nested

    return text_body or html_body or "(no body content)"


def send_email(to: str, subject: str, body: str, cc: str = "") -> dict:
    """
    Send an email via Gmail.

    Args:
        to: Recipient email address
        subject: Email subject line
        body: Email body text (plain text)
        cc: CC recipients (comma-separated, optional)

    Returns:
        Dict with keys: status, message_id
    """
    service = _get_gmail_service()

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    if cc:
        message["cc"] = cc

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")

    try:
        sent = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        logger.info("Email sent successfully, id=%s", sent["id"])
        return {
            "status": "sent",
            "message_id": sent["id"],
        }
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        return {
            "status": "error",
            "message_id": None,
            "error": str(e),
        }
