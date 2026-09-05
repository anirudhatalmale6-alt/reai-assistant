from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from app.routers import (chat, auth, health, dashboard, uploads, exports,
                         social_approval, showings, mcp)

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(title="REAI - Real Estate AI Assistant")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api/auth")
app.include_router(chat.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(uploads.router, prefix="/api")
app.include_router(exports.router, prefix="/api")
app.include_router(social_approval.router, prefix="/api")
app.include_router(showings.router, prefix="/api")

# No /api prefix: a connector URL is typed by hand into a vendor's form, and
# /mcp is the path both Anthropic's and OpenAI's documentation use as the
# example. Matching it removes one thing that can be got wrong.
app.include_router(mcp.router)


@app.get("/showings")
async def showings_page():
    return FileResponse(str(STATIC_DIR / "showings.html"))

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))
