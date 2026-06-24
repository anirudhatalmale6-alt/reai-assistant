"""Meta (Facebook/Instagram) OAuth2 authentication service."""

import json
import urllib.parse
import requests

from app.config import settings

TOKEN_FILE = settings.TOKEN_DIR / "meta.json"
GRAPH_API = "https://graph.facebook.com/v21.0"

SCOPES = [
    "pages_manage_posts",
    "pages_read_engagement",
    "pages_messaging",
    "pages_manage_metadata",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_messages",
    "public_profile",
]


def get_auth_url() -> str:
    params = {
        "client_id": settings.META_APP_ID,
        "redirect_uri": settings.META_REDIRECT_URI,
        "response_type": "code",
        "scope": ",".join(SCOPES),
        "state": "reai_meta_auth",
    }
    return "https://www.facebook.com/v21.0/dialog/oauth?" + urllib.parse.urlencode(params)


def exchange_code(code: str) -> bool:
    resp = requests.get(f"{GRAPH_API}/oauth/access_token", params={
        "client_id": settings.META_APP_ID,
        "client_secret": settings.META_APP_SECRET,
        "redirect_uri": settings.META_REDIRECT_URI,
        "code": code,
    }, timeout=15)
    if resp.status_code != 200:
        return False

    short_token = resp.json().get("access_token")
    if not short_token:
        return False

    ll_resp = requests.get(f"{GRAPH_API}/oauth/access_token", params={
        "grant_type": "fb_exchange_token",
        "client_id": settings.META_APP_ID,
        "client_secret": settings.META_APP_SECRET,
        "fb_exchange_token": short_token,
    }, timeout=15)
    if ll_resp.status_code != 200:
        return False

    long_token = ll_resp.json().get("access_token")

    pages_resp = requests.get(f"{GRAPH_API}/me/accounts", params={
        "access_token": long_token,
        "fields": "id,name,access_token,instagram_business_account{id,username}",
    }, timeout=15)

    pages = []
    ig_accounts = []
    if pages_resp.status_code == 200:
        for page in pages_resp.json().get("data", []):
            pages.append({
                "id": page["id"],
                "name": page["name"],
                "access_token": page["access_token"],
            })
            ig = page.get("instagram_business_account")
            if ig:
                ig_accounts.append({
                    "id": ig["id"],
                    "username": ig.get("username", ""),
                    "page_id": page["id"],
                })

    if not pages:
        debug_resp = requests.get(f"{GRAPH_API}/debug_token", params={
            "input_token": long_token,
            "access_token": f"{settings.META_APP_ID}|{settings.META_APP_SECRET}",
        }, timeout=15)
        if debug_resp.status_code == 200:
            granular = debug_resp.json().get("data", {}).get("granular_scopes", [])
            page_ids = set()
            ig_ids = set()
            for scope in granular:
                if scope.get("scope") == "pages_manage_posts":
                    page_ids.update(scope.get("target_ids", []))
                if scope.get("scope") == "instagram_basic":
                    ig_ids.update(scope.get("target_ids", []))
            for pid in page_ids:
                pr = requests.get(f"{GRAPH_API}/{pid}", params={
                    "access_token": long_token, "fields": "id,name,access_token",
                }, timeout=15)
                if pr.status_code == 200:
                    pd = pr.json()
                    pages.append({"id": pd["id"], "name": pd.get("name", ""), "access_token": pd.get("access_token", "")})
            for iid in ig_ids:
                ir = requests.get(f"{GRAPH_API}/{iid}", params={
                    "access_token": long_token, "fields": "id,username",
                }, timeout=15)
                if ir.status_code == 200:
                    igd = ir.json()
                    ig_accounts.append({"id": igd["id"], "username": igd.get("username", ""), "page_id": pages[0]["id"] if pages else ""})

    token_data = {
        "user_access_token": long_token,
        "pages": pages,
        "instagram_accounts": ig_accounts,
    }
    TOKEN_FILE.write_text(json.dumps(token_data, indent=2))
    return True


def get_token_data() -> dict | None:
    if not TOKEN_FILE.exists():
        return None
    return json.loads(TOKEN_FILE.read_text())


def get_page_token(page_id: str = "") -> str | None:
    data = get_token_data()
    if not data or not data.get("pages"):
        return None
    if page_id:
        for p in data["pages"]:
            if p["id"] == page_id:
                return p["access_token"]
    return data["pages"][0]["access_token"]


def get_page_id() -> str | None:
    data = get_token_data()
    if not data or not data.get("pages"):
        return None
    return data["pages"][0]["id"]


def get_page_name() -> str | None:
    data = get_token_data()
    if not data or not data.get("pages"):
        return None
    return data["pages"][0]["name"]


def get_ig_account_id() -> str | None:
    data = get_token_data()
    if not data or not data.get("instagram_accounts"):
        return None
    return data["instagram_accounts"][0]["id"]


def is_meta_connected() -> bool:
    data = get_token_data()
    return data is not None and len(data.get("pages", [])) > 0


def disconnect():
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()
