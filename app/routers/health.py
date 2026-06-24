from fastapi import APIRouter
from app.services.google_auth import is_google_connected

router = APIRouter()


@router.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "google_connected": is_google_connected(),
    }
