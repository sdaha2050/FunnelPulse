"""Checks for the monthly dashboard data (simulated history)."""
from datetime import date

from app import monthly


def test_monthly_has_12_months_and_ranked_top_issues():
    d = monthly.build(today=date(2026, 11, 21))
    assert len(d["months"]) == 12
    assert d["months"][-1]["partial"] and d["months"][-1]["label"].startswith("Nov 2026")
    issues = d["issues"]
    assert 5 <= len(issues) <= 10
    lost = [i["lost_bookings"] for i in issues]
    assert lost == sorted(lost, reverse=True), "issues must be ranked by lost bookings"
    for i in issues:
        assert i["root_cause"] and i["owner"] and i["fix"] and len(i["trend"]) == 12


def test_funnel_never_grows_between_stages():
    for m in monthly.build(today=date(2026, 11, 21))["months"]:
        assert all(a >= b for a, b in zip(m["stages"], m["stages"][1:]))
