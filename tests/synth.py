"""A small made-up data pack, written to a folder in the same CSV layout as the real one.

No real data is needed to run the tests. The story planted in it:

- AAA-01: from 5 Sep 2026 two salespeople are Off every Saturday and Sunday, and the
  store converts far fewer weekend walk-ins. Expected: one `missed_shifts` alert.
- AAA-02: steady. One day has more bills than walk-ins (a data issue, still judged).
- AAA-03: steady, but the door counter reads 0 on 10 days of October while bills
  continue. Expected: a data issue, not judged, no alert.
- BBB-01: conversion falls in the last 28 days with nothing in the roster to explain
  it and nobody whose weekly off lands on a busy day. Expected: no action can be
  built, so no alert is sent.
- BBB-02: opened 15 Sep 2026. New, not judged.
"""
from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path

START = date(2026, 5, 1)
END = date(2026, 10, 31)
ONSET = date(2026, 9, 5)

FIRST_NAMES = ["Amar", "Bina", "Chand", "Dev", "Esha", "Firoz"]

STORES = [
    # store_id, city, state, tier, opened_on, area_manager_id
    ("AAA-01", "Alpha", "Uttar Pradesh", "S+", "2020-01-01", "AM-01"),
    ("AAA-02", "Alpha", "Uttar Pradesh", "A", "2019-01-01", "AM-01"),
    ("AAA-03", "Alpha", "Uttar Pradesh", "A", "2018-01-01", "AM-01"),
    ("BBB-01", "Beta", "Bihar", "A", "2017-01-01", "AM-02"),
    ("BBB-02", "Beta", "Bihar", "B", "2026-09-15", "AM-02"),
]


def _write(path: Path, header: list[str], rows: list[list]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)


def make_dataset(folder: Path, end: date = END, poison_after: date | None = None) -> Path:
    """Write the pack to `folder`, with rows up to `end`.

    With `poison_after`, every measured row dated after that day is made wildly
    different (bills tripled, footfall halved, everyone Off, a new salesperson and a
    new store appear). An as-of run at that day must not notice.
    """
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    people: dict[str, list[str]] = {}
    sp_rows = []
    n = 1000
    for store, *_rest in STORES:
        opened = date.fromisoformat(_rest[3])
        people[store] = []
        for k in range(6):
            n += 1
            sp = f"SP{n}"
            people[store].append(sp)
            name = f"{FIRST_NAMES[k]} {'VWXYZ'[len(people) - 1]}."  # no digits: names are quoted in alert text
            sp_rows.append([sp, store, name, max(opened, date(2015, 1, 1)).isoformat()])

    stores_rows = [[s, c, st, "North", t, "2000", "500", o, am] for s, c, st, t, o, am in STORES]
    if poison_after:
        stores_rows.append(["CCC-01", "Alpha", "Uttar Pradesh", "North", "B", "1000", "200",
                            (poison_after + timedelta(days=2)).isoformat(), "AM-01"])
        sp_rows.append(["SP9999", "AAA-02", "Late Joiner Z.", (poison_after + timedelta(days=1)).isoformat()])

    footfall_rows, roster_rows, bill_rows, line_rows = [], [], [], []
    bill_no = 0
    day = START
    while day <= end:
        iso = day.isoformat()
        wd = day.weekday()
        weekend = wd >= 5
        poisoned = poison_after is not None and day > poison_after
        for store, _city, _state, _tier, opened_on, _am in STORES:
            if iso < opened_on:
                continue
            ff = 150 if weekend else 100
            rate = 0.13
            if store == "AAA-01" and day >= ONSET and weekend:
                rate = 0.06
            if store == "BBB-01" and day > END - timedelta(days=28):
                rate = 0.08
            bills = round(ff * rate)
            shown_ff = ff
            if store == "AAA-03" and date(2026, 10, 8) <= day <= date(2026, 10, 17):
                shown_ff = 0  # broken door counter, bills continue
            if store == "AAA-02" and day == date(2026, 8, 12):
                shown_ff = 5  # fewer walk-ins recorded than bills made
            if poisoned:
                bills *= 3
                shown_ff = max(1, shown_ff // 2)
            footfall_rows.append([iso, store, shown_ff])

            present = []
            for k, sp in enumerate(people[store]):
                off = wd == k % 5  # one weekday off each, nobody off at weekends
                if store == "AAA-01" and k < 2 and day >= ONSET and weekend:
                    off = True  # the planted missed shifts
                if poisoned:
                    off = True
                roster_rows.append([iso, store, sp, "Off" if off else "Present"])
                if not off:
                    present.append(sp)
            sellers = present or people[store]
            for i in range(bills):
                bill_no += 1
                bid = f"B{bill_no:07d}"
                bill_rows.append([bid, iso, store, sellers[(i + day.toordinal()) % len(sellers)], f"C{bill_no:08d}"])
                line_rows.append([bid, "KUR-01-M", 2, 5000, 4500])
                line_rows.append([bid, "PKG-BAG", 1, 0, 0])
        day += timedelta(days=1)

    cal_rows = []
    day = START
    while day <= date(2026, 11, 30):  # the calendar is published in advance
        for state in ("Uttar Pradesh", "Bihar"):
            festival = "Test Festival" if (state == "Uttar Pradesh" and day == date(2026, 11, 4)) else ""
            cal_rows.append([day.isoformat(), state, festival, 0])
        day += timedelta(days=1)

    _write(folder / "stores.csv", ["store_id", "city", "state", "zone", "tier", "size_sqft",
                                   "stock_capacity_units", "opened_on", "area_manager_id"], stores_rows)
    _write(folder / "area_managers.csv", ["area_manager_id", "name", "city", "stores", "max_alerts_per_week"], [
        ["AM-01", "Manager One", "Alpha", "AAA-01, AAA-02, AAA-03", 5],
        ["AM-02", "Manager Two", "Beta", "BBB-01, BBB-02", 5],
    ])
    _write(folder / "salespeople.csv", ["salesperson_id", "store_id", "name", "join_date"], sp_rows)
    _write(folder / "roster_daily.csv", ["date", "store_id", "salesperson_id", "status"], roster_rows)
    _write(folder / "footfall_daily.csv", ["date", "store_id", "footfall"], footfall_rows)
    _write(folder / "bills.csv", ["bill_id", "bill_date", "store_id", "salesperson_id", "customer_id"], bill_rows)
    _write(folder / "bill_lines.csv", ["bill_id", "sku_id", "qty", "mrp", "selling_price"], line_rows)
    _write(folder / "items.csv", ["sku_id", "style_id", "style_name", "category", "size", "mrp", "cost_price",
                                  "launch_date", "is_core_style", "is_packaging"], [
        ["KUR-01-M", "KUR-01", "Test Kurta", "Kurta Set", "M", 5000, 2000, "2024-01-01", 1, 0],
        ["PKG-BAG", "PKG", "Carry Bag", "Packaging", "FS", 0, 0, "2024-01-01", 1, 1],
    ])
    _write(folder / "calendar.csv", ["date", "state", "festival", "is_wedding_date"], cal_rows)
    return folder
