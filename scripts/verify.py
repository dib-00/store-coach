#!/usr/bin/env python
"""Independent verification of the engine's output.

Recomputes every Check in web/public/data/latest.json straight from the raw CSVs and
checks the rules the output must obey. It is written from docs/CHECKS.md,
docs/CHECKS-followup.md and docs/CHECKS-repeat.md alone: it imports nothing from engine/
and shares no code with it.

    python -X utf8 scripts/verify.py                      # latest.json against data/csv
    python -X utf8 scripts/verify.py --file F --data-dir D
    python -X utf8 scripts/verify.py --strict             # warnings also fail
    python -X utf8 scripts/verify.py --earlier-run R      # the run of 7 days earlier, for follow-ups

A kind that no document describes fails (the "bigger baskets" kinds today). For those the
script also tries its own reading, kept apart in PROVISIONAL, only to say in the mismatch
line whether the figure can be reproduced. It never makes such a check pass.

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

EXACT_HALVES = []  # figures that sat exactly on a rounding half while one check was recomputed


def rhu(x, n=0):
    """Round half up to n decimals, exactly: floor(x * 10^n + 0.5) / 10^n."""
    scale = Fraction(10) ** n
    scaled = Fraction(x) * scale
    if scaled.denominator == 2:
        EXACT_HALVES.append(f"{float(Fraction(x))!r} is exactly on the half; half up to {n} decimals "
                            f"is {float(Fraction(math.floor(scaled + Fraction(1, 2))) / scale)!r} "
                            "(binary floats can land just under it)")
    return Fraction(math.floor(scaled + Fraction(1, 2))) / scale


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
        self.opened_on = dict(zip(stores["store_id"], stores["opened_on"]))
        # every bill up to as_of, for the repeat recipes: (bill_id, date, store, salesperson, customer)
        self.bill_rows = list(zip(bills["bill_id"], bills["bill_date"], bills["store_id"],
                                  bills["salesperson_id"], bills["customer_id"]))
        self._lines = lines[["bill_id", "sku_id"]]
        self._skus_of_bill = None
        self._customers = {}
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
        self.festival = {}  # (date, state) -> festival name, trimmed ('' when blank)
        for dt, state, fest, wed in zip(calendar["date"], calendar["state"],
                                        calendar["festival"], calendar["is_wedding_date"]):
            try:
                wedding = wed.strip() != "" and float(wed) == 1
            except ValueError:
                wedding = False
            self.calendar[(dt, state)] = fest.strip() != "" or wedding
            self.festival[(dt, state)] = fest.strip()

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

    # ---- docs/CHECKS-repeat.md

    def customers(self, exclude):
        key = tuple(sorted(exclude))
        if key not in self._customers:
            self._customers[key] = Customers(self, key)
        return self._customers[key]

    def placeholder_ids(self):
        """Non-blank customer ids on 25 or more bills, or with bills at 6 or more stores."""
        n_bills, stores = Counter(), defaultdict(set)
        for _, _, st, _, cu in self.bill_rows:
            n_bills[cu] += 1
            stores[cu].add(st)
        return sorted(cu for cu in n_bills if cu.strip() != ""
                      and (n_bills[cu] >= 25 or len(stores[cu]) >= 6))

    def product_categories_of_bill(self, bill_id):
        """Categories of the non-packaging lines of one bill (items.csv)."""
        if self._skus_of_bill is None:
            items = self.read("items")
            self._category = {sku: (cat, pkg.strip()) for sku, cat, pkg in
                              zip(items["sku_id"], items["category"], items["is_packaging"])}
            self._skus_of_bill = defaultdict(list)
            for bid, sku in zip(self._lines["bill_id"], self._lines["sku_id"]):
                self._skus_of_bill[bid].append(sku)
        out = set()
        for sku in self._skus_of_bill.get(bill_id, ()):
            if sku not in self._category:
                raise CannotCompute(f"bill {bill_id} has SKU {sku!r} that is not in items.csv")
            cat, pkg = self._category[sku]
            if pkg != "1":
                out.add(cat)
        return out

    def baskets(self):
        """Per bill, over its lines that are not packaging: categories, value at selling price and
        at MRP (paise), whether any line sold under MRP, and value per category. Built on first use."""
        if getattr(self, "_baskets", None) is None:
            self.product_categories_of_bill("")          # loads items.csv into self._category
            raw = self.read("bill_lines")
            raw = raw[raw["bill_id"].isin({row[0] for row in self.bill_rows})]
            out = {}
            for bid, sku, qty, mrp, price in zip(raw["bill_id"], raw["sku_id"], raw["qty"], raw["mrp"],
                                                 raw["selling_price"]):
                if sku not in self._category:
                    raise CannotCompute(f"bill {bid} has SKU {sku!r} that is not in items.csv")
                cat, pkg = self._category[sku]
                if pkg == "1":
                    continue
                b = out.setdefault(bid, {"cats": defaultdict(Fraction), "sale": Fraction(0), "mrp": Fraction(0),
                                         "discounted": False, "items": 0})
                q, m, sp = Fraction(qty), Fraction(mrp), Fraction(price)
                b["cats"][cat] += q * sp
                b["sale"] += q * sp
                b["mrp"] += q * m
                b["discounted"] = b["discounted"] or sp < m
                b["items"] += int(qty)
            self._baskets = out
        return self._baskets

    def peers(self, store_id, exclude):
        self.state(store_id)
        if not isinstance(exclude, list):
            raise CannotCompute("exclude_salesperson_ids must be a list")
        return sorted(sp for sp in self.people_of_store.get(store_id, []) if sp not in exclude)


# --------------------------------------------------------------------------- registry

class Recipe:
    def __init__(self, kind, fn, required, optional, display, rupees_step, future_calendar):
        self.kind, self.fn = kind, fn
        self.required, self.optional = set(required), set(optional)
        self.display, self.rupees_step = display, rupees_step
        self.future_calendar = future_calendar


RECIPES = {}


def recipe(kind, required, optional=(), display=fmt_plain, rupees_step=None, future_calendar=False):
    """Register the recompute function for one check kind.

    rupees_step: set it (e.g. 100) on the kind that carries an alert's rupees at stake;
    it is the step the figure is rounded to.
    future_calendar: True only for a kind the documents allow to read calendar rows
    after as_of. Every other kind fails if a param or value is dated after as_of.
    """
    def register(fn):
        if kind in RECIPES:
            raise RuntimeError(f"two recipes for kind {kind!r}")
        RECIPES[kind] = Recipe(kind, fn, required, optional, display, rupees_step, future_calendar)
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


# ---- docs/CHECKS.md section 6: city-adjusted sizing and dated windows

def fmt_date_range(v):
    a, b = str(v).split("..")
    return f"{fmt_day(a)} to {fmt_day(b)}"


@recipe("date_range", ("start", "end"), (), fmt_date_range)
def date_range(d, p, ctx):
    days(p["start"], p["end"])                       # a real window, start on or before end
    return f"{p['start']}..{p['end']}"


@recipe("beyond_city_z", ("store_ids", "other_store_ids", "start", "end", "base_start", "base_end"), (), fmt_2dp)
def beyond_city_z(d, p, ctx):
    rates = []
    for stores in (p["store_ids"], p["other_store_ids"]):
        for lo, hi in ((p["start"], p["end"]), (p["base_start"], p["base_end"])):
            b, n = _bills_and_footfall(d, {"store_ids": stores, "start": lo, "end": hi})
            if n == 0:
                raise CannotCompute("a window has no walk-ins on valid store-days")
            rates.append((Fraction(b) / n, n))
    (p1, _), (p0, _), (q1, _), (q0, _) = rates
    variance = sum(r * (1 - r) / n for r, n in rates)
    if variance <= 0:
        raise CannotCompute("standard error is zero")
    return rhu(Fraction(float((p1 - p0) - (q1 - q0)) / math.sqrt(float(variance))), 2)


@recipe("rupees_at_stake_city",
        ("benchmark_check_id", "current_check_id", "city_benchmark_check_id", "city_current_check_id",
         "walkins_check_id", "avg_bill_check_id"),
        (), fmt_rupees, rupees_step=100)
def rupees_at_stake_city(d, p, ctx):
    tenths = lambda key: rhu(ctx.value_of(p[key], "conversion") * 1000)
    city_drop = max(0, tenths("city_benchmark_check_id") - tenths("city_current_check_id"))
    gap = tenths("benchmark_check_id") - tenths("current_check_id") - city_drop
    walkins = rhu(ctx.value_of(p["walkins_check_id"], "walkins_per_week"))
    bill = rhu(ctx.value_of(p["avg_bill_check_id"], "avg_bill_value"))
    return int(rhu(gap * walkins * bill / 1000 / 100) * 100)


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


# docs/CHECKS-followup.md section 2 changes the window of docs/CHECKS.md section 2 from 7 to 9:
# "start = as_of + 1 day, end = as_of + 9 days".
UPCOMING_DAYS = 9


@recipe("upcoming_busy_dates", ("state", "start", "end"), (), fmt_day_list, future_calendar=True)
def upcoming_busy_dates(d, p, ctx):
    as_of = to_date(d.as_of)
    want = ((as_of + timedelta(1)).isoformat(), (as_of + timedelta(UPCOMING_DAYS)).isoformat())
    if (p["start"], p["end"]) != want:
        raise CannotCompute(f"docs/CHECKS-followup.md says the window is the {UPCOMING_DAYS} days after as_of, "
                            f"{want[0]}..{want[1]}; the check asks for {p['start']}..{p['end']}")
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


# ---- docs/CHECKS-followup.md section 1: the small additions

@recipe("festival_name", ("state", "date"), (), future_calendar=True)
def festival_name(d, p, ctx):
    # May read a calendar row after as_of "like upcoming_busy_dates", to name a date in an
    # action or on a card. Those dates are the busy dates of the look-ahead, so a later date
    # than as_of + UPCOMING_DAYS is not something the documents allow.
    last = (to_date(d.as_of) + timedelta(UPCOMING_DAYS)).isoformat()
    if to_date(p["date"]).isoformat() > last:
        raise CannotCompute(f"date {p['date']} is beyond the {UPCOMING_DAYS}-day look-ahead that ends {last}")
    if (p["date"], p["state"]) not in d.festival:
        raise CannotCompute(f"calendar.csv has no row for {p['date']} in {p['state']!r}")
    name = d.festival[(p["date"], p["state"])]
    if name == "":
        raise CannotCompute("the festival cell is blank; the check is only written when it is not")
    return name


@recipe("store_opened_on", ("store_id",), (), fmt_day)
def store_opened_on(d, p, ctx):
    d.state(p["store_id"])
    return d.opened_on[p["store_id"]]


# ---- docs/CHECKS-repeat.md

_ORDINALS = {}


def ordinal(iso):
    if iso not in _ORDINALS:
        _ORDINALS[iso] = to_date(iso).toordinal()
    return _ORDINALS[iso]


class Customer:
    __slots__ = ("first_date", "store", "salesperson", "first_bill", "bills")

    def __init__(self, rows):
        # rows: (date, bill_id, store, salesperson), sorted by date then bill_id (text order)
        self.first_date, self.first_bill, self.store, self.salesperson = rows[0]
        first = ordinal(self.first_date)
        self.bills = [(dt, ordinal(dt) - first, st, bid) for dt, bid, st, _ in rows]  # (date, gap, store, id)

    def returned(self, lo, hi):
        return any(lo <= gap <= hi for _, gap, _, _ in self.bills)

    @property
    def month(self):
        return self.first_date[:7]

    @property
    def quarter(self):
        return f"{self.first_date[:4]}Q{(int(self.first_date[5:7]) - 1) // 3 + 1}"


class Customers:
    """Every customer after the placeholder ids are removed; the first bill decides who they belong to."""

    def __init__(self, d, exclude):
        drop = set(exclude)
        rows = defaultdict(list)
        for bid, dt, st, sp, cu in d.bill_rows:
            if cu.strip() == "" or cu in drop:
                continue
            rows[cu].append((dt, bid, st, sp))
        self.by_store = defaultdict(list)       # store the customer belongs to -> customers
        self.bills_at = defaultdict(list)       # store the bill was made at -> (date, gap, bill_id)
        for cu in sorted(rows):
            c = Customer(sorted(rows[cu]))
            self.by_store[c.store].append(c)
            for dt, gap, st, bid in c.bills:
                self.bills_at[st].append((dt, gap, bid))

    def group(self, p, prefix=""):
        stores = p[prefix + "store_ids"]
        people = p.get(prefix + "salesperson_ids")
        if not isinstance(stores, list) or not stores:
            raise CannotCompute(f"{prefix}store_ids must be a non-empty list")
        if people is not None and not isinstance(people, list):
            raise CannotCompute(f"{prefix}salesperson_ids must be a list")
        return [c for st in dict.fromkeys(stores) for c in self.by_store.get(st, ())
                if people is None or c.salesperson in people]


def _repeat(d, p):
    ids = p["exclude_customer_ids"]
    if not isinstance(ids, list):
        raise CannotCompute("exclude_customer_ids must be a list")
    return d.customers(ids)


def _gaps(p):
    lo, hi = p["min_gap_days"], p["max_gap_days"]
    if isinstance(lo, bool) or isinstance(hi, bool) or not isinstance(lo, int) or not isinstance(hi, int):
        raise CannotCompute("min_gap_days and max_gap_days must be whole numbers")
    return lo, hi


def _cohort(p, customers):
    to_date(p["first_bill_to"])
    start = p.get("first_bill_from")
    if start is not None:
        to_date(start)
    return [c for c in customers
            if c.first_date <= p["first_bill_to"] and (start is None or c.first_date >= start)]


def _subject_and_peers(d, p):
    cu = _repeat(d, p)
    subject, peers = cu.group(p), cu.group(p, "peer_")
    if {id(c) for c in subject} & {id(c) for c in peers}:
        raise CannotCompute("the subject group and the peer group overlap")
    return _cohort(p, subject), _cohort(p, peers)


def _tally(customers, key, lo, hi):
    """key -> [customers, returned]."""
    out = defaultdict(lambda: [0, 0])
    for c in customers:
        cell = out[key(c)]
        cell[0] += 1
        cell[1] += c.returned(lo, hi)
    return out


def _by_month(d, p):
    lo, hi = _gaps(p)
    subject, peers = _subject_and_peers(d, p)
    s, q = _tally(subject, lambda c: c.month, lo, hi), _tally(peers, lambda c: c.month, lo, hi)
    if not s:
        raise CannotCompute("the subject has no customers in the cohort")
    empty = sorted(m for m in s if q.get(m, [0, 0])[0] == 0)
    if empty:
        raise CannotCompute(f"the peers have no customers first billed in {empty} (the recipe gives null)")
    return s, q


REPEAT_GROUP = ("store_ids", "exclude_customer_ids")
REPEAT_COHORT = REPEAT_GROUP + ("first_bill_to",)
REPEAT_GAPS = ("min_gap_days", "max_gap_days")
REPEAT_VERSUS = REPEAT_COHORT + REPEAT_GAPS + ("peer_store_ids",)
REPEAT_VERSUS_OPT = ("salesperson_ids", "peer_salesperson_ids", "first_bill_from")


@recipe("repeat_customers", REPEAT_COHORT, ("salesperson_ids", "first_bill_from") + REPEAT_GAPS, fmt_whole)
def repeat_customers(d, p, ctx):
    return len(_cohort(p, _repeat(d, p).group(p)))


@recipe("repeat_returned", REPEAT_COHORT + REPEAT_GAPS, ("salesperson_ids", "first_bill_from"), fmt_whole)
def repeat_returned(d, p, ctx):
    lo, hi = _gaps(p)
    return sum(c.returned(lo, hi) for c in _cohort(p, _repeat(d, p).group(p)))


@recipe("repeat_return_rate", REPEAT_COHORT + REPEAT_GAPS, ("salesperson_ids", "first_bill_from"), fmt_percent1)
def repeat_return_rate(d, p, ctx):
    lo, hi = _gaps(p)
    cohort = _cohort(p, _repeat(d, p).group(p))
    if not cohort:
        raise CannotCompute("no customers in the group and the cohort (the recipe gives null)")
    return rhu(Fraction(sum(c.returned(lo, hi) for c in cohort), len(cohort)), 4)


@recipe("repeat_fair_rate", REPEAT_VERSUS, REPEAT_VERSUS_OPT, fmt_percent1)
def repeat_fair_rate(d, p, ctx):
    s, q = _by_month(d, p)
    expected = sum(Fraction(n * q[m][1], q[m][0]) for m, (n, _) in s.items())
    return rhu(expected / sum(n for n, _ in s.values()), 4)


@recipe("repeat_z", REPEAT_VERSUS, REPEAT_VERSUS_OPT, fmt_2dp)
def repeat_z(d, p, ctx):
    s, q = _by_month(d, p)
    observed, expected, variance = 0, Fraction(0), Fraction(0)
    for m, (n_s, r_s) in s.items():
        n_p, r_p = q[m]
        total, returned = n_s + n_p, r_s + r_p
        observed += r_s
        expected += Fraction(n_s * returned, total)
        if total > 1:
            variance += Fraction(n_s * n_p * returned * (total - returned), total * total * (total - 1))
    if variance == 0:
        raise CannotCompute("the variance is zero (the recipe gives null)")
    return rhu(Fraction(float(observed - expected) / math.sqrt(float(variance))), 2)


@recipe("repeat_quarters", REPEAT_VERSUS + ("min_customers", "count"), REPEAT_VERSUS_OPT, fmt_whole)
def repeat_quarters(d, p, ctx):
    lo, hi = _gaps(p)
    if p["count"] not in ("compared", "ahead", "behind"):
        raise CannotCompute(f"unknown count {p['count']!r}")
    subject, peers = _subject_and_peers(d, p)
    s, q = _tally(subject, lambda c: c.quarter, lo, hi), _tally(peers, lambda c: c.quarter, lo, hi)
    counts = Counter()
    for quarter, (n_s, r_s) in s.items():
        n_p, r_p = q.get(quarter, (0, 0))
        if n_s < p["min_customers"] or n_p < p["min_customers"]:
            continue
        counts["compared"] += 1
        counts["ahead"] += r_s * n_p > r_p * n_s
        counts["behind"] += r_s * n_p < r_p * n_s
    return counts[p["count"]]


@recipe("repeat_new_customers_per_week", REPEAT_GROUP + ("start", "end"), ("salesperson_ids",), fmt_1dp)
def repeat_new_customers_per_week(d, p, ctx):
    n_days = len(days(p["start"], p["end"]))
    new = sum(p["start"] <= c.first_date <= p["end"] for c in _repeat(d, p).group(p))
    return rhu(Fraction(new * 7, n_days), 1)


def _return_bills(d, p):
    """Bills made AT store_ids in the window whose gap from the customer's first bill is in range."""
    lo, hi = _gaps(p)
    days(p["start"], p["end"])
    cu = _repeat(d, p)
    if not isinstance(p["store_ids"], list) or not p["store_ids"]:
        raise CannotCompute("store_ids must be a non-empty list")
    return [bid for st in dict.fromkeys(p["store_ids"]) for dt, gap, bid in cu.bills_at.get(st, ())
            if p["start"] <= dt <= p["end"] and lo <= gap <= hi]


@recipe("repeat_return_bill_count", REPEAT_GROUP + REPEAT_GAPS + ("start", "end"), (), fmt_whole)
def repeat_return_bill_count(d, p, ctx):
    return len(_return_bills(d, p))


@recipe("repeat_avg_return_bill_value", REPEAT_GROUP + REPEAT_GAPS + ("start", "end"), (), fmt_rupees)
def repeat_avg_return_bill_value(d, p, ctx):
    ids = _return_bills(d, p)
    if not ids:
        raise CannotCompute("no return bills in the window (the recipe gives null)")
    return rhu(Fraction(sum(d.bill_paise.get(b, 0) for b in ids), 100 * len(ids)), 2)


@recipe("repeat_call_list", REPEAT_GROUP + ("first_from", "first_to", "no_bill_through"),
        ("salesperson_ids", "category"), fmt_whole)
def repeat_call_list(d, p, ctx):
    days(p["first_from"], p["first_to"])
    to_date(p["no_bill_through"])
    category = p.get("category")
    count = 0
    for c in _repeat(d, p).group(p):
        if not p["first_from"] <= c.first_date <= p["first_to"]:
            continue
        if sum(dt <= p["no_bill_through"] for dt, _, _, _ in c.bills) != 1:
            continue
        if category is not None and category not in d.product_categories_of_bill(c.first_bill):
            continue
        count += 1
    return count


@recipe("repeat_weekly_returns_per_100", REPEAT_GROUP + REPEAT_GAPS + ("start", "end"),
        ("salesperson_ids",), fmt_2dp)
def repeat_weekly_returns_per_100(d, p, ctx):
    lo, hi = _gaps(p)
    n_days = len(days(p["start"], p["end"]))
    end = to_date(p["end"])
    first_from, first_to = (end - timedelta(hi)).isoformat(), (end - timedelta(lo)).isoformat()
    group = _repeat(d, p).group(p)
    eligible = sum(first_from <= c.first_date <= first_to for c in group)
    if eligible == 0:
        raise CannotCompute("no customer of the group is inside the return window on `end` (the recipe gives null)")
    bills = sum(1 for c in group for dt, gap, _, _ in c.bills
                if p["start"] <= dt <= p["end"] and lo <= gap <= hi)
    return rhu(Fraction(bills * 7 * 100, n_days * eligible), 2)


@recipe("repeat_date_offset", ("date", "days"), (), fmt_day)
def repeat_date_offset(d, p, ctx):
    if isinstance(p["days"], bool) or not isinstance(p["days"], int):
        raise CannotCompute("days must be a whole number")
    return (to_date(p["date"]) + timedelta(p["days"])).isoformat()


@recipe("repeat_rupees_at_stake", ("fair_rate", "own_rate", "new_customers_per_week", "avg_return_bill_value"),
        (), fmt_rupees, rupees_step=100)
def repeat_rupees_at_stake(d, p, ctx):
    for key, value in p.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise CannotCompute(f"{key} must be a number")

    def tenths(rate):  # (round(x × 10000) + 5) integer-divided by 10
        return (int(rhu(as_fraction(rate) * 10000)) + 5) // 10

    gap = tenths(p["fair_rate"]) - tenths(p["own_rate"])
    n10 = int(rhu(as_fraction(p["new_customers_per_week"]) * 10))
    bill = int(rhu(as_fraction(p["avg_return_bill_value"])))
    return int(rhu(Fraction(gap * n10 * bill, 10000) / 100) * 100)


def _bills_of_customer_id(d, p):
    if not isinstance(p["customer_id"], str):
        raise CannotCompute("customer_id must be text")
    return [row for row in d.bill_rows if row[4] == p["customer_id"]]


@recipe("repeat_placeholder_bills", ("customer_id",), (), fmt_whole)
def repeat_placeholder_bills(d, p, ctx):
    return len(_bills_of_customer_id(d, p))


@recipe("repeat_placeholder_stores", ("customer_id",), (), fmt_whole)
def repeat_placeholder_stores(d, p, ctx):
    return len({row[2] for row in _bills_of_customer_id(d, p)})


@recipe("repeat_placeholder_days", ("customer_id",), (), fmt_whole)
def repeat_placeholder_days(d, p, ctx):
    return len({row[1] for row in _bills_of_customer_id(d, p)})


# --------------------------------------------------------------------------- docs/CHECKS-baskets.md
#
# The "bigger baskets" lever. Recipes as written in docs/CHECKS-baskets.md (product bills only,
# carry bags left out, half-up rounding on exact fractions). PROVISIONAL below is kept for any
# future kind that has no document yet: such a kind is still a FAILURE, never a pass.

PROVISIONAL = {}


def provisional(kind):
    def register(fn):
        PROVISIONAL[kind] = fn
        return fn
    return register


def _product_bills(d, p, start=None, end=None, people="salesperson_ids"):
    """Ids of bills made at store_ids in the window, by those salespeople when given, that have
    at least one line that is not packaging. No valid-store-day rule."""
    lo, hi = start or p["start"], end or p["end"]
    days(lo, hi)
    who = p.get(people)
    made = d.baskets()
    return [bid for bid, dt, st, sp, _ in d.bill_rows
            if st in p["store_ids"] and lo <= dt <= hi and (who is None or sp in who) and bid in made]


def _share(part, whole, decimals=4):
    if whole == 0:
        raise CannotCompute("no bills to take a share of")
    return rhu(Fraction(part, whole), decimals)


def _z(a1, n1, a0, n0):
    if n1 == 0 or n0 == 0:
        raise CannotCompute("one side has no bills")
    pooled = Fraction(a1 + a0, n1 + n0)
    variance = pooled * (1 - pooled) * (Fraction(1, n1) + Fraction(1, n0))
    if variance <= 0:
        raise CannotCompute("standard error is zero")
    return rhu(Fraction(float(Fraction(a1, n1) - Fraction(a0, n0)) / math.sqrt(float(variance))), 2)


def _has(d, bills, category):
    made = d.baskets()
    return [b for b in bills if category in made[b]["cats"]]


@recipe("window_days", ("start", "end"), (), fmt_whole)
def window_days(d, p, ctx):
    return len(days(p["start"], p["end"]))


@recipe("product_bills", ("store_ids", "start", "end"), ("salesperson_ids",), fmt_whole)
def product_bills(d, p, ctx):
    return len(_product_bills(d, p))


@recipe("product_bills_per_week", ("store_ids", "start", "end"), ("salesperson_ids",), fmt_1dp)
def product_bills_per_week(d, p, ctx):
    return rhu(Fraction(len(_product_bills(d, p)) * 7, len(days(p["start"], p["end"]))), 1)


@recipe("category_bills", ("store_ids", "start", "end", "category"), ("salesperson_ids",), fmt_whole)
def category_bills(d, p, ctx):
    return len(_has(d, _product_bills(d, p), p["category"]))


@recipe("category_bills_per_week", ("store_ids", "start", "end", "category"), ("salesperson_ids",), fmt_1dp)
def category_bills_per_week(d, p, ctx):
    return rhu(Fraction(len(_has(d, _product_bills(d, p), p["category"])) * 7, len(days(p["start"], p["end"]))), 1)


@recipe("category_bill_share", ("store_ids", "start", "end", "category"), ("salesperson_ids",), fmt_percent1)
def category_bill_share(d, p, ctx):
    bills = _product_bills(d, p)
    return _share(len(_has(d, bills, p["category"])), len(bills))


@recipe("category_bill_share_z", ("store_ids", "start", "end", "category", "peer_salesperson_ids"), ("salesperson_ids",), fmt_2dp)
def category_bill_share_z(d, p, ctx):
    own, others = _product_bills(d, p), _product_bills(d, p, people="peer_salesperson_ids")
    return _z(len(_has(d, own, p["category"])), len(own), len(_has(d, others, p["category"])), len(others))


@recipe("attach_rate", ("store_ids", "start", "end", "main_category", "addon_category"), ("salesperson_ids",), fmt_percent1)
def attach_rate(d, p, ctx):
    main = _has(d, _product_bills(d, p), p["main_category"])
    return _share(len(_has(d, main, p["addon_category"])), len(main))


@recipe("attach_rate_z", ("store_ids", "start", "end", "base_start", "base_end", "main_category", "addon_category"), ("salesperson_ids",), fmt_2dp)
def attach_rate_z(d, p, ctx):
    now = _has(d, _product_bills(d, p), p["main_category"])
    base = _has(d, _product_bills(d, p, p["base_start"], p["base_end"]), p["main_category"])
    return _z(len(_has(d, now, p["addon_category"])), len(now), len(_has(d, base, p["addon_category"])), len(base))


@recipe("avg_addon_value", ("store_ids", "start", "end", "main_category", "addon_category"), ("salesperson_ids",), fmt_rupees)
def avg_addon_value(d, p, ctx):
    both = _has(d, _has(d, _product_bills(d, p), p["main_category"]), p["addon_category"])
    if not both:
        raise CannotCompute("no bill has both categories")
    made = d.baskets()
    return rhu(sum(made[b]["cats"][p["addon_category"]] for b in both) / len(both), 2)


@recipe("avg_bill_value_split", ("store_ids", "start", "end", "category", "with_category"), ("salesperson_ids",), fmt_rupees)
def avg_bill_value_split(d, p, ctx):
    made = d.baskets()
    bills = [b for b in _product_bills(d, p) if (p["category"] in made[b]["cats"]) == bool(p["with_category"])]
    if not bills:
        raise CannotCompute("no such bills")
    return rhu(sum(made[b]["sale"] for b in bills) / len(bills), 2)


@recipe("discount_rate", ("store_ids", "start", "end"), ("salesperson_ids",), fmt_percent1)
def discount_rate(d, p, ctx):
    made = d.baskets()
    bills = _product_bills(d, p)
    at_mrp = sum(made[b]["mrp"] for b in bills)
    if at_mrp == 0:
        raise CannotCompute("nothing sold in the window")
    return rhu(1 - sum(made[b]["sale"] for b in bills) / at_mrp, 4)


@recipe("discounted_bill_share", ("store_ids", "start", "end"), ("salesperson_ids",), fmt_percent1)
def discounted_bill_share(d, p, ctx):
    made = d.baskets()
    bills = _product_bills(d, p)
    return _share(sum(made[b]["discounted"] for b in bills), len(bills))


@recipe("discounted_bill_share_z", ("store_ids", "start", "end", "peer_salesperson_ids"), ("salesperson_ids",), fmt_2dp)
def discounted_bill_share_z(d, p, ctx):
    made = d.baskets()
    own, others = _product_bills(d, p), _product_bills(d, p, people="peer_salesperson_ids")
    return _z(sum(made[b]["discounted"] for b in own), len(own), sum(made[b]["discounted"] for b in others), len(others))


@recipe("mrp_sales_per_week", ("store_ids", "start", "end"), ("salesperson_ids",), fmt_rupees)
def mrp_sales_per_week(d, p, ctx):
    made = d.baskets()
    return rhu(sum(made[b]["mrp"] for b in _product_bills(d, p)) * 7 / len(days(p["start"], p["end"])), 0)


# ---- docs/CHECKS-baskets.md section 6: items per bill

@recipe("items_per_bill", ("store_ids", "start", "end"), ("salesperson_ids",), fmt_2dp)
def items_per_bill(d, p, ctx):
    made, bills = d.baskets(), _product_bills(d, p)
    if not bills:
        raise CannotCompute("no bills")
    return rhu(Fraction(sum(made[b]["items"] for b in bills), len(bills)), 2)


@recipe("items_per_bill_z", ("store_ids", "start", "end", "peer_salesperson_ids"), ("salesperson_ids",), fmt_2dp)
def items_per_bill_z(d, p, ctx):
    """Welch z of mean items per bill, salesperson_ids against peer_salesperson_ids (sample variances)."""
    made = d.baskets()
    a = [made[b]["items"] for b in _product_bills(d, p)]
    c = [made[b]["items"] for b in _product_bills(d, p, people="peer_salesperson_ids")]
    if len(a) < 2 or len(c) < 2:
        raise CannotCompute("fewer than two bills on one side")
    var = lambda xs: sum((x - sum(xs) / len(xs)) ** 2 for x in xs) / (len(xs) - 1)
    se2 = Fraction(var(a)) / len(a) + Fraction(var(c)) / len(c)
    if se2 <= 0:
        raise CannotCompute("standard error is zero")
    diff = Fraction(sum(a), len(a)) - Fraction(sum(c), len(c))
    return rhu(Fraction(float(diff) / math.sqrt(float(se2))), 2)


@recipe("avg_item_value", ("store_ids", "start", "end"), ("salesperson_ids",), fmt_rupees)
def avg_item_value(d, p, ctx):
    made, bills = d.baskets(), _product_bills(d, p)
    n = sum(made[b]["items"] for b in bills)
    if n == 0:
        raise CannotCompute("no items")
    return rhu(sum(made[b]["sale"] for b in bills) / n, 2)


@recipe("items_rupees_weekly", ("peer_check_id", "own_check_id", "bills_per_week_check_id", "item_value_check_id"),
        (), fmt_rupees, rupees_step=100)
def items_rupees_weekly(d, p, ctx):
    hundredths = lambda key: rhu(ctx.value_of(p[key]) * 100)
    raw = ((hundredths("peer_check_id") - hundredths("own_check_id")) * rhu(ctx.value_of(p["bills_per_week_check_id"]), 1)
           * rhu(ctx.value_of(p["item_value_check_id"])) / 100)
    return int(rhu(raw / 100) * 100)


def _tenths(ctx, check_id):        # a rate as displayed, in tenths of a percentage point
    return rhu(ctx.value_of(check_id) * 1000)


@recipe("attach_rupees_weekly", ("benchmark_check_id", "current_check_id", "bills_per_week_check_id", "addon_value_check_id"), (), fmt_rupees, rupees_step=100)
def attach_rupees_weekly(d, p, ctx):
    raw = ((_tenths(ctx, p["benchmark_check_id"]) - _tenths(ctx, p["current_check_id"]))
           * rhu(ctx.value_of(p["bills_per_week_check_id"]), 1) * rhu(ctx.value_of(p["addon_value_check_id"])) / 1000)
    return int(rhu(raw / 100) * 100)


@recipe("discount_given_away_weekly", ("own_check_id", "norm_check_id", "mrp_sales_check_id"), (), fmt_rupees, rupees_step=100)
def discount_given_away_weekly(d, p, ctx):
    raw = ((_tenths(ctx, p["own_check_id"]) - _tenths(ctx, p["norm_check_id"]))
           * rhu(ctx.value_of(p["mrp_sales_check_id"])) / 1000)
    return int(rhu(raw / 100) * 100)


@recipe("category_rupees_weekly", ("peer_check_id", "own_check_id", "bills_per_week_check_id", "with_check_id", "without_check_id"), (), fmt_rupees, rupees_step=100)
def category_rupees_weekly(d, p, ctx):
    raw = ((_tenths(ctx, p["peer_check_id"]) - _tenths(ctx, p["own_check_id"]))
           * rhu(ctx.value_of(p["bills_per_week_check_id"]), 1)
           * (rhu(ctx.value_of(p["with_check_id"])) - rhu(ctx.value_of(p["without_check_id"]))) / 1000)
    return int(rhu(raw / 100) * 100)


class ProvisionalContext:
    def __init__(self, data, beside):
        self.data, self.beside = data, beside

    def value_of(self, check_id):
        found = [c for c in self.beside if c.get("id") == check_id]
        if len(found) != 1:
            raise CannotCompute(f"needs exactly one check {check_id!r} beside it, found {len(found)}")
        return Fraction(provisional_value(self.data, found[0], self.beside))


def provisional_value(data, check, beside):
    if check["kind"] in RECIPES:
        return recompute(data, check, beside)
    return PROVISIONAL[check["kind"]](data, check["params"], ProvisionalContext(data, beside))


def undocumented(data, check, beside):
    """What to print for a kind with no recipe in any docs/CHECKS*.md."""
    kind = check["kind"]
    if kind not in PROVISIONAL:
        return "a recipe in scripts/verify.py (UNKNOWN KIND)"
    del EXACT_HALVES[:]
    try:
        value = provisional_value(data, check, beside)
        verdict = "the same" if same(value, check["value"]) else "DIFFERENT"
        note = f"the undocumented reading in scripts/README.md gives {show(value)}, {verdict}"
    except (CannotCompute, KeyError, TypeError, ValueError, ZeroDivisionError) as why:
        note = f"the undocumented reading in scripts/README.md cannot compute it: {why}"
    return f"a recipe in docs/CHECKS*.md (UNKNOWN KIND: no document describes it; {note})"


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
        del EXACT_HALVES[:]
        try:
            expected = recompute(data, check, beside)
        except KeyError:
            rep.fail(group, cid, kind, undocumented(data, check, beside), show(check["value"]))
            continue
        except CannotCompute as why:
            rep.fail(group, cid, kind, f"cannot be computed: {why}", show(check["value"]))
            continue
        hint = f"   [{EXACT_HALVES[-1]}]" if EXACT_HALVES else ""
        rep.test(group, same(expected, check["value"]), cid, kind, show(expected) + hint, show(check["value"]))

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
        if kind == "repeat_rupees_at_stake":
            verify_repeat_rupees_inputs(check, beside, rep)
        if isinstance(check["params"].get("exclude_customer_ids"), list):
            rule_ids = data.placeholder_ids()
            rep.test("rule    repeat: excluded ids = placeholder rule",
                     sorted(check["params"]["exclude_customer_ids"]) == rule_ids, cid, kind,
                     f"exclude_customer_ids {rule_ids} (blank, 25 or more bills, or 6 or more stores, up to as_of)",
                     str(sorted(check["params"]["exclude_customer_ids"])))


def verify_repeat_rupees_inputs(check, beside, rep):
    """docs/CHECKS-repeat.md: the rupees use the two `_recent` rates, new customers a week and
    the average return bill value of the same alert or card. The params must be those checks."""
    group = "rule    repeat rupees built on its own checks"
    cid = check["id"]
    stem = cid[:-len("rupees_at_stake")] if cid.endswith("rupees_at_stake") else cid + ":"
    by_id = {c["id"]: c for c in beside}
    found = {slug: by_id.get(stem + slug, {}).get("value")
             for slug in ("fair_rate_recent", "return_rate_recent", "new_customers_per_week",
                          "avg_return_bill_value")}
    p = check["params"]
    want_rates = sorted(str(found[k]) for k in ("fair_rate_recent", "return_rate_recent"))
    have_rates = sorted(str(p.get(k)) for k in ("fair_rate", "own_rate"))
    rep.test(group, None not in found.values() and want_rates == have_rates
             and str(found["new_customers_per_week"]) == str(p.get("new_customers_per_week"))
             and str(found["avg_return_bill_value"]) == str(p.get("avg_return_bill_value")),
             cid, check["kind"], f"params equal to the sibling checks {found}", json.dumps(p))


def verify_no_future(check, as_of, rep):
    """No check may be built on a row dated after as_of."""
    group = "rule    nothing after as_of"
    kind = check["kind"]
    if kind in RECIPES and RECIPES[kind].future_calendar:
        return  # a documented exception; its window is pinned inside its recipe
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
    # Every documented rupee figure is "whole rupees, a multiple of 100"; an alert whose rupee
    # kind has no recipe is still held to that step when its worked line is multiplied out.
    step = RECIPES[carriers[0]["kind"]].rupees_step if carriers else 100
    rep.test(group, any(same(rupees, c["value"]) for c in carriers) if isinstance(rupees, (int, float)) else False,
             aid, "rupees_at_stake_weekly",
             ("equal to the alert's rupees-at-stake check " + str([c["value"] for c in carriers])) if carriers
             else "a check of a rupees-at-stake kind that has a documented recipe (none in this alert)",
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
    per_person = Counter(card.get("salesperson_id") for card in out.get("cards", []))
    per_id = Counter(card.get("card_id") for card in out.get("cards", []))
    for card in out.get("cards", []):
        cid = card.get("card_id", "?")
        rep.test("rule    cards: one per salesperson",
                 per_person[card.get("salesperson_id")] == 1 and per_id[card.get("card_id")] == 1, cid,
                 "salesperson_id", "one card for this salesperson, and a card_id used once",
                 f"{per_person[card.get('salesperson_id')]} cards for {card.get('salesperson_id')}, "
                 f"{per_id[card.get('card_id')]} with this card_id")
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


FOLLOW_UP_DAYS = 7          # docs/METHOD-followup.md: "the run of exactly 7 days earlier"
EARLIER_WEEKS = 8           # docs/CHECKS-followup.md section 3: earlier_week_1 .. earlier_week_8
MIN_EARLIER_WEEKS = 4       # section 3.2: "With fewer than 4 earlier weeks the result is not_measurable"
MAX_INVALID_SHARE = Fraction(20, 100)   # section 3.1: "more than 20% of its store-days are invalid"


def find_earlier_run(file, raised, explicit=None):
    """The run of 7 days earlier: runs/<date>.json beside the file, or <date>.json in its folder."""
    if explicit:
        return Path(explicit) if Path(explicit).is_file() else None
    for candidate in (file.parent / "runs" / f"{raised}.json", file.parent / f"{raised}.json"):
        if candidate.is_file() and candidate.resolve() != file.resolve():
            return candidate
    return None


REAL_MOVE = 2  # docs/CHECKS-followup.md section 3: a move is called at 2 standard errors (or deviations)


def expected_moved(fu, slug, data, alert_fu, after_window):
    """`moved` from docs/CHECKS-followup.md sections 3.1 and 3.2, and why. Uses the values of
    the follow-up's own checks (each of which is recomputed from the CSVs on its own)."""
    kind, params = alert_fu.get("kind"), alert_fu.get("params") or {}
    if "before" not in slug:
        return "not_measurable", "the 'before' check is not written (it no longer recomputes)"
    if kind == "conversion":
        for st in params.get("store_ids", []):
            rows = data.store_days([st], *after_window)
            bad = sum(r[4] is not None for r in rows)
            if len(rows) == bad:
                return "not_measurable", f"{st} has no valid store-day in the week"
            if Fraction(bad, len(rows)) > MAX_INVALID_SHARE:
                return "not_measurable", f"{st}: {bad} of {len(rows)} store-days in the week are invalid"
    if "after" not in slug or isinstance(slug["after"]["value"], (str, bool, type(None))):
        return "not_measurable", "the recipe gives no value for the week"
    before, after = as_fraction(slug["before"]["value"]), as_fraction(slug["after"]["value"])
    change = after - before if alert_fu.get("higher_is_better", True) else before - after
    if kind == "conversion":
        if "after_numerator" not in slug or "after_denominator" not in slug:
            raise CannotCompute("after_numerator and after_denominator checks are needed for conversion")
        if "before_numerator" not in slug or "before_denominator" not in slug:
            raise CannotCompute("before_numerator and before_denominator checks are needed for conversion")
        b = as_fraction(slug["after_numerator"]["value"])
        n = as_fraction(slug["after_denominator"]["value"])
        b0 = as_fraction(slug["before_numerator"]["value"])
        n0 = as_fraction(slug["before_denominator"]["value"])
        if n <= 0 or n0 <= 0:
            return "not_measurable", "no walk-ins in the week"
        # REAL_MOVE standard errors of (after - before): the two errors add in squares
        se_sq = (b / n) * (1 - b / n) / n + (b0 / n0) * (1 - b0 / n0) / n0
        spread_sq, name = REAL_MOVE * REAL_MOVE * se_sq, f"{REAL_MOVE} standard errors of the difference"
    else:
        weeks = [as_fraction(slug[f"earlier_week_{k}"]["value"]) for k in range(1, EARLIER_WEEKS + 1)
                 if f"earlier_week_{k}" in slug
                 and not isinstance(slug[f"earlier_week_{k}"]["value"], (str, bool, type(None)))]
        if len(weeks) < MIN_EARLIER_WEEKS:
            return "not_measurable", f"only {len(weeks)} earlier weeks have a value"
        mean = sum(weeks) / len(weeks)
        var = sum((w - mean) ** 2 for w in weeks) / (len(weeks) - 1)
        if var == 0:
            return "not_measurable", "the same seven-day figure in every earlier week"
        spread_sq, name = REAL_MOVE * REAL_MOVE * var, f"{REAL_MOVE} standard deviations of the earlier weeks"
    why = f"change {float(change):+.4f} against {name} {math.sqrt(float(spread_sq)):.4f}"
    if change > 0 and change * change >= spread_sq:
        return "improved", why
    if change < 0 and change * change >= spread_sq:
        return "worse", why
    return "no_change", why


def verify_follow_up_rules(out, data, rep, file, earlier_file):
    """docs/CHECKS-followup.md section 3 and docs/METHOD-followup.md section 1."""
    group = "rule    follow-up matches the earlier run"
    as_of = data.as_of
    raised = (to_date(as_of) - timedelta(FOLLOW_UP_DAYS)).isoformat()
    after_window = ((to_date(raised) + timedelta(1)).isoformat(), as_of)
    fus = out.get("follow_ups", [])
    path = find_earlier_run(Path(file), raised, earlier_file)
    earlier = {}
    if path is None:
        rep.test(group, not fus, "follow_ups", "earlier run", f"no follow-ups when there is no run for {raised}",
                 f"{len(fus)} follow-ups, and no runs/{raised}.json beside the file (pass --earlier-run)")
    else:
        try:
            prior = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CannotRun(f"cannot read the earlier run {path}: {exc}")
        rep.test(group, prior.get("as_of") == raised, str(path), "as_of", raised, repr(prior.get("as_of")))
        for block in prior.get("area_managers", []):
            for alert in block.get("alerts", []):
                earlier[alert.get("alert_id")] = (block.get("area_manager_id"), alert)
        ids = [fu.get("alert_id") for fu in fus]
        rep.test(group, sorted(map(str, ids)) == sorted(map(str, earlier)), "follow_ups", "alert ids",
                 f"one follow-up for each alert of {path.name}: {sorted(map(str, earlier))}", str(sorted(map(str, ids))))

    for fu in fus:
        fid = fu.get("alert_id", "?")
        prefix = f"followup:{fid}:"
        slug = {c["id"][len(prefix):]: c for c in fu.get("checks", [])
                if is_check(c) and c["id"].startswith(prefix)}
        stray = [c.get("id") for c in fu.get("checks", []) if not (is_check(c) and c["id"].startswith(prefix))]
        rep.test(group, not stray, fid, "check ids", f"every check id starts with {prefix!r}", str(stray))
        rep.test(group, fu.get("raised_as_of") == raised and fu.get("measured_as_of") == as_of, fid, "dates",
                 f"raised {raised}, measured {as_of}", f"raised {fu.get('raised_as_of')!r}, measured {fu.get('measured_as_of')!r}")
        nm = fu.get("moved") == "not_measurable"

        def field_is_check(field, name):
            c = slug.get(name)
            rep.test(group, c is not None and same_or_none(c["value"], fu.get(field))
                     and fu.get(f"{field}_display") == c["display"], fid, field,
                     f"{field} and {field}_display are the value and display of check {prefix}{name}"
                     + (f": {c['value']!r}, {c['display']!r}" if c else " (no such check)"),
                     f"{fu.get(field)!r}, {fu.get(f'{field}_display')!r}")

        field_is_check("before", "before")
        field_is_check("target", "target")
        if nm:
            rep.test(group, fu.get("after") is None and fu.get("after_display") == "not measurable", fid, "after",
                     "after null and after_display 'not measurable' when the week cannot be measured",
                     f"{fu.get('after')!r}, {fu.get('after_display')!r}")
        else:
            field_is_check("after", "after")

        if fid not in earlier:
            if path is not None:
                rep.fail(group, fid, "alert_id", f"an alert of {path.name}", "no such alert in the earlier run")
            continue
        manager, alert = earlier[fid]
        afu = alert.get("follow_up") or {}
        for field, want in (("area_manager_id", manager), ("store_ids", alert.get("store_ids")),
                            ("lever", alert.get("lever")), ("headline", alert.get("headline")),
                            ("action_text", (alert.get("action") or {}).get("text")),
                            ("metric_label", afu.get("metric_label")),
                            ("before", afu.get("baseline_value")), ("target", afu.get("target_value"))):
            rep.test(group, fu.get(field) == want, fid, field, f"as on the alert of {raised}: {want!r}", repr(fu.get(field)))

        def check_is(name, kind, params, required=True):
            c = slug.get(name)
            if c is None:
                if required:
                    rep.fail(group, fid, name, f"a check {prefix}{name} of kind {kind}", "no such check")
                return
            rep.test(group, c["kind"] == kind and c["params"] == params, fid, name,
                     f"kind {kind}, params {json.dumps(params, ensure_ascii=False)}",
                     f"kind {c['kind']}, params {json.dumps(c['params'], ensure_ascii=False)}")

        after_params = dict(afu.get("params") or {}, start=after_window[0], end=after_window[1])
        check_is("before", afu.get("kind"), afu.get("params"), required=not nm)
        check_is("after", afu.get("kind"), after_params, required=not nm)
        first_store = (alert.get("store_ids") or [None])[0]
        check_is("days", "day_count", {"state": data.state_of_store.get(first_store), "start": after_window[0],
                                       "end": after_window[1], "day_type": "all"})
        if "days" in slug:
            rep.test(group, slug["days"]["value"] == FOLLOW_UP_DAYS, fid, "days", str(FOLLOW_UP_DAYS), repr(slug["days"]["value"]))
        carriers = [c for c in alert.get("checks", []) if is_check(c)
                    and not isinstance(c["value"], (str, bool)) and same(afu.get("target_value"), c["value"])]
        target = slug.get("target")
        rep.test(group, target is not None and any(c["kind"] == target["kind"] and c["params"] == target["params"]
                                                   for c in carriers), fid, "target",
                 f"kind and params of the check of the {raised} alert that carried target_value {afu.get('target_value')!r}",
                 "no such check on that alert" if target is not None else "no target check")
        if afu.get("kind") == "conversion":
            check_is("after_numerator", "bills_count", after_params, required=not nm)
            check_is("after_denominator", "footfall_sum", after_params, required=not nm)
        else:
            for k in range(1, EARLIER_WEEKS + 1):
                end = to_date(raised) - timedelta(7 * (k - 1))
                window = dict(afu.get("params") or {}, start=(end - timedelta(6)).isoformat(), end=end.isoformat())
                name = f"earlier_week_{k}"
                check_is(name, afu.get("kind"), window, required=False)
                if name not in slug and afu.get("kind") in RECIPES:   # left out only when it has no value
                    probe = {"id": prefix + name, "kind": afu.get("kind"), "params": window, "value": None, "display": ""}
                    try:
                        value = show(recompute(data, probe, []))
                        rep.fail(group, fid, name, f"a check, because the week has the value {value}", "left out")
                    except CannotCompute:
                        rep.ok(group)

        group_moved = "rule    follow-up verdict follows the rule"
        try:
            want, why = expected_moved(fu, slug, data, afu, after_window)
            rep.test(group_moved, fu.get("moved") == want, fid, "moved", f"{want} ({why})", repr(fu.get("moved")))
        except (CannotCompute, ValueError, ZeroDivisionError) as exc:
            rep.fail(group_moved, fid, "moved", f"cannot be worked out: {exc}", repr(fu.get("moved")))
        said = str(fu.get("verdict", "")).lower()
        tone = {"improved": "improved" in said, "worse": "worse" in said,
                "no_change": "no change" in said or "no real change" in said,
                "not_measurable": "not measurable" in said or "cannot be measured" in said or "could not be measured" in said}
        rep.test(group_moved, tone.get(fu.get("moved"), False), fid, "verdict",
                 f"a sentence that says {fu.get('moved')!r}", repr(fu.get("verdict")))


def same_or_none(expected, found):
    if expected is None or found is None:
        return expected is None and found is None
    return same(expected, found)


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


def run(file, data_dir, strict=False, stream=None, earlier_run=None):
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
    # a placeholder customer id quoted in text (C99999999) is an id, not a number
    ids = sorted(set(ids) | set(data.placeholder_ids()), key=len, reverse=True)

    verify_checks(out, data, rep)
    for block in out.get("area_managers", []):
        for alert in block.get("alerts", []):
            verify_alert(alert, data, rep, ids)
    verify_managers(out, data, rep)
    verify_cards(out, data, rep, ids)
    verify_follow_ups(out, data, rep, ids)
    verify_follow_up_rules(out, data, rep, file, earlier_run)
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
    parser.add_argument("--earlier-run", default=None,
                        help="the run of 7 days earlier, for the follow-ups (default: runs/<as_of - 7 days>.json "
                             "beside the file, or <as_of - 7 days>.json in its folder)")
    args = parser.parse_args(argv)
    try:
        return run(args.file, args.data_dir, args.strict, earlier_run=args.earlier_run)
    except CannotRun as why:
        print(f"CANNOT RUN: {why}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
