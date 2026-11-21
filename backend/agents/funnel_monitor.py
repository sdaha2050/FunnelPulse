"""FunnelMonitorAgent: watches conversion between each funnel stage.

Every tick it looks at the last 10 seconds of journeys and compares each
stage-to-stage conversion with its baseline. A drop must be big (>=8%
relative), statistically clear (z >= 4) and based on enough travelers
(min sample) before it is called an anomaly.
"""
from __future__ import annotations

import math

from app.bus import MessageBus
from agents.simulator import BASE_RATES, STAGE_LABELS, STAGES

WINDOW = 10.0
MIN_SAMPLE = 80
MIN_REL_DROP = 0.08
MIN_Z = 4.0
RECOVER_TICKS = 4
CONFIRM_SLA = 5.0                         # seconds a supplier normally takes, at most
BASELINES = {**BASE_RATES, "booking_created": 0.96}


class FunnelMonitorAgent:
    name = "FunnelMonitorAgent"

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.open: dict[str, dict] = {}      # from_stage -> anomaly
        self._normal_ticks: dict[str, int] = {}
        self.funnel: list[dict] = []

    def tick(self, now: float, journeys, orders: dict) -> None:
        window = [j for j in journeys if j["ts"] >= now - WINDOW]
        samples = {}
        counts = {s: 0 for s in STAGES}
        for j in window:
            for i in range(j["reached"] + 1):
                counts[STAGES[i]] += 1

        # Shopping funnel transitions: who reached stage i, and did they go on?
        for i, stage in enumerate(STAGES[:4]):
            samples[stage] = [dict(j, converted=j["reached"] >= i + 1) for j in window if j["reached"] >= i]
        # Reservation step: bookings old enough to judge — confirmed within SLA?
        judged = [o for o in orders.values() if now - 15 <= o["created"] <= now - CONFIRM_SLA]
        samples["booking_created"] = [
            dict(o, converted=bool(o.get("confirmed_at")) and o["confirmed_at"] - o["created"] <= CONFIRM_SLA)
            for o in judged]

        # Suppliers take a few seconds to confirm, so the newest bookings can't be judged yet.
        # Estimate confirmed/delivered from bookings old enough to judge.
        judged_rate = (sum(s["converted"] for s in samples["booking_created"]) / len(samples["booking_created"])
                       if samples["booking_created"] else 1.0)
        counts["supplier_confirmed"] = round(counts["booking_created"] * judged_rate)
        counts["itinerary_delivered"] = round(counts["supplier_confirmed"] * 0.99)

        self.funnel = []
        for i, stage in enumerate(STAGES):
            nxt = counts[STAGES[i + 1]] if i + 1 < len(STAGES) else None
            self.funnel.append({
                "stage": stage, "label": STAGE_LABELS[stage], "count": counts[stage],
                "next_rate": round(nxt / counts[stage], 3) if nxt is not None and counts[stage] else None,
                "baseline": BASELINES.get(stage),
            })

        for stage, sample in samples.items():
            self._evaluate(stage, sample, now)

    def _evaluate(self, stage: str, sample: list[dict], now: float) -> None:
        n = len(sample)
        base = BASELINES[stage]
        if n < MIN_SAMPLE:
            return                                    # not enough travelers to judge
        rate = sum(s["converted"] for s in sample) / n
        z = (base - rate) / math.sqrt(base * (1 - base) / n)
        rel_drop = (base - rate) / base
        is_bad = rel_drop >= MIN_REL_DROP and z >= MIN_Z
        to_stage = STAGES[STAGES.index(stage) + 1]

        if is_bad and stage not in self.open:
            anomaly = {
                "key": f"funnel:{stage}", "from_stage": stage, "to_stage": to_stage,
                "label": f"{STAGE_LABELS[stage]} -> {STAGE_LABELS[to_stage]}",
                "rate": round(rate, 3), "baseline": base, "drop_pct": round(rel_drop * 100, 1),
                "z": round(z, 1), "n": n, "detected_at": now,
            }
            self.open[stage] = anomaly
            self._normal_ticks[stage] = 0
            self.bus.publish(
                self.name, "funnel.anomaly", {**anomaly, "sample": sample},
                f"Drop found: {anomaly['label']} conversion is {rate:.0%} vs {base:.0%} normal "
                f"({n} travelers, z={z:.1f}).", to="RootCauseAgent")
        elif stage in self.open:
            # Hysteresis: stay "open" until conversion is clearly back (drop under half the threshold).
            if rel_drop >= MIN_REL_DROP / 2:
                self._normal_ticks[stage] = 0
                self.open[stage].update(rate=round(rate, 3), drop_pct=round(rel_drop * 100, 1), n=n)
                # Quiet update so RootCause can re-check with more data (not shown in the feed).
                self.bus.publish(self.name, "funnel.update", {**self.open[stage], "sample": sample},
                                 "", log=False)
            else:
                self._normal_ticks[stage] = self._normal_ticks.get(stage, 0) + 1
                if self._normal_ticks[stage] >= RECOVER_TICKS:
                    anomaly = self.open.pop(stage)
                    self.bus.publish(self.name, "funnel.recovered", {"key": anomaly["key"]},
                                     f"Recovered: {anomaly['label']} is back to normal ({rate:.0%}).",
                                     to="ActionRouterAgent")

    def snapshot(self) -> dict:
        return {"funnel": self.funnel,
                "anomalies": [{k: v for k, v in a.items()} for a in self.open.values()]}
