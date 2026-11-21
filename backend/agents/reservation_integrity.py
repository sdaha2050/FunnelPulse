"""ReservationIntegrityAgent: finds bookings that broke after the traveler paid.

The traveler thinks the trip is booked, but the supplier never confirmed it.
These are the most expensive failures (a traveler turned away at the hotel),
so they are sorted by check-in time: soonest first.
"""
from __future__ import annotations

from app.bus import MessageBus

STUCK_AFTER = 10.0     # seconds without supplier confirmation = stuck (demo SLA)


class ReservationIntegrityAgent:
    name = "ReservationIntegrityAgent"

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self.flagged: set[str] = set()

    def stuck_orders(self, orders: dict, now: float) -> list[dict]:
        stuck = [o for o in orders.values()
                 if o["status"] in ("pending", "needs_human") and now - o["created"] >= STUCK_AFTER]
        return sorted(stuck, key=lambda o: (o["checkin_hours"], o["created"]))

    def tick(self, now: float, orders: dict) -> list[dict]:
        stuck = self.stuck_orders(orders, now)
        new = [o for o in stuck if o["id"] not in self.flagged]
        if new:
            self.flagged.update(o["id"] for o in new)
            by_supplier: dict[str, int] = {}
            for o in new:
                by_supplier[o["supplier"]] = by_supplier.get(o["supplier"], 0) + 1
            top = max(by_supplier, key=by_supplier.get)
            soonest = new[0]["checkin_hours"]
            self.bus.publish(
                self.name, "reservation.stuck",
                {"orders": [{"id": o["id"], "supplier": o["supplier"], "created": o["created"]} for o in new],
                 "by_supplier": by_supplier},
                f"{len(new)} paid booking(s) not confirmed after {STUCK_AFTER:.0f}s "
                f"(most from {top}; soonest check-in in {soonest}h).", to="ActionRouterAgent")
        return stuck

    def snapshot(self, orders: dict, now: float) -> list[dict]:
        return [{
            "id": o["id"], "supplier": o["supplier"], "brand": o["brand"],
            "checkin_hours": o["checkin_hours"], "retries": o["retries"], "status": o["status"],
            "waiting_s": round(now - o["created"]), "traveler": o["traveler"], "email": o["email"],
        } for o in self.stuck_orders(orders, now)[:8]]
