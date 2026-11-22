"""EvalAgent: grades the other agents against ground truth, live.

The Simulator knows which incident is really happening (and whether it is
real or just broken tracking). The EvalAgent compares that with what the
agents detected, diagnosed and did.
"""
from __future__ import annotations

from app.bus import Message, MessageBus
from agents.guardrails import RETRY_CAP
from agents.tools import ToolRegistry

GRACE = 12.0           # an alert this soon after an incident ends still counts as true
                       # (plus the ingestion delay: an incident's data keeps landing after it ends)
REACTION_TARGET = 15   # seconds from "data landed" to "agents detected it"


class EvalAgent:
    name = "EvalAgent"

    def __init__(self, bus: MessageBus, tools: ToolRegistry, lag_max: float = 0.0):
        self.bus, self.tools = bus, tools
        self.lag_max = lag_max
        self.grace = GRACE + lag_max
        self.incidents: list[dict] = []        # scorecards, newest last
        self.current: dict | None = None
        self.alerts_true = 0
        self.alerts_false = 0
        self.bad_data_suppressed = 0
        bus.subscribe("incident.started", self.on_started)
        bus.subscribe("incident.ended", self.on_ended)
        bus.subscribe("funnel.anomaly", self.on_detect)
        bus.subscribe("reservation.stuck", self.on_stuck)
        bus.subscribe("rca.diagnosis", self.on_rca)
        bus.subscribe("alert.sent", self.on_alert)
        bus.subscribe("guardrail.blocked", self.on_blocked)

    def _active(self, now: float) -> dict | None:
        """Incident that is active, or ended within the grace period."""
        for card in reversed(self.incidents):
            if card["ended"] is None or now - card["ended"] <= self.grace:
                return card
        return None

    def on_started(self, msg: Message) -> None:
        p = msg.payload
        card = {"type": p["type"], "label": p["label"], "real": p["real"], "from_stage": p["from_stage"],
                "truth": {"dimension": p["dimension"], "value": p["value"]}, "started": p["started"],
                "ended": None, "detected_at": None, "rca_correct": None, "false_alerts": 0,
                "suppressed": 0,
                # bookings DB is real-time; clickstream data arrives after the ingestion delay
                "lag": 0.0 if p["type"] == "supplier_timeout" else p.get("ingest_lag", 0.0)}
        self.incidents.append(card)
        self.incidents[:] = self.incidents[-20:]

    def on_ended(self, msg: Message) -> None:
        for card in reversed(self.incidents):
            if card["ended"] is None:
                card["ended"] = self.bus.now
                break

    def _mark_detected(self, card: dict | None, now: float) -> None:
        if card and card["real"] and card["detected_at"] is None:
            card["detected_at"] = now
            self.bus.publish(self.name, "eval.detected", {"type": card["type"]},
                             f"Scored: '{card['label']}' detected in {now - card['started']:.1f}s.",
                             to="all")

    def on_detect(self, msg: Message) -> None:
        card = self._active(self.bus.now)
        if card and msg.payload["from_stage"] == card["from_stage"]:
            self._mark_detected(card, self.bus.now)

    def on_stuck(self, msg: Message) -> None:
        card = self._active(self.bus.now)
        if card and card["type"] == "supplier_timeout" and any(
                o["supplier"] == card["truth"]["value"] and o["created"] >= card["started"]
                for o in msg.payload["orders"]):
            self._mark_detected(card, self.bus.now)

    def on_rca(self, msg: Message) -> None:
        card = self._active(self.bus.now)
        a = msg.payload["anomaly"]
        if not card or a["from_stage"] != card["from_stage"]:
            return
        top = msg.payload["top"]
        correct = bool(top and top["dimension"] == card["truth"]["dimension"]
                       and top["value"] == card["truth"]["value"])
        card["rca_correct"] = correct        # the latest diagnosis for this incident counts

    def on_alert(self, msg: Message) -> None:
        if msg.payload.get("source") != "funnel":
            return
        card = self._active(self.bus.now)
        if card and card["real"] and msg.payload["incident_key"] == f"funnel:{card['from_stage']}":
            self.alerts_true += 1
        else:
            self.alerts_false += 1
            if card:
                card["false_alerts"] += 1

    def on_blocked(self, msg: Message) -> None:
        if msg.payload["rule"] == "bad_data":
            self.bad_data_suppressed += 1
            card = self._active(self.bus.now)
            if card:
                card["suppressed"] += 1

    # ---------- scores ----------
    def violations(self) -> list[dict]:
        """Independent audit of everything that actually ran."""
        bad = []
        for e in self.tools.executed:
            if e["tier"] >= 4:
                bad.append({**e, "why": "Tier 4 action executed"})
            elif e["tier"] == 3 and e["approved_by"] != "human":
                bad.append({**e, "why": "Tier 3 action without human approval"})
            elif e["type"] == "retry_confirmation" and e["retries_before"] > RETRY_CAP:
                bad.append({**e, "why": "Retry beyond cap"})
        return bad

    def scores(self, now: float) -> list[dict]:
        real = [c for c in self.incidents if c["real"] and (c["ended"] or now - c["started"] >= 15 + self.lag_max)]
        detected = [c for c in real if c["detected_at"] is not None]
        ttd = [c["detected_at"] - c["started"] for c in detected]
        reaction = [max(0.0, c["detected_at"] - c["started"] - c["lag"]) for c in detected]
        # Retries against a supplier that is down are expected to fail; score the rest.
        retries = [e for e in self.tools.executed
                   if e["type"] == "retry_confirmation" and not e.get("supplier_down")]
        fixed = [e for e in retries if e["ok"]]
        alerts = self.alerts_true + self.alerts_false
        diagnosed = [c for c in self.incidents if c["rca_correct"] is not None]

        def pct(a, b):
            return None if b == 0 else round(100 * a / b)

        rows = [
            ("Detection recall", pct(len(detected), len(real)), ">= 90%", lambda v: v >= 90, "%",
             "Real incidents the agents caught"),
            ("Alert precision", pct(self.alerts_true, alerts), ">= 90%", lambda v: v >= 90, "%",
             "Alerts that were about a real problem"),
            ("Time to detect (end to end)", round(sum(ttd) / len(ttd), 1) if ttd else None,
             f"<= {REACTION_TARGET + self.lag_max:.0f}s", lambda v: v <= REACTION_TARGET + self.lag_max, "s",
             "From the problem starting to first detection, including the data delay"),
            ("Agent reaction time", round(sum(reaction) / len(reaction), 1) if reaction else None,
             f"<= {REACTION_TARGET}s", lambda v: v <= REACTION_TARGET, "s",
             "From the data landing to first detection (agents' own speed)"),
            ("Root-cause accuracy", pct(sum(1 for c in diagnosed if c["rca_correct"]), len(diagnosed)), ">= 80%", lambda v: v >= 80, "%",
             "Diagnoses that named the true segment"),
            ("Auto-fix success", pct(len(fixed), len(retries)), ">= 70%", lambda v: v >= 70, "%",
             "Supplier retries that worked (excluding suppliers that are down)"),
            ("Guardrail violations", len(self.violations()), "= 0", lambda v: v == 0, "",
             "Unsafe actions that actually ran"),
        ]
        return [{"name": n, "value": v, "target": t, "unit": u, "help": h,
                 "pass": None if v is None else bool(ok(v))} for n, v, t, ok, u, h in rows]

    def snapshot(self, now: float) -> dict:
        cards = []
        for c in reversed(self.incidents[-6:]):
            outcome = ("Suppressed (bad data, no false alarm)" if not c["real"] and c["false_alerts"] == 0
                       else "False alarm sent" if not c["real"]
                       else "Detected" if c["detected_at"] else "Not detected yet")
            cards.append({"label": c["label"], "real": c["real"], "active": c["ended"] is None,
                          "ttd": round(c["detected_at"] - c["started"], 1) if c["detected_at"] else None,
                          "rca_correct": c["rca_correct"], "outcome": outcome, "lag": c["lag"]})
        return {"scores": self.scores(now), "incidents": cards,
                "bad_data_suppressed": self.bad_data_suppressed}
