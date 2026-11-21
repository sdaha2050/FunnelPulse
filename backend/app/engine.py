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
                "agents": AGENTS,
                "tools": TOOL_TIERS,
            }


def _public(a: dict) -> dict:
    keys = ("id", "type", "tier", "title", "owner", "evidence", "severity", "reason", "impact",
            "status", "ts", "result", "note", "order_id", "decision")
    return {k: a.get(k) for k in keys}
