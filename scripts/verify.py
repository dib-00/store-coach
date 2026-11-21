#!/usr/bin/env python
"""Independent verification of the engine's output.

Recomputes every Check in web/public/data/latest.json straight from the raw CSVs and
checks the rules the output must obey. It is written from docs/CHECKS.md (and
docs/CHECKS-*.md) alone: it imports nothing from engine/ and shares no code with it.

    python -X utf8 scripts/verify.py                      # latest.json against data/csv
    python -X utf8 scripts/verify.py --file F --data-dir D
    python -X utf8 scripts/verify.py --strict             # warnings also fail

Exit code: 0 only when everything matches. 1 on any mismatch, any broken rule, or any
check kind this script has no recipe for (an unknown kind is a failure, never a skip).
2 when it could not run at all (a file is missing or unreadable).

TOLERANCE. Every figure is worked out in exact fractions and rounded half up to the
number of decimals the recipe documents. The JSON value must then equal it to within
1e-9, which only absorbs how a decimal is stored as a float. Whole numbers, dates and
names must be equal. Nothing is "close enough".

HOW TO ADD A KIND. Write one function below and decorate it:

    @recipe("my_kind", required=("store_ids", "start", "end"), optional=("day_type",),
            display=fmt_whole)
    def my_kind(d, p, ctx):
        ...
        return value        # int, Fraction (already rounded with rhu) or str

`d` is the loaded CSV pack (class Data), `p` the check's params, `ctx` gives access to
the sibling checks of the same alert or card (ctx.value_of(check_id)). Raise
CannotCompute("why") when the recipe has no answer. Nothing else needs touching.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from fractions import Fraction
from pathlib import Path

import pandas as pd

TOL = 1e-9
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
CHECK_KEYS = ("id", "kind", "params", "value", "display")
ROOT = Path(__file__).resolve().parent.parent


class CannotRun(Exception):
    """The script cannot start (missing file, unreadable CSV). Exit code 2."""


class CannotCompute(Exception):
    """A recipe has no answer for these params. Reported as a mismatch."""


# --------------------------------------------------------------------------- helpers

def rhu(x, n=0):
    """Round half up to n decimals, exactly: floor(x * 10^n + 0.5) / 10^n."""
    scale = Fraction(10) ** n
    return Fraction(math.floor(Fraction(x) * scale + Fraction(1, 2))) / scale


def to_date(iso):
    if not isinstance(iso, str) or not ISO.fullmatch(iso):
        raise CannotCompute(f"not a YYYY-MM-DD date: {iso!r}")
    try:
        return date.fromisoformat(iso)
    except ValueError:
        raise CannotCompute(f"not a real date: {iso!r}")


def days(start, end):
    """ISO dates from start to end, both inclusive."""
    a, b = to_date(start), to_date(end)
    if a > b:
        raise CannotCompute(f"window starts after it ends: {start}..{end}")
    return [(a + timedelta(n)).isoformat() for n in range((b - a).days + 1)]


def weekday(iso):
    return WEEKDAYS[to_date(iso).weekday()]


def median(values):
    v = sorted(values)
    if not v:
        raise CannotCompute("median of nothing")
    mid = len(v) // 2
    return Fraction(v[mid]) if len(v) % 2 else Fraction(v[mid - 1] + v[mid], 2)


def as_fraction(value):
    """The JSON number exactly as written (0.1071 is 1071/10000, not a binary float)."""
    return Fraction(str(value))


# --------------------------------------------------------------------------- display

def indian(n):
    """Whole number with Indian digit grouping: 122600 -> 1,22,600."""
    n = int(n)
    sign, s = ("-" if n < 0 else ""), str(abs(n))
    if len(s) <= 3:
        return sign + s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    parts.insert(0, head)
    return sign + ",".join(parts) + "," + tail


def fixed(x, n):
    r = rhu(abs(Fraction(x)), n)
    whole, frac = divmod(r.numerator * 10 ** n // r.denominator, 10 ** n)
    sign = "-" if x < 0 and r != 0 else ""
    return f"{sign}{whole}.{frac:0{n}d}" if n else f"{sign}{whole}"


def fmt_plain(v):
    if isinstance(v, float) and v == int(v):
        return {str(v), str(int(v))}
    return str(v)


def fmt_percent1(v):
    return fixed(as_fraction(v) * 100, 1) + "%"


def fmt_rupees(v):
    return "₹" + indian(rhu(as_fraction(v)))


def fmt_whole(v):
    return indian(rhu(as_fraction(v)))


def fmt_2dp(v):
    return fixed(as_fraction(v), 2)


def fmt_1dp(v):
    return fixed(as_fraction(v), 1)


def fmt_1dp_trim(v):
    s = fixed(as_fraction(v), 1)
    return s[:-2] if s.endswith(".0") else s


def fmt_day(iso):
    d = to_date(iso)
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def fmt_day_list(v):
    if v == "":
        return ""
    return ", ".join(f"{weekday(i)[:3]} {fmt_day(i)}" for i in v.split(", "))


# --------------------------------------------------------------------------- the CSVs

class Data:
    """The raw CSV pack, read as text and cut at as_of (docs/CHECKS.md section 1)."""

    def __init__(self, folder, as_of):
        self.folder, self.as_of = Path(folder), as_of
        self.notes = []
        to_date_or_die = lambda s, what: self._check_dates(s, what)

        stores = self.read("stores")
        people = self.read("salespeople")
        bills = self.read("bills")
        lines = self.read("bill_lines")
        footfall = self.read("footfall_daily")
        roster = self.read("roster_daily")
        calendar = self.read("calendar")
        self.area_managers = self.read("area_managers")

        to_date_or_die(stores["opened_on"], "stores.opened_on")
        to_date_or_die(people["join_date"], "salespeople.join_date")
        to_date_or_die(bills["bill_date"], "bills.bill_date")
        to_date_or_die(footfall["date"], "footfall_daily.date")
        to_date_or_die(roster["date"], "roster_daily.date")
        to_date_or_die(calendar["date"], "calendar.date")

        # The as-of cut. The calendar is not cut.
        self.rows_after_as_of = {
            "bills": int((bills["bill_date"] > as_of).sum()),
            "footfall_daily": int((footfall["date"] > as_of).sum()),
            "roster_daily": int((roster["date"] > as_of).sum()),
            "salespeople": int((people["join_date"] > as_of).sum()),
            "stores": int((stores["opened_on"] > as_of).sum()),
        }
        stores = stores[stores["opened_on"] <= as_of]
        people = people[people["join_date"] <= as_of]
        bills = bills[bills["bill_date"] <= as_of]
        lines = lines[lines["bill_id"].isin(set(bills["bill_id"]))]
        footfall = footfall[footfall["date"] <= as_of]
        roster = roster[roster["date"] <= as_of]

        self.stores = stores
        self.people = people
        self.state_of_store = dict(zip(stores["store_id"], stores["state"]))
        self.store_of_person = dict(zip(people["salesperson_id"], people["store_id"]))
        self.name_of_person = dict(zip(people["salesperson_id"], people["name"]))
        self.people_of_store = defaultdict(list)
        for sp, st in self.store_of_person.items():
            self.people_of_store[st].append(sp)

        # footfall: (store, date) -> whole number, or None when blank
        if footfall.duplicated(["store_id", "date"]).any():
            raise CannotRun("footfall_daily has two rows for one store and date; "
                            "docs/CHECKS.md does not say how to combine them")
        self.footfall = {}
        for st, dt, raw in zip(footfall["store_id"], footfall["date"], footfall["footfall"]):
            raw = raw.strip()
            try:
                self.footfall[(st, dt)] = None if raw == "" else Fraction(raw)
            except ValueError:
                raise CannotRun(f"footfall_daily: footfall {raw!r} is not a number ({st}, {dt})")

        # bills: (store, date) -> bill ids; salesperson -> Counter of bill dates
        self.bills_on = defaultdict(list)
        self.bill_dates_of_person = defaultdict(Counter)
        for bid, dt, st, sp in zip(bills["bill_id"], bills["bill_date"], bills["store_id"],
                                   bills["salesperson_id"]):
            self.bills_on[(st, dt)].append(bid)
            self.bill_dates_of_person[sp][dt] += 1

        # bill value in paise (whole numbers, so sums are exact)
        try:
            paise = pd.to_numeric(lines["qty"]) * pd.to_numeric(lines["selling_price"]) * 100
        except (ValueError, TypeError) as exc:
            raise CannotRun(f"bill_lines: qty or selling_price is not a number ({exc})")
        if len(paise) and (paise - paise.round()).abs().max() > 1e-6:
            raise CannotRun("bill_lines: qty × selling_price has more than 2 decimals")
        totals = paise.round().astype("int64").groupby(lines["bill_id"]).sum()
        self.bill_paise = {k: int(v) for k, v in totals.items()}

        # roster: person -> date -> [status]; store (roster.store_id) -> date -> [status]
        self.roster_of_person = defaultdict(lambda: defaultdict(list))
        self.roster_of_store = defaultdict(lambda: defaultdict(list))
        moved = 0
        for dt, st, sp, status in zip(roster["date"], roster["store_id"],
                                      roster["salesperson_id"], roster["status"]):
            self.roster_of_person[sp][dt].append(status)
            self.roster_of_store[st][dt].append(status)
            if self.store_of_person.get(sp, st) != st:
                moved += 1
        if moved:
            self.notes.append(
                f"{moved} roster rows carry a store_id different from the person's store in "
                "salespeople.csv. median_staff_present and footfall_per_present_staff say "
                "'the store has a roster row' without saying which of the two store ids is "
                "meant; this script uses roster_daily.store_id.")

        # calendar: (date, state) -> busy flag from festival / wedding
        self.calendar = {}
        for dt, state, fest, wed in zip(calendar["date"], calendar["state"],
                                        calendar["festival"], calendar["is_wedding_date"]):
            try:
                wedding = wed.strip() != "" and float(wed) == 1
            except ValueError:
                wedding = False
            self.calendar[(dt, state)] = fest.strip() != "" or wedding

    def read(self, name, required=True):
        path = self.folder / f"{name}.csv"
        if not path.exists():
            if required:
                raise CannotRun(f"missing CSV: {path}")
            return None
        try:
            return pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False,
                               encoding="utf-8-sig")
        except Exception as exc:  # unreadable file
            raise CannotRun(f"cannot read {path}: {exc}")

    @staticmethod
    def _check_dates(series, what):
        bad = series[~series.str.fullmatch(ISO.pattern)]
        if len(bad):
            raise CannotRun(f"{what} has values that are not YYYY-MM-DD, e.g. {bad.iloc[0]!r}")

    # ---- shared rules of section 1

    def is_busy(self, state, iso):
        return to_date(iso).weekday() >= 5 or self.calendar.get((iso, state), False)

    def of_day_type(self, state, iso, day_type):
        if day_type == "all":
            return True
        if day_type == "busy":
            return self.is_busy(state, iso)
        if day_type == "normal":
            return not self.is_busy(state, iso)
        raise CannotCompute(f"unknown day_type {day_type!r}")

    def state(self, store_id):
        if store_id not in self.state_of_store:
            raise CannotCompute(f"store {store_id!r} is not in stores.csv as of {self.as_of}")
        return self.state_of_store[store_id]

    def person_state(self, sp):
        if sp not in self.store_of_person:
            raise CannotCompute(f"salesperson {sp!r} is not in salespeople.csv as of {self.as_of}")
        return self.state(self.store_of_person[sp])

    def store_days(self, store_ids, start, end, day_type="all"):
        """(store, date, footfall or None, bills, reason) for every store-day in the window.

        reason is None for a valid store-day, else footfall_zero or bills_exceed_footfall.
        """
        if not isinstance(store_ids, list) or not store_ids:
            raise CannotCompute("store_ids must be a non-empty list")
        out = []
        for st in store_ids:
            state = self.state(st)
            for dt in days(start, end):
                has_row = (st, dt) in self.footfall
                n_bills = len(self.bills_on.get((st, dt), ()))
                if not has_row and n_bills == 0:
                    continue  # not a store-day
                if not self.of_day_type(state, dt, day_type):
                    continue
                ff = self.footfall.get((st, dt))
                if ff is None or ff <= 0:
                    reason = "footfall_zero"
                elif n_bills > ff:
                    reason = "bills_exceed_footfall"
                else:
                    reason = None
                out.append((st, dt, ff, n_bills, reason))
        return out

    def valid_days(self, store_ids, start, end, day_type="all"):
        return [r for r in self.store_days(store_ids, start, end, day_type) if r[4] is None]

    def invalid_days(self, store_ids, start, end, rule="any"):
        if rule not in ("any", "footfall_zero", "bills_exceed_footfall"):
            raise CannotCompute(f"unknown rule {rule!r}")
        return [r for r in self.store_days(store_ids, start, end)
                if r[4] is not None and rule in ("any", r[4])]

    def present_days(self, sp, start, end, day_type="all"):
        state = self.person_state(sp)
        rows = self.roster_of_person.get(sp, {})
        return sum(rows.get(dt, []).count("Present") for dt in days(start, end)
                   if self.of_day_type(state, dt, day_type))

    def bills_per_present_day(self, sp, start, end):
        """Unrounded bills ÷ present days for one person."""
        self.person_state(sp)
        present = self.present_days(sp, start, end)
        if present == 0:
            raise CannotCompute(f"{sp} has no Present day in {start}..{end}")
        made = self.bill_dates_of_person.get(sp, {})
        return Fraction(sum(made.get(dt, 0) for dt in days(start, end)), present)

    def peers(self, store_id, exclude):
        self.state(store_id)
        if not isinstance(exclude, list):
            raise CannotCompute("exclude_salesperson_ids must be a list")
        return sorted(sp for sp in self.people_of_store.get(store_id, []) if sp not in exclude)


# --------------------------------------------------------------------------- registry

class Recipe:
    def __init__(self, kind, fn, required, optional, display, rupees_step):
        self.kind, self.fn = kind, fn
        self.required, self.optional = set(required), set(optional)
        self.display, self.rupees_step = display, rupees_step


RECIPES = {}


def recipe(kind, required, optional=(), display=fmt_plain, rupees_step=None):
    """Register the recompute function for one check kind.

    rupees_step: set it (e.g. 100) on the kind that carries an alert's rupees at stake;
    it is the step the figure is rounded to.
    """
    def register(fn):
        if kind in RECIPES:
            raise RuntimeError(f"two recipes for kind {kind!r}")
        RECIPES[kind] = Recipe(kind, fn, required, optional, display, rupees_step)
        return fn
    return register


# ---- section 2: store measures

def _bills_and_footfall(d, p):
    rows = d.valid_days(p["store_ids"], p["start"], p["end"], p.get("day_type", "all"))
    return sum(r[3] for r in rows), sum(r[2] for r in rows)


@recipe("bills_count", ("store_ids", "start", "end"), ("day_type",), fmt_whole)
def bills_count(d, p, ctx):
    return _bills_and_footfall(d, p)[0]


@recipe("footfall_sum", ("store_ids", "start", "end"), ("day_type",), fmt_whole)
def footfall_sum(d, p, ctx):
    return _bills_and_footfall(d, p)[1]


@recipe("conversion", ("store_ids", "start", "end"), ("day_type",), fmt_percent1)
def conversion(d, p, ctx):
    b, n = _bills_and_footfall(d, p)
    if n == 0:
        raise CannotCompute("no walk-ins on valid store-days in the window")
    return rhu(Fraction(b) / n, 4)


@recipe("avg_bill_value", ("store_ids", "start", "end"), (), fmt_rupees)
def avg_bill_value(d, p, ctx):
    ids = [b for st, dt, *_ in d.valid_days(p["store_ids"], p["start"], p["end"])
           for b in d.bills_on.get((st, dt), ())]
    if not ids:
        raise CannotCompute("no bills on valid store-days in the window")
    return rhu(Fraction(sum(d.bill_paise.get(b, 0) for b in ids), 100 * len(ids)), 2)


@recipe("walkins_per_week", ("store_ids", "start", "end"), (), fmt_whole)
def walkins_per_week(d, p, ctx):
    total = Fraction(0)
    for st in p["store_ids"]:
        rows = d.valid_days([st], p["start"], p["end"])
        if not rows:
            raise CannotCompute(f"{st} has no valid store-day in the window")
        total += Fraction(sum(r[2] for r in rows), len(rows)) * 7
    return rhu(total, 1)


@recipe("valid_days", ("store_ids", "start", "end"))
def valid_days(d, p, ctx):
    return len(d.valid_days(p["store_ids"], p["start"], p["end"]))


@recipe("invalid_days", ("store_ids", "start", "end"), ("rule",))
def invalid_days(d, p, ctx):
    return len(d.invalid_days(p["store_ids"], p["start"], p["end"], p.get("rule", "any")))


@recipe("bills_on_invalid_days", ("store_ids", "start", "end"), ("rule",))
def bills_on_invalid_days(d, p, ctx):
    return sum(r[3] for r in d.invalid_days(p["store_ids"], p["start"], p["end"],
                                            p.get("rule", "any")))


@recipe("two_proportion_z", ("store_ids", "start", "end", "base_start", "base_end"),
        ("day_type",), fmt_2dp)
def two_proportion_z(d, p, ctx):
    b1, n1 = _bills_and_footfall(d, p)
    b0, n0 = _bills_and_footfall(d, dict(p, start=p["base_start"], end=p["base_end"]))
    if n1 == 0 or n0 == 0:
        raise CannotCompute("a window has no walk-ins on valid store-days")
    pooled = Fraction(b1 + b0) / (n1 + n0)
    variance = pooled * (1 - pooled) * (Fraction(1) / n1 + Fraction(1) / n0)
    if variance <= 0:
        raise CannotCompute("standard error is zero")
    z = float(Fraction(b1) / n1 - Fraction(b0) / n0) / math.sqrt(float(variance))
    return rhu(Fraction(z), 2)


@recipe("quietest_weekday", ("store_id", "start", "end"))
def quietest_weekday(d, p, ctx):
    by_day = defaultdict(list)
    for _, dt, ff, _, _ in d.valid_days([p["store_id"]], p["start"], p["end"]):
        by_day[weekday(dt)].append(ff)
    if not by_day:
        raise CannotCompute("no valid store-day in the window")
    # min() keeps the first of equal means, and WEEKDAYS is in Monday-first order
    return min((w for w in WEEKDAYS if w in by_day),
               key=lambda w: Fraction(sum(by_day[w]), len(by_day[w])))


@recipe("day_count", ("state", "start", "end"), ("day_type",))
def day_count(d, p, ctx):
    return sum(d.of_day_type(p["state"], dt, p.get("day_type", "all"))
               for dt in days(p["start"], p["end"]))


@recipe("upcoming_busy_dates", ("state", "start", "end"), (), fmt_day_list)
def upcoming_busy_dates(d, p, ctx):
    as_of = to_date(d.as_of)
    want = ((as_of + timedelta(1)).isoformat(), (as_of + timedelta(7)).isoformat())
    if (p["start"], p["end"]) != want:
        raise CannotCompute(f"window must be the 7 days after as_of, {want[0]}..{want[1]}")
    return ", ".join(dt for dt in days(p["start"], p["end"]) if d.is_busy(p["state"], dt))


# ---- section 3: people measures

@recipe("present_days", ("salesperson_id", "start", "end"), ("day_type",))
def present_days(d, p, ctx):
    return d.present_days(p["salesperson_id"], p["start"], p["end"], p.get("day_type", "all"))


@recipe("peer_median_present_days", ("store_id", "exclude_salesperson_ids", "start", "end"),
        ("day_type",), fmt_1dp_trim)
def peer_median_present_days(d, p, ctx):
    window = days(p["start"], p["end"])
    day_type = p.get("day_type", "all")
    peers = [sp for sp in d.peers(p["store_id"], p["exclude_salesperson_ids"])
             if all(d.roster_of_person.get(sp, {}).get(dt) for dt in window)]
    if not peers:
        raise CannotCompute("no colleague is on the roster on every date of the window")
    return rhu(median(d.present_days(sp, p["start"], p["end"], day_type) for sp in peers), 1)


@recipe("last_roster_date", ("salesperson_id", "as_of"), (), fmt_day)
def last_roster_date(d, p, ctx):
    d.person_state(p["salesperson_id"])
    to_date(p["as_of"])
    dates = [dt for dt in d.roster_of_person.get(p["salesperson_id"], {}) if dt <= p["as_of"]]
    if not dates:
        raise CannotCompute("no roster row on or before as_of")
    return max(dates)


@recipe("bills_per_present_day", ("salesperson_id", "start", "end"), (), fmt_2dp)
def bills_per_present_day(d, p, ctx):
    return rhu(d.bills_per_present_day(p["salesperson_id"], p["start"], p["end"]), 2)


@recipe("peer_median_bills_per_present_day",
        ("store_id", "exclude_salesperson_ids", "start", "end", "min_present_days"), (), fmt_2dp)
def peer_median_bills_per_present_day(d, p, ctx):
    peers = [sp for sp in d.peers(p["store_id"], p["exclude_salesperson_ids"])
             if d.present_days(sp, p["start"], p["end"]) >= p["min_present_days"]]
    if not peers:
        raise CannotCompute("no colleague with enough present days")
    return rhu(median(d.bills_per_present_day(sp, p["start"], p["end"]) for sp in peers), 2)


@recipe("usual_off_weekday", ("salesperson_id", "start", "end"))
def usual_off_weekday(d, p, ctx):
    d.person_state(p["salesperson_id"])
    rows = d.roster_of_person.get(p["salesperson_id"], {})
    offs = Counter()
    for dt in days(p["start"], p["end"]):
        offs[weekday(dt)] += rows.get(dt, []).count("Off")
    if not sum(offs.values()):
        raise CannotCompute("no Off row in the window")
    return max(WEEKDAYS, key=lambda w: offs[w])  # max() keeps the first (earlier) of a tie


@recipe("rostered_staff", ("store_id", "date"))
def rostered_staff(d, p, ctx):
    to_date(p["date"])
    return sum(1 for sp in d.peers(p["store_id"], [])
               if d.roster_of_person.get(sp, {}).get(p["date"]))


@recipe("median_staff_present", ("store_id", "start", "end"), ("day_type",))
def median_staff_present(d, p, ctx):
    state = d.state(p["store_id"])
    rows = d.roster_of_store.get(p["store_id"], {})
    daily = [rows[dt].count("Present") for dt in days(p["start"], p["end"])
             if rows.get(dt) and d.of_day_type(state, dt, p.get("day_type", "all"))]
    if not daily:
        raise CannotCompute("the store has no roster row in the window")
    return int(rhu(median(daily)))


@recipe("footfall_per_present_staff", ("store_id", "start", "end"), ("day_type",), fmt_1dp)
def footfall_per_present_staff(d, p, ctx):
    rows = d.roster_of_store.get(p["store_id"], {})
    walkins = present = 0
    for _, dt, ff, _, _ in d.valid_days([p["store_id"]], p["start"], p["end"],
                                        p.get("day_type", "all")):
        if rows.get(dt):
            walkins += ff
            present += rows[dt].count("Present")
    if present == 0:
        raise CannotCompute("nobody Present on the valid store-days of the window")
    return rhu(Fraction(walkins) / present, 1)


# ---- section 4: rupees at stake

@recipe("rupees_at_stake",
        ("benchmark_check_id", "current_check_id", "walkins_check_id", "avg_bill_check_id"),
        (), fmt_rupees, rupees_step=100)
def rupees_at_stake(d, p, ctx):
    bench = rhu(ctx.value_of(p["benchmark_check_id"], "conversion") * 1000)   # tenths of a point
    current = rhu(ctx.value_of(p["current_check_id"], "conversion") * 1000)
    walkins = rhu(ctx.value_of(p["walkins_check_id"], "walkins_per_week"))
    bill = rhu(ctx.value_of(p["avg_bill_check_id"], "avg_bill_value"))
    return int(rhu((bench - current) * walkins * bill / 1000 / 100) * 100)


# --------------------------------------------------------------------------- report

class Report:
    def __init__(self):
        self.counts = {}        # group -> [checked, failed]
        self.failures = []
        self.warnings = []

    def _group(self, group):
        return self.counts.setdefault(group, [0, 0])

    def ok(self, group):
        self._group(group)[0] += 1

    def fail(self, group, ident, kind, expected, found):
        g = self._group(group)
        g[0] += 1
        g[1] += 1
        self.failures.append((group, ident, kind, expected, found))

    def test(self, group, passed, ident, kind, expected, found):
        if passed:
            self.ok(group)
        else:
            self.fail(group, ident, kind, expected, found)
        return passed

    def warn(self, message):
        self.warnings.append(message)


def show(value):
    if isinstance(value, Fraction):
        return str(int(value)) if value.denominator == 1 else repr(float(value))
    return repr(value)


def same(expected, found):
    if isinstance(expected, str):
        return isinstance(found, str) and found == expected
    if isinstance(found, bool) or not isinstance(found, (int, float)):
        return False
    return abs(float(expected) - float(found)) <= TOL


# --------------------------------------------------------------------------- checks

def is_check(obj):
    return isinstance(obj, dict) and all(k in obj for k in CHECK_KEYS)


def find_checks(node, path=""):
    """Every Check anywhere in the JSON: (path, check, the checks beside it)."""
    if isinstance(node, dict):
        if is_check(node):
            yield path, node, [node]
            return
        for key, child in node.items():
            yield from find_checks(child, f"{path}/{key}")
    elif isinstance(node, list):
        beside = [c for c in node if is_check(c)]
        for i, child in enumerate(node):
            if is_check(child):
                yield f"{path}/{i}", child, beside
            else:
                yield from find_checks(child, f"{path}/{i}")


class Context:
    """What a recipe may see besides the CSVs: the checks beside it."""

    def __init__(self, data, beside, depth=0):
        self.data, self.beside, self.depth = data, beside, depth

    def value_of(self, check_id, kind=None):
        found = [c for c in self.beside if c.get("id") == check_id]
        if len(found) != 1:
            raise CannotCompute(f"needs exactly one check {check_id!r} beside it, found {len(found)}")
        if kind and found[0].get("kind") != kind:
            raise CannotCompute(f"check {check_id!r} should be of kind {kind}, is {found[0].get('kind')}")
        return recompute(self.data, found[0], self.beside, self.depth + 1)


def recompute(data, check, beside, depth=0):
    """The value of one check from the CSVs. Raises CannotCompute or KeyError('unknown kind')."""
    kind, params = check.get("kind"), check.get("params")
    if depth > 5:
        raise CannotCompute("checks refer to each other in a loop")
    if kind not in RECIPES:
        raise KeyError(kind)
    rec = RECIPES[kind]
    if not isinstance(params, dict):
        raise CannotCompute("params is not an object")
    missing = sorted(rec.required - set(params))
    extra = sorted(set(params) - rec.required - rec.optional)
    if missing:
        raise CannotCompute(f"missing params {missing}")
    if extra:
        raise CannotCompute(f"params not in the documented recipe: {extra}")
    return rec.fn(data, params, Context(data, beside, depth))


def verify_checks(out, data, rep):
    seen = {}
    for path, check, beside in find_checks(out):
        cid, kind = check["id"], check["kind"]
        group = f"check   {kind}"

        # ids are unique within the file
        fingerprint = json.dumps(check, sort_keys=True, ensure_ascii=False)
        if cid in seen and seen[cid] != fingerprint:
            rep.fail("rule    check ids unique", cid, kind, "one check per id",
                     f"two different checks share this id (second at {path})")
        elif cid in seen:
            rep.warn(f"check id {cid!r} appears more than once with identical content ({path})")
        else:
            seen[cid] = fingerprint
            rep.ok("rule    check ids unique")

        # the value, from the CSVs
        try:
            expected = recompute(data, check, beside)
        except KeyError:
            rep.fail(group, cid, kind, "a recipe in scripts/verify.py (UNKNOWN KIND)", show(check["value"]))
            continue
        except CannotCompute as why:
            rep.fail(group, cid, kind, f"cannot be computed: {why}", show(check["value"]))
            continue
        rep.test(group, same(expected, check["value"]), cid, kind, show(expected), show(check["value"]))

        # the display, from the value in the file
        try:
            want = RECIPES[kind].display(check["value"])
        except Exception:
            continue  # the value itself is malformed and was reported above
        wanted = want if isinstance(want, set) else {want}
        rep.test("rule    display matches value", check["display"] in wanted, cid, kind,
                 "display " + " or ".join(repr(w) for w in sorted(wanted)),
                 "display " + repr(check["display"]))

        verify_no_future(check, data.as_of, rep)


def verify_no_future(check, as_of, rep):
    """No check may be built on a row dated after as_of."""
    group = "rule    nothing after as_of"
    kind = check["kind"]
    if kind == "upcoming_busy_dates":
        return  # the one documented exception; its window is pinned inside the recipe
    late = [f"{k}={v}" for k, v in sorted(check["params"].items())
            if isinstance(v, str) and ISO.fullmatch(v) and v > as_of]
    if isinstance(check["value"], str):
        late += [f"value={v}" for v in ISO.findall(check["value"]) if v > as_of]
    rep.test(group, not late, check["id"], kind, f"no date after {as_of}", ", ".join(late))


# --------------------------------------------------------------------------- text rules

NUMBER = re.compile(r"\d+(?:,\d+)*(?:\.\d+)?")


def numbers_in(text, known_ids=()):
    """Number tokens in a text, digit grouping removed. Known ids (LKO-02) are not numbers."""
    for ident in known_ids:
        text = text.replace(ident, " ")
    return [m.group(0).replace(",", "") for m in NUMBER.finditer(text)]


def unbacked_numbers(texts, checks, known_ids):
    backed = {n for c in checks for n in numbers_in(str(c.get("display", "")))}
    return [(field, n) for field, text in texts
            for n in numbers_in(text or "", known_ids) if n not in backed]


def evaluate(expr):
    """Exact value of an arithmetic expression: numbers, + - * / and brackets."""
    tokens = re.findall(r"\d+(?:\.\d+)?|[-+*/()]", expr)
    if "".join(tokens) != re.sub(r"\s+", "", expr):
        raise ValueError(f"cannot read {expr!r}")
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def take():
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def atom():
        tok = take() if peek() is not None else None
        if tok == "(":
            value = total()
            if peek() != ")":
                raise ValueError("unbalanced brackets")
            take()
            return value
        if tok == "-":
            return -atom()
        if tok is None or not tok[0].isdigit():
            raise ValueError(f"unexpected {tok!r}")
        return Fraction(tok)

    def product():
        value = atom()
        while peek() in ("*", "/"):
            value = value * atom() if take() == "*" else value / atom()
        return value

    def total():
        value = product()
        while peek() in ("+", "-"):
            value = value + product() if take() == "+" else value - product()
        return value

    result = total()
    if pos != len(tokens):
        raise ValueError(f"cannot read {expr!r}")
    return result


def worked_sides(worked):
    """'(13.2% − 10.7%) × 486 walk-ins a week × ₹10,092 = ₹1,22,600 a week' -> (lhs, rhs)."""
    text = re.sub(r"[A-Za-z]+(?:[-'][A-Za-z]+)*", " ", worked)       # words and units
    text = re.sub(r"(?<=\d),(?=\d)", "", text).replace("₹", " ")
    text = text.replace("%", "/100").replace("−", "-").replace("–", "-")
    text = text.replace("×", "*").replace("÷", "/")
    sides = text.split("=")
    if len(sides) != 2:
        raise ValueError("expected exactly one '='")
    return evaluate(sides[0]), evaluate(sides[1])


def verify_alert(alert, data, rep, known_ids):
    aid = alert.get("alert_id", "?")
    checks = [c for c in alert.get("checks", []) if is_check(c)]
    by_id = {c["id"]: c for c in checks}
    rupees = alert.get("rupees_at_stake_weekly")
    arithmetic = alert.get("arithmetic") or {}
    worked = arithmetic.get("worked", "")

    # rupees at stake against its own checks
    group = "rule    alert rupees = its check"
    carriers = [c for c in checks
                if c["kind"] in RECIPES and RECIPES[c["kind"]].rupees_step is not None]
    step = RECIPES[carriers[0]["kind"]].rupees_step if carriers else None
    rep.test(group, any(same(rupees, c["value"]) for c in carriers) if isinstance(rupees, (int, float)) else False,
             aid, "rupees_at_stake_weekly",
             "equal to the alert's rupees-at-stake check " + str([c["value"] for c in carriers]),
             show(rupees))

    # ... and against its own arithmetic
    group = "rule    alert arithmetic multiplies out"
    inputs = arithmetic.get("input_check_ids", [])
    missing = [i for i in inputs if i not in by_id]
    rep.test(group, bool(inputs) and not missing, aid, "arithmetic.input_check_ids",
             "ids of checks in this alert", f"not in the alert: {missing}" if inputs else "empty")
    unshown = [i for i in inputs if i in by_id and by_id[i]["display"] not in worked]
    rep.test(group, not unshown, aid, "arithmetic.worked",
             "the display of every input check appears in the worked line",
             f"missing from {worked!r}: {[by_id[i]['display'] for i in unshown]}")
    try:
        lhs, rhs = worked_sides(worked)
        rounded = rhu(lhs / step) * step if step else lhs
        rep.test(group, rounded == rhs and same(rhs, rupees), aid, "arithmetic.worked",
                 f"left side = {show(lhs)}, to the nearest {step} = {show(rounded)}",
                 f"line says {show(rhs)}, rupees_at_stake_weekly = {show(rupees)}")
    except (ValueError, ZeroDivisionError) as why:
        rep.fail(group, aid, "arithmetic.worked", "an expression that can be multiplied out",
                 f"{worked!r} ({why})")

    # every number in the text is the display of one of the alert's checks
    group = "rule    alert text numbers have a check"
    texts = [("headline", alert.get("headline")), ("cause", alert.get("cause")),
             ("action.text", (alert.get("action") or {}).get("text")),
             ("arithmetic.worked", worked)]
    for field, _ in texts:
        loose = [n for f, n in unbacked_numbers(texts, checks, known_ids) if f == field]
        rep.test(group, not loose, aid, field, "every number is in the display of one of the alert's checks",
                 f"no check shows: {loose}")

    # the follow-up baseline is itself a figure and must recompute
    fu = alert.get("follow_up")
    if isinstance(fu, dict):
        group = "rule    alert follow-up baseline"
        probe = {"id": f"{aid}:follow_up", "kind": fu.get("kind"), "params": fu.get("params"),
                 "value": fu.get("baseline_value"), "display": ""}
        try:
            expected = recompute(data, probe, checks)
            rep.test(group, same(expected, fu.get("baseline_value")), aid, f"follow_up {fu.get('kind')}",
                     show(expected), show(fu.get("baseline_value")))
        except KeyError:
            rep.fail(group, aid, f"follow_up {fu.get('kind')}", "a recipe in scripts/verify.py (UNKNOWN KIND)",
                     show(fu.get("baseline_value")))
        except CannotCompute as why:
            rep.fail(group, aid, f"follow_up {fu.get('kind')}", f"cannot be computed: {why}",
                     show(fu.get("baseline_value")))
        late = [f"{k}={v}" for k, v in sorted((fu.get("params") or {}).items())
                if isinstance(v, str) and ISO.fullmatch(v) and v > data.as_of]
        rep.test("rule    nothing after as_of", not late, aid, "follow_up.params",
                 f"no date after {data.as_of}", ", ".join(late))
        if not any(same(c["value"], fu.get("target_value")) for c in checks
                   if not isinstance(c["value"], str)):
            rep.warn(f"alert {aid}: follow_up.target_value {fu.get('target_value')!r} is not the "
                     "value of any check in the alert")


def verify_managers(out, data, rep):
    group = "rule    weekly cap and ranking"
    am = data.area_managers
    cap = dict(zip(am["area_manager_id"], am["max_alerts_per_week"]))
    stores = {a: [s.strip() for s in raw.split(",") if s.strip()]
              for a, raw in zip(am["area_manager_id"], am["stores"])}
    blocks = out.get("area_managers", [])
    listed = [b.get("area_manager_id") for b in blocks]
    rep.test(group, sorted(listed) == sorted(cap), "area_managers", "managers",
             f"exactly the managers of area_managers.csv {sorted(cap)}", str(sorted(map(str, listed))))
    for block in blocks:
        mid = block.get("area_manager_id")
        if mid not in cap:
            continue
        limit = int(cap[mid])
        alerts = block.get("alerts", [])
        rep.test(group, block.get("max_alerts_per_week") == limit, mid, "max_alerts_per_week",
                 f"{limit} (area_managers.csv)", show(block.get("max_alerts_per_week")))
        rep.test(group, len(alerts) <= limit, mid, "alert count", f"at most {limit}", str(len(alerts)))
        order = [(a.get("rupees_at_stake_weekly"), a.get("alert_id")) for a in alerts]
        try:
            ranked = sorted(order, key=lambda t: (-t[0], t[1]))
        except TypeError:
            ranked = None
        rep.test(group, order == ranked, mid, "order",
                 "most rupees first, ties by alert_id: " + str(ranked), str(order))
        ranks = [a.get("rank") for a in alerts]
        rep.test(group, ranks == list(range(1, len(alerts) + 1)), mid, "rank",
                 str(list(range(1, len(alerts) + 1))), str(ranks))
        held = block.get("held_back", [])
        if held:
            floor = min((a.get("rupees_at_stake_weekly", 0) for a in alerts), default=0)
            most = max(h.get("rupees_at_stake_weekly", 0) for h in held)
            rep.test(group, len(alerts) == limit and most <= floor, mid, "held_back",
                     f"held back only when {limit} alerts are sent, and none above the smallest sent (₹{floor})",
                     f"{len(alerts)} sent, largest held back ₹{most}")
        own = set(stores[mid])
        rep.test(group, sorted(block.get("store_ids", [])) == sorted(own), mid, "store_ids",
                 str(sorted(own)), str(sorted(block.get("store_ids", []))))
        for a in alerts:
            stray = [s for s in a.get("store_ids", []) if s not in own]
            rep.test(group, bool(a.get("store_ids")) and not stray, a.get("alert_id", "?"), "alert store_ids",
                     f"stores of {mid}", f"not this manager's: {stray}" if stray else "no store")


def verify_cards(out, data, rep, known_ids):
    group = "rule    cards: 60 words, peer from same store"
    for card in out.get("cards", []):
        cid = card.get("card_id", "?")
        text = card.get("text") or ""
        words = len(text.split())
        store, sp = card.get("store_id"), card.get("salesperson_id")
        peer = card.get("peer") or {}
        pid = peer.get("salesperson_id")
        rep.test(group, 0 < words <= 60, cid, "text", "1 to 60 words", f"{words} words")
        rep.test(group, card.get("word_count") == words, cid, "word_count", str(words), show(card.get("word_count")))
        rep.test(group, data.store_of_person.get(sp) == store and store is not None, cid, "salesperson",
                 f"{sp} works at {store} (salespeople.csv)", f"{sp} is at {data.store_of_person.get(sp)!r}")
        rep.test(group, data.name_of_person.get(sp) == card.get("salesperson_name"), cid, "salesperson_name",
                 repr(data.name_of_person.get(sp)), repr(card.get("salesperson_name")))
        rep.test(group, pid is not None and pid != sp and data.store_of_person.get(pid) == store, cid, "peer",
                 f"a different salesperson of {store}", f"{pid} is at {data.store_of_person.get(pid)!r}")
        rep.test(group, bool(peer.get("name")) and data.name_of_person.get(pid) == peer.get("name"), cid, "peer.name",
                 repr(data.name_of_person.get(pid)), repr(peer.get("name")))
        rep.test(group, bool(peer.get("name")) and peer["name"] in text, cid, "text",
                 f"names the peer {peer.get('name')!r}", repr(text))
        loose = [n for _, n in unbacked_numbers([("text", text)], card.get("checks", []), known_ids)]
        rep.test("rule    card text numbers have a check", not loose, cid, "text",
                 "every number is in the display of one of the card's checks", f"no check shows: {loose}")


def verify_as_of(out, data, rep):
    group = "rule    nothing after as_of"
    as_of = data.as_of

    def not_late(ident, field, value):
        ok = isinstance(value, str) and bool(ISO.fullmatch(value)) and value <= as_of
        rep.test(group, ok, ident, field, f"a date on or before {as_of}", repr(value))

    for name, window in (out.get("windows") or {}).items():
        not_late(f"windows.{name}", "start", (window or {}).get("start"))
        not_late(f"windows.{name}", "end", (window or {}).get("end"))
    for issue in out.get("data_issues", []):
        not_late(issue.get("issue_id", "?"), "first_date", issue.get("first_date"))
        not_late(issue.get("issue_id", "?"), "last_date", issue.get("last_date"))
    for fu in out.get("follow_ups", []):
        not_late(fu.get("alert_id", "?"), "measured_as_of", fu.get("measured_as_of"))
        not_late(fu.get("alert_id", "?"), "raised_as_of", fu.get("raised_as_of"))
    for store in out.get("stores", []):
        sid = store.get("store_id")
        rep.test(group, sid in data.state_of_store, str(sid), "store",
                 f"a store opened on or before {as_of}", "not in stores.csv as of that date")
        ghosts = [p.get("salesperson_id") for p in store.get("salespeople", [])
                  if data.store_of_person.get(p.get("salesperson_id")) != sid]
        rep.test(group, not ghosts, str(sid), "salespeople",
                 f"people of {sid} who joined on or before {as_of}", f"not so: {ghosts}")


def verify_data_issues(out, data, rep, known_ids):
    """Not a failure: data-issue text is not in the list of texts the engine gates."""
    for issue in out.get("data_issues", []):
        extra = [{"display": fmt_day(issue[k])} for k in ("first_date", "last_date")
                 if isinstance(issue.get(k), str) and ISO.fullmatch(issue[k])]
        texts = [(f, issue.get(f)) for f in ("title", "detail", "handling")]
        loose = unbacked_numbers(texts, issue.get("checks", []) + extra, known_ids)
        if loose:
            rep.warn(f"data issue {issue.get('issue_id')}: numbers in its text with no check: "
                     + ", ".join(f"{n} ({f})" for f, n in loose))
        if not any(same(c["value"], issue.get("days_affected")) for c in issue.get("checks", [])
                   if is_check(c) and not isinstance(c["value"], str)):
            rep.warn(f"data issue {issue.get('issue_id')}: days_affected "
                     f"{issue.get('days_affected')!r} is not the value of any of its checks")


def verify_follow_ups(out, data, rep, known_ids):
    group = "rule    follow-up text numbers have a check"
    for fu in out.get("follow_ups", []):
        fid = fu.get("alert_id", "?")
        checks = fu.get("checks", [])
        loose = [n for _, n in unbacked_numbers([("verdict", fu.get("verdict"))], checks, known_ids)]
        rep.test(group, not loose, fid, "verdict",
                 "every number is in the display of one of the follow-up's checks", f"no check shows: {loose}")
        shown = {c.get("display") for c in checks if is_check(c)}
        for field in ("before_display", "after_display", "target_display"):
            if fu.get("moved") == "not_measurable" and field == "after_display":
                continue
            if fu.get(field) not in shown:
                rep.warn(f"follow-up {fid}: {field} {fu.get(field)!r} is not the display of any of its checks")


# --------------------------------------------------------------------------- main

def known_identifiers(data):
    """Ids that may appear in text and are not numbers (LKO-02, SP1018, SHW-01-M)."""
    ids = set(data.state_of_store) | set(data.store_of_person)
    items = data.read("items", required=False)
    if items is not None:
        for col in ("sku_id", "style_id"):
            if col in items:
                ids |= set(items[col])
    return sorted((i for i in ids if i), key=len, reverse=True)


def run(file, data_dir, strict=False, stream=None):
    stream = stream or sys.stdout
    say = lambda *a: print(*a, file=stream)
    file, data_dir = Path(file), Path(data_dir)
    try:
        out = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CannotRun(f"cannot read {file}: {exc}")
    as_of = out.get("as_of") if isinstance(out, dict) else None
    if not isinstance(as_of, str) or not ISO.fullmatch(as_of):
        raise CannotRun(f"{file} has no usable as_of (found {as_of!r})")
    data = Data(data_dir, as_of)
    rep = Report()
    ids = known_identifiers(data)

    verify_checks(out, data, rep)
    for block in out.get("area_managers", []):
        for alert in block.get("alerts", []):
            verify_alert(alert, data, rep, ids)
    verify_managers(out, data, rep)
    verify_cards(out, data, rep, ids)
    verify_follow_ups(out, data, rep, ids)
    verify_as_of(out, data, rep)
    verify_data_issues(out, data, rep, ids)
    for note in data.notes:
        rep.warn(note)

    docs = sorted(p.name for p in (ROOT / "docs").glob("CHECKS*.md")) if (ROOT / "docs").is_dir() else []
    say(f"Store Coach verify   file: {file}")
    say(f"                     data: {data_dir}   as_of: {as_of}   recipes from: {', '.join(docs) or 'docs/CHECKS.md'}")
    say(f"                     rows after as_of left out: {data.rows_after_as_of}")
    say(f"                     tolerance: documented rounding (half up, exact fractions), then |difference| <= {TOL}")
    say("")
    n_checks = n_check_fail = n_rules = n_rule_fail = 0
    for group in sorted(rep.counts):
        checked, failed = rep.counts[group]
        say(f"{group:<48} {checked:>4} checked  {checked - failed:>4} ok  {failed:>3} mismatch")
        if group.startswith("check"):
            n_checks, n_check_fail = n_checks + checked, n_check_fail + failed
        else:
            n_rules, n_rule_fail = n_rules + checked, n_rule_fail + failed
    for name, n in (("alerts", sum(len(b.get("alerts", [])) for b in out.get("area_managers", []))),
                    ("cards", len(out.get("cards", []))), ("follow_ups", len(out.get("follow_ups", []))),
                    ("data_issues", len(out.get("data_issues", [])))):
        say(f"seen    {name:<40} {n:>4}")
    say("")
    for group, ident, kind, expected, found in rep.failures:
        say(f"MISMATCH [{group.split(None, 1)[1]}] id={ident} kind={kind}")
        say(f"         expected from CSV: {expected}")
        say(f"         found in JSON:     {found}")
    for w in rep.warnings:
        say(f"WARNING  {w}")
    failed = n_check_fail + n_rule_fail + (len(rep.warnings) if strict else 0)
    say(f"RESULT   {n_checks} checks recomputed, {n_check_fail} mismatch; "
        f"{n_rules} rule tests, {n_rule_fail} broken; {len(rep.warnings)} warnings"
        f"{' (fatal with --strict)' if strict else ''} -> {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):  # the rupee sign on a Windows console
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Recompute every figure in the engine output from the raw CSVs.")
    parser.add_argument("--file", default=str(ROOT / "web" / "public" / "data" / "latest.json"),
                        help="engine output to verify (default: web/public/data/latest.json)")
    parser.add_argument("--data-dir", default=str(ROOT / "data" / "csv"),
                        help="folder with the raw CSVs (default: data/csv)")
    parser.add_argument("--strict", action="store_true", help="treat warnings as failures")
    args = parser.parse_args(argv)
    try:
        return run(args.file, args.data_dir, args.strict)
    except CannotRun as why:
        print(f"CANNOT RUN: {why}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
