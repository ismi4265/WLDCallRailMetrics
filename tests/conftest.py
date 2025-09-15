# tests/conftest.py
import os
import tempfile
import shutil
import sqlite3
import datetime as dt
import pytest
from fastapi.testclient import TestClient

@pytest.fixture(scope="session")
def temp_env():
    tmp_dir = tempfile.mkdtemp(prefix="wld_cr_tests_")
    db_path = os.path.join(tmp_dir, "test.db")

    # Set env BEFORE importing the app
    os.environ["DB_PATH"] = db_path
    os.environ["CALLRAIL_API_KEY"] = "dummy"
    os.environ["CALLRAIL_ACCOUNT_ID"] = "acct_dummy"
    os.environ["EXCLUDE_AGENTS"] = ""
    os.environ["DEFAULT_ONLY_TAGS"] = ""

    yield {"db_path": db_path, "tmp_dir": tmp_dir}
    shutil.rmtree(tmp_dir, ignore_errors=True)

@pytest.fixture(scope="session")
def app_instance(temp_env):
    # Import after env is set so the app boots with our temp DB
    from app.main import app
    return app

@pytest.fixture(scope="session")
def client(app_instance):
    return TestClient(app_instance)

@pytest.fixture
def db_conn(temp_env):
    conn = sqlite3.connect(temp_env["db_path"])
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()

@pytest.fixture
def clear_db(db_conn):
    db_conn.execute("DELETE FROM calls")
    db_conn.commit()
    yield
    db_conn.execute("DELETE FROM calls")
    db_conn.commit()

def _iso(d: dt.date) -> str:
    return d.strftime("%Y-%m-%d")

@pytest.fixture
def seed_calls(db_conn, clear_db):
    today = dt.date.today()
    rows = [
        {
            "id": "c1",
            "company_id": "co1",
            "company_name": "Clinic A",
            "started_at": f"{_iso(today)}T10:00:00-06:00",
            "duration_seconds": 180,
            "source_name": "Google Ads",
            "tracking_number": "111-111",
            "customer_phone_number": "555-0001",
            "tags": "New Patient,AI Generated Scheduled",
            "call_type": "inbound",
            "call_status": "answered",
            "recording_url": None,
            "agent_name": "Taylor",
            "created_at": dt.datetime.utcnow().isoformat(),
        },
        {
            "id": "c2",
            "company_id": "co1",
            "company_name": "Clinic A",
            "started_at": f"{_iso(today - dt.timedelta(days=1))}T11:00:00-06:00",
            "duration_seconds": 90,
            "source_name": "Direct",
            "tracking_number": "111-111",
            "customer_phone_number": "555-0002",
            "tags": "Existing Patient",
            "call_type": "inbound",
            "call_status": "answered",
            "recording_url": None,
            "agent_name": "Sam",
            "created_at": dt.datetime.utcnow().isoformat(),
        },
        {
            "id": "c3",
            "company_id": "co2",
            "company_name": "Clinic B",
            "started_at": f"{_iso(today - dt.timedelta(days=2))}T09:30:00-06:00",
            "duration_seconds": 0,
            "source_name": "Facebook",
            "tracking_number": "222-222",
            "customer_phone_number": "555-0003",
            "tags": "New Patient",
            "call_type": "inbound",
            "call_status": "missed",
            "recording_url": None,
            "agent_name": None,
            "created_at": dt.datetime.utcnow().isoformat(),
        },
        {
            "id": "c4",
            "company_id": "co2",
            "company_name": "Clinic B",
            "started_at": f"{_iso(today - dt.timedelta(days=6))}T13:00:00-06:00",
            "duration_seconds": 240,
            "source_name": "Google Ads",
            "tracking_number": "333-333",
            "customer_phone_number": "555-0004",
            "tags": "Existing Patient,Appointment Booked",
            "call_type": "inbound",
            "call_status": "answered",
            "recording_url": None,
            "agent_name": "Sam",
            "created_at": dt.datetime.utcnow().isoformat(),
        },
    ]
    # Ensure table exists (app initializes on import)
    for r in rows:
        db_conn.execute("""
        INSERT OR REPLACE INTO calls
            (id, company_id, company_name, started_at, duration_seconds, source_name,
             tracking_number, customer_phone_number, tags, call_type, call_status,
             recording_url, agent_name, created_at)
        VALUES (:id,:company_id,:company_name,:started_at,:duration_seconds,:source_name,
                :tracking_number,:customer_phone_number,:tags,:call_type,:call_status,
                :recording_url,:agent_name,:created_at)
        """, r)
    db_conn.commit()
    return rows
