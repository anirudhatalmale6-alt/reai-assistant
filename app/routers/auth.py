from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.services.google_auth import get_auth_url, exchange_code, is_google_connected
from app.services.meta_auth import (
    get_auth_url as meta_get_auth_url,
    exchange_code as meta_exchange_code,
    is_meta_connected,
    disconnect as meta_disconnect,
)
from app.services.lofty_auth import (
    get_auth_url as lofty_get_auth_url,
    exchange_code as lofty_exchange_code,
    is_lofty_connected,
    disconnect as lofty_disconnect,
)

router = APIRouter()


class CodeRequest(BaseModel):
    code: str


@router.get("/google")
async def google_auth():
    url = get_auth_url()
    return {"auth_url": url}


@router.post("/callback")
async def google_callback(request: CodeRequest):
    code = request.code.strip()
    success = exchange_code(code)
    if success:
        return {"status": "connected"}
    return JSONResponse({"error": "Failed to connect. Please try again."}, status_code=400)


@router.get("/meta")
async def meta_auth():
    url = meta_get_auth_url()
    return {"auth_url": url}


@router.post("/meta/callback")
async def meta_callback(request: CodeRequest):
    code = request.code.strip()
    success = meta_exchange_code(code)
    if success:
        return {"status": "connected"}
    return JSONResponse({"error": "Failed to connect Meta. Please try again."}, status_code=400)


@router.post("/meta/disconnect")
async def disconnect_meta():
    meta_disconnect()
    return {"meta_connected": False}


@router.get("/lofty")
async def lofty_auth():
    url = lofty_get_auth_url()
    return {"auth_url": url}


@router.post("/lofty/callback")
async def lofty_callback(request: CodeRequest):
    code = request.code.strip()
    success = lofty_exchange_code(code)
    if success:
        return {"status": "connected"}
    return JSONResponse({"error": "Failed to connect Lofty. Please try again."}, status_code=400)


@router.post("/lofty/disconnect")
async def disconnect_lofty():
    lofty_disconnect()
    return {"lofty_connected": False}


@router.get("/status")
async def auth_status():
    return {
        "google_connected": is_google_connected(),
        "meta_connected": is_meta_connected(),
        "lofty_connected": is_lofty_connected(),
    }


@router.post("/disconnect")
async def disconnect_google():
    from app.config import settings
    token_file = settings.TOKEN_DIR / "default.json"
    if token_file.exists():
        token_file.unlink()
    return {"google_connected": False}
