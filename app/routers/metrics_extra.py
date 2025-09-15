from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlite3 import Row

from ..core.db import get_db

router = APIRouter(prefix="/metrics", tags=["metrics-extra"])


def _utc_today_date():
    # Use timezone-aware now to avoid warnings
    return datetime.now(timezone.utc).date()


def _date_str(dt) -> str:
    return str(dt)


def _percentile(values: List[float], p: float) -> float:
    """
    Simple percentile calc in Python for SQLite results.
    values must be sorted already; p in [0,1].
    """
    if not values:
        return 0.0
    if p <= 0:
        return float(values[0])
    if p >= 1:
        return float(values[-1])
    idx = (len(values) - 1) * p
    lo = int(idx)
    hi = min(lo + 1, len(values) - 1)
    frac = idx - lo
    return float(values[lo] * (1 - frac) + values[hi] * frac)


# ------------------------------------------------------------
# 1) Speed to Answer
# ------------------------------------------------------------
@router.get("/speed-to-answer")
def speed_to_answer(
    days: int = Query(7, ge=1, le=365),
    sla: int = Query(30, ge=0, description="SLA threshold in seconds"),
    db=Depends(get_db),
):
    """
    Average ring time (seconds) for answered calls within last `days`.
    Also returns SLA achievement rate (answered within `sla` seconds)
    and p50/p90 percentiles (computed in Python).
    """
    today = _utc_today_date()
    start = today - timedelta(days=days)

    # Pull individual ring times (fallback to 0 when NULL)
    q = """
    SELECT COALESCE(ring_time_seconds, 0) AS ring_s
    FROM calls
    WHERE call_status = 'answered'
      AND duration_seconds > 0
      AND DATE(substr(started_at,1,10)) >= DATE(:start)
    """
    rows: List[Row] = db.execute(q, {"start": _date_str(start)}).fetchall()
    rings = [int(r["ring_s"]) for r in rows]

    total = len(rings)
    avg_seconds = float(sum(rings) / total) if total else 0.0
    p50_seconds = _percentile(sorted(rings), 0.5) if total else 0.0
    p90_seconds = _percentile(sorted(rings), 0.9) if total else 0.0
    sla_rate = (sum(1 for x in rings if x <= sla) / total) if total else 0.0

    return {
        "total": total,
        "avg_seconds": round(avg_seconds, 2),
        "p50_seconds": round(p50_seconds, 2),
        "p90_seconds": round(p90_seconds, 2),
        "sla_rate": round(sla_rate, 4),
        "start": _date_str(start),
        "end": _date_str(today),
    }


# ------------------------------------------------------------
# 2) Agent Occupancy
# ------------------------------------------------------------
@router.get("/agent-occupancy")
def agent_occupancy(
    days: int = Query(7, ge=1, le=365),
    db=Depends(get_db),
):
    """
    Per-agent: answered call count, total talk/hold seconds, avg talk seconds.
    """
    today = _utc_today_date()
    start = today - timedelta(days=days)

    q = """
    SELECT
      COALESCE(agent_name, 'Unassigned') AS agent,
      COUNT(*)                           AS answered_calls,
      SUM(duration_seconds)              AS total_talk_seconds,
      SUM(COALESCE(hold_time_seconds,0)) AS total_hold_seconds,
      AVG(duration_seconds)              AS avg_talk_seconds
    FROM calls
    WHERE call_status = 'answered'
      AND duration_seconds > 0
      AND DATE(substr(started_at,1,10)) >= DATE(:start)
    GROUP BY agent
    ORDER BY total_talk_seconds DESC
    """
    rows: List[Row] = db.execute(q, {"start": _date_str(start)}).fetchall()
    return {
        "start": _date_str(start),
        "end": _date_str(today),
        "agents": [
            {
                "agent": r["agent"],
                "answered_calls": int(r["answered_calls"] or 0),
                "total_talk_seconds": int(r["total_talk_seconds"] or 0),
                "total_hold_seconds": int(r["total_hold_seconds"] or 0),
                "avg_talk_seconds": float(r["avg_talk_seconds"] or 0.0),
            }
            for r in rows
        ],
    }


# ------------------------------------------------------------
# 3) New vs Returning Callers
# ------------------------------------------------------------
@router.get("/new-vs-returning")
def new_vs_returning(
    days: int = Query(30, ge=1, le=365),
    db=Depends(get_db),
):
    """
    Within last `days` calls, how many callers are first-time vs returning.
    """
    today = _utc_today_date()
    start = today - timedelta(days=days)

    q = """
    WITH recent AS (
      SELECT DISTINCT customer_phone_number
      FROM calls
      WHERE customer_phone_number IS NOT NULL AND customer_phone_number <> ''
        AND DATE(substr(started_at,1,10)) >= DATE(:start)
    ),
    first_seen AS (
      SELECT customer_phone_number, MIN(DATE(substr(started_at,1,10))) AS first_date
      FROM calls
      WHERE customer_phone_number IS NOT NULL AND customer_phone_number <> ''
      GROUP BY customer_phone_number
    )
    SELECT
      SUM(CASE WHEN f.first_date >= DATE(:start) THEN 1 ELSE 0 END) AS new_callers,
      SUM(CASE WHEN f.first_date <  DATE(:start) THEN 1 ELSE 0 END) AS returning_callers
    FROM recent r
    JOIN first_seen f USING (customer_phone_number)
    """
    row: Row | None = db.execute(q, {"start": _date_str(start)}).fetchone()
    new_callers = int(row["new_callers"] or 0) if row else 0
    returning_callers = int(row["returning_callers"] or 0) if row else 0

    return {
        "start": _date_str(start),
        "end": _date_str(today),
        "new_callers": new_callers,
        "returning_callers": returning_callers,
        "new_rate": round(new_callers / (new_callers + returning_callers), 4)
        if (new_callers + returning_callers) > 0
        else 0.0,
    }


# ------------------------------------------------------------
# 4) Source Conversion (by source_name)
# ------------------------------------------------------------
@router.get("/source-conversion")
def source_conversion(
    days: int = Query(30, ge=1, le=365),
    only_tags: Optional[str] = Query(
        None, description="Restrict rows to calls containing this single tag (case-insensitive)."
    ),
    db=Depends(get_db),
):
    """
    Calls & booked rate by source_name within last `days`.
    Booked is inferred from tags (“ai generated scheduled” OR “appointment booked”).
    """
    today = _utc_today_date()
    start = today - timedelta(days=days)

    q = """
    WITH base AS (
      SELECT source_name, call_status, COALESCE(tags, '') AS tags
      FROM calls
      WHERE DATE(substr(started_at,1,10)) >= DATE(:start)
    ),
    filtered AS (
      SELECT *
      FROM base
      WHERE (:only_tags IS NULL OR instr(',' || lower(tags) || ',', ',' || lower(:only_tags) || ',') > 0)
    )
    SELECT
      COALESCE(source_name, 'Unknown') AS source,
      COUNT(*) AS calls,
      SUM(CASE WHEN call_status='answered' THEN 1 ELSE 0 END) AS answered,
      SUM(
        CASE
          WHEN lower(tags) LIKE '%ai generated scheduled%'
            OR lower(tags) LIKE '%appointment booked%'
          THEN 1 ELSE 0
        END
      ) AS booked
    FROM filtered
    GROUP BY source
    ORDER BY calls DESC
    """
    rows: List[Row] = db.execute(q, {"start": _date_str(start), "only_tags": only_tags}).fetchall()

    sources = []
    for r in rows:
        calls = int(r["calls"] or 0)
        answered = int(r["answered"] or 0)
        booked = int(r["booked"] or 0)
        booked_rate = (booked / answered) if answered > 0 else 0.0
        sources.append(
            {
                "source": r["source"],
                "calls": calls,
                "answered": answered,
                "booked": booked,
                "booked_rate": round(booked_rate, 4),
            }
        )

    return {"start": _date_str(start), "end": _date_str(today), "sources": sources}


# ------------------------------------------------------------
# 5) Hour × DOW Heatmap
# ------------------------------------------------------------
@router.get("/heatmap")
def heatmap(
    days: int = Query(30, ge=1, le=365),
    db=Depends(get_db),
):
    """
    Returns a 7x24 grid of call counts: dow (0=Sun..6=Sat) x hour (0..23)
    """
    today = _utc_today_date()
    start = today - timedelta(days=days)

    q = """
    SELECT
      CAST(strftime('%w', started_at) AS INT) AS dow,
      CAST(strftime('%H', started_at) AS INT) AS hour,
      COUNT(*) AS calls
    FROM calls
    WHERE DATE(substr(started_at,1,10)) >= DATE(:start)
    GROUP BY dow, hour
    ORDER BY dow, hour
    """
    rows: List[Row] = db.execute(q, {"start": _date_str(start)}).fetchall()

    grid = [[0 for _ in range(24)] for _ in range(7)]
    for r in rows:
        d = int(r["dow"] or 0)
        h = int(r["hour"] or 0)
        c = int(r["calls"] or 0)
        if 0 <= d <= 6 and 0 <= h <= 23:
            grid[d][h] = c

    return {"start": _date_str(start), "end": _date_str(today), "grid": grid}


# ------------------------------------------------------------
# 6) Missed Call Rate + Critical Misses
# ------------------------------------------------------------
@router.get("/missed")
def missed(
    days: int = Query(7, ge=1, le=365),
    critical_ring: int = Query(20, ge=0),
    db=Depends(get_db),
):
    """
    Overall missed rate and 'critical misses' (missed with ring >= critical_ring).
    """
    today = _utc_today_date()
    start = today - timedelta(days=days)

    q = """
    WITH w AS (
      SELECT call_status, COALESCE(ring_time_seconds,0) AS ring_s
      FROM calls
      WHERE DATE(substr(started_at,1,10)) >= DATE(:start)
    )
    SELECT
      COUNT(*) AS total,
      SUM(CASE WHEN call_status='missed' THEN 1 ELSE 0 END) AS missed,
      SUM(CASE WHEN call_status='missed' AND ring_s >= :critical THEN 1 ELSE 0 END) AS critical_missed
    FROM w
    """
    row: Row | None = db.execute(
        q, {"start": _date_str(start), "critical": critical_ring}
    ).fetchone()

    total = int(row["total"] or 0) if row else 0
    missed_n = int(row["missed"] or 0) if row else 0
    critical_n = int(row["critical_missed"] or 0) if row else 0
    missed_rate = (missed_n / total) if total else 0.0

    return {
        "start": _date_str(start),
        "end": _date_str(today),
        "total": total,
        "missed": missed_n,
        "missed_rate": round(missed_rate, 4),
        "critical_missed": critical_n,
        "critical_ring_seconds": critical_ring,
    }


# ------------------------------------------------------------
# 7) Data Quality Snapshot
# ------------------------------------------------------------
@router.get("/data-quality")
def data_quality(
    days: int = Query(30, ge=1, le=365),
    db=Depends(get_db),
):
    """
    Recording coverage and zero-duration answered calls.
    """
    today = _utc_today_date()
    start = today - timedelta(days=days)

    q = """
    SELECT
      COUNT(*) AS total,
      SUM(CASE WHEN call_status='answered' THEN 1 ELSE 0 END) AS answered,
      SUM(CASE WHEN call_status='answered'
                AND recording_url IS NOT NULL AND recording_url <> ''
          THEN 1 ELSE 0 END) AS answered_with_recording,
      SUM(CASE WHEN call_status='answered'
                AND (duration_seconds IS NULL OR duration_seconds <= 0)
          THEN 1 ELSE 0 END) AS answered_zero_duration
    FROM calls
    WHERE DATE(substr(started_at,1,10)) >= DATE(:start)
    """
    row: Row | None = db.execute(q, {"start": _date_str(start)}).fetchone()

    return {
        "start": _date_str(start),
        "end": _date_str(today),
        "total": int(row["total"] or 0) if row else 0,
        "answered": int(row["answered"] or 0) if row else 0,
        "answered_with_recording": int(row["answered_with_recording"] or 0) if row else 0,
        "answered_zero_duration": int(row["answered_zero_duration"] or 0) if row else 0,
    }


# ------------------------------------------------------------
# 8) Tag Summary (Python tally)
# ------------------------------------------------------------
@router.get("/tag-summary")
def tag_summary(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(25, ge=1, le=200),
    db=Depends(get_db),
):
    """
    Top tags within the window (case-insensitive).
    """
    today = _utc_today_date()
    start = today - timedelta(days=days)

    q = """
    SELECT COALESCE(tags,'') AS tags
    FROM calls
    WHERE DATE(substr(started_at,1,10)) >= DATE(:start)
    """
    rows: List[Row] = db.execute(q, {"start": _date_str(start)}).fetchall()

    counts: Dict[str, int] = {}
    for r in rows:
        raw = (r["tags"] or "").strip()
        if not raw:
            continue
        # split by comma, trim, lowercase
        for part in raw.split(","):
            tag = part.strip().lower()
            if not tag:
                continue
            counts[tag] = counts.get(tag, 0) + 1

    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return {
        "start": _date_str(start),
        "end": _date_str(today),
        "tags": [{"tag": k, "count": v} for k, v in top],
        "total_distinct": len(counts),
    }
