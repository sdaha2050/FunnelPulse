"""Guardrails: every action an agent proposes is checked here first.

Rules (in order): kill switch, prohibited (Tier 4), evidence required,
bad-data suppression, duplicate alerts, alert rate limit, retry cap,
Tier 3 needs a human. Every decision is written to the audit log, and every
blocked mistake is counted as a "mishap prevented".
"""
from __future__ import annotations

import re
from collections import deque

from app.bus import MessageBus

RETRY_CAP = 3
ALERTS_PER_OWNER_PER_MIN = 5
DEDUP_SECONDS = 120
EMAIL_RE = re.compile(r"\b([A-Za-z0-9])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")

RULE_LABELS = {
    "kill_switch": "Kill switch stopped an automated action",
    "prohibited": "Blocked a prohibited action (price / ranking / fraud rules)",
    "no_evidence": "Blocked an action with no evidence",
    "bad_data": "Suppressed an alert because the data was broken",
    "duplicate": "Deduplicated a repeat alert for the same incident",
    "rate_limit": "Held an alert to prevent alert flooding",
    "retry_cap": "Stopped a 4th retry; handed the booking to a human",
    "pii": "Masked personal data before it was shown",
}


def mask_pii(text: str) -> tuple[str, bool]:
    """Mask any raw email address: jane.doe@x.com -> j***@x.com."""
    masked, n = EMAIL_RE.subn(lambda m: f"{m.group(1)}***@{m.group(2)}", text)
    return masked, n > 0


class Guardrails:
    name = "Guardrails"

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.kill_switch = {"global": False, "types": set()}
        self.data_reliable = True
        self.bad_segment: dict | None = None
        self.audit: deque[dict] = deque(maxlen=300)
        self.mishaps: dict[str, dict] = {}     # rule -> {count, last example}
        self._sent: dict[str, float] = {}      # dedup key -> time
        self._alerts: dict[str, deque] = {}    # owner -> recent alert times
        bus.subscribe("dq.status", self._on_dq)

    def _on_dq(self, msg) -> None:
        self.data_reliable = msg.payload["reliable"]
        self.bad_segment = msg.payload.get("segment")

    def _hit_by_bad_data(self, a: dict) -> bool:
        """Only suppress alerts the broken data could explain (same segment, or cause unknown)."""
        if self.data_reliable:
            return False
        seg = a.get("segment")
        return seg is None or self.bad_segment is None or seg == self.bad_segment

    def _prevent(self, rule: str, action: dict, now: float) -> None:
        m = self.mishaps.setdefault(rule, {"rule": rule, "label": RULE_LABELS[rule], "count": 0})
        m["count"] += 1
        m["last_ts"] = now
        m["example"] = action["title"]
        if m["count"] == 1 or rule in ("prohibited", "bad_data", "kill_switch"):
            self.bus.publish(self.name, "guardrail.blocked", {"rule": rule, "action": action["type"]},
                             f"BLOCKED '{action['title']}' -> {RULE_LABELS[rule]}.",
                             to=action.get("proposed_by", "ActionRouterAgent"))

    def check(self, action: dict, now: float, order: dict | None = None) -> dict:
        """Return {"decision": "allow" | "needs_human" | "block" | "hold", "rule": ..., "reason": ...}."""
        # PII: mask anything that slipped into text fields.
        for field in ("title", "reason", "impact"):
            if isinstance(action.get(field), str):
                action[field], hit = mask_pii(action[field])
                if hit:
                    self._prevent("pii", action, now)

        decision = self._decide(action, now, order)
        self.audit.append({"ts": now, "action": action["type"], "tier": action["tier"],
                           "title": action["title"], **decision})
        if decision["decision"] == "block" and decision["rule"]:
            self._prevent(decision["rule"], action, now)
        return decision

    def _decide(self, a: dict, now: float, order: dict | None) -> dict:
        ks = self.kill_switch
        if a["tier"] >= 2 and (ks["global"] or a["type"] in ks["types"]):
            return {"decision": "block", "rule": "kill_switch", "reason": "Kill switch is ON"}
        if a["tier"] >= 4:
            return {"decision": "block", "rule": "prohibited",
                    "reason": "Tier 4: agents may never change prices, ranking, inventory or fraud rules"}
        if not a.get("evidence"):
            return {"decision": "block", "rule": "no_evidence", "reason": "No evidence attached"}
        if a["type"] == "notify" and a.get("source") == "funnel" and self._hit_by_bad_data(a):
            return {"decision": "block", "rule": "bad_data",
                    "reason": "Data quality check failed: this drop may be broken tracking"}
        if a["type"] == "notify":
            key = f"{a['incident_key']}:{a['owner']}"
            if now - self._sent.get(key, -1e9) < DEDUP_SECONDS:
                return {"decision": "block", "rule": "duplicate", "reason": "Already alerted"}
            q = self._alerts.setdefault(a["owner"], deque())
            while q and q[0] < now - 60:
                q.popleft()
            if len(q) >= ALERTS_PER_OWNER_PER_MIN:
                return {"decision": "block", "rule": "rate_limit", "reason": "Alert budget used"}
            q.append(now)
            self._sent[key] = now
        if a["type"] == "retry_confirmation" and order and order["retries"] >= RETRY_CAP:
            return {"decision": "block", "rule": "retry_cap",
                    "reason": f"Already retried {RETRY_CAP} times"}
        if a["tier"] == 3:
            return {"decision": "needs_human", "rule": None, "reason": "Tier 3: a human must approve"}
        return {"decision": "allow", "rule": None, "reason": "Within policy"}

    def snapshot(self) -> dict:
        return {
            "kill_switch": {"global": self.kill_switch["global"],
                            "types": sorted(self.kill_switch["types"])},
            "data_reliable": self.data_reliable,
            "mishaps": sorted(self.mishaps.values(), key=lambda m: -m.get("last_ts", 0)),
            "mishaps_total": sum(m["count"] for m in self.mishaps.values()),
            "audit": list(self.audit)[-25:][::-1],
        }
