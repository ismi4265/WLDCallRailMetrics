# app/routers/admin.py
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..core.config import settings
from ..core.db import get_db
from ..services.callrail import CallRailClient

router = APIRouter(prefix="/admin", tags=["admin"])

AGENT_TAG_RE = re.compile(r"^\s*agent:\s*([^\.,]+)\.?\s*$", re.I)


def _now_iso() -> str:
    return dt.datetime.utcnow().isoformat()


def _normalize_tag_list(raw_tags: Optional[List[str]]) -> Tuple[str, str, List[str]]:
    """
    Returns (tags_csv, tags_norm, agents_from_tags)
      - tags_csv: original tags joined by ", "
      - tags_norm: ",{lower_tag1},{lower_tag2}," for reliable LIKE '%,"pattern",%'
      - agents_from_tags: ["Taylor", ...] parsed from tags "Agent: Taylor."
    """
    if not raw_tags:
        return "", ",,", []

    cleaned = [t.strip() for t in raw_tags if isinstance(t, str) and t.strip()]
    tags_csv = ", ".join(cleaned)

    lowered = [t.lower().strip() for t in cleaned]
    tags_norm = "," + ",".join(lowered) + ","

    agents: List[str] = []
    for t in lowered:
        m = AGENT_TAG_RE.match(t)
        if m:
            agents.append(m.group(1).strip().title())

    return tags_csv, tags_norm, agents


def _derive_status(answered: Optional[bool], voicemail: Optional[bool]) -> str:
    if answered:
        return "answered"
    if voicemail:
        return "voicemail"
    return "missed"


class RefreshResult(BaseModel):
    status: str
    examined: int
    upserted: int
    start: str
    end: str


@router.post("/refresh-calls", response_model=RefreshResult)
def refresh_calls(days: int = Query(14, ge=1, le=90), company_id: Optional[str] = None):
    if not settings.CALLRAIL_API_KEY or not settings.CALLRAIL_ACCOUNT_ID:
        raise HTTPException(status_code=400, detail="Missing CALLRAIL credentials")

    today = dt.datetime.utcnow().date()
    start_date = (today - dt.timedelta(days=days)).isoformat()
    end_date = today.isoformat()

    client = CallRailClient(
        api_key=settings.CALLRAIL_API_KEY,
        account_id=settings.CALLRAIL_ACCOUNT_ID,
        base_url=getattr(settings, "CALLRAIL_API_URL", "https://api.callrail.com/v3"),
    )

    calls = client.list_calls(
        start_date=start_date,
        end_date=end_date,
        per_page=250,
        relative=True,
        fields=[
            "tags",
            "agent_email",
            "company_id",
            "company_name",
            "source_name",
            "business_phone_number",
            "customer_phone_number",
        ],
        company_id=company_id,
        sort="start_time",
        order="desc",
    )

    examined = 0
    upserted = 0

    with get_db() as conn:
        for c in calls:
            examined += 1
            cid = c.get("id")
            if not cid:
                continue

            answered = c.get("answered")
            voicemail = c.get("voicemail")
            call_status = _derive_status(answered, voicemail)

            # duration is in seconds per CallRail
            try:
                duration_seconds = int(c.get("duration") or 0)
            except Exception:
                duration_seconds = 0

            started_at = c.get("start_time")
            call_type = c.get("direction") or "inbound"
            recording_url = c.get("recording")

            tags_csv, tags_norm, agents = _normalize_tag_list(c.get("tags") or [])

            # Prefer name from agent_email; else fall back to Agent: {Name}. tag
            agent_email = c.get("agent_email")
            agent_name = None
            if agent_email:
                agent_name = agent_email.split("@", 1)[0].replace(".", " ").title()
            if not agent_name and agents:
                agent_name = agents[0]

            conn.execute(
                """
                INSERT INTO calls (
                    id, company_id, company_name, started_at, duration_seconds, source_name,
                    tracking_number, customer_phone_number, tags, tags_norm, call_type,
                    call_status, recording_url, agent_name, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    company_id=excluded.company_id,
                    company_name=excluded.company_name,
                    started_at=excluded.started_at,
                    duration_seconds=excluded.duration_seconds,
                    source_name=excluded.source_name,
                    tracking_number=excluded.tracking_number,
                    customer_phone_number=excluded.customer_phone_number,
                    tags=excluded.tags,
                    tags_norm=excluded.tags_norm,
                    call_type=excluded.call_type,
                    call_status=excluded.call_status,
                    recording_url=excluded.recording_url,
                    agent_name=excluded.agent_name
                """,
                (
                    str(cid),
                    c.get("company_id"),
                    c.get("company_name"),
                    started_at,
                    duration_seconds,
                    c.get("source_name"),
                    c.get("tracking_phone_number"),
                    c.get("customer_phone_number"),
                    tags_csv,
                    tags_norm,
                    call_type,
                    call_status,
                    recording_url,
                    agent_name,
                    _now_iso(),
                ),
            )
            upserted += 1

    return RefreshResult(status="ok", examined=examined, upserted=upserted, start=start_date, end=end_date)


class QuickRepairOut(BaseModel):
    status: str
    answered_fixed: int
    agent_fixed: int
    tags_norm_fixed: int


@router.post("/quick-repair", response_model=QuickRepairOut)
def quick_repair():
    """
    Backfill:
      - call_status from answered/voicemail heuristics (if you ever ingest raw flags)
      - agent_name from Agent: {Name}. in tags when agent_name is NULL
      - tags_norm from tags (for reliable search)
    """
    answered_fixed = 0
    agent_fixed = 0
    tags_norm_fixed = 0

    with get_db() as conn:
        # call_status repair based on existing call_status/duration if needed
        # (Keep this simple — most are already set.)
        # agent_name from tags
        cur = conn.execute("SELECT id, tags, agent_name FROM calls")
        rows = cur.fetchall()
        for r in rows:
            call_id = r["id"]
            tags = r["tags"] or ""
            agent_name = r["agent_name"]
            tags_csv, tags_norm, agents = _normalize_tag_list([t.strip() for t in tags.split(",") if t.strip()])
            # only update tags_norm if changed
            if (r.get("tags_norm") if isinstance(r, dict) else None) != tags_norm:
                conn.execute("UPDATE calls SET tags_norm = ? WHERE id = ?", (tags_norm, call_id))
                tags_norm_fixed += 1
            if not agent_name and agents:
                conn.execute("UPDATE calls SET agent_name = ? WHERE id = ?", (agents[0], call_id))
                agent_fixed += 1

    return QuickRepairOut(status="ok", answered_fixed=answered_fixed, agent_fixed=agent_fixed, tags_norm_fixed=tags_norm_fixed)


class PreviewAgentOut(BaseModel):
    start: str
    end: str
    agent: str
    count: int
    rows: List[Dict[str, Any]]


@router.get("/preview-agent", response_model=PreviewAgentOut)
def preview_agent(tag_agent: str = Query(...), days: int = Query(14, ge=1, le=90)):
    """
    Preview rows that match "Agent: {name}." tag (period optional, case-insensitive), using tags_norm.
    """
    today = dt.datetime.utcnow().date()
    start = (today - dt.timedelta(days=days)).isoformat()
    end = today.isoformat()

    needle1 = f",agent: {tag_agent.lower().strip()}.,"
    needle2 = f",agent: {tag_agent.lower().strip()},"

    sql = """
    SELECT id, started_at, duration_seconds, call_status, agent_name, tags
    FROM calls
    WHERE date(substr(started_at, 1, 10)) BETWEEN ? AND ?
      AND (
        coalesce(tags_norm, ',,') LIKE ?
        OR coalesce(tags_norm, ',,') LIKE ?
      )
    ORDER BY started_at DESC
    LIMIT 50
    """

    rows: List[Dict[str, Any]] = []
    with get_db() as conn:
        for r in conn.execute(sql, (start, end, f"%{needle1}%", f"%{needle2}%")).fetchall():
            rows.append({
                "id": r["id"],
                "started_at": r["started_at"],
                "duration_seconds": r["duration_seconds"],
                "call_status": r["call_status"],
                "agent_name": r["agent_name"],
                "tags": r["tags"],
            })

    return PreviewAgentOut(start=start, end=end, agent=tag_agent, count=len(rows), rows=rows)
