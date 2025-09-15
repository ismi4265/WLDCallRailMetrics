# app/core/config.py
from __future__ import annotations

import os
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # === Core ===
    CALLRAIL_API_KEY: str = Field(default=os.getenv("CALLRAIL_API_KEY", ""))
    CALLRAIL_ACCOUNT_ID: str = Field(default=os.getenv("CALLRAIL_ACCOUNT_ID", ""))

    # A safe default so running locally “just works”
    DB_PATH: str = Field(
        default=os.getenv("DB_PATH", os.path.join(".", "data", "callrail.sqlite3"))
    )

    # CORS
    CORS_ORIGINS: str = Field(default=os.getenv("CORS_ORIGINS", "*"))

    # Filtering / Tags
    EXCLUDE_AGENTS: str = Field(default=os.getenv("EXCLUDE_AGENTS", ""))  # CSV
    DEFAULT_ONLY_TAGS: str = Field(default=os.getenv("DEFAULT_ONLY_TAGS", ""))  # CSV

    DEBUG: bool = Field(default=bool(int(os.getenv("DEBUG", "0"))))

    # Derived convenience lists (computed post-init)
    EXCLUDE_AGENT_LIST: List[str] = []
    DEFAULT_ONLY_TAGS_LIST: List[str] = []

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    def _compute_derived(self) -> None:
        def to_list(csv: str) -> List[str]:
            return [x.strip() for x in csv.split(",") if x.strip()]

        self.EXCLUDE_AGENT_LIST = to_list(self.EXCLUDE_AGENTS)
        self.DEFAULT_ONLY_TAGS_LIST = to_list(self.DEFAULT_ONLY_TAGS)


# Public module-level singletons/constants
settings = Settings()
settings._compute_derived()

# CORS origins as a list
ORIGINS: List[str] = (
    ["*"]
    if settings.CORS_ORIGINS.strip() == "*"
    else [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
)

# Booking tag aliases used in conversion metrics
BOOKING_TAGS: List[str] = [
    "Appointment Booked",
    "Booked",
    "AI Generated Scheduled",
    "AI Scheduled",
]

# Re-exports for backwards compatibility
EXCLUDE_AGENT_LIST: List[str] = settings.EXCLUDE_AGENT_LIST
DEFAULT_ONLY_TAGS: List[str] = settings.DEFAULT_ONLY_TAGS
