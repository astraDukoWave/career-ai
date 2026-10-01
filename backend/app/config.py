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
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"

    # --- STT (Deepgram) ----------------------------------------------------
    # Optional at boot — without it the live WebSocket answers with an
    # `stt_unavailable` error and the text copilot keeps working.
    DEEPGRAM_API_KEY: str = ""

    # --- Live interview copilot (C2-SPEC-01) --------------------------------
    # Deepgram's live endpoint; overridable so tests can point at a local fake.
    DEEPGRAM_LIVE_URL: str = "wss://api.deepgram.com/v1/listen"
    STT_CONNECT_TIMEOUT_S: float = 5.0  # NFR-02
    STT_KEEPALIVE_S: float = 4.0  # KeepAlive after this long without audio (NFR-02)
    STT_ENDPOINTING_MS: int = 100  # REQ-02 "short": the CS-0 winner (PR #11)
    STT_UTTERANCE_END_MS: int = 1000  # REQ-02: >= 1000
    STT_MAX_KEYTERMS: int = 50  # REQ-03
    # REQ-04 v1.1: speech (a filler like "um" included) that starts within
    # this long after a turn closes continues it. Calibrated in the E2E.
    TURN_CONTINUATION_S: float = 1.5
    # NFR-05 cost guard: concurrent sessions per dyno and session length.
    LIVE_MAX_SESSIONS: int = 2
    LIVE_MAX_SESSION_S: float = 90 * 60

    # --- Storage -----------------------------------------------------------
    # Where generated CV PDFs/HTML are written. Mounted to a Docker volume.
    CV_OUTPUT_DIR: Path = Path("/app/storage/cvs")

    # --- CV Engine -----------------------------------------------------------
    # LLM bullet rewrite to "lift" the ATS score. OFF by default: on a real CV
    # (2026-09-29) it wove missing posting keywords into true bullets as new
    # claims ("static analysis", "machine learning", "functional programming",
    # "Linux"). Keywords get added only after the candidate confirms them
    # (Cycle #3). Set to true only to reproduce the old behaviour.
    CV_REWRITE_BULLETS: bool = False

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
