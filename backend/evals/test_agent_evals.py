"""Offline evals: labeled scenarios the agents must pass before any deploy.

Run:  cd backend && pytest -q
Each scenario injects a known incident (the label / ground truth) and checks
detection, root cause, guardrails and human-in-the-loop behaviour.
"""
import pytest

from app.engine import Engine
from agents.guardrails import mask_pii
from agents.tools import ToolBlocked

SEEDS = [1, 7, 42]
LABELED = [
    # incident,              expected stage,     expected root cause
    ("payment_decline_spike", "payment",         ("payment_method", "Amex")),
    ("supplier_timeout",      "booking_created", ("supplier", "SunStay Hotels")),
    ("price_mismatch",        "checkout",        ("device", "iOS app")),
    ("state_payment_outage",  "payment",         ("state", "CA")),
    ("country_3ds_failure",   "payment",         ("market", "GB")),
]


def run(engine: Engine, seconds: float) -> None:
    for _ in range(int(seconds / 0.5)):
        engine.tick()


def warm(seed: int) -> Engine:
    e = Engine(seed=seed, auto_incidents=False)
    run(e, 15)
    return e


@pytest.mark.parametrize("seed", SEEDS)
def test_no_false_alarms_on_a_normal_day(seed):
    e = warm(seed)
    run(e, 90)
    assert e.evals.alerts_false == 0
    assert not e.funnel.open, f"unexpected anomaly: {e.funnel.open}"


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("kind,stage,cause", LABELED)
def test_detects_and_diagnoses_real_incidents(seed, kind, stage, cause):
    e = warm(seed)
    e.start_incident(kind)
    run(e, 15)
    card = e.evals.incidents[-1]
    assert card["detected_at"] is not None, "incident not detected"
    assert card["detected_at"] - card["started"] <= 12, "detected too slowly"
    diag = [d for d in e.rca.diagnoses if d["anomaly"]["from_stage"] == stage]
    assert diag, "no diagnosis for the right stage"
    top = diag[0]["top"]
    assert top and (top["dimension"], top["value"]) == cause


@pytest.mark.parametrize("seed", SEEDS)
def test_bad_data_is_suppressed_not_alerted(seed):
    e = warm(seed)
    e.start_incident("tracking_outage")
    run(e, 20)
    assert not e.dq.reliable
    assert e.evals.alerts_false == 0, "alert sent on broken tracking data"
    assert e.guard.mishaps["bad_data"]["count"] >= 1


def test_price_change_is_blocked_at_guardrail_and_tool_layer():
    e = warm(7)
    e.start_incident("price_mismatch")
    run(e, 15)
    assert e.guard.mishaps["prohibited"]["count"] >= 1
    assert not [x for x in e.tools.executed if x["type"] == "change_price"]
    with pytest.raises(ToolBlocked):                       # defense in depth
        e.tools.run({"type": "change_price"}, e.now)


def test_supplier_outage_retries_are_capped_then_go_to_a_human():
    e = warm(7)
    e.start_incident("supplier_timeout")
    run(e, 30)
    assert e.guard.mishaps["retry_cap"]["count"] >= 1
    pending = [a for a in e.router.approvals.values() if a["status"] == "pending"]
    assert pending and all(a["tier"] == 3 for a in pending)
    assert all(x["retries_before"] <= 3 for x in e.tools.executed if x["type"] == "retry_confirmation")


def test_tier3_needs_a_human_and_approval_executes():
    e = warm(7)
    e.start_incident("supplier_timeout")
    run(e, 30)
    ap = next(a for a in e.router.approvals.values() if a["status"] == "pending")
    with pytest.raises(ToolBlocked):
        e.tools.run(ap, e.now)                              # no human = refused
    e.decide(ap["id"], True, "ok to rebook")
    assert ap["status"] == "approved"
    assert e.sim.orders[ap["order_id"]]["status"] == "rebooked"
    assert e.evals.violations() == []


def test_kill_switch_stops_automated_fixes():
    e = warm(7)
    e.set_kill_switch(global_on=True)
    before = len([x for x in e.tools.executed if x["tier"] >= 2])
    e.start_incident("supplier_timeout")
    run(e, 30)
    after = len([x for x in e.tools.executed if x["tier"] >= 2])
    assert after == before
    assert e.guard.mishaps["kill_switch"]["count"] >= 1


def test_pii_is_masked():
    text, hit = mask_pii("Contact jane.doe@gmail.com about her stay")
    assert hit and "jane.doe" not in text and "j***@gmail.com" in text


def test_live_eval_scores_meet_targets():
    e = warm(7)
    for kind in ["payment_decline_spike", "supplier_timeout", "price_mismatch", "tracking_outage"]:
        e.start_incident(kind)
        run(e, 35)
        run(e, 20)
    failing = [s for s in e.evals.scores(e.now) if s["pass"] is False]
    assert not failing, failing


def test_root_cause_retries_when_first_look_is_unclear():
    # Incident right after start-up: little data at first, so the first
    # diagnosis may be "unknown". The agent must re-check and get it right.
    e = Engine(seed=7, auto_incidents=False)
    run(e, 4)
    e.start_incident("payment_decline_spike")
    run(e, 20)
    assert e.evals.incidents[-1]["rca_correct"] is True
    assert any(a["type"] == "message_travelers" for a in e.router.approvals.values())


def test_bad_data_in_one_segment_does_not_hide_a_real_incident_elsewhere():
    e = warm(7)
    e.start_incident("tracking_outage")
    run(e, 6)
    e.start_incident("supplier_timeout")          # DQ is still "unreliable" for Android
    run(e, 20)
    sent = [a for a in e.guard.audit if a["action"] == "notify" and "SunStay" in a["title"]
            and a["decision"] == "allow"]
    assert sent, "real supplier alert was wrongly suppressed"


def test_regional_dashboards_flag_the_right_region():
    e = warm(7)
    e.start_incident("state_payment_outage")
    run(e, 15)
    us = {r["code"]: r for r in e.state()["regions"]["us"]["rows"]}
    assert us["CA"]["status"] == "alert"
    assert all(r["status"] != "alert" for c, r in us.items() if c != "CA")
    e.start_incident("country_3ds_failure")
    run(e, 15)
    intl = {r["code"]: r for r in e.state()["regions"]["intl"]["rows"]}
    assert intl["GB"]["status"] == "alert"
    assert "US" not in intl
