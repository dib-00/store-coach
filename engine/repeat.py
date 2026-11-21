"""Lever 3, "more repeat" (customers billing again 30+ days after their first bill). Plugs into engine/run.py.

Interface (the same for every lever module):
    detect(m)            -> (alert candidates, notes)   candidates are full Alert dicts, rank 0
    card_candidates(m)   -> list of card candidates     see engine/cards.py
    data_issues(m, windows) -> list of DataIssue dicts
Check kinds this lever adds are registered in metrics.EXTRA_KINDS and checks.EXTRA_DISPLAY.

ONE DEFINITION, used by every figure here (docs/METHOD-repeat.md, docs/CHECKS-repeat.md):
  - a customer belongs to the salesperson and store of their FIRST bill in the data;
  - they RETURNED if they billed again at ANY store 30 to 180 days after that first bill;
  - the cohort is customers whose first bill is on or before as_of minus 180 days;
  - placeholder customer ids (not a person) are excluded.
People are compared with same-store colleagues, stores with the other stores of their
city, always over the SAME first-bill months.
"""
from __future__ import annotations

import math
from fractions import Fraction

import pandas as pd

from . import checks, metrics
from .checks import CheckBook, conv_tenths, fmt_date, fmt_inr, fmt_int_in, fmt_num, fmt_pct, numbers_not_in_checks
from .detect import is_new_store, join_names
from .metrics import Metrics, add_days, d, rnd, rnd_div
from .rank import has_who_what_when

LEVER = "more_repeat"

MIN_GAP_DAYS = 30  # a bill this many days after the first bill, or later, is a return
MAX_GAP_DAYS = 180  # ... up to this many days after it
PLACEHOLDER_MIN_BILLS = 25  # a customer id on this many bills is not one person
PLACEHOLDER_MIN_STORES = 6  # ... nor is one that billed at this many different stores

Z_PERSON = 3.6  # one-sided 0.05 / (2 directions x about 160 salespeople)  -> z 3.6
Z_STORE = 3.0  # one-sided 0.05 / (2 directions x 19 stores)                -> z 3.0
LOW_RATIO = 0.67  # a salesperson's rate at most two thirds of the fair rate
HIGH_RATIO = 1.5  # a role model's rate at least one and a half times the fair rate
STORE_LOW_RATIO = 0.80  # a store's rate at most 80% of the fair rate
MIN_CUSTOMERS = 200  # cohort customers needed to judge a salesperson
MIN_STORE_CUSTOMERS = 500  # ... and a store
MIN_QUARTER_CUSTOMERS = 30  # a first-bill quarter is compared when both sides have this many
MIN_QUARTERS = 3  # at least this many quarters compared
CONSISTENT_SHARE = 0.75  # and the gap has the same sign in this share of them

NEW_DAYS = 91  # new customers a week = first bills in the last 13 weeks / 13
RECENT_DAYS = 364  # rupees use the gap among customers first billed in the latest 52 weeks of the cohort
VALUE_DAYS = 364  # average value of a return bill: the last 52 weeks
MIN_RETURN_BILLS = 20  # return bills needed for that average
FOLLOW_DAYS = 91  # baseline window of the follow-up metric (it is a per-week figure, so 7 days compare with it)
CALL_WINDOWS = [60, 44, 37]  # call customers first billed 30 to N days ago; the first N that fits a day
MAX_CALLS = 30  # calls one person can make in a day
COACHED = 2  # colleagues a role model sits with in one day

FORMULA = ("(fair return rate − own return rate, both for customers first billed in the latest 52 weeks of the cohort) "
           "× new customers a week × average value of a return bill")
FORMULA_ROLE = ("(role model's return rate − colleagues' return rate over the same first-bill months, both for customers "
                "first billed in the latest 52 weeks of the cohort) × new customers a week of the colleagues coached "
                "today × average value of a return bill")


# ------------------------------------------------------------------------------------------ core tables
class Core:
    """Customer-level tables built once per run from m.data (already cut at as_of)."""

    def __init__(self, m: Metrics):
        b = m.data.bills[["bill_id", "bill_date", "store_id", "salesperson_id", "customer_id", "value"]].copy()
        per = b.groupby("customer_id").agg(n=("bill_id", "size"), stores=("store_id", "nunique"))
        self.placeholders = sorted(
            c for c, n, s in zip(per.index, per["n"], per["stores"])
            if str(c).strip() == "" or n >= PLACEHOLDER_MIN_BILLS or s >= PLACEHOLDER_MIN_STORES
        )
        self.all_bills = b
        b = b[~b["customer_id"].isin(self.placeholders)]
        b = b.sort_values(["customer_id", "bill_date", "bill_id"], kind="mergesort").reset_index(drop=True)
        b["ord"] = (pd.to_datetime(b["bill_date"]) - pd.Timestamp("1970-01-01")).dt.days.astype(int)
        b["first_ord"] = b.groupby("customer_id")["ord"].transform("first")
        b["gap"] = b["ord"] - b["first_ord"]
        self.bills = b
        first = b.drop_duplicates("customer_id", keep="first")
        self.cust = pd.DataFrame({
            "customer_id": first["customer_id"].to_numpy(),
            "first_bill_id": first["bill_id"].to_numpy(),
            "first_date": first["bill_date"].to_numpy(),
            "store_id": first["store_id"].to_numpy(),
            "salesperson_id": first["salesperson_id"].to_numpy(),
        })
        self.lines = m.data.lines
        self._agg: dict = {}
        self._cat: dict = {}

    def agg(self, first_bill_to: str, min_gap: int, max_gap: int, first_bill_from: str = "") -> dict:
        """(store, salesperson, first-bill month) -> [customers, returned] for the cohort."""
        key = (first_bill_to, min_gap, max_gap, first_bill_from)
        if key not in self._agg:
            b = self.bills
            back = set(b.loc[(b["gap"] >= min_gap) & (b["gap"] <= max_gap), "customer_id"])
            out: dict = {}
            c = self.cust
            for cid, dt, s, p in zip(c["customer_id"], c["first_date"], c["store_id"], c["salesperson_id"]):
                if first_bill_from <= dt <= first_bill_to:
                    row = out.setdefault((s, p, dt[:7]), [0, 0])
                    row[0] += 1
                    row[1] += cid in back
            self._agg[key] = out
        return self._agg[key]

    def first_bills_with(self, category: str) -> set:
        """Bill ids with at least one non-packaging line of the category."""
        if category not in self._cat:
            ln = self.lines
            ok = (ln["category"] == category) & (ln["is_packaging"].astype(str) != "1")
            self._cat[category] = set(ln.loc[ok, "bill_id"])
        return self._cat[category]


def core_of(m: Metrics) -> Core:
    c = getattr(m, "_repeat_core", None)
    if c is None:
        c = Core(m)
        m._repeat_core = c
    return c


# ------------------------------------------------------------------------------------------ the arithmetic
def _by_month(agg: dict, stores, sps) -> dict:
    stores = set(stores)
    sps = set(sps) if sps is not None else None
    out: dict = {}
    for (s, p, month), (n, r) in agg.items():
        if s in stores and (sps is None or p in sps):
            row = out.setdefault(month, [0, 0])
            row[0] += n
            row[1] += r
    return out


def _cohort(m: Metrics, p: dict) -> dict:
    return core_of(m).agg(p["first_bill_to"], p["min_gap_days"], p["max_gap_days"], p.get("first_bill_from", ""))


def _subject(m: Metrics, p: dict) -> dict:
    return _by_month(_cohort(m, p), p["store_ids"], p.get("salesperson_ids"))


def _peers(m: Metrics, p: dict) -> dict:
    return _by_month(_cohort(m, p), p["peer_store_ids"], p.get("peer_salesperson_ids"))


def _totals(by_month: dict) -> tuple[int, int]:
    return sum(v[0] for v in by_month.values()), sum(v[1] for v in by_month.values())


def _covered(S: dict, P: dict) -> bool:
    """Every first-bill month of the subject also has peer customers."""
    return bool(S) and all(P.get(month, [0, 0])[0] > 0 for month in S)


def fair_rate(S: dict, P: dict):
    """The peers' month-by-month return rates applied to the subject's own mix of first-bill months."""
    if not _covered(S, P):
        return None
    n = sum(v[0] for v in S.values())
    expected = sum(Fraction(S[month][0] * P[month][1], P[month][0]) for month in sorted(S))  # exact
    return expected / n


def cmh_z(S: dict, P: dict):
    """Cochran-Mantel-Haenszel z, stratified by first-bill month. Positive = the subject returns more."""
    if not _covered(S, P):
        return None
    a = e = v = 0.0
    for month in sorted(S):
        n1, r1 = S[month]
        n0, r0 = P[month]
        big_n, m1 = n1 + n0, r1 + r0
        a += r1
        e += n1 * m1 / big_n
        if big_n > 1:
            v += n1 * n0 * m1 * (big_n - m1) / (big_n * big_n * (big_n - 1))
    return (a - e) / math.sqrt(v) if v > 0 else None


def _quarter(month: str) -> str:
    return f"{month[:4]}Q{(int(month[5:7]) - 1) // 3 + 1}"


def quarters(S: dict, P: dict, min_customers: int) -> dict:
    """First-bill quarters where both sides have enough customers, and where the subject is ahead / behind."""
    qs: dict = {}
    for side, table in ((0, S), (1, P)):
        for month, (n, r) in table.items():
            row = qs.setdefault(_quarter(month), [0, 0, 0, 0])
            row[side * 2] += n
            row[side * 2 + 1] += r
    out = {"compared": 0, "ahead": 0, "behind": 0}
    for q in sorted(qs):
        n1, r1, n0, r0 = qs[q]
        if n1 >= min_customers and n0 >= min_customers:
            out["compared"] += 1
            # exact comparison of r1/n1 with r0/n0 in whole numbers
            if r1 * n0 > r0 * n1:
                out["ahead"] += 1
            elif r1 * n0 < r0 * n1:
                out["behind"] += 1
    return out


def rupees(fair: float, own: float, new_per_week: float, value: float) -> int:
    """Rupees a week from the figures exactly as displayed (rate to 0.1 of a point, customers to 0.1,
    bill value to a whole rupee), rounded half up to the nearest Rs 100."""
    gap_tenths = conv_tenths(fair) - conv_tenths(own)
    raw = gap_tenths * int(rnd(new_per_week * 10)) * int(rnd(value)) / 10000
    return int(rnd(raw / 100)) * 100


# ------------------------------------------------------------------------------------------ check kinds
def k_customers(m, p):
    return int(_totals(_subject(m, p))[0])


def k_returned(m, p):
    return int(_totals(_subject(m, p))[1])


def k_return_rate(m, p):
    n, r = _totals(_subject(m, p))
    return rnd_div(r, n, 4) if n else None


def k_fair_rate(m, p):
    v = fair_rate(_subject(m, p), _peers(m, p))
    return rnd_div(v, 1, 4) if v is not None else None


def k_z(m, p):
    v = cmh_z(_subject(m, p), _peers(m, p))
    return rnd(v, 2) if v is not None else None


def k_quarters(m, p):
    return quarters(_subject(m, p), _peers(m, p), p["min_customers"])[p["count"]]


def _first_in(m, p, start, end):
    c = core_of(m).cust
    ok = c["store_id"].isin(p["store_ids"]) & (c["first_date"] >= start) & (c["first_date"] <= end)
    if p.get("salesperson_ids") is not None:
        ok &= c["salesperson_id"].isin(p["salesperson_ids"])
    return c[ok]


def k_new_per_week(m, p):
    days = (d(p["end"]) - d(p["start"])).days + 1
    return rnd_div(len(_first_in(m, p, p["start"], p["end"])) * 7, days, 1) if days > 0 else None


def _return_bills(m, p):
    b = core_of(m).bills
    ok = (b["store_id"].isin(p["store_ids"]) & (b["bill_date"] >= p["start"]) & (b["bill_date"] <= p["end"])
          & (b["gap"] >= p["min_gap_days"]) & (b["gap"] <= p["max_gap_days"]))
    return b[ok]


def k_return_bill_count(m, p):
    return int(len(_return_bills(m, p)))


def k_avg_return_bill_value(m, p):
    x = _return_bills(m, p)
    return rnd_div(float(x["value"].sum()), len(x), 2) if len(x) else None


def k_call_list(m, p):
    core = core_of(m)
    c = _first_in(m, p, p["first_from"], p["first_to"])
    b = core.bills
    n_bills = b[b["bill_date"] <= p["no_bill_through"]].groupby("customer_id").size()
    c = c[c["customer_id"].map(n_bills).fillna(0) == 1]
    if p.get("category"):
        c = c[c["first_bill_id"].isin(core.first_bills_with(p["category"]))]
    return int(len(c))


def k_weekly_returns(m, p):
    """Return bills a week (at any store) per 100 of the group's customers who are inside their return window."""
    core = core_of(m)
    days = (d(p["end"]) - d(p["start"])).days + 1
    eligible = _first_in(m, p, add_days(p["end"], -p["max_gap_days"]), add_days(p["end"], -p["min_gap_days"]))
    if days <= 0 or not len(eligible):
        return None
    c = core.cust
    mine = c["store_id"].isin(p["store_ids"])
    if p.get("salesperson_ids") is not None:
        mine &= c["salesperson_id"].isin(p["salesperson_ids"])
    b = core.bills
    ok = ((b["bill_date"] >= p["start"]) & (b["bill_date"] <= p["end"]) & (b["gap"] >= p["min_gap_days"])
          & (b["gap"] <= p["max_gap_days"]) & b["customer_id"].isin(set(c.loc[mine, "customer_id"])))
    return rnd_div(int(ok.sum()) * 700, days * len(eligible), 2)


def k_date_offset(m, p):
    return add_days(p["date"], p["days"])


def k_rupees(m, p):
    return rupees(p["fair_rate"], p["own_rate"], p["new_customers_per_week"], p["avg_return_bill_value"])


def _placeholder_rows(m, p):
    b = core_of(m).all_bills
    return b[b["customer_id"] == p["customer_id"]]


def k_placeholder_bills(m, p):
    return int(len(_placeholder_rows(m, p)))


def k_placeholder_stores(m, p):
    return int(_placeholder_rows(m, p)["store_id"].nunique())


_fmt_count = lambda v: fmt_int_in(int(v))
_KINDS = {
    "repeat_customers": (k_customers, _fmt_count),
    "repeat_returned": (k_returned, _fmt_count),
    "repeat_return_rate": (k_return_rate, fmt_pct),
    "repeat_fair_rate": (k_fair_rate, fmt_pct),
    "repeat_z": (k_z, lambda v: fmt_num(v, 2)),
    "repeat_quarters": (k_quarters, _fmt_count),
    "repeat_new_customers_per_week": (k_new_per_week, lambda v: fmt_num(v, 1)),
    "repeat_return_bill_count": (k_return_bill_count, _fmt_count),
    "repeat_avg_return_bill_value": (k_avg_return_bill_value, fmt_inr),
    "repeat_call_list": (k_call_list, _fmt_count),
    "repeat_weekly_returns_per_100": (k_weekly_returns, lambda v: fmt_num(v, 2)),
    "repeat_date_offset": (k_date_offset, fmt_date),
    "repeat_rupees_at_stake": (k_rupees, fmt_inr),
    "repeat_placeholder_bills": (k_placeholder_bills, _fmt_count),
    "repeat_placeholder_stores": (k_placeholder_stores, _fmt_count),
}
for _kind, (_fn, _show) in _KINDS.items():
    metrics.EXTRA_KINDS[_kind] = _fn
    checks.EXTRA_DISPLAY[_kind] = _show


# ------------------------------------------------------------------------------------------ the lever
def first_name(name: str) -> str:
    return name.split()[0]


def follow_label(who: str) -> str:
    return (f"Return bills a week, at any store, per 100 customers of {who} who are {MIN_GAP_DAYS} to {MAX_GAP_DAYS} "
            "days past their first bill")


class Repeat:
    def __init__(self, m: Metrics):
        self.m = m
        self.core = core_of(m)
        self.as_of = m.as_of
        self.cohort_end = add_days(self.as_of, -MAX_GAP_DAYS)
        self.coh = {"first_bill_to": self.cohort_end, "min_gap_days": MIN_GAP_DAYS, "max_gap_days": MAX_GAP_DAYS,
                    "exclude_customer_ids": list(self.core.placeholders)}
        self.agg = self.core.agg(self.cohort_end, MIN_GAP_DAYS, MAX_GAP_DAYS)
        self.store_rows = {r["store_id"]: r for r in m.data.stores.to_dict("records")}
        self.established = sorted(s for s, r in self.store_rows.items() if not is_new_store(r["opened_on"], self.as_of))
        self.notes: list[str] = []
        self.alerts: list[dict] = []
        self.cards: list[dict] = []
        self.sellers: dict[str, list[str]] = {}  # store -> salespeople with cohort customers first billed there
        for (s, p, _month) in self.agg:
            if p not in self.sellers.setdefault(s, []):
                self.sellers[s].append(p)
        for s in self.sellers:
            self.sellers[s].sort()
        self._run()

    # ---------------------------------------------------------------- small helpers
    def name(self, sp: str) -> str:
        return self.m.sp_name.get(sp, sp)

    def active(self, sp: str) -> bool:
        """Still on the roster in the last 7 days (or, with no roster at all, billed in the last 28)."""
        m = self.m
        if m.roster_min is None:
            return m.sp_bill_count(sp, add_days(self.as_of, -27), self.as_of) > 0
        last = m.last_roster_date(sp)
        return last is not None and (d(self.as_of) - d(last)).days <= 6

    def definition(self, who: str, versus: str) -> str:
        ids = join_names(self.core.placeholders)
        excl = f" Placeholder customer id {ids} is excluded." if ids else ""
        return (
            "A customer belongs to the salesperson and store of their first bill in the data. They returned if "
            f"they billed again at any store {MIN_GAP_DAYS} to {MAX_GAP_DAYS} days after that first bill. Counted over "
            f"customers whose first bill is on or before {fmt_date(self.cohort_end)} ({MAX_GAP_DAYS} days before "
            f"{fmt_date(self.as_of)}), so each has had the full window.{excl} {who} is compared with {versus} over the "
            "same first-bill months: the fair rate is their month-by-month return rate applied to "
            f"{who}'s own mix of first-bill months."
        )

    def stat(self, subject: dict, peer: dict) -> dict | None:
        """Figures for one comparison, rounded exactly as the checks store them."""
        m, p = self.m, {**subject, **peer, **self.coh}
        n = m.compute("repeat_customers", p)
        rate, fair, z = (m.compute(k, p) for k in ("repeat_return_rate", "repeat_fair_rate", "repeat_z"))
        if rate is None or fair is None or z is None or fair <= 0:
            return None
        q = quarters(_subject(m, p), _peers(m, p), MIN_QUARTER_CUSTOMERS)
        return {"n": n, "rate": rate, "fair": fair, "z": z, "q": q, "params": p}

    def person(self, store: str, sp: str, peers: list[str]) -> dict | None:
        if not peers:
            return None
        return self.stat({"store_ids": [store], "salesperson_ids": [sp]},
                         {"peer_store_ids": [store], "peer_salesperson_ids": sorted(peers)})

    @staticmethod
    def consistent(st: dict, side: str) -> bool:
        q = st["q"]
        return q["compared"] >= MIN_QUARTERS and q[side] >= CONSISTENT_SHARE * q["compared"]

    def is_low(self, st: dict | None, z_min: float = Z_PERSON, ratio: float = LOW_RATIO, n_min: int = MIN_CUSTOMERS) -> bool:
        return bool(st) and st["n"] >= n_min and st["z"] <= -z_min and st["rate"] <= ratio * st["fair"] \
            and self.consistent(st, "behind")

    def is_high(self, st: dict | None) -> bool:
        return bool(st) and st["n"] >= MIN_CUSTOMERS and st["z"] >= Z_PERSON and st["rate"] >= HIGH_RATIO * st["fair"] \
            and self.consistent(st, "ahead")

    # ---------------------------------------------------------------- shared check builders
    def comparison_checks(self, book: CheckBook, st: dict, who: str, versus: str, side: str) -> dict:
        p = st["params"]
        own = {k: v for k, v in p.items() if not k.startswith("peer_")}
        tail = (f"billed again at any store {MIN_GAP_DAYS} to {MAX_GAP_DAYS} days after the first bill; first bill on or "
                f"before {fmt_date(self.cohort_end)}; placeholder ids excluded")
        out = {
            "n": book.add("customers", f"Customers first billed by {who} ({tail})", "repeat_customers", dict(own)),
            "returned": book.add("returned", f"Of those, customers who returned ({tail})", "repeat_returned", dict(own)),
            "rate": book.add("return_rate", f"Return rate, {who} ({tail})", "repeat_return_rate", dict(own)),
            "fair": book.add("fair_rate", f"Fair return rate: {versus}, same first-bill months as {who} ({tail})",
                             "repeat_fair_rate", dict(p)),
            "z": book.add("z", f"Stratified z (by first-bill month), {who} against {versus}", "repeat_z", dict(p)),
        }
        qp = {**p, "min_customers": MIN_QUARTER_CUSTOMERS}
        out["qc"] = book.add("quarters_compared", f"First-bill quarters compared (both sides {MIN_QUARTER_CUSTOMERS} or more customers)",
                             "repeat_quarters", {**qp, "count": "compared"})
        out["qs"] = book.add(f"quarters_{side}", f"Quarters in which {who} is {side}", "repeat_quarters", {**qp, "count": side})
        return out

    def money_checks(self, book: CheckBook, store: str, group: dict, who_new: str, st: dict, who: str, versus: str,
                     formula: str, role_model: bool = False):
        """Recent gap, new customers a week, the value of a return bill, rupees at stake and the worked line.

        The gap is taken among customers first billed in the latest 52 weeks of the cohort: the early months of the
        data hold many existing regulars, whose return rates are far higher than a new customer's today.
        Returns None when any piece is missing.
        """
        as_of = self.as_of
        ex = {"exclude_customer_ids": list(self.core.placeholders)}
        recent_from = add_days(self.cohort_end, -(RECENT_DAYS - 1))
        c_from = book.add("recent_from", f"Start of the latest 52 weeks of the cohort ({RECENT_DAYS - 1} days before "
                          f"{fmt_date(self.cohort_end)})", "repeat_date_offset",
                          {"date": as_of, "days": -(MAX_GAP_DAYS + RECENT_DAYS - 1)})
        p = {**st["params"], "first_bill_from": recent_from}
        own_p = {k: v for k, v in p.items() if not k.startswith("peer_")}
        span = f"customers first billed {fmt_date(recent_from)} to {fmt_date(self.cohort_end)}"
        c_own = book.add("return_rate_recent", f"Return rate, {who}, {span}", "repeat_return_rate", own_p)
        c_fair = book.add("fair_rate_recent", f"Fair return rate: {versus}, same first-bill months as {who}, {span}",
                          "repeat_fair_rate", p)
        new_w = {"start": add_days(as_of, -(NEW_DAYS - 1)), "end": as_of}
        c_new = book.add("new_customers_per_week",
                         f"New customers a week, {who_new}: first bills {fmt_date(new_w['start'])} to {fmt_date(as_of)}, "
                         f"divided by {NEW_DAYS // 7} weeks", "repeat_new_customers_per_week", {**group, **new_w, **ex})
        val_w = {"store_ids": [store], "start": add_days(as_of, -(VALUE_DAYS - 1)), "end": as_of,
                 "min_gap_days": MIN_GAP_DAYS, "max_gap_days": MAX_GAP_DAYS, **ex}
        label = (f"bills at {store}, {fmt_date(val_w['start'])} to {fmt_date(as_of)}, made {MIN_GAP_DAYS} to {MAX_GAP_DAYS} "
                 "days after the customer's first bill")
        c_cnt = book.add("return_bill_count", f"Return bills: {label}", "repeat_return_bill_count", dict(val_w))
        c_val = book.add("avg_return_bill_value", f"Average value of a return bill: {label}",
                         "repeat_avg_return_bill_value", dict(val_w))
        if (c_val["value"] is None or c_cnt["value"] < MIN_RETURN_BILLS or not c_new["value"]
                or c_own["value"] is None or c_fair["value"] is None):
            return None
        high, low = (c_own, c_fair) if role_model else (c_fair, c_own)
        rp = {"fair_rate": high["value"], "own_rate": low["value"], "new_customers_per_week": c_new["value"],
              "avg_return_bill_value": c_val["value"]}
        c_r = book.add("rupees_at_stake", "Rupees at stake a week", "repeat_rupees_at_stake", rp)
        arithmetic = {
            "formula": formula,
            "worked": f"({high['display']} − {low['display']}) × {c_new['display']} new customers a week × "
                      f"{c_val['display']} = {c_r['display']} a week",
            "input_check_ids": [high["id"], low["id"], c_new["id"], c_val["id"]],
        }
        recent = (f"Among customers first billed since {c_from['display']}, the ones most like today's new customers, "
                  f"it is {c_own['display']} against {c_fair['display']}; rupees at stake use these two figures.")
        return {"rupees": c_r["value"], "arithmetic": arithmetic, "recent": recent}

    def call_list(self, book: CheckBook, group: dict, slug: str, who: str, cap: int):
        """Customers to call today: first billed 30 to N days ago and not back since. None if nobody to call."""
        as_of = self.as_of
        ex = {"exclude_customer_ids": list(self.core.placeholders)}
        first_to = add_days(as_of, -MIN_GAP_DAYS)
        chosen = None
        for back in CALL_WINDOWS:
            p = {**group, "first_from": add_days(as_of, -back), "first_to": first_to, "no_bill_through": as_of, **ex}
            n = self.m.compute("repeat_call_list", p)
            chosen = (back, p, n)
            if n <= cap:
                break
        back, p, n = chosen
        if n <= 0 or n > cap:
            return None
        span = f"first bill {fmt_date(p['first_from'])} to {fmt_date(first_to)}, no other bill up to {fmt_date(as_of)}"
        c_n = book.add(f"call_list{slug}", f"Customers to call, {who}: {span}", "repeat_call_list", dict(p))
        c_s = book.add(f"call_list_sherwani{slug}", f"Of those, customers whose first bill had a sherwani ({who})",
                       "repeat_call_list", {**p, "category": "Sherwani"})
        return {"n": c_n, "sherwani": c_s, "back": back}

    def call_dates(self, book: CheckBook, back: int) -> tuple[dict, dict]:
        c_from = book.add("call_from", f"{back} days before {fmt_date(self.as_of)}", "repeat_date_offset",
                          {"date": self.as_of, "days": -back})
        c_to = book.add("call_to", f"{MIN_GAP_DAYS} days before {fmt_date(self.as_of)}", "repeat_date_offset",
                        {"date": self.as_of, "days": -MIN_GAP_DAYS})
        return c_from, c_to

    def follow_up(self, book: CheckBook, label: str, subject: dict, peer: dict, peer_label: str):
        """The 7-day-measurable figure, and the same figure for the benchmark. None when it cannot be measured,
        or when the last 13 weeks do not show the gap (then there is nothing to re-measure, and no alert)."""
        as_of = self.as_of
        w = {"start": add_days(as_of, -(FOLLOW_DAYS - 1)), "end": as_of, "min_gap_days": MIN_GAP_DAYS,
             "max_gap_days": MAX_GAP_DAYS, "exclude_customer_ids": list(self.core.placeholders)}
        span = f"{fmt_date(w['start'])} to {fmt_date(as_of)}"
        c_own = book.add("weekly_returns", f"{label}, {span}", "repeat_weekly_returns_per_100", {**subject, **w})
        c_peer = book.add("weekly_returns_benchmark", f"The same figure for {peer_label}, {span}",
                          "repeat_weekly_returns_per_100", {**peer, **w})
        if c_own["value"] is None or c_peer["value"] is None or c_own["value"] >= c_peer["value"]:
            return None
        return {"metric_label": label, "kind": "repeat_weekly_returns_per_100", "params": {**subject, **w},
                "baseline_value": c_own["value"], "target_value": c_peer["value"], "higher_is_better": True}

    def finish(self, *, alert_id, store, cause_code, headline, cause, action, money, basis, people, book, follow_up,
               definition):
        if money is None or money["rupees"] <= 0:
            self.notes.append(f"{alert_id}: not sent, no rupees at stake could be worked out")
            return
        if not has_who_what_when(action):
            self.notes.append(f"{alert_id}: not sent, no action naming who, what and when could be built")
            return
        if follow_up is None:
            self.notes.append(f"{alert_id}: not sent, the last {FOLLOW_DAYS // 7} weeks do not show the gap, so there is nothing to re-measure")
            return
        stray = numbers_not_in_checks([headline, cause, action["text"], money["arithmetic"]["worked"]], book.items)
        if stray or not book.usable():
            self.notes.append(f"{alert_id}: not sent, figures without a check: {stray}")
            return
        self.alerts.append({
            "alert_id": alert_id,
            "rank": 0,
            "scope": "store",
            "store_ids": [store],
            "city": self.store_rows[store]["city"],
            "lever": LEVER,
            "cause_code": cause_code,
            "headline": headline,
            "cause": cause,
            "action": action,
            "rupees_at_stake_weekly": money["rupees"],
            "arithmetic": money["arithmetic"],
            "benchmark_basis": basis,
            "salesperson_ids": sorted(people),
            "checks": book.items,
            "follow_up": follow_up,
            "definition": definition,
        })

    # ---------------------------------------------------------------- detection
    def _run(self):
        m = self.m
        self.role_models: dict[str, list[tuple[str, dict]]] = {}
        self.low: dict[str, list[tuple[str, dict]]] = {}
        for store in self.established:
            sellers = self.sellers.get(store, [])
            highs = []
            for sp in sellers:
                st = self.person(store, sp, [x for x in sellers if x != sp])
                if self.is_high(st):
                    highs.append((sp, st))
            highs.sort(key=lambda t: (-t[1]["z"], t[0]))
            self.role_models[store] = highs
            # Being behind an exceptional colleague is not a problem: role models are left out of the yardstick.
            top = {sp for sp, _ in highs}
            lows = []
            for sp in sellers:
                if sp in top:
                    continue
                st = self.person(store, sp, [x for x in sellers if x != sp and x not in top])
                if self.is_low(st):
                    lows.append((sp, st))
            self.low[store] = lows

        for store in self.established:
            low_ids = set()
            for sp, st in self.low[store]:
                if not self.active(sp):
                    self.notes.append(f"{store}:{LEVER}:customers_not_returning:{sp}: not sent, {self.name(sp)} is no longer on the roster")
                    continue
                low_ids.add(sp)
                self.low_alert(store, sp, st)
            for sp, st in self.role_models[store]:
                if not self.active(sp):
                    self.notes.append(f"{store}:{LEVER}:role_model:{sp}: not sent, {self.name(sp)} is no longer on the roster")
                    continue
                self.role_model_alert(store, sp, st, skip=low_ids)
            self.store_alert(store)
        self.alerts.sort(key=lambda a: a["alert_id"])
        self.cards.sort(key=lambda c: (c["store_id"], c["salesperson_id"]))

    def coach_for(self, store: str, sp: str) -> tuple[str, dict] | None:
        """The named peer: the store's role model, else the active colleague this person is furthest behind."""
        best = None
        models = [x for x, _ in self.role_models[store] if x != sp and self.active(x)]
        pool = models or [x for x in self.sellers.get(store, []) if x != sp and self.active(x)]
        for x in pool:
            pair = self.person(store, sp, [x])
            if pair is None or self.m.compute("repeat_customers", {"store_ids": [store], "salesperson_ids": [x], **self.coh}) < MIN_CUSTOMERS:
                continue
            if not self.is_low(pair):
                continue
            if best is None or (pair["z"], x) < (best[1]["z"], best[0]):
                best = (x, pair)
        return best

    def card(self, store: str, sp: str, coach: tuple[str, dict]) -> dict | None:
        """One card: own return rate, the named peer over the same months, the calls to make today."""
        peer, pair = coach
        m, name, peer_name = self.m, self.name(sp), self.name(peer)
        book = CheckBook(m, f"card:{store}:{sp}:{LEVER}")
        c = self.comparison_checks(book, pair, name, peer_name, "behind")
        group = {"store_ids": [store], "salesperson_ids": [sp]}
        calls = self.call_list(book, group, "", name, MAX_CALLS)
        if calls is None:
            return None
        c_from, c_to = self.call_dates(book, calls["back"])
        money = self.money_checks(book, store, group, name, pair, name, peer_name, FORMULA)
        me, them = first_name(name), first_name(peer_name)
        behaviour = (f"{me}, {c['rate']['display']} of the customers you first billed came back and billed again. "
                     f"For {peer_name}, same store, same months, it was {c['fair']['display']}.")
        action = (f"Today, call the {calls['n']['display']} customers you first billed between {c_from['display']} and "
                  f"{c_to['display']} who have not been back, and ask {them} to sit in on your first five calls.")
        text = f"{behaviour} {action}"
        if numbers_not_in_checks([text], book.items) or not book.usable():
            return None
        return {
            "store_id": store, "salesperson_id": sp, "salesperson_name": name, "lever": LEVER,
            "behaviour": behaviour, "peer": {"salesperson_id": peer, "name": peer_name}, "action": action, "text": text,
            "checks": book.items, "priority": money["rupees"] if money else 0,
            "definition": self.definition(name, peer_name),
        }

    def low_alert(self, store: str, sp: str, st: dict):
        m, name = self.m, self.name(sp)
        alert_id = f"{store}:{LEVER}:customers_not_returning:{sp}"
        book = CheckBook(m, alert_id)
        versus = f"the other salespeople at {store}"
        c = self.comparison_checks(book, st, name, versus, "behind")
        group = {"store_ids": [store], "salesperson_ids": [sp]}
        money = self.money_checks(book, store, group, name, st, name, versus, FORMULA)
        headline = (f"{c['rate']['display']} of the {c['n']['display']} customers first billed by {name} at {store} came "
                    f"back and billed again, against {c['fair']['display']} for colleagues' customers first billed in the same months.")
        cause = (f"{name} is behind colleagues in {c['qs']['display']} of the {c['qc']['display']} first-bill quarters "
                 f"compared (z {c['z']['display']}), so this is a pattern and not one slow season or a late joining date. "
                 f"The data does not show what is said at the billing counter.")
        if money:
            cause += " " + money["recent"]
        coach = self.coach_for(store, sp)
        people = [sp]
        calls = self.call_list(book, group, "", name, MAX_CALLS)
        action = None
        if calls:
            c_from, c_to = self.call_dates(book, calls["back"])
            text = (f"Today, {name} calls the {calls['n']['display']} customers first billed between {c_from['display']} "
                    f"and {c_to['display']} who have not been back")
            if 1 < calls["sherwani"]["value"] < calls["n"]["value"]:
                text += f", starting with the {calls['sherwani']['display']} who bought a sherwani"
            who = name
            if coach:
                peer, pair = coach
                people.append(peer)
                c_peer = book.add("peer_rate", f"Return rate of {self.name(peer)}'s customers, same first-bill months as {name}",
                                  "repeat_fair_rate", dict(pair["params"]))
                cause += (f" {self.name(peer)}'s customers, first billed at {store} in the same months, came back at "
                          f"{c_peer['display']}.")
                text += f"; {self.name(peer)} sits in on the first five calls"
                who = f"{name}, with {self.name(peer)}"
            action = {"who": who, "what": f"Call the {calls['n']['display']} first-time customers who have not been back",
                      "when": "Today", "text": text + "."}
        peers = st["params"]["peer_salesperson_ids"]
        fu = self.follow_up(book, follow_label(name), group, {"store_ids": [store], "salesperson_ids": peers}, versus)
        self.finish(alert_id=alert_id, store=store, cause_code="customers_not_returning", headline=headline, cause=cause,
                    action=action, money=money, basis=f"Same store: the other salespeople at {store}, same first-bill months",
                    people=people, book=book, follow_up=fu, definition=self.definition(name, versus))
        if coach:
            card = self.card(store, sp, coach)
            if card:
                self.cards.append(card)

    def role_model_alert(self, store: str, sp: str, st: dict, skip: set):
        m, name = self.m, self.name(sp)
        alert_id = f"{store}:{LEVER}:role_model:{sp}"
        book = CheckBook(m, alert_id)
        versus = f"the other salespeople at {store}"
        c = self.comparison_checks(book, st, name, versus, "ahead")
        # Colleagues with something to learn: active, enough customers, clearly behind the role model over the same months.
        learners = []
        for x in self.sellers.get(store, []):
            if x == sp or not self.active(x):
                continue
            pair = self.person(store, x, [sp])
            if self.is_low(pair):
                learners.append((pair["rate"] / pair["fair"], x, pair))
        learners.sort(key=lambda t: (t[0], t[1]))
        for _, x, pair in learners:
            if x in skip:
                continue  # already has a card from their own alert
            card = self.card(store, x, (sp, pair))
            if card:
                self.cards.append(card)
        coached, lists = [], []
        for _, x, _pair in learners:
            calls = self.call_list(book, {"store_ids": [store], "salesperson_ids": [x]}, f":{x}", self.name(x), MAX_CALLS)
            if calls and (not lists or calls["back"] == lists[0]["back"]):
                coached.append(x)
                lists.append(calls)
            if len(coached) == COACHED:
                break
        if not coached:
            self.notes.append(f"{alert_id}: not sent, no colleague on the roster is clearly behind {name} over the same "
                              "months with customers to call today, so there is nobody to coach")
            return
        action = money = fu = None
        headline = (f"{c['rate']['display']} of the {c['n']['display']} customers first billed by {name} at {store} came back "
                    f"and billed again, against {c['fair']['display']} for colleagues' customers first billed in the same months.")
        cause = (f"{name} is ahead of colleagues in {c['qs']['display']} of the {c['qc']['display']} first-bill quarters "
                 f"compared (z {c['z']['display']}), so it is not an early joining date or one good season. "
                 f"What {name} does to bring customers back is not yet shared on the floor.")
        if coached:
            names = [self.name(x) for x in coached]
            c_from, c_to = self.call_dates(book, lists[0]["back"])
            counts = join_names([l["n"]["display"] for l in lists])
            each = "each call their" if len(coached) > 1 else "calls the"
            text = (f"Today, {join_names(names)} {each} customers first billed between {c_from['display']} and "
                    f"{c_to['display']} who have not been back ({counts} customers), and {name} sits in on the first five "
                    f"calls{' of each' if len(coached) > 1 else ''}.")
            action = {"who": f"{join_names(names)}, with {name}",
                      "what": "Call their first-time customers who have not been back, with the role model listening in",
                      "when": "Today", "text": text}
            group = {"store_ids": [store], "salesperson_ids": sorted(coached)}
            money = self.money_checks(book, store, group, join_names(names), st, name, versus, FORMULA_ROLE,
                                      role_model=True)
            if money:
                cause += " " + money["recent"]
            fu = self.follow_up(book, follow_label(join_names(names)), group,
                                {"store_ids": [store], "salesperson_ids": [sp]}, name)
        self.finish(alert_id=alert_id, store=store, cause_code="role_model", headline=headline, cause=cause, action=action,
                    money=money, basis=f"Same store: the other salespeople at {store}, same first-bill months",
                    people=[sp] + coached, book=book, follow_up=fu, definition=self.definition(name, versus))

    def store_peers(self, store: str) -> tuple[list[str], str]:
        row = self.store_rows[store]
        city = [s for s in self.established if s != store and self.store_rows[s]["city"] == row["city"]]
        if city:
            return city, f"the other {row['city']} stores"
        state = [s for s in self.established if s != store and self.store_rows[s]["state"] == row["state"]]
        return state, f"the other {row['state']} stores"

    def store_alert(self, store: str):
        """A store against the other stores of its city, counting only customers first billed by salespeople
        who are still on its roster: the team that can act today is not judged on the record of someone who left."""
        m = self.m
        peers, versus = self.store_peers(store)
        team = [x for x in self.sellers.get(store, []) if self.active(x)]
        if not peers or not team:
            return
        group = {"store_ids": [store], "salesperson_ids": team}
        st = self.stat(group, {"peer_store_ids": sorted(peers)})
        if not self.is_low(st, Z_STORE, STORE_LOW_RATIO, MIN_STORE_CUSTOMERS):
            return
        alert_id = f"{store}:{LEVER}:store_customers_not_returning"
        book = CheckBook(m, alert_id)
        who = f"the salespeople still on the roster at {store}"
        c = self.comparison_checks(book, st, who, versus, "behind")
        money = self.money_checks(book, store, {"store_ids": [store]}, store, st, who, versus, FORMULA)
        headline = (f"{c['rate']['display']} of the {c['n']['display']} customers first billed at {store} by the salespeople "
                    f"still on its roster came back and billed again, against {c['fair']['display']} at {versus} for "
                    "customers first billed in the same months.")
        cause = (f"{store} is behind {versus} in {c['qs']['display']} of the {c['qc']['display']} first-bill quarters "
                 f"compared (z {c['z']['display']}), so this is a pattern and not one slow season. ")
        flagged = [self.name(sp) for sp, _ in self.low[store] if self.active(sp)]
        cause += (f"Part of it sits with {join_names(flagged)}, reported separately." if flagged else
                  f"No single salesperson at {store} is far enough from colleagues to explain it.")
        if money:
            cause += " " + money["recent"]
        action = None
        calls = self.call_list(book, group, "", who, MAX_CALLS * len(team))
        if calls:
            c_from, c_to = self.call_dates(book, calls["back"])
            text = (f"Today, the store manager at {store} has each salesperson on the roster call their own customers first "
                    f"billed between {c_from['display']} and {c_to['display']} who have not been back, "
                    f"{calls['n']['display']} customers in all")
            if 1 < calls["sherwani"]["value"] < calls["n"]["value"]:
                text += f", starting with the {calls['sherwani']['display']} who bought a sherwani"
            action = {"who": f"Store manager at {store} and every salesperson on the roster",
                      "what": f"Each calls their own first-time customers who have not been back, {calls['n']['display']} in all",
                      "when": "Today", "text": text + "."}
        fu = self.follow_up(book, follow_label(who), group, {"store_ids": sorted(peers)}, versus)
        self.finish(alert_id=alert_id, store=store, cause_code="store_customers_not_returning", headline=headline,
                    cause=cause, action=action, money=money, basis=f"{versus[0].upper()}{versus[1:]}, same first-bill months",
                    people=[], book=book, follow_up=fu, definition=self.definition(who, versus))


def _lever(m: Metrics) -> Repeat:
    r = getattr(m, "_repeat_lever", None)
    if r is None:
        r = Repeat(m)
        m._repeat_lever = r
    return r


def detect(m: Metrics) -> tuple[list[dict], list[str]]:
    r = _lever(m)
    return list(r.alerts), list(r.notes)


def card_candidates(m: Metrics) -> list[dict]:
    return list(_lever(m).cards)


def data_issues(m: Metrics, windows: dict) -> list[dict]:
    core = core_of(m)
    out = []
    for cid in core.placeholders:
        rows = core.all_bills[core.all_bills["customer_id"] == cid]
        issue_id = f"ALL:placeholder_customer_id:{cid}"
        book = CheckBook(m, issue_id)
        n = book.add("bills", f"Bills carrying customer id {cid}", "repeat_placeholder_bills", {"customer_id": cid})
        s = book.add("stores", f"Different stores those bills were made at", "repeat_placeholder_stores", {"customer_id": cid})
        first, last = str(rows["bill_date"].min()), str(rows["bill_date"].max())
        out.append({
            "issue_id": issue_id,
            "store_id": "ALL",
            "kind": "placeholder_customer_id",
            "title": f"{cid} is a placeholder mobile number, not a customer",
            "detail": (f"Customer id {cid} is on {n['display']} bills at {s['display']} different stores between "
                       f"{fmt_date(first)} and {fmt_date(last)}. One person cannot bill that often or in that many "
                       f"stores (the rule: {PLACEHOLDER_MIN_BILLS} or more bills, or {PLACEHOLDER_MIN_STORES} or more "
                       "stores), so this is a number keyed in when the customer gave none."),
            "first_date": first,
            "last_date": last,
            "days_affected": int(rows["bill_date"].nunique()),
            "handling": ("Those bills still count as bills for conversion and for basket size, but they cannot be followed "
                         "for repeat: the id is left out of every return-rate figure, and no alert is raised from it."),
            "checks": book.items,
        })
    return out
