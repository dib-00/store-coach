"""Figures are rounded half up exactly, as docs/CHECKS.md says, never a hair under the half."""
from __future__ import annotations

import pandas as pd

from engine.load import load
from engine.metrics import Metrics, rnd_div

from .synth import make_dataset


def test_exact_half_rounds_up():
    # 1,889 walk-ins on 28 valid days is 472.25 a week; a float division gives 472.24999...
    assert 1889 / 28 * 7 < 472.25
    assert rnd_div(1889 * 7, 28, 1) == 472.3
    assert rnd_div(927 * 7, 28, 1) == 231.8  # 231.75
    assert rnd_div(1, 160, 4) == 0.0063  # 0.00625
    assert rnd_div(9, 40, 2) == 0.23  # 0.225
    assert rnd_div(5, 2) == 3 and rnd_div(-5, 2) == -2  # half up, also below zero


def test_ordinary_values_are_unchanged():
    assert rnd_div(208, 1942, 4) == 0.1071
    assert rnd_div(13595, 28, 1) == 485.5
    assert rnd_div(26, 16, 2) == 1.63  # 1.625


def test_walkins_per_week_on_an_exact_half(tmp_path):
    folder = make_dataset(tmp_path / "pack")
    ff = pd.read_csv(folder / "footfall_daily.csv", dtype=str)
    window = (ff["store_id"] == "AAA-02") & (ff["date"] >= "2026-10-04") & (ff["date"] <= "2026-10-31")
    assert int(window.sum()) == 28
    values = ["67"] * 27 + ["80"]  # 1,889 walk-ins, every day still above its bills
    ff.loc[window, "footfall"] = values
    ff.to_csv(folder / "footfall_daily.csv", index=False)
    m = Metrics(load(folder, "2026-10-31"))
    p = {"store_ids": ["AAA-02"], "start": "2026-10-04", "end": "2026-10-31"}
    assert m.compute("valid_days", p) == 28 and m.compute("footfall_sum", {**p, "day_type": "all"}) == 1889
    assert m.compute("walkins_per_week", p) == 472.3
