"""Download the engine's inputs from Supabase. Used by the daily job, which has no data/ folder.

    python scripts/fetch_data.py                       # the nine CSVs into data/csv
    python scripts/fetch_data.py --data-dir some/dir
    python scripts/fetch_data.py --skip-csv --prior-run-for 2026-10-31 --runs-dir web/public/data/runs

The CSVs live in the PRIVATE Storage bucket "store-coach-data" as csv/<name>.csv
(put there once by scripts/upload_data.py). Every file is checked after download: it
must be non-empty, start with the expected header row and hold at least one data row.

--prior-run-for restores the run of seven days earlier from the `runs` table when that
file is not already in --runs-dir, so the follow-up has last week's alerts to re-measure
even though the daily job never commits to the repo. A copy already in the folder is
never overwritten.

Standard library only. Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the
environment or in the git-ignored .env file in the repo root. The key is never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

from publish_supabase import BUCKET, OpsError, load_env, request, require_settings

# The nine files engine/load.py reads, with the columns each must start with.
# tests/test_ops.py checks this list against engine.load.USED_FILES.
HEADERS = {
    "stores": "store_id,city,state,zone,tier,size_sqft,stock_capacity_units,opened_on,area_manager_id",
    "area_managers": "area_manager_id,name,city,stores,max_alerts_per_week",
    "salespeople": "salesperson_id,store_id,name,join_date",
    "roster_daily": "date,store_id,salesperson_id,status",
    "footfall_daily": "date,store_id,footfall",
    "bills": "bill_id,bill_date,store_id,salesperson_id,customer_id",
    "bill_lines": "bill_id,sku_id,qty,mrp,selling_price",
    "items": "sku_id,style_id,style_name,category,size,mrp,cost_price,launch_date,is_core_style,is_packaging",
    "calendar": "date,state,festival,is_wedding_date",
}


def check_csv(name: str, data: bytes) -> int:
    """Raise OpsError unless `data` is a usable copy of <name>.csv. Returns the data-row count."""
    if not data.strip():
        raise OpsError(f"{name}.csv is empty")
    try:
        lines = data.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError:
        raise OpsError(f"{name}.csv is not UTF-8 text") from None
    header = [c.strip() for c in lines[0].split(",")]
    expected = HEADERS[name].split(",")
    absent = [c for c in expected if c not in header]
    if absent:
        raise OpsError(f"{name}.csv has no header row with the columns: {', '.join(absent)}")
    rows = sum(1 for line in lines[1:] if line.strip())
    if rows == 0:
        raise OpsError(f"{name}.csv has a header row but no data rows")
    return rows


def fetch_csvs(base_url: str, key: str, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    for name in HEADERS:
        url = f"{base_url}/storage/v1/object/{BUCKET}/csv/{name}.csv"
        try:
            data = request("GET", url, key)
        except OpsError as e:
            raise OpsError(
                f"{e} Check that csv/{name}.csv is in the bucket {BUCKET} (python scripts/upload_data.py) "
                "and that SUPABASE_SERVICE_ROLE_KEY is the service-role key of this project."
            ) from None
        rows = check_csv(name, data)
        tmp = data_dir / f"{name}.csv.part"
        tmp.write_bytes(data)
        os.replace(tmp, data_dir / f"{name}.csv")
        total += len(data)
        print(f"  {name}.csv  {len(data):,} bytes, {rows:,} rows")
    print(f"fetched {len(HEADERS)} files, {total:,} bytes, into {data_dir}")


def prior_run_date(as_of: str) -> str:
    return (date.fromisoformat(as_of) - timedelta(days=7)).isoformat()


def restore_prior_run(base_url: str, key: str, as_of: str, runs_dir: Path) -> str:
    """Put runs/<as_of - 7>.json in place from Supabase if the folder lacks it. Returns a note."""
    prior = prior_run_date(as_of)
    path = runs_dir / f"{prior}.json"
    if path.is_file():
        return f"{path.as_posix()} is already there; kept as it is"
    found = json.loads(request("GET", f"{base_url}/rest/v1/runs?as_of=eq.{prior}&select=output&limit=1", key))
    if not found:
        return f"no run for {prior} in the repo or in Supabase: this run will report no follow-ups"
    runs_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(found[0]["output"], ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    return f"restored {path.as_posix()} from Supabase"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Download the engine's inputs from Supabase")
    ap.add_argument("--data-dir", default="data/csv")
    ap.add_argument("--skip-csv", action="store_true", help="do not download the CSVs")
    ap.add_argument("--prior-run-for", metavar="AS_OF", help="restore the run of AS_OF minus 7 days if it is missing")
    ap.add_argument("--runs-dir", default="web/public/data/runs")
    args = ap.parse_args(argv)

    try:
        if args.prior_run_for:
            try:
                date.fromisoformat(args.prior_run_for)
            except ValueError:
                raise OpsError(f"--prior-run-for must be YYYY-MM-DD, got {args.prior_run_for!r}") from None
        base_url, key = require_settings(load_env())
        if not args.skip_csv:
            fetch_csvs(base_url, key, Path(args.data_dir))
        if args.prior_run_for:
            print(restore_prior_run(base_url, key, args.prior_run_for, Path(args.runs_dir)))
        return 0
    except OpsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
