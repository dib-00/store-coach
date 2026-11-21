"""Follow-up: a week later, re-measure last week's alerts and say whether the number moved."""
from __future__ import annotations

from pathlib import Path

from .load import Data
from .metrics import Metrics


def follow_ups(m: Metrics, data: Data, runs_dir: Path) -> list[dict]:
    return []
