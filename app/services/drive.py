"""
Google Drive API service for searching and reading files.
"""

import logging

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.services.google_auth import get_credentials

logger = logging.getLogger(__name__)

# Mapping of Google Workspace MIME types to export formats
EXPORT_MIME_MAP = {
    "application/vnd.google-apps.document": {
        "mime": "text/plain",
        "label": "Google Doc",
    },
    "application/vnd.google-apps.spreadsheet": {
        "mime": "text/csv",
        "label": "Google Sheet",
    },
    "application/vnd.google-apps.presentation": {
        "mime": "text/plain",
        "label": "Google Slides",
    },
}


def _get_drive_service():
    """Build and return a Google Drive API service instance."""
    creds = get_credentials()
    if not creds:
        raise RuntimeError(
            "Google credentials not found. Please connect your Google account first."
        )
    return build("drive", "v3", credentials=creds)


def search_files(query: str, max_results: int = 10) -> list[dict]:
    """
    Search for files in Google Drive.

    Args:
        query: Search query (file name or content keywords).
               Converted into a Drive API query using fullText or name contains.
        max_results: Maximum number of results (default 10)

    Returns:
        List of dicts with keys: id, name, mimeType, modifiedTime, webViewLink
    """
    service = _get_drive_service()

    # Build a Drive search query from the natural-language query
    # Use fullText contains for broad matching, exclude trashed files
    drive_query = f"fullText contains '{_escape_query(query)}' and trashed = false"

    try:
        results = (
            service.files()
            .list(
                q=drive_query,
                pageSize=max_results,
                fields="files(id, name, mimeType, modifiedTime, webViewLink)",
                orderBy="modifiedTime desc",
            )
            .execute()
        )
    except HttpError as e:
        logger.error("Drive search failed: %s", e)
        # Fall back to name-only search if fullText fails
        try:
            drive_query = f"name contains '{_escape_query(query)}' and trashed = false"
            results = (
                service.files()
                .list(
                    q=drive_query,
                    pageSize=max_results,
                    fields="files(id, name, mimeType, modifiedTime, webViewLink)",
                    orderBy="modifiedTime desc",
                )
                .execute()
            )
        except HttpError as e2:
            logger.error("Drive name search also failed: %s", e2)
            return []

    files = []
    for f in results.get("files", []):
        files.append({
            "id": f["id"],
            "name": f["name"],
            "mimeType": f.get("mimeType", ""),
            "modifiedTime": f.get("modifiedTime", ""),
            "webViewLink": f.get("webViewLink", ""),
        })

    return files


def read_file(file_id: str) -> dict:
    """
    Read the content of a file from Google Drive.

    For Google Workspace files (Docs, Sheets, Slides), exports to
    a text format. For regular files, downloads the raw content.

    Args:
        file_id: The Google Drive file ID

    Returns:
        Dict with keys: name, mimeType, content
    """
    service = _get_drive_service()

    # Get file metadata first
    try:
        file_meta = (
            service.files()
            .get(fileId=file_id, fields="id, name, mimeType")
            .execute()
        )
    except HttpError as e:
        logger.error("Failed to get file metadata for %s: %s", file_id, e)
        return {"name": "", "content": f"Error: Could not access file - {e}"}

    file_name = file_meta.get("name", "")
    mime_type = file_meta.get("mimeType", "")

    # Handle Google Workspace file types (need export, not download)
    if mime_type in EXPORT_MIME_MAP:
        export_info = EXPORT_MIME_MAP[mime_type]
        try:
            content = (
                service.files()
                .export(fileId=file_id, mimeType=export_info["mime"])
                .execute()
            )
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="replace")
            return {
                "name": file_name,
                "mimeType": mime_type,
                "content": content,
            }
        except HttpError as e:
            logger.error("Failed to export %s (%s): %s", file_name, export_info["label"], e)
            return {
                "name": file_name,
                "mimeType": mime_type,
                "content": f"Error exporting {export_info['label']}: {e}",
            }

    # Handle regular (binary/text) files
    try:
        content = (
            service.files()
            .get_media(fileId=file_id)
            .execute()
        )
        if isinstance(content, bytes):
            # Try decoding as text; if it fails, note it's binary
            try:
                content = content.decode("utf-8")
            except UnicodeDecodeError:
                content = f"[Binary file: {file_name}, {len(content)} bytes - cannot display as text]"
        return {
            "name": file_name,
            "mimeType": mime_type,
            "content": content,
        }
    except HttpError as e:
        logger.error("Failed to download file %s: %s", file_name, e)
        return {
            "name": file_name,
            "mimeType": mime_type,
            "content": f"Error downloading file: {e}",
        }


def _escape_query(query: str) -> str:
    """Escape single quotes in search queries for the Drive API."""
    return query.replace("\\", "\\\\").replace("'", "\\'")
