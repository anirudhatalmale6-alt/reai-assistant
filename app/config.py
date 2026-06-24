from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    ANTHROPIC_API_KEY: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/callback"
    LOFTY_API_KEY: str = ""
    LOFTY_CLIENT_ID: str = ""
    LOFTY_CLIENT_SECRET: str = ""
    LOFTY_REDIRECT_URI: str = "http://localhost"
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    META_REDIRECT_URI: str = "http://localhost/"
    APP_SECRET_KEY: str = "change-me-in-production"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    TOKEN_DIR: Path = BASE_DIR / "data" / "tokens"

    GOOGLE_SCOPES: list[str] = [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/drive.readonly",
    ]

    model_config = {"env_file": str(Path(__file__).resolve().parent.parent / ".env"), "env_file_encoding": "utf-8"}


settings = Settings()
settings.TOKEN_DIR.mkdir(parents=True, exist_ok=True)
