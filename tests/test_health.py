def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "account_id" in data
    assert "db_path" in data
    assert "booking_tags" in data
