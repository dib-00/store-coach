"""--as-of: the engine must not see anything dated after it."""
from __future__ import annotations

import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from engine.load import load
from engine.run import to_json

from .conftest import alerts_of, run_engine
from .synth import make_dataset

AS_OF = "2026-10-17"
REAL = Path(__file__).resolve().parents[1] / "data" / "csv"


def test_loader_drops_every_later_row(pack):
    data = load(pack, AS_OF)
    assert data.bills["bill_date"].max() <= AS_OF
    assert data.footfall["date"].max() <= AS_OF
    assert data.roster["date"].max() <= AS_OF
    assert data.salespeople["join_date"].max() <= AS_OF
    assert data.stores["opened_on"].max() <= AS_OF
    # the calendar is published in advance and is kept whole
    assert data.calendar["date"].max() > AS_OF


def test_as_of_run_equals_run_on_truncated_data(pack, tmp_path):
    full, _ = run_engine(pack, AS_OF)
    cut, _ = run_engine(make_dataset(tmp_path / "cut", end=date.fromisoformat(AS_OF)), AS_OF)
    assert to_json(full) == to_json(cut)
    assert alerts_of(full), "the comparison should cover a run that does raise an alert"


def test_rows_after_as_of_cannot_change_the_output(pack, tmp_path):
    clean, _ = run_engine(pack, AS_OF)
    poisoned_pack = make_dataset(tmp_path / "poisoned", poison_after=date.fromisoformat(AS_OF))
    poisoned, _ = run_engine(poisoned_pack, AS_OF)
    assert to_json(clean) == to_json(poisoned)
    # and the poison is real: without the cut-off the output does change
    later, _ = run_engine(poisoned_pack, "2026-10-31")
    unpoisoned_later, _ = run_engine(pack, "2026-10-31")
    assert to_json(later) != to_json(unpoisoned_later)


def test_default_as_of_is_the_last_bill_date(pack):
    assert load(pack).as_of == "2026-10-31"


def test_two_runs_are_byte_identical(pack):
    assert to_json(run_engine(pack, AS_OF)[0]) == to_json(run_engine(pack, AS_OF)[0])


@pytest.mark.skipif(not (REAL / "bills.csv").exists(), reason="real data pack not present")
def test_real_data_as_of_equals_truncated_copy(tmp_path):
    as_of = "2026-09-30"
    date_col = {"bills": "bill_date", "footfall_daily": "date", "roster_daily": "date",
                "salespeople": "join_date", "stores": "opened_on"}
    for name in ["stores", "area_managers", "salespeople", "roster_daily", "footfall_daily", "bills",
                 "bill_lines", "items", "calendar"]:
        if name in date_col:
            df = pd.read_csv(REAL / f"{name}.csv", dtype=str, keep_default_na=False)
            df[df[date_col[name]] <= as_of].to_csv(tmp_path / f"{name}.csv", index=False)
        else:
            shutil.copy(REAL / f"{name}.csv", tmp_path / f"{name}.csv")
    # bill_lines was copied whole: lines of later bills are orphans and must be ignored
    assert to_json(run_engine(REAL, as_of)[0]) == to_json(run_engine(tmp_path, as_of)[0])
