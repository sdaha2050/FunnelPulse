"""RootCauseAgent: works out *why* a drop is happening.

It splits the affected travelers by segment (payment method, supplier, device,
market, brand) and looks for the one segment that explains most of the lost
conversions. Every hypothesis carries evidence and a confidence score. Below
the confidence threshold it says "unknown, needs review" instead of guessing.

If ANTHROPIC_API_KEY is set (and the `anthropic` package is installed), an LLM
rewrites the summary in plain English in the background. The numbers always
come from this code, never from the model.
"""
from __future__ import annotations

import os
import threading

from app.bus import Message, MessageBus

DIMENSIONS = ["payment_method", "supplier", "device", "market", "brand"]
DIM_LABELS = {"payment_method": "payment method", "supplier": "supplier", "device": "device",
              "market": "market", "brand": "brand"}
CONFIDENCE_THRESHOLD = 0.5
MIN_SEGMENT = 15


def diagnose(sample: list[dict], baseline: float) -> dict:
    """Pure function (easy to test): rank segments that explain a drop."""
    n = len(sample)
    rate = sum(s["converted"] for s in sample) / n if n else 0
    total_lost = max(n * (baseline - rate), 1e-9)
    hyps = []
    for dim in DIMENSIONS:
        values = {s.get(dim) for s in sample}
        for val in values:
            seg = [s for s in sample if s.get(dim) == val]
            rest = [s for s in sample if s.get(dim) != val]
            if len(seg) < MIN_SEGMENT or len(rest) < MIN_SEGMENT:
                continue
            r_seg = sum(s["converted"] for s in seg) / len(seg)
            r_rest = sum(s["converted"] for s in rest) / len(rest)
            if r_rest <= 0 or r_seg >= r_rest:
                continue
            gap = (r_rest - r_seg) / r_rest                     # how much worse this segment is
            explained = min(len(seg) * (r_rest - r_seg) / total_lost, 1.0)  # share of the loss
            # big gap AND explains most of the loss = high confidence
            conf = round(min(0.99, explained * min(1.0, gap / 0.3)), 2)
            hyps.append({
                "dimension": dim, "value": val, "confidence": conf,
                "evidence": f"{val}: {r_seg:.0%} convert vs {r_rest:.0%} for other "
                            f"{DIM_LABELS[dim]}s (n={len(seg)})",
            })
    hyps.sort(key=lambda h: h["confidence"], reverse=True)
    top = hyps[0] if hyps and hyps[0]["confidence"] >= CONFIDENCE_THRESHOLD else None
    return {"hypotheses": hyps[:3], "top": top, "rate": rate}


class RootCauseAgent:
    name = "RootCauseAgent"

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.diagnoses: list[dict] = []
        self._confident: set[str] = set()      # anomalies with a confident diagnosis
        self._last_try: dict[str, float] = {}
        bus.subscribe("funnel.anomaly", self.on_anomaly)
        bus.subscribe("funnel.update", self.on_update)
        bus.subscribe("funnel.recovered", lambda m: self._confident.discard(m.payload["key"]))

    def on_update(self, msg: Message) -> None:
        """If the first diagnosis was 'unknown', try again every 2s as more data arrives."""
        key = msg.payload["key"]
        if key in self._confident or self.bus.now - self._last_try.get(key, -1e9) < 2.0:
            return
        anomaly = {k: v for k, v in msg.payload.items() if k != "sample"}
        if diagnose(msg.payload["sample"], anomaly["baseline"])["top"]:
            self.on_anomaly(msg, retry=True)
        else:
            self._last_try[key] = self.bus.now

    def on_anomaly(self, msg: Message, retry: bool = False) -> None:
        anomaly = {k: v for k, v in msg.payload.items() if k != "sample"}
        self._last_try[anomaly["key"]] = self.bus.now
        result = diagnose(msg.payload["sample"], anomaly["baseline"])
        top = result["top"]
        if top:
            self._confident.add(anomaly["key"])
            summary = (f"Most likely cause: {DIM_LABELS[top['dimension']]} = {top['value']} "
                       f"(confidence {top['confidence']:.0%}). {top['evidence']}.")
        else:
            summary = "Cause unknown: no single segment explains the drop. Needs human review."
        if retry:
            summary = "Update with more data. " + summary
        diag = {"anomaly": anomaly, **result, "summary": summary, "ts": self.bus.now}
        self.diagnoses.append(diag)
        self.diagnoses[:] = self.diagnoses[-20:]
        self._maybe_llm_summary(diag)
        self.bus.publish(self.name, "rca.diagnosis", diag, summary, to="ActionRouterAgent")

    def _maybe_llm_summary(self, diag: dict) -> None:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return

        def run():
            try:
                import anthropic  # optional dependency
                client = anthropic.Anthropic()
                facts = {"drop": diag["anomaly"]["label"], "rate": diag["rate"],
                         "baseline": diag["anomaly"]["baseline"], "hypotheses": diag["hypotheses"]}
                resp = client.messages.create(
                    model=os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5"), max_tokens=120,
                    messages=[{"role": "user", "content":
                               "In 2 short sentences for an ops team, explain this booking funnel "
                               f"drop and its likely cause. Use only these facts: {facts}"}])
                diag["llm_summary"] = resp.content[0].text
            except Exception as exc:  # never let the LLM break the pipeline
                diag["llm_summary_error"] = str(exc)[:120]

        threading.Thread(target=run, daemon=True).start()
