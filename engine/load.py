"""Load the CSVs and apply the as-of cut-off.

This module is the ONLY place where --as-of is applied. Everything downstream
receives a Data object that simply does not contain later rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

USED_FILES = [
    "stores",
    "area_managers",
    "salespeople",
    "roster_daily",
    "footfall_daily",
    "bills",
    "bill_lines",
    "items",
    "calendar",
]


@dataclass
class Data:
    as_of: str  # YYYY-MM-DD; no measured row is later than this
    stores: pd.DataFrame
    managers: pd.DataFrame
    salespeople: pd.DataFrame
    roster: pd.DataFrame  # date, store_id, salesperson_id, status
    footfall: pd.DataFrame  # date, store_id, footfall (float, NaN when blank)
    bills: pd.DataFrame  # bill_id, bill_date, store_id, salesperson_id, customer_id, value
    lines: pd.DataFrame  # bill_id, sku_id, qty_n, mrp_n, price_n, line_value, category, is_packaging
    items: pd.DataFrame  # sku_id, style_id, style_name, category, size, is_packaging, ...
    calendar: pd.DataFrame  # date, state, festival, is_wedding_date (published in advance)


def read_csv(data_dir: Path, name: str) -> pd.DataFrame:
    """Every column is read as text. Numbers are converted explicitly by the caller."""
    return pd.read_csv(Path(data_dir) / f"{name}.csv", dtype=str, keep_default_na=False)


def last_bill_date(data_dir: Path) -> str:
    return str(read_csv(data_dir, "bills")["bill_date"].max())


def load(data_dir: Path | str, as_of: str | None = None) -> Data:
    data_dir = Path(data_dir)
    raw = {name: read_csv(data_dir, name) for name in USED_FILES}
    if as_of is None:
        as_of = str(raw["bills"]["bill_date"].max())

    # ---- the as-of cut-off: the one place where later rows are dropped ----
    bills = raw["bills"][raw["bills"]["bill_date"] <= as_of].copy()
    footfall = raw["footfall_daily"][raw["footfall_daily"]["date"] <= as_of].copy()
    roster = raw["roster_daily"][raw["roster_daily"]["date"] <= as_of].copy()
    salespeople = raw["salespeople"][raw["salespeople"]["join_date"] <= as_of].copy()
    stores = raw["stores"][raw["stores"]["opened_on"] <= as_of].copy()
    lines = raw["bill_lines"][raw["bill_lines"]["bill_id"].isin(set(bills["bill_id"]))].copy()
    # The calendar is published in advance and is NOT cut. Future calendar rows are
    # used only to name upcoming busy days in an action, never to measure anything.
    calendar = raw["calendar"].copy()
    # ----------------------------------------------------------------------

    # Bill value = sum(qty x selling_price) over its lines. Packaging lines are Rs 0.
    lines["qty_n"] = pd.to_numeric(lines["qty"])
    lines["price_n"] = pd.to_numeric(lines["selling_price"])
    lines["mrp_n"] = pd.to_numeric(lines["mrp"])
    lines["line_value"] = lines["qty_n"] * lines["price_n"]
    items = raw["items"].copy()
    lines = lines.merge(items[["sku_id", "category", "is_packaging"]], on="sku_id", how="left")
    value = lines.groupby("bill_id")["line_value"].sum()
    bills["value"] = bills["bill_id"].map(value).fillna(0.0).astype(float)

    footfall["footfall"] = pd.to_numeric(footfall["footfall"].replace("", pd.NA), errors="coerce")

    managers = raw["area_managers"].copy()
    managers["max_alerts_per_week"] = pd.to_numeric(managers["max_alerts_per_week"]).astype(int)

    sort = lambda df, cols: df.sort_values(cols, kind="mergesort").reset_index(drop=True)
    return Data(
        as_of=as_of,
        stores=sort(stores, ["store_id"]),
        managers=sort(managers, ["area_manager_id"]),
        salespeople=sort(salespeople, ["salesperson_id"]),
        roster=sort(roster, ["date", "store_id", "salesperson_id"]),
        footfall=sort(footfall, ["date", "store_id"]),
        bills=sort(bills, ["bill_id"]),
        lines=sort(lines, ["bill_id", "sku_id"]),
        items=sort(items, ["sku_id"]),
        calendar=sort(calendar, ["date", "state"]),
    )
