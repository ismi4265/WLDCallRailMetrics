# at top of main.py
from dotenv import load_dotenv; load_dotenv()

import os
import asyncio
import datetime as dt
from typing import Dict, Any, List, Optional, Tuple


import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic_settings import BaseSettings
import sqlite3

# =========================
# Config via env vars
# =========================
class Settings(BaseSettings):
    CALLRAIL_API_KEY: str
    CALLRAIL_ACCOUNT_ID: str
    DB_PATH: str = "callrail_metrics.db"

    class Config:
        env_file = ".env"  # loads .env automatically if python-dotenv is installed

settings = Settings()

BASE_URL = "https://api.callrail.com/v3"
USER_AGENT = "CallRail-Metrics-App/1.0 (+fastapi)"

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
# CallRail Client
# =========================
HEADERS = {
    "Authorization": f'Token token="{settings.CALLRAIL_API_KEY}"',
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}

async def fetch_calls(client: httpx.AsyncClient, start: str, end: str) -> List[Dict[str, Any]]:
    all_calls = []
    params = {
        "start_date": start,
        "end_date": end,
        "per_page": 250,
        "relative_pagination": "true",
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
        if next_page.startswith("http"):
            url = next_page
            params = None
        else:
            url = f"{BASE_URL}/a/{settings.CALLRAIL_ACCOUNT_ID}/calls.json"
            params = {"cursor": next_page, "per_page": 250}

    return all_calls

def upsert_calls(calls: List[Dict[str, Any]]):
    conn = get_db()
    cur = conn.cursor()
    for c in calls:
        call_id = str(c.get("id") or c.get("call_id"))
        company = c.get("company", {}) or {}
        company_id = company.get("id") or c.get("company_id")
        company_name = company.get("name") or c.get("company_name")
        started_at = c.get("start_time") or c.get("started_at")
        duration_seconds = c.get("duration") or c.get("duration_in_seconds")
        source_name = c.get("source_name")
        tags = c.get("tags")
        tags_str = ",".join([t.get("name") if isinstance(t, dict) else str(t) for t in tags]) if isinstance(tags, list) else (tags or "")
        call_type = c.get("direction")
        call_status = c.get("call_status")
        recording_url = c.get("recording") or c.get("recording_url")
        agent_name = c.get("agent_name")

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
            call_id, company_id, company_name, started_at, duration_seconds,
            source_name, c.get("tracking_number"), c.get("customer_phone_number"),
            tags_str, call_type, call_status, recording_url, agent_name,
            dt.datetime.utcnow().isoformat()
        ))
    conn.commit()
    conn.close()

# =========================
# Metrics Helpers
# =========================
def summarize_totals(conn, start: Optional[str], end: Optional[str]) -> Dict[str, Any]:
    q = "SELECT COUNT(*) AS calls, SUM(CASE WHEN call_status='answered' THEN 1 ELSE 0 END) AS answered, AVG(COALESCE(duration_seconds,0)) AS avg_duration FROM calls"
    params = []
    if start and end:
        q += " WHERE date(started_at) BETWEEN ? AND ?"
        params = [start, end]
    row = conn.execute(q, params).fetchone()
    return dict(row) if row else {"calls": 0, "answered": 0, "avg_duration": 0}

# =========================
# FastAPI App
# =========================
app = FastAPI(title="CallRail Metrics", version="1.0.0")

@app.get("/health")
def health():
    return {
        "ok": True,
        "account_id": settings.CALLRAIL_ACCOUNT_ID,
        "db_path": settings.DB_PATH
    }

@app.post("/ingest")
async def ingest(start: dt.date, end: dt.date):
    async with httpx.AsyncClient() as client:
        calls = await fetch_calls(client, start.isoformat(), end.isoformat())
    upsert_calls(calls)
    return {"ingested": len(calls), "range": f"{start} to {end}"}

@app.get("/metrics/summary")
def metrics_summary(start: Optional[dt.date] = None, end: Optional[dt.date] = None):
    conn = get_db()
    try:
        s = start.isoformat() if start else None
        e = end.isoformat() if end else None
        return summarize_totals(conn, s, e)
    finally:
        conn.close()
