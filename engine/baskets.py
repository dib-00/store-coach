"""Lever 2, "bigger baskets" (items per bill). Plugs into engine/run.py.

Interface (the same for every lever module):
    detect(m)            -> (alert candidates, notes)   candidates are full Alert dicts, rank 0
    card_candidates(m)   -> list of card candidates     see engine/cards.py
    data_issues(m, windows) -> list of DataIssue dicts
Check kinds this lever adds are registered in metrics.EXTRA_KINDS and checks.EXTRA_DISPLAY.

Four things are tested (docs/METHOD-baskets.md explains every threshold):
    pair_attach_drop    a store stops selling the obvious add-on with the main item
    high_discount       salespeople discounting far more often than same-store colleagues
    low_items_per_bill  salespeople with fewer items per bill than same-store colleagues
    category_avoided    a salesperson who hardly sells a category the colleagues do sell
The recipe for every check kind is in docs/CHECKS-baskets.md.
"""
from __future__ import annotations

import math

import pandas as pd

from . import checks, metrics
from .checks import CheckBook, conv_tenths, fmt_inr, fmt_int_in, fmt_num, fmt_pct, numbers_not_in_checks
from .detect import is_new_store, join_names
from .metrics import Metrics, add_days, d, rnd, rnd_div, z_score
from .rank import has_who_what_when
from .workday import action_day, corrected, off_tomorrow

LEVER = "bigger_baskets"

CUR_DAYS = 90  # the window every figure of this lever is measured on
PRIOR_DAYS = 275  # the nine months before it (same store), the fair benchmark for a pair
YEAR_DAYS = 365  # shift to "the same days a year earlier"; also the category window
ACTIVE_DAYS = 7  # on the roster within the last 7 days = still at the store
RECENT_BILL_DAYS = 28  # used instead when there is no roster up to as-of

# About 115 salespeople are compared with their colleagues in each family of tests, every
# run. One-sided 5% shared over 115 comparisons is z = 3.3; two families run side by side
# (items per bill, discounts), so 3.5.
Z_PERSON = 3.5
# 8 categories x about 125 salespeople = 1,000 comparisons: z = 3.9 for a shared 5%.
Z_CATEGORY = 4.0
# 4 pairs x 19 stores = 76 comparisons: z = 3.2. The same fall must also show against the
# same days a year earlier (z <= -2.0), so a seasonal swing cannot pass.
Z_ATTACH = 3.2
Z_ATTACH_YEAR = 2.0
Z_DRIVER = 2.0  # one test per salesperson inside a store already flagged

MIN_BILLS_PERSON = 30  # bills in the window before a salesperson is compared
MIN_BILLS_PEERS = 60  # bills of the colleagues they are compared with
IPB_MIN_GAP = 0.15  # at least 15% fewer items per bill than colleagues
LONG_DAYS = 180  # small-store fallback: the items-per-bill group test uses the last 180 days
DISC_MIN_GAP = 0.02  # discount rate at least 2 points of MRP above colleagues
ATTACH_MIN_MAIN = 100  # main-item bills in the current window and in each benchmark
ATTACH_MIN_REL_DROP = 0.20  # attach rate at least 20% below the benchmark
DRIVER_MIN_MAIN = 30  # main-item bills before a salesperson is named
CAT_MIN_BILLS = 100  # bills in the 365 days before a salesperson is tested on a category
CAT_MIN_EXPECTED = 10  # bills of the category they would have at the colleagues' share
CAT_MAX_RATIO = 0.5  # own share at most half the colleagues' share (year and last 90 days)

PAIRS = [("Sherwani", "Safa"), ("Sherwani", "Mojari"), ("Sherwani", "Mala"), ("Kurta Set", "Jacket")]
CATEGORIES = ["Sherwani", "Indo-Western", "Kurta Set", "Jacket", "Mojari", "Safa", "Mala", "Stole"]
MAIN_WORD = {"Sherwani": "sherwani", "Kurta Set": "kurta-set", "Indo-Western": "Indo-Western"}
ADDON_WORD = {"Safa": "a safa", "Mojari": "mojari", "Mala": "a mala", "Jacket": "a jacket", "Stole": "a stole"}
CAT_WORD = {"Sherwani": "sherwanis", "Indo-Western": "Indo-Western sets", "Kurta Set": "kurta sets", "Jacket": "jackets",
            "Mojari": "mojari", "Safa": "safas", "Mala": "malas", "Stole": "stoles"}


# ------------------------------------------------------------------ bill table
def _frame(m: Metrics) -> pd.DataFrame:
    """One row per bill: product-line totals (carry bags left out) and one flag per category."""
    f = getattr(m, "_basket_frame", None)
    if f is not None:
        return f
    lines = m.data.lines
    prod = lines[lines["is_packaging"].astype(str) != "1"].copy()
    prod["mrp_value"] = prod["qty_n"] * prod["mrp_n"]
    prod["disc"] = prod["price_n"] < prod["mrp_n"]
    prod["above"] = prod["price_n"] > prod["mrp_n"]
    g = prod.groupby("bill_id", sort=True)
    bill = pd.DataFrame({
        "items": g["qty_n"].sum(), "value": g["line_value"].sum(), "mrp_value": g["mrp_value"].sum(),
        "disc": g["disc"].max(), "above": g["above"].sum(),
    })
    for cat in CATEGORIES:
        val = prod[prod["category"] == cat].groupby("bill_id")["line_value"].sum()
        bill["has:" + cat] = bill.index.isin(val.index)
        bill["val:" + cat] = val.reindex(bill.index).fillna(0.0)
    b = m.data.bills[["bill_id", "bill_date", "store_id", "salesperson_id"]].set_index("bill_id")
    f = b.join(bill, how="inner").sort_index(kind="mergesort")
    m._basket_frame = f
    m._basket_store = {s: x for s, x in f.groupby("store_id", sort=True)}
    return f


def _sel(m: Metrics, p: dict, sp_key: str = "salesperson_ids", start: str = "start", end: str = "end") -> pd.DataFrame:
    """Bills of the given stores in the window, optionally only those billed by the given salespeople."""
    _frame(m)
    parts = [m._basket_store[s] for s in sorted(p["store_ids"]) if s in m._basket_store]
    if not parts:
        return _frame(m).iloc[0:0]
    f = parts[0] if len(parts) == 1 else pd.concat(parts)
    mask = (f["bill_date"] >= p[start]) & (f["bill_date"] <= p[end])
    ids = p.get(sp_key)
    if ids is not None:
        mask &= f["salesperson_id"].isin(ids)
    return f[mask]


def _days(p: dict) -> int:
    return (d(p["end"]) - d(p["start"])).days + 1


def _ratio(num, den, n):
    return rnd_div(float(num), float(den), n) if den else None


def _welch(a: pd.Series, b: pd.Series):
    """Welch z of mean(a) - mean(b), sample variances. Negative = a is lower."""
    if len(a) < 2 or len(b) < 2:
        return None
    se2 = float(a.var(ddof=1)) / len(a) + float(b.var(ddof=1)) / len(b)
    if se2 <= 0:
        return None
    return (float(a.mean()) - float(b.mean())) / math.sqrt(se2)


def _z2(k1, n1, k0, n0):
    z = z_score(float(k1), float(n1), float(k0), float(n0))
    return rnd(z, 2) if z is not None else None


def _peers(m, p):
    return _sel(m, p, "peer_salesperson_ids")


def _attach_parts(f: pd.DataFrame, p: dict):
    main = f[f["has:" + p["main_category"]]]
    return int(main["has:" + p["addon_category"]].sum()), int(len(main))


# ------------------------------------------------------------------ check kinds
def k_window_days(m, p):
    return _days(p)


def k_bills(m, p):
    return int(len(_sel(m, p)))


def k_bills_per_week(m, p):
    return rnd_div(len(_sel(m, p)) * 7, _days(p), 1)


def k_items_per_bill(m, p):
    f = _sel(m, p)
    return _ratio(f["items"].sum(), len(f), 2)


def k_items_per_bill_z(m, p):
    z = _welch(_sel(m, p)["items"], _peers(m, p)["items"])
    return rnd(z, 2) if z is not None else None


def k_avg_item_value(m, p):
    f = _sel(m, p)
    return _ratio(f["value"].sum(), f["items"].sum(), 2)


def k_discount_rate(m, p):
    f = _sel(m, p)
    mrp = float(f["mrp_value"].sum())
    return rnd_div(mrp - float(f["value"].sum()), mrp, 4) if mrp > 0 else None


def k_discounted_bill_share(m, p):
    f = _sel(m, p)
    return _ratio(f["disc"].sum(), len(f), 4)


def k_discounted_bill_share_z(m, p):
    a, b = _sel(m, p), _peers(m, p)
    return _z2(a["disc"].sum(), len(a), b["disc"].sum(), len(b))


def k_mrp_sales_per_week(m, p):
    return rnd_div(float(_sel(m, p)["mrp_value"].sum()) * 7, _days(p), 0)


def k_category_bills(m, p):
    return int(_sel(m, p)["has:" + p["category"]].sum())


def k_category_bills_per_week(m, p):
    return rnd_div(k_category_bills(m, p) * 7, _days(p), 1)


def k_category_bill_share(m, p):
    f = _sel(m, p)
    return _ratio(f["has:" + p["category"]].sum(), len(f), 4)


def k_category_bill_share_z(m, p):
    a, b = _sel(m, p), _peers(m, p)
    c = "has:" + p["category"]
    return _z2(a[c].sum(), len(a), b[c].sum(), len(b))


def k_avg_bill_value_split(m, p):
    f = _sel(m, p)
    f = f[f["has:" + p["category"]] == bool(p["with_category"])]
    return _ratio(f["value"].sum(), len(f), 2)


def k_attach_rate(m, p):
    k, n = _attach_parts(_sel(m, p), p)
    return _ratio(k, n, 4)


def k_attach_rate_z(m, p):
    k1, n1 = _attach_parts(_sel(m, p), p)
    k0, n0 = _attach_parts(_sel(m, p, start="base_start", end="base_end"), p)
    return _z2(k1, n1, k0, n0)


def k_avg_addon_value(m, p):
    f = _sel(m, p)
    f = f[f["has:" + p["main_category"]] & f["has:" + p["addon_category"]]]
    return _ratio(f["val:" + p["addon_category"]].sum(), len(f), 2)


def k_lines_above_mrp(m, p):
    return int(_sel(m, p)["above"].sum())


_PCT = ("discount_rate", "discounted_bill_share", "category_bill_share", "attach_rate")
_INR = ("avg_item_value", "mrp_sales_per_week", "avg_bill_value_split", "avg_addon_value",
        "attach_rupees_weekly", "discount_given_away_weekly", "items_rupees_weekly", "category_rupees_weekly")
_COUNT = ("window_days", "product_bills", "category_bills", "lines_above_mrp")
_ONE = ("product_bills_per_week", "category_bills_per_week")
_TWO = ("items_per_bill", "items_per_bill_z", "discounted_bill_share_z", "category_bill_share_z", "attach_rate_z")

metrics.EXTRA_KINDS.update({
    "window_days": k_window_days, "product_bills": k_bills, "product_bills_per_week": k_bills_per_week,
    "items_per_bill": k_items_per_bill, "items_per_bill_z": k_items_per_bill_z, "avg_item_value": k_avg_item_value,
    "discount_rate": k_discount_rate, "discounted_bill_share": k_discounted_bill_share,
    "discounted_bill_share_z": k_discounted_bill_share_z, "mrp_sales_per_week": k_mrp_sales_per_week,
    "category_bills": k_category_bills, "category_bills_per_week": k_category_bills_per_week,
    "category_bill_share": k_category_bill_share, "category_bill_share_z": k_category_bill_share_z,
    "avg_bill_value_split": k_avg_bill_value_split, "attach_rate": k_attach_rate, "attach_rate_z": k_attach_rate_z,
    "avg_addon_value": k_avg_addon_value, "lines_above_mrp": k_lines_above_mrp,
})
for _k in _PCT:
    checks.EXTRA_DISPLAY[_k] = fmt_pct
for _k in _INR:
    checks.EXTRA_DISPLAY[_k] = fmt_inr
for _k in _COUNT:
    checks.EXTRA_DISPLAY[_k] = lambda v: fmt_int_in(int(v))
for _k in _ONE:
    checks.EXTRA_DISPLAY[_k] = lambda v: fmt_num(v, 1)
for _k in _TWO:
    checks.EXTRA_DISPLAY[_k] = lambda v: fmt_num(v, 2)


# ------------------------------------------------------------------ rupees, from the figures as displayed
def _to_100(raw: float) -> int:
    return int(rnd(raw / 100)) * 100


def _tenths(v: float) -> int:
    return int(rnd(v * 10))


def attach_rupees(fair: float, cur: float, bills_week: float, addon_value: float) -> int:
    """(fair % - current %), 1 decimal x bills a week, 1 decimal x whole rupees; nearest Rs 100."""
    return _to_100((conv_tenths(fair) - conv_tenths(cur)) * _tenths(bills_week) * int(rnd(addon_value)) / 10000)


def discount_rupees(own: float, norm: float, mrp_week: float) -> int:
    """(own % - norm %), 1 decimal x weekly sales at MRP, whole rupees; nearest Rs 100."""
    return _to_100((conv_tenths(own) - conv_tenths(norm)) * int(rnd(mrp_week)) / 1000)


def items_rupees(peer: float, own: float, bills_week: float, item_value: float) -> int:
    """(peer - own items per bill), 2 decimals x bills a week, 1 decimal x whole rupees; nearest Rs 100."""
    gap = int(rnd(peer * 100)) - int(rnd(own * 100))
    return _to_100(gap * _tenths(bills_week) * int(rnd(item_value)) / 1000)


def category_rupees(peer: float, own: float, bills_week: float, with_value: float, without_value: float) -> int:
    """(peer % - own %), 1 decimal x bills a week, 1 decimal x (bill with - bill without), whole rupees."""
    step = int(rnd(with_value)) - int(rnd(without_value))
    return _to_100((conv_tenths(peer) - conv_tenths(own)) * _tenths(bills_week) * step / 10000)


# ------------------------------------------------------------------ detector
def _first(name: str) -> str:
    return name.split()[0]


def _verb(n: int, plural: str, singular: str) -> str:
    return plural if n > 1 else singular


class Baskets:
    def __init__(self, m: Metrics):
        self.m = m
        self.as_of = m.as_of
        self.cur = {"start": add_days(self.as_of, -(CUR_DAYS - 1)), "end": self.as_of}
        self.prior = {"start": add_days(self.cur["start"], -PRIOR_DAYS), "end": add_days(self.cur["start"], -1)}
        self.year_ago = {"start": add_days(self.cur["start"], -YEAR_DAYS), "end": add_days(self.as_of, -YEAR_DAYS)}
        self.year = {"start": add_days(self.as_of, -(YEAR_DAYS - 1)), "end": self.as_of}
        self.rows = {r["store_id"]: r for r in m.data.stores.to_dict("records")}
        self.established = sorted(s for s, r in self.rows.items() if not is_new_store(r["opened_on"], self.as_of))
        self.alerts: list[dict] = []
        self.cards: list[dict] = []
        self.notes: list[str] = []
        self.subjects: set = set()  # people this lever is correcting; never named as somebody's model
        _frame(m)

    def shadow_day(self, book: CheckBook, people: list[str]):
        """("Today" or "On Tuesday", when) for an action that needs these people on the floor together."""
        return action_day(self.m, book, people)

    def correcting(self, people: list[str]):
        self.subjects.update(people)
        corrected(self.m).update(people)

    # ---------------------------------------------------------------- people
    def active(self, store: str) -> list[str]:
        """Salespeople of the store still there: on the roster in the last 7 days (or, with no
        roster up to as-of for the store, at least one bill at the store in the last 28 days)."""
        m = self.m
        since = add_days(self.as_of, -(ACTIVE_DAYS - 1))
        people = m.store_sps.get(store, [])
        on_roster = [p for p in people if (m.last_roster_date(p) or "") >= since]
        if on_roster or any(dt >= since for dt in m.present_count.get(store, {})):
            return on_roster
        recent = _sel(m, {"store_ids": [store], "start": add_days(self.as_of, -(RECENT_BILL_DAYS - 1)), "end": self.as_of})
        billed = set(recent["salesperson_id"])
        return [p for p in people if p in billed]

    def name(self, sp: str) -> str:
        return self.m.sp_name[sp]

    @staticmethod
    def yardstick(others: list[str], by: dict, stat, min_bills: int):
        """(colleagues used as the yardstick, the best colleague).

        The best colleague (highest `stat` among those with at least `min_bills` bills; ties go to
        the lower id) is the role model. With three or more colleagues the best one is left out of
        the yardstick, so that one star cannot make everybody else at the store look weak.
        """
        ranked = sorted((-stat(by[x]), x) for x in others if len(by[x]) >= min_bills)
        top = ranked[0][1] if ranked else None
        if top is not None and len(others) >= 3:
            return [x for x in others if x != top], top
        return list(others), top

    def days_check(self, book: CheckBook, w: dict, slug: str = "window_days"):
        return book.add(slug, "Days in the window", "window_days", dict(w))

    # ---------------------------------------------------------------- gates
    def finish(self, *, alert_id, store, cause_code, headline, cause, action, rupees, arithmetic, basis, people,
               book, follow_up, definition):
        if rupees is None or rupees <= 0:
            self.notes.append(f"{alert_id}: not sent, no rupees at stake could be worked out")
            return None
        if not has_who_what_when(action):
            self.notes.append(f"{alert_id}: not sent, no action naming who, what and when could be built")
            return None
        stray = numbers_not_in_checks([headline, cause, action["text"], arithmetic["worked"]], book.items)
        if stray or not book.usable():
            self.notes.append(f"{alert_id}: not sent, figures without a check: {stray}")
            return None
        alert = {
            "alert_id": alert_id, "rank": 0, "scope": "store", "store_ids": [store], "city": self.rows[store]["city"],
            "lever": LEVER, "cause_code": cause_code, "headline": headline, "cause": cause, "action": action,
            "rupees_at_stake_weekly": rupees, "arithmetic": arithmetic, "benchmark_basis": basis,
            "salesperson_ids": sorted(people), "checks": book.items, "follow_up": follow_up, "definition": definition,
        }
        self.alerts.append(alert)
        return alert

    def card(self, *, alert_id, store, sp, peer, behaviour, peer_line, action, book_items, priority, definition):
        if off_tomorrow(self.m, sp):
            self.notes.append(f"{store}:{sp}: no card today, the card says 'today' and that is the usual weekly off")
            return
        text = f"{behaviour} {peer_line} {action}"
        # the card carries its own copy of each figure, under its own id (ids are unique in the file)
        prefix = f"card:{store}:{sp}:{LEVER}"
        used = [{**c, "id": prefix + c["id"][len(alert_id):]} for c in book_items if c["value"] is not None]
        if numbers_not_in_checks([text], used):
            self.notes.append(f"{store}:{sp}: card not offered, figures without a check")
            return
        self.cards.append({
            "store_id": store, "salesperson_id": sp, "salesperson_name": self.name(sp), "lever": LEVER,
            "behaviour": behaviour, "peer": {"salesperson_id": peer, "name": self.name(peer)}, "action": action,
            "text": text, "checks": used, "priority": float(priority), "definition": definition,
        })

    # ------------------------------------------------- 1. the obvious pair
    def pair_attach(self, store: str, main: str, addon: str):
        m, cur, prior, ya = self.m, self.cur, self.prior, self.year_ago
        base = {"store_ids": [store], "main_category": main, "addon_category": addon}
        k1, n1 = _attach_parts(_sel(m, {**base, **cur}), base)
        k0, n0 = _attach_parts(_sel(m, {**base, **prior}), base)
        k2, n2 = _attach_parts(_sel(m, {**base, **ya}), base)
        if min(n1, n0, n2) < ATTACH_MIN_MAIN or not k0:
            return None
        z = z_score(k1, n1, k0, n0)
        zy = z_score(k1, n1, k2, n2)
        if z is None or zy is None or z > -Z_ATTACH or zy > -Z_ATTACH_YEAR:
            return None
        if (k1 / n1) / (k0 / n0) - 1 > -ATTACH_MIN_REL_DROP:
            return None

        alert_id = f"{store}:{LEVER}:pair_attach_drop:{main.lower().replace(' ', '_')}_{addon.lower()}"
        mw, aw = MAIN_WORD[main], ADDON_WORD[addon]
        book = CheckBook(m, alert_id)
        days = self.days_check(book, cur)
        c_cur = book.add("attach_current", f"Share of {mw} bills with {aw}, last {CUR_DAYS} days", "attach_rate", {**base, **cur})
        c_fair = book.add("attach_prior", f"Share of {mw} bills with {aw}, the {PRIOR_DAYS} days before", "attach_rate", {**base, **prior})
        c_year = book.add("attach_year_ago", f"Share of {mw} bills with {aw}, same days a year earlier", "attach_rate", {**base, **ya})
        book.add("main_bills_current", f"Bills with a {mw}, last {CUR_DAYS} days", "category_bills", {"store_ids": [store], "category": main, **cur})
        book.add("main_bills_prior", f"Bills with a {mw}, the {PRIOR_DAYS} days before", "category_bills", {"store_ids": [store], "category": main, **prior})
        book.add("main_bills_year_ago", f"Bills with a {mw}, same days a year earlier", "category_bills", {"store_ids": [store], "category": main, **ya})
        book.add("z_prior", "Two-proportion z, current against the nine months before", "attach_rate_z",
                 {**base, **cur, "base_start": prior["start"], "base_end": prior["end"]})
        book.add("z_year_ago", "Two-proportion z, current against the same days a year earlier", "attach_rate_z",
                 {**base, **cur, "base_start": ya["start"], "base_end": ya["end"]})
        c_week = book.add("main_bills_per_week", f"Bills with a {mw} a week, last {CUR_DAYS} days", "category_bills_per_week",
                          {"store_ids": [store], "category": main, **cur})
        c_val = book.add("avg_addon_value", f"Average value of the {addon.lower()} on a {mw} bill, last {CUR_DAYS} days",
                         "avg_addon_value", {**base, **cur})

        # who drives it: active salespeople whose own attach rate fell, against their own nine months before
        drivers, models = [], []
        for sp in self.active(store):
            one = {**base, "salesperson_ids": [sp]}
            a1, b1 = _attach_parts(_sel(m, {**one, **cur}), base)
            a0, b0 = _attach_parts(_sel(m, {**one, **prior}), base)
            if b1 < DRIVER_MIN_MAIN:
                continue
            zp = z_score(a1, b1, a0, b0) if b0 >= DRIVER_MIN_MAIN else None
            if zp is not None and zp <= -Z_DRIVER and a1 / b1 < k0 / n0:
                drivers.append((a1 / b1 - a0 / b0, sp))
            elif a1 / b1 >= k0 / n0 and sp not in self.subjects:
                models.append((-a1 / b1, -b1, sp))
        drivers = [sp for _, sp in sorted(drivers)][:3]
        model = sorted(models)[0][2] if models else None

        rupees = None
        if c_val["value"] is not None:
            rupees = attach_rupees(c_fair["value"], c_cur["value"], c_week["value"], c_val["value"])
        r = book.add("rupees_at_stake", "Rupees at stake a week", "attach_rupees_weekly", {
            "benchmark_check_id": c_fair["id"], "current_check_id": c_cur["id"],
            "bills_per_week_check_id": c_week["id"], "addon_value_check_id": c_val["id"]}, value=rupees or 0)

        action = None
        cause = (f"In the last {days['display']} days {c_cur['display']} of {mw} bills at {store} included {aw}, against "
                 f"{c_fair['display']} in the nine months before and {c_year['display']} in the same days a year earlier.")
        own = {}
        if drivers and model:
            bits = []
            for sp in drivers:
                one = {**base, "salesperson_ids": [sp]}
                now = book.add(f"attach_current:{sp}", f"{self.name(sp)}: share of {mw} bills with {aw}, last {CUR_DAYS} days",
                               "attach_rate", {**one, **cur})
                was = book.add(f"attach_prior:{sp}", f"{self.name(sp)}: share of {mw} bills with {aw}, the {PRIOR_DAYS} days before",
                               "attach_rate", {**one, **prior})
                book.add(f"z_prior:{sp}", f"{self.name(sp)}: two-proportion z against own nine months before", "attach_rate_z",
                         {**one, **cur, "base_start": prior["start"], "base_end": prior["end"]})
                book.add(f"main_bills:{sp}", f"{self.name(sp)}: bills with a {mw}, last {CUR_DAYS} days", "category_bills",
                         {"store_ids": [store], "category": main, "salesperson_ids": [sp], **cur})
                own[sp] = now
                bits.append(f"{self.name(sp)} fell from {was['display']} to {now['display']}")
            c_model = book.add(f"attach_current:{model}", f"{self.name(model)}: share of {mw} bills with {aw}, last {CUR_DAYS} days",
                               "attach_rate", {**base, "salesperson_ids": [model], **cur})
            cause += f" {join_names(bits)}; {self.name(model)} at the same store is at {c_model['display']}."
            who = join_names([self.name(sp) for sp in drivers])
            n = len(drivers)
            what = (f"{_verb(n, 'shadow', 'shadows')} {self.name(model)} for the first five {mw} trials and "
                    f"{_verb(n, 'bring', 'brings')} {aw} to the trial room each time")
            day = self.shadow_day(book, drivers + [model])
            if day:
                action = {"who": who, "what": what, "when": day[1], "text": f"{day[0]}, {who} {what}."}
        else:
            self.notes.append(f"{alert_id}: no salesperson still at the store drives the fall, so no action can name who")

        alert = self.finish(
            alert_id=alert_id, store=store, cause_code="pair_attach_drop",
            headline=f"{store}: {aw} now goes with {c_cur['display']} of {mw} bills, down from {c_fair['display']}",
            cause=cause, action=action, rupees=rupees,
            arithmetic={
                "formula": f"(fair attach rate − current attach rate) × {mw} bills a week × average value of the {addon.lower()} added",
                "worked": f"({c_fair['display']} − {c_cur['display']}) × {c_week['display']} {mw} bills a week × "
                          f"{c_val['display']} = {r['display']} a week",
                "input_check_ids": [c_fair["id"], c_cur["id"], c_week["id"], c_val["id"]],
            },
            basis=f"Same store, the nine months before; confirmed against the same {CUR_DAYS} days a year earlier",
            people=drivers + ([model] if model else []), book=book,
            follow_up={"metric_label": f"Share of {mw} bills with {aw} at {store}", "kind": "attach_rate",
                       "params": {**base, **cur}, "baseline_value": c_cur["value"], "target_value": c_fair["value"],
                       "higher_is_better": True},
            definition=(f"Attach rate = bills containing both a {main} line and a {addon} line ÷ bills containing a {main} line, "
                        f"at this store. Current = the {CUR_DAYS} days ending on the run date; fair = the same store's {PRIOR_DAYS} days before that; "
                        f"also checked against the same {CUR_DAYS} days one year (365 days) earlier."),
        )
        if alert:
            self.correcting(drivers)
            for sp in drivers:
                share = rupees / len(drivers)
                self.card(
                    alert_id=alert_id, store=store, sp=sp, peer=model,
                    behaviour=f"{_first(self.name(sp))}, {aw} went with {own[sp]['display']} of your {mw} bills in the last {days['display']} days.",
                    peer_line=f"{self.name(model)} at your store adds one to {c_model['display']}.",
                    action=f"Today, bring {aw} to the trial room with every {mw} trial, before the customer asks.",
                    book_items=[days, own[sp], c_model], priority=share,
                    definition=f"Share of your bills with a {main} line that also have a {addon} line, last {CUR_DAYS} days.",
                )
        return alert

    # ------------------------------------------------- 2 and 3. person against same-store colleagues
    def _pool(self, store: str, w: dict | None = None):
        act = self.active(store)
        f = _sel(self.m, {"store_ids": [store], **(w or self.cur), "salesperson_ids": act})
        return act, {sp: g for sp, g in f.groupby("salesperson_id", sort=True)}

    def high_discount(self, store: str):
        m, cur = self.m, self.cur
        if k_lines_above_mrp(m, {"store_ids": [store], **cur}):
            self.notes.append(f"{store}: discounts not judged, some lines are priced above MRP (see data issues)")
            return None
        act, by = self._pool(store)
        flagged = []
        for sp in act:
            g = by.get(sp)
            rest = [by[x] for x in act if x != sp and x in by]
            if g is None or len(g) < MIN_BILLS_PERSON or not rest:
                continue
            o = pd.concat(rest)
            if len(o) < MIN_BILLS_PEERS or not o["mrp_value"].sum():
                continue
            z = z_score(float(g["disc"].sum()), len(g), float(o["disc"].sum()), len(o))
            gap = (1 - g["value"].sum() / g["mrp_value"].sum()) - (1 - o["value"].sum() / o["mrp_value"].sum())
            if z is not None and z >= Z_PERSON and gap >= DISC_MIN_GAP:
                flagged.append(sp)
        peers = [x for x in act if x not in flagged]
        if not flagged or not peers:
            return None
        alert_id = f"{store}:{LEVER}:high_discount"
        book = CheckBook(m, alert_id)
        sid = {"store_ids": [store]}
        grp, oth = {**sid, "salesperson_ids": flagged, **cur}, {**sid, "salesperson_ids": peers, **cur}
        days = self.days_check(book, cur)
        c_own = book.add("discount_rate_named", "Discount rate of the named salespeople", "discount_rate", grp)
        c_norm = book.add("discount_rate_colleagues", "Discount rate of the other salespeople at the store", "discount_rate", oth)
        c_peer_share = book.add("discounted_share_colleagues", "Share of bills with a discount, the other salespeople",
                                "discounted_bill_share", oth)
        c_mrp = book.add("mrp_sales_per_week_named", "Sales at MRP a week, the named salespeople", "mrp_sales_per_week", grp)
        book.add("bills_named", "Bills of the named salespeople", "product_bills", grp)
        book.add("bills_colleagues", "Bills of the other salespeople", "product_bills", oth)
        bits, own = [], {}
        for sp in flagged:
            one = {**sid, "salesperson_ids": [sp], **cur}
            rate = book.add(f"discount_rate:{sp}", f"{self.name(sp)}: discount rate", "discount_rate", one)
            share = book.add(f"discounted_share:{sp}", f"{self.name(sp)}: share of bills with a discount", "discounted_bill_share", one)
            book.add(f"z:{sp}", f"{self.name(sp)}: two-proportion z of that share against every other salesperson at the store",
                     "discounted_bill_share_z", {**one, "peer_salesperson_ids": [x for x in act if x != sp]})
            book.add(f"bills:{sp}", f"{self.name(sp)}: bills", "product_bills", one)
            mrp = book.add(f"mrp_sales_per_week:{sp}", f"{self.name(sp)}: sales at MRP a week", "mrp_sales_per_week", one)
            own[sp] = (rate, share, mrp)
            bits.append(f"{self.name(sp)} gave a discount on {share['display']} of bills ({rate['display']} of MRP)")
        if not book.usable() or c_norm["value"] is None:
            return None
        rupees = discount_rupees(c_own["value"], c_norm["value"], c_mrp["value"])
        r = book.add("rupees_at_stake", "Rupees given away a week", "discount_given_away_weekly", {
            "own_check_id": c_own["id"], "norm_check_id": c_norm["id"], "mrp_sales_check_id": c_mrp["id"]}, value=rupees)
        who = join_names([self.name(sp) for sp in flagged])
        n = len(flagged)
        what = (f"{_verb(n, 'quote', 'quotes')} the full price first and {_verb(n, 'take', 'takes')} every discount "
                "to the store manager for a yes or no before the bill is made")
        # role model: the colleague who sells the most at MRP while discounting less than the store norm
        models = []
        for x in peers:
            g = by.get(x)
            if g is not None and len(g) >= MIN_BILLS_PERSON and g["mrp_value"].sum() and x not in self.subjects:
                if 1 - g["value"].sum() / g["mrp_value"].sum() <= c_norm["value"]:
                    models.append((-float(g["mrp_value"].sum()), x))
        model = sorted(models)[0][1] if models else None
        cause = (f"In the last {days['display']} days {join_names(bits)}. The other salespeople at {store} discounted "
                 f"{c_peer_share['display']} of their bills ({c_norm['display']} of MRP).")
        # is it new? each named person's own rate in the nine months before the window
        was = []
        for sp in flagged:
            v = k_discount_rate(m, {**sid, "salesperson_ids": [sp], **self.prior})
            if v is not None:
                c_was = book.add(f"discount_rate_prior:{sp}", f"{self.name(sp)}: discount rate, the {PRIOR_DAYS} days before",
                                 "discount_rate", {**sid, "salesperson_ids": [sp], **self.prior})
                was.append(f"{self.name(sp)} gave {c_was['display']}")
        if len(was) == len(flagged):
            cause += f" In the nine months before, {join_names(was)} of MRP."
        alert = self.finish(
            alert_id=alert_id, store=store, cause_code="high_discount",
            headline=f"{store}: {who} give away {c_own['display']} of MRP in discounts; colleagues give {c_norm['display']}"
            if n > 1 else f"{store}: {who} gives away {c_own['display']} of MRP in discounts; colleagues give {c_norm['display']}",
            cause=cause, action={"who": who, "what": what, "when": "from today", "text": f"From today, {who} {what}."},
            rupees=rupees,
            arithmetic={
                "formula": "(their discount rate − discount rate of same-store colleagues) × their sales at MRP a week "
                           "= margin given away a week (not sales lost)",
                "worked": f"({c_own['display']} − {c_norm['display']}) × {c_mrp['display']} of sales at MRP a week = "
                          f"{r['display']} given away a week",
                "input_check_ids": [c_own["id"], c_norm["id"], c_mrp["id"]],
            },
            basis=f"Same store, the other salespeople, same {CUR_DAYS} days", people=flagged, book=book,
            follow_up={"metric_label": f"Discount rate of {who} at {store}", "kind": "discount_rate", "params": grp,
                       "baseline_value": c_own["value"], "target_value": c_norm["value"], "higher_is_better": False},
            definition=(f"Discount rate = 1 − sum(qty × selling price) ÷ sum(qty × MRP) over product lines (carry bags left out) "
                        f"of bills in the {CUR_DAYS} days ending on the run date. The named salespeople are compared with the other salespeople "
                        "of the same store who are still on the roster, over the same days."),
        )
        if alert:
            self.correcting(flagged)
        if alert and model:
            one = {**sid, "salesperson_ids": [model], **cur}
            c_model = book.add(f"discount_rate:{model}", f"{self.name(model)}: discount rate", "discount_rate", one)
            for sp in flagged:
                rate, share, mrp = own[sp]
                self.card(
                    alert_id=alert_id, store=store, sp=sp, peer=model,
                    behaviour=f"{_first(self.name(sp))}, you gave a discount on {share['display']} of your bills in the last "
                              f"{days['display']} days, {rate['display']} of MRP.",
                    peer_line=f"{self.name(model)} sells the most among your colleagues and gives {c_model['display']}.",
                    action="Today, quote the full price first and take any discount to the store manager before you bill.",
                    book_items=[days, share, rate, c_model],
                    priority=max(0.0, (rate["value"] - c_norm["value"]) * mrp["value"]),
                    definition=f"Discount = 1 − selling price ÷ MRP over the products on your bills, last {CUR_DAYS} days.",
                )
        return alert

    def low_group(self, store: str):
        """Small-store fallback: (window, flagged, colleagues, model) or None.

        Over the last LONG_DAYS days, the active salespeople whose items per bill are at least
        IPB_MIN_GAP below the store's best seller are tested together, as one group, against the
        rest of the store (Welch z at Z_PERSON). One test per store, so the bar stays strict.
        """
        w = {"start": add_days(self.as_of, -(LONG_DAYS - 1)), "end": self.as_of}
        act, by = self._pool(store, w)
        sized = {sp: g for sp, g in by.items() if sp in act and len(g) >= MIN_BILLS_PERSON}
        if len(sized) < 2:
            return None
        mean = {sp: float(g["items"].mean()) for sp, g in sized.items()}
        best = sorted(sized, key=lambda x: (-mean[x], x))[0]
        low = sorted(sp for sp in sized if mean[sp] <= (1 - IPB_MIN_GAP) * mean[best])
        rest = sorted(sp for sp in sized if sp not in low)
        if not low or not rest:
            return None
        a, b = pd.concat([sized[x] for x in low]), pd.concat([sized[x] for x in rest])
        if len(b) < MIN_BILLS_PEERS:
            return None
        z = _welch(a["items"], b["items"])
        if z is None or z > -Z_PERSON or a["items"].mean() / b["items"].mean() - 1 > -IPB_MIN_GAP:
            return None
        return w, low, rest, best

    def low_items(self, store: str):
        m, cur = self.m, self.cur
        act, by = self._pool(store)
        stat = lambda g: float(g["items"].mean())
        flagged, used = [], {}
        for sp in act:
            g = by.get(sp)
            others, _ = self.yardstick([x for x in act if x != sp and x in by], by, stat, MIN_BILLS_PERSON)
            if g is None or len(g) < MIN_BILLS_PERSON or not others:
                continue
            o = pd.concat([by[x] for x in others])
            if len(o) < MIN_BILLS_PEERS:
                continue
            z = _welch(g["items"], o["items"])
            if z is not None and z <= -Z_PERSON and g["items"].mean() / o["items"].mean() - 1 <= -IPB_MIN_GAP:
                flagged.append(sp)
                used[sp] = others
        peers, model = self.yardstick([x for x in act if x not in flagged and x in by], by, stat, MIN_BILLS_PERSON)
        n_days = CUR_DAYS
        if not flagged:
            group = self.low_group(store)
            if group is None:
                return None
            cur, flagged, peers, model = group
            used = {sp: peers for sp in flagged}
            n_days = LONG_DAYS
        if not flagged or not peers or not model:
            return None
        if model in self.subjects:
            self.notes.append(f"{store}:{LEVER}:low_items_per_bill: not sent, the colleague to shadow is being corrected "
                              "on another measure, so no action can name a model")
            return None
        left_out = " (the best one left out)" if model not in peers else ""
        alert_id = f"{store}:{LEVER}:low_items_per_bill"
        book = CheckBook(m, alert_id)
        sid = {"store_ids": [store]}
        grp, oth = {**sid, "salesperson_ids": flagged, **cur}, {**sid, "salesperson_ids": peers, **cur}
        days = self.days_check(book, cur)
        c_own = book.add("items_per_bill_named", "Items per bill of the named salespeople", "items_per_bill", grp)
        c_peer = book.add("items_per_bill_colleagues", f"Items per bill of the other salespeople at the store{left_out}", "items_per_bill", oth)
        c_week = book.add("bills_per_week_named", "Bills a week, the named salespeople", "product_bills_per_week", grp)
        c_val = book.add("avg_item_value", f"Average value of an item at {store}", "avg_item_value", {**sid, **cur})
        book.add("bills_named", "Bills of the named salespeople", "product_bills", grp)
        book.add("bills_colleagues", "Bills of the other salespeople", "product_bills", oth)
        bits, own = [], {}
        for sp in flagged:
            one = {**sid, "salesperson_ids": [sp], **cur}
            ipb = book.add(f"items_per_bill:{sp}", f"{self.name(sp)}: items per bill", "items_per_bill", one)
            book.add(f"z:{sp}", f"{self.name(sp)}: Welch z against the other salespeople at the store{left_out}", "items_per_bill_z",
                     {**one, "peer_salesperson_ids": used[sp]})
            book.add(f"bills:{sp}", f"{self.name(sp)}: bills", "product_bills", one)
            wk = book.add(f"bills_per_week:{sp}", f"{self.name(sp)}: bills a week", "product_bills_per_week", one)
            own[sp] = (ipb, wk)
            bits.append(f"{self.name(sp)} averaged {ipb['display']} items a bill")
        if not book.usable():
            return None
        c_model = book.add(f"items_per_bill:{model}", f"{self.name(model)}: items per bill", "items_per_bill",
                           {**sid, "salesperson_ids": [model], **cur})
        rupees = items_rupees(c_peer["value"], c_own["value"], c_week["value"], c_val["value"])
        r = book.add("rupees_at_stake", "Rupees at stake a week", "items_rupees_weekly", {
            "peer_check_id": c_peer["id"], "own_check_id": c_own["id"], "bills_per_week_check_id": c_week["id"],
            "item_value_check_id": c_val["id"]}, value=rupees)
        who = join_names([self.name(sp) for sp in flagged])
        n = len(flagged)
        what = (f"{_verb(n, 'shadow', 'shadows')} {self.name(model)} for the first five customers and "
                f"{_verb(n, 'show', 'shows')} one matching add-on at every trial before the bill is made")
        day = self.shadow_day(book, flagged + [model])
        alert = self.finish(
            alert_id=alert_id, store=store, cause_code="low_items_per_bill",
            headline=f"{store}: {who} {_verb(n, 'sell', 'sells')} {c_own['display']} items a bill; colleagues sell {c_peer['display']}",
            cause=(f"In the last {days['display']} days {join_names(bits)}. "
                   + (f"{self.name(model)}, the only other salesperson at {store} with enough bills to compare, averaged "
                      f"{c_model['display']}." if peers == [model] else
                      f"The other salespeople at {store} averaged {c_peer['display']}{left_out}, and {self.name(model)}, "
                      f"the best of them, {c_model['display']}.")),
            action={"who": who, "what": what, "when": day[1], "text": f"{day[0]}, {who} {what}."} if day else None,
            rupees=rupees,
            arithmetic={
                "formula": "(colleagues' items per bill − their items per bill) × their bills a week × average value of an item at the store",
                "worked": f"({c_peer['display']} − {c_own['display']}) × {c_week['display']} bills a week × {c_val['display']} "
                          f"= {r['display']} a week",
                "input_check_ids": [c_peer["id"], c_own["id"], c_week["id"], c_val["id"]],
            },
            basis=f"Same store, the other salespeople{left_out}, same {n_days} days", people=flagged + [model], book=book,
            follow_up={"metric_label": f"Items per bill of {who} at {store}", "kind": "items_per_bill", "params": grp,
                       "baseline_value": c_own["value"], "target_value": c_peer["value"], "higher_is_better": True},
            definition=(f"Items per bill = sum of qty over product lines (carry bags left out) ÷ number of bills, over the "
                        f"{n_days} days ending on the run date. The named salespeople are compared with the other salespeople of the same "
                        "store who are still on the roster, over the same days."),
        )
        if alert:
            self.correcting(flagged)
            for sp in flagged:
                ipb, wk = own[sp]
                self.card(
                    alert_id=alert_id, store=store, sp=sp, peer=model,
                    behaviour=f"{_first(self.name(sp))}, your bills averaged {ipb['display']} items in the last {days['display']} days.",
                    peer_line=f"{self.name(model)} at your store averages {c_model['display']}.",
                    action="Today, show one matching add-on at every trial before you make the bill.",
                    book_items=[days, ipb, c_model],
                    priority=max(0.0, (c_peer["value"] - ipb["value"]) * wk["value"] * c_val["value"]),
                    definition=f"Items per bill = products on your bills ÷ your bills, last {n_days} days; carry bags are not counted.",
                )
        return alert

    # ------------------------------------------------- 4. a category the colleagues sell and one person does not
    def category_avoided(self, store: str):
        m, year, cur = self.m, self.year, self.cur
        if self.rows[store]["opened_on"] > year["start"]:
            return
        act = self.active(store)
        f = _sel(m, {"store_ids": [store], **year, "salesperson_ids": act})
        by = {sp: g for sp, g in f.groupby("salesperson_id", sort=True)}
        recent = {sp: g[g["bill_date"] >= cur["start"]] for sp, g in by.items()}
        for sp in act:
            g = by.get(sp)
            everyone = [x for x in act if x != sp and x in by]
            if g is None or len(g) < CAT_MIN_BILLS or not everyone:
                continue
            g90 = recent[sp]
            for cat in CATEGORIES:
                col = "has:" + cat
                others, model = self.yardstick(everyone, by, lambda x: float(x[col].mean()), CAT_MIN_BILLS)
                if not others or not model:
                    continue
                o = pd.concat([by[x] for x in others])
                o90 = pd.concat([recent[x] for x in others])
                k1, n1, k0, n0 = float(g[col].sum()), len(g), float(o[col].sum()), len(o)
                if not k0 or n1 * k0 / n0 < CAT_MIN_EXPECTED:
                    continue
                z = z_score(k1, n1, k0, n0)
                if z is None or z > -Z_CATEGORY or k1 / n1 > CAT_MAX_RATIO * k0 / n0:
                    continue
                if not len(g90) or not len(o90) or g90[col].mean() > CAT_MAX_RATIO * o90[col].mean():
                    continue  # not visible in the last 90 days: it is history, not something to change today
                self._category_alert(store, sp, cat, others, model)

    def _category_alert(self, store, sp, cat, others, model):
        m, year, cur = self.m, self.year, self.cur
        alert_id = f"{store}:{LEVER}:category_avoided:{sp}"
        if any(a["alert_id"] == alert_id for a in self.alerts):
            return  # one alert per salesperson: the first category in the fixed list order
        word = CAT_WORD[cat]
        book = CheckBook(m, alert_id)
        sid = {"store_ids": [store], "category": cat}
        one, oth = {**sid, "salesperson_ids": [sp]}, {**sid, "salesperson_ids": others}
        ydays = self.days_check(book, year, "window_days_year")
        days = self.days_check(book, cur)
        c_own = book.add("share_own", f"{self.name(sp)}: share of bills with {word}, last {YEAR_DAYS} days", "category_bill_share", {**one, **year})
        c_peer = book.add("share_colleagues", f"Other salespeople at the store: share of bills with {word}, last {YEAR_DAYS} days",
                          "category_bill_share", {**oth, **year})
        c_k = book.add("category_bills_own", f"{self.name(sp)}: bills with {word}, last {YEAR_DAYS} days", "category_bills", {**one, **year})
        c_n = book.add("bills_own", f"{self.name(sp)}: bills, last {YEAR_DAYS} days", "product_bills",
                       {"store_ids": [store], "salesperson_ids": [sp], **year})
        book.add("z", "Two-proportion z against the other salespeople at the store", "category_bill_share_z",
                 {**one, **year, "peer_salesperson_ids": others})
        c_own90 = book.add("share_own_recent", f"{self.name(sp)}: share of bills with {word}, last {CUR_DAYS} days", "category_bill_share", {**one, **cur})
        c_peer90 = book.add("share_colleagues_recent", f"Other salespeople: share of bills with {word}, last {CUR_DAYS} days",
                            "category_bill_share", {**oth, **cur})
        city = self.rows[store]["city"]
        city_stores = sorted(s for s in self.established if self.rows[s]["city"] == city)
        c_city = book.add("share_city", f"{city}, established stores: share of bills with {word}, last {YEAR_DAYS} days",
                          "category_bill_share", {"store_ids": city_stores, "category": cat, **year})
        c_week = book.add("bills_per_week_own", f"{self.name(sp)}: bills a week, last {CUR_DAYS} days", "product_bills_per_week",
                          {"store_ids": [store], "salesperson_ids": [sp], **cur})
        c_with = book.add("avg_bill_with", f"Average bill at {store} with {word}, last {YEAR_DAYS} days", "avg_bill_value_split",
                          {"store_ids": [store], "category": cat, "with_category": True, **year})
        c_without = book.add("avg_bill_without", f"Average bill at {store} without {word}, last {YEAR_DAYS} days", "avg_bill_value_split",
                             {"store_ids": [store], "category": cat, "with_category": False, **year})
        if not book.usable():
            self.notes.append(f"{alert_id}: not sent, a figure could not be worked out")
            return
        # rupees from the last 90 days (what is being lost now), not from the year the test needs
        rupees = category_rupees(c_peer90["value"], c_own90["value"], c_week["value"], c_with["value"], c_without["value"])
        r = book.add("rupees_at_stake", "Rupees at stake a week", "category_rupees_weekly", {
            "peer_check_id": c_peer90["id"], "own_check_id": c_own90["id"], "bills_per_week_check_id": c_week["id"],
            "with_check_id": c_with["id"], "without_check_id": c_without["id"]}, value=max(rupees, 0))
        action = None
        left_out = " (the best one left out)" if model not in others else ""
        if model in self.subjects:
            self.notes.append(f"{alert_id}: not sent, the colleague to shadow is being corrected on another measure")
            return
        if model:
            c_model = book.add(f"share:{model}", f"{self.name(model)}: share of bills with {word}, last {YEAR_DAYS} days",
                               "category_bill_share", {**sid, "salesperson_ids": [model], **year})
            who = self.name(sp)
            what = (f"shadows {self.name(model)} for the first five customers and shows {word} to every customer "
                    "before the trial ends")
            day = self.shadow_day(book, [sp, model])
            if day:
                action = {"who": who, "what": what, "when": day[1], "text": f"{day[0]}, {who} {what}."}
        alert = self.finish(
            alert_id=alert_id, store=store, cause_code="category_avoided",
            headline=f"{store}: {self.name(sp)} has {word} on {c_own['display']} of bills; colleagues {c_peer['display']}",
            cause=(f"In the last {ydays['display']} days {word} were on {c_k['display']} of {self.name(sp)}'s {c_n['display']} bills "
                   f"({c_own['display']}), against {c_peer['display']} for the other salespeople at {store}{left_out} and {c_city['display']} "
                   f"across {city}'s stores. In the last {days['display']} days it is {c_own90['display']} against {c_peer90['display']}."
                   + (f" {self.name(model)}, the best of them, is at {c_model['display']}." if model else "")),
            action=action, rupees=rupees,
            arithmetic={
                "formula": f"(colleagues' share of bills with the category − own share, last {CUR_DAYS} days) × own bills a week × "
                           "(average bill with the category − average bill without it, same store, last 365 days)",
                "worked": f"({c_peer90['display']} − {c_own90['display']}) × {c_week['display']} bills a week × "
                          f"({c_with['display']} − {c_without['display']}) = {r['display']} a week",
                "input_check_ids": [c_peer90["id"], c_own90["id"], c_week["id"], c_with["id"], c_without["id"]],
            },
            basis=f"Same store, the other salespeople{left_out}, same {YEAR_DAYS} days; the city is shown for reference",
            people=[sp] + ([model] if model else []), book=book,
            follow_up={"metric_label": f"Share of {self.name(sp)}'s bills with {word} at {store}", "kind": "category_bill_share",
                       "params": {**one, **cur}, "baseline_value": c_own90["value"], "target_value": c_peer90["value"],
                       "higher_is_better": True},
            definition=(f"Share = bills with at least one {cat} line ÷ all bills of the salesperson at this store, over the "
                        f"{YEAR_DAYS} days ending on the run date (a category is a small share of bills, so {CUR_DAYS} days is too few to tell). "
                        "Compared with the other salespeople of the same store who are still on the roster, same days."),
        )
        if alert:
            self.correcting([sp])
            self.card(
                alert_id=alert_id, store=store, sp=sp, peer=model,
                behaviour=f"{_first(self.name(sp))}, {word} were on {c_own['display']} of your bills in the last {ydays['display']} days.",
                peer_line=f"{self.name(model)} at your store has them on {c_model['display']}.",
                action=f"Today, show {word} to every customer before the trial ends.",
                book_items=[ydays, c_own, c_model], priority=rupees,
                definition=f"Share of your bills with at least one {cat} line, last {YEAR_DAYS} days.",
            )

    # ---------------------------------------------------------------- run
    def run(self):
        for store in self.established:
            if store not in self.m._basket_store:
                continue
            # discounts and items per bill first: someone flagged there is not named as a model after
            self.high_discount(store)
            self.low_items(store)
            for main, addon in PAIRS:
                self.pair_attach(store, main, addon)
            self.category_avoided(store)
        return self


def _run(m: Metrics) -> Baskets:
    """One pass per Metrics object; detect() and card_candidates() share it."""
    b = getattr(m, "_basket_run", None)
    if b is None:
        b = Baskets(m).run()
        m._basket_run = b
    return b


def detect(m: Metrics) -> tuple[list[dict], list[str]]:
    b = _run(m)
    return list(b.alerts), list(b.notes)


def card_candidates(m: Metrics) -> list[dict]:
    return list(_run(m).cards)


def data_issues(m: Metrics, windows: dict) -> list[dict]:
    """A selling price above MRP cannot be right. Listed per store; that store's discounts are not judged."""
    cur = {"start": add_days(m.as_of, -(CUR_DAYS - 1)), "end": m.as_of}
    f = _frame(m)
    out = []
    for store in sorted(m._basket_store):
        p = {"store_ids": [store], **cur}
        bad = _sel(m, p)
        bad = bad[bad["above"] > 0]
        if not len(bad):
            continue
        issue_id = f"{store}:price_above_mrp"
        book = CheckBook(m, issue_id)
        n = book.add("lines_above_mrp", f"Product lines sold above MRP, last {CUR_DAYS} days", "lines_above_mrp", p)
        dates = sorted(set(bad["bill_date"]))
        out.append({
            "issue_id": issue_id, "store_id": store, "kind": "price_above_mrp",
            "title": f"{store}: items billed above MRP",
            "detail": f"{n['display']} product lines have a selling price higher than the MRP. A negative discount cannot be right.",
            "first_date": dates[0], "last_date": dates[-1], "days_affected": len(dates),
            "handling": "Discounts at this store are not judged while such lines are in the window, and no discount alert is raised.",
            "checks": book.items,
        })
    return out
