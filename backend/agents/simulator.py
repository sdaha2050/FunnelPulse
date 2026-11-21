"""SimulatorAgent: fake data ingestion.

Generates Expedia-style traveler journeys (search -> ... -> itinerary delivered)
every tick, with realistic drop rates. It can also inject incidents. Because it
creates the incidents, it also knows the *ground truth*, which the EvalAgent
uses to grade the other agents.
"""
from __future__ import annotations

import hashlib
import itertools
import random
from collections import deque

from app.bus import MessageBus

STAGES = ["search", "detail", "checkout", "payment", "booking_created",
          "supplier_confirmed", "itinerary_delivered"]
STAGE_LABELS = {
    "search": "Search", "detail": "Property detail", "checkout": "Checkout",
    "payment": "Payment", "booking_created": "Booking created",
    "supplier_confirmed": "Supplier confirmed", "itinerary_delivered": "Itinerary delivered",
}

# Normal chance of moving from one stage to the next (shopping funnel).
BASE_RATES = {"search": 0.45, "detail": 0.40, "checkout": 0.75, "payment": 0.92}

BRANDS = [("Expedia", 5), ("Hotels.com", 3), ("Vrbo", 2)]
# Country codes (ISO-2). The US gets most traffic, like a real US-based OTA.
MARKETS = [("US", 60), ("GB", 12), ("DE", 7), ("FR", 5), ("CA", 4), ("MX", 3),
           ("JP", 3), ("AU", 2), ("ES", 2), ("IN", 2)]
# Where US travelers book from (state codes).
US_STATES = [("CA", 22), ("TX", 13), ("FL", 12), ("NY", 11), ("WA", 7), ("IL", 6),
             ("NV", 5), ("GA", 5), ("MA", 4), ("NC", 4), ("CO", 4), ("AZ", 4), ("HI", 3)]
DEVICES = [("Web", 4), ("iOS app", 3), ("Android app", 3)]
SUPPLIERS = [("SunStay Hotels", 3), ("Harbor Inns", 3), ("Alpine Lodges", 2), ("CityNest", 2)]
PAYMENTS = [("Visa", 4), ("Mastercard", 3), ("Amex", 3), ("PayPal", 1)]
FIRST = ["ana", "ben", "chen", "dev", "ema", "farid", "gia", "hiro", "ivy", "jon"]

# Incidents the demo can inject. `real=False` means travelers are NOT actually
# affected: it's broken tracking, and alerting on it would be a false alarm.
INCIDENTS = {
    "payment_decline_spike": {
        "label": "Payment declines spike for Amex cards", "from_stage": "payment",
        "dimension": "payment_method", "value": "Amex", "real": True},
    "supplier_timeout": {
        "label": "SunStay Hotels stops confirming bookings", "from_stage": "booking_created",
        "dimension": "supplier", "value": "SunStay Hotels", "real": True},
    "price_mismatch": {
        "label": "iOS app shows a higher price at checkout than in search", "from_stage": "checkout",
        "dimension": "device", "value": "iOS app", "real": True},
    "tracking_outage": {
        "label": "Android app tracking breaks (data problem, travelers are fine)",
        "from_stage": "search", "dimension": "device", "value": "Android app", "real": False},
    # Regional incidents: they light up the US-by-state and International dashboards.
    "state_payment_outage": {
        "label": "California: card payments fail at a regional gateway", "from_stage": "payment",
        "dimension": "state", "value": "CA", "real": True},
    "country_3ds_failure": {
        "label": "United Kingdom: bank verification (3-D Secure) fails", "from_stage": "payment",
        "dimension": "market", "value": "GB", "real": True},
}
PAYMENT_INCIDENTS = {"payment_decline_spike": 0.25, "state_payment_outage": 0.10,
                     "country_3ds_failure": 0.10}

INCIDENT_SECONDS = 35      # how long an injected incident lasts
AUTO_GAP_SECONDS = 15      # calm time between auto-injected incidents


def _pick(rng: random.Random, options):
    names, weights = zip(*options)
    return rng.choices(names, weights=weights, k=1)[0]


def _mask_email(name: str) -> str:
    return f"{name[0]}***@example.com"


class SimulatorAgent:
    name = "Simulator"

    def __init__(self, bus: MessageBus, seed: int = 7, journeys_per_tick: int = 60,
                 auto_incidents: bool = True):
        self.bus = bus
        self.rng = random.Random(seed)
        self.per_tick = journeys_per_tick
        self.auto = auto_incidents
        self.journeys: deque[dict] = deque()      # last ~60s of journeys
        self.orders: dict[str, dict] = {}         # bookings waiting on / done with supplier
        self.recent_events: deque[dict] = deque(maxlen=30)
        self.incident: dict | None = None
        self.incident_history: list[dict] = []
        self._ids = itertools.count(100000)
        self._last_incident_end = 0.0
        self._auto_order = list(INCIDENTS)
        self.rng.shuffle(self._auto_order)
        self._auto_idx = 0
        self._tick = 0

    # ---------- incidents (ground truth) ----------
    def start_incident(self, kind: str, now: float) -> dict:
        if kind not in INCIDENTS:
            raise ValueError(f"unknown incident {kind}")
        self.clear_incident(now)
        self.incident = {"type": kind, **INCIDENTS[kind], "started": now,
                         "ends": now + INCIDENT_SECONDS}
        self.bus.publish(self.name, "incident.started", dict(self.incident),
                         f"Injected test incident: {self.incident['label']}", to="EvalAgent")
        return self.incident

    def clear_incident(self, now: float) -> None:
        if self.incident:
            self.incident["ended"] = now
            self.incident_history.append(self.incident)
            self.bus.publish(self.name, "incident.ended", {"type": self.incident["type"]},
                             f"Incident over: {self.incident['label']}", to="EvalAgent")
            self.incident = None
            self._last_incident_end = now

    def _affects(self, journey: dict, kind: str) -> bool:
        inc = self.incident
        return bool(inc and inc["type"] == kind and journey.get(inc["dimension"]) == inc["value"])

    def supplier_down(self, supplier: str) -> bool:
        inc = self.incident
        return bool(inc and inc["type"] == "supplier_timeout" and inc["value"] == supplier)

    # ---------- the tick ----------
    def tick(self, now: float) -> list[dict]:
        self._tick += 1
        if self.incident and now >= self.incident["ends"]:
            self.clear_incident(now)
        if self.auto and not self.incident and now - self._last_incident_end >= AUTO_GAP_SECONDS \
                and now > 20:
            kind = self._auto_order[self._auto_idx % len(self._auto_order)]
            self._auto_idx += 1
            self.start_incident(kind, now)

        batch = [self._new_journey(now) for _ in range(self.per_tick)]
        self._advance_orders(now)

        # forget old data
        while self.journeys and self.journeys[0]["ts"] < now - 60:
            self.journeys.popleft()
        for oid in [o for o, v in self.orders.items()
                    if (v["created"] < now - 120 and v["status"] in ("confirmed", "rebooked", "refunded"))
                    or v["created"] < now - 300]:          # keep the demo's memory small
            del self.orders[oid]

        # Announce ingestion every 2s so the agent feed isn't flooded.
        log = self._tick % 4 == 0
        bookings = sum(1 for j in batch if j["reached"] >= 4)
        self.bus.publish(self.name, "events.batch", {"batch": batch},
                         f"Ingested {len(batch)} traveler journeys ({bookings} bookings)",
                         to="DataQualityAgent", log=log)
        return batch

    def _new_journey(self, now: float) -> dict:
        rng = self.rng
        name = rng.choice(FIRST)
        j = {
            "id": f"J{next(self._ids)}", "ts": now,
            "brand": _pick(rng, BRANDS), "market": _pick(rng, MARKETS), "state": None,
            "device": _pick(rng, DEVICES), "supplier": _pick(rng, SUPPLIERS),
            "payment_method": _pick(rng, PAYMENTS),
            # PII is never stored raw: hashed id + masked email only.
            "traveler": hashlib.sha256(f"{name}{rng.random()}".encode()).hexdigest()[:10],
            "email": _mask_email(name),
            "schema_ok": True, "reached": 0,
        }
        if j["market"] == "US":
            j["state"] = _pick(rng, US_STATES)
        # Walk the shopping funnel.
        reached = 0
        for idx, stage in enumerate(STAGES[:4]):
            rate = BASE_RATES[stage]
            if stage == "checkout" and self._affects(j, "price_mismatch"):
                rate = 0.30
            if stage == "payment":
                for kind, bad_rate in PAYMENT_INCIDENTS.items():
                    if self._affects(j, kind):
                        rate = min(rate, bad_rate)
            if rng.random() < rate:
                reached = idx + 1
            else:
                break
        if self._affects(j, "tracking_outage"):
            # Tracking is broken: events arrive with missing fields and
            # nothing after search is recorded (travelers are actually fine).
            j["schema_ok"] = False
            j["session_id"] = None
            reached = 0
        j["reached"] = reached
        self.journeys.append(j)

        if reached >= 4 and j["schema_ok"]:
            self._create_order(j, now)
        self.recent_events.append({
            "ts": now, "id": j["id"], "brand": j["brand"], "market": j["market"], "state": j["state"],
            "device": j["device"], "stage": STAGES[reached], "schema_ok": j["schema_ok"],
            "booked": reached >= 4,
        })
        return j

    def _create_order(self, j: dict, now: float) -> None:
        oid = f"ORD-{j['id'][1:]}"
        transient = self.rng.random() < 0.03          # normal, fixable hiccups
        down = self.supplier_down(j["supplier"])
        confirm_at = None if (transient or down) else now + self.rng.uniform(1.0, 3.0)
        j["order_id"] = oid
        self.orders[oid] = {
            "id": oid, "journey": j["id"], "created": now, "supplier": j["supplier"],
            "brand": j["brand"], "market": j["market"], "state": j["state"], "device": j["device"],
            "payment_method": j["payment_method"], "traveler": j["traveler"], "email": j["email"],
            "checkin_hours": self.rng.choice([6, 18, 30, 48, 72, 120, 240]),
            "confirm_at": confirm_at, "status": "pending", "retries": 0,
            "transient": transient, "value_usd": self.rng.randint(120, 900),
        }

    def _advance_orders(self, now: float) -> None:
        for o in self.orders.values():
            if o["status"] == "pending" and o["confirm_at"] and now >= o["confirm_at"]:
                o["status"] = "confirmed"
                o["confirmed_at"] = now

    # ---------- a "tool" other agents may call ----------
    def retry_confirmation(self, order_id: str, now: float) -> bool:
        """Re-send the booking to the supplier. Idempotent: confirmed orders stay confirmed."""
        o = self.orders.get(order_id)
        if not o:
            return False
        if o["status"] == "confirmed":
            return True
        o["retries"] += 1
        if self.supplier_down(o["supplier"]):
            return False
        if self.rng.random() < 0.85:
            o["confirm_at"] = now + 0.5
            return True
        return False
