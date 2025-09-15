import urllib.parse

def test_avg_call_time_last_week(client, seed_calls):
    res = client.get("/reports/avg-call-time-last-week")
    assert res.status_code == 200
    data = res.json()
    # avg over answered rows within last 7 days (c1, c2, c4 are within the 7-day window)
    # durations: c1=180, c2=90, c4=240 -> avg = 510/3 = 170 sec
    assert round(data["average_seconds"], 2) == 170.0
    assert data["average_hms"] == "00:02:50"

def test_avg_call_time_last_week_only_agent_taylor(client, seed_calls):
    q = urllib.parse.urlencode({"only_agent": "Taylor"})
    res = client.get(f"/reports/avg-call-time-last-week?{q}")
    assert res.status_code == 200
    data = res.json()
    # Taylor has one answered call: 180s
    assert round(data["average_seconds"], 2) == 180.0
    assert data["average_hms"] == "00:03:00"
