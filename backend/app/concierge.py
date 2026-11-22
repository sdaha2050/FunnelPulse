"""TravelAssistantAgent ("Ava"): a traveler-facing chat agent for pre-stay, during-stay and post-stay.

It understands the message (intent + details), answers like a person would, and takes
actions through the SAME action router and guardrails as the other agents:
  Tier 1  inform / notify   (create a ticket, tell the hotel)            -> runs automatically
  Tier 2  safe & reversible (hold a room, request early check-in, ...)   -> runs automatically
  Tier 3  money or policy   (refunds, credits, fee waivers)              -> a human approves
  Tier 4  never             (changing prices / free upgrades)            -> blocked
Intent detection is rule-based so the demo works with no API key. Every reply carries a
"brain" trace (intent, confidence, details found, reasoning, actions) for the UI.
"""
from __future__ import annotations

import itertools
import random
import re

from app.bus import Message, MessageBus

_conv_ids = itertools.count(1)

TRAVELER = {"name": "Maya", "full_name": "Maya Patel", "user_id": "U12345", "tier": "Gold member",
            "card": "Visa ending 4417", "email": "m***@example.com"}
TRIP = {"hotel": "Harbor Inns Seattle Waterfront", "supplier": "Harbor Inns", "city": "Seattle",
        "dates": "Dec 12–15", "nights": 3, "nightly": 189, "room": "King room, city view",
        "order_id": "ORD-48210", "flight": "SkyWay Air SW 214 · SFO → SEA · Dec 12, 9:40am",
        "free_cancel_until": "Dec 10", "checkin": "3pm", "checkout": "11am", "room_number": "714"}

SAMPLES = {
    "pre": [
        "Find me a pet-friendly hotel in Paris under $250",
        "Any flights from Seattle to New York next Friday?",
        "Can I check in early on Dec 12? My flight lands at noon",
        "Is breakfast included and is there parking?",
        "The price dropped since I booked. Can you match it?",
        "Can you upgrade me to a suite for free?",
        "I need to cancel my Seattle trip",
    ],
    "during": [
        "The AC in my room isn't working and it's really hot",
        "My room wasn't cleaned and there are no towels",
        "It's very noisy next door, I can't sleep",
        "Can I get a late checkout tomorrow?",
        "I was charged twice for the minibar",
        "I locked myself out of my room",
        "I'd like to stay one more night",
    ],
    "post": [
        "The stay was great, 5 stars! The staff were lovely",
        "Honestly it was disappointing: dirty room and rude front desk. 2 stars",
        "I left my phone charger in room 714",
        "Can you send me the invoice for my company?",
        "My loyalty points from this stay are missing",
        "I paid for breakfast but the restaurant was closed. Can I get a refund?",
    ],
}

PHASE_INTRO = {
    "pre": f"Hi Maya! I'm Ava, your trip assistant. You're all set for {TRIP['hotel']}, {TRIP['dates']}. "
           f"I can help you find hotels or flights, change your booking, or answer questions. What can I do for you?",
    "during": f"Welcome to Seattle, Maya! I hope room {TRIP['room_number']} is treating you well. "
              f"If anything isn't right during your stay, tell me and I'll sort it out with the hotel.",
    "post": f"Hi Maya, thanks for staying at {TRIP['hotel']}! How was your trip? "
            f"I'd love to hear your feedback, and I can help with receipts, lost items or points.",
}

CITIES = ["paris", "london", "new york", "seattle", "tokyo", "rome", "barcelona", "chicago", "miami",
          "san francisco", "los angeles", "denver", "boston", "austin", "vancouver", "lisbon"]
HOTEL_WORDS = ["Riverside", "Garden", "Grand", "Lumen", "Harbor", "Atelier", "Maison", "Skyline", "Old Town", "Parkview"]
HOTEL_KINDS = ["Hotel", "Suites", "Inn", "House", "Residences"]


def _city(text: str) -> str | None:
    t = text.lower()
    for c in CITIES:
        if c in t:
            return c.title()
    m = re.search(r"\bin ([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)?)", text)
    return m.group(1) if m else None


def _money(text: str) -> int | None:
    m = re.search(r"\$\s?(\d{2,5})", text) or re.search(r"under (\d{2,5})", text.lower())
    return int(m.group(1)) if m else None


def _stars(text: str) -> int | None:
    m = re.search(r"([1-5])\s*(?:/\s*5|stars?|★)", text.lower())
    return int(m.group(1)) if m else None


# intent name -> (phases where it fits, keyword patterns)
INTENTS = [
    ("emergency", "*", [r"\bemergenc", r"\bunsafe\b", r"\bfire\b", r"\bmedical\b", r"\bthreat", r"\bhurt\b", r"\bpolice\b", r"need help now"]),
    ("compensation", "during", [r"compensat|refund for (the|my) (night|room)|money back for"]),
    ("wait_ok", "during", [r"i'?ll wait|that'?s fine,? i'?ll|no rush"]),
    ("hk_time", "during", [r"^now,? please|while i'?m out"]),
    ("add_breakfast", "pre", [r"^(yes, )?add breakfast"]),
    ("paid_upgrade", "*", [r"book the paid suite|paid upgrade"]),
    ("human", "*", [r"\bhuman\b", r"\breal person\b", r"\bagent\b.*\btalk|\btalk to (someone|a person)", r"\bmanager\b"]),
    ("upgrade_free", "*", [r"upgrade.*free|free.*upgrade|complimentary upgrade"]),
    ("search_flight", "pre", [r"\bflights? (from|to|between)\b", r"\bany flights\b", r"\bfly (from|to)\b", r"book (me )?a flight"]),
    ("search_hotel", "pre", [r"\b(find|search|looking for|recommend|need)\b.*\b(hotel|stay|place|room)", r"\bhotels? in\b", r"pet[- ]friendly", r"cheaper options"]),
    ("book_option", "pre", [r"\bbook (option|number|#)?\s*\d", r"^option \d", r"\bbook (the )?(first|second|third)"]),
    ("price_match", "pre", [r"price (dropped|drop|went down|is lower)|cheaper (now|elsewhere)|price match|match (it|the price)"]),
    ("cancel", "pre", [r"\bcancel"]),
    ("early_checkin", "pre", [r"early check[- ]?in|check in early|arrive early"]),
    ("change_dates", "pre", [r"change (my )?dates|move (my )?(booking|stay)|different dates"]),
    ("policy", "pre", [r"breakfast|parking|pool|gym|pets?\b|wifi|wi-fi|check[- ]?in time|cancellation policy|included"]),
    ("room_issue", "during", [r"\b(ac|a/c|air ?con|heating|heater|hot water|shower|toilet|tv|broken|not working|doesn'?t work|leak)"]),
    ("housekeeping", "during", [r"not (been )?clean|wasn'?t cleaned|dirty|towels?|housekeeping|sheets"]),
    ("noise", "during", [r"nois|loud|can'?t sleep|party next door"]),
    ("late_checkout", "during", [r"late check[- ]?out|check out late|stay until"]),
    ("billing", "during", [r"charged twice|double charge|overcharg|wrong charge|extra charge|charge.*(minibar|room)"]),
    ("locked_out", "during", [r"locked (myself )?out|lost (my )?key|key card"]),
    ("extend", "during", [r"(one|another|extra) (more )?night|extend (my )?stay|stay longer"]),
    ("lost_item", "post", [r"\bleft (my|a|the)\b|forgot (my|a)|lost (my|a)"]),
    ("invoice", "post", [r"invoice|receipt|bill for|expense"]),
    ("points", "post", [r"points|miles|loyalty"]),
    ("amenity_refund", "post", [r"refund|paid for .* (closed|didn'?t|wasn'?t)|money back"]),
    ("feedback", "post", [r"\bstars?\b|great|amazing|lovely|wonderful|disappoint|terrible|awful|rude|loved|bad stay|\d/5"]),
    ("yes", "*", [r"^(yes|yep|yeah|sure|please do|go ahead|ok|okay|confirm|do it|move me|move it|add the note)\b"]),
    ("no", "*", [r"^(no|nope|not now|cancel that|never mind)\b"]),
    ("thanks", "*", [r"\bthank", r"\bthx\b", r"\bappreciate"]),
    ("greet", "*", [r"^(hi|hello|hey|good (morning|evening))\b"]),
]


def detect(text: str, phase: str) -> tuple[str, float, list[str]]:
    """Return (intent, confidence, matched keywords). Prefers intents that fit the current phase."""
    t = text.lower().strip()
    best, score, hits = "unknown", 0.0, []
    for name, phases, pats in INTENTS:
        found = [m.group(0) for p in pats if (m := re.search(p, t))]
        if not found:
            continue
        s = 0.6 + 0.15 * min(len(found), 2) + (0.1 if phases == phase else 0.0 if phases == "*" else -0.25)
        if s > score:
            best, score, hits = name, s, found
    return best, round(min(score, 0.98), 2), hits


class TravelAssistant:
    name = "TravelAssistantAgent"

    def __init__(self, bus: MessageBus, router):
        self.bus, self.router = bus, router
        self.convs: dict[str, dict] = {}
        bus.subscribe("human.decision", self.on_human_decision)

    # ---------- conversations ----------
    def new(self, phase: str = "pre") -> dict:
        cid = f"C{next(_conv_ids)}"
        c = {"id": cid, "phase": phase, "messages": [], "pending": None, "last_options": None,
             "rng": random.Random(cid), "n": 0, "trip": dict(TRIP), "booked": []}
        self._say(c, PHASE_INTRO[phase], brain={"intent": "welcome", "confidence": 1.0, "slots": {},
                                                "reasoning": [f"New conversation in the {self._phase_name(phase)} phase."],
                                                "actions": []},
                  quick=SAMPLES[phase][:3])
        self.convs[cid] = c
        while len(self.convs) > 200:
            self.convs.pop(next(iter(self.convs)))
        return c

    def set_phase(self, c: dict, phase: str) -> None:
        c["phase"], c["pending"], c["last_options"] = phase, None, None
        self._say(c, PHASE_INTRO[phase], brain={"intent": "phase_change", "confidence": 1.0, "slots": {},
                                                "reasoning": [f"Switched to {self._phase_name(phase)}."], "actions": []},
                  quick=SAMPLES[phase][:3])

    @staticmethod
    def _phase_name(p: str) -> str:
        return {"pre": "pre-stay", "during": "during-stay", "post": "post-stay"}[p]

    def view(self, c: dict) -> dict:
        return {"id": c["id"], "phase": c["phase"], "traveler": TRAVELER, "trip": c["trip"],
                "messages": c["messages"], "samples": SAMPLES}

    def _say(self, c, text, brain=None, cards=None, quick=None):
        c["messages"].append({"id": len(c["messages"]) + 1, "role": "agent", "text": text, "cards": cards or [],
                              "quick": quick or [], "brain": brain})

    # ---------- actions go through the shared router + guardrails ----------
    def _act(self, c, type_, tier, title, why, owner="Hotel front desk", severity="Sev 3", amount=None) -> dict:
        c["n"] += 1
        a = self.router._action(type_, tier, title, owner, [f"Traveler {TRAVELER['user_id']} in chat {c['id']}: {why}"],
                                f"chat:{c['id']}:{c['n']}", severity, why,
                                f"${amount}" if amount else "", source="assistant")
        a["conv_id"] = c["id"]
        decision = self.router.submit(a)
        self.bus.publish(self.name, "assistant.action", {"conv": c["id"], "type": type_},
                         f"{TRAVELER['name']} (chat {c['id']}): {title} → "
                         f"{ {'allow': 'done', 'needs_human': 'sent to a human', 'block': 'BLOCKED'}.get(decision['decision'], decision['decision']) }",
                         to="Human agent" if decision["decision"] == "needs_human" else "ActionRouterAgent")
        return {"id": a["id"], "type": type_, "tier": tier, "title": title, "decision": decision["decision"],
                "rule": decision.get("rule"), "reason": decision.get("reason", "")}

    def on_human_decision(self, msg: Message) -> None:
        ap = msg.payload
        c = self.convs.get(ap.get("conv_id") or "")
        if not c:
            return
        n = TRAVELER["name"]
        if ap["status"] == "approved":
            text = f"Good news, {n}: a member of our team approved it. {ap['result']['detail']}. It should show up within 3–5 business days."
        else:
            text = (f"{n}, I'm sorry: our team reviewed your request and couldn't approve it this time"
                    + (f" ({ap['note']})" if ap.get("note") else "") + ". I've added a note to your account, and "
                    "you can reply here if you'd like a person to call you.")
        self._say(c, text, brain={"intent": "human_decision", "confidence": 1.0, "slots": {},
                                  "reasoning": [f"A human {ap['status']} '{ap['title']}' in the Needs a human queue.",
                                                "The assistant tells the traveler right away, in the same chat."],
                                  "actions": []})

    # ---------- the turn ----------
    def handle(self, c: dict, text: str) -> list[dict]:
        before = len(c["messages"])
        c["messages"].append({"id": before + 1, "role": "user", "text": text})
        intent, conf, hits = detect(text, c["phase"])
        brain = {"intent": intent, "confidence": conf, "slots": {}, "reasoning": [], "actions": []}
        if hits:
            brain["reasoning"].append(f"Matched: {', '.join(repr(h) for h in hits[:3])}.")
        # A yes/no answers the question we asked last.
        if intent in ("yes", "no") and c["pending"]:
            self._confirm(c, intent == "yes", brain)
        else:
            getattr(self, f"_i_{intent}", self._i_unknown)(c, text, brain)
        return c["messages"][before + 1:]

    def _pick(self, c, *options):
        return c["rng"].choice(options)

    # ----- general -----
    def _i_greet(self, c, text, brain):
        brain["reasoning"].append("A greeting: answer warmly and offer the most useful next steps for this phase.")
        self._say(c, f"Hi {TRAVELER['name']}! What can I help you with?", brain, quick=SAMPLES[c["phase"]][:3])

    def _i_thanks(self, c, text, brain):
        brain["reasoning"].append("Thanks: close the loop and leave the door open.")
        self._say(c, self._pick(c, f"Anytime, {TRAVELER['name']}! I'm here if you need anything else.",
                                "You're welcome! Enjoy your trip.", "Happy to help. Just message me if anything comes up."), brain)

    def _i_unknown(self, c, text, brain):
        brain["reasoning"].append("No intent matched with enough confidence, so ask rather than guess.")
        self._say(c, f"I want to get this right, {TRAVELER['name']}. Could you tell me a bit more? Here are some things I can do:",
                  brain, quick=SAMPLES[c["phase"]][:4] + ["Talk to a person"])

    def _i_human(self, c, text, brain):
        a = self._act(c, "notify", 1, "Traveler asked for a human agent", "Traveler requested a person",
                      owner="Customer care", severity="Sev 3")
        brain["actions"].append(a)
        brain["reasoning"].append("The traveler asked for a person. Always honor that: hand off with the full chat history.")
        self._say(c, f"Of course. I've passed this conversation to a member of our care team, with everything we've discussed "
                     f"so you won't have to repeat yourself. Typical wait right now is about 4 minutes.", brain)

    def _i_emergency(self, c, text, brain):
        a = self._act(c, "notify", 1, "SAFETY: traveler reports an emergency", "Possible safety emergency",
                      owner="Safety team + hotel duty manager", severity="Sev 1")
        brain["actions"].append(a)
        brain["reasoning"] += ["Safety comes first: give emergency guidance immediately, no troubleshooting.",
                               "Page the safety team (Sev 1) and the hotel's duty manager at the same time."]
        self._say(c, "If you're in danger or anyone is hurt, please call 911 now (or dial 0 for the front desk). "
                     "I've alerted our safety team and the hotel's duty manager, and someone will call you within minutes. "
                     "Are you somewhere safe right now?", brain, quick=["Yes, I'm safe", "I need help now"])

    def _i_upgrade_free(self, c, text, brain):
        a = self._act(c, "change_price", 4, "Give a free suite upgrade (change the room rate to $0 extra)",
                      "Traveler asked for a free upgrade")
        brain["actions"].append(a)
        brain["reasoning"] += ["A free upgrade means changing a rate: that is Tier 4, so the guardrails block it.",
                               "Offer what is allowed instead: a paid upgrade at the published price, or a note to the hotel."]
        self._say(c, f"I'd love to, {TRAVELER['name']}, but I'm not able to change room rates myself. What I can do: "
                     f"the suite is available for $65 more per night, or I can add a note asking the hotel to upgrade you "
                     f"if one is free at check-in (as a {TRAVELER['tier']}, you're near the top of their list).",
                  brain, quick=["Add the note to the hotel", "Book the paid suite", "No thanks"])
        c["pending"] = {"kind": "upgrade_note"}

    # ----- pre-stay -----
    def _i_search_hotel(self, c, text, brain):
        last = c.get("last_options") if c.get("last_options") and c["last_options"]["kind"] == "hotel" else None
        city = _city(text) or (last["city"] if last else c["trip"]["city"])
        budget = _money(text)
        if "cheaper" in text.lower() and last:
            budget = int(min(i["price"] for i in last["items"]) * 0.9)
        pets = bool(re.search(r"pet|dog|cat", text.lower()))
        brain["slots"] = {"city": city, "max_price": budget, "pet_friendly": pets}
        brain["reasoning"].append(f"Search hotels in {city}" + (f" under ${budget}/night" if budget else "")
                                  + (", pet-friendly only" if pets else "") + ".")
        r = random.Random(f"{city}{budget}{pets}")
        hi = budget or 320
        opts = []
        for i in range(3):
            price = r.randint(max(90, int(hi * 0.55)), hi - 5)
            opts.append({"kind": "hotel", "n": i + 1,
                         "name": f"{r.choice(HOTEL_WORDS)} {r.choice(HOTEL_KINDS)} {city}",
                         "area": r.choice(["City centre", "Old town", "Near the river", "Arts district", "By the station"]),
                         "price": price, "rating": round(r.uniform(4.1, 4.8), 1),
                         "perks": [p for p in (["Pets welcome"] if pets else []) + r.sample(
                             ["Free breakfast", "Free cancellation", "Pool", "Gym", "Free Wi-Fi", "Late checkout"], 2)]})
        opts.sort(key=lambda o: -o["rating"])
        for i, o in enumerate(opts):
            o["n"] = i + 1
        c["last_options"] = {"kind": "hotel", "city": city, "items": opts}
        brain["reasoning"].append("Rank by guest rating, show 3 options, and let the traveler book in one tap.")
        self._say(c, f"Here are three great options in {city}" + (f" under ${budget}" if budget else "")
                  + (" that welcome pets" if pets else "") + ". Want me to book one?", brain, cards=opts,
                  quick=[f"Book option {o['n']}" for o in opts] + ["Show cheaper options"])

    def _i_search_flight(self, c, text, brain):
        m = re.search(r"from ([A-Za-z ]+?) to ([A-Za-z ]+?)(?: on| next| this|\?|$)", text, re.I)
        a, b = (m.group(1).strip().title(), m.group(2).strip().title()) if m else ("Seattle", "New York")
        brain["slots"] = {"from": a, "to": b, "date": "next Friday" if "friday" in text.lower() else "your date"}
        brain["reasoning"].append(f"Search flights {a} → {b}; show nonstop first, then cheapest.")
        r = random.Random(a + b)
        opts = []
        for i, (dep, dur) in enumerate([("7:05am", "5h 20m"), ("11:40am", "5h 35m"), ("4:15pm", "6h 50m · 1 stop")]):
            opts.append({"kind": "flight", "n": i + 1, "name": f"SkyWay Air SW {r.randint(100, 999)}",
                         "area": f"{a} → {b} · departs {dep} · {dur}", "price": r.randint(180, 420),
                         "rating": None, "perks": ["Carry-on included"] + (["Wi-Fi"] if i < 2 else [])})
        c["last_options"] = {"kind": "flight", "city": b, "items": opts}
        self._say(c, f"I found these flights from {a} to {b}. The morning nonstop is usually the most reliable. Shall I hold one?",
                  brain, cards=opts, quick=[f"Book option {o['n']}" for o in opts])

    def _i_book_option(self, c, text, brain):
        m = re.search(r"(\d)", text) or None
        words = {"first": 1, "second": 2, "third": 3}
        n = int(m.group(1)) if m else next((v for k, v in words.items() if k in text.lower()), 1)
        opts = c.get("last_options")
        if not opts or not 1 <= n <= len(opts["items"]):
            brain["reasoning"].append("Asked to book, but there are no options on screen yet: search first.")
            self._say(c, "Happy to book something! Which city and dates are you thinking of?", brain,
                      quick=["Find me a hotel in Paris", "Flights from Seattle to New York"])
            return
        o = opts["items"][n - 1]
        nights = 3 if opts["kind"] == "hotel" else 1
        total = o["price"] * nights
        brain["slots"] = {"option": n, "name": o["name"], "total": total}
        brain["reasoning"] += ["Booking charges the traveler's card, so confirm the exact item and total first.",
                               "After a clear 'yes' from the traveler, booking runs automatically (Tier 2, customer-confirmed)."]
        c["pending"] = {"kind": "book", "item": o, "total": total, "type": opts["kind"]}
        what = f"{o['name']} for 3 nights (${o['price']}/night)" if opts["kind"] == "hotel" else f"{o['name']}, {o['area']}"
        self._say(c, f"Great choice! Just to confirm: {what}, total ${total}, charged to your {TRAVELER['card']}. Shall I book it?",
                  brain, quick=["Yes, book it", "No, not yet"])

    def _i_policy(self, c, text, brain):
        t = text.lower()
        answers = []
        if "breakfast" in t:
            answers.append("Breakfast isn't included in your rate, but you can add it for $22 per person per day")
        if "parking" in t:
            answers.append("there's valet parking at $45/night (self-parking nearby is about $30)")
        if "pet" in t or "dog" in t:
            answers.append("pets up to 40 lb are welcome for a $50 one-time fee")
        if "pool" in t or "gym" in t:
            answers.append("the gym is open 24/7 and the rooftop pool runs 7am–10pm")
        if "wifi" in t or "wi-fi" in t:
            answers.append("Wi-Fi is free for all guests")
        if "cancel" in t:
            answers.append(f"you can cancel for free until {c['trip']['free_cancel_until']}")
        if "check" in t:
            answers.append(f"check-in is from {c['trip']['checkin']} and checkout by {c['trip']['checkout']}")
        if not answers:
            answers.append("everything you booked is on your itinerary, and I'm happy to check any detail with the hotel")
        brain["reasoning"].append("A factual question about the hotel: answer from the property's policy data, no action needed.")
        txt = "; ".join(answers)
        self._say(c, f"Good questions! At {c['trip']['hotel']}: {txt[0].upper() + txt[1:]}. Would you like me to add breakfast?",
                  brain, quick=["Yes, add breakfast", "No thanks"])
        c["pending"] = {"kind": "add_breakfast"}

    def _i_early_checkin(self, c, text, brain):
        a = self._act(c, "request_early_checkin", 2, f"Request early check-in at {c['trip']['hotel']} (arrival ~1pm, Dec 12)",
                      "Traveler's flight lands at noon")
        brain["actions"].append(a)
        brain["reasoning"] += ["Asking the hotel is free and reversible (Tier 2), so do it right away.",
                               "Be honest: early check-in is never guaranteed; offer luggage storage as a fallback."]
        self._say(c, f"Done! I've asked the hotel for early check-in around 1pm on Dec 12 and flagged that you're a "
                     f"{TRAVELER['tier']}. It isn't guaranteed, but they'll do their best, and you can always leave your bags "
                     f"at the front desk and explore. I'll message you as soon as they reply.", brain)

    def _i_change_dates(self, c, text, brain):
        brain["reasoning"] += ["Changing dates may change the price: check availability, then confirm the difference."]
        c["pending"] = {"kind": "change_dates", "diff": 40}
        self._say(c, "I can do that. The hotel has your room for Dec 13–16, and it's $40 more in total because Saturday "
                     "nights cost a bit more. Shall I move your booking?", brain, quick=["Yes, move it", "No, keep my dates"])

    def _i_price_match(self, c, text, brain):
        a = self._act(c, "price_match_credit", 3, f"Price-match credit $54 for {c['trip']['order_id']} (rate dropped $18/night)",
                      "Same room is now $18/night cheaper than the traveler paid", owner="Service ops", amount=54)
        brain["actions"].append(a)
        brain["reasoning"] += ["The rate dropped $18/night × 3 nights = $54.",
                               "A credit moves money, so it's Tier 3: a human approves before it's applied."]
        self._say(c, f"Nice catch, {TRAVELER['name']}! The same room is $18 a night cheaper now, so you'd get $54 back. "
                     f"I've sent the price-match request to our team for a quick approval, and I'll let you know here "
                     f"as soon as it's done.", brain)

    def _i_cancel(self, c, text, brain):
        total = c["trip"]["nightly"] * c["trip"]["nights"]
        brain["reasoning"] += [f"The booking is still in the free-cancellation window (until {c['trip']['free_cancel_until']}).",
                               "Cancelling within policy is a standard, customer-confirmed action, but confirm first: it can't be undone."]
        c["pending"] = {"kind": "cancel", "total": total}
        self._say(c, f"I'm sorry your plans changed. Good news: you're still within free cancellation, so you'd get the full ${total} "
                     f"back to your {TRAVELER['card']}. Would you like me to cancel {c['trip']['hotel']} for {c['trip']['dates']}?",
                  brain, quick=["Yes, cancel it", "No, keep it"])

    # ----- during the stay -----
    def _i_room_issue(self, c, text, brain):
        what = "AC" if re.search(r"\bac\b|a/c|air ?con", text.lower()) else "issue"
        a1 = self._act(c, "create_ticket", 1, f"Maintenance ticket: {what} in room {c['trip']['room_number']}",
                       f"Traveler reports: {text[:80]}", owner="Hotel maintenance", severity="Sev 2")
        brain["actions"].append(a1)
        brain["reasoning"] += ["Comfort problem during the stay: fix fast. Open a maintenance ticket (Tier 1) immediately.",
                               "Offer a room move as a backup (safe, same rate, Tier 2) and ask what the traveler prefers."]
        self._say(c, f"Oh no, I'm so sorry, {TRAVELER['name']}. That's no way to spend your evening. I've sent maintenance to room "
                     f"{c['trip']['room_number']} (they're usually there within 20 minutes). If you'd rather not wait, I can move "
                     f"you to another room right now at no extra cost. What would you prefer?",
                  brain, quick=["Move me to another room", "I'll wait for maintenance", "I'd like compensation"])
        c["pending"] = {"kind": "room_move"}

    def _i_housekeeping(self, c, text, brain):
        a = self._act(c, "housekeeping_request", 2, f"Housekeeping to room {c['trip']['room_number']}: full clean + fresh towels",
                      f"Traveler reports: {text[:80]}", owner="Hotel housekeeping")
        brain["actions"].append(a)
        brain["reasoning"].append("Housekeeping is routine and reversible (Tier 2): send it now and give an ETA.")
        self._say(c, f"I'm sorry about that! Housekeeping is on the way with fresh towels and will clean the room within 30 minutes. "
                     f"Would you like them to come now, or while you're out?", brain, quick=["Now, please", "While I'm out"])

    def _i_noise(self, c, text, brain):
        a = self._act(c, "create_ticket", 1, f"Noise complaint near room {c['trip']['room_number']}",
                      "Traveler can't sleep due to noise", owner="Hotel night manager", severity="Sev 2")
        brain["actions"].append(a)
        brain["reasoning"] += ["Ask the night manager to handle the noise (Tier 1) and offer a quieter room (Tier 2)."]
        c["pending"] = {"kind": "room_move"}
        self._say(c, f"That's frustrating, especially when you need to rest. I've asked the night manager to deal with the noise "
                     f"right away. I can also move you to a quieter room on a higher floor. Want me to do that?",
                  brain, quick=["Yes, move me", "No, I'll stay"])

    def _i_late_checkout(self, c, text, brain):
        a = self._act(c, "request_late_checkout", 2, "Late checkout until 1pm for room 714 (Gold member benefit)",
                      "Traveler asked for late checkout")
        brain["actions"].append(a)
        brain["reasoning"].append("Gold members get late checkout until 1pm free: within policy, so it's automatic (Tier 2).")
        self._say(c, f"You've got it: late checkout until 1pm tomorrow, free as a {TRAVELER['tier']}. "
                     f"If you need longer, the hotel can do 3pm for $40. Enjoy your morning!", brain)

    def _i_billing(self, c, text, brain):
        a = self._act(c, "refund", 3, "Refund duplicate minibar charge $38 on room 714",
                      "Minibar charge $38 posted twice on the folio", owner="Hotel billing + Service ops", amount=38)
        brain["actions"].append(a)
        brain["reasoning"] += ["Checked the folio: the $38 minibar charge appears twice.",
                               "Refunds move money, so it's Tier 3: a human approves."]
        self._say(c, f"Thanks for flagging it, {TRAVELER['name']}. I checked your bill and you're right: the $38 minibar charge "
                     f"was added twice. I've sent a refund request for $38 to our team for approval, and I'll confirm here as soon as "
                     f"it's done. Nothing else on the bill looks off.", brain)

    def _i_locked_out(self, c, text, brain):
        a = self._act(c, "notify", 1, "Guest locked out of room 714: new key at front desk",
                      "Traveler locked out", owner="Hotel front desk", severity="Sev 2")
        brain["actions"].append(a)
        brain["reasoning"].append("Urgent but simple: alert the front desk (Tier 1). For security they'll check ID before a new key.")
        self._say(c, "No worries, it happens! The front desk has a new key ready for you. For your security they'll ask for "
                     "your ID. If you can't get downstairs, tell me and they'll send someone up.", brain)

    def _i_extend(self, c, text, brain):
        c["pending"] = {"kind": "extend", "price": 199}
        brain["reasoning"].append("Check availability for one more night, then confirm the price before charging.")
        self._say(c, "Great news: your room is free for another night (Dec 15–16) at $199. Shall I extend your stay "
                     "so you don't have to move rooms?", brain, quick=["Yes, extend it", "No thanks"])

    # ----- after the stay -----
    def _i_feedback(self, c, text, brain):
        stars = _stars(text)
        neg = bool(re.search(r"disappoint|terrible|awful|rude|dirty|bad|worst|never again", text.lower()))
        if stars is None:
            stars = 2 if neg else 5
        brain["slots"] = {"rating": stars, "sentiment": "negative" if stars <= 3 else "positive"}
        if stars >= 4:
            a = self._act(c, "add_loyalty_points", 2, "Add 500 thank-you points for a review", "Positive review submitted")
            brain["actions"].append(a)
            brain["reasoning"] += [f"{stars} stars, positive: thank them, share it with the hotel, add review points (Tier 2)."]
            self._say(c, f"That makes my day, {TRAVELER['name']}! Thank you. I've shared your kind words with the team at "
                         f"{c['trip']['hotel']} and added 500 points to your account as a thank-you. Would you like me to save "
                         f"this hotel for your next trip to Seattle?", brain, quick=["Yes, save it", "No thanks"])
        else:
            a1 = self._act(c, "create_ticket", 1, f"Guest complaint ({stars}★): cleanliness and front desk",
                           f"Review: {text[:80]}", owner="Hotel general manager", severity="Sev 2")
            a2 = self._act(c, "goodwill_credit", 3, "Goodwill credit $75 for a poor stay", "Low rating with specific complaints",
                           owner="Service ops", amount=75)
            brain["actions"] += [a1, a2]
            brain["reasoning"] += [f"{stars} stars, negative: apologize sincerely, send the details to the hotel's GM (Tier 1).",
                                   "Offer a goodwill credit: it costs money, so a human approves it (Tier 3)."]
            self._say(c, f"I'm really sorry, {TRAVELER['name']}. A dirty room and an unfriendly welcome isn't what you deserved. "
                         f"I've sent your feedback straight to the hotel's general manager, and I've asked our team to approve a "
                         f"$75 credit for your next trip. I'll let you know here once it's on your account.", brain)

    def _i_lost_item(self, c, text, brain):
        a = self._act(c, "create_ticket", 1, f"Lost & found: item left in room {c['trip']['room_number']}",
                      f"Traveler: {text[:80]}", owner="Hotel lost & found")
        brain["actions"].append(a)
        brain["reasoning"].append("Open a lost-and-found request with the hotel (Tier 1) and explain the next steps.")
        self._say(c, "I've asked the hotel's lost and found to check room 714. If they have it, they can post it to you "
                     "(about $12 shipping) or hold it for 30 days. I'll update you as soon as they reply.", brain)

    def _i_invoice(self, c, text, brain):
        a = self._act(c, "send_invoice", 2, f"Email itemized invoice for {c['trip']['order_id']}", "Traveler needs an invoice")
        brain["actions"].append(a)
        brain["reasoning"].append("Sending an invoice is safe and instant (Tier 2).")
        self._say(c, f"Done! I've emailed an itemized invoice to {TRAVELER['email']}. Need your company's name or VAT number on it? "
                     f"Just tell me and I'll reissue it.", brain)

    def _i_points(self, c, text, brain):
        a = self._act(c, "add_loyalty_points", 2, f"Credit 1,134 missing points for {c['trip']['order_id']}",
                      "Points for a completed stay were not posted")
        brain["actions"].append(a)
        brain["reasoning"].append("Missing points for a completed stay: posting what was earned is routine (Tier 2).")
        self._say(c, "Sorry about that! You earned 1,134 points for this stay and they hadn't posted yet. I've added them now. "
                     "They'll show in your account within the hour.", brain)

    def _i_amenity_refund(self, c, text, brain):
        a = self._act(c, "refund", 3, "Refund unused breakfast $66 (restaurant closed)", "Paid breakfast not available",
                      owner="Service ops", amount=66)
        brain["actions"].append(a)
        brain["reasoning"] += ["The traveler paid for something they couldn't use: a refund is fair.",
                               "Refunds are Tier 3: a human approves."]
        self._say(c, "That's not right, and I'm sorry. You paid $66 for breakfast you couldn't have. I've sent a refund request "
                     "to our team, and I'll confirm here as soon as it's approved.", brain)

    def _i_yes(self, c, text, brain):
        brain["reasoning"].append("A 'yes' with no open question: acknowledge and move on.")
        self._say(c, self._pick(c, "Done! Anything else I can help with?", "Perfect, all set. What else can I do for you?"), brain)

    def _i_no(self, c, text, brain):
        brain["reasoning"].append("A 'no' with no open question: offer help without pushing.")
        self._say(c, "No problem! I'm here if you need anything.", brain)

    def _i_wait_ok(self, c, text, brain):
        c["pending"] = None
        brain["reasoning"].append("The traveler prefers to wait: confirm the ETA and promise a follow-up.")
        self._say(c, "Sounds good. Maintenance is on the way (about 20 minutes). I'll check back with you in 30 minutes to make "
                     "sure it's fixed. Meanwhile there's a fan available at the front desk if you'd like one.", brain)

    def _i_hk_time(self, c, text, brain):
        brain["reasoning"].append("Pass the traveler's preferred time to housekeeping.")
        self._say(c, "Got it, I've let housekeeping know. Fresh towels are coming first.", brain)

    def _i_add_breakfast(self, c, text, brain):
        c["pending"] = {"kind": "add_breakfast"}
        self._confirm(c, True, brain)

    def _i_paid_upgrade(self, c, text, brain):
        c["pending"] = None
        a = self._act(c, "modify_booking", 2, "Upgrade to suite at the published rate (+$65/night × 3)",
                      "Traveler chose the paid upgrade at the published price", owner="Booking service")
        brain["actions"].append(a)
        brain["reasoning"].append("A paid upgrade at the published price changes no rates: customer-confirmed Tier 2.")
        self._say(c, "Done! You're upgraded to the suite for $65 more per night ($195 total). Enjoy the view!", brain)

    def _i_compensation(self, c, text, brain):
        c["pending"] = None
        a = self._act(c, "goodwill_credit", 3, "Goodwill credit: 50% off tonight ($95) for broken AC in room 714",
                      "AC failed during the stay; maintenance ticket open", owner="Service ops", amount=95)
        brain["actions"].append(a)
        brain["reasoning"] += ["A fair gesture for a broken AC is about half a night ($95).",
                               "Compensation costs money, so it's Tier 3: a human approves."]
        self._say(c, f"Completely fair, {TRAVELER['name']}. I've asked our team to approve 50% off tonight ($95) because of the AC. "
                     f"I'll confirm here as soon as it's approved, usually within a few minutes.", brain)

    # ----- confirmations -----
    def _confirm(self, c, yes: bool, brain):
        p, c["pending"] = c["pending"], None
        brain["intent"] = f"confirm_{p['kind']}" if yes else f"decline_{p['kind']}"
        if not yes:
            brain["reasoning"].append("The traveler said no: do nothing and offer alternatives.")
            self._say(c, "No problem at all. Is there anything else I can help with?", brain, quick=SAMPLES[c["phase"]][:3])
            return
        brain["reasoning"].append("The traveler confirmed, so the action can run.")
        if p["kind"] == "book":
            o = p["item"]
            a = self._act(c, "create_booking", 2, f"Book {o['name']} · ${p['total']} on {TRAVELER['card']}",
                          "Traveler confirmed item and total in chat", owner="Booking service")
            brain["actions"].append(a)
            oid = f"ORD-{random.Random(o['name']).randint(60000, 69999)}"
            c["booked"].append(oid)
            self._say(c, f"You're booked! 🎉 {o['name']}, confirmation {oid}. I've emailed your itinerary to {TRAVELER['email']}. "
                         f"Anything else for this trip, like airport transfer or breakfast?", brain,
                      quick=["Add breakfast", "No, that's all"])
        elif p["kind"] == "cancel":
            a = self._act(c, "cancel_booking", 2, f"Cancel {c['trip']['order_id']} within free cancellation · refund ${p['total']}",
                          f"Within free-cancellation window (until {c['trip']['free_cancel_until']})", owner="Booking service")
            brain["actions"].append(a)
            brain["reasoning"].append("Within policy, so the full refund is automatic. A refund outside policy would need a human.")
            self._say(c, f"All done. Your booking is cancelled and ${p['total']} is on its way back to your {TRAVELER['card']} "
                         f"(3–5 business days). I hope we can help you plan the next one!", brain)
        elif p["kind"] == "room_move":
            a = self._act(c, "room_move", 2, "Move guest from room 714 to 1108 (same type, same rate)",
                          "Traveler accepted a room move", owner="Hotel front desk")
            brain["actions"].append(a)
            self._say(c, "Done! Room 1108 is ready for you: same room type, a quieter floor, and the AC works perfectly. "
                         "Your new key is at the front desk and a porter can help with bags. I'm sorry again for the trouble.", brain)
        elif p["kind"] == "change_dates":
            a = self._act(c, "modify_booking", 2, f"Move {c['trip']['order_id']} to Dec 13–16 (+$40)",
                          "Traveler confirmed new dates and price difference", owner="Booking service")
            brain["actions"].append(a)
            c["trip"]["dates"] = "Dec 13–16"
            self._say(c, "All set! Your stay is now Dec 13–16, and the $40 difference was charged to your card. "
                         "Want me to check if your flight should move too?", brain, quick=["Yes, check my flight", "No thanks"])
        elif p["kind"] == "extend":
            a = self._act(c, "modify_booking", 2, f"Extend stay by one night (Dec 15–16) · $199",
                          "Traveler confirmed extension and price", owner="Booking service")
            brain["actions"].append(a)
            self._say(c, "Done: you're staying through Dec 16 in the same room, so no packing tonight! Enjoy the extra day.", brain)
        elif p["kind"] == "add_breakfast":
            a = self._act(c, "modify_booking", 2, "Add breakfast for 1 guest × 3 days ($66)", "Traveler asked to add breakfast",
                          owner="Booking service")
            brain["actions"].append(a)
            self._say(c, "Breakfast is added for all 3 mornings ($66). It's served 6:30–10:30am on the ground floor.", brain)
        elif p["kind"] == "upgrade_note":
            a = self._act(c, "create_ticket", 1, "Note to hotel: guest would love an upgrade if available at check-in",
                          "Traveler interested in an upgrade", owner="Hotel front desk")
            brain["actions"].append(a)
            self._say(c, "Done! I've added a note for the front desk. Fingers crossed!", brain)
        else:
            self._say(c, "Done!", brain)
