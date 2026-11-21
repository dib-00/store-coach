"""Shared fixtures: a made-up data pack on disk and one engine run over it."""
from __future__ import annotations

import pytest

from engine.load import load
from engine.run import build_output

from .synth import make_dataset

STAMP = "2026-01-01T00:00:00Z"  # fixed generated_at, so outputs can be compared byte for byte


def run_engine(folder, as_of=None):
    """(output dict, notes) for one run."""
    return build_output(load(folder, as_of), STAMP)


@pytest.fixture(scope="session")
def pack(tmp_path_factory):
    return make_dataset(tmp_path_factory.mktemp("pack"))


@pytest.fixture(scope="session")
def result(pack):
    return run_engine(pack, "2026-10-31")


def alerts_of(output):
    return [a for block in output["area_managers"] for a in block["alerts"]]
