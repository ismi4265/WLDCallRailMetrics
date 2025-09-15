# app/routers/webhooks.py
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request, Response, status

from app.core.config import settings

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

AGENT_TAG_RE = re.compile(r"(?i)^agent:\s*(.+)$")


def _open() -> sqlite3.Connection:
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _as_csv_tags(v: Any) -> str:
    """
    Accepts tags as:
      - list[str]
      - list[dict] with 'name'/'label'/'value'
      - CSV string
      - JSON string of a list
    Returns a simple comma-separated string: "Tag A,Tag B"
    """
    if v is None:
        return ""
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return ""
        # Try to parse as JSON list
        try:
            arr = json.loads(s)
            if isinstance(arr, list):
                v = arr
            else:
                return s
        except Exception:
            return s
    if isinstance(v, list):
        out: List[str] = []
        for t in v:
            if isinstance(t, str):
                name = t.strip()
            elif isinstance(t, dict):
                name = (t.get("name") or t.get("label") or t.get("value") or "").strip()
            else:
                name = ""
            if name:
                out.append(name)
        return ",".join(out)
    return ""


def _agent_from_tags(csv_tags: str) -> str:
    for part in [p.strip() for p in csv_tags.split(",") if p.strip()]:
        m = AGENT_TAG_RE.match(part)
        if m:
            return m.group(1).strip()
    return ""


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _int(v: Any) -> int:
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))
        except Exception:
            return 0


@router.post("/call-completed")
async def call_completed(req: Request) -> Response:
    """
    Idempotent upsert for CallRail's 'call completed' webhook.

    We’re liberal in what we accept:
      - duration may be 'duration_seconds', 'duration_in_seconds', or 'duration'
      - answered can be boolean, numeric, or string; we also interpret call_status
      - tags can be list/CSV/JSON; we also derive `agent_name` from 'Agent: ...' tag
    """
    payload = await req.json()
    call = payload.get("call") if isinstance(payload.get("call"), dict) else payload

    call_id: Optional[str] = call.get("id") or call.get("call_id")
    if not call_id:
        # Nothing to key on — reject politely
        return Response(status_code=status.HTTP_400_BAD_REQUEST)

    started_at = call.get("started_at") or call.get("start_time") or call.get("start_time_iso8601")

    duration_seconds = (
        call.get("duration_seconds")
        or call.get("duration_in_seconds")
        or call.get("duration")
        or 0
    )
    duration_seconds = _int(duration_seconds)

    answered = call.get("answered")
    if answered is None:
        status_val = (call.get("call_status") or "").strip().lower()
        if status_val in {"answered", "completed"}:
            answered = True
        elif status_val in {"missed", "no-answer"}:
            answered = False
    answered = _bool(answered)

    tags_csv = _as_csv_tags(call.get("tags"))

    agent_name = (call.get("agent_name") or call.get("agent") or "").strip()
    if not agent_name and tags_csv:
        agent_name = _agent_from_tags(tags_csv)

    row: Dict[str, Any] = {
        "id": call_id,
        "company_id": call.get("company_id"),
        "company_name": call.get("company_name"),
        "started_at": started_at,
        "duration_seconds": duration_seconds,
        "source_name": call.get("source_name") or call.get("source"),
        "tracking_number": call.get("tracking_number") or call.get("tracking_phone_number"),
        "customer_phone_number": call.get("customer_phone_number"),
        "tags": tags_csv,
        "call_type": call.get("direction") or call.get("call_type"),
        "call_status": "answered" if answered else (call.get("call_status") or None),
        "recording_url": call.get("recording_url"),
        "agent_name": agent_name or None,
        "created_at": call.get("created_at"),
        "qualified": call.get("qualified"),
        "transcript": call.get("transcript"),
        "summary": call.get("summary"),
        "ring_time_seconds": call.get("ring_time_seconds"),
        "hold_time_seconds": call.get("hold_time_seconds"),
    }

    cols = ",".join(row.keys())
    placeholders = ",".join([f":{k}" for k in row.keys()])
    updates = ",".join([f"{k}=excluded.{k}" for k in row.keys() if k != "id"])

    conn = _open()
    try:
        conn.execute(
            f"""
            INSERT INTO calls ({cols}) VALUES ({placeholders})
            ON CONFLICT(id) DO UPDATE SET {updates}
            """,
            row,
        )
        conn.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    finally:
        conn.close()
