"""Serves the recipient lists produced for a campaign."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services import campaign

router = APIRouter()


@router.get("/exports/{filename}")
async def get_export(filename: str):
    path = (campaign.EXPORT_DIR / filename).resolve()
    if campaign.EXPORT_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    media = "text/csv" if path.suffix == ".csv" else "text/plain"
    return FileResponse(str(path), media_type=media, filename=path.name)


@router.get("/exports")
async def list_exports() -> dict:
    files = sorted(campaign.EXPORT_DIR.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return {"exports": [
        {"filename": p.name, "size_bytes": p.stat().st_size,
         "url": f"/api/exports/{p.name}"} for p in files[:40] if p.is_file()
    ]}
