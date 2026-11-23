"""All runtime configuration, read once from the environment (and backend/.env)."""

import os
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from loguru import logger

load_dotenv(Path(__file__).parent / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID") or "cgSgspJ2msm6clMCkdW9"  # "Jessica", usable on free plans
ELEVENLABS_TTS_MODEL = os.getenv("ELEVENLABS_TTS_MODEL") or "eleven_flash_v2_5"

# Groq (optional, recommended): much lower latency than Gemini's free API. When set it is the primary LLM
# and the Gemini models below become automatic fallbacks.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL = os.getenv("GROQ_MODEL") or "openai/gpt-oss-120b"

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL") or "gemini-3.5-flash-lite"
# Used when the main model is rate-limited or down. Free-tier quotas are per model.
GEMINI_FALLBACK_MODELS = [m.strip() for m in (os.getenv("GEMINI_FALLBACK_MODELS") or "gemini-3.6-flash,gemini-3.7-flash").split(",") if m.strip()]

HOST = os.getenv("HOST", "0.0.0.0")
PORT = _int("PORT", 7860)
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
MAX_CONCURRENT_CALLS = max(1, _int("MAX_CONCURRENT_CALLS", 3))
CALL_IDLE_TIMEOUT_SECS = _int("CALL_IDLE_TIMEOUT_SECS", 120)  # hang up if nobody speaks for this long
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
# One clock for everything: the agent's calendar, slot generation, "past" checks and the dashboard.
# Keeps Aria and the dashboard in sync even when the server runs in another timezone (e.g. UTC in the cloud).
CLINIC_TIMEZONE = os.getenv("CLINIC_TIMEZONE") or "Asia/Kolkata"
TZ = ZoneInfo(CLINIC_TIMEZONE)


def now() -> datetime:
    """Clinic wall-clock time (naive, like the slot times stored in the database)."""
    return datetime.now(TZ).replace(tzinfo=None)


def today() -> date:
    return now().date()


DB_PATH = Path(os.getenv("DB_PATH") or Path(__file__).parent / "clinic.db")


def missing_keys() -> list[str]:
    missing = [] if ELEVENLABS_API_KEY else ["ELEVENLABS_API_KEY"]
    if not (GROQ_API_KEY or GOOGLE_API_KEY):
        missing.append("GROQ_API_KEY or GOOGLE_API_KEY")
    return missing


def llm_chain() -> list[str]:
    """Models in failover order, e.g. ['groq:openai/gpt-oss-120b', 'gemini:gemini-3.5-flash-lite', ...]."""
    chain = [f"groq:{GROQ_MODEL}"] if GROQ_API_KEY else []
    if GOOGLE_API_KEY:
        chain += [f"gemini:{m}" for m in dict.fromkeys([GEMINI_MODEL, *GEMINI_FALLBACK_MODELS])]
    return chain


def setup_logging() -> None:
    """Pipecat logs every ICE candidate at DEBUG; keep production logs readable."""
    logger.remove()
    logger.add(sys.stderr, level=LOG_LEVEL, format="{time:HH:mm:ss} | {level: <7} | {name}:{function} - {message}")
