"""Application settings loaded from environment variables.

Why a dedicated module: enforces the user rule that NO ports/hosts/credentials
are hardcoded anywhere in the codebase. Every value comes from env vars (with
safe defaults only for non-secret development values).
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings — fails loudly at startup if a required env var is missing."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # --- LLM ---------------------------------------------------------------
    # Optional at boot so the API can start even without a key configured.
    # The CV endpoint will return 503 with a clear error if it is missing.
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # --- STT (Deepgram) ----------------------------------------------------
    # Optional at boot — if missing, the STT client logs a warning and
    # returns "" so the WebSocket route stays alive.
    DEEPGRAM_API_KEY: str = ""

    # --- Storage -----------------------------------------------------------
    # Where generated CV PDFs/HTML are written. Mounted to a Docker volume.
    CV_OUTPUT_DIR: Path = Path("/app/storage/cvs")

    # --- CORS --------------------------------------------------------------
    # Comma-separated list — parsed by the property below.
    CORS_ORIGINS: str = "http://localhost:5173"

    @property
    def cors_origins_list(self) -> list[str]:
        """Split the env-var string into a clean list for FastAPI's CORSMiddleware."""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — call this from anywhere instead of instantiating Settings."""
    return Settings()
