"""DataQualityAgent: checks the data before anyone trusts it.

Freshness (did a batch arrive?), volume (is it normal size?) and schema (are
required fields present?). If the data is bad, it marks metrics "unreliable" so
the guardrails can suppress alerts. Bad data must never look like a real drop.
"""
from __future__ import annotations

from collections import Counter, deque

from app.bus import Message, MessageBus

REQUIRED = ("id", "brand", "market", "device", "session_id")
SCHEMA_ERROR_LIMIT = 0.02     # >2% broken events = unreliable
CLEAN_SECONDS = 10            # must be clean this long (one funnel window) to recover


class DataQualityAgent:
    name = "DataQualityAgent"

    def __init__(self, bus: MessageBus, expected_per_batch: int = 60):
        self.bus = bus
        self.expected = expected_per_batch
        self.reliable = True
        self.reason = "All checks passing"
        self.bad_segment: dict | None = None
        self.last_batch_ts: float | None = None
        self._recent: deque[tuple[float, int, int]] = deque(maxlen=8)  # (ts, total, broken)
        self._last_bad_ts = -999.0
        self.checks = {"freshness": True, "volume": True, "schema": True}
        self.lag: float = 0.0          # how far behind real time the data is
        bus.subscribe("events.batch", self.on_batch)

    def on_batch(self, msg: Message) -> None:
        batch = msg.payload["batch"]
        now = self.bus.now
        broken = [j for j in batch if any(j.get(f) in (None, "") for f in REQUIRED if f != "session_id")
                  or j.get("session_id", "ok") is None]
        self._recent.append((now, len(batch), len(broken)))
        self.last_batch_ts = now
        self.lag = msg.payload.get("lag", 0.0)

        total = sum(t for _, t, _ in self._recent)
        bad = sum(b for _, _, b in self._recent)
        schema_ok = total == 0 or bad / total <= SCHEMA_ERROR_LIMIT
        volume_ok = len(batch) >= 0.5 * self.expected
        self.checks = {"freshness": True, "volume": volume_ok, "schema": schema_ok}

        if not (schema_ok and volume_ok):
            self._last_bad_ts = now
            seg = Counter(j["device"] for j in broken).most_common(1)
            self.bad_segment = {"dimension": "device", "value": seg[0][0]} if seg else None
            if self.reliable:
                self.reliable = False
                where = f" from {self.bad_segment['value']}" if self.bad_segment else ""
                self.reason = f"{bad / max(total, 1):.0%} of events are missing required fields{where}"
                self.bus.publish(self.name, "dq.status",
                                 {"reliable": False, "reason": self.reason, "segment": self.bad_segment},
                                 f"Data looks broken: {self.reason}. Marking metrics UNRELIABLE.",
                                 to="Guardrails")
        elif not self.reliable and now - self._last_bad_ts >= CLEAN_SECONDS:
            self.reliable = True
            self.reason = "All checks passing"
            self.bad_segment = None
            self.bus.publish(self.name, "dq.status", {"reliable": True},
                             "Data is clean again. Metrics are reliable.", to="Guardrails")

    def check_freshness(self, now: float) -> None:
        ok = self.last_batch_ts is not None and now - self.last_batch_ts < 3
        self.checks["freshness"] = ok

    def snapshot(self) -> dict:
        return {"reliable": self.reliable, "reason": self.reason, "checks": dict(self.checks),
                "lag_seconds": self.lag}
