"""Event playground: sample events a person can send, and a step-by-step trace
of what every agent did with them, with the reasoning behind each step.
"""
from __future__ import annotations

import itertools
from collections import OrderedDict

from app.bus import Message, MessageBus
from app.lookup import order_view
from agents.funnel_monitor import MIN_REL_DROP, MIN_SAMPLE, MIN_Z
from agents.reservation_integrity import STUCK_AFTER
from agents.root_cause import CONFIDENCE_THRESHOLD
from agents.simulator import STAGE_LABELS, STAGES

_ids = itertools.count(1)
STAGE_INDEX = {"search": 0, "detail": 1, "checkout": 2, "payment": 3, "booked": 4}

# ---------- sample events shown in the UI ----------
SAMPLES = [
    {"id": "one_booking", "name": "One traveler books a hotel",
     "story": "A normal booking: search, property page, checkout, pay with Visa, supplier confirms.",
     "expect": "Lands after the delay, passes data checks, counts as a booking, supplier confirms. No action needed.",
     "events": [{"type": "traveler_session", "user_id": "U20001", "brand": "Expedia", "market": "US", "state": "WA",
                 "device": "Web", "supplier": "Harbor Inns", "payment_method": "Visa",
                 "furthest_stage": "booked", "supplier_confirms": True, "count": 1}]},
    {"id": "one_drop", "name": "One traveler leaves at payment",
     "story": "A single traveler reaches the payment page and gives up.",
     "expect": "No alert. One traveler leaving is normal; the funnel monitor needs a big, statistically clear drop.",
     "events": [{"type": "traveler_session", "user_id": "U20002", "brand": "Hotels.com", "market": "US", "state": "NY",
                 "device": "iOS app", "payment_method": "Mastercard", "furthest_stage": "payment", "count": 1}]},
    {"id": "amex_declines", "name": "50 Amex payments fail",
     "story": "50 travelers reach payment with an Amex card and none of them can pay.",
     "expect": "Drop at Payment, root cause = Amex, alert to Payments on-call (automatic), "
               "email to affected travelers waits for a human.",
     "events": [
         {"type": "traveler_session", "brand": "Expedia", "market": "US", "state": "TX", "device": "Web", "payment_method": "Amex", "furthest_stage": "payment", "count": 15},
         {"type": "traveler_session", "brand": "Hotels.com", "market": "US", "state": "NY", "device": "iOS app", "payment_method": "Amex", "furthest_stage": "payment", "count": 12},
         {"type": "traveler_session", "brand": "Vrbo", "market": "GB", "device": "Android app", "payment_method": "Amex", "furthest_stage": "payment", "count": 12},
         {"type": "traveler_session", "brand": "Expedia", "market": "DE", "device": "Web", "payment_method": "Amex", "furthest_stage": "payment", "count": 11}]},
    {"id": "ios_checkout", "name": "60 iOS travelers abandon checkout",
     "story": "The iOS app shows a higher price at checkout than in search, so 60 travelers leave at checkout.",
     "expect": "Drop at Checkout, root cause = iOS app, alert to app team, the 'lower the price' shortcut is "
               "BLOCKED by guardrails, price-match credit waits for a human.",
     "events": [
         {"type": "traveler_session", "brand": "Vrbo", "market": "US", "state": "FL", "device": "iOS app", "payment_method": "Visa", "furthest_stage": "checkout", "count": 20},
         {"type": "traveler_session", "brand": "Expedia", "market": "US", "state": "CA", "device": "iOS app", "payment_method": "Mastercard", "furthest_stage": "checkout", "count": 20},
         {"type": "traveler_session", "brand": "Hotels.com", "market": "GB", "device": "iOS app", "payment_method": "Amex", "furthest_stage": "checkout", "count": 20}]},
    {"id": "california", "name": "45 California travelers can't pay",
     "story": "A regional payment gateway fails: travelers in California can't complete payment.",
     "expect": "Drop at Payment, root cause = US state CA. Watch the US by state tab: California turns red.",
     "events": [
         {"type": "traveler_session", "brand": "Expedia", "market": "US", "state": "CA", "device": "Web", "payment_method": "Mastercard", "furthest_stage": "payment", "count": 15},
         {"type": "traveler_session", "brand": "Hotels.com", "market": "US", "state": "CA", "device": "iOS app", "payment_method": "Visa", "furthest_stage": "payment", "count": 15},
         {"type": "traveler_session", "brand": "Vrbo", "market": "US", "state": "CA", "device": "Android app", "payment_method": "Amex", "furthest_stage": "payment", "count": 15}]},
    {"id": "supplier_silent", "name": "8 bookings the hotel never confirms",
     "story": "8 travelers book and pay at Alpine Lodges, but the hotel's system never confirms.",
     "expect": "Bookings DB is real-time: flagged as stuck after 10s, the agent retries 3 times, then asks a "
               "human to approve rebooking each traveler.",
     "events": [{"type": "traveler_session", "brand": "Hotels.com", "market": "US", "state": "CO", "device": "Web",
                 "supplier": "Alpine Lodges", "payment_method": "Visa", "furthest_stage": "booked",
                 "supplier_confirms": False, "count": 8}]},
    {"id": "broken_tracking", "name": "60 events with missing session ID",
     "story": "An app release breaks tracking: events arrive without a session ID.",
     "expect": "Data quality marks the data UNRELIABLE and the guardrails hold back alerts, so bad data "
               "never looks like a real drop.",
     "events": [{"type": "traveler_session", "brand": "Expedia", "market": "US", "state": "IL",
                 "device": "Android app", "session_id": None, "furthest_stage": "search", "count": 60}]},
]
SAMPLE_BY_ID = {s["id"]: s for s in SAMPLES}

ALLOWED_TYPES = {"traveler_session"}
MAX_EVENTS = 300


def validate(events) -> tuple[list[dict], list[str]]:
    """The API checks only the SHAPE of events. Data quality is judged later by the agents."""
    errors = []
    if not isinstance(events, list) or not events:
        return [], ["'events' must be a non-empty list"]
    clean, total = [], 0
    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            errors.append(f"event {i + 1}: must be an object")
            continue
        if ev.get("type") not in ALLOWED_TYPES:
            errors.append(f"event {i + 1}: type must be 'traveler_session'")
        if ev.get("furthest_stage", "search") not in STAGE_INDEX:
            errors.append(f"event {i + 1}: furthest_stage must be one of {', '.join(STAGE_INDEX)}")
        try:
            count = int(ev.get("count", 1))
        except (TypeError, ValueError):
            count = 0
        if not 1 <= count <= 200:
            errors.append(f"event {i + 1}: count must be 1-200")
        total += max(count, 0)
        clean.append({**ev, "count": count})
    if total > MAX_EVENTS:
        errors.append(f"too many events ({total}); send at most {MAX_EVENTS} at once")
    return clean, errors


def _common(events: list[dict], key: str):
    vals = {ev.get(key) for ev in events}
    return vals.pop() if len(vals) == 1 else None


class Tracer:
    """Listens on the bus and remembers what happened to each batch of sent events."""

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.traces: OrderedDict[str, dict] = OrderedDict()
        self.last_diag: dict[str, dict] = {}
        bus.subscribe("events.batch", self.on_landed)
        bus.subscribe("funnel.anomaly", self.on_anomaly)
        bus.subscribe("rca.diagnosis", self.on_diagnosis)
        bus.subscribe("reservation.stuck", self.on_stuck)

    @staticmethod
    def new_id() -> str:
        return f"T{next(_ids)}"

    def start(self, tid: str, name: str, events: list[dict], ingest: dict, skip_delay: bool, now: float) -> dict:
        reached = {STAGE_INDEX.get(ev.get("furthest_stage", "search"), 0) for ev in events}
        t = {"id": tid, "name": name or "Custom events", "sent_at": now, "skip_delay": skip_delay,
             "events": events, "count": sum(ev["count"] for ev in events),
             "reached": max(reached) if len(reached) == 1 else None,
             "attrs": {k: _common(events, k) for k in ("payment_method", "device", "state", "market", "supplier", "brand")},
             "journeys": set(ingest["journeys"]), "orders": ingest["orders"], "land_at": ingest["land_at"],
             "landed_at": None, "lag": None, "dq": None, "anomaly": None, "diagnosis": None, "stuck": []}
        self.traces[tid] = t
        while len(self.traces) > 30:
            self.traces.popitem(last=False)
        return t

    def _open(self, now: float, window: float = 25.0):
        return [t for t in self.traces.values() if t["landed_at"] is not None and now - t["landed_at"] <= window]

    def on_landed(self, msg: Message) -> None:
        mine = [j for j in msg.payload["batch"] if j.get("trace_id")]
        if not mine:
            return
        t = self.traces.get(mine[0]["trace_id"])
        if not t:
            return
        broken = [j for j in mine if not j["schema_ok"]]
        t["landed_at"], t["lag"] = self.bus.now, msg.payload.get("lag", 0.0)
        t["dq"] = {"broken": len(broken), "total": len(mine)}

    def on_anomaly(self, msg: Message) -> None:
        a = {k: v for k, v in msg.payload.items() if k != "sample"}
        for t in self._open(self.bus.now):
            if t["anomaly"] is None and t["reached"] is not None and t["reached"] < 4 \
                    and a["from_stage"] == STAGES[t["reached"]]:
                t["anomaly"] = a
                d = self.last_diag.get(a["key"])
                if d and d["ts"] >= a["detected_at"]:
                    t["diagnosis"] = {"top": d["top"], "hypotheses": d["hypotheses"], "summary": d["summary"]}

    def on_diagnosis(self, msg: Message) -> None:
        d = msg.payload
        self.last_diag[d["anomaly"]["key"]] = d
        for t in self.traces.values():
            if t["anomaly"] and d["anomaly"]["key"] == t["anomaly"]["key"] and d["ts"] >= t["anomaly"]["detected_at"]:
                if t["diagnosis"] is None or (d["top"] and not t["diagnosis"]["top"]):
                    t["diagnosis"] = {"top": d["top"], "hypotheses": d["hypotheses"], "summary": d["summary"]}

    def on_stuck(self, msg: Message) -> None:
        ids = {o["id"] for o in msg.payload["orders"]}
        for t in self.traces.values():
            hit = ids & set(t["orders"])
            if hit:
                t["stuck"] = sorted(set(t["stuck"]) | hit)


# ---------- the trace view: steps + reasoning ----------
def trace_view(engine, tid: str) -> dict | None:
    t = engine.tracer.traces.get(tid)
    if not t:
        return None
    now = engine.now
    steps = []
    n = t["count"]
    booked = t["reached"] == 4
    a, d = t["anomaly"], t["diagnosis"]
    since_land = None if t["landed_at"] is None else now - t["landed_at"]

    def step(key, title, status, text, why):
        steps.append({"key": key, "title": title, "status": status, "text": text, "why": why})

    # 1. API
    step("received", "1. Received by the API", "done",
         f"Accepted {n} traveler session event(s). Each got a journey ID and a trace ID ({t['id']}).",
         "The API only checks the shape of each event (type, stage, count). Whether the data is "
         "trustworthy is decided later by the Data quality agent, exactly like a real pipeline.")

    # 2. pipeline
    if t["landed_at"] is None:
        left = max(0, round(t["land_at"] - now))
        step("pipeline", "2. Travelling through the event stream (Kafka)", "active",
             f"In the queue with ~{engine.sim.pipeline_snapshot(now)['in_flight_events']:,} other events. "
             f"The agents will see these events in about {left}s.",
             "Clickstream events (searches, checkouts, payments) reach the agents 10-20 seconds after they "
             "happen, like consumer lag in a real Kafka pipeline. Until then, no agent can react.")
    else:
        extra = f" Their {len(t['orders'])} booking(s) were written to the bookings database instantly." if t["orders"] else ""
        step("pipeline", "2. Travelled through the event stream (Kafka)", "done",
             f"Landed {t['lag']:.0f}s after being sent.{extra}",
             "Bookings come straight from the bookings database (no delay), which is why stuck bookings "
             "can be caught faster than funnel drops.")

    # 3. data quality
    if t["dq"] is None:
        step("dq", "3. Data quality check", "pending", "Waiting for the events to land.",
             "Checks freshness, volume and required fields (brand, market, device, session ID).")
    elif t["dq"]["broken"]:
        step("dq", "3. Data quality check", "warn",
             f"{t['dq']['broken']} of {t['dq']['total']} events are missing required fields. The agent marked the "
             f"data UNRELIABLE (now: {'unreliable' if not engine.dq.reliable else 'reliable again'}).",
             "If more than 2% of recent events are broken, the numbers can't be trusted. The guardrails then "
             "hold back alerts for that segment, so broken tracking never looks like travelers leaving.")
    else:
        step("dq", "3. Data quality check", "done", f"All {t['dq']['total']} events have the required fields.",
             "Brand, market, device and session ID are present, so these events count in the funnel.")

    # 4. detection
    if booked:
        if t["landed_at"] is None and not t["stuck"]:
            step("detect", "4. Reservation check", "pending", "Watching the bookings for supplier confirmation.",
                 f"A booking with no supplier confirmation after {STUCK_AFTER:.0f}s counts as stuck.")
        elif t["stuck"]:
            step("detect", "4. Reservation check", "warn",
                 f"{len(t['stuck'])} booking(s) not confirmed by the supplier after {STUCK_AFTER:.0f}s: flagged as stuck.",
                 "A paid booking the hotel never confirms means the traveler may arrive and find no room. "
                 "This is caught from the bookings database, without waiting for the event stream.")
        else:
            step("detect", "4. Reservation check", "done",
                 f"Counted as {n} booking(s). The supplier confirmed, so nothing is stuck.",
                 f"Only bookings without confirmation after {STUCK_AFTER:.0f}s are flagged.")
    elif t["dq"] and t["dq"]["broken"]:
        step("detect", "4. Funnel monitor", "skipped",
             "Not judged: the data for this segment is unreliable.",
             "Agents don't diagnose broken data. Fix the tracking first.")
    elif a:
        step("detect", "4. Funnel monitor", "warn",
             f"Drop detected at {a['label'].replace('->', '→')}: {a['rate']:.0%} continued vs {a['baseline']:.0%} "
             f"normal (−{a['drop_pct']}%, {a['n']} travelers, z = {a['z']}).",
             f"Rule: alert only when a stage falls at least {MIN_REL_DROP:.0%} below normal, with at least "
             f"{MIN_SAMPLE} travelers, and the drop is too big to be chance (z ≥ {MIN_Z:.0f}). Your {n} events "
             f"mixed with background traffic in the last 10 seconds and pushed the rate past all three.")
    elif t["landed_at"] is None or since_land < 12:
        step("detect", "4. Funnel monitor", "active" if t["landed_at"] else "pending",
             "Comparing the last 10 seconds of each stage with its normal rate…",
             f"Needs a drop of at least {MIN_REL_DROP:.0%}, at least {MIN_SAMPLE} travelers, and z ≥ {MIN_Z:.0f}.")
    else:
        stage = STAGES[t["reached"]] if t["reached"] is not None else None
        row = next((f for f in engine.funnel.snapshot()["funnel"] if f["stage"] == stage), None)
        rate = f" ({STAGE_LABELS[stage]} → next stage is {row['next_rate']:.0%} right now)" if row and row.get("next_rate") else ""
        step("detect", "4. Funnel monitor", "done",
             f"No alert. {n} traveler(s) leaving was not enough to move the conversion rate{rate}.",
             "That's the right call: a few travelers leaving is normal browsing. Alerting on it would flood "
             "teams with false alarms.")

    # 5. root cause
    if booked:
        step("rca", "5. Root cause", "skipped" if not t["stuck"] else "done",
             f"Not needed: the stuck orders name the supplier directly ({t['attrs'].get('supplier') or 'see orders'})."
             if t["stuck"] else "Not needed: nothing went wrong.",
             "Root-cause analysis is for funnel drops, where the cause has to be found among many groups.")
    elif not a and (t["landed_at"] is None or since_land < 12) and not (t["dq"] and t["dq"]["broken"]):
        step("rca", "5. Root cause", "pending", "Runs only if the funnel monitor finds a drop.",
             "The root-cause agent only runs when the funnel monitor reports a drop.")
    elif not a:
        step("rca", "5. Root cause", "skipped", "Not needed: no drop to explain.",
             "The root-cause agent only runs when the funnel monitor reports a drop.")
    elif not d:
        step("rca", "5. Root cause", "active", "Splitting the affected travelers by card, device, supplier, country, state and brand…", "")
    elif d["top"]:
        top = d["top"]
        sent = t["attrs"].get(top["dimension"] if top["dimension"] != "market" else "market")
        match = (f" ✓ This matches what you sent ({top['dimension'].replace('_', ' ')} = {sent})."
                 if sent == top["value"] else "")
        others = "; ".join(f"{h['value']} {round(h['confidence'] * 100)}%" for h in d["hypotheses"][1:3])
        step("rca", "5. Root cause", "done",
             f"Most likely cause: {top['dimension'].replace('_', ' ')} = {top['value']} "
             f"(confidence {round(top['confidence'] * 100)}%).{match}",
             f"It compared every group with everyone else and picked the one that is much worse AND explains most "
             f"of the lost travelers. Evidence: {top['evidence']}." + (f" Runners-up: {others}." if others else ""))
    else:
        step("rca", "5. Root cause", "warn", "Cause unknown: no single group explains the drop.",
             f"Below {CONFIDENCE_THRESHOLD:.0%} confidence the agent says 'unknown' and asks a human, instead of guessing.")

    # 6 + 7. actions and guardrails
    key = a["key"] if a else None
    since = (a["detected_at"] - 1) if a else t["sent_at"]
    acts = [x for x in engine.router.history
            if x.get("ts", 0) >= since and ((key and x["incident_key"] == key) or x.get("order_id") in t["orders"])]
    retries = [x for x in acts if x["type"] == "retry_confirmation" and x.get("decision", {}).get("decision") == "allow"]
    main = [x for x in acts if x["type"] != "retry_confirmation"]
    # actions the router could not send to a human yet (queue full)
    queued = len([o for o in t["orders"] if o in engine.sim.orders and engine.sim.orders[o]["status"] == "pending"
                  and engine.sim.orders[o]["retries"] >= 3])
    lines = [f"Tier {x['tier']} · {x['title']}" for x in main[:6]]
    if retries:
        lines.insert(0, f"Tier 2 · Retried supplier confirmation {len(retries)} time(s) across {len({r['order_id'] for r in retries})} booking(s)")
    if acts:
        step("act", "6. Action router", "done", " | ".join(lines),
             "Each problem gets a plan. Tier 1 (alerts) and Tier 2 (safe, repeatable fixes like a retry) run "
             "automatically. Tier 3 (moves money, changes a trip, or contacts travelers) needs a human. Tier 4 "
             "(prices, inventory, fraud rules) is never allowed for agents.")
        verdicts = []
        for x in acts:
            dec = x.get("decision", {})
            verdicts.append((dec.get("decision"), dec.get("rule"), dec.get("reason", "")))
        allow = sum(1 for v in verdicts if v[0] == "allow")
        human = sum(1 for v in verdicts if v[0] == "needs_human")
        blocked = [v for v in verdicts if v[0] == "block"]
        reasons = sorted({v[2] for v in blocked if v[2]})[:3]
        step("guard", "7. Guardrails", "warn" if blocked else "done",
             f"{allow} allowed automatically · {human} sent to a human · {len(blocked)} blocked"
             + (f" ({'; '.join(reasons)})" if reasons else ""),
             "Every proposed action is checked against policy before it runs: tier rules, retry cap (3), alert rate "
             "limits, duplicate alerts, bad-data suppression and the kill switch. Everything is written to the audit log.")
    else:
        waiting = t["landed_at"] is None or (since_land is not None and since_land < 12) or (booked and not t["orders"])
        step("act", "6. Action router", "pending" if waiting else "skipped",
             "Waiting for a finding." if waiting else "No action: nothing needs fixing.",
             "Actions are only proposed for real findings.")
        step("guard", "7. Guardrails", "pending" if waiting else "skipped",
             "Nothing to check yet." if waiting else "Nothing to check.", "")

    # 8. outcome
    orders = [order_view(engine, o) for o in t["orders"][:8]]
    orders = [o for o in orders if o]
    pending = {x["id"]: x for x in main if x.get("status") == "pending"}
    pending.update({x["id"]: x for x in engine.router.approvals.values()
                    if x.get("order_id") in t["orders"] and x["status"] == "pending"})
    if pending or queued:
        text = (f"{len(pending)} action(s) are waiting for you under Live agents → Needs a human"
                + (f", and {queued} more are queued behind them (the human queue shows 6 at a time)." if queued else "."))
        status = "warn"
    elif t["dq"] and t["dq"]["broken"]:
        text, status = ("Correctly ignored: the data was broken, so no false alarm was raised. "
                        "The fix belongs to the team that owns tracking, not to the agents."), "done"
    elif acts:
        expired = [x for x in main if x.get("status") == "expired"]
        decided = [x for x in main if x.get("status") in ("approved", "rejected")]
        text = "Handled. The automatic actions ran"
        if decided:
            text += f"; a human {decided[0]['status']} the sensitive action."
        elif expired:
            text += ("; the request to a human expired because the problem cleared before anyone decided "
                     "(open requests close automatically when the funnel recovers).")
        else:
            text += "."
        status = "done"
    elif t["landed_at"] is None or (since_land is not None and since_land < 12):
        text, status = "Still in progress.", "pending"
    else:
        text, status = "Nothing needed doing. The platform correctly treated this as normal traffic.", "done"
    step("outcome", "8. Outcome", status, text,
         "The Eval agent scores every step against the truth (was it detected, was the root cause right, did any "
         "unsafe action run), so the agents' quality is measured, not assumed.")

    return {"id": t["id"], "name": t["name"], "sent_ago": round(now - t["sent_at"]), "count": n,
            "events": t["events"], "steps": steps,
            "orders": [{"id": o["id"], "label": o["label"], "tone": o["tone"], "user_id": o["user_id"]} for o in orders],
            "done": status in ("done", "warn") and steps[-1]["status"] != "pending"}


def traces_list(engine) -> list[dict]:
    return [{"id": t["id"], "name": t["name"], "count": t["count"], "sent_ago": round(engine.now - t["sent_at"])}
            for t in reversed(engine.tracer.traces.values())]
