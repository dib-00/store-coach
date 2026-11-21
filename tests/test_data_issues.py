"""Store-days that cannot be right are left out of conversion and listed, never alerted."""
from __future__ import annotations

from engine.load import load
from engine.metrics import Metrics

from .conftest import alerts_of

OCT = {"start": "2026-10-04", "end": "2026-10-31"}


def test_zero_footfall_days_are_left_out_of_both_sides(pack):
    m = Metrics(load(pack, "2026-10-31"))
    p = {"store_ids": ["AAA-03"], **OCT}
    # 28 days, 10 of them (8 to 17 Oct) with footfall 0 and bills still made
    assert m.compute("invalid_days", p) == 10
    assert m.compute("valid_days", p) == 18
    # the 18 valid days: 13 weekdays (100 walk-ins, 13 bills) and 5 weekend days (150, 20)
    assert m.compute("footfall_sum", p) == 13 * 100 + 5 * 150
    assert m.compute("bills_count", p) == 13 * 13 + 5 * 20
    assert m.compute("conversion", p) == round((13 * 13 + 5 * 20) / (13 * 100 + 5 * 150), 4)
    # every bill is 2 x 4,500 plus a Rs 0 carry bag
    assert m.compute("avg_bill_value", p) == 9000.0


def test_bills_above_footfall_is_invalid_too(pack):
    m = Metrics(load(pack, "2026-10-31"))
    day = {"store_ids": ["AAA-02"], "start": "2026-08-12", "end": "2026-08-12"}
    assert m.compute("invalid_days", {**day, "rule": "bills_exceed_footfall"}) == 1
    assert m.compute("invalid_days", {**day, "rule": "footfall_zero"}) == 0
    assert m.compute("bills_count", day) == 0 and m.compute("footfall_sum", day) == 0


def test_invalid_days_become_data_issues_not_alerts(result):
    output, _ = result
    issues = {i["issue_id"]: i for i in output["data_issues"]}
    assert set(issues) == {"AAA-03:footfall_zero_with_bills", "AAA-02:bills_exceed_footfall"}

    zero = issues["AAA-03:footfall_zero_with_bills"]
    assert (zero["first_date"], zero["last_date"], zero["days_affected"]) == ("2026-10-08", "2026-10-17", 10)
    assert "left out of both bills and walk-ins" in zero["handling"]
    assert "not judged" in zero["handling"]  # 10 of 28 days is too many to judge the store

    one_day = issues["AAA-02:bills_exceed_footfall"]
    assert one_day["days_affected"] == 1 and "not judged" not in one_day["handling"]

    alerted = {s for a in alerts_of(output) for s in a["store_ids"]}
    assert "AAA-03" not in alerted and "AAA-02" not in alerted


def test_unjudged_store_shows_no_current_conversion(result):
    stores = {s["store_id"]: s for s in result[0]["stores"]}
    slugs = lambda sid: [c["id"].split(":")[-1] for c in stores[sid]["summary"]]
    assert "conversion_current" not in slugs("AAA-03")
    assert "conversion_baseline" in slugs("AAA-03")
    assert "conversion_current" in slugs("AAA-02")
