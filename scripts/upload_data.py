"""One-off, run by a person on their own machine: put the CSVs where the daily job can read them.

    python scripts/upload_data.py

Creates the PRIVATE Supabase Storage bucket "store-coach-data" if it is missing and
uploads data/csv/*.csv to csv/<name>.csv, replacing any earlier copy. The source data
belongs to Vedant Fashions and is not in Git; a private bucket is readable only with
the service-role key.

Reads SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from the environment or from the
git-ignored .env file in the repo root. Prints file sizes and a final count, never the key.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path

from publish_supabase import BUCKET, REPO_ROOT, OpsError, load_env, request, require_settings


def ensure_private_bucket(base_url: str, key: str) -> str:
    """Make sure the bucket exists and is private. Returns what was done."""
    storage = f"{base_url}/storage/v1"
    try:
        info = json.loads(request("GET", f"{storage}/bucket/{BUCKET}", key))
    except OpsError:
        info = None  # not found (the Storage API answers 400 or 404 for a missing bucket)
    if info is None:
        body = json.dumps({"id": BUCKET, "name": BUCKET, "public": False}).encode("utf-8")
        request("POST", f"{storage}/bucket", key, body, {"Content-Type": "application/json"})
        return "created (private)"
    if info.get("public"):
        body = json.dumps({"public": False}).encode("utf-8")
        request("PUT", f"{storage}/bucket/{BUCKET}", key, body, {"Content-Type": "application/json"})
        return "already there but public; switched to private"
    return "already there (private)"


def object_url(base_url: str, name: str) -> str:
    return f"{base_url}/storage/v1/object/{BUCKET}/csv/{urllib.parse.quote(name)}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Upload data/csv/*.csv to the private Supabase bucket")
    ap.add_argument("--data-dir", default=str(REPO_ROOT / "data" / "csv"))
    args = ap.parse_args(argv)

    try:
        files = sorted(Path(args.data_dir).glob("*.csv"))
        if not files:
            raise OpsError(f"no .csv files in {args.data_dir}")
        base_url, key = require_settings(load_env())
        print(f"bucket {BUCKET}: {ensure_private_bucket(base_url, key)}")
        total = 0
        for f in files:
            data = f.read_bytes()
            request("POST", object_url(base_url, f.name), key, data, {"Content-Type": "text/csv", "x-upsert": "true"})
            total += len(data)
            print(f"  csv/{f.name}  {len(data):,} bytes")
        print(f"uploaded {len(files)} files, {total:,} bytes, to bucket {BUCKET}")
        return 0
    except OpsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
