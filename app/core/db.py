# app/core/db.py
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Generator, Iterable, Optional

from .config import settings


DB_PATH = settings.DB_PATH


def _ensure_parent_dir(path: str) -> None:
    """
    Create the parent directory for `path` if it exists.
    If `path` is a bare filename (no directory), do nothing.
    """
    parent = os.path.dirname(os.path.abspath(path))
    # If path has no parent directory beyond the current directory (i.e., "."),
    # we still want to ensure "."/data exists when the default is "./data/..."
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def _connect() -> sqlite3.Connection:
    # Ensure the directory exists before connecting
    _ensure_parent_dir(DB_PATH)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """
    Initialize the SQLite DB if it doesn't exist.
    Safe to call multiple times.
    """
    _ensure_parent_dir(DB_PATH)
    with _connect() as conn:
        cur = conn.cursor()
        # Core table: matches what the app uses and what tests expect.
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS calls (
                id TEXT PRIMARY KEY,
                company_id TEXT,
                company_name TEXT,
                started_at TEXT,              -- ISO string (CallRail timezone or UTC-normalized upstream)
                duration_seconds INTEGER,
                source_name TEXT,
                tracking_number TEXT,
                customer_phone_number TEXT,
                tags TEXT,                    -- comma-separated
                call_type TEXT,               -- inbound/outbound
                call_status TEXT,             -- answered/missed/etc
                recording_url TEXT,
                agent_name TEXT,
                created_at TEXT,              -- ISO insert time
                qualified INTEGER,            -- null/0/1
                transcript TEXT,
                summary TEXT,
                ring_time_seconds INTEGER,
                hold_time_seconds INTEGER
            )
            """
        )
        conn.commit()


def migrate_db() -> None:
    """
    Add columns if your schema evolved. SQLite is lax, so we can add columns conditionally.
    This function is idempotent.
    """
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(calls)")
        cols = {row["name"] for row in cur.fetchall()}

        # Example future migrations (no-ops if already present)
        wanted: Iterable[tuple[str, str]] = (
            # ("some_new_col", "ALTER TABLE calls ADD COLUMN some_new_col TEXT"),
        )

        for name, ddl in wanted:
            if name not in cols:
                cur.execute(ddl)

        conn.commit()


@contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    """
    FastAPI dependency: yields a live connection per request.
    """
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


# --- Utilities for admin/maintenance endpoints ---

def exec_script(sql: str, params: Optional[tuple] = None) -> int:
    """
    Execute a write statement, return affected row count.
    """
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        conn.commit()
        return cur.rowcount


def query_all(sql: str, params: Optional[tuple] = None) -> list[dict]:
    """
    Run a SELECT and return list of dict rows.
    """
    with _connect() as conn:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        return [dict(r) for r in rows]
