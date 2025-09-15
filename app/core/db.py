# app/core/db.py
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .config import settings

DB_PATH = settings.DB_PATH


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY,
                company_id TEXT,
                company_name TEXT,
                started_at TEXT,
                duration_seconds INTEGER,
                source_name TEXT,
                tracking_number TEXT,
                customer_phone_number TEXT,
                tags TEXT,
                call_type TEXT,
                call_status TEXT,
                recording_url TEXT,
                agent_name TEXT,
                created_at TEXT,
                qualified INTEGER,
                transcript TEXT,
                summary TEXT,
                ring_time_seconds INTEGER,
                hold_time_seconds INTEGER,
                -- new: normalized tags for reliable lookups
                tags_norm TEXT
            )
            """
        )
        # helpful indices
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_started_at ON calls(started_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_call_status ON calls(call_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_agent_name ON calls(agent_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_tags_norm ON calls(tags_norm)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_duration ON calls(duration_seconds)")
        conn.commit()


def migrate_db() -> None:
    """
    Keep schema up-to-date across versions. Add tags_norm if missing, plus indices.
    """
    with get_db() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(calls)").fetchall()}
        if "tags_norm" not in cols:
            conn.execute("ALTER TABLE calls ADD COLUMN tags_norm TEXT")
        # indices are idempotent
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_started_at ON calls(started_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_call_status ON calls(call_status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_agent_name ON calls(agent_name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_tags_norm ON calls(tags_norm)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_calls_duration ON calls(duration_seconds)")
        conn.commit()
