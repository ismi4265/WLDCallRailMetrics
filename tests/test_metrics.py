from fastapi import APIRouter, Query
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from ..core.db import get_db
from ..core.config import BOOKING_TAGS

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _hms(seconds: Optional[float]) -> Optional[str]:
    if seconds is None:
        return None
    s = int(round(seconds))
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


@router.get("/answer-rate")
def answer_rate(
    start: Optional[str] = None,
    end: Optional[str] = None,
    only_company: Optional[str] = Query(default=None),
    only_tags: Optional[str] = Query(default=None),
):
    today = datetime.utcnow().date()
    start_date = datetime.fromisoformat(start).date() if start else (today - timedelta(days=6))
    end_date = datetime.fromisoformat(end).date() if end else today

    where = ["created_at BETWEEN ? AND ?"]
    params: List[Any] = [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]

    if only_company:
        where.append("company_id = ?")
        params.append(only_company)

    tags_filter: List[str] = []
    if only_tags:
        tags_filter = [t.strip() for t in only_tags.split(",") if t.strip()]

    with get_db() as conn:
        cur = conn.cursor()

        tag_exists_where = ""
        params_with_tags = params
        if tags_filter:
            placeholders = ",".join("?" * len(tags_filter))
            tag_exists_where = f"""
              AND EXISTS (
                SELECT 1 FROM call_tags ct
                WHERE ct.call_id = c.id AND ct.tag IN ({placeholders})
              )
            """
            params_with_tags = params + tags_filter

        base_where = " AND ".join(where)

        cur.execute(f"""
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN call_status='answered' THEN 1 ELSE 0 END) AS answered
            FROM calls c
            WHERE {base_where} {tag_exists_where}
        """, params_with_tags)
        total, answered = cur.fetchone() or (0, 0)
        total = total or 0
        answered = answered or 0

    rate = (answered / total) if total else 0.0
    return {
        "start": str(start_date),
        "end": str(end_date),
        "total": total,
        "answered": answered,
        "answer_rate": round(rate, 4),
    }


@router.get("/conversion")
def conversion(
    start: Optional[str] = None,
    end: Optional[str] = None,
    only_company: Optional[str] = Query(default=None),
    only_tags: Optional[str] = Query(default=None),
):
    today = datetime.utcnow().date()
    start_date = datetime.fromisoformat(start).date() if start else (today - timedelta(days=6))
    end_date = datetime.fromisoformat(end).date() if end else today

    where = ["created_at BETWEEN ? AND ?"]
    params: List[Any] = [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]
    if only_company:
        where.append("company_id = ?")
        params.append(only_company)

    tags_filter: List[str] = []
    if only_tags:
        tags_filter = [t.strip() for t in only_tags.split(",") if t.strip()]

    with get_db() as conn:
        cur = conn.cursor()

        tag_exists_where = ""
        params_with_tags = params
        if tags_filter:
            placeholders = ",".join("?" * len(tags_filter))
            tag_exists_where = f"""
              AND EXISTS (
                SELECT 1 FROM call_tags ct
                WHERE ct.call_id = c.id AND ct.tag IN ({placeholders})
              )
            """
            params_with_tags = params + tags_filter

        base_where = " AND ".join(where)

        # answered in window (optionally tag-filtered)
        cur.execute(f"""
            SELECT SUM(CASE WHEN call_status='answered' THEN 1 ELSE 0 END) AS answered
            FROM calls c
            WHERE {base_where} {tag_exists_where}
        """, params_with_tags)
        answered = cur.fetchone()[0] or 0

        # booked in window (answered + BOOKING_TAGS)
        placeholders = ",".join("?" * len(BOOKING_TAGS)) if BOOKING_TAGS else "''"
        book_params = params + (BOOKING_TAGS or [])
        cur.execute(f"""
            SELECT SUM(
              CASE WHEN c.call_status='answered'
                AND EXISTS (
                  SELECT 1 FROM call_tags ct
                  WHERE ct.call_id = c.id AND ct.tag IN ({placeholders})
                )
              THEN 1 ELSE 0 END
            ) AS booked
            FROM calls c
            WHERE {base_where}
        """, book_params)
        booked = cur.fetchone()[0] or 0

    booked_rate = (booked / answered) if answered else 0.0
    return {
        "start": str(start_date),
        "end": str(end_date),
        "answered": answered,
        "booked": booked,
        "booked_rate": round(booked_rate, 4),
    }


@router.get("/agent-scorecard")
def agent_scorecard(
    start: Optional[str] = None,
    end: Optional[str] = None,
    only_agent: Optional[str] = Query(default=None),
    only_company: Optional[str] = Query(default=None),
    only_tags: Optional[str] = Query(default=None),
):
    """
    Per-agent:
      - calls (total)
      - answered
      - booked (answered + booking tag)
      - booked_rate
      - avg_duration_seconds / avg_duration_hms (answered + duration_seconds > 0)
    """
    today = datetime.utcnow().date()
    start_date = datetime.fromisoformat(start).date() if start else (today - timedelta(days=6))
    end_date = datetime.fromisoformat(end).date() if end else today

    tags_filter: List[str] = []
    if only_tags:
        tags_filter = [t.strip() for t in only_tags.split(",") if t.strip()]

    params: List[Any] = [f"{start_date} 00:00:00", f"{end_date} 23:59:59"]
    where = ["created_at BETWEEN ? AND ?"]

    if only_agent:
        where.append("agent_name = ?")
        params.append(only_agent)

    if only_company:
        where.append("company_id = ?")
        params.append(only_company)

    base_where = " AND ".join(where)

    with get_db() as conn:
        cur = conn.cursor()

        tag_exists_where = ""
        params_with_tags = params
        if tags_filter:
            placeholders = ",".join("?" * len(tags_filter))
            tag_exists_where = f"""
              AND EXISTS (
                SELECT 1 FROM call_tags ct
                WHERE ct.call_id = c.id AND ct.tag IN ({placeholders})
              )
            """
            params_with_tags = params + tags_filter

        # calls / answered
        cur.execute(f"""
            SELECT
                c.agent_name AS agent,
                COUNT(*) AS calls,
                SUM(CASE WHEN c.call_status='answered' THEN 1 ELSE 0 END) AS answered
            FROM calls c
            WHERE {base_where} {tag_exists_where}
            GROUP BY c.agent_name
        """, params_with_tags)
        rows = cur.fetchall()

        # booked
        placeholders = ",".join("?" * len(BOOKING_TAGS)) if BOOKING_TAGS else "''"
        book_params = params + (BOOKING_TAGS or [])
        cur.execute(f"""
            SELECT
                c.agent_name AS agent,
                SUM(
                  CASE WHEN c.call_status='answered'
                    AND EXISTS (
                      SELECT 1 FROM call_tags ct
                      WHERE ct.call_id = c.id AND ct.tag IN ({placeholders})
                    )
                  THEN 1 ELSE 0 END
                ) AS booked
            FROM calls c
            WHERE {base_where}
            GROUP BY c.agent_name
        """, book_params)
        booked_map = {r[0]: (r[1] or 0) for r in cur.fetchall()}

        # average duration: answered + duration_seconds > 0
        cur.execute(f"""
            SELECT
                c.agent_name AS agent,
                AVG(CASE WHEN c.call_status='answered' AND c.duration_seconds > 0
                         THEN CAST(c.duration_seconds AS REAL) END) AS avg_sec
            FROM calls c
            WHERE {base_where}
            GROUP BY c.agent_name
        """, params)
        avg_map = {r[0]: r[1] for r in cur.fetchall()}

    agents: List[Dict[str, Any]] = []
    for agent, calls, answered in rows:
        booked = booked_map.get(agent, 0)
        calls = calls or 0
        answered = answered or 0
        booked_rate = (booked / answered) if answered else 0.0
        avg_sec = avg_map.get(agent)
        agents.append({
            "agent": agent,
            "calls": calls,
            "answered": answered,
            "booked": booked,
            "booked_rate": round(booked_rate, 4),
            "avg_duration_seconds": float(avg_sec) if avg_sec is not None else None,
            "avg_duration_hms": _hms(avg_sec),
        })

    # If the user filtered to a specific agent and none found, return a friendly message
    if only_agent and not agents:
        return {
            "start": str(start_date),
            "end": str(end_date),
            "agents": [],
            "message": f"No calls for agent {only_agent} in the selected window.",
        }

    return {
        "start": str(start_date),
        "end": str(end_date),
        "agents": agents,
    }


@router.get("/time-buckets")
def time_buckets(
    start: Optional[str] = None,
    end: Optional[str] = None,
    by: str = Query(default="hour", pattern="^(hour|weekday)$"),
):
    """
    Buckets call counts by hour-of-day (0-23) or weekday (0-6).
    """
    today = datetime.utcnow().date()
    start_date = datetime.fromisoformat(start).date() if start else (today - timedelta(days=6))
    end_date = datetime.fromisoformat(end).date() if end else today

    with get_db() as conn:
        cur = conn.cursor()
        if by == "hour":
            # SQLite: strftime('%H', ...) -> '00'..'23'
            cur.execute("""
                SELECT CAST(strftime('%H', created_at) AS INTEGER) AS bucket, COUNT(*)
                FROM calls
                WHERE created_at BETWEEN ? AND ?
                GROUP BY bucket
            """, (f"{start_date} 00:00:00", f"{end_date} 23:59:59"))
            raw = dict(cur.fetchall())
            grid = [int(raw.get(h, 0)) for h in range(24)]
        else:
            # weekday 0=Sunday .. 6=Saturday in SQLite: %w
            cur.execute("""
                SELECT CAST(strftime('%w', created_at) AS INTEGER) AS bucket, COUNT(*)
                FROM calls
                WHERE created_at BETWEEN ? AND ?
                GROUP BY bucket
            """, (f"{start_date} 00:00:00", f"{end_date} 23:59:59"))
            raw = dict(cur.fetchall())
            grid = [int(raw.get(d, 0)) for d in range(7)]

    return {
        "start": str(start_date),
        "end": str(end_date),
        "by": by,
        "grid": grid,
        "buckets": [{"bucket": i, "count": c} for i, c in enumerate(grid)],
    }
