"""Build Check objects (see web/lib/types.ts) and format figures for people."""
from __future__ import annotations

import re

from .metrics import Metrics, d, rnd

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def conv_tenths(value: float) -> int:
    """Conversion fraction (4 decimals) -> tenths of a percentage point, half up. 0.1054 -> 105."""
    return (int(round(value * 10000)) + 5) // 10


def fmt_pct(value: float) -> str:
    t = conv_tenths(value)
    return f"{t // 10}.{t % 10}%"


def rupees_at_stake(bench_conv: float, cur_conv: float, walkins: float, abv: float) -> int:
    """Rupees a week, from the figures exactly as displayed, so the worked line multiplies out by hand.

    Conversion to 0.1 of a percentage point, walk-ins to a whole number, bill value to a
    whole rupee; the result is rounded half up to the nearest Rs 100.
    """
    gap_tenths = conv_tenths(bench_conv) - conv_tenths(cur_conv)
    raw = gap_tenths * int(rnd(walkins)) * int(rnd(abv)) / 1000
    return int(rnd(raw / 100)) * 100


def fmt_int_in(n: int) -> str:
    """Indian digit grouping: 138600 -> 1,38,600."""
    s = str(abs(int(n)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return ("-" if n < 0 else "") + s


def fmt_inr(n: float) -> str:
    return "₹" + fmt_int_in(int(rnd(n)))


def fmt_date(s: str) -> str:
    x = d(s)
    return f"{x.day} {MONTHS[x.month - 1]} {x.year}"


def fmt_day(s: str) -> str:
    """Weekday, day and month: 'Sun 1 Nov'."""
    x = d(s)
    return f"{DAYS[x.weekday()]} {x.day} {MONTHS[x.month - 1]}"


def fmt_num(v: float, n: int) -> str:
    return f"{v:.{n}f}"


def display(kind: str, value) -> str:
    if value is None:
        return "not available"
    if kind == "conversion":
        return fmt_pct(value)
    if kind in ("avg_bill_value", "rupees_at_stake"):
        return fmt_inr(value)
    if kind in ("bills_count", "footfall_sum"):
        return fmt_int_in(value)
    if kind == "walkins_per_week":
        return fmt_int_in(int(rnd(value)))
    if kind == "last_roster_date":
        return fmt_date(value)
    if kind in ("bills_per_present_day", "peer_median_bills_per_present_day", "two_proportion_z"):
        return fmt_num(value, 2)
    if kind == "footfall_per_present_staff":
        return fmt_num(value, 1)
    if kind == "peer_median_present_days":
        s = fmt_num(value, 1)
        return s[:-2] if s.endswith(".0") else s
    if kind == "upcoming_busy_dates":
        return ", ".join(fmt_day(x) + " " + x[:4] for x in value.split(", ")) if value else "none"
    return str(value)


class CheckBook:
    """Collects the checks of one alert / store / data issue, with ids unique in the file."""

    def __init__(self, metrics: Metrics, prefix: str):
        self.m = metrics
        self.prefix = prefix
        self.items: list[dict] = []
        self._ids: set[str] = set()

    def add(self, slug: str, label: str, kind: str, params: dict, value=None) -> dict:
        """Compute `kind` with `params` (unless a value is supplied) and record it."""
        if value is None:
            value = self.m.compute(kind, params)
        cid = f"{self.prefix}:{slug}"
        if cid in self._ids:
            raise ValueError(f"duplicate check id {cid}")
        self._ids.add(cid)
        check = {
            "id": cid,
            "label": label,
            "kind": kind,
            "params": params,
            "value": value,
            "display": display(kind, value),
        }
        self.items.append(check)
        return check

    def usable(self) -> bool:
        return all(c["value"] is not None for c in self.items)


_ID_RE = re.compile(r"\b[A-Z]{2,4}-\d+\b|\bSP\d+\b")
_NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


def number_tokens(text: str) -> list[str]:
    """Numbers quoted in a sentence, ignoring store and salesperson ids."""
    return [t.rstrip(",") for t in _NUM_RE.findall(_ID_RE.sub(" ", text))]


def numbers_not_in_checks(texts: list[str], checks: list[dict]) -> list[str]:
    """Every number shown in an alert's text must be the display of one of its checks."""
    known: set[str] = set()
    for c in checks:
        known.update(number_tokens(c["display"]))
    return [t for text in texts for t in number_tokens(text) if t not in known]
