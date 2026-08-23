"""Reading the documents the agent attaches in the chat.

Photos go straight into the graphic generator by filename. A PDF, TXT or CSV
needs its text pulling out first - a feature sheet, an offer, a Lofty export.
"""
from pathlib import Path

from app.services import graphics

MAX_CHARS = 20000  # a long agreement still fits; a 300-page dump does not

TOOLS = [
    {
        "name": "read_document",
        "description": (
            "Read a PDF, TXT or CSV the agent attached in the chat. Use this whenever the "
            "agent attaches a document and asks a question about it - a feature sheet, an "
            "offer, a listing agreement, a CSV export. Returns the text. The file is already "
            "on the server: never ask the agent to email it, re-upload it or paste it in. "
            "If you are unsure of the exact filename call list_attached_files first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "The attached file's name, exactly as given in the chat.",
                },
                "max_pages": {
                    "type": "integer",
                    "description": "PDFs only. How many pages to read. Leave out to read it all.",
                    "default": 0,
                },
            },
            "required": ["filename"],
        },
    },
    {
        "name": "list_attached_files",
        "description": ("List the documents (PDF, TXT, CSV) the agent has attached, newest "
                        "first. For photos use list_listing_photos instead."),
        "input_schema": {"type": "object", "properties": {}},
    },
]

DOC_EXT = {".pdf", ".txt", ".csv"}


def _resolve(filename: str) -> Path:
    """Confine to the upload dir - a filename off the model must not escape it."""
    name = Path(str(filename or "").strip()).name
    path = (graphics.UPLOAD_DIR / name).resolve()
    if graphics.UPLOAD_DIR.resolve() not in path.parents or not path.is_file():
        raise FileNotFoundError(f"No attached file called {name}")
    return path


def _read_pdf(path: Path, max_pages: int) -> tuple[str, int]:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise RuntimeError("PDF reading is not installed on the server yet")

    try:
        reader = PdfReader(str(path))
        pages = reader.pages[:max_pages] if max_pages and max_pages > 0 else reader.pages
        text = "\n\n".join((p.extract_text() or "").strip() for p in pages)
    except Exception as e:
        # A damaged or password-locked PDF. Say it plainly - the raw pypdf
        # message means nothing to the agent.
        raise RuntimeError(f"Could not open {path.name} - the PDF looks damaged or "
                           f"password-protected ({e}). Ask the agent to re-save and attach it again.")
    return text, len(reader.pages)


def _read(params: dict) -> dict:
    path = _resolve(params.get("filename", ""))
    suffix = path.suffix.lower()
    if suffix not in DOC_EXT:
        return {"error": f"{path.name} is not a document. Images go into a graphic by filename."}

    if suffix == ".pdf":
        text, page_count = _read_pdf(path, params.get("max_pages") or 0)
        meta = {"pages": page_count}
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
        meta = {}

    text = text.strip()
    if not text:
        # A scanned contract is images, not text. Say so rather than returning
        # nothing and letting the assistant guess at what is in it.
        return {"filename": path.name,
                "error": "No text in this file - it looks like a scan. Ask the agent what it says.",
                **meta}

    truncated = len(text) > MAX_CHARS
    return {"filename": path.name, "text": text[:MAX_CHARS], "truncated": truncated, **meta}


def _list(params: dict) -> dict:
    files = sorted((p for p in graphics.UPLOAD_DIR.iterdir()
                    if p.is_file() and p.suffix.lower() in DOC_EXT),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return {"files": [{"filename": p.name, "kb": round(p.stat().st_size / 1024)}
                      for p in files[:40]]}


HANDLERS = {
    "read_document": _read,
    "list_attached_files": _list,
}
