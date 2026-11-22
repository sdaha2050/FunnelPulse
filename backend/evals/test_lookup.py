"""Search by order ID and traveler journey view."""
from app import lookup
from app.engine import Engine


def _engine_with_stuck_orders():
    e = Engine(seed=7, auto_incidents=False, ingest_delay=(10, 20))
    for _ in range(60):
        e.tick()
    e.start_incident("supplier_timeout")
    for _ in range(80):
        e.tick()
    return e


def test_order_lookup_shows_status_and_history():
    e = _engine_with_stuck_orders()
    oid = lookup.samples(e)["orders"][0]
    v = lookup.order_view(e, oid.lower())                  # case-insensitive
    assert v and v["id"] == oid
    assert v["timeline"][0]["who"] == "Traveler"
    assert [t["ts"] for t in v["timeline"]] == sorted(t["ts"] for t in v["timeline"])
    assert "@example.com" in v["email"] and "***" in v["email"]   # PII stays masked
    assert lookup.order_view(e, "ORD-000000") is None


def test_user_journey_covers_search_to_booked():
    e = _engine_with_stuck_orders()
    uid = lookup.samples(e)["users"][0]
    v = lookup.user_view(e, uid)
    assert v and v["total"] >= 1
    s = v["sessions"][-1]
    assert [st["name"] for st in s["steps"]][:5] == ["Search", "Property page", "Checkout", "Payment", "Booked"]
    assert s["steps"][0]["state"] == "done"
    assert lookup.user_view(e, "U99999") is None


def test_user_sessions_still_in_pipeline_are_shown():
    e = _engine_with_stuck_orders()
    flying = e.sim.in_flight[-1]["batch"][0]["user_id"]
    v = lookup.user_view(e, flying)
    assert any(x["in_pipeline"] and x["lands_in"] >= 0 for x in v["sessions"])
