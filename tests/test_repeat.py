"""Lever 3, "more repeat": tests on a small made-up data pack built here. No real data is needed.

The story planted in the pack (two established stores in one city, one new store):

- RRR-01: Tara S. brings customers back four times as often as her colleagues, in every
  month. Expected: a `role_model` alert naming her, cards for the two colleagues still on
  the roster with her as the named peer. Usha T. left in August 2026: no card, never a peer.
- RRR-02: Omar L.'s customers come back a fifth as often as his colleagues'. Expected: a
  `customers_not_returning` alert, with a colleague from the same store named as coach.
  Leela N. joined in January 2026. Customers first billed early in the data return three
  times as often for everybody (existing regulars), so her raw rate is far below the
  veterans' raw rate. Over the SAME first-bill months she is level: she must not be flagged.
- RRR-03 opened on 10 Oct 2026: not judged and not a benchmark.
- Customer id C99999999 is on a bill every fifth day at two stores: a placeholder, excluded.
- Bills 3 days and 200 days after the first bill exist and must not count as a return.
"""
from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from engine import repeat
from engine.cards import MAX_CARD_WORDS, select_cards, word_count
from engine.checks import conv_tenths, numbers_not_in_checks
from engine.load import load
from engine.metrics import Metrics
from engine.rank import has_who_what_when

START = date(2025, 1, 1)
END = date(2026, 10, 31)
AS_OF = END.isoformat()
EARLY_END = date(2025, 6, 30)  # first bills up to here return three times as often (existing regulars)
PLACEHOLDER = "C99999999"

# salesperson -> (store, name, first day, last day, returns per 100 customers after EARLY_END)
PEOPLE = {
    "SP2001": ("RRR-01", "Tara S.", START, END, 20),
    "SP2002": ("RRR-01", "Anil P.", START, END, 5),
    "SP2003": ("RRR-01", "Bela Q.", START, END, 5),
    "SP2004": ("RRR-01", "Usha T.", START, date(2026, 8, 15), 5),
    "SP2005": ("RRR-02", "Omar L.", START, END, 1),
    "SP2006": ("RRR-02", "Dipa M.", START, END, 5),
    "SP2007": ("RRR-02", "Eshan O.", START, END, 5),
    "SP2008": ("RRR-02", "Leela N.", date(2026, 1, 1), END, 5),
    "SP2009": ("RRR-03", "Farid U.", date(2026, 10, 10), END, 5),
}
STORES = [
    ("RRR-01", "Rho", "Bihar", "A", "2019-01-01", "AM-01"),
    ("RRR-02", "Rho", "Bihar", "A", "2018-01-01", "AM-01"),
    ("RRR-03", "Rho", "Bihar", "B", "2026-10-10", "AM-01"),
]


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def make_pack(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    bills: list[list] = []  # bill_date, store, salesperson, customer, has_sherwani
    counter = {sp: 0 for sp in PEOPLE}
    cust_no = 0
    day = START
    while day <= END:
        for sp, (store, _name, first, last, late_rate) in PEOPLE.items():
            if not first <= day <= last:
                continue
            for _ in range(2):  # two new customers a day each
                counter[sp] += 1
                cust_no += 1
                i, cid = counter[sp], f"C{cust_no:08d}"
                bills.append([day, store, sp, cid, i % 9 == 0])
                rate = late_rate * 3 if day <= EARLY_END else late_rate
                other = "RRR-02" if store == "RRR-01" else "RRR-01"
                seller = "SP2005" if other == "RRR-02" else "SP2002"
                if (i * 37) % 100 < rate:  # a real return, 60 days later, at the other store
                    bills.append([day + timedelta(days=60), other, seller, cid, False])
                elif i % 7 == 3:  # picked up an alteration 3 days later: not a return
                    bills.append([day + timedelta(days=3), store, sp, cid, False])
                elif i % 11 == 5:  # back after 200 days: outside the window, not a return
                    bills.append([day + timedelta(days=200), store, sp, cid, False])
        if (day - START).days % 5 == 0:  # the placeholder number, keyed in at two stores
            store = "RRR-01" if (day - START).days % 10 == 0 else "RRR-02"
            bills.append([day, store, "SP2002" if store == "RRR-01" else "SP2006", PLACEHOLDER, False])
        day += timedelta(days=1)
    bills = sorted((b for b in bills if b[0] <= END), key=lambda b: b[0])

    bill_rows, line_rows = [], []
    for n, (dt, store, sp, cid, sherwani) in enumerate(bills, start=1):
        bid = f"B{n:07d}"
        bill_rows.append([bid, dt.isoformat(), store, sp, cid])
        line_rows.append([bid, "KUR-01-M", 1, 4000, 4000])
        if sherwani:
            line_rows.append([bid, "SHW-01-M", 1, 20000, 20000])
        line_rows.append([bid, "PKG-BAG", 1, 0, 0])

    footfall_rows, roster_rows, cal_rows = [], [], []
    day = START
    while day <= date(2026, 11, 30):
        cal_rows.append([day.isoformat(), "Bihar", "", 0])
        if day <= END:
            for store, *_rest in STORES:
                if day.isoformat() >= _rest[3]:
                    footfall_rows.append([day.isoformat(), store, 200])
            if day >= date(2026, 5, 1):
                for sp, (store, _name, first, last, _r) in PEOPLE.items():
                    if first <= day <= last:
                        roster_rows.append([day.isoformat(), store, sp, "Present"])
        day += timedelta(days=1)

    _write(folder / "stores.csv", ["store_id", "city", "state", "zone", "tier", "size_sqft", "stock_capacity_units",
                                   "opened_on", "area_manager_id"],
           [[s, c, st, "East", t, "2000", "500", o, am] for s, c, st, t, o, am in STORES])
    _write(folder / "area_managers.csv", ["area_manager_id", "name", "city", "stores", "max_alerts_per_week"],
           [["AM-01", "Manager One", "Rho", "RRR-01, RRR-02, RRR-03", 5]])
    _write(folder / "salespeople.csv", ["salesperson_id", "store_id", "name", "join_date"],
           [[sp, v[0], v[1], v[2].isoformat()] for sp, v in PEOPLE.items()])
    _write(folder / "roster_daily.csv", ["date", "store_id", "salesperson_id", "status"], roster_rows)
    _write(folder / "footfall_daily.csv", ["date", "store_id", "footfall"], footfall_rows)
    _write(folder / "bills.csv", ["bill_id", "bill_date", "store_id", "salesperson_id", "customer_id"], bill_rows)
    _write(folder / "bill_lines.csv", ["bill_id", "sku_id", "qty", "mrp", "selling_price"], line_rows)
    _write(folder / "items.csv", ["sku_id", "style_id", "style_name", "category", "size", "mrp", "cost_price",
                                  "launch_date", "is_core_style", "is_packaging"], [
        ["KUR-01-M", "KUR-01", "Test Kurta", "Kurta Set", "M", 4000, 1500, "2024-01-01", 1, 0],
        ["SHW-01-M", "SHW-01", "Test Sherwani", "Sherwani", "M", 20000, 8000, "2024-01-01", 1, 0],
        ["PKG-BAG", "PKG", "Carry Bag", "Packaging", "FS", 0, 0, "2024-01-01", 1, 1],
    ])
    _write(folder / "calendar.csv", ["date", "state", "festival", "is_wedding_date"], cal_rows)
    return folder


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    return make_pack(tmp_path_factory.mktemp("repeat_pack"))


@pytest.fixture(scope="module")
def m(folder):
    return Metrics(load(folder, AS_OF))


@pytest.fixture(scope="module")
def alerts(m):
    found, _notes = repeat.detect(m)
    return {a["alert_id"]: a for a in found}


@pytest.fixture(scope="module")
def cards(m):
    return {c["salesperson_id"]: c for c in repeat.card_candidates(m)}


# ---------------------------------------------------------------- an independent recomputation from the CSV
def by_hand(folder: Path) -> dict:
    """customer -> (first date, store, salesperson, returned), straight from bills.csv with the csv module."""
    with open(folder / "bills.csv", encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["customer_id"] != PLACEHOLDER and r["bill_date"] <= AS_OF]
    rows.sort(key=lambda r: (r["customer_id"], r["bill_date"], r["bill_id"]))
    out: dict = {}
    for r in rows:
        dt = date.fromisoformat(r["bill_date"])
        if r["customer_id"] not in out:
            out[r["customer_id"]] = [dt, r["store_id"], r["salesperson_id"], False]
        elif 30 <= (dt - out[r["customer_id"]][0]).days <= 180:
            out[r["customer_id"]][3] = True
    cutoff = END - timedelta(days=180)
    return {c: v for c, v in out.items() if v[0] <= cutoff}


def hand_rate(cohort: dict, sp: str) -> tuple[int, int]:
    mine = [v for v in cohort.values() if v[2] == sp]
    return len(mine), sum(v[3] for v in mine)


def hand_fair(cohort: dict, sp: str, peers: list[str]) -> float:
    months: dict = {}
    for dt, _store, who, back in cohort.values():
        row = months.setdefault(dt.strftime("%Y-%m"), [0, 0, 0])
        if who == sp:
            row[0] += 1
        elif who in peers:
            row[1] += 1
            row[2] += back
    n = sum(r[0] for r in months.values())
    return sum(r[0] * r[2] / r[1] for r in months.values() if r[0]) / n


def check(item: dict, slug: str) -> dict:
    return next(c for c in item["checks"] if c["id"].endswith(":" + slug))


# ---------------------------------------------------------------- the placeholder
def test_placeholder_is_found_by_rule_and_reported_not_alerted(m, folder):
    issues = repeat.data_issues(m, {})
    assert [i["issue_id"] for i in issues] == [f"ALL:placeholder_customer_id:{PLACEHOLDER}"]
    issue = issues[0]
    assert issue["store_id"] == "ALL" and issue["kind"] == "placeholder_customer_id"
    with open(folder / "bills.csv", encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["customer_id"] == PLACEHOLDER]
    assert check(issue, "bills")["value"] == len(rows) >= repeat.PLACEHOLDER_MIN_BILLS
    assert check(issue, "stores")["value"] == 2
    assert check(issue, "bills")["display"] in issue["detail"]
    assert "conversion" in issue["handling"] and "repeat" in issue["handling"]
    assert PLACEHOLDER not in set(repeat.core_of(m).cust["customer_id"])


def test_a_real_frequent_customer_is_not_a_placeholder(m):
    per = repeat.core_of(m).bills.groupby("customer_id").size()
    assert per.max() == 2  # everyone left in has at most two bills here


# ---------------------------------------------------------------- the one definition
def test_return_rate_matches_a_recomputation_by_hand(m, folder, alerts):
    cohort = by_hand(folder)
    a = alerts["RRR-01:more_repeat:role_model:SP2001"]
    n, back = hand_rate(cohort, "SP2001")
    assert check(a, "customers")["value"] == n
    assert check(a, "returned")["value"] == back
    assert check(a, "return_rate")["value"] == pytest.approx(back / n, abs=5e-5)
    fair = hand_fair(cohort, "SP2001", ["SP2002", "SP2003", "SP2004"])
    assert check(a, "fair_rate")["value"] == pytest.approx(fair, abs=5e-5)
    assert check(a, "customers")["params"]["first_bill_to"] == "2026-05-04"  # as-of minus 180 days


def test_bills_3_and_200_days_later_are_not_returns(m, folder):
    cohort = by_hand(folder)
    n, back = hand_rate(cohort, "SP2002")
    p = {"store_ids": ["RRR-01"], "salesperson_ids": ["SP2002"], "first_bill_to": "2026-05-04",
         "min_gap_days": 30, "max_gap_days": 180}
    assert m.compute("repeat_returned", p) == back
    # with the window opened to 1..400 days, the alteration pick-ups and late visits count too
    wide = m.compute("repeat_returned", {**p, "min_gap_days": 1, "max_gap_days": 400})
    assert wide > back * 2


# ---------------------------------------------------------------- what is detected
def test_role_model_and_low_performer_are_found_and_nobody_else(alerts):
    assert sorted(alerts) == [
        "RRR-01:more_repeat:role_model:SP2001",
        "RRR-02:more_repeat:customers_not_returning:SP2005",
        "RRR-02:more_repeat:store_customers_not_returning",
    ]
    role = alerts["RRR-01:more_repeat:role_model:SP2001"]
    assert role["lever"] == "more_repeat" and role["cause_code"] == "role_model" and role["rank"] == 0
    assert "Tara S." in role["headline"] and "Tara S." in role["action"]["text"]
    assert role["salesperson_ids"] == ["SP2001", "SP2002", "SP2003"]  # the two she coaches are on the roster
    assert "Usha T." not in role["action"]["text"]  # left in August
    low = alerts["RRR-02:more_repeat:customers_not_returning:SP2005"]
    assert "Omar L." in low["headline"]
    assert low["salesperson_ids"][0] == "SP2005" and len(low["salesperson_ids"]) == 2
    assert low["salesperson_ids"][1] in ("SP2006", "SP2007")  # the coach is a same-store colleague


def test_late_joiner_is_not_flagged_for_having_joined_late(m, folder, alerts):
    cohort = by_hand(folder)
    n, back = hand_rate(cohort, "SP2008")
    n_vet, back_vet = hand_rate(cohort, "SP2006")
    assert n >= repeat.MIN_CUSTOMERS
    assert back / n < repeat.LOW_RATIO * back_vet / n_vet  # on raw rates she looks bad ...
    assert not any("SP2008" in a["salesperson_ids"] for a in alerts.values())  # ... over the same months she is not
    peers = {"peer_store_ids": ["RRR-02"], "peer_salesperson_ids": ["SP2006", "SP2007"]}
    p = {"store_ids": ["RRR-02"], "salesperson_ids": ["SP2008"], **peers, "first_bill_to": "2026-05-04",
         "min_gap_days": 30, "max_gap_days": 180}
    assert abs(m.compute("repeat_z", p)) < 1.0
    assert m.compute("repeat_fair_rate", p) == pytest.approx(back / n, abs=0.01)


def test_new_store_is_not_judged_and_not_a_benchmark(m, alerts, cards):
    assert not any(a["store_ids"] == ["RRR-03"] for a in alerts.values())
    assert "SP2009" not in cards
    store = alerts["RRR-02:more_repeat:store_customers_not_returning"]
    assert check(store, "fair_rate")["params"]["peer_store_ids"] == ["RRR-01"]


# ---------------------------------------------------------------- the sending rules
def test_every_number_in_the_text_is_a_check_and_the_action_names_who_what_when(alerts):
    for a in alerts.values():
        texts = [a["headline"], a["cause"], a["action"]["text"], a["arithmetic"]["worked"]]
        assert numbers_not_in_checks(texts, a["checks"]) == []
        assert has_who_what_when(a["action"]) and a["action"]["when"] == "Today"
        assert "30 to 180 days" in a["definition"] and PLACEHOLDER in a["definition"]
        assert "same first-bill months" in a["definition"]
        ids = [c["id"] for c in a["checks"]]
        assert len(ids) == len(set(ids)) and set(a["arithmetic"]["input_check_ids"]) <= set(ids)


def test_every_check_recomputes_from_its_params(m, alerts, cards):
    items = list(alerts.values()) + list(cards.values()) + repeat.data_issues(m, {})
    n = 0
    for item in items:
        for c in item["checks"]:
            assert m.compute(c["kind"], c["params"]) == c["value"], c["id"]
            n += 1
    assert n > 50


def test_rupees_multiply_out_from_the_displayed_figures(alerts):
    for a in alerts.values():
        by_id = {c["id"]: c for c in a["checks"]}
        high, low, new, value = (by_id[i] for i in a["arithmetic"]["input_check_ids"])
        raw = (conv_tenths(high["value"]) - conv_tenths(low["value"])) / 1000 * float(new["display"]) \
            * int(value["display"].replace("₹", "").replace(",", ""))
        assert a["rupees_at_stake_weekly"] == int(raw / 100 + 0.5) * 100 > 0
        assert a["arithmetic"]["worked"].endswith(f"= {check(a, 'rupees_at_stake')['display']} a week")


def test_call_list_is_small_and_counts_customers_who_have_not_been_back(m, folder, alerts):
    a = alerts["RRR-02:more_repeat:customers_not_returning:SP2005"]
    c = check(a, "call_list")
    assert 0 < c["value"] <= repeat.MAX_CALLS and f"the {c['display']} customers" in a["action"]["text"]
    p = c["params"]
    with open(folder / "bills.csv", encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["customer_id"] != PLACEHOLDER]
    per: dict = {}
    for r in sorted(rows, key=lambda r: (r["bill_date"], r["bill_id"])):
        per.setdefault(r["customer_id"], []).append(r)
    want = sum(1 for bills in per.values() if len(bills) == 1 and bills[0]["salesperson_id"] == "SP2005"
               and p["first_from"] <= bills[0]["bill_date"] <= p["first_to"])
    assert c["value"] == want
    assert p["first_to"] == "2026-10-01"  # 30 days before as-of


def test_follow_up_is_measurable_on_the_seven_days_after(folder, alerts):
    # the follow-up replaces start and end with a 7-day window; the kind must work on one
    later = Metrics(load(folder, AS_OF))
    for a in alerts.values():
        fu = a["follow_up"]
        assert fu["kind"] == "repeat_weekly_returns_per_100" and fu["higher_is_better"] is True
        assert fu["baseline_value"] < fu["target_value"]
        week = {**fu["params"], "start": "2026-10-25", "end": "2026-10-31"}
        value = later.compute(fu["kind"], week)
        assert isinstance(value, float) and value >= 0


# ---------------------------------------------------------------- cards
def test_cards_go_to_people_on_the_roster_with_a_named_same_store_peer(m, cards):
    assert sorted(cards) == ["SP2002", "SP2003", "SP2005"]  # not the role model, not the leaver, not the late joiner
    for sp, c in cards.items():
        assert c["lever"] == "more_repeat" and c["store_id"] == m.sp_store[sp]
        assert m.sp_store[c["peer"]["salesperson_id"]] == c["store_id"] and c["peer"]["salesperson_id"] != sp
        assert c["peer"]["salesperson_id"] != "SP2004"
        assert word_count(c["text"]) <= MAX_CARD_WORDS
        assert c["text"].startswith(c["salesperson_name"].split()[0] + ",")
        assert c["peer"]["name"] in c["text"] and "Today" in c["action"]
        assert numbers_not_in_checks([c["text"]], c["checks"]) == []
        assert "same first-bill months" in c["definition"]
    assert cards["SP2002"]["peer"]["salesperson_id"] == "SP2001"
    assert len(select_cards(list(cards.values()))) == 3


# ---------------------------------------------------------------- determinism and quiet data
def test_two_runs_give_identical_output(folder):
    def run():
        mm = Metrics(load(folder, AS_OF))
        return json.dumps([repeat.detect(mm), repeat.card_candidates(mm), repeat.data_issues(mm, {})],
                          ensure_ascii=False, sort_keys=True)
    assert run() == run()


def test_nothing_is_raised_where_nobody_returns(pack):
    """The shared pack gives every bill a new customer: no returns, so nothing to compare and no placeholder."""
    mm = Metrics(load(pack, "2026-10-31"))
    found, _notes = repeat.detect(mm)
    assert found == [] and repeat.card_candidates(mm) == [] and repeat.data_issues(mm, {}) == []
