"""The tool layer: the only way agents can change anything.

Defense in depth: even if a guardrail bug let a Tier 4 action through, the
tool simply does not exist here, so it cannot run. Tier 3 tools refuse to run
unless a human approved them.
"""
from __future__ import annotations

from agents.simulator import SimulatorAgent


class ToolBlocked(Exception):
    pass


TOOL_TIERS = {
    "notify": 1,
    "retry_confirmation": 2,
    "message_travelers": 3,
    "price_match_credit": 3,
    "rebook_traveler": 3,
    "refund": 3,
    # Traveler assistant tools (Tier 1-2 run automatically, Tier 3 needs a human)
    "create_ticket": 1,
    "request_early_checkin": 2, "request_late_checkout": 2, "housekeeping_request": 2, "room_move": 2,
    "create_booking": 2, "cancel_booking": 2, "modify_booking": 2, "send_invoice": 2, "add_loyalty_points": 2,
    "goodwill_credit": 3,
    # Tier 4 tools (change_price, change_ranking, edit_fraud_rules) are
    # intentionally NOT registered.
}


ASSISTANT_DETAIL = {
    "create_ticket": "Ticket sent to the hotel", "request_early_checkin": "Early check-in requested from the hotel",
    "request_late_checkout": "Late checkout set until 1pm", "housekeeping_request": "Housekeeping dispatched",
    "room_move": "Room move arranged", "create_booking": "Booking created and itinerary emailed",
    "cancel_booking": "Booking cancelled, refund within policy issued", "modify_booking": "Booking updated",
    "send_invoice": "Invoice emailed", "add_loyalty_points": "Loyalty points credited",
}


class ToolRegistry:
    def __init__(self, sim: SimulatorAgent):
        self.sim = sim
        self.executed: list[dict] = []     # used by the EvalAgent to audit for violations

    def run(self, action: dict, now: float, approved_by: str | None = None) -> dict:
        kind = action["type"]
        if kind not in TOOL_TIERS:
            raise ToolBlocked(f"Tool '{kind}' does not exist for agents")
        if TOOL_TIERS[kind] == 3 and approved_by is None:
            raise ToolBlocked(f"Tool '{kind}' needs human approval")

        result = {"ok": True, "detail": ""}
        order = self.sim.orders.get(action.get("order_id") or "")
        supplier_down = bool(order and self.sim.supplier_down(order["supplier"]))
        if kind == "notify":
            result["detail"] = f"Paged {action['owner']}"
        elif kind == "retry_confirmation":
            ok = self.sim.retry_confirmation(action["order_id"], now)
            result = {"ok": ok, "detail": "Supplier confirmed on retry" if ok else "Supplier still not responding"}
        elif kind == "rebook_traveler":
            o = self.sim.orders.get(action["order_id"])
            if o:
                o["status"] = "rebooked"
            result["detail"] = "Traveler rebooked at a comparable property"
        elif kind == "refund":
            o = self.sim.orders.get(action["order_id"])
            if o:
                o["status"] = "refunded"
            result["detail"] = "Refund issued"
        elif kind == "message_travelers":
            result["detail"] = "Message sent to affected travelers"
        elif kind == "price_match_credit":
            result["detail"] = ("Price-match credit applied" if action.get("source") == "assistant"
                                else "Price-match credit applied for affected travelers")
        elif kind == "goodwill_credit":
            result["detail"] = f"Goodwill credit of {action.get('impact') or 'the agreed amount'} applied"
        elif kind in ASSISTANT_DETAIL:
            result["detail"] = ASSISTANT_DETAIL[kind]

        self.executed.append({"ts": now, "type": kind, "tier": TOOL_TIERS[kind],
                              "approved_by": approved_by, "supplier_down": supplier_down, "order_id": action.get("order_id"),
                              "retries_before": (self.sim.orders.get(action.get("order_id") or "", {})
                                                 .get("retries", 0)), **result})
        del self.executed[:-5000]          # evals score the most recent 5,000 actions
        return result
