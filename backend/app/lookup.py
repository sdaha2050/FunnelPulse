"""Order and traveler lookups for the UI (search by order ID, traveler journey view).

Everything is rebuilt from what the agents already keep: the order record, the
tool runs and approvals that mention it, and the traveler's recent sessions.
"""
from __future__ import annotations

from agents.reservation_integrity import STUCK_AFTER
from agents.simulator import STAGES

STAGE_NAMES = ["Search", "Property page", "Checkout", "Payment", "Booked", "Supplier confirmed",
               "Itinerary delivered"]

DROP_REASON = {
    0: "Left after searching (still comparing)",
    1: "Looked at a property, didn't start checkout",
    2: "Started checkout, didn't pay",
    3: "Payment failed or was abandoned",
}

STATUS_TEXT = {
    "pending": "Waiting for the supplier to confirm",
    "confirmed": "Confirmed by the supplier",
    "needs_human": "Waiting for a human to approve a rebooking",
    "rebooked": "Rebooked at a comparable property (human approved)",
    "refunded": "Refunded (human approved)",
    "escalated": "Escalated to the service team (human rejected the rebooking)",
}

TOOL_TEXT = {
    "retry_confirmation": "Agent retried the supplier confirmation",
    "rebook_traveler": "Traveler rebooked",
    "refund": "Refund issued",
}


def order_view(engine, order_id: str) -> dict | None:
    sim, now = engine.sim, engine.now
    oid = order_id.strip().upper()
    o = sim.orders.get(oid) or sim.order_archive.get(oid)
    if not o:
        return None
    status = o["status"]
    stuck = status == "pending" and now - o["created"] > STUCK_AFTER
    label = "Stuck: supplier is not confirming" if stuck else STATUS_TEXT.get(status, status)
    tone = ("ok" if status in ("confirmed", "rebooked", "refunded")
            else "bad" if stuck or status in ("needs_human", "escalated") else "wait")

    timeline = [{"ts": o["created"], "text": f"Booked and paid (${o['value_usd']}, {o['payment_method']})",
                 "who": "Traveler"}]
    for e in engine.tools.executed:
        if e.get("order_id") == oid and e["type"] in TOOL_TEXT:
            timeline.append({"ts": e["ts"], "who": "Human agent" if e["approved_by"] == "human" else "ActionRouterAgent",
                             "text": f"{TOOL_TEXT[e['type']]}: {e['detail'].lower()}"})
    approvals = [a for a in engine.router.approvals.values() if a.get("order_id") == oid]
    for a in approvals:
        timeline.append({"ts": a["ts"], "who": "ActionRouterAgent",
                         "text": f"Sent to a human for approval: {a['title'].split(' - ')[0]}"})
        if a.get("decided_at") is not None:
            timeline.append({"ts": a["decided_at"], "who": "Human agent",
                             "text": f"Human {a['status']} the request" + (f" ({a['note']})" if a.get("note") else "")})
    if o.get("confirmed_at"):
        timeline.append({"ts": o["confirmed_at"], "who": "Supplier", "text": f"{o['supplier']} confirmed the booking"})
    if stuck or o["retries"]:
        first_fix = min([t["ts"] for t in timeline[1:]] or [o["created"] + STUCK_AFTER])
        timeline.append({"ts": min(o["created"] + STUCK_AFTER, first_fix - 0.01), "who": "ReservationIntegrityAgent",
                         "text": f"Flagged as stuck: no confirmation after {STUCK_AFTER:.0f}s"})
    timeline.sort(key=lambda t: t["ts"])
    for t in timeline:
        t["ago"] = round(now - t["ts"])
    pending = next((a for a in approvals if a["status"] == "pending"), None)
    return {
        "id": oid, "status": status, "label": label, "tone": tone,
        "user_id": o.get("user_id"), "supplier": o["supplier"], "brand": o["brand"],
        "market": o["market"], "state": o.get("state"), "device": o["device"],
        "payment_method": o["payment_method"], "value_usd": o["value_usd"],
        "checkin_hours": o["checkin_hours"], "retries": o["retries"],
        "traveler": o["traveler"], "email": o["email"],      # already hashed / masked
        "age_seconds": round(now - o["created"]),
        "pending_approval_id": pending["id"] if pending else None,
        "timeline": timeline,
        "confirmed_ago": round(now - o["confirmed_at"]) if o.get("confirmed_at") else None,
    }


def _session_view(engine, j: dict, in_pipeline: bool = False, lands_in: float | None = None) -> dict:
    now = engine.now
    event_ts = j.get("event_ts", j["ts"])
    reached = j["reached"]
    start = event_ts - j["stage_secs"][-1]
    order = order_view(engine, j["order_id"]) if j.get("order_id") else None
    steps = []
    for i, name in enumerate(STAGE_NAMES):
        if i <= reached:
            state, when = "done", start + j["stage_secs"][i]
        elif i == reached + 1 and reached < 4:
            state, when = "dropped", None
        else:
            state, when = "not_reached", None
        if i >= 5 and reached >= 4 and order:      # after booking: follow the order
            ok = order["status"] in ("confirmed", "rebooked")
            if ok:
                state = "done"
            elif i == 5:
                state = "dropped" if order["tone"] == "bad" else "waiting"
            else:
                state = "not_reached"            # no itinerary until the supplier confirms
            when = (now - order["confirmed_ago"]) if ok and order["confirmed_ago"] is not None else None
        steps.append({"name": name, "state": state, "ago": None if when is None else round(now - when)})
    if not j["schema_ok"]:
        outcome, why = "Tracking data missing", "Events for this session arrived without required fields; the agents ignored it."
    elif reached >= 4:
        outcome = "Booked"
        why = order["label"] if order else "Booked"
    else:
        outcome = f"Left at {STAGE_NAMES[reached]}"
        why = DROP_REASON[reached]
    return {
        "session_id": j["session_id"], "outcome": outcome, "why": why, "issue": j.get("issue"),
        "brand": j["brand"], "market": j["market"], "state": j.get("state"), "device": j["device"],
        "supplier": j["supplier"], "payment_method": j["payment_method"],
        "started_ago": round(now - start), "steps": steps, "order_id": j.get("order_id"),
        "in_pipeline": in_pipeline, "lands_in": None if lands_in is None else round(lands_in),
        "lag": j.get("lag"),
    }


def user_view(engine, user_id: str) -> dict | None:
    sim = engine.sim
    uid = user_id.strip().upper()
    landed = list(sim.user_index.get(uid, []))
    flying = [(j, b["land_at"]) for b in sim.in_flight for j in b["batch"] if j["user_id"] == uid]
    if not landed and not flying:
        return None
    sessions = [_session_view(engine, j, True, land_at - engine.now) for j, land_at in flying][::-1]
    sessions += [_session_view(engine, j) for j in landed][::-1]
    booked = sum(1 for x in sessions if x["outcome"] == "Booked")
    return {"user_id": uid, "sessions": sessions, "booked": booked, "total": len(sessions)}


def samples(engine) -> dict:
    sim = engine.sim
    recent = list(sim.journeys)[-600:][::-1]
    booked = [j["user_id"] for j in recent if j["reached"] >= 4][:3]
    dropped = [j["user_id"] for j in recent if j["reached"] == 3][:2]
    orders = [a["order_id"] for a in engine.router.approvals.values() if a.get("order_id") and a["status"] == "pending"][:2]
    orders += [o["id"] for o in engine.integrity.stuck_orders(sim.orders, engine.now)][:2]
    orders += [o["id"] for o in list(sim.orders.values())[::-1] if o["status"] == "confirmed"][:2]
    return {"users": list(dict.fromkeys(booked + dropped)), "orders": list(dict.fromkeys(orders))}
