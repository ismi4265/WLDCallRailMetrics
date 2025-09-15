# app/routers/ingest.py
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from typing import Any, Dict, List, Union, Optional
import re
import sqlite3
import json
import re

from app.core.config import settings

router = APIRouter(prefix="/ingest", tags=["ingest"])


DUR_HMS = re.compile(r"^\s*(\d{1,2}):([0-5]?\d):([0-5]?\d)\s*$")
DUR_MS  = re.compile(r"^\s*([0-5]?\d):([0-5]?\d)\s*$")
# Matches "1h 2m 3s", "2m 3s", "2m", "75s" (whitespace flexible, case-insensitive)
DUR_HUMAN = re.compile(
    r"(?i)^\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m(?:in)?)?\s*(?:(\d+)\s*s)?\s*$"
)

AGENT_TAG_RE = re.compile(r'(?i)(?:^|,)\s*agent:\s*([^,]+?)\s*(?:,|$)')


def _parse_duration_to_seconds(value: Any) -> int:
    """
    Accepts:
      - int/float seconds
      - numeric strings like "180"
      - time strings "H:MM:SS" or "MM:SS"
      - human strings like "1h 2m 3s", "2m 2s", "2m", "122s"
    Returns a non-negative integer seconds (0 on failure).
    """
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return max(0, int(value))

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return 0

        # pure number
        if s.isdigit():
            return max(0, int(s))

        # H:MM:SS
        m = DUR_HMS.match(s)
        if m:
            h, mm, ss = map(int, m.groups())
            return max(0, h * 3600 + mm * 60 + ss)

        # MM:SS
        m = DUR_MS.match(s)
        if m:
            mm, ss = map(int, m.groups())
            return max(0, mm * 60 + ss)

        # "1h 2m 3s" / "2m 2s" / "2m" / "75s"
        m = DUR_HUMAN.match(s)
        if m:
            h, mm, ss = m.groups()
            h = int(h) if h else 0
            mm = int(mm) if mm else 0
            ss = int(ss) if ss else 0
            return max(0, h * 3600 + mm * 60 + ss)

    return 0


def _normalize_tags(value: Any) -> str:
    """
    Normalize to a single comma-separated string.
      - list[str] -> comma join
      - list[dict] -> take 'name'/'label'/'value'
      - JSON-looking string -> parse then normalize
      - plain string -> as-is
    """
    if value is None:
        return ""

    def _from_list(lst):
        out = []
        for t in lst:
            if isinstance(t, str):
                s = t.strip()
            elif isinstance(t, dict):
                s = (t.get("name") or t.get("label") or t.get("value") or "").strip()
            else:
                s = ""
            if s:
                out.append(s)
        return ",".join(out)

    if isinstance(value, list):
        return _from_list(value)

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return ""
        # Try JSON array string
        try:
            arr = json.loads(s)
            if isinstance(arr, list):
                return _from_list(arr)
        except Exception:
            pass
        return s

    return ""


def _extract_agent_from_tags(tags_str: Optional[str]) -> Optional[str]:
    """Return the agent name from a tag like 'Agent: Taylor' or 'Agent:Taylor'."""
    if not tags_str:
        return None
    # Ensure token boundaries by wrapping with commas
    haystack = f",{tags_str},"
    m = AGENT_TAG_RE.search(haystack)
    if m:
        return m.group(1).strip()
    return None


def _open_db() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@router.post("/calls")
def ingest_calls(payload: Union[List[Dict[str, Any]], Dict[str, Any]]) -> Dict[str, Any]:
    """
    Ingest CallRail-style call rows. Accepts either:
      - a JSON array of call objects, or
      - an object with a key 'calls' that is an array.

    Behavior:
      - Normalize duration_* to integer seconds -> 'duration_seconds'.
      - Normalize tags to single comma-separated string -> 'tags'.
      - If 'agent_name' missing, derive it from 'Agent: <name>' tag.
    """
    if isinstance(payload, dict) and "calls" in payload:
        calls = payload["calls"]
    else:
        calls = payload

    if not isinstance(calls, list):
        raise HTTPException(status_code=400, detail="Expected a list of calls.")

    to_insert = []
    for c in calls:
        if not isinstance(c, dict):
            continue

        duration_raw = (
            c.get("duration_seconds")
            or c.get("duration_in_seconds")
            or c.get("duration")
        )
        tags = _normalize_tags(c.get("tags"))
        agent_name = (c.get("agent_name") or "").strip() or _extract_agent_from_tags(tags)

        row = {
            "call_id": c.get("call_id"),
            "company_id": c.get("company_id"),
            "call_type": c.get("call_type"),
            "call_status": c.get("call_status"),
            "agent_name": agent_name,
            "duration_seconds": _parse_duration_to_seconds(duration_raw),
            "created_at": c.get("created_at"),  # ISO8601 in UTC (string)
            "recording_url": c.get("recording_url"),
            "transcript": c.get("transcript"),
            "summary": c.get("summary"),
            "tags": tags,
        }
        to_insert.append(row)

    if not to_insert:
        return {"inserted": 0}

    conn = _open_db()
    try:
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT OR REPLACE INTO calls (
              call_id, company_id, call_type, call_status, agent_name,
              duration_seconds, created_at, recording_url, transcript, summary, tags
            )
            VALUES (
              :call_id, :company_id, :call_type, :call_status, :agent_name,
              :duration_seconds, :created_at, :recording_url, :transcript, :summary, :tags
            )
            """,
            to_insert,
        )
        conn.commit()
        return {"inserted": cur.rowcount}
    finally:
        conn.close()
