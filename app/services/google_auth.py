import json
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import urllib.parse

from app.config import settings

TOKEN_FILE = settings.TOKEN_DIR / "default.json"

REDIRECT_URI = "http://localhost"


def get_auth_url() -> str:
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(settings.GOOGLE_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    return "https://accounts.google.com/o/oauth2/auth?" + urllib.parse.urlencode(params)


def exchange_code(code: str) -> bool:
    import requests
    resp = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code,
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    })
    if resp.status_code != 200:
        return False
    tokens = resp.json()
    token_data = {
        "token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": settings.GOOGLE_CLIENT_ID,
        "client_secret": settings.GOOGLE_CLIENT_SECRET,
        "scopes": settings.GOOGLE_SCOPES,
    }
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
    return True


def save_credentials(creds: Credentials) -> None:
    token_data = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes) if creds.scopes else settings.GOOGLE_SCOPES,
    }
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2))


def get_credentials() -> Credentials | None:
    if not TOKEN_FILE.exists():
        return None
    data = json.loads(TOKEN_FILE.read_text())
    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri=data.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=data.get("client_id", settings.GOOGLE_CLIENT_ID),
        client_secret=data.get("client_secret", settings.GOOGLE_CLIENT_SECRET),
        scopes=data.get("scopes", settings.GOOGLE_SCOPES),
    )
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(creds)
    return creds


def is_google_connected() -> bool:
    creds = get_credentials()
    return creds is not None and creds.valid
