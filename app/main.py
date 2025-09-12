import asyncio
import datetime as dt
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings

# =========================
# Config via env vars
# =========================
class Settings(BaseSettings):
    CALLRAIL_API_KEY: str
    CALLRAIL_ACCOUNT_ID: str
    DB_PATH: str = "callrail_metrics.db"
    CORS_ORIGINS: str = "*"         # comma-separated list or "*" for all
    EXCLUDE_AGENTS: str = ""        # comma-separated names to exclude by default (e.g., "Taylor,John Doe")
    class Config:
        env_file = ".env"

settings = Settings()
EXCLUDE_AGENT_LIST = [a.strip() for a in settings.EXCLUDE_AGENTS.split(",") if a.strip()]

BASE_URL = "https://api.callrail.com/v3"
USER_AGENT = "CallRail-Metrics-App/1.0 (+fastapi)"
HEADERS = {
    "Authorization": f'Token token="{settings.CALLRAIL_API_KEY}"',
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}

# For reliable date filtering on RFC3339 strings with TZ: 'YYYY-MM-DDTHH:MM:SS-06:00'
DATE_COL = "substr(started_at,1,10)"  # -> 'YYYY-MM-DD'

# =========================
# DB Helpers
# =========================
def get_db():
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
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
        created_at TEXT
    );
    """)
    conn.commit()
    conn.close()

init_db()

# =========================
# Utilities
# =========================
def iso_date(d: dt.date) -> str:
    return d.strftime("%Y-%m-%d")

def clamp_date_range(start: dt.date, end: dt.date) -> Tuple[dt.date, dt.date]:
    if end < start:
        raise ValueError("end date must be >= start date")
    return start, end

def rows_to_list(rows) -> List[Dict[str, Any]]:
    return [dict(r) for r in rows]

def format_hms(seconds: Optional[float | int]) -> str:
    if seconds is None:
        return "00:00:00"
    s = int(round(float(seconds)))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

# Build SQL agent filter clause once per request
def _agent_filter_clause(only_agent: Optional[str]) -> Tuple[str, List[str]]:
    """
    - If only_agent is provided: include ONLY that agent.
    - Else: exclude global EXCLUDE_AGENT_LIST from env (if any).
    Returns (sql_snippet, params_list) that should be appended to WHERE.
    """
    if only_agent:
        return " AND agent_name = ?", [only_agent]
    if EXCLUDE_AGENT_LIST:
        placeholders = ",".join("?" for _ in EXCLUDE_AGENT_LIST)
        # Keep rows with NULL agent_name, exclude the listed ones
        return f" AND (agent_name IS NULL OR agent_name NOT IN ({placeholders}))", EXCLUDE_AGENT_LIST
    return "", []

# =========================
# CallRail Client
# =========================
async def fetch_calls(
    client: httpx.AsyncClient,
    start: str,
    end: str,
    per_page: int = 250,
    relative_pagination: bool = True
) -> List[Dict[str, Any]]:
    all_calls: List[Dict[str, Any]] = []
    params = {
        "start_date": start,
        "end_date": end,
        "per_page": per_page,
        "relative_pagination": "true" if relative_pagination else "false",
    }
    url = f"{BASE_URL}/a/{settings.CALLRAIL_ACCOUNT_ID}/calls.json"

    while True:
        r = await client.get(url, headers=HEADERS, params=params, timeout=60.0)
        if r.status_code == 429:
            await asyncio.sleep(2.0)
            continue
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)

        payload = r.json()
        items = payload.get("calls", payload.get("data", []))
        all_calls.extend(items)

        next_page = payload.get("next_page") or payload.get("links", {}).get("next")
        if not next_page:
            break
        if isinstance(next_page, str) and next_page.startswith("http"):
            url = next_page
            params = None
        else:
            url = f"{BASE_URL}/a/{settings.CALLRAIL_ACCOUNT_ID}/calls.json"
            params = {"cursor": next_page, "per_page": per_page}

    return all_calls

def upsert_calls(calls: List[Dict[str, Any]]):
    conn = get_db()
    cur = conn.cursor()
    for c in calls:
        call_id = str(c.get("id") or c.get("call_id") or "")
        if not call_id:
            continue

        company = c.get("company", {}) or {}
        company_id = company.get("id") or c.get("company_id")
        company_name = company.get("name") or c.get("company_name")

        started_at = c.get("start_time") or c.get("started_at") or c.get("created_at")
        duration_seconds = c.get("duration") or c.get("duration_in_seconds")

        source_name = c.get("source_name")
        if not source_name and isinstance(c.get("source"), dict):
            source_name = c["source"].get("name")

        tags = c.get("tags")
        if isinstance(tags, list):
            tags_str = ",".join([t.get("name") if isinstance(t, dict) else str(t) for t in tags])
        else:
            tags_str = tags or ""

        call_type = c.get("direction") or c.get("call_type")
        call_status = c.get("call_status") or ("answered" if c.get("answered") in (True, "true", 1, "1") else None)
        recording_url = c.get("recording") or c.get("recording_url")
        agent_name = c.get("agent_name") or (c.get("agent", {}).get("name") if isinstance(c.get("agent"), dict) else None)

        cur.execute("""
        INSERT INTO calls (id, company_id, company_name, started_at, duration_seconds,
                           source_name, tracking_number, customer_phone_number,
                           tags, call_type, call_status, recording_url, agent_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          company_id=excluded.company_id,
          company_name=excluded.company_name,
          started_at=excluded.started_at,
          duration_seconds=excluded.duration_seconds,
          source_name=excluded.source_name,
          tracking_number=excluded.tracking_number,
          customer_phone_number=excluded.customer_phone_number,
          tags=excluded.tags,
          call_type=excluded.call_type,
          call_status=excluded.call_status,
          recording_url=excluded.recording_url,
          agent_name=excluded.agent_name,
          created_at=excluded.created_at;
        """, (
            call_id,
            company_id,
            company_name,
            started_at,
            duration_seconds,
            source_name,
            c.get("tracking_number"),
            c.get("customer_phone_number") or c.get("customer_phone"),
            tags_str,
            call_type,
            call_status if isinstance(call_status, str) else ("answered" if call_status else None),
            recording_url,
            agent_name,
            dt.datetime.utcnow().isoformat()
        ))
    conn.commit()
    conn.close()

# =========================
# Aggregations (agent-aware)
# =========================
def summarize_totals(conn, start: Optional[str], end: Optional[str], only_agent: Optional[str] = None) -> Dict[str, Any]:
    q = f"""
    SELECT
      COUNT(*) AS calls,
      SUM(CASE WHEN call_status='answered' OR call_status='true' OR call_status='1' THEN 1 ELSE 0 END) AS answered,
      AVG(COALESCE(duration_seconds,0)) AS avg_duration
    FROM calls
    """
    params: List[Any] = []
    if start and end:
        q += f" WHERE {DATE_COL} BETWEEN ? AND ?"
        params = [start, end]
    else:
        q += " WHERE 1=1"
    clause, extra = _agent_filter_clause(only_agent)
    q += clause
    params.extend(extra)
    row = conn.execute(q, params).fetchone()
    return dict(row) if row else {"calls": 0, "answered": 0, "avg_duration": 0}

def group_by(conn, field: str, start: Optional[str], end: Optional[str], only_agent: Optional[str] = None) -> List[Dict[str, Any]]:
    q = f"""
    SELECT
      COALESCE({field}, 'Unknown') AS key,
      COUNT(*) AS calls,
      SUM(CASE WHEN call_status='answered' OR call_status='true' OR call_status='1' THEN 1 ELSE 0 END) AS answered,
      ROUND(AVG(COALESCE(duration_seconds,0)), 2) AS avg_duration
    FROM calls
    """
    params: List[Any] = []
    if start and end:
        q += f" WHERE {DATE_COL} BETWEEN ? AND ?"
        params = [start, end]
    else:
        q += " WHERE 1=1"
    clause, extra = _agent_filter_clause(only_agent)
    q += clause
    params.extend(extra)
    q += " GROUP BY key ORDER BY calls DESC"
    cur = conn.execute(q, params)
    return rows_to_list(cur.fetchall())

def duration_buckets(conn, start: Optional[str], end: Optional[str], only_agent: Optional[str] = None) -> List[Dict[str, Any]]:
    cases = """
    CASE
      WHEN COALESCE(duration_seconds,0) <= 30 THEN '0-30s'
      WHEN duration_seconds <= 60 THEN '31-60s'
      WHEN duration_seconds <= 120 THEN '61-120s'
      WHEN duration_seconds <= 300 THEN '121-300s'
      ELSE '>300s'
    END
    """
    q = f"SELECT {cases} AS bucket, COUNT(*) AS calls FROM calls"
    params: List[Any] = []
    if start and end:
        q += f" WHERE {DATE_COL} BETWEEN ? AND ?"
        params = [start, end]
    else:
        q += " WHERE 1=1"
    clause, extra = _agent_filter_clause(only_agent)
    q += clause
    params.extend(extra)
    q += " GROUP BY bucket ORDER BY calls DESC"
    cur = conn.execute(q, params)
    return rows_to_list(cur.fetchall())

def avg_duration_between(conn, start_iso: str, end_iso: str, only_agent: Optional[str] = None) -> Optional[float]:
    q = f"""
    SELECT AVG(duration_seconds) AS avg_secs
    FROM calls
    WHERE duration_seconds IS NOT NULL
      AND {DATE_COL} BETWEEN ? AND ?
    """
    params: List[Any] = [start_iso, end_iso]
    clause, extra = _agent_filter_clause(only_agent)
    q += clause
    params.extend(extra)
    row = conn.execute(q, params).fetchone()
    return row["avg_secs"] if row and row["avg_secs"] is not None else None

# =========================
# FastAPI App + CORS
# =========================
app = FastAPI(title="CallRail Metrics", version="1.2.0")

origins = (
    [o.strip() for o in settings.CORS_ORIGINS.split(",")]
    if settings.CORS_ORIGINS and settings.CORS_ORIGINS != "*"
    else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =========================
# Routes
# =========================
@app.get("/health")
def health():
    return {
        "ok": True,
        "account_id": settings.CALLRAIL_ACCOUNT_ID,
        "db_path": settings.DB_PATH,
        "exclude_agents": EXCLUDE_AGENT_LIST
    }

@app.post("/ingest")
async def ingest(
    start: dt.date = Query(..., description="Start date (YYYY-MM-DD)"),
    end: dt.date = Query(..., description="End date (YYYY-MM-DD)")
):
    start, end = clamp_date_range(start, end)
    async with httpx.AsyncClient() as client:
        calls = await fetch_calls(client=client, start=iso_date(start), end=iso_date(end))
    upsert_calls(calls)
    return {"ingested": len(calls), "start": iso_date(start), "end": iso_date(end)}

@app.post("/ingest/last-week")
async def ingest_last_week():
    """Convenience: ingest rolling last 7 days including today."""
    today = dt.date.today()
    start = today - dt.timedelta(days=6)
    async with httpx.AsyncClient() as client:
        calls = await fetch_calls(client=client, start=iso_date(start), end=iso_date(today))
    upsert_calls(calls)
    return {"ingested": len(calls), "start": iso_date(start), "end": iso_date(today)}

@app.get("/metrics/summary")
def metrics_summary(
    start: Optional[dt.date] = Query(None),
    end: Optional[dt.date] = Query(None),
    only_agent: Optional[str] = Query(None, description="If set, include only this agent (overrides global excludes)")
):
    s = iso_date(start) if start else None
    e = iso_date(end) if end else None
    conn = get_db()
    try:
        out = summarize_totals(conn, s, e, only_agent)
        out["avg_duration_hms"] = format_hms(out.get("avg_duration"))
        out["agent_filter"] = f"only {only_agent}" if only_agent else (f"excluding {EXCLUDE_AGENT_LIST}" if EXCLUDE_AGENT_LIST else "all agents")
        return out
    finally:
        conn.close()

@app.get("/metrics/by-company")
def metrics_by_company(
    start: Optional[dt.date] = Query(None),
    end: Optional[dt.date] = Query(None),
    only_agent: Optional[str] = Query(None)
):
    s = iso_date(start) if start else None
    e = iso_date(end) if end else None
    conn = get_db()
    try:
        return group_by(conn, "company_name", s, e, only_agent)
    finally:
        conn.close()

@app.get("/metrics/by-source")
def metrics_by_source(
    start: Optional[dt.date] = Query(None),
    end: Optional[dt.date] = Query(None),
    only_agent: Optional[str] = Query(None)
):
    s = iso_date(start) if start else None
    e = iso_date(end) if end else None
    conn = get_db()
    try:
        return group_by(conn, "source_name", s, e, only_agent)
    finally:
        conn.close()

@app.get("/metrics/by-tag")
def metrics_by_tag(
    start: Optional[dt.date] = Query(None),
    end: Optional[dt.date] = Query(None),
    only_agent: Optional[str] = Query(None)
):
    s = iso_date(start) if start else None
    e = iso_date(end) if end else None
    conn = get_db()
    try:
        params: List[Any] = []
        q = "SELECT tags FROM calls WHERE tags IS NOT NULL AND tags <> ''"
        if s and e:
            q += f" AND {DATE_COL} BETWEEN ? AND ?"
            params = [s, e]
        clause, extra = _agent_filter_clause(only_agent)
        q += clause
        params.extend(extra)
        rows = [r["tags"] for r in conn.execute(q, params).fetchall()]
        from collections import Counter
        c = Counter()
        for t in rows:
            for tag in [x.strip() for x in t.split(",") if x.strip()]:
                c[tag] += 1
        return [{"key": k, "calls": v} for k, v in c.most_common()]
    finally:
        conn.close()

@app.get("/metrics/duration-buckets")
def metrics_duration_buckets(
    start: Optional[dt.date] = Query(None),
    end: Optional[dt.date] = Query(None),
    only_agent: Optional[str] = Query(None)
):
    s = iso_date(start) if start else None
    e = iso_date(end) if end else None
    conn = get_db()
    try:
        return duration_buckets(conn, s, e, only_agent)
    finally:
        conn.close()

# =========================
# Reports
# =========================
@app.get("/reports/avg-call-time-last-week")
def report_avg_call_time_last_week(
    only_agent: Optional[str] = Query(None, description="If set, include only this agent (overrides global excludes)")
):
    today = dt.date.today()
    start = today - dt.timedelta(days=6)
    s_iso, e_iso = start.isoformat(), today.isoformat()

    conn = get_db()
    try:
        avg_secs = avg_duration_between(conn, s_iso, e_iso, only_agent)
    finally:
        conn.close()

    return {
        "start": s_iso,
        "end": e_iso,
        "average_seconds": round(avg_secs, 2) if avg_secs is not None else 0.0,
        "average_hms": format_hms(avg_secs),
        "note": "Rolling 7-day window including today.",
        "agent_filter": f"only {only_agent}" if only_agent else (f"excluding {EXCLUDE_AGENT_LIST}" if EXCLUDE_AGENT_LIST else "all agents")
    }

# =========================
# Debugging helpers (no agent filters here)
# =========================
@app.get("/debug/db-stats")
def debug_db_stats():
    conn = get_db()
    try:
        row = conn.execute("SELECT COUNT(*) AS n FROM calls").fetchone()
        minmax = conn.execute(
            f"SELECT MIN({DATE_COL}) AS min_date, MAX({DATE_COL}) AS max_date FROM calls"
        ).fetchone()
        return {"rows": row["n"], "min_date": minmax["min_date"], "max_date": minmax["max_date"]}
    finally:
        conn.close()

@app.get("/debug/dates")
def debug_dates(limit: int = 30):
    """Show counts per day to verify what’s in the DB."""
    conn = get_db()
    try:
        rows = conn.execute(
            f"""
            SELECT {DATE_COL} AS day, COUNT(*) AS calls,
                   ROUND(AVG(COALESCE(duration_seconds,0)), 2) AS avg_secs
            FROM calls
            GROUP BY day
            ORDER BY day DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return rows_to_list(rows)
    finally:
        conn.close()
