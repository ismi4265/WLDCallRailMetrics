# app/routers/metrics.py
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..core.db import get_db

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _today_utc_date() -> dt.date:
    # Keep utcnow for compatibility with tests (you can switch to timezone-aware later)
    return dt.datetime.utcnow().date()


# ---------- /metrics/answer-rate ----------

class AnswerRateOut(BaseModel):
    start: str
    end: str
    answered: int
    total: int
    answer_rate: float


@router.get("/answer-rate", response_model=AnswerRateOut)
def answer_rate(days: int = Query(7, ge=1, le=90)) -> AnswerRateOut:
    today = _today_utc_date()
    start = (today - dt.timedelta(days=days)).isoformat()
    end = today.isoformat()

    sql = """
    SELECT
      SUM(CASE WHEN call_status = 'answered' THEN 1 ELSE 0 END) AS answered,
      COUNT(*) AS total
    FROM calls
    WHERE date(substr(started_at, 1, 10)) BETWEEN ? AND ?
    """
    with get_db() as conn:
        row = conn.execute(sql, (start, end)).fetchone()
        answered = int(row["answered"] or 0)
        total = int(row["total"] or 0)

    rate = (answered / total) if total else 0.0
    return AnswerRateOut(start=start, end=end, answered=answered, total=total, answer_rate=rate)


# ---------- /metrics/conversion ----------

BOOKING_TAGS = ("ai generated scheduled", "appointment booked", "booked", "scheduled")


class ConversionOut(BaseModel):
    start: str
    end: str
    answered: int
    booked: int
    booked_rate: float


@router.get("/conversion", response_model=ConversionOut)
def conversion(
    days: int = Query(7, ge=1, le=90),
    only_tags: Optional[str] = Query(None, description="Comma-separated filter of required tags (case-insensitive)"),
) -> ConversionOut:
    today = _today_utc_date()
    start = (today - dt.timedelta(days=days)).isoformat()
    end = today.isoformat()

    params: List[Any] = [start, end]
    extra = ""
    if only_tags:
        # require any of the provided tags to be present (OR over list)
        wanted = [t.strip().lower() for t in only_tags.split(",") if t.strip()]
        if wanted:
            ors = []
            for t in wanted:
                ors.append("(',' || lower(coalesce(tags, '')) || ',') LIKE ?")
                params.append(f"%,{t},%")
            extra = " AND (" + " OR ".join(ors) + ")"

    answered_sql = f"""
    SELECT COUNT(*) AS c
    FROM calls
    WHERE date(substr(started_at, 1, 10)) BETWEEN ? AND ?
      AND call_status = 'answered'
    {extra}
    """

    booked_sql = f"""
    SELECT COUNT(*) AS c
    FROM calls
    WHERE date(substr(started_at, 1, 10)) BETWEEN ? AND ?
      AND call_status = 'answered'
      AND (
        {" OR ".join(["(',' || lower(coalesce(tags, '')) || ',') LIKE ?"] * len(BOOKING_TAGS))}
      )
    {extra}
    """

    with get_db() as conn:
        # answered
        arow = conn.execute(answered_sql, params).fetchone()
        answered = int(arow["c"] or 0)

        # booked (add booking tags to params)
        bparams = list(params)
        for t in BOOKING_TAGS:
            bparams.append(f"%,{t},%")
        brow = conn.execute(booked_sql, bparams).fetchone()
        booked = int(brow["c"] or 0)

    booked_rate = (booked / answered) if answered else 0.0
    return ConversionOut(start=start, end=end, answered=answered, booked=booked, booked_rate=booked_rate)


# ---------- /metrics/agent-scorecard ----------

class AgentRow(BaseModel):
    agent: str
    calls: int
    answered: int
    booked: int
    booked_rate: float


class AgentScorecardOut(BaseModel):
    start: str
    end: str
    agents: List[AgentRow]


@router.get("/agent-scorecard", response_model=AgentScorecardOut)
def agent_scorecard(days: int = Query(7, ge=1, le=90)) -> AgentScorecardOut:
    today = _today_utc_date()
    start = (today - dt.timedelta(days=days)).isoformat()
    end = today.isoformat()

    # Base per-agent counts
    sql = """
    SELECT
      coalesce(agent_name, '') AS agent,
      COUNT(*) AS calls,
      SUM(CASE WHEN call_status = 'answered' THEN 1 ELSE 0 END) AS answered
    FROM calls
    WHERE date(substr(started_at, 1, 10)) BETWEEN ? AND ?
    GROUP BY coalesce(agent_name, '')
    HAVING calls > 0
    ORDER BY agent
    """
    agents: Dict[str, Dict[str, int]] = {}
    with get_db() as conn:
        for r in conn.execute(sql, (start, end)).fetchall():
            agent = r["agent"]
            agents[agent] = {
                "calls": int(r["calls"] or 0),
                "answered": int(r["answered"] or 0),
                "booked": 0,
            }

        # booked by agent (answered + tag in BOOKING_TAGS)
        booked_sql = f"""
        SELECT coalesce(agent_name, '') AS agent, COUNT(*) AS booked
        FROM calls
        WHERE date(substr(started_at, 1, 10)) BETWEEN ? AND ?
          AND call_status = 'answered'
          AND (
            {" OR ".join(["(',' || lower(coalesce(tags, '')) || ',') LIKE ?"] * len(BOOKING_TAGS))}
          )
        GROUP BY coalesce(agent_name, '')
        """
        bparams: List[Any] = [start, end]
        for t in BOOKING_TAGS:
            bparams.append(f"%,{t},%")

        for r in conn.execute(booked_sql, bparams).fetchall():
            key = r["agent"]
            if key in agents:
                agents[key]["booked"] = int(r["booked"] or 0)

    rows: List[AgentRow] = []
    for name, d in agents.items():
        calls = d["calls"]
        answered = d["answered"]
        booked = d["booked"]
        rate = (booked / answered) if answered else 0.0
        rows.append(AgentRow(agent=name or "(unknown)", calls=calls, answered=answered, booked=booked, booked_rate=rate))

    return AgentScorecardOut(start=start, end=end, agents=rows)


# ---------- /metrics/time-buckets ----------

class TimeBucketsOut(BaseModel):
    start: str
    end: str
    by: str
    buckets: List[Dict[str, int]]
    grid: List[int]


@router.get("/time-buckets", response_model=TimeBucketsOut)
def time_buckets(days: int = Query(7, ge=1, le=90)) -> TimeBucketsOut:
    """
    Return a 24-slot hour-of-day histogram for calls within the window.
    `grid` is a list with 24 integers indexed 0..23.
    """
    today = _today_utc_date()
    start = (today - dt.timedelta(days=days)).isoformat()
    end = today.isoformat()

    # We parse hour from started_at (ISO-ish text). Handle cases without 'T' gracefully.
    sql = """
    SELECT
      CAST(strftime('%H', replace(replace(started_at, 'T', ' '), 'Z', '')) AS INTEGER) AS hr,
      COUNT(*) AS c
    FROM calls
    WHERE date(substr(started_at, 1, 10)) BETWEEN ? AND ?
    GROUP BY hr
    """
    counts: Dict[int, int] = {i: 0 for i in range(24)}
    with get_db() as conn:
        for r in conn.execute(sql, (start, end)).fetchall():
            hr = r["hr"]
            c = r["c"]
            if hr is not None and 0 <= int(hr) <= 23:
                counts[int(hr)] = int(c)

    grid = [counts[h] for h in range(24)]
    # compact buckets for convenience too
    buckets = [{"bucket": h, "count": counts[h]} for h in range(24) if counts[h] > 0]

    return TimeBucketsOut(start=start, end=end, by="hour", buckets=buckets, grid=grid)
