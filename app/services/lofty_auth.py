"""Lofty CRM OAuth2 authentication service."""

import json
import base64
import urllib.parse
import requests

from app.config import settings

TOKEN_FILE = settings.TOKEN_DIR / "lofty.json"
AUTH_URL = "https://crm.lofty.com/api/user-web/oauth/authorize"
TOKEN_URL = "https://crm.lofty.com/api/user-web/oauth/token"


def get_auth_url() -> str:
    params = {
        "response_type": "code",
        "client_id": settings.LOFTY_CLIENT_ID,
        "redirect_uri": settings.LOFTY_REDIRECT_URI,
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params)


def exchange_code(code: str) -> bool:
    credentials = base64.b64encode(
        f"{settings.LOFTY_CLIENT_ID}:{settings.LOFTY_CLIENT_SECRET}".encode()
    ).decode()

    resp = requests.post(TOKEN_URL, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Authorization": f"Basic {credentials}",
    }, data={
        "grant_type": "authorization_code",
        "code": code,
        "client_id": settings.LOFTY_CLIENT_ID,
        "redirect_uri": settings.LOFTY_REDIRECT_URI,
    }, timeout=15)

    if resp.status_code != 200:
        return False

    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return False

    save_data = {
        "access_token": access_token,
        "refresh_token": token_data.get("refresh_token", ""),
        "token_type": token_data.get("token_type", "Bearer"),
        "expires_in": token_data.get("expires_in", 0),
    }
    TOKEN_FILE.write_text(json.dumps(save_data, indent=2))
    return True


def get_access_token() -> str | None:
    if not TOKEN_FILE.exists():
        return None
    data = json.loads(TOKEN_FILE.read_text())
    return data.get("access_token")


def is_lofty_connected() -> bool:
    if get_access_token() is not None:
        return True
    from app.config import settings
    return bool(settings.LOFTY_API_KEY)


def disconnect():
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
