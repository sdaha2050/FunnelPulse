"""Smoke test for the HTTP API the UI uses."""
from fastapi.testclient import TestClient

from app.main import app, engine


def test_api_end_to_end():
    with TestClient(app) as client:
        assert client.get("/api/health").json()["ok"]
        for _ in range(30):
            engine.tick()
        assert client.post("/api/incidents/supplier_timeout").status_code == 200
        assert client.post("/api/incidents/not_a_thing").status_code == 404
        for _ in range(60):
            engine.tick()
        s = client.get("/api/state").json()
        assert s["incident"] and s["funnel"] and s["messages"]
        ap = client.get("/api/approvals").json()
        assert ap, "expected a rebook approval"
        r = client.post(f"/api/approvals/{ap[0]['id']}/approve", json={"note": "test"})
        assert r.json()["status"] == "approved"
        assert client.post(f"/api/approvals/{ap[0]['id']}/approve").status_code == 404
        ks = client.post("/api/killswitch", json={"global_on": True}).json()
        assert ks["global"] is True
        client.post("/api/incidents/clear")
