"""The "more bills" lever: find real conversion drops, name the cause, build the action.

Conversion = bills / footfall over valid store-days. The method and every threshold
are explained in docs/METHOD.md.
"""
from __future__ import annotations

import math

from .checks import EXTRA_DISPLAY, CheckBook, conv_tenths, fmt_date, fmt_day, fmt_int_in, fmt_num, numbers_not_in_checks, rupees_at_stake
from .issues import judgeable
from .metrics import EXTRA_KINDS, WEEKDAYS, Metrics, add_days, d, rnd, z_score
from .rank import has_who_what_when

LEVER = "more_bills"
CUR_DAYS = 28  # current window
BASE_DAYS = 91  # benchmark window (13 weeks)
NEW_STORE_DAYS = 180  # opened less than this before as-of: not judged, not a benchmark
LOOK_AHEAD_DAYS = 9  # busy dates named in an action: from the day after as-of through the next full weekend

Z_SCAN = -2.9  # undirected scan over every store and city, every run
Z_CAUSE = -2.0  # one test tied to one dated event
MIN_REL_DROP = 0.10  # current conversion at least 10% below its benchmark

LEAVER_MIN_GONE_DAYS = 14  # off the roster at least this long
LEAVER_LOOKBACK_DAYS = 91  # and no longer ago than this
STRONG_RATIO = 1.25  # bills per present day vs same-store peer median
MIN_PRESENT_DAYS = 20  # to compare bills per present day

MISSED_RATIO = 0.80  # present on at most 80% of the colleagues' median days
MISSED_MIN_GAP = 4  # and at least 4 days fewer
SHORT_WEEK_DAYS = 4  # a short week: present on 4 or fewer of 7 days, and fewer than colleagues
MISSED_MAX_WEEKS_BACK = 26  # how far back to look for the week the missed shifts began

THIN_RATIO = 1.25  # walk-ins per salesperson, busy days vs other days
CITY_BEYOND = 0.10  # a store in a slow city needs a drop this much deeper than the city

NOT_SENT = "not_sent"  # a cause was found but the alert broke a sending rule; do not try another cause

FORMULA = "(fair conversion − current conversion) × walk-ins a week × average bill value"


# ---- two small check kinds used to name things (recipes in docs/CHECKS-followup.md) ----
def _festival_name(m: Metrics, p: dict):
    """The festival in the calendar for that state and date, or None."""
    names = getattr(m, "_festival_names", None)
    if names is None:
        cal = m.data.calendar
        names = {(st, dt): f.strip() for dt, st, f in zip(cal["date"], cal["state"], cal["festival"]) if f.strip()}
        m._festival_names = names
    return names.get((p["state"], p["date"]))


def _store_opened_on(m: Metrics, p: dict):
    opened = dict(zip(m.data.stores["store_id"], m.data.stores["opened_on"]))
    return opened.get(p["store_id"])


EXTRA_KINDS["festival_name"] = _festival_name
EXTRA_KINDS["store_opened_on"] = _store_opened_on
EXTRA_DISPLAY["store_opened_on"] = fmt_date


# ---- city-adjusted sizing (recipes in docs/CHECKS.md section 6) ----
def _date_range(m: Metrics, p: dict):
    """The window itself, so that the dates quoted beside a figure are a check: "start..end"."""
    return f"{p['start']}..{p['end']}"


def _show_range(v: str) -> str:
    a, b = v.split("..")
    return f"{fmt_date(a)} to {fmt_date(b)}"


def _beyond_city_z(m: Metrics, p: dict):
    """z of (change at the store) minus (change at the other city stores), base window to test window.

    Negative = the store fell more than the rest of its city. Unpooled: each of the four
    conversions adds p(1 - p) / walk-ins to the variance. Rounded half up to 2 decimals.
    """
    rates = []
    for stores in (p["store_ids"], p["other_store_ids"]):
        for s_, e_ in ((p["start"], p["end"]), (p["base_start"], p["base_end"])):
            b, f, *_ = m.parts(stores, s_, e_)
            if not f:
                return None
            rates.append((b / f, f))
    (p1, n1), (p0, n0), (q1, k1), (q0, k0) = rates
    var = sum(x * (1 - x) / n for x, n in rates)
    if var <= 0:
        return None
    return rnd(((p1 - p0) - (q1 - q0)) / math.sqrt(var), 2)


def rupees_beyond_city(bench: float, cur: float, city_bench: float, city_cur: float, walkins: float, abv: float) -> int:
    """Rupees a week on the drop beyond the city, from the figures as displayed.

    (store drop - city drop) in tenths of a point; the city drop counts only when the other
    stores fell (it never makes the figure bigger than the store's own drop).
    """
    city_drop = max(0, conv_tenths(city_bench) - conv_tenths(city_cur))
    gap = conv_tenths(bench) - conv_tenths(cur) - city_drop
    return int(rnd(gap * int(rnd(walkins)) * int(rnd(abv)) / 1000 / 100)) * 100


EXTRA_KINDS["date_range"] = _date_range
EXTRA_DISPLAY["date_range"] = _show_range
EXTRA_KINDS["beyond_city_z"] = _beyond_city_z
EXTRA_DISPLAY["beyond_city_z"] = lambda v: fmt_num(v, 2)
EXTRA_DISPLAY["rupees_at_stake_city"] = lambda v: "₹" + fmt_int_in(int(v))

DUSSEHRA = "Dussehra / Dasara"
YOY_MAX_DAYS_AFTER_FESTIVAL = 60  # align on Dussehra only in the festival season that follows it


def upcoming_busy_dates(m: Metrics, book: CheckBook, state: str) -> tuple[list[str], str]:
    """Busy dates in the LOOK_AHEAD_DAYS after as-of, and how to say them: 'Sat 7 Nov and Sun 8 Nov (Diwali)'.

    The only use of calendar rows after as-of. Every date is in the `upcoming_busy_dates`
    check and every festival named has its own `festival_name` check.
    """
    c = book.add("upcoming_busy_dates",
                 f"Busy days in the next {LOOK_AHEAD_DAYS} days (weekends, festivals, wedding dates)",
                 "upcoming_busy_dates",
                 {"state": state, "start": add_days(m.as_of, 1), "end": add_days(m.as_of, LOOK_AHEAD_DAYS)})
    dates = c["value"].split(", ") if c["value"] else []
    said = []
    for dt in dates:
        text = fmt_day(dt)
        if _festival_name(m, {"state": state, "date": dt}):
            f = book.add(f"festival:{dt}", f"Festival on {fmt_date(dt)} in the {state} calendar", "festival_name",
                         {"state": state, "date": dt})
            text += f" ({f['display']})"
        said.append(text)
    return dates, join_names(said)


def conversion_definition(where: str, compared_with: str) -> str:
    """One sentence, no figures: how conversion is measured and which windows the headline compares."""
    return (f"Conversion is bills divided by walk-ins {where}, counted only on days with a usable door count "
            f"(walk-ins above zero and no more bills than walk-ins); the headline compares the last four weeks "
            f"with {compared_with}, and both windows are dated in the checks.")


def make_windows(as_of: str) -> dict:
    cur_start = add_days(as_of, -(CUR_DAYS - 1))
    return {
        "current": {"start": cur_start, "end": as_of},
        "baseline": {"start": add_days(cur_start, -BASE_DAYS), "end": add_days(cur_start, -1)},
    }


def is_new_store(opened_on: str, as_of: str) -> bool:
    return (d(as_of) - d(opened_on)).days < NEW_STORE_DAYS


def join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def win(start: str, end: str) -> dict:
    return {"start": start, "end": end}


def span(w: dict) -> str:
    return f"{fmt_date(w['start'])} to {fmt_date(w['end'])}"


class Detector:
    def __init__(self, m: Metrics):
        self.m = m
        self.as_of = m.as_of
        self.windows = make_windows(self.as_of)
        self.cur = self.windows["current"]
        self.base = self.windows["baseline"]
        st = m.data.stores
        self.store_rows = {r["store_id"]: r for r in st.to_dict("records")}
        self.established = [s for s, r in self.store_rows.items() if not is_new_store(r["opened_on"], self.as_of)]
        self.notes: list[str] = []  # why a candidate was not sent (printed by the CLI, not in the JSON)

    # ------------------------------------------------------------------ tests
    def drop_test(self, stores: list[str], test: dict, bench: dict, day_type: str = "all"):
        """(z, relative change of the current window vs the benchmark) or None when not measurable."""
        m = self.m
        b1, n1, *_ = m.parts(stores, test["start"], test["end"], day_type)
        b0, n0, *_ = m.parts(stores, bench["start"], bench["end"], day_type)
        z = z_score(b1, n1, b0, n0)
        bc, nc, *_ = m.parts(stores, self.cur["start"], self.cur["end"], day_type)
        if z is None or not nc or not b0:
            return None
        return z, (bc / nc) / (b0 / n0) - 1

    def judged(self, store: str, *wins: dict) -> bool:
        return store in self.established and all(judgeable(self.m, store, w["start"], w["end"]) for w in wins)

    # --------------------------------------------------------- shared pieces
    def city_others(self, store: str, *wins: dict) -> list[str]:
        """The other established stores of the store's city with usable footfall in every window."""
        city = self.store_rows[store]["city"]
        return sorted(s for s in self.established if s != store and self.store_rows[s]["city"] == city
                      and self.judged(s, *wins))

    def core_checks(self, book: CheckBook, stores: list[str], bench: dict, test: dict, bench_label: str,
                    city_adjust: bool = False):
        """The checks every alert carries: conversion now and at the benchmark, the test, and the rupees.

        With city_adjust (a single store), the rupees are sized on the drop beyond the other
        stores of its city over the same two windows (docs/METHOD.md section 4).
        """
        cur = self.cur
        sid = {"store_ids": sorted(stores)}
        c_cur = book.add("conv_current", f"Conversion, {span(cur)}", "conversion", {**sid, **cur, "day_type": "all"})
        c_bench = book.add("conv_benchmark", f"Conversion, {bench_label} ({span(bench)})", "conversion",
                           {**sid, **bench, "day_type": "all"})
        book.add("bills_current", f"Bills, {span(cur)}", "bills_count", {**sid, **cur, "day_type": "all"})
        book.add("footfall_current", f"Walk-ins, {span(cur)}", "footfall_sum", {**sid, **cur, "day_type": "all"})
        book.add("bills_benchmark", f"Bills, {span(bench)}", "bills_count", {**sid, **bench, "day_type": "all"})
        book.add("footfall_benchmark", f"Walk-ins, {span(bench)}", "footfall_sum", {**sid, **bench, "day_type": "all"})
        c_test = c_cur
        if test != cur:
            c_test = book.add("conv_since", f"Conversion, {span(test)}", "conversion", {**sid, **test, "day_type": "all"})
        book.add("z", f"Two-proportion z, {span(test)} against {span(bench)}", "two_proportion_z",
                 {**sid, **test, "base_start": bench["start"], "base_end": bench["end"], "day_type": "all"})
        walk = book.add("walkins_per_week", f"Walk-ins a week, {span(cur)}", "walkins_per_week", {**sid, **cur})
        abv = book.add("avg_bill_value", f"Average bill value, {span(cur)}", "avg_bill_value", {**sid, **cur})
        r_cur = book.add("range_current", "Dates of the current window", "date_range", dict(cur))
        r_bench = book.add("range_benchmark", "Dates of the benchmark window", "date_range", dict(bench))
        r_test = r_cur if test == cur else book.add("range_since", "Dates since the cause began", "date_range", dict(test))
        if any(c["value"] is None for c in (c_cur, c_bench, walk, abv)):
            return None
        out = {"cur": c_cur, "bench": c_bench, "test": c_test, "walk": walk, "abv": abv,
               "r_cur": r_cur, "r_bench": r_bench, "r_test": r_test, "city": None}
        others = self.city_others(stores[0], cur, bench, test) if city_adjust and len(stores) == 1 else []
        if others:
            city = self.store_rows[stores[0]]["city"]
            osid = {"store_ids": others}
            c_cb = book.add("conv_city_benchmark", f"Conversion at the other {city} stores ({join_names(others)}), {span(bench)}",
                            "conversion", {**osid, **bench, "day_type": "all"})
            c_cc = book.add("conv_city_current", f"Conversion at the other {city} stores ({join_names(others)}), {span(cur)}",
                            "conversion", {**osid, **cur, "day_type": "all"})
            c_z = book.add("z_beyond_city", f"z of the fall at {stores[0]} beyond the other {city} stores, {span(test)} "
                           f"against {span(bench)}", "beyond_city_z",
                           {"store_ids": sorted(stores), "other_store_ids": others, **test,
                            "base_start": bench["start"], "base_end": bench["end"]})
            if c_cb["value"] is None or c_cc["value"] is None:
                return None
            rupees = rupees_beyond_city(c_bench["value"], c_cur["value"], c_cb["value"], c_cc["value"],
                                        walk["value"], abv["value"])
            r = book.add("rupees_at_stake", "Rupees at stake a week, on the fall beyond the rest of the city",
                         "rupees_at_stake_city", {
                             "benchmark_check_id": c_bench["id"], "current_check_id": c_cur["id"],
                             "city_benchmark_check_id": c_cb["id"], "city_current_check_id": c_cc["id"],
                             "walkins_check_id": walk["id"], "avg_bill_check_id": abv["id"]}, value=rupees)
            if conv_tenths(c_cb["value"]) > conv_tenths(c_cc["value"]):
                worked = (f"(({c_bench['display']} − {c_cur['display']}) − ({c_cb['display']} − {c_cc['display']})) × "
                          f"{walk['display']} walk-ins a week × {abv['display']} = {r['display']} a week")
                inputs = [c_bench["id"], c_cur["id"], c_cb["id"], c_cc["id"], walk["id"], abv["id"]]
                formula = (f"(fall at {stores[0]} − fall at the other {city} stores over the same weeks) × walk-ins a week "
                           f"× average bill value")
            else:
                worked = (f"({c_bench['display']} − {c_cur['display']}) × {walk['display']} walk-ins a week × "
                          f"{abv['display']} = {r['display']} a week")
                inputs = [c_bench["id"], c_cur["id"], walk["id"], abv["id"]]
                formula = (f"(fall at {stores[0]}) × walk-ins a week × average bill value; the other {city} stores did not "
                           f"fall over the same weeks, so nothing is taken off for the city")
            out.update(rupees=rupees, city={"name": city, "others": others, "bench": c_cb, "cur": c_cc, "z": c_z},
                       arithmetic={"formula": formula, "worked": worked, "input_check_ids": inputs})
            return out
        rupees = rupees_at_stake(c_bench["value"], c_cur["value"], walk["value"], abv["value"])
        r = book.add("rupees_at_stake", "Rupees at stake a week", "rupees_at_stake", {
            "benchmark_check_id": c_bench["id"], "current_check_id": c_cur["id"],
            "walkins_check_id": walk["id"], "avg_bill_check_id": abv["id"]}, value=rupees)
        out.update(rupees=rupees, arithmetic={
            "formula": FORMULA,
            "worked": f"({c_bench['display']} − {c_cur['display']}) × {walk['display']} walk-ins a week × "
                      f"{abv['display']} = {r['display']} a week",
            "input_check_ids": [c_bench["id"], c_cur["id"], walk["id"], abv["id"]],
        })
        return out

    def city_sentence(self, core) -> str:
        """What the rest of the city did over the same weeks, and whether the store's extra fall could be chance."""
        c = core and core.get("city")
        if not c:
            return ""
        text = (f" Over the same weeks the other {c['name']} stores went from {c['bench']['display']} to "
                f"{c['cur']['display']}, and the rupees at stake count only the fall beyond them.")
        if c["z"]["value"] is None or c["z"]["value"] > Z_CAUSE:
            text += " The part of the fall beyond the rest of the city is not large enough to rule out chance."
        return text

    def upcoming(self, book: CheckBook, state: str) -> tuple[list[str], str]:
        """(busy dates in the days after as-of, the same dates as text with festivals named)."""
        return upcoming_busy_dates(self.m, book, state)

    def active_staff(self, store: str) -> list[str]:
        return [p for p in self.m.store_sps.get(store, []) if self.as_of in self.m.roster.get(p, {})]

    def quiet_day(self, book: CheckBook, store: str) -> str | None:
        c = book.add("quietest_weekday", f"Quietest weekday by average walk-ins, {span({'start': self.base['start'], 'end': self.as_of})}",
                     "quietest_weekday", {"store_id": store, "start": self.base["start"], "end": self.as_of})
        return c["value"]

    def offs_on_busy_days(self, book: CheckBook, store: str, dates: list[str], skip: list[str], limit: int = 2):
        """Active salespeople whose usual weekly off falls on the weekday of an upcoming busy date."""
        busy_weekdays = {WEEKDAYS[d(x).weekday()] for x in dates}
        found = []
        for p in self.active_staff(store):
            if p in skip or len(found) >= limit:
                continue
            day = self.m.compute("usual_off_weekday", {"salesperson_id": p, **self.cur})
            if day in busy_weekdays:
                book.add(f"usual_off:{p}", f"Usual weekly off of {self.m.sp_name[p]}, {span(self.cur)}",
                         "usual_off_weekday", {"salesperson_id": p, **self.cur})
                found.append((p, day))
        return found

    def finish(self, *, alert_id, scope, stores, city, cause_code, headline, cause, action, core, basis,
               people, book, metric_label, definition):
        """Assemble an Alert, or return NOT_SENT (with a note) when it breaks a sending rule."""
        if core is None or core["rupees"] <= 0:
            self.notes.append(f"{alert_id}: not sent, no rupees at stake could be worked out")
            return NOT_SENT
        if not has_who_what_when(action):
            self.notes.append(f"{alert_id}: not sent, no action naming who, what and when could be built")
            return NOT_SENT
        stray = numbers_not_in_checks([headline, cause, action["text"], core["arithmetic"]["worked"]], book.items)
        if stray or not book.usable():
            self.notes.append(f"{alert_id}: not sent, figures without a check: {stray}")
            return NOT_SENT
        return {
            "alert_id": alert_id,
            "rank": 0,
            "scope": scope,
            "store_ids": sorted(stores),
            "city": city,
            "lever": LEVER,
            "cause_code": cause_code,
            "headline": headline,
            "definition": definition,
            "cause": cause,
            "action": action,
            "rupees_at_stake_weekly": core["rupees"],
            "arithmetic": core["arithmetic"],
            "benchmark_basis": basis,
            "salesperson_ids": sorted(people),
            "checks": book.items,
            "follow_up": {
                "metric_label": metric_label,
                "kind": "conversion",
                "params": {"store_ids": sorted(stores), **self.cur, "day_type": "all"},
                "baseline_value": core["cur"]["value"],
                "target_value": core["bench"]["value"],
                "higher_is_better": True,
            },
        }

    # --------------------------------------------------- cause 1: someone left
    def salesperson_left(self, store: str):
        m, as_of = self.m, self.as_of
        if m.roster_min is None or as_of not in m.present_count.get(store, {}):
            return None  # no roster up to as-of for this store: cannot tell who has left
        best = None
        for p in m.store_sps.get(store, []):
            last = m.last_roster_date(p)
            if last is None:
                continue
            gone = (d(as_of) - d(last)).days
            if not (LEAVER_MIN_GONE_DAYS <= gone <= LEAVER_LOOKBACK_DAYS):
                continue
            before = win(max(add_days(last, -(BASE_DAYS - 1)), m.roster_min), last)
            if (d(before["end"]) - d(before["start"])).days + 1 < CUR_DAYS:
                continue
            if m.present_days(p, **before) < MIN_PRESENT_DAYS:
                continue
            rate = m.bills_per_present_day(p, **before)
            peer = m.compute("peer_median_bills_per_present_day", {
                "store_id": store, "exclude_salesperson_ids": [p], **before, "min_present_days": MIN_PRESENT_DAYS})
            if peer is None or peer <= 0 or rate < STRONG_RATIO * peer:
                continue
            if best is None or (rate, p) > (best[1], best[0]):
                best = (p, rate, last, before)
        if best is None:
            return None
        p, _, last, before = best
        test = win(add_days(last, 1), as_of)
        if not self.judged(store, self.cur, before, test):
            return None
        res = self.drop_test([store], test, before)
        if res is None or res[0] > Z_CAUSE or res[1] > -MIN_REL_DROP:
            return None

        name = m.sp_name[p]
        alert_id = f"{store}:{LEVER}:salesperson_left:{p}"
        book = CheckBook(m, alert_id)
        core = self.core_checks(book, [store], before, test, f"before {name} left", city_adjust=True)
        c_last = book.add("last_roster_date", f"Last day {name} appears on the roster", "last_roster_date",
                          {"salesperson_id": p, "as_of": as_of})
        c_rate = book.add("leaver_bills_per_present_day", f"Bills per day present, {name}, {span(before)}",
                          "bills_per_present_day", {"salesperson_id": p, **before})
        c_peer = book.add("peer_bills_per_present_day", f"Bills per day present, typical colleague at {store}, {span(before)}",
                          "peer_median_bills_per_present_day",
                          {"store_id": store, "exclude_salesperson_ids": [p], **before, "min_present_days": MIN_PRESENT_DAYS})
        headline = (f"{store} is converting {core['cur']['display']} of walk-ins ({core['r_cur']['display']}), down from "
                    f"{core['bench']['display']} ({core['r_bench']['display']}) before {name} left.") if core else ""
        cause = (f"{name} last appears on the roster on {c_last['display']}. {name} made {c_rate['display']} bills "
                 f"for each day present, against {c_peer['display']} for a typical colleague at {store}. "
                 f"Since then ({core['r_test']['display']}) the store has converted {core['test']['display']} of walk-ins."
                 + self.city_sentence(core)) if core else ""

        # action: full floor on the coming busy days, strongest sellers present
        state = self.store_rows[store]["state"]
        dates, when = self.upcoming(book, state)
        action = None
        active = self.active_staff(store)
        if dates and active:
            c_n = book.add("busy_day_staff_before", f"Salespeople on the floor on a typical busy day, {span(before)}",
                           "median_staff_present", {"store_id": store, **before, "day_type": "busy"})
            c_act = book.add("rostered_staff", f"Salespeople on the roster on {fmt_date(as_of)}", "rostered_staff",
                             {"store_id": store, "date": as_of})
            ranked = sorted(
                ((m.bills_per_present_day(x, **self.cur), x) for x in active
                 if m.present_days(x, **self.cur) >= 10), key=lambda t: (-t[0], t[1]))
            top = [x for _, x in ranked[:2]]
            for x in top:
                book.add(f"bills_per_present_day:{x}", f"Bills per day present, {m.sp_name[x]}, {span(self.cur)}",
                         "bills_per_present_day", {"salesperson_id": x, **self.cur})
            if c_n["value"] and top:
                n = min(c_n["value"], c_act["value"])
                top_names = join_names([m.sp_name[x] for x in top])
                everyone = "all " if n == c_act["value"] else ""
                floor = f"keep {everyone}{n} salespeople on the floor at {store}"
                if n == c_n["value"]:
                    floor += f", as on busy days before {name} left"
                text = (f"On {when}, {floor}, and make sure {top_names}, the strongest on bills per day now, "
                        f"work{'s' if len(top) == 1 else ''} those days.")
                moves = self.offs_on_busy_days(book, store, dates, skip=[])
                quiet = self.quiet_day(book, store) if moves else None
                if moves and quiet:
                    text += " " + " ".join(
                        f"Move the weekly off of {m.sp_name[x]} from {day} to {quiet}." for x, day in moves)
                action = {
                    "who": f"Store manager at {store}, with {top_names}",
                    "what": f"Keep {n} salespeople on the floor, with {top_names} working",
                    "when": when,
                    "text": text,
                }
        before_days = (d(before["end"]) - d(before["start"])).days + 1
        basis = f"Same store, the {before_days} days before {name} left ({span(before)})"
        weeks = "thirteen weeks" if before_days == BASE_DAYS else "weeks"
        return self.finish(alert_id=alert_id, scope="store", stores=[store], city=self.store_rows[store]["city"],
                           cause_code="salesperson_left", headline=headline, cause=cause, action=action, core=core,
                           basis=basis, people=[p], book=book, metric_label=f"Conversion at {store}",
                           definition=conversion_definition(f"at {store}", f"the same store's {weeks} before {name} left"))

    # ------------------------------------------------ cause 2: missed shifts
    def _missing(self, store: str, w: dict) -> list[str]:
        """Salespeople present on far fewer days than same-store colleagues in the window."""
        m = self.m
        people = m.full_window_peers(store, [], w["start"], w["end"])
        if len(people) < 4:
            return []
        out = []
        for p in people:
            mine = m.present_days(p, **w)
            med = m.compute("peer_median_present_days", {"store_id": store, "exclude_salesperson_ids": [p], **w})
            if med and mine <= MISSED_RATIO * med and med - mine >= MISSED_MIN_GAP:
                out.append(p)
        return out

    def missed_shifts(self, store: str):
        m, as_of, cur = self.m, self.as_of, self.cur
        if m.roster_min is None or cur["start"] < m.roster_min:
            return None
        flagged = self._missing(store, cur)
        if not flagged:
            return None
        # When did it start? Step back one week at a time (7-day blocks ending on as-of)
        # while at least one of these people is still having short weeks.
        onset = None
        for k in range(MISSED_MAX_WEEKS_BACK):
            week = win(add_days(as_of, -7 * k - 6), add_days(as_of, -7 * k))
            if week["start"] < m.roster_min:
                break
            med = m.compute("peer_median_present_days", {"store_id": store, "exclude_salesperson_ids": flagged, **week})
            short = [p for p in flagged if m.present_days(p, **week) <= min(SHORT_WEEK_DAYS, (med or 0) - 1)]
            if not short:
                break
            onset = week["start"]
        if onset is None:
            return None
        bench = win(add_days(onset, -BASE_DAYS), add_days(onset, -1))
        test = win(onset, as_of)
        if not self.judged(store, cur, bench, test):
            return None
        res = self.drop_test([store], test, bench)
        if res is None or res[0] > Z_CAUSE or res[1] > -MIN_REL_DROP:
            return None

        names = [m.sp_name[p] for p in flagged]
        who = join_names(names)
        alert_id = f"{store}:{LEVER}:missed_shifts"
        book = CheckBook(m, alert_id)
        core = self.core_checks(book, [store], bench, test, "before the missed shifts began", city_adjust=True)
        state = self.store_rows[store]["state"]
        c_days = book.add("days_in_window", f"Days, {span(cur)}", "day_count", {"state": state, **cur, "day_type": "all"})
        c_busy_days = book.add("busy_days_in_window", f"Weekend and festival days, {span(cur)}", "day_count",
                               {"state": state, **cur, "day_type": "busy"})
        c_med = book.add("peer_present_days", f"Days present, typical colleague at {store}, {span(cur)}",
                         "peer_median_present_days", {"store_id": store, "exclude_salesperson_ids": flagged, **cur, "day_type": "all"})
        c_med_busy = book.add("peer_present_busy_days", f"Busy days present, typical colleague at {store}, {span(cur)}",
                              "peer_median_present_days",
                              {"store_id": store, "exclude_salesperson_ids": flagged, **cur, "day_type": "busy"})
        pres, pres_busy = [], []
        for p in flagged:
            pres.append(book.add(f"present_days:{p}", f"Days present, {m.sp_name[p]}, {span(cur)}", "present_days",
                                 {"salesperson_id": p, **cur, "day_type": "all"}))
            pres_busy.append(book.add(f"present_busy_days:{p}", f"Busy days present, {m.sp_name[p]}, {span(cur)}",
                                      "present_days", {"salesperson_id": p, **cur, "day_type": "busy"}))
        c_busy = book.add("conv_busy_current", f"Conversion on weekend and festival days, {span(cur)}", "conversion",
                          {"store_ids": [store], **cur, "day_type": "busy"})
        c_norm = book.add("conv_other_current", f"Conversion on other days, {span(cur)}", "conversion",
                          {"store_ids": [store], **cur, "day_type": "normal"})
        book.add("staff_busy_current", f"Salespeople on the floor on a typical busy day, {span(cur)}",
                 "median_staff_present", {"store_id": store, **cur, "day_type": "busy"})
        book.add("staff_busy_benchmark", f"Salespeople on the floor on a typical busy day, {span(bench)}",
                 "median_staff_present", {"store_id": store, **bench, "day_type": "busy"})

        headline = (f"{store} is converting {core['cur']['display']} of walk-ins ({core['r_cur']['display']}), down from "
                    f"{core['bench']['display']} ({core['r_bench']['display']}) before {who} began missing shifts.") if core else ""
        parts = [f"{n} was on the floor on {c['display']}" for n, c in zip(names, pres)]
        cause = (f"Of the last {c_days['display']} days, {join_names(parts)}, against {c_med['display']} for a "
                 f"typical colleague at {store}.")
        busy_gap = c_med_busy["value"] and all(c["value"] <= 0.5 * c_med_busy["value"] for c in pres_busy)
        if busy_gap and c_busy["value"] is not None and c_norm["value"] is not None and c_busy["value"] < c_norm["value"]:
            parts = [f"{n} worked {c['display']}" for n, c in zip(names, pres_busy)]
            cause += (f" Of the {c_busy_days['display']} weekend and festival days, {join_names(parts)}; on those "
                      f"days {store} converted {c_busy['display']} of walk-ins, against {c_norm['display']} on other days.")
        cause += self.city_sentence(core)

        dates, when = self.upcoming(book, state)
        action = None
        if dates:
            busy_weekdays = {WEEKDAYS[d(x).weekday()] for x in dates}
            quiet = None
            offs = []
            for p in flagged:
                day = m.compute("usual_off_weekday", {"salesperson_id": p, **bench})
                if day is not None:
                    book.add(f"usual_off:{p}", f"Usual weekly off of {m.sp_name[p]}, {span(bench)}",
                             "usual_off_weekday", {"salesperson_id": p, **bench})
                if day is None or day in busy_weekdays:
                    # no weekday off on record: use the store's quietest weekday instead
                    quiet = quiet or self.quiet_day(book, store)
                    day = quiet
                offs.append(day)
            if all(offs):
                off_text = join_names([f"{n} on {day}" for n, day in zip(names, offs)])
                text = (f"Put {who} on the floor at {store} on {when}. Give the weekly off to {off_text} instead, "
                        f"as before the missed shifts began.")
                action = {
                    "who": f"Store manager at {store}, with {who}",
                    "what": f"Roster {who} on the floor on the busy days and move the weekly off to a weekday",
                    "when": when,
                    "text": text,
                }
        basis = f"Same store, 13 weeks before the missed shifts began ({span(bench)})"
        return self.finish(alert_id=alert_id, scope="store", stores=[store], city=self.store_rows[store]["city"],
                           cause_code="missed_shifts", headline=headline, cause=cause, action=action, core=core,
                           basis=basis, people=flagged, book=book, metric_label=f"Conversion at {store}",
                           definition=conversion_definition(
                               f"at {store}", "the same store's thirteen weeks before the missed shifts began"))

    # ------------------------- causes 3 and 4: a drop found by the store scan
    def scan_drop(self, store: str):
        """Thin floor on busy days if the roster shows it, otherwise a plain conversion fall."""
        m, cur, base = self.m, self.cur, self.base
        state = self.store_rows[store]["state"]
        thin = False
        if m.roster_min is not None and base["start"] >= m.roster_min:
            busy = m.compute("footfall_per_present_staff", {"store_id": store, **cur, "day_type": "busy"})
            other = m.compute("footfall_per_present_staff", {"store_id": store, **cur, "day_type": "normal"})
            res = self.drop_test([store], cur, base, "busy")
            thin = bool(busy and other and busy >= THIN_RATIO * other and res and res[0] <= Z_CAUSE and res[1] < 0)
        cause_code = "thin_floor_busy_days" if thin else "conversion_falling"
        alert_id = f"{store}:{LEVER}:{cause_code}"
        book = CheckBook(m, alert_id)
        core = self.core_checks(book, [store], base, cur, "previous 13 weeks", city_adjust=True)
        if core is None:
            return NOT_SENT
        f_cur = book.add("walkins_per_week_benchmark", f"Walk-ins a week, {span(base)}", "walkins_per_week",
                         {"store_ids": [store], **base})
        headline = (f"{store} is converting {core['cur']['display']} of walk-ins ({core['r_cur']['display']}), down from "
                    f"{core['bench']['display']} ({core['r_bench']['display']}).")
        dates, when = self.upcoming(book, state)
        action = None
        moves = self.offs_on_busy_days(book, store, dates, skip=[]) if dates else []
        quiet = self.quiet_day(book, store) if moves else None
        move_text = " ".join(f"Move the weekly off of {m.sp_name[x]} from {day} to {quiet}." for x, day in moves) if quiet else ""
        move_names = join_names([m.sp_name[x] for x, _ in moves])
        if thin:
            c_fb = book.add("walkins_per_staff_busy", f"Walk-ins per salesperson present, busy days, {span(cur)}",
                            "footfall_per_present_staff", {"store_id": store, **cur, "day_type": "busy"})
            c_fo = book.add("walkins_per_staff_other", f"Walk-ins per salesperson present, other days, {span(cur)}",
                            "footfall_per_present_staff", {"store_id": store, **cur, "day_type": "normal"})
            c_cb = book.add("conv_busy_current", f"Conversion on busy days, {span(cur)}", "conversion",
                            {"store_ids": [store], **cur, "day_type": "busy"})
            c_bb = book.add("conv_busy_benchmark", f"Conversion on busy days, {span(base)}", "conversion",
                            {"store_ids": [store], **base, "day_type": "busy"})
            book.add("z_busy", "Two-proportion z on busy days", "two_proportion_z",
                     {"store_ids": [store], **cur, "base_start": base["start"], "base_end": base["end"], "day_type": "busy"})
            c_now = book.add("staff_busy_current", f"Salespeople on the floor on a typical busy day, {span(cur)}",
                             "median_staff_present", {"store_id": store, **cur, "day_type": "busy"})
            c_was = book.add("staff_busy_benchmark", f"Salespeople on the floor on a typical busy day, {span(base)}",
                             "median_staff_present", {"store_id": store, **base, "day_type": "busy"})
            c_act = book.add("rostered_staff", f"Salespeople on the roster on {fmt_date(self.as_of)}", "rostered_staff",
                             {"store_id": store, "date": self.as_of})
            cause = (f"On weekends and festival days each salesperson on the floor faced {c_fb['display']} walk-ins, "
                     f"against {c_fo['display']} on other days, and conversion on those busy days fell to "
                     f"{c_cb['display']} from {c_bb['display']}.") + self.city_sentence(core)
            more = c_was["value"] and c_now["value"] and c_now["value"] < c_was["value"] <= c_act["value"]
            if dates and (more or move_text):
                bits = []
                if more:
                    bits.append(f"On {when}, put {c_was['display']} salespeople on the floor at {store}, "
                                f"up from {c_now['display']} on recent busy days.")
                if move_text:
                    bits.append(move_text)
                action = {
                    "who": f"Store manager at {store}" + (f", with {move_names}" if move_names else ""),
                    "what": "Put more salespeople on the floor on the busy days",
                    "when": when,
                    "text": " ".join(bits),
                }
        else:
            cause = (f"Walk-ins are {core['walk']['display']} a week now against {f_cur['display']} before, "
                     f"and fewer of them are buying. The roster shows nobody who left or missed shifts, and no thin "
                     f"floor on busy days.") + self.city_sentence(core)
            if dates and move_text:
                action = {
                    "who": f"Store manager at {store}, with {move_names}",
                    "what": "Move weekly offs away from the busy days so the full team is on the floor",
                    "when": when,
                    "text": f"{move_text} That puts the full team on the floor at {store} on {when}.",
                }
        basis = f"Same store, previous 13 weeks ({span(base)})"
        return self.finish(alert_id=alert_id, scope="store", stores=[store], city=self.store_rows[store]["city"],
                           cause_code=cause_code, headline=headline, cause=cause, action=action, core=core,
                           basis=basis, people=[x for x, _ in moves], book=book, metric_label=f"Conversion at {store}",
                           definition=conversion_definition(f"at {store}", "the same store's previous thirteen weeks"))

    # ------------------------------------------------- a whole city slowing
    def city_slowdown(self, city: str, stores: list[str]):
        m, cur, base = self.m, self.cur, self.base
        res = self.drop_test(stores, cur, base)
        if len(stores) < 2 or res is None or res[0] > Z_SCAN or res[1] > -MIN_REL_DROP:
            return None
        fell = [s for s in stores if (self.drop_test([s], cur, base) or (0, 0))[1] < 0]
        if len(fell) * 2 <= len(stores):
            return None
        alert_id = f"{city}:{LEVER}:market_slowdown"
        book = CheckBook(m, alert_id)
        core = self.core_checks(book, stores, base, cur, "previous 13 weeks")
        if core is None:
            return NOT_SENT
        for s in stores:
            book.add(f"conv_current:{s}", f"Conversion at {s}, {span(cur)}", "conversion",
                     {"store_ids": [s], **cur, "day_type": "all"})
            book.add(f"conv_benchmark:{s}", f"Conversion at {s}, {span(base)}", "conversion",
                     {"store_ids": [s], **base, "day_type": "all"})
        headline = (f"{city} as a whole is converting {core['cur']['display']} of walk-ins, down from "
                    f"{core['bench']['display']} in the previous weeks.")
        cause = (f"The fall is across the city, not one store: {join_names(fell)} all converted less than in the "
                 f"previous weeks. This is one market alert, not one per store.")
        state = self.store_rows[stores[0]]["state"]
        dates, when = self.upcoming(book, state)
        moves_txt, people = [], []
        if dates:
            for s in fell:
                sub = CheckBook(m, f"{alert_id}:{s}")
                moves = self.offs_on_busy_days(sub, s, dates, skip=[])
                quiet = self.quiet_day(sub, s) if moves else None
                if moves and quiet:
                    book.items.extend(sub.items)
                    people += [x for x, _ in moves]
                    moves_txt.append(f"at {s}, move the weekly off of " + join_names(
                        [f"{m.sp_name[x]} from {day}" for x, day in moves]) + f" to {quiet}")
        action = None
        if moves_txt:
            action = {
                "who": f"Store managers at {join_names(sorted(fell))}",
                "what": "Move weekly offs away from the busy days so every store has its full team on the floor",
                "when": when,
                "text": f"Before {when}: " + "; ".join(moves_txt) + ".",
            }
        return self.finish(alert_id=alert_id, scope="city", stores=stores, city=city, cause_code="market_slowdown",
                           headline=headline, cause=cause, action=action, core=core,
                           basis=f"Same city, previous 13 weeks ({span(base)})", people=people, book=book,
                           metric_label=f"Conversion across {city}",
                           definition=conversion_definition(
                               f"across the established stores of {city} taken together",
                               "the same stores' previous thirteen weeks"))

    # ------------------------------------- a whole city down against last year
    def last_year_window(self, state: str) -> tuple[dict, list[str]]:
        """The 28 days of last year that match the current window, and the festival dates used.

        In the festival season (up to 60 days after this year's Dussehra in the state calendar),
        the match is the same number of days after last year's Dussehra, because the festival
        moves by weeks between years (2 Oct 2025, 20 Oct 2026). Otherwise it is 364 days earlier,
        which keeps the weekday mix. Only calendar rows on or before as-of are used.
        """
        cal = self.m.data.calendar
        fest = sorted(dt for dt, st, f in zip(cal["date"], cal["state"], cal["festival"])
                      if st == state and f.strip() == DUSSEHRA and dt <= self.as_of)
        if fest and (d(self.as_of) - d(fest[-1])).days <= YOY_MAX_DAYS_AFTER_FESTIVAL:
            this = fest[-1]
            prev = [x for x in fest if 300 <= (d(this) - d(x)).days <= 430]
            if prev:
                end = add_days(prev[-1], (d(self.as_of) - d(this)).days)
                return win(add_days(end, -(CUR_DAYS - 1)), end), [this, prev[-1]]
        end = add_days(self.as_of, -364)
        return win(add_days(end, -(CUR_DAYS - 1)), end), []

    def city_vs_last_year(self, city: str, stores: list[str]):
        """One market note when a whole city converts clearly less than in the same weeks last year."""
        m, cur = self.m, self.cur
        state = self.store_rows[stores[0]]["state"]
        prev, fests = self.last_year_window(state)
        stores = [s for s in stores if self.judged(s, prev)]
        if len(stores) < 2:
            return None
        res = self.drop_test(stores, cur, prev)
        if res is None or res[0] > Z_SCAN or res[1] > -MIN_REL_DROP:
            return None
        fell = [s for s in stores if (self.drop_test([s], cur, prev) or (0, 0))[1] < 0]
        if len(fell) * 2 <= len(stores):
            return None
        note_id = f"{city}:{LEVER}:market_vs_last_year"
        book = CheckBook(m, note_id)
        sid = {"store_ids": stores}
        c_now = book.add("conv_current", f"Conversion across {city}, {span(cur)}", "conversion", {**sid, **cur, "day_type": "all"})
        c_prev = book.add("conv_last_year", f"Conversion across {city}, {span(prev)}", "conversion", {**sid, **prev, "day_type": "all"})
        r_now = book.add("range_current", "Dates of the current window", "date_range", dict(cur))
        r_prev = book.add("range_last_year", "Dates of the same weeks last year", "date_range", dict(prev))
        book.add("z", f"Two-proportion z, {span(cur)} against {span(prev)}", "two_proportion_z",
                 {**sid, **cur, "base_start": prev["start"], "base_end": prev["end"], "day_type": "all"})
        for s in stores:
            book.add(f"conv_current:{s}", f"Conversion at {s}, {span(cur)}", "conversion", {"store_ids": [s], **cur, "day_type": "all"})
            book.add(f"conv_last_year:{s}", f"Conversion at {s}, {span(prev)}", "conversion", {"store_ids": [s], **prev, "day_type": "all"})
        how = "364 days earlier, the same weekdays"
        if fests:
            f_now = book.add(f"festival:{fests[0]}", f"Festival on {fmt_date(fests[0])} in the {state} calendar", "festival_name",
                             {"state": state, "date": fests[0]})
            book.add(f"festival:{fests[1]}", f"Festival on {fmt_date(fests[1])} in the {state} calendar", "festival_name",
                     {"state": state, "date": fests[1]})
            how = f"the same number of days after {f_now['display']} last year, because the festival moves between years"
        headline = (f"{city} as a whole converted {c_now['display']} of walk-ins ({r_now['display']}), against "
                    f"{c_prev['display']} in the same weeks last year ({r_prev['display']}).")
        detail = (f"{join_names(fell)} all converted less than a year ago, so this is a market change, reported once for "
                  f"the city and not as a store alert. Each {city} store is judged only on what it lost beyond the other "
                  f"{city} stores. Same weeks last year means {how}.")
        if not book.usable() or numbers_not_in_checks([headline, detail], book.items):
            self.notes.append(f"{note_id}: not shown, a figure has no check")
            return None
        return {"note_id": note_id, "city": city, "store_ids": sorted(stores), "headline": headline,
                "detail": detail, "checks": book.items}

    def market_notes(self) -> list[dict]:
        cities: dict[str, list[str]] = {}
        for s in sorted(self.established):
            if self.judged(s, self.cur):
                cities.setdefault(self.store_rows[s]["city"], []).append(s)
        return [n for c in sorted(cities) if (n := self.city_vs_last_year(c, cities[c])) is not None]

    # ------------------------------------------------------------- run all
    def run(self) -> list[dict]:
        """All candidate alerts for the lever, before the weekly cap. Deterministic order."""
        cur, base = self.cur, self.base
        judged = [s for s in sorted(self.established) if self.judged(s, cur, base)]
        cities: dict[str, list[str]] = {}
        for s in judged:
            cities.setdefault(self.store_rows[s]["city"], []).append(s)

        alerts = []
        slow: dict[str, float] = {}
        for city in sorted(cities):
            a = self.city_slowdown(city, cities[city])
            if a is not None:  # the city fell, whether or not the alert could be sent
                slow[city] = self.drop_test(cities[city], cur, base)[1]
                if a != NOT_SENT:
                    alerts.append(a)

        for s in judged:
            city = self.store_rows[s]["city"]
            scan = self.drop_test([s], cur, base)
            if city in slow and not (scan and scan[1] <= slow[city] - CITY_BEYOND):
                self.notes.append(f"{s}: covered by the {city} market alert")
                continue
            # first cause that holds; a cause that holds but cannot be sent is not replaced by another
            a = self.salesperson_left(s)
            if a is None:
                a = self.missed_shifts(s)
            if a is None and scan and scan[0] <= Z_SCAN and scan[1] <= -MIN_REL_DROP:
                a = self.scan_drop(s)
            if a is not None and a != NOT_SENT:
                alerts.append(a)
        return alerts
