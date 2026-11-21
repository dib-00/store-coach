"""Follow-up: a week later the number is re-measured, honestly, and never with later data."""
from __future__ import annotations

import json
import math
from datetime import date

import pandas as pd
import pytest

from engine.checks import numbers_not_in_checks
from engine.followup import classify, rate_standard_error
from engine.load import load
from engine.run import build_output, main, to_json

from .conftest import STAMP, alerts_of
from .synth import make_dataset

RAISED, MEASURED = "2026-10-17", "2026-10-24"  # the alert at AAA-01 is raised on the 17th
WEEK = ("2026-10-18", "2026-10-24")


def run(folder, as_of, runs_dir=None):
    return build_output(load(folder, as_of), STAMP, runs_dir)[0]


def write_run(runs_dir, output):
    runs_dir.mkdir(parents=True, exist_ok=True)
    with open(runs_dir / f"{output['as_of']}.json", "w", encoding="utf-8", newline="\n") as f:
        f.write(to_json(output))


@pytest.fixture()
def runs(pack, tmp_path):
    """A runs folder holding the run of a week earlier."""
    runs_dir = tmp_path / "runs"
    write_run(runs_dir, run(pack, RAISED))
    return runs_dir


def scale_footfall(folder, store, start, end, factor):
    ff = pd.read_csv(folder / "footfall_daily.csv", dtype=str)
    hit = (ff["store_id"] == store) & (ff["date"] >= start) & (ff["date"] <= end)
    ff.loc[hit, "footfall"] = [str(int(int(x) * factor)) for x in ff.loc[hit, "footfall"]]
    ff.to_csv(folder / "footfall_daily.csv", index=False)


# ------------------------------------------------------------ the verdict rule
def test_moved_needs_a_change_of_at_least_the_noise():
    assert classify(0.107, 0.119, 0.010) == "improved"
    assert classify(0.107, 0.095, 0.010) == "worse"
    assert classify(0.107, 0.112, 0.010) == "no_change"
    assert classify(0.107, 0.102, 0.010) == "no_change"
    assert classify(0.107, 0.117, 0.010) == "improved"  # exactly one standard error counts
    assert classify(0.107, 0.107, 0.0) == "no_change"
    # a measure where lower is better is read the other way round
    assert classify(0.30, 0.20, 0.05, higher_is_better=False) == "improved"
    assert classify(0.30, 0.40, 0.05, higher_is_better=False) == "worse"


def test_standard_error_of_a_rate_on_a_count():
    assert rate_standard_error(31, 260) == pytest.approx(math.sqrt(31 / 260 * (1 - 31 / 260) / 260))
    assert rate_standard_error(0, 0) is None


# ------------------------------------------------------------- the follow-up
def test_no_earlier_run_means_no_follow_up(pack, tmp_path):
    assert run(pack, MEASURED, tmp_path / "empty")["follow_ups"] == []
    assert run(pack, MEASURED)["follow_ups"] == []


def test_every_alert_of_a_week_earlier_is_followed_up(pack, runs):
    earlier = alerts_of(run(pack, RAISED))
    assert [a["alert_id"] for a in earlier] == ["AAA-01:more_bills:missed_shifts"]
    alert = earlier[0]
    out = run(pack, MEASURED, runs)
    assert len(out["follow_ups"]) == 1
    f = out["follow_ups"][0]
    assert f["alert_id"] == alert["alert_id"] and f["area_manager_id"] == "AM-01"
    assert f["headline"] == alert["headline"] and f["action_text"] == alert["action"]["text"]
    assert (f["raised_as_of"], f["measured_as_of"]) == (RAISED, MEASURED)
    assert f["definition"] == alert["definition"]
    # before and target are the alert's own figures, shown the way the alert showed them
    shown = {c["id"].rsplit(":", 1)[1]: c["display"] for c in alert["checks"]}
    assert f["before"] == alert["follow_up"]["baseline_value"] and f["before_display"] == shown["conv_current"]
    assert f["target"] == alert["follow_up"]["target_value"] and f["target_display"] == shown["conv_benchmark"]
    # after is the same recipe on the 7 days after the alert, and only those days
    by_slug = {c["id"].rsplit(":", 1)[1]: c for c in f["checks"]}
    assert by_slug["after"]["params"] == {"store_ids": ["AAA-01"], "start": WEEK[0], "end": WEEK[1], "day_type": "all"}
    assert by_slug["days"]["value"] == 7
    # by hand from the CSVs: 5 weekdays of 13 bills from 100 walk-ins, 2 weekend days of 9 from 150
    bills = pd.read_csv(pack / "bills.csv", dtype=str)
    ff = pd.read_csv(pack / "footfall_daily.csv", dtype=str)
    n_bills = int(((bills["store_id"] == "AAA-01") & bills["bill_date"].between(*WEEK)).sum())
    n_walk = int(ff[(ff["store_id"] == "AAA-01") & ff["date"].between(*WEEK)]["footfall"].astype(int).sum())
    assert (n_bills, n_walk) == (83, 800)
    assert by_slug["after_numerator"]["value"] == 83 and by_slug["after_denominator"]["value"] == 800
    assert f["after"] == pytest.approx(83 / 800, abs=0.00006)
    # nothing changed in the made-up store, and the follow-up says so
    assert f["moved"] == "no_change" and f["after"] == f["before"] and "No change in the week after." in f["verdict"]
    assert "83 bills from 800 walk-ins" in f["verdict"]


def test_every_number_in_the_verdict_has_a_check(pack, runs):
    for f in run(pack, MEASURED, runs)["follow_ups"]:
        assert numbers_not_in_checks([f["verdict"]], f["checks"]) == []
        ids = [c["id"] for c in f["checks"]]
        assert len(ids) == len(set(ids)) and all(i.startswith("followup:") for i in ids)
        shown = {c["display"] for c in f["checks"]}
        assert {f["before_display"], f["after_display"], f["target_display"]} <= shown


def test_verdict_never_credits_the_action(pack, runs):
    for f in run(pack, MEASURED, runs)["follow_ups"]:
        low = f["verdict"].lower()
        assert not any(w in low for w in ("because of", "thanks to", "worked", "due to the action", "as a result"))


@pytest.mark.parametrize("factor, moved", [(0.5, "improved"), (2, "worse")])
def test_a_real_move_is_reported_either_way(tmp_path, runs, factor, moved):
    folder = make_dataset(tmp_path / "pack")
    scale_footfall(folder, "AAA-01", *WEEK, factor)  # same bills from half / twice the walk-ins
    f = run(folder, MEASURED, runs)["follow_ups"][0]
    assert f["moved"] == moved
    assert f["after"] == pytest.approx(83 / (800 * factor), abs=0.00006)
    assert ("Improved" if moved == "improved" else "Worse") in f["verdict"]


def test_unusable_footfall_is_not_measurable_not_a_guess(tmp_path, runs):
    folder = make_dataset(tmp_path / "pack")
    scale_footfall(folder, "AAA-01", "2026-10-18", "2026-10-20", 0)  # 3 of the 7 days: door counter reads 0
    f = run(folder, MEASURED, runs)["follow_ups"][0]
    assert f["moved"] == "not_measurable" and f["after"] is None and f["after_display"] == "not measurable"
    assert "cannot be measured" in f["verdict"] and "door counter" in f["verdict"]
    assert numbers_not_in_checks([f["verdict"]], f["checks"]) == []


def test_unknown_measure_or_a_wrong_file_never_crashes(pack, tmp_path):
    earlier = run(pack, RAISED)
    alert = alerts_of(earlier)[0]
    alert["follow_up"]["kind"] = "no_such_measure"
    runs_dir = tmp_path / "runs"
    write_run(runs_dir, earlier)
    f = run(pack, MEASURED, runs_dir)["follow_ups"][0]
    assert f["moved"] == "not_measurable" and f["after"] is None
    assert numbers_not_in_checks([f["verdict"]], f["checks"]) == []
    # a file that is not the run of exactly a week earlier is ignored
    earlier["as_of"] = "2026-10-10"
    with open(runs_dir / f"{RAISED}.json", "w", encoding="utf-8") as fh:
        fh.write(to_json(earlier))
    assert run(pack, MEASURED, runs_dir)["follow_ups"] == []
    (runs_dir / f"{RAISED}.json").write_text("not json", encoding="utf-8")
    assert run(pack, MEASURED, runs_dir)["follow_ups"] == []


# ------------------------------------------------------- nothing after as-of
def test_follow_up_cannot_see_data_after_as_of(pack, tmp_path, runs):
    clean = run(pack, MEASURED, runs)
    poisoned_pack = make_dataset(tmp_path / "poisoned", poison_after=date.fromisoformat(MEASURED))
    poisoned = run(poisoned_pack, MEASURED, runs)
    assert clean["follow_ups"] and to_json(clean) == to_json(poisoned)
    for f in clean["follow_ups"]:
        for c in f["checks"]:
            assert all(v <= MEASURED for k, v in c["params"].items() if k in ("start", "end", "base_end"))


def test_earlier_run_is_identical_whether_or_not_later_rows_exist(pack, tmp_path):
    with_later_rows = run(pack, RAISED, tmp_path / "runs")  # the pack runs to 31 Oct
    truncated = run(make_dataset(tmp_path / "cut", end=date.fromisoformat(RAISED)), RAISED, tmp_path / "runs")
    poisoned = run(make_dataset(tmp_path / "poisoned", poison_after=date.fromisoformat(RAISED)), RAISED, tmp_path / "runs")
    assert to_json(with_later_rows) == to_json(truncated) == to_json(poisoned)
    assert alerts_of(with_later_rows)


# ------------------------------------------------------------ the command line
def test_dated_only_writes_the_dated_run_and_leaves_latest_alone(pack, tmp_path, capsys):
    out = tmp_path / "out"
    args = ["--data-dir", str(pack), "--out-dir", str(out), "--generated-at", STAMP]
    assert main(["--as-of", RAISED, "--dated-only", *args]) == 0
    assert (out / "runs" / f"{RAISED}.json").is_file() and not (out / "latest.json").exists()

    assert main(["--as-of", MEASURED, *args]) == 0
    latest = (out / "latest.json").read_bytes()
    assert latest == (out / "runs" / f"{MEASURED}.json").read_bytes()
    data = json.loads(latest)
    assert data["as_of"] == MEASURED
    assert [f["alert_id"] for f in data["follow_ups"]] == ["AAA-01:more_bills:missed_shifts"]

    assert main(["--as-of", RAISED, "--dated-only", *args]) == 0  # rebuilding the earlier week again
    assert (out / "latest.json").read_bytes() == latest
    assert json.loads((out / "runs" / f"{RAISED}.json").read_text(encoding="utf-8"))["follow_ups"] == []
    capsys.readouterr()
