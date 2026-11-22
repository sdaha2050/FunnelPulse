"""Traveler assistant: understands sample messages, acts within guardrails, humans approve money."""
import pytest

from app.concierge import SAMPLES, detect
from app.engine import Engine

EXPECTED = {
    "Find me a pet-friendly hotel in Paris under $250": "search_hotel",
    "Can I check in early on Dec 12? My flight lands at noon": "early_checkin",
    "Can you upgrade me to a suite for free?": "upgrade_free",
    "The AC in my room isn't working and it's really hot": "room_issue",
    "I was charged twice for the minibar": "billing",
    "Honestly it was disappointing: dirty room and rude front desk. 2 stars": "feedback",
}


@pytest.mark.parametrize("msg,intent", EXPECTED.items())
def test_intents(msg, intent):
    phase = next(p for p, ms in SAMPLES.items() if msg in ms)
    assert detect(msg, phase)[0] == intent


def _engine():
    e = Engine(seed=7, auto_incidents=False)
    for _ in range(10):
        e.tick()
    return e


def test_money_needs_a_human_and_free_upgrade_is_blocked():
    e = _engine()
    c = e.assistant.new("during")
    acts = e.assistant.handle(c, "I was charged twice for the minibar")[-1]["brain"]["actions"]
    assert acts[0]["tier"] == 3 and acts[0]["decision"] == "needs_human"
    acts = e.assistant.handle(c, "Can you upgrade me to a suite for free?")[-1]["brain"]["actions"]
    assert acts[0]["decision"] == "block"
    assert e.evals.violations() == []


def test_booking_needs_explicit_yes_then_runs():
    e = _engine()
    c = e.assistant.new("pre")
    e.assistant.handle(c, "Find me a hotel in Rome")
    r = e.assistant.handle(c, "Book option 1")
    assert r[-1]["brain"]["actions"] == [] and "Shall I book" in r[-1]["text"]
    r = e.assistant.handle(c, "Yes, book it")
    assert r[-1]["brain"]["actions"][0]["type"] == "create_booking"
    assert r[-1]["brain"]["actions"][0]["decision"] == "allow"


def test_human_decision_is_reported_back_in_the_chat():
    e = _engine()
    c = e.assistant.new("post")
    e.assistant.handle(c, "I paid for breakfast but the restaurant was closed. Can I get a refund?")
    ap = next(a for a in e.router.approvals.values() if a.get("conv_id") == c["id"])
    e.decide(ap["id"], False, "outside policy")
    assert "couldn't approve" in c["messages"][-1]["text"]
