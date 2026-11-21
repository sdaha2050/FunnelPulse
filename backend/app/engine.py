"""Wires all agents together and runs one "tick" every 0.5 seconds."""
from __future__ import annotations

import threading
import time

from app.bus import MessageBus
from agents.action_router import ActionRouterAgent
from agents.data_quality import DataQualityAgent
from agents.evals import EvalAgent
from agents.funnel_monitor import FunnelMonitorAgent
from agents.guardrails import Guardrails
from agents.reservation_integrity import ReservationIntegrityAgent
from agents.root_cause import RootCauseAgent
from agents.simulator import INCIDENTS, SimulatorAgent
from agents.tools import TOOL_TIERS, ToolRegistry

TICK_SECONDS = 0.5

AGENTS = [
    {"name": "Simulator", "job": "Fake data ingestion: streams traveler journeys and injects incidents",
     "powers": "None (data source)"},
    {"name": "DataQualityAgent", "job": "Checks freshness, volume and schema before data is trusted",
     "powers": "Tier 0: observe"},
    {"name": "FunnelMonitorAgent", "job": "Compares stage-to-stage conversion with baseline",
     "powers": "Tier 0: observe"},
    {"name": "ReservationIntegrityAgent", "job": "Finds paid bookings the supplier never confirmed",
     "powers": "Tier 0: observe"},
    {"name": "RootCauseAgent", "job": "Ranks the segment that explains a drop, with evidence + confidence",
     "powers": "Tier 0: observe"},
    {"name": "ActionRouterAgent", "job": "Picks the action, tier, severity and owner",
     "powers": "Tier 1 notify, Tier 2 safe retry; proposes Tier 3"},
    {"name": "Guardrails", "job": "Checks every action against policy; audit log; kill switch",
     "powers": "Can block anything"},
    {"name": "EvalAgent", "job": "Scores agents against ground truth in real time",
     "powers": "Tier 0: observe"},
    {"name": "Human agent", "job": "Approves or rejects sensitive (Tier 3) actions",
     "powers": "Tier 3 approve"},
]


class Engine:
    def __init__(self, seed: int = 7, auto_incidents: bool = True):
        self.lock = threading.RLock()
        self.bus = MessageBus()
        self.sim = SimulatorAgent(self.bus, seed=seed, auto_incidents=auto_incidents)
        self.dq = DataQualityAgent(self.bus, expected_per_batch=self.sim.per_tick)
        self.guard = Guardrails(self.bus)
        self.funnel = FunnelMonitorAgent(self.bus)
        self.integrity = ReservationIntegrityAgent(self.bus)
        self.rca = RootCauseAgent(self.bus)
        self.tools = ToolRegistry(self.sim)
        self.router = ActionRouterAgent(self.bus, self.guard, self.tools, self.sim, self.integrity)
        self.evals = EvalAgent(self.bus, self.tools)
        self.now = 0.0
        self.started_wall = time.time()
        self.ticks = 0

    def tick(self, now: float | None = None) -> None:
        with self.lock:
            self.now = now if now is not None else self.now + TICK_SECONDS
            self.bus.now = self.now
            self.ticks += 1
            self.sim.tick(self.now)                                   # 1. ingest (-> DataQuality via bus)
            self.dq.check_freshness(self.now)
            self.funnel.tick(self.now, self.sim.journeys, self.sim.orders)  # 2. detect drops (-> RCA -> Router)
            self.integrity.tick(self.now, self.sim.orders)            # 3. detect stuck bookings
            self.router.tick(self.now)                                # 4. retries / escalations

    # ---------- commands from the UI ----------
    def start_incident(self, kind: str) -> dict:
        with self.lock:
            return self.sim.start_incident(kind, self.now)

    def clear_incident(self) -> None:
        with self.lock:
            self.sim.clear_incident(self.now)

    def decide(self, approval_id: str, approve: bool, note: str = "") -> dict:
        with self.lock:
            return self.router.decide(approval_id, approve, note)

    def set_kill_switch(self, global_on: bool | None = None, action_type: str | None = None,
                        on: bool | None = None) -> dict:
        with self.lock:
            ks = self.guard.kill_switch
            if global_on is not None:
                ks["global"] = global_on
                self.bus.publish("Human agent", "killswitch", {"global": global_on},
                                 f"Kill switch {'ON: all automated fixes stopped' if global_on else 'OFF'}",
                                 to="Guardrails")
            if action_type:
                (ks["types"].add if on else ks["types"].discard)(action_type)
            return self.guard.snapshot()["kill_switch"]

    # ---------- everything the UI needs ----------
    def state(self) -> dict:
        with self.lock:
            now = self.now
            inc = self.sim.incident
            approvals = sorted(self.router.approvals.values(), key=lambda a: -a["ts"])
            return {
                "now": round(now, 1),
                "incident": ({"type": inc["type"], "label": inc["label"], "real": inc["real"],
                              "seconds_left": round(inc["ends"] - now)} if inc else None),
                "incident_types": {k: v["label"] for k, v in INCIDENTS.items()},
                "data_quality": self.dq.snapshot(),
                **self.funnel.snapshot(),
                "events": list(self.sim.recent_events)[-20:][::-1],
                "messages": [m.to_dict() for m in list(self.bus.log)[-60:]][::-1],
                "stuck_orders": self.integrity.snapshot(self.sim.orders, now),
                "auto_actions": [_public(a) for a in self.router.auto_actions[-15:][::-1]],
                "approvals": [_public(a) for a in approvals if a["status"] == "pending"],
                "waiting_for_human": self.router.waiting_for_human(),
                "decided": [_public(a) for a in approvals if a["status"] != "pending"][:8],
                "blocked": [_public(a) for a in self.router.blocked[-10:][::-1]],
                "guardrails": self.guard.snapshot(),
                "evals": self.evals.snapshot(now),
                "diagnoses": [{k: v for k, v in d.items() if k != "anomaly"} | {"label": d["anomaly"]["label"]}
                              for d in self.rca.diagnoses[-3:][::-1]],
                "regions": self.regions(),
                "agents": AGENTS,
                "tools": TOOL_TIERS,
            }


    # ---------- regional dashboards ----------
    def regions(self) -> dict:
        """Roll the last 20s of journeys up by US state and by country.

        Status is computed from the data only (never from the simulator's ground
        truth): a region is "alert" when its search-to-booking conversion is far
        below everyone else's AND the gap is statistically clear (z >= 4.5).
        """
        # Last 20s: short enough that a new problem shows up fast on screen.
        journeys = [j for j in self.sim.journeys if j["schema_ok"] and j["ts"] >= self.now - 20]
        orders = [o for o in self.sim.orders.values() if o["created"] >= self.now - 20]
        stuck = [o for o in self.sim.orders.values() if o["status"] != "confirmed"
                 and self.now - o["created"] > 5]
        top = next((d["top"] for d in reversed(self.rca.diagnoses) if d.get("top")), None)
        us = [j for j in journeys if j["market"] == "US"]
        intl = [j for j in journeys if j["market"] != "US"]
        return {
            "us": _rollup(us, "state", [o for o in orders if o["market"] == "US"],
                          [o for o in stuck if o["market"] == "US"], top),
            "intl": _rollup(intl, "market", [o for o in orders if o["market"] != "US"],
                            [o for o in stuck if o["market"] != "US"], top),
        }


SHOP_STAGES = ["Search", "Detail", "Checkout", "Payment", "Booked"]


def _stage_counts(js: list[dict]) -> list[int]:
    return [sum(1 for j in js if j["reached"] >= i) for i in range(5)]


def _rollup(js: list[dict], key: str, orders: list[dict], stuck: list[dict], top: dict | None) -> dict:
    total_conv = (sum(j["reached"] >= 4 for j in js) / len(js)) if js else 0
    rows = []
    for val in sorted({j[key] for j in js if j.get(key)}):
        g = [j for j in js if j[key] == val]
        rest = [j for j in js if j[key] != val]
        conv = sum(j["reached"] >= 4 for j in g) / len(g)
        rest_conv = (sum(j["reached"] >= 4 for j in rest) / len(rest)) if rest else conv
        at_pay = sum(j["reached"] >= 3 for j in g)
        paid = sum(j["reached"] >= 4 for j in g)
        ratio = conv / rest_conv if rest_conv else 1
        # z-score: how many standard errors below everyone else? Small regions are
        # noisy, so a low ratio alone is not enough; it must be statistically clear.
        se = (rest_conv * (1 - rest_conv) / len(g)) ** 0.5 if 0 < rest_conv < 1 else 0
        z = (rest_conv - conv) / se if se else 0
        status = "ok"
        if z >= 4.5 and ratio < 0.6:
            status = "alert"
        elif z >= 3.5 and ratio < 0.75:
            status = "watch"
        flagged = bool(top and top["dimension"] == key and top["value"] == val)
        rows.append({
            "code": val, "searches": len(g), "bookings": paid,
            "conversion": round(conv, 4), "vs_others": round(ratio, 2), "z": round(z, 1),
            "payment_success": round(paid / at_pay, 3) if at_pay else None,
            "stages": _stage_counts(g),
            "revenue_usd": sum(o["value_usd"] for o in orders if o.get(key) == val),
            "stuck_orders": sum(1 for o in stuck if o.get(key) == val),
            "status": "alert" if flagged else status,
            "agent_flag": (f"RootCauseAgent: {top['value']} explains the drop "
                           f"({round(top['confidence'] * 100)}% confidence)") if flagged else None,
        })
    rows.sort(key=lambda r: -r["searches"])
    return {
        "searches": len(js), "bookings": sum(j["reached"] >= 4 for j in js),
        "conversion": round(total_conv, 4),
        "revenue_usd": sum(o["value_usd"] for o in orders),
        "stuck_orders": len(stuck), "stage_labels": SHOP_STAGES, "stages": _stage_counts(js),
        "alerts": sum(r["status"] == "alert" for r in rows), "rows": rows,
    }


def _public(a: dict) -> dict:
    keys = ("id", "type", "tier", "title", "owner", "evidence", "severity", "reason", "impact",
            "status", "ts", "result", "note", "order_id", "decision")
    return {k: a.get(k) for k in keys}
