"""Every figure the engine shows is computed here, by `Metrics.compute(kind, params)`.

The recipe for each kind is written out in docs/CHECKS.md so that a reviewer can
recompute it from the raw CSVs without reading this file.
"""
from __future__ import annotations

import math
from datetime import date, timedelta

from .load import Data

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def d(s: str) -> date:
    return date.fromisoformat(s)


def iso(x: date) -> str:
    return x.isoformat()


def add_days(s: str, n: int) -> str:
    return iso(d(s) + timedelta(days=n))


def date_range(start: str, end: str) -> list[str]:
    a, b = d(start), d(end)
    return [iso(a + timedelta(days=i)) for i in range((b - a).days + 1)] if b >= a else []


def rnd(x: float, n: int = 0) -> float:
    """Round half up (not banker's rounding) to n decimals."""
    m = 10**n
    return math.floor(x * m + 0.5) / m


def median(xs: list[float]) -> float:
    s = sorted(xs)
    k = len(s)
    return s[k // 2] if k % 2 else (s[k // 2 - 1] + s[k // 2]) / 2


class Metrics:
    def __init__(self, data: Data):
        self.data = data
        self.as_of = data.as_of
        self.state = dict(zip(data.stores["store_id"], data.stores["state"]))

        # store -> date -> [footfall or None, bills, value]
        self.day: dict[str, dict[str, list]] = {s: {} for s in data.stores["store_id"]}
        for dt, s, f in zip(data.footfall["date"], data.footfall["store_id"], data.footfall["footfall"]):
            if s not in self.day:
                continue
            row = self.day[s].setdefault(dt, [None, 0, 0.0])
            if f == f:  # not NaN
                row[0] = (row[0] or 0.0) + float(f)
        for dt, s, v in zip(data.bills["bill_date"], data.bills["store_id"], data.bills["value"]):
            if s not in self.day:
                continue
            row = self.day[s].setdefault(dt, [None, 0, 0.0])
            row[1] += 1
            row[2] += float(v)

        # calendar: (state, date) -> busy flag from festival / wedding date
        self.special: set[tuple[str, str]] = set()
        for dt, st, fest, wed in zip(
            data.calendar["date"], data.calendar["state"], data.calendar["festival"], data.calendar["is_wedding_date"]
        ):
            if fest.strip() != "" or wed.strip() == "1":
                self.special.add((st, dt))

        # roster: salesperson -> date -> status ; store -> date -> number Present
        self.roster: dict[str, dict[str, str]] = {}
        self.present_count: dict[str, dict[str, int]] = {}
        self.roster_store: dict[str, str] = {}
        for dt, s, p, status in zip(
            data.roster["date"], data.roster["store_id"], data.roster["salesperson_id"], data.roster["status"]
        ):
            self.roster.setdefault(p, {})[dt] = status
            self.roster_store[p] = s
            pc = self.present_count.setdefault(s, {})
            pc.setdefault(dt, 0)
            if status == "Present":
                pc[dt] += 1
        self.roster_min = str(data.roster["date"].min()) if len(data.roster) else None

        self.sp_store = dict(zip(data.salespeople["salesperson_id"], data.salespeople["store_id"]))
        self.sp_name = dict(zip(data.salespeople["salesperson_id"], data.salespeople["name"]))
        self.store_sps: dict[str, list[str]] = {}
        for p, s in self.sp_store.items():
            self.store_sps.setdefault(s, []).append(p)
        for s in self.store_sps:
            self.store_sps[s].sort()

        # salesperson -> date -> bills
        self.sp_bills: dict[str, dict[str, int]] = {}
        for dt, p in zip(data.bills["bill_date"], data.bills["salesperson_id"]):
            m = self.sp_bills.setdefault(p, {})
            m[dt] = m.get(dt, 0) + 1

    # ---------- day rules ----------
    def is_busy(self, state: str, dt: str) -> bool:
        """Busy day = Saturday, Sunday, or a festival / wedding date in that state's calendar."""
        return d(dt).weekday() >= 5 or (state, dt) in self.special

    def type_ok(self, state: str, dt: str, day_type: str) -> bool:
        if day_type == "all":
            return True
        busy = self.is_busy(state, dt)
        return busy if day_type == "busy" else not busy

    @staticmethod
    def is_valid(row: list) -> bool:
        """A store-day is valid when footfall > 0 and bills <= footfall."""
        f, b, _ = row
        return f is not None and f > 0 and b <= f

    def store_days(self, store_ids, start, end, day_type="all"):
        """Yield (store, date, footfall, bills, value, valid) for store-days in the window."""
        for s in sorted(store_ids):
            days = self.day.get(s, {})
            st = self.state.get(s, "")
            for dt in sorted(days):
                if start <= dt <= end and self.type_ok(st, dt, day_type):
                    row = days[dt]
                    yield s, dt, row[0], row[1], row[2], self.is_valid(row)

    def parts(self, store_ids, start, end, day_type="all"):
        """(bills, footfall, value, valid days, invalid days) over the window."""
        b = f = v = 0.0
        nv = ni = 0
        for _, _, ff, bb, val, ok in self.store_days(store_ids, start, end, day_type):
            if ok:
                b += bb
                f += ff
                v += val
                nv += 1
            else:
                ni += 1
        return b, f, v, nv, ni

    # ---------- people ----------
    def present_days(self, sp, start, end, day_type="all"):
        st = self.state.get(self.sp_store.get(sp, ""), "")
        return sum(
            1
            for dt, status in self.roster.get(sp, {}).items()
            if start <= dt <= end and status == "Present" and self.type_ok(st, dt, day_type)
        )

    def rostered_every_day(self, sp, start, end):
        r = self.roster.get(sp, {})
        return all(dt in r for dt in date_range(start, end))

    def sp_bill_count(self, sp, start, end):
        return sum(n for dt, n in self.sp_bills.get(sp, {}).items() if start <= dt <= end)

    def bills_per_present_day(self, sp, start, end):
        p = self.present_days(sp, start, end)
        return self.sp_bill_count(sp, start, end) / p if p else None

    def last_roster_date(self, sp):
        r = self.roster.get(sp)
        return max(r) if r else None

    def full_window_peers(self, store, exclude, start, end):
        return [
            p
            for p in self.store_sps.get(store, [])
            if p not in exclude and self.rostered_every_day(p, start, end)
        ]

    # ---------- the check kinds ----------
    def compute(self, kind: str, p: dict):
        if kind in ("bills_count", "footfall_sum", "conversion", "avg_bill_value", "valid_days"):
            b, f, v, nv, ni = self.parts(p["store_ids"], p["start"], p["end"], p.get("day_type", "all"))
            if kind == "bills_count":
                return int(b)
            if kind == "footfall_sum":
                return int(f)
            if kind == "valid_days":
                return nv
            if kind == "conversion":
                return rnd(b / f, 4) if f else None
            return rnd(v / b, 2) if b else None
        if kind in ("invalid_days", "bills_on_invalid_days"):
            rule = p.get("rule", "any")
            n = bills = 0
            for _, _, ff, bb, _, ok in self.store_days(p["store_ids"], p["start"], p["end"]):
                if ok:
                    continue
                reason = "footfall_zero" if (ff is None or ff <= 0) else "bills_exceed_footfall"
                if rule in ("any", reason):
                    n += 1
                    bills += bb
            return n if kind == "invalid_days" else int(bills)
        if kind == "walkins_per_week":
            total = 0.0
            for s in sorted(p["store_ids"]):
                _, f, _, nv, _ = self.parts([s], p["start"], p["end"])
                if nv:
                    total += f / nv * 7
            return rnd(total, 1)
        if kind == "two_proportion_z":
            dt = p.get("day_type", "all")
            b1, n1, *_ = self.parts(p["store_ids"], p["start"], p["end"], dt)
            b0, n0, *_ = self.parts(p["store_ids"], p["base_start"], p["base_end"], dt)
            z = z_score(b1, n1, b0, n0)
            return rnd(z, 2) if z is not None else None
        if kind == "day_count":
            return sum(1 for dt in date_range(p["start"], p["end"]) if self.type_ok(p["state"], dt, p.get("day_type", "all")))
        if kind == "present_days":
            return self.present_days(p["salesperson_id"], p["start"], p["end"], p.get("day_type", "all"))
        if kind == "peer_median_present_days":
            peers = self.full_window_peers(p["store_id"], p["exclude_salesperson_ids"], p["start"], p["end"])
            vals = [self.present_days(x, p["start"], p["end"], p.get("day_type", "all")) for x in peers]
            return rnd(median(vals), 1) if vals else None
        if kind == "last_roster_date":
            return self.last_roster_date(p["salesperson_id"])
        if kind == "bills_per_present_day":
            v = self.bills_per_present_day(p["salesperson_id"], p["start"], p["end"])
            return rnd(v, 2) if v is not None else None
        if kind == "peer_median_bills_per_present_day":
            vals = []
            for x in self.store_sps.get(p["store_id"], []):
                if x in p["exclude_salesperson_ids"]:
                    continue
                if self.present_days(x, p["start"], p["end"]) >= p["min_present_days"]:
                    vals.append(self.bills_per_present_day(x, p["start"], p["end"]))
            return rnd(median(vals), 2) if vals else None
        if kind == "median_staff_present":
            st = self.state.get(p["store_id"], "")
            pc = self.present_count.get(p["store_id"], {})
            vals = [n for dt, n in pc.items() if p["start"] <= dt <= p["end"] and self.type_ok(st, dt, p.get("day_type", "all"))]
            return int(rnd(median(vals), 0)) if vals else None
        if kind == "footfall_per_present_staff":
            pc = self.present_count.get(p["store_id"], {})
            f = n = 0.0
            for _, dt, ff, _, _, ok in self.store_days([p["store_id"]], p["start"], p["end"], p.get("day_type", "all")):
                if ok and dt in pc:
                    f += ff
                    n += pc[dt]
            return rnd(f / n, 1) if n else None
        if kind == "usual_off_weekday":
            counts = [0] * 7
            for dt, status in self.roster.get(p["salesperson_id"], {}).items():
                if p["start"] <= dt <= p["end"] and status == "Off":
                    counts[d(dt).weekday()] += 1
            return WEEKDAYS[counts.index(max(counts))] if max(counts) > 0 else None
        if kind == "quietest_weekday":
            tot = [0.0] * 7
            cnt = [0] * 7
            for _, dt, ff, _, _, ok in self.store_days([p["store_id"]], p["start"], p["end"]):
                if ok:
                    tot[d(dt).weekday()] += ff
                    cnt[d(dt).weekday()] += 1
            means = [(tot[i] / cnt[i], i) for i in range(7) if cnt[i]]
            return WEEKDAYS[min(means)[1]] if means else None
        if kind == "upcoming_busy_dates":
            days = [dt for dt in date_range(p["start"], p["end"]) if self.is_busy(p["state"], dt)]
            return ", ".join(days)
        raise KeyError(f"unknown check kind: {kind}")


def z_score(b1, n1, b0, n0):
    """Two-proportion z: current (b1 of n1) against benchmark (b0 of n0). Negative = current is lower."""
    if not n1 or not n0:
        return None
    pooled = (b1 + b0) / (n1 + n0)
    if pooled <= 0 or pooled >= 1:
        return None
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n0))
    return (b1 / n1 - b0 / n0) / se


def rupees_at_stake(bench_conv: float, cur_conv: float, walkins: float, abv: float) -> int:
    """Uses the figures exactly as displayed, so the worked line multiplies out by hand.

    conversion to 0.1 of a percentage point, walk-ins to a whole number, bill value to
    a whole rupee; result rounded half up to the nearest Rs 100.
    """
    gap_tenths = int(rnd(bench_conv * 1000)) - int(rnd(cur_conv * 1000))
    raw = gap_tenths * int(rnd(walkins)) * int(rnd(abv)) / 1000
    return int(rnd(raw / 100) * 100)
