"""Lever 2, "bigger baskets" (items per bill). Plugs into engine/run.py.

Interface (the same for every lever module):
    detect(m)            -> (alert candidates, notes)   candidates are full Alert dicts, rank 0
    card_candidates(m)   -> list of card candidates     see engine/cards.py
    data_issues(m, windows) -> list of DataIssue dicts
Check kinds this lever adds are registered in metrics.EXTRA_KINDS and checks.EXTRA_DISPLAY.
"""
from __future__ import annotations

from .metrics import Metrics

LEVER = "bigger_baskets"


def detect(m: Metrics) -> tuple[list[dict], list[str]]:
    return [], []


def card_candidates(m: Metrics) -> list[dict]:
    return []


def data_issues(m: Metrics, windows: dict) -> list[dict]:
    return []
