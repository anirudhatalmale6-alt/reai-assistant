"""Photo uploads used by the marketing-graphic generator."""
import re
import unicodedata
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.services import graphics

router = APIRouter()

IMAGES = {".jpg", ".jpeg", ".png", ".webp"}
DOCS = {".pdf", ".txt", ".csv"}
ALLOWED = IMAGES | DOCS
MAX_BYTES = 12 * 1024 * 1024  # plenty for a listing photo off a phone


def _safe_name(name: str) -> str:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).stem).strip("-.") or "photo"
    return f"{stem[:60]}{Path(name).suffix.lower()}"


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 500):
        candidate = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise HTTPException(status_code=409, detail="Too many files with that name")


@router.post("/uploads")
async def upload_photos(files: list[UploadFile] = File(...)) -> dict:
    saved = []
    for upload in files:
        suffix = Path(upload.filename or "").suffix.lower()
        if suffix not in ALLOWED:
            raise HTTPException(
                status_code=400,
                detail=f"{upload.filename}: JPG, PNG, WEBP, PDF, TXT and CSV only")
        data = await upload.read()
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail=f"{upload.filename} is over 12 MB")

        target = _unique(graphics.UPLOAD_DIR / _safe_name(upload.filename or "photo.jpg"))
        target.write_bytes(data)
        saved.append({"filename": target.name, "url": f"/api/uploads/{target.name}",
                      "kind": "image" if suffix in IMAGES else "file"})

    return {"uploaded": saved, "count": len(saved)}


@router.get("/uploads")
async def list_photos() -> dict:
    return {"photos": graphics.list_uploads()}


@router.get("/uploads/{filename}")
async def get_photo(filename: str):
    # Resolve and confine to the upload dir so ../ cannot escape it.
    path = (graphics.UPLOAD_DIR / filename).resolve()
    if graphics.UPLOAD_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(str(path))


@router.delete("/uploads/{filename}")
async def delete_photo(filename: str) -> dict:
    path = (graphics.UPLOAD_DIR / filename).resolve()
    if graphics.UPLOAD_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    path.unlink()
    return {"deleted": filename}
