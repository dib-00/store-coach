"""scripts/verify.py must fail loudly.

A tiny made-up CSV pack and a JSON whose figures were worked out BY HAND (see the
comments in `pack` and `good_output`), not by the engine and not by verify.py. The
clean file must pass; then one thing at a time is broken and the script must exit
non-zero and name what is wrong. Nothing here needs data/csv or imports engine/.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "verify.py"
AS_OF = "2026-10-18"  # a Sunday


def _load_script():
    spec = importlib.util.spec_from_file_location("store_coach_verify", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = _load_script()


def _dates(start, end):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return [(a + timedelta(n)).isoformat() for n in range((b - a).days + 1)]


def _write(folder, name, header, rows):
    lines = [header] + [",".join(str(v) for v in row) for row in rows]
    (folder / f"{name}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_pack(folder, with_future_rows=False):
    """One judged store, S-01, over two weeks (Mon 5 Oct to Sun 18 Oct 2026).

    Week 1 (5-11 Oct):  10 walk-ins and 2 bills a day           -> 14 bills / 70 walk-ins
    Week 2 (12-18 Oct): 10 walk-ins and 1 bill a day, except Wed 14 Oct where the
                        counter reads 0 and there is still 1 bill (an invalid day)
                                                                -> 6 bills / 60 walk-ins on 6 valid days
    Week 2 bill values on valid days: five of ₹1,000 and one of 2 × ₹800 = ₹1,600.
    Binod B. is Off on both weekends; Asha A. is Present every day.
    Wed 21 Oct is a wedding date and Tue 27 Oct is "Test Festival", so the busy days in
    the 9 days after as-of are 21, 24, 25 and 27 Oct.

    S-02 carries the made-up customers of the repeat recipes (docs/CHECKS-repeat.md). It has
    no footfall rows, so nothing below touches a figure of S-01. First bill decides who a
    customer belongs to; "returned" = billed again 30 to 180 days later.

      Chitra C. (SP03)                               Dev D. (SP04)
      R1 first 10 Jan, again 20 Feb (41 days)  yes   Q1 first  5 Jan, again  1 Mar (55 days)  yes
      R2 first 15 Jan, again 30 Jan (15 days)  no    Q2 first 20 Jan, again 25 Feb (36 days)  yes
      R3 first  5 Feb, never again             no    Q3 first  1 Feb, never again             no
      R4 first 10 Feb, again  1 Sep (203 days) no    Q4 first 15 Feb, again 20 Mar (33 days)  yes

      New customers of Chitra C.: N1 first 10 Sep (never again), N2 first 12 Sep (again 15 Oct,
      33 days, ₹3,000), N3 first 20 Sep (a sherwani, never again).
      C9 is on 25 bills (1 to 25 Mar 2025): a placeholder id by the 25-bills rule.
      Every other return bill is ₹2,000.
    """
    folder.mkdir(parents=True, exist_ok=True)
    _write(folder, "stores",
           "store_id,city,state,zone,tier,size_sqft,stock_capacity_units,opened_on,area_manager_id",
           [("S-01", "Testcity", "Teststate", "North", "B", 1000, 100, "2020-01-01", "AM-01"),
            ("S-02", "Testcity", "Teststate", "North", "B", 1000, 100, "2020-01-01", "AM-01")])
    _write(folder, "area_managers", "area_manager_id,name,city,stores,max_alerts_per_week",
           [("AM-01", "Test Manager", "Testcity", '"S-01, S-02"', 5)])
    _write(folder, "salespeople", "salesperson_id,store_id,name,join_date",
           [("SP01", "S-01", "Asha A.", "2020-01-01"), ("SP02", "S-01", "Binod B.", "2020-01-01"),
            ("SP03", "S-02", "Chitra C.", "2020-01-01"), ("SP04", "S-02", "Dev D.", "2020-01-01")])
    _write(folder, "calendar", "date,state,festival,is_wedding_date",
           [(d, "Teststate", " Test Festival " if d == "2026-10-27" else "", 1 if d == "2026-10-21" else 0)
            for d in _dates("2026-10-05", "2026-10-27")])
    _write(folder, "items", "sku_id,style_id,style_name,category,size,mrp,cost_price,launch_date,is_core_style,is_packaging",
           [("ITEM-1", "ITEM", "Plain Kurta", "Kurta", "M", 1000, 400, "2020-01-01", 1, 0),
            ("SHW-1", "SHW", "Test Sherwani", "Sherwani", "M", 2000, 800, "2020-01-01", 1, 0),
            ("PKG-BAG", "PKG", "Carry Bag", "Sherwani", "", 0, 0, "2020-01-01", 0, 1)])

    footfall = [(d, "S-01", 0 if d == "2026-10-14" else 10) for d in _dates("2026-10-05", AS_OF)]
    bills, lines, n = [], [], 0

    def bill(day, qty, price):
        nonlocal n
        n += 1
        bills.append((f"B{n:04d}", day, "S-01", "SP01", f"C{n:04d}"))
        lines.append((f"B{n:04d}", "ITEM-1", qty, price, price))
        lines.append((f"B{n:04d}", "PKG-BAG", 1, 0, 0))

    for d in _dates("2026-10-05", "2026-10-11"):
        bill(d, 1, 1000)
        bill(d, 1, 1000)
    for d in _dates("2026-10-12", AS_OF):
        if d == "2026-10-14":
            bill(d, 1, 9999)      # on the invalid day: must be left out of everything
        elif d == AS_OF:
            bill(d, 2, 800)
        else:
            bill(d, 1, 1000)
    def repeat_bill(day, sp, customer, price=2000, sku="ITEM-1"):
        nonlocal n
        n += 1
        bills.append((f"B{n:04d}", day, "S-02", sp, customer))
        lines.append((f"B{n:04d}", sku, 1, price, price))
        lines.append((f"B{n:04d}", "PKG-BAG", 1, 0, 0))   # packaging filed under Sherwani: must not count

    for customer, sp, first, again in (
            ("R1", "SP03", "2026-01-10", "2026-02-20"), ("R2", "SP03", "2026-01-15", "2026-01-30"),
            ("R3", "SP03", "2026-02-05", None), ("R4", "SP03", "2026-02-10", "2026-09-01"),
            ("Q1", "SP04", "2026-01-05", "2026-03-01"), ("Q2", "SP04", "2026-01-20", "2026-02-25"),
            ("Q3", "SP04", "2026-02-01", None), ("Q4", "SP04", "2026-02-15", "2026-03-20"),
            ("N1", "SP03", "2026-09-10", None), ("N2", "SP03", "2026-09-12", None)):
        repeat_bill(first, sp, customer)
        if again:
            repeat_bill(again, "SP04", customer)          # who serves the return does not matter
    repeat_bill("2026-10-15", "SP04", "N2", price=3000)
    repeat_bill("2026-09-20", "SP03", "N3", sku="SHW-1")
    for d in _dates("2025-03-01", "2025-03-25"):
        repeat_bill(d, "SP03", "C9")

    if with_future_rows:          # rows after as-of: verify must not see them
        footfall.append(("2026-10-19", "S-01", 5000))
        bill("2026-10-19", 1, 77777)

    _write(folder, "footfall_daily", "date,store_id,footfall", footfall)
    _write(folder, "bills", "bill_id,bill_date,store_id,salesperson_id,customer_id", bills)
    _write(folder, "bill_lines", "bill_id,sku_id,qty,mrp,selling_price", lines)
    weekend = {"2026-10-10", "2026-10-11", "2026-10-17", "2026-10-18"}
    _write(folder, "roster_daily", "date,store_id,salesperson_id,status",
           [(d, "S-01", sp, "Off" if sp == "SP02" and d in weekend else "Present")
            for d in _dates("2026-10-05", AS_OF) for sp in ("SP01", "SP02")])
    return folder


def _check(cid, kind, params, value, display):
    return {"id": cid, "label": cid, "kind": kind, "params": params, "value": value, "display": display}


def good_output():
    """Every value below was worked out by hand from the story in make_pack."""
    week1 = {"start": "2026-10-05", "end": "2026-10-11"}
    week2 = {"start": "2026-10-12", "end": AS_OF}
    store = {"store_ids": ["S-01"]}
    a = "S-01:more_bills:missed_shifts"
    checks = [
        _check(f"{a}:conv_current", "conversion", {**store, **week2, "day_type": "all"}, 0.1, "10.0%"),      # 6 / 60
        _check(f"{a}:conv_benchmark", "conversion", {**store, **week1, "day_type": "all"}, 0.2, "20.0%"),    # 14 / 70
        _check(f"{a}:bills_current", "bills_count", {**store, **week2, "day_type": "all"}, 6, "6"),
        _check(f"{a}:footfall_current", "footfall_sum", {**store, **week2, "day_type": "all"}, 60, "60"),
        # p = 20/130, se = sqrt(p(1-p)(1/60 + 1/70)) = 0.06348, z = (0.1 - 0.2) / se = -1.575
        _check(f"{a}:z", "two_proportion_z",
               {**store, **week2, "base_start": "2026-10-05", "base_end": "2026-10-11", "day_type": "all"},
               -1.58, "-1.58"),
        _check(f"{a}:walkins", "walkins_per_week", {**store, **week2}, 70.0, "70"),                          # 60 / 6 × 7
        _check(f"{a}:avg_bill", "avg_bill_value", {**store, **week2}, 1100.0, "₹1,100"),                     # 6,600 / 6
        _check(f"{a}:rupees", "rupees_at_stake",
               {"benchmark_check_id": f"{a}:conv_benchmark", "current_check_id": f"{a}:conv_current",
                "walkins_check_id": f"{a}:walkins", "avg_bill_check_id": f"{a}:avg_bill"},
               7700, "₹7,700"),                                                                              # 10% × 70 × 1,100
        _check(f"{a}:present:SP02", "present_days", {"salesperson_id": "SP02", **week2, "day_type": "all"}, 5, "5"),
        _check(f"{a}:present:SP01", "present_days", {"salesperson_id": "SP01", **week2, "day_type": "all"}, 7, "7"),
        _check(f"{a}:busy", "upcoming_busy_dates",
               {"state": "Teststate", "start": "2026-10-19", "end": "2026-10-27"},
               "2026-10-21, 2026-10-24, 2026-10-25, 2026-10-27",
               "Wed 21 Oct 2026, Sat 24 Oct 2026, Sun 25 Oct 2026, Tue 27 Oct 2026"),
        _check(f"{a}:festival:2026-10-27", "festival_name", {"state": "Teststate", "date": "2026-10-27"},
               "Test Festival", "Test Festival"),
    ]
    alert = {
        "alert_id": a, "rank": 1, "scope": "store", "store_ids": ["S-01"], "city": "Testcity",
        "lever": "more_bills", "cause_code": "missed_shifts",
        "headline": "S-01 is converting 10.0% of walk-ins, down from 20.0%.",
        "cause": "Binod B. was on the floor on 5 days, against 7 for Asha A.",
        "action": {"who": "Store manager at S-01, with Binod B.", "what": "Roster Binod B. on the busy days",
                   "when": "Sat 24 Oct and Sun 25 Oct",
                   "text": "On Sat 24 Oct and Sun 25 Oct, put Binod B. on the floor at S-01."},
        "rupees_at_stake_weekly": 7700,
        "arithmetic": {"formula": "(fair conversion − current conversion) × walk-ins a week × average bill value",
                       "worked": "(20.0% − 10.0%) × 70 walk-ins a week × ₹1,100 = ₹7,700 a week",
                       "input_check_ids": [f"{a}:conv_benchmark", f"{a}:conv_current", f"{a}:walkins", f"{a}:avg_bill"]},
        "benchmark_basis": "Same store, the week before",
        "salesperson_ids": ["SP02"],
        "checks": checks,
        "follow_up": {"metric_label": "Conversion at S-01", "kind": "conversion",
                      "params": {**store, **week2, "day_type": "all"},
                      "baseline_value": 0.1, "target_value": 0.2, "higher_is_better": True},
    }
    card = {
        "card_id": "S-01:SP02:more_bills", "store_id": "S-01", "salesperson_id": "SP02",
        "salesperson_name": "Binod B.", "lever": "more_bills", "behaviour": "Be on the floor on busy days",
        "peer": {"salesperson_id": "SP01", "name": "Asha A."}, "action": "Work both weekend days this week.",
        "text": "Binod B., Asha A. was on the floor 7 days this week and you were on 5. "
                "Work both weekend days this week.",
        "word_count": 23,
        "checks": [
            _check("card:S-01:SP02:own", "present_days", {"salesperson_id": "SP02", **week2, "day_type": "all"}, 5, "5"),
            _check("card:S-01:SP02:peer", "present_days", {"salesperson_id": "SP01", **week2, "day_type": "all"}, 7, "7"),
        ],
    }
    issue = {
        "issue_id": "S-01:footfall_zero_with_bills", "store_id": "S-01", "kind": "footfall_zero_with_bills",
        "title": "S-01: door counter shows no walk-ins on a day with bills", "detail": "", "handling": "",
        "first_date": "2026-10-14", "last_date": "2026-10-14", "days_affected": 1,
        "checks": [
            _check("issue:S-01:days", "invalid_days", {**store, **week2, "rule": "footfall_zero"}, 1, "1"),
            _check("issue:S-01:bills", "bills_on_invalid_days", {**store, **week2, "rule": "footfall_zero"}, 1, "1"),
            _check("issue:S-01:valid", "valid_days", {**store, **week2}, 6, "6"),
        ],
    }
    return {
        "schema_version": 1, "as_of": AS_OF, "generated_at": "2026-01-01T00:00:00Z",
        "windows": {"current": week2, "baseline": week1},
        "area_managers": [{"area_manager_id": "AM-01", "name": "Test Manager", "city": "Testcity",
                           "store_ids": ["S-01", "S-02"], "max_alerts_per_week": 5,
                           "alerts": [alert], "held_back": []}],
        "stores": [{"store_id": "S-02", "salespeople": [{"salesperson_id": "SP03", "name": "Chitra C.", "active": True},
                                                        {"salesperson_id": "SP04", "name": "Dev D.", "active": True}],
                    "summary": repeat_checks()}],
        "cards": [card], "follow_ups": [], "data_issues": [issue],
    }


def repeat_checks():
    """Every value worked out by hand from the customers listed in make_pack."""
    r = "S-02:more_repeat:test"
    own = {"store_ids": ["S-02"], "salesperson_ids": ["SP03"], "exclude_customer_ids": ["C9"]}
    cohort = {**own, "first_bill_to": "2026-04-21", "min_gap_days": 30, "max_gap_days": 180}   # as-of − 180 days
    versus = {**cohort, "peer_store_ids": ["S-02"], "peer_salesperson_ids": ["SP04"]}
    gaps = {"min_gap_days": 30, "max_gap_days": 180}
    return [
        _check(f"{r}:opened_on", "store_opened_on", {"store_id": "S-02"}, "2020-01-01", "1 Jan 2020"),
        _check(f"{r}:customers", "repeat_customers", cohort, 4, "4"),                    # R1 R2 R3 R4
        _check(f"{r}:returned", "repeat_returned", cohort, 1, "1"),                      # R1 only
        _check(f"{r}:return_rate", "repeat_return_rate", cohort, 0.25, "25.0%"),
        # Jan: 2 of Chitra's customers, and Dev's Jan customers returned 2 of 2; Feb: 2 of hers, Dev's 1 of 2
        # expected = 2 × 1 + 2 × 0.5 = 3, over 4 customers = 0.75
        _check(f"{r}:fair_rate", "repeat_fair_rate", versus, 0.75, "75.0%"),
        # Jan: N 4, R 3, E 1.5, V 2×2×3×1/(16×3) = 0.25; Feb: N 4, R 1, E 0.5, V 2×2×1×3/(16×3) = 0.25
        # z = (1 − 2) / sqrt(0.5) = −1.414
        _check(f"{r}:z", "repeat_z", versus, -1.41, "-1.41"),
        _check(f"{r}:quarters_compared", "repeat_quarters", {**versus, "min_customers": 2, "count": "compared"}, 1, "1"),
        _check(f"{r}:quarters_behind", "repeat_quarters", {**versus, "min_customers": 2, "count": "behind"}, 1, "1"),
        _check(f"{r}:quarters_ahead", "repeat_quarters", {**versus, "min_customers": 2, "count": "ahead"}, 0, "0"),
        _check(f"{r}:return_rate_recent", "repeat_return_rate", {**cohort, "first_bill_from": "2026-01-01"}, 0.25, "25.0%"),
        _check(f"{r}:fair_rate_recent", "repeat_fair_rate", {**versus, "first_bill_from": "2026-01-01"}, 0.75, "75.0%"),
        # N1, N2, N3 first billed in the 42 days (6 weeks) to as-of
        _check(f"{r}:new_customers_per_week", "repeat_new_customers_per_week",
               {**own, "start": "2026-09-07", "end": AS_OF}, 0.5, "0.5"),
        # return bills made at S-02 this year: R1, Q1, Q2, Q4 at ₹2,000 and N2 at ₹3,000
        _check(f"{r}:return_bill_count", "repeat_return_bill_count",
               {"store_ids": ["S-02"], "exclude_customer_ids": ["C9"], "start": "2026-01-01", "end": AS_OF, **gaps}, 5, "5"),
        _check(f"{r}:avg_return_bill_value", "repeat_avg_return_bill_value",
               {"store_ids": ["S-02"], "exclude_customer_ids": ["C9"], "start": "2026-01-01", "end": AS_OF, **gaps},
               2200.0, "₹2,200"),
        # (75.0% − 25.0%) × 0.5 × ₹2,200 = 500 × 5 × 2200 / 10000 = 550 -> ₹600 (half up)
        _check(f"{r}:rupees_at_stake", "repeat_rupees_at_stake",
               {"fair_rate": 0.75, "own_rate": 0.25, "new_customers_per_week": 0.5, "avg_return_bill_value": 2200.0},
               600, "₹600"),
        _check(f"{r}:call_list", "repeat_call_list",
               {**own, "first_from": "2026-09-01", "first_to": "2026-09-30", "no_bill_through": AS_OF}, 2, "2"),   # N1, N3
        _check(f"{r}:call_list_sherwani", "repeat_call_list",
               {**own, "first_from": "2026-09-01", "first_to": "2026-09-30", "no_bill_through": AS_OF,
                "category": "Sherwani"}, 1, "1"),                                                                    # N3
        # week to as-of: 1 return bill (N2); inside the window on 18 Oct (first bill 21 Apr to 18 Sep): N1, N2
        _check(f"{r}:weekly_returns", "repeat_weekly_returns_per_100",
               {**own, "start": "2026-10-12", "end": AS_OF, **gaps}, 50.0, "50.00"),
        _check(f"{r}:call_to", "repeat_date_offset", {"date": AS_OF, "days": -30}, "2026-09-18", "18 Sep 2026"),
        _check(f"{r}:placeholder_bills", "repeat_placeholder_bills", {"customer_id": "C9"}, 25, "25"),
        _check(f"{r}:placeholder_stores", "repeat_placeholder_stores", {"customer_id": "C9"}, 1, "1"),
    ]


def earlier_run():
    """The run of Sun 11 Oct: one alert on S-01, conversion 14 / 70 = 20.0% over week 1."""
    week1 = {"store_ids": ["S-01"], "start": "2026-10-05", "end": "2026-10-11", "day_type": "all"}
    a = "S-01:more_bills:test"
    return {"schema_version": 1, "as_of": "2026-10-11", "area_managers": [{"area_manager_id": "AM-01", "alerts": [{
        "alert_id": a, "store_ids": ["S-01"], "lever": "more_bills",
        "headline": "S-01 is converting 20.0% of walk-ins.",
        "action": {"text": "On Sat 17 Oct, put Binod B. on the floor at S-01."},
        "checks": [_check(f"{a}:conv_current", "conversion", week1, 0.2, "20.0%"),
                   _check(f"{a}:conv_busy", "conversion", {**week1, "day_type": "busy"}, 0.2, "20.0%")],   # 4 / 20
        "follow_up": {"metric_label": "Conversion at S-01", "kind": "conversion", "params": week1,
                      "baseline_value": 0.2, "target_value": 0.2, "higher_is_better": True}}]}]}


def with_follow_up(output):
    """Week 2 against the alert of 11 Oct. 6 bills from 60 walk-ins = 10.0%; one invalid day in 7
    (14%) is within the 20% limit. se = sqrt(0.1 × 0.9 / 60) = 0.0387; change −0.1 -> worse."""
    alert = earlier_run()["area_managers"][0]["alerts"][0]
    f = f"followup:{alert['alert_id']}"
    week1 = alert["follow_up"]["params"]
    after = {**week1, "start": "2026-10-12", "end": AS_OF}
    output["follow_ups"] = [{
        "alert_id": alert["alert_id"], "area_manager_id": "AM-01", "store_ids": ["S-01"], "lever": "more_bills",
        "headline": alert["headline"], "action_text": alert["action"]["text"],
        "raised_as_of": "2026-10-11", "measured_as_of": AS_OF, "metric_label": "Conversion at S-01",
        "before": 0.2, "after": 0.1, "target": 0.2,
        "before_display": "20.0%", "after_display": "10.0%", "target_display": "20.0%", "moved": "worse",
        "verdict": "Conversion at S-01 was 20.0% when raised and 10.0% in the 7 days after (6 bills from 60 "
                   "walk-ins); the target is 20.0%. Worse than when raised, though one week is a small sample.",
        "checks": [
            _check(f"{f}:before", "conversion", week1, 0.2, "20.0%"),
            _check(f"{f}:target", "conversion", {**week1, "day_type": "busy"}, 0.2, "20.0%"),
            _check(f"{f}:days", "day_count", {"state": "Teststate", "start": "2026-10-12", "end": AS_OF, "day_type": "all"}, 7, "7"),
            _check(f"{f}:after", "conversion", after, 0.1, "10.0%"),
            _check(f"{f}:after_numerator", "bills_count", after, 6, "6"),
            _check(f"{f}:after_denominator", "footfall_sum", after, 60, "60"),
        ]}]
    return output


def run_with_earlier(tmp_path, pack, output, capsys):
    (tmp_path / "runs").mkdir(exist_ok=True)
    (tmp_path / "runs" / "2026-10-11.json").write_text(json.dumps(earlier_run(), ensure_ascii=False), encoding="utf-8")
    return run_verify(tmp_path, pack, output, capsys)


@pytest.fixture(scope="module")
def csv_pack(tmp_path_factory):
    return make_pack(tmp_path_factory.mktemp("verify_pack"))


def run_verify(tmp_path, pack, output, capsys):
    """(exit code, printed text) of scripts/verify.py for this output."""
    path = tmp_path / "out.json"
    path.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    code = verify.main(["--file", str(path), "--data-dir", str(pack)])
    captured = capsys.readouterr()
    return code, captured.out + captured.err


def alert_of(output):
    return output["area_managers"][0]["alerts"][0]


def check_of(output, suffix):
    return next(c for c in alert_of(output)["checks"] if c["id"].endswith(suffix))


def test_hand_worked_file_passes(tmp_path, csv_pack, capsys):
    code, text = run_verify(tmp_path, csv_pack, good_output(), capsys)
    assert code == 0, text
    assert "38 checks recomputed, 0 mismatch" in text      # 12 in the alert, 2 card, 3 issue, 21 repeat and store
    assert "-> PASS" in text


def test_one_corrupted_value_exits_non_zero_and_is_named(tmp_path, csv_pack):
    """The real thing: a separate process, its exit code and what it prints."""
    output = good_output()
    check_of(output, ":conv_current")["value"] = 0.11
    path = tmp_path / "out.json"
    path.write_text(json.dumps(output, ensure_ascii=False), encoding="utf-8")
    done = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "--file", str(path), "--data-dir", str(csv_pack)],
                          capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "MISMATCH [conversion] id=S-01:more_bills:missed_shifts:conv_current kind=conversion" in done.stdout
    assert "expected from CSV: 0.1\n" in done.stdout
    assert "found in JSON:     0.11\n" in done.stdout
    assert "-> FAIL" in done.stdout


def test_a_difference_in_the_last_documented_decimal_fails(tmp_path, csv_pack, capsys):
    output = good_output()
    check_of(output, ":avg_bill")["value"] = 1100.01
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "id=S-01:more_bills:missed_shifts:avg_bill kind=avg_bill_value" in text


def test_unknown_kind_is_a_failure_not_a_skip(tmp_path, csv_pack, capsys):
    output = good_output()
    alert_of(output)["checks"].append(_check("mystery", "items_per_bill_from_nowhere", {}, 2.1, "2.1"))
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1
    assert "id=mystery kind=items_per_bill_from_nowhere" in text and "UNKNOWN KIND" in text


def test_undocumented_param_fails(tmp_path, csv_pack, capsys):
    output = good_output()
    check_of(output, ":bills_current")["params"]["only_big_bills"] = True
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "params not in the documented recipe: ['only_big_bills']" in text


def test_display_that_does_not_match_its_value_fails(tmp_path, csv_pack, capsys):
    output = good_output()
    check_of(output, ":conv_current")["display"] = "10.4%"
    alert_of(output)["headline"] = "S-01 is converting 10.4% of walk-ins, down from 20.0%."
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "[display matches value] id=S-01:more_bills:missed_shifts:conv_current" in text


def test_number_in_text_without_a_check_fails(tmp_path, csv_pack, capsys):
    output = good_output()
    alert_of(output)["cause"] += " Conversion fell 33% on weekends."
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1
    assert "[alert text numbers have a check] id=S-01:more_bills:missed_shifts kind=cause" in text
    assert "no check shows: ['33']" in text


def test_rupees_that_do_not_follow_from_the_checks_fail(tmp_path, csv_pack, capsys):
    output = good_output()
    alert_of(output)["rupees_at_stake_weekly"] = 7800
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "[alert rupees = its check] id=S-01:more_bills:missed_shifts" in text


def test_worked_line_that_does_not_multiply_out_fails(tmp_path, csv_pack, capsys):
    output = good_output()
    alert = alert_of(output)
    alert["arithmetic"]["worked"] = "(20.0% − 10.0%) × 70 walk-ins a week × ₹1,100 = ₹7,800 a week"
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "[alert arithmetic multiplies out]" in text


def test_more_alerts_than_the_cap_fails(tmp_path, csv_pack, capsys):
    output = good_output()
    block = output["area_managers"][0]
    block["alerts"] = [dict(copy.deepcopy(block["alerts"][0]), rank=i + 1) for i in range(6)]
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "id=AM-01 kind=alert count" in text and "at most 5" in text


def test_alerts_not_ranked_by_rupees_fail(tmp_path, csv_pack, capsys):
    output = good_output()
    block = output["area_managers"][0]
    small = copy.deepcopy(block["alerts"][0])
    small["alert_id"] = "S-01:more_bills:other"
    block["alerts"][0]["rank"] = 2
    block["alerts"].insert(0, small)
    small["rupees_at_stake_weekly"] = 100   # smaller, yet listed first
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "id=AM-01 kind=order" in text


def test_card_over_60_words_fails(tmp_path, csv_pack, capsys):
    output = good_output()
    card = output["cards"][0]
    card["text"] += " please" * 38                       # 23 + 38 = 61 words
    card["word_count"] = 61
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "id=S-01:SP02:more_bills kind=text" in text and "61 words" in text


def test_card_peer_from_another_store_fails(tmp_path, csv_pack, capsys):
    output = good_output()
    card = output["cards"][0]
    card["peer"] = {"salesperson_id": "SP03", "name": "Chitra C."}
    card["text"] = card["text"].replace("Asha A.", "Chitra C.")
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "id=S-01:SP02:more_bills kind=peer" in text and "'S-02'" in text


def test_card_that_does_not_name_its_peer_fails(tmp_path, csv_pack, capsys):
    output = good_output()
    card = output["cards"][0]
    card["text"] = card["text"].replace("Asha A.", "A colleague")
    card["word_count"] = len(card["text"].split())
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "names the peer 'Asha A.'" in text


def test_check_window_after_as_of_fails(tmp_path, csv_pack, capsys):
    output = good_output()
    check_of(output, ":present:SP01")["params"]["end"] = "2026-10-19"
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1
    assert "[nothing after as_of] id=S-01:more_bills:missed_shifts:present:SP01" in text and "end=2026-10-19" in text


def test_data_issue_dated_after_as_of_fails(tmp_path, csv_pack, capsys):
    output = good_output()
    output["data_issues"][0]["last_date"] = "2026-10-20"
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "id=S-01:footfall_zero_with_bills kind=last_date" in text


def test_rows_after_as_of_in_the_csvs_are_not_used(tmp_path, capsys):
    """Same hand-worked file, but the pack also holds a huge day after as-of."""
    pack = make_pack(tmp_path / "pack", with_future_rows=True)
    code, text = run_verify(tmp_path, pack, good_output(), capsys)
    assert code == 0, text
    assert "'bills': 1, 'footfall_daily': 1" in text


def test_an_engine_that_read_a_later_row_is_caught(tmp_path, capsys):
    """If the figures had been computed with the row of 19 Oct, they no longer match."""
    pack = make_pack(tmp_path / "pack", with_future_rows=True)
    output = good_output()
    check_of(output, ":footfall_current")["value"] = 5060      # 60 + the 5,000 of 19 Oct
    check_of(output, ":footfall_current")["display"] = "5,060"
    code, text = run_verify(tmp_path, pack, output, capsys)
    assert code == 1 and "footfall_current kind=footfall_sum" in text and "expected from CSV: 60" in text


def test_missing_csv_cannot_run(tmp_path, capsys):
    pack = make_pack(tmp_path / "pack")
    (pack / "bills.csv").unlink()
    code, text = run_verify(tmp_path, pack, good_output(), capsys)
    assert code == 2 and "CANNOT RUN" in text


def test_rounding_is_half_up_and_exact():
    from fractions import Fraction
    assert verify.rhu(Fraction(13223, 28), 1) == Fraction(4723, 10)    # 472.25 -> 472.3, not 472.2
    assert verify.rhu(Fraction(5, 1000), 2) == Fraction(1, 100)        # 0.005 -> 0.01
    assert verify.indian(122600) == "1,22,600" and verify.indian(12345678) == "1,23,45,678"
    assert verify.fmt_percent1(0.1071) == "10.7%" and verify.fmt_1dp_trim(23.0) == "23"
    assert verify.fmt_day_list("2026-11-01, 2026-11-07") == "Sun 1 Nov 2026, Sat 7 Nov 2026"


def test_busy_dates_beyond_the_documented_9_days_fail(tmp_path, csv_pack, capsys):
    """Only the 9 days after as-of may be read from the future calendar (CHECKS-followup.md)."""
    output = good_output()
    check_of(output, ":busy")["params"]["end"] = "2026-10-28"
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "the 9 days after as_of, 2026-10-19..2026-10-27" in text


def summary_check(output, suffix):
    return next(c for c in output["stores"][0]["summary"] if c["id"].endswith(suffix))


def test_festival_name_is_read_from_the_calendar(tmp_path, csv_pack, capsys):
    output = good_output()
    check_of(output, ":festival:2026-10-27")["value"] = "Diwali"
    check_of(output, ":festival:2026-10-27")["display"] = "Diwali"
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "kind=festival_name" in text and "expected from CSV: 'Test Festival'" in text


def test_festival_name_on_a_day_without_a_festival_fails(tmp_path, csv_pack, capsys):
    output = good_output()
    check_of(output, ":festival:2026-10-27")["params"]["date"] = "2026-10-24"
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "the festival cell is blank" in text


@pytest.mark.parametrize("suffix, wrong", [
    (":customers", 5),            # 5 is what you get if the placeholder C9 is not removed
    (":returned", 2), (":return_rate", 0.5), (":fair_rate", 0.7), (":z", -1.42), (":quarters_behind", 0),
    (":new_customers_per_week", 0.6), (":return_bill_count", 6), (":avg_return_bill_value", 2000.0),
    (":rupees_at_stake", 500), (":call_list", 3), (":call_list_sherwani", 2), (":weekly_returns", 33.33),
    (":call_to", "2026-09-17"), (":placeholder_bills", 24), (":opened_on", "2020-01-02"),
])
def test_each_new_kind_catches_a_wrong_value(tmp_path, csv_pack, capsys, suffix, wrong):
    output = good_output()
    summary_check(output, suffix)["value"] = wrong
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and f"id=S-02:more_repeat:test{suffix} " in text


def test_placeholder_left_in_is_caught(tmp_path, csv_pack, capsys):
    """An exclude list that is not what the rule gives fails, whatever the value says."""
    output = good_output()
    check = summary_check(output, ":customers")
    check["params"]["exclude_customer_ids"] = []
    check["value"], check["display"] = 5, "5"                    # consistent with not excluding C9
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "[repeat: excluded ids = placeholder rule] id=S-02:more_repeat:test:customers" in text


def test_repeat_rupees_must_use_the_checks_beside_it(tmp_path, csv_pack, capsys):
    output = good_output()
    check = summary_check(output, ":rupees_at_stake")
    check["params"]["fair_rate"] = 0.85                          # self-consistent, but not the rate shown
    check["value"], check["display"] = 700, "₹700"               # 600 × 5 × 2200 / 10000 = 660 -> 700
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "[repeat rupees built on its own checks]" in text


def test_follow_up_worked_by_hand_passes(tmp_path, csv_pack, capsys):
    code, text = run_with_earlier(tmp_path, csv_pack, with_follow_up(good_output()), capsys)
    assert code == 0, text
    assert "44 checks recomputed, 0 mismatch" in text


def test_follow_up_without_the_earlier_run_fails(tmp_path, csv_pack, capsys):
    code, text = run_verify(tmp_path, csv_pack, with_follow_up(good_output()), capsys)
    assert code == 1 and "no follow-ups when there is no run for 2026-10-11" in text


def test_an_alert_of_last_week_with_no_follow_up_fails(tmp_path, csv_pack, capsys):
    code, text = run_with_earlier(tmp_path, csv_pack, good_output(), capsys)
    assert code == 1 and "one follow-up for each alert of 2026-10-11.json" in text


def test_follow_up_verdict_must_follow_the_rule(tmp_path, csv_pack, capsys):
    output = with_follow_up(good_output())
    fu = output["follow_ups"][0]
    fu["moved"] = "no_change"
    fu["verdict"] = fu["verdict"].replace("Worse than when raised, though one week is a small sample.", "No real change.")
    code, text = run_with_earlier(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "[follow-up verdict follows the rule]" in text and "expected from CSV: worse" in text


def test_follow_up_after_must_be_the_seven_days_after_the_alert(tmp_path, csv_pack, capsys):
    output = with_follow_up(good_output())
    by_slug = {c["id"].rsplit(":", 1)[1]: c for c in output["follow_ups"][0]["checks"]}
    for slug in ("after", "after_numerator", "after_denominator"):
        by_slug[slug]["params"]["start"] = "2026-10-13"          # six days: 5 bills / 50 walk-ins, still 10.0%
    by_slug["after_numerator"]["value"], by_slug["after_numerator"]["display"] = 5, "5"
    by_slug["after_denominator"]["value"], by_slug["after_denominator"]["display"] = 50, "50"
    output["follow_ups"][0]["verdict"] = output["follow_ups"][0]["verdict"].replace("6 bills from 60", "5 bills from 50")
    code, text = run_with_earlier(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "[follow-up matches the earlier run]" in text and "kind=after" in text


def test_follow_up_before_must_be_the_figure_the_alert_showed(tmp_path, csv_pack, capsys):
    output = with_follow_up(good_output())
    output["follow_ups"][0]["before"] = 0.21
    code, text = run_with_earlier(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "kind=before" in text


def test_week_with_too_many_unusable_days_must_be_not_measurable(tmp_path, capsys):
    """Two of the seven days unusable (29%): the verdict may not report a move."""
    pack = make_pack(tmp_path / "pack")
    rows = (pack / "footfall_daily.csv").read_text(encoding="utf-8").replace("2026-10-13,S-01,10", "2026-10-13,S-01,0")
    (pack / "footfall_daily.csv").write_text(rows, encoding="utf-8")
    output = with_follow_up(good_output())
    code, text = run_with_earlier(tmp_path, pack, output, capsys)
    assert code == 1 and "expected from CSV: not_measurable (S-01: 2 of 7 store-days in the week are invalid)" in text


def test_two_cards_for_one_salesperson_fail(tmp_path, csv_pack, capsys):
    output = good_output()
    second = copy.deepcopy(output["cards"][0])
    second["card_id"] = "S-01:SP02:more_repeat"
    for check in second["checks"]:
        check["id"] += ":again"
    output["cards"].append(second)
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "[cards: one per salesperson] id=S-01:SP02:more_repeat" in text


def test_script_does_not_import_the_engine():
    import re
    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+engine\b", source, flags=re.M)
