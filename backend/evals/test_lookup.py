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


# ---------- event playground ----------
import pytest

from app import trace


@pytest.mark.parametrize("sample,expect", [
    ("amex_declines", "Amex"), ("ios_checkout", "iOS app"), ("california", "CA")])
def test_sent_events_are_traced_to_the_right_root_cause(sample, expect):
    e = Engine(seed=7, auto_incidents=False, ingest_delay=(10, 20))
    for _ in range(60):
        e.tick()
    events, errors = trace.validate(trace.SAMPLE_BY_ID[sample]["events"])
    assert not errors
    t = e.send_events(sample, events)
    for _ in range(100):
        e.tick()
    steps = {s["key"]: s for s in trace.trace_view(e, t["id"])["steps"]}
    assert steps["pipeline"]["status"] == "done" and steps["detect"]["status"] == "warn"
    assert f"= {expect}" in steps["rca"]["text"] and "✓" in steps["rca"]["text"]


def test_one_event_raises_no_alert_and_broken_events_are_ignored():
    e = Engine(seed=7, auto_incidents=False, ingest_delay=(10, 20))
    for _ in range(60):
        e.tick()
    for sample in ("one_drop", "broken_tracking"):
        t = e.send_events(sample, trace.validate(trace.SAMPLE_BY_ID[sample]["events"])[0])
        for _ in range(100):
            e.tick()
        steps = {s["key"]: s for s in trace.trace_view(e, t["id"])["steps"]}
        assert steps["act"]["status"] == "skipped"
    assert e.evals.alerts_false == 0


def test_api_rejects_bad_shapes():
    _, errors = trace.validate([{"type": "nope", "count": 999}])
    assert len(errors) >= 2
