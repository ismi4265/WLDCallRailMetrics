# app/routers/reports.py
from __future__ import annotations

import datetime as dt
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..core.db import get_db

router = APIRouter(prefix="/reports", tags=["reports"])


class AvgOut(BaseModel):
    average_seconds: float
    average_hms: str
    count: int
    start: str
    end: str
    note: Optional[str] = None


def _fmt_hms(seconds: float) -> str:
    s = int(round(seconds))
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"


@router.get("/avg-call-time-last-week", response_model=AvgOut)
def avg_call_time_last_week(
    only_agent: Optional[str] = Query(None, description="Filter by agent name OR tag 'Agent: {name}.' (period optional)"),
):
    end_date = dt.datetime.utcnow().date()
    start_date = end_date - dt.timedelta(days=7)
    start = start_date.isoformat()
    end = end_date.isoformat()

    params = [start, end]
    agent_sql = ""
    if only_agent:
        canon = only_agent.strip().lower()
        # match agent_name exactly (case-insensitive) or tags_norm contains ,agent: name., or ,agent: name,
        needle1 = f",agent: {canon}.,"
        needle2 = f",agent: {canon},"
        agent_sql = """
          AND (
                lower(coalesce(agent_name, '')) = ?
             OR coalesce(tags_norm, ',,') LIKE ?
             OR coalesce(tags_norm, ',,') LIKE ?
          )
        """
        params.extend([canon, f"%{needle1}%", f"%{needle2}%"])

    sql = f"""
    SELECT COUNT(*) AS cnt, AVG(duration_seconds) AS avg_sec
    FROM calls
    WHERE date(substr(started_at, 1, 10)) BETWEEN ? AND ?
      AND call_status = 'answered'
      AND duration_seconds > 0
      {agent_sql}
    """

    with get_db() as conn:
        row = conn.execute(sql, params).fetchone()
        cnt = int(row["cnt"] or 0)
        avg_sec = float(row["avg_sec"] or 0.0)

    note = None
    if cnt == 0 and only_agent:
        note = f"No answered calls for agent {only_agent} in the last 7 days (by name or 'Agent: {only_agent}.' tag)."

    return AvgOut(
        average_seconds=avg_sec,
        average_hms=_fmt_hms(avg_sec),
        count=cnt,
        start=start,
        end=end,
        note=note,
    )
