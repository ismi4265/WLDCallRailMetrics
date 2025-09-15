# app/core/config.py
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    CALLRAIL_API_KEY: str
    CALLRAIL_ACCOUNT_ID: str
    DB_PATH: str = "callrail_metrics.db"
    CORS_ORIGINS: str = "*"               # comma-separated or "*"
    EXCLUDE_AGENTS: str = ""              # e.g. "Taylor,John Doe"
    DEFAULT_ONLY_TAGS: str = ""           # e.g. "Existing Patient,New Patient"

    class Config:  # pydantic v2 warning is fine for now
        env_file = ".env"

settings = Settings()

# ---- Derived, module-level values (DO NOT assign back onto `settings`) ----
EXCLUDE_AGENT_LIST: List[str] = [a.strip() for a in settings.EXCLUDE_AGENTS.split(",") if a.strip()]
DEFAULT_ONLY_TAGS: List[str] = [t.strip() for t in settings.DEFAULT_ONLY_TAGS.split(",") if t.strip()]

ORIGINS = (
    [o.strip() for o in settings.CORS_ORIGINS.split(",")]
    if settings.CORS_ORIGINS and settings.CORS_ORIGINS != "*"
    else ["*"]
)

BASE_URL = "https://api.callrail.com/v3"
USER_AGENT = "CallRail-Metrics-App/1.4.1 (+fastapi)"
HEADERS = {
    "Authorization": f'Token token="{settings.CALLRAIL_API_KEY}"',
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}

DATE_COL = "substr(created_at,1,10)"  # 'YYYY-MM-DD'

# 👇 This must exist so imports don’t fail
BOOKING_TAGS = ["Appointment Booked", "AI Generated Scheduled"]
