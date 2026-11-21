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
    Wed 21 Oct is a wedding date, so the busy days after as-of are 21, 24 and 25 Oct.
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
            ("SP03", "S-02", "Chitra C.", "2020-01-01")])
    _write(folder, "calendar", "date,state,festival,is_wedding_date",
           [(d, "Teststate", "", 1 if d == "2026-10-21" else 0) for d in _dates("2026-10-05", "2026-10-25")])

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
               {"state": "Teststate", "start": "2026-10-19", "end": "2026-10-25"},
               "2026-10-21, 2026-10-24, 2026-10-25", "Wed 21 Oct 2026, Sat 24 Oct 2026, Sun 25 Oct 2026"),
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
        "stores": [], "cards": [card], "follow_ups": [], "data_issues": [issue],
    }


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
    assert "16 checks recomputed, 0 mismatch" in text
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


def test_busy_dates_beyond_the_documented_7_days_fail(tmp_path, csv_pack, capsys):
    """Only the 7 days after as-of may be read from the future calendar."""
    output = good_output()
    check_of(output, ":busy")["params"]["end"] = "2026-10-27"
    code, text = run_verify(tmp_path, csv_pack, output, capsys)
    assert code == 1 and "the 7 days after as_of, 2026-10-19..2026-10-25" in text


def test_script_does_not_import_the_engine():
    import re
    source = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+engine", source, flags=re.M)
