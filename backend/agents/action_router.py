"""ActionRouterAgent: decides what to do, how risky it is, and who owns it.

Tiers:  1 notify  |  2 safe auto-fix  |  3 human must approve  |  4 never.
Every proposal goes through the Guardrails first; only then does it run
(Tier 1-2), wait in the human queue (Tier 3), or get blocked.
"""
from __future__ import annotations

from collections import deque

import itertools

from app.bus import Message, MessageBus
from agents.guardrails import Guardrails
from agents.reservation_integrity import ReservationIntegrityAgent
from agents.simulator import SimulatorAgent
from agents.tools import ToolBlocked, ToolRegistry

MAX_PENDING_APPROVALS = 6
RETRY_BACKOFF = 2.0     # seconds x retry number

_ids = itertools.count(1)


class ActionRouterAgent:
    name = "ActionRouterAgent"

    def __init__(self, bus: MessageBus, guard: Guardrails, tools: ToolRegistry,
                 sim: SimulatorAgent, integrity: ReservationIntegrityAgent):
        self.bus, self.guard, self.tools, self.sim, self.integrity = bus, guard, tools, sim, integrity
        self.auto_actions: list[dict] = []
        self.approvals: dict[str, dict] = {}
        self.blocked: list[dict] = []
        self._last_retry: dict[str, float] = {}
        self._escalated: set[str] = set()
        self._capped: set[str] = set()
        bus.subscribe("rca.diagnosis", self.on_diagnosis)
        bus.subscribe("funnel.recovered", self.on_recovered)
        self.history: deque[dict] = deque(maxlen=4000)

    # ---------- building actions ----------
    def _action(self, type_, tier, title, owner, evidence, incident_key, severity="Sev 2",
                reason="", impact="", source="funnel", order_id=None) -> dict:
        return {"id": f"A{next(_ids)}", "type": type_, "tier": tier, "title": title, "owner": owner,
                "evidence": evidence, "incident_key": incident_key, "severity": severity,
                "reason": reason, "impact": impact, "source": source, "order_id": order_id,
                "proposed_by": self.name}

    def on_diagnosis(self, msg: Message) -> None:
        d = msg.payload
        a, top = d["anomaly"], d["top"]
        key = a["key"]
        evidence = [h["evidence"] for h in d["hypotheses"] if h["confidence"] >= 0.3] or [
            f"{a['label']}: {a['rate']:.0%} vs {a['baseline']:.0%} baseline (n={a['n']})"]
        evidence.insert(0, f"{a['label']}: {a['rate']:.0%} vs {a['baseline']:.0%} normal, n={a['n']}")
        lost = int(a["n"] * (a["baseline"] - a["rate"]))
        impact = f"~{lost} travelers lost in the last 10s window"
        stage = a["from_stage"]

        plan: list[dict] = []
        if not top:
            plan.append(self._action("notify", 1, f"Investigate drop at {a['label']} (cause unknown)",
                                     "Shopping on-call", evidence, key, reason=d["summary"], impact=impact))
        elif stage == "payment":
            plan += [
                self._action("notify", 1, f"Payment success dropped for {top['value']}", "Payments on-call",
                             evidence, key, "Sev 1", d["summary"], impact),
                self._action("message_travelers", 3,
                             f"Email travelers whose {top['value']} payment failed a link to pay another way",
                             "Service ops", evidence, key, "Sev 1",
                             "Recovers bookings, but it contacts travelers, so a human approves.", impact),
            ]
        elif stage == "checkout":
            plan += [
                self._action("notify", 1, f"Checkout drop on {top['value']}: price shown differs",
                             "Checkout PM + app on-call", evidence, key, "Sev 2", d["summary"], impact),
                # The tempting shortcut. Guardrails must block it (Tier 4).
                self._action("change_price", 4, f"Lower the {top['value']} price to match search",
                             "Pricing", evidence, key, "Sev 2", "Tempting quick fix proposed by planner"),
                self._action("price_match_credit", 3,
                             f"Honor the search price for affected {top['value']} travelers",
                             "Service ops", evidence, key, "Sev 2",
                             "Costs money, so a human approves.", impact),
            ]
        elif stage == "booking_created":
            plan.append(self._action("notify", 1, f"{top['value']} is not confirming bookings",
                                     "Partner manager", evidence, key, "Sev 1", d["summary"], impact))
        else:
            plan.append(self._action("notify", 1, f"Drop at {a['label']} on {top['value']}",
                                     "Shopping on-call", evidence, key, "Sev 2", d["summary"], impact))
        for action in plan:
            action["segment"] = {"dimension": top["dimension"], "value": top["value"]} if top else None
            self.submit(action)

    def on_recovered(self, msg: Message) -> None:
        # Close open approvals for that incident that were never decided.
        for ap in self.approvals.values():
            if ap["incident_key"] == msg.payload["key"] and ap["status"] == "pending" and not ap.get("order_id"):
                ap["status"] = "expired"

    # ---------- reservation flow (runs every tick) ----------
    def waiting_for_human(self) -> int:
        self._capped &= set(self.sim.orders)        # forget orders the demo has dropped
        return len(self._capped - self._escalated)

    def tick(self, now: float) -> None:
        self._retry_results: list[bool] = []
        for o in self.integrity.stuck_orders(self.sim.orders, now):
            if o["status"] != "pending" or o["id"] in self._escalated:
                continue
            if o["id"] in self._capped:          # retries used up: waiting for room in the human queue
                self._escalate(o, now)
                continue
            if now - self._last_retry.get(o["id"], -1e9) < RETRY_BACKOFF * max(o["retries"], 1):
                continue
            self._last_retry[o["id"]] = now
            ev = [f"{o['id']} paid {now - o['created']:.0f}s ago, no confirmation from {o['supplier']}"]
            retry = self._action("retry_confirmation", 2, f"Retry supplier confirmation for {o['id']}",
                                 "Agent (auto)", ev, f"order:{o['id']}", "Sev 3", source="order",
                                 order_id=o["id"])
            decision = self.submit(retry, order=o)
            if decision["rule"] == "retry_cap":
                self._capped.add(o["id"])
                self._escalate(o, now)
            elif retry.get("result"):
                self._retry_results.append(retry["result"]["ok"])
        if self._retry_results:
            ok = sum(self._retry_results)
            fail = len(self._retry_results) - ok
            self.bus.publish(self.name, "action.auto", {"ok": ok, "failed": fail},
                             f"Auto-fix: retried {len(self._retry_results)} supplier confirmation(s): "
                             f"{ok} confirmed, {fail} still not responding.", to="Simulator")

    def _escalate(self, o: dict, now: float) -> None:
        pending = sum(1 for a in self.approvals.values() if a["status"] == "pending")
        if pending >= MAX_PENDING_APPROVALS:
            return      # queue is full; try again next tick
        self._escalated.add(o["id"])
        o["status"] = "needs_human"
        ev = [f"{o['id']}: {o['retries']} retries to {o['supplier']} failed",
              f"Check-in in {o['checkin_hours']}h, booking value ${o['value_usd']}"]
        self.submit(self._action(
            "rebook_traveler", 3, f"Rebook traveler {o['traveler']} ({o['email']}) - {o['id']}",
            "Service ops", ev, f"order:{o['id']}", "Sev 1" if o["checkin_hours"] <= 24 else "Sev 2",
            "Supplier won't confirm. Rebooking moves money and changes the trip, so a human decides.",
            f"${o['value_usd']} booking, check-in in {o['checkin_hours']}h", source="order",
            order_id=o["id"]))

    # ---------- the gate ----------
    def submit(self, action: dict, order: dict | None = None) -> dict:
        now = self.bus.now
        decision = self.guard.check(action, now, order)
        action["decision"] = decision
        action["ts"] = now
        self.history.append(action)          # every proposed action, for the event trace view
        if decision["decision"] == "allow":
            try:
                result = self.tools.run(action, now)
            except ToolBlocked as exc:
                decision.update(decision="block", rule="prohibited", reason=str(exc))
                self.blocked.append(action)
                return decision
            action["result"] = result
            self.auto_actions.append(action)
            self.auto_actions[:] = self.auto_actions[-40:]
            if action["type"] == "notify":
                self.bus.publish(self.name, "alert.sent", action,
                                 f"Alert -> {action['owner']}: {action['title']}", to=action["owner"])
        elif decision["decision"] == "needs_human":
            action["status"] = "pending"
            self.approvals[action["id"]] = action
            self.bus.publish(self.name, "approval.requested", action,
                             f"Needs a human: {action['title']}", to="Human agent")
        else:
            self.blocked.append(action)
            self.blocked[:] = self.blocked[-40:]
        return decision

    def decide(self, approval_id: str, approve: bool, note: str = "") -> dict:
        ap = self.approvals.get(approval_id)
        if not ap or ap["status"] != "pending":
            raise KeyError(approval_id)
        now = self.bus.now
        ap["note"] = note
        ap["decided_at"] = now
        if approve:
            ap["result"] = self.tools.run(ap, now, approved_by="human")
            ap["status"] = "approved"
            text = f"Human APPROVED: {ap['title']} -> {ap['result']['detail']}"
        else:
            ap["status"] = "rejected"
            if ap.get("order_id") and ap["order_id"] in self.sim.orders:
                self.sim.orders[ap["order_id"]]["status"] = "escalated"
            text = f"Human REJECTED: {ap['title']}" + (f" ({note})" if note else "")
        self.guard.audit.append({"ts": now, "action": ap["type"], "tier": ap["tier"], "title": ap["title"],
                                 "decision": ap["status"], "rule": None, "reason": f"Human: {note or '-'}"})
        self.bus.publish("Human agent", "human.decision", ap, text, to=self.name)
        return ap
