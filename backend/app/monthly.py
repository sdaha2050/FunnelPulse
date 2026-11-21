"""Monthly dashboard: 12 months of SIMULATED history plus the top issues behind drops.

The live demo only keeps the last minute of data in memory, so this module
generates a believable year of history (deterministic, seeded) to show what a
monthly business review would look like. Every number here is fake.
"""
from __future__ import annotations

import random
from datetime import date

AVG_BOOKING_USD = 310          # average booking value used to price lost bookings
STAGES = ["Search", "Detail", "Checkout", "Payment", "Booked", "Supplier confirmed"]
# Normal share of travelers moving to the next stage (before known issues).
BASE = {"Detail": 0.48, "Checkout": 0.42, "Payment": 0.80, "Booked": 0.95, "Supplier confirmed": 0.995}

# Seasonality: travel searches peak in summer and around the holidays.
SEASON = {1: 0.82, 2: 0.86, 3: 0.98, 4: 1.0, 5: 1.08, 6: 1.18, 7: 1.22, 8: 1.12,
          9: 0.95, 10: 0.97, 11: 1.0, 12: 1.06}

# The top issues. `share` = fraction of travelers at that stage who are lost to
# this issue in a typical month; `shape` changes it month by month (index 0 =
# oldest month). Root cause + evidence describe what the agents found.
ISSUES = [
    {"id": "fees", "title": "Taxes and resort fees appear only at checkout", "stage": "Checkout",
     "root_cause": "Search and property pages show the nightly rate without mandatory taxes and resort fees; "
                   "the total jumps by 15-25% on the checkout page.",
     "evidence": "Most checkout exits happen within 10 seconds of the fee line appearing; worst on resort properties.",
     "found_by": "FunnelMonitor + RootCauseAgent (segment: properties with resort fees)",
     "owner": "Checkout PM", "fix": "Show the all-in total price on search and property pages",
     "status": "Fix rolling out", "share": 0.060,
     "shape": [1, 1, 1, 1.05, 1.1, 1.15, 1.15, 1.1, 1, 0.8, 0.65, 0.55]},
    {"id": "declines", "title": "Card payments declined by the bank", "stage": "Payment",
     "root_cause": "3-D Secure (bank verification) challenges fail or time out, mostly for EU and UK cards, "
                   "and some issuers decline cross-border travel payments.",
     "evidence": "Declines cluster by issuer and country; same cards succeed on retry with another processor.",
     "found_by": "RootCauseAgent (segment: issuer country + payment method)",
     "owner": "Payments team", "fix": "Smart routing to a second processor and frictionless 3-D Secure",
     "status": "In progress", "share": 0.055,
     "shape": [1, 1, 0.95, 1, 1.05, 1.2, 1.25, 1.15, 1.05, 1, 1, 0.95]},
    {"id": "soldout", "title": "\"No longer available\" when booking", "stage": "Booked",
     "root_cause": "Availability is served from a cache that refreshes every 30 minutes; at peak the supplier "
                   "sells the last rooms before the cache updates.",
     "evidence": "Failures rise with demand and are concentrated on suppliers with low remaining inventory.",
     "found_by": "ReservationIntegrityAgent + RootCauseAgent (segment: supplier, peak dates)",
     "owner": "Supply / Inventory eng", "fix": "Live availability check when checkout starts; shorter cache on hot dates",
     "status": "Planned", "share": 0.030,
     "shape": [0.8, 0.85, 0.95, 1, 1.15, 1.35, 1.45, 1.3, 1, 0.95, 1, 1.05]},
    {"id": "pricechange", "title": "Price changes between property page and checkout", "stage": "Checkout",
     "root_cause": "The property page uses a cached rate; checkout re-prices with the live supplier rate, "
                   "so travelers see a \"price changed\" message.",
     "evidence": "Exits spike right after the price-change pop-up; gap is largest for channel-manager suppliers.",
     "found_by": "FunnelMonitor (checkout exits) + RootCauseAgent (segment: connectivity type)",
     "owner": "Pricing / Rates eng", "fix": "Refresh the rate when the property page loads; hold price for 15 minutes",
     "status": "In progress", "share": 0.022,
     "shape": [1, 1, 1, 1.05, 1.1, 1.2, 1.2, 1.1, 1, 1, 0.95, 0.9]},
    {"id": "android_form", "title": "Android checkout form rejects valid details", "stage": "Checkout",
     "root_cause": "Phone and postcode validation only accepts US formats; international travelers on the "
                   "Android app cannot submit the form.",
     "evidence": "Form-error rate is 4x higher on Android for non-US travelers; started with app release 26.8.",
     "found_by": "RootCauseAgent (segment: device = Android app, market = non-US)",
     "owner": "Mobile app team", "fix": "Hotfix validation rules; add form-error monitoring to release checks",
     "status": "Fixed (Oct)", "share": 0.018,
     "shape": [0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 0.2, 1.6, 1.8, 0.4, 0.2]},
    {"id": "signin", "title": "Forced sign-in before checkout", "stage": "Checkout",
     "root_cause": "An A/B test turned off guest checkout for 50% of traffic; many first-time travelers "
                   "abandon at the sign-in wall.",
     "evidence": "Drop exists only in the test variant and only for new travelers.",
     "found_by": "FunnelMonitor + experiment guardrail check",
     "owner": "Growth / Loyalty PM", "fix": "Stop the variant; offer sign-in after booking instead",
     "status": "Experiment stopped", "share": 0.016,
     "shape": [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 1.8, 2.0, 1.6, 0.3, 0.1]},
    {"id": "supplier_timeout", "title": "Suppliers don't confirm bookings in time", "stage": "Supplier confirmed",
     "root_cause": "A channel-manager API slows down at peak hours; bookings stay \"pending\" and some are never "
                   "confirmed, causing cancellations and \"hotel has no record\" calls.",
     "evidence": "Pending time grows with request volume; concentrated on two channel managers.",
     "found_by": "ReservationIntegrityAgent (paid but not confirmed after SLA)",
     "owner": "Partner / Supplier integrations", "fix": "Automatic retries (agent, Tier 2) + escalation to partner manager",
     "status": "Agent auto-retrying", "share": 0.004,
     "shape": [1, 1, 1, 1.1, 1.3, 1.6, 1.7, 1.4, 1, 0.9, 0.8, 0.7]},
    {"id": "fraud_fp", "title": "Real travelers blocked by fraud checks", "stage": "Payment",
     "root_cause": "A new fraud rule flags first-time travelers on new devices or VPNs; good customers are "
                   "declined (false positives).",
     "evidence": "Blocked travelers have low chargeback history and later book with competitors' sites.",
     "found_by": "RootCauseAgent (segment: new device + new traveler)",
     "owner": "Fraud / Risk team", "fix": "Step-up verification instead of a hard block; retune the rule",
     "status": "Under review", "share": 0.012,
     "shape": [0.6, 0.6, 0.7, 0.8, 1, 1, 1.1, 1.1, 1.2, 1.3, 1.3, 1.3]},
    {"id": "zero_results", "title": "Searches with no or only sold-out results", "stage": "Detail",
     "root_cause": "Inventory gaps on peak dates in top destinations; results pages show mostly sold-out "
                   "properties and travelers leave.",
     "evidence": "Zero-result rate peaks on holiday weekends in a handful of cities.",
     "found_by": "FunnelMonitor (search to detail) by destination and date",
     "owner": "Supply / Market managers", "fix": "Add supply in gap cities; suggest nearby dates and areas",
     "status": "Ongoing", "share": 0.035,
     "shape": [0.9, 0.9, 1, 1, 1.1, 1.3, 1.35, 1.2, 0.95, 0.9, 1, 1.1]},
    {"id": "slow_pages", "title": "Slow property pages on the mobile app", "stage": "Detail",
     "root_cause": "Large, uncompressed photos make property pages load in more than 4 seconds on mobile "
                   "networks; travelers back out before the page loads.",
     "evidence": "Detail-page exits rise with load time; worst on iOS and Android over cellular.",
     "found_by": "FunnelMonitor + performance monitoring",
     "owner": "Mobile platform team", "fix": "Image compression and lazy loading",
     "status": "Fixed (Sep)", "share": 0.020,
     "shape": [1, 1.05, 1.1, 1.1, 1.15, 1.2, 1.2, 1.15, 0.5, 0.35, 0.3, 0.3]},
]

# Of travelers lost at a stage, how many would have booked? (Travelers lost at
# "Supplier confirmed" had already booked, so each one is a full lost booking.)
WOULD_BOOK = {"Detail": BASE["Checkout"] * BASE["Payment"] * BASE["Booked"],
              "Checkout": BASE["Payment"] * BASE["Booked"], "Payment": BASE["Booked"],
              "Booked": 1.0, "Supplier confirmed": 1.0}

PREV_STAGE = {"Detail": "Search", "Checkout": "Detail", "Payment": "Checkout",
              "Booked": "Payment", "Supplier confirmed": "Booked"}


def _months(today: date, n: int = 12) -> list[date]:
    out, y, m = [], today.year, today.month
    for _ in range(n):
        out.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def build(today: date | None = None, seed: int = 2026) -> dict:
    today = today or date.today()
    rng = random.Random(seed)
    months = _months(today)
    rows = []
    for i, m in enumerate(months):
        partial = (i == len(months) - 1)
        frac = min(today.day, 30) / 30 if partial else 1.0           # month to date
        searches = int(12_000_000 * SEASON[m.month] * rng.uniform(0.97, 1.03) * frac)
        counts = {"Search": searches}
        lost = {}
        for stage in STAGES[1:]:
            reached_prev = counts[PREV_STAGE[stage]]
            # every issue at this stage removes its share of travelers
            stage_issues = [x for x in ISSUES if x["stage"] == stage]
            loss_rate = sum(x["share"] * x["shape"][i] for x in stage_issues)
            for x in stage_issues:
                lost[x["id"]] = int(reached_prev * x["share"] * x["shape"][i] * WOULD_BOOK[stage])
            counts[stage] = int(reached_prev * max(0.0, BASE[stage] - loss_rate)
                                * rng.uniform(0.995, 1.005))
        bookings = counts["Booked"]
        rows.append({
            "month": m.strftime("%Y-%m"), "label": m.strftime("%b %Y") + (" (to date)" if partial else ""),
            "partial": partial, "searches": searches, "bookings": bookings,
            "conversion": round(bookings / searches, 4) if searches else 0,
            "revenue_usd": bookings * AVG_BOOKING_USD,
            "stages": [counts[s] for s in STAGES],
            "lost_by_issue": lost,                     # lost BOOKINGS per issue
            "lost_bookings": sum(lost.values()),
        })

    last_full = rows[-2]                         # rank issues on the last full month
    total_lost = max(1, last_full["lost_bookings"])
    issues = []
    for x in ISSUES:
        trend = [r["lost_by_issue"][x["id"]] for r in rows]
        lost_n = last_full["lost_by_issue"][x["id"]]
        prev = rows[-3]["lost_by_issue"][x["id"]]
        issues.append({
            **{k: x[k] for k in ("id", "title", "stage", "root_cause", "evidence", "found_by",
                                 "owner", "fix", "status")},
            "lost_bookings": lost_n,
            "lost_revenue_usd": lost_n * AVG_BOOKING_USD,
            "share_of_loss": round(lost_n / total_lost, 3),
            "change_vs_prev": round((lost_n - prev) / prev, 2) if prev else None,
            "trend": trend,
            "year_lost_revenue_usd": sum(trend) * AVG_BOOKING_USD,
        })
    issues.sort(key=lambda r: -r["lost_bookings"])
    for rank, it in enumerate(issues, 1):
        it["rank"] = rank
    return {
        "note": "Simulated 12-month history for the demo. All numbers are fake.",
        "stage_labels": STAGES, "avg_booking_usd": AVG_BOOKING_USD,
        "months": rows, "ranked_on": last_full["label"], "issues": issues,
    }
