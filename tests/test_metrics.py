import urllib.parse
from fastapi.testclient import TestClient

from app.core.db import get_db  # <-- absolute import
from app.main import app        # <-- absolute import

def test_answer_rate_default_window(client, seed_calls):
    res = client.get("/metrics/answer-rate")
    assert res.status_code == 200
    data = res.json()
    assert data["answered"] == 3
    assert data["total"] == 4
    assert 0.74 < data["answer_rate"] < 0.76

def test_conversion_with_booking_tags(client, seed_calls):
    res = client.get("/metrics/conversion")
    assert res.status_code == 200
    data = res.json()
    # booked = 2 (AI Generated Scheduled on c1; Appointment Booked on c4), answered = 3
    assert data["answered"] == 3
    assert data["booked"] == 2
    assert 0.65 < data["booked_rate"] < 0.68  # 2/3 ≈ 0.666...

def test_conversion_only_tags_filter(client, seed_calls):
    # Restrict to only 'New Patient' calls — only c1 and c3; booked among these is c1 (answered)
    q = urllib.parse.urlencode({"only_tags": "New Patient"})
    res = client.get(f"/metrics/conversion?{q}")
    assert res.status_code == 200
    data = res.json()
    # among 'New Patient' rows: answered = 1 (c1), booked = 1 (AI tag)
    assert data["answered"] == 1
    assert data["booked"] == 1
    assert data["booked_rate"] == 1.0

def test_agent_scorecard(client, seed_calls):
    res = client.get("/metrics/agent-scorecard")
    assert res.status_code == 200
    agents = res.json()["agents"]
    names = [a["agent"] for a in agents]
    assert "Taylor" in names
    assert "Sam" in names
    taylor = next(a for a in agents if a["agent"] == "Taylor")
    assert taylor["calls"] == 1
    assert taylor["answered"] == 1
    assert taylor["booked"] == 1
    assert taylor["booked_rate"] == 1.0

def test_time_buckets(client, seed_calls):
    res = client.get("/metrics/time-buckets")
    assert res.status_code == 200
    data = res.json()
    assert "grid" in data
    assert isinstance(data["grid"], list)
    assert len(data["grid"]) == 24
    # Expect all 4 seeded rows fall in one bucket (0th hour by default fixtures)
    assert any(b.get("count", 0) == 4 for b in data["grid"])
