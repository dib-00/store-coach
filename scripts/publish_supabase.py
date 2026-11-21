"""Write one engine run to Supabase, the store of record.

    python scripts/publish_supabase.py --file web/public/data/latest.json
    python scripts/publish_supabase.py --file web/public/data/latest.json --dry-run
    python scripts/publish_supabase.py --file web/public/data/latest.json --summary

What it writes (tables are defined in supabase/schema.sql):

    runs         one row per as_of; `output` holds the whole EngineOutput JSON
    alerts       one row per alert sent to an area manager
    cards        one row per salesperson card
    follow_ups   one row per alert re-measured in this run
    data_issues  one row per data issue

The run is upserted. The child rows for that as_of are deleted and inserted again, so
publishing the same run twice leaves exactly one copy. `alert_status` (the "done" tick
an area manager sets on the site) is never read or written here.

Standard library only. Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the
environment or in a git-ignored .env file in the repo root. The key is never printed.

This module also holds the small helpers the other two ops scripts share
(fetch_data.py and upload_data.py): the .env parser, the settings check and the HTTP call.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUCKET = "store-coach-data"
# urllib's default User-Agent is refused by some gateways, so name ourselves.
USER_AGENT = "store-coach-ops/1.0"
BOM = chr(0xFEFF)  # a byte-order mark, which Notepad puts at the start of a file
CHILD_TABLES = [  # (table, the column that holds the run's as_of, primary key columns)
    ("alerts", "as_of", "as_of,alert_id"),
    ("cards", "as_of", "as_of,card_id"),
    ("follow_ups", "measured_as_of", "measured_as_of,alert_id"),
    ("data_issues", "as_of", "as_of,issue_id"),
]


class OpsError(Exception):
    """A problem the person running the script can fix. Printed without a traceback."""


# ----------------------------------------------------------------------------
# Settings: environment first, then .env in the repo root
# ----------------------------------------------------------------------------


def parse_env(text: str) -> dict[str, str]:
    """Parse the text of a .env file. KEY=VALUE per line; # comments; optional quotes."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip().lstrip(BOM)
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if not key or " " in key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        out[key] = value
    return out


def load_env(path: Path | None = None, environ: dict[str, str] | None = None) -> dict[str, str]:
    """Settings from the .env file, overridden by non-empty environment variables."""
    path = REPO_ROOT / ".env" if path is None else path
    environ = dict(os.environ) if environ is None else environ
    values: dict[str, str] = {}
    if path.is_file():
        values.update(parse_env(path.read_text(encoding="utf-8-sig")))
    values.update({k: v for k, v in environ.items() if v.strip()})
    return values


def _jwt_role(key: str) -> str | None:
    """The `role` claim of a legacy Supabase JWT key, or None when the key is not a JWT."""
    parts = key.split(".")
    if len(parts) != 3:
        return None
    try:
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("role")
    except Exception:
        return None


def require_settings(env: dict[str, str]) -> tuple[str, str]:
    """(base URL, service-role key), or an OpsError that says exactly what is missing."""
    missing = [n for n in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY") if not env.get(n, "").strip()]
    if missing:
        raise OpsError(
            "Missing " + " and ".join(missing) + ". Locally: put them in a .env file in the repo "
            "root (see .env.example). In GitHub Actions: add them as repository secrets "
            "(Settings > Secrets and variables > Actions)."
        )
    url = env["SUPABASE_URL"].strip().rstrip("/")
    for suffix in ("/rest/v1", "/storage/v1"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
    if not url.startswith("https://") and not url.startswith("http://localhost") and not url.startswith("http://127.0.0.1"):
        raise OpsError("SUPABASE_URL must look like https://<project-ref>.supabase.co")
    key = env["SUPABASE_SERVICE_ROLE_KEY"].strip()
    if key.startswith("sb_publishable_") or _jwt_role(key) == "anon":
        raise OpsError(
            "SUPABASE_SERVICE_ROLE_KEY holds the public (anon / publishable) key. This script "
            "needs the service-role (secret) key from Supabase > Project Settings > API Keys."
        )
    return url, key


# ----------------------------------------------------------------------------
# HTTP: one function, urllib only
# ----------------------------------------------------------------------------


def request(
    method: str,
    url: str,
    key: str,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 120,
    attempts: int = 3,
) -> bytes:
    """One authenticated call to Supabase. Retries on 5xx and network errors.

    Error messages carry the method, the URL path and the server's reply. They never
    carry the key, and the URL holds no secret.
    """
    all_headers = {"apikey": key, "Authorization": f"Bearer {key}", "User-Agent": USER_AGENT}
    all_headers.update(headers or {})
    where = f"{method} {urllib.parse.urlsplit(url).path}"
    last = ""
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(url, data=body, method=method, headers=all_headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            reply = e.read().decode("utf-8", "replace")[:500]
            last = f"{where} failed with HTTP {e.code}: {reply}"
            if e.code < 500:
                raise OpsError(last) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = f"{where} could not reach Supabase: {getattr(e, 'reason', e)}"
        if attempt < attempts:
            time.sleep(2 * attempt)
    raise OpsError(last)


# ----------------------------------------------------------------------------
# Rows: pure functions from an EngineOutput dict (web/lib/types.ts)
# ----------------------------------------------------------------------------

REQUIRED_KEYS = ("schema_version", "as_of", "generated_at", "area_managers", "cards", "follow_ups", "data_issues")


def build_rows(output: dict) -> dict[str, list[dict]]:
    """The rows for every table, keyed by table name. Raises ValueError on a bad file."""
    absent = [k for k in REQUIRED_KEYS if k not in output]
    if absent:
        raise ValueError("not an EngineOutput file: missing " + ", ".join(absent))
    as_of = output["as_of"]

    alerts = []
    for block in output["area_managers"]:
        for a in block["alerts"]:
            alerts.append(
                {
                    "alert_id": a["alert_id"],
                    "as_of": as_of,
                    "area_manager_id": block["area_manager_id"],
                    "rank": a["rank"],
                    "lever": a["lever"],
                    "cause_code": a["cause_code"],
                    "store_ids": list(a["store_ids"]),
                    "headline": a["headline"],
                    "cause": a["cause"],
                    "action_text": a["action"]["text"],
                    "rupees_at_stake_weekly": int(a["rupees_at_stake_weekly"]),
                }
            )

    cards = [
        {
            "card_id": c["card_id"],
            "as_of": as_of,
            "store_id": c["store_id"],
            "salesperson_id": c["salesperson_id"],
            "lever": c["lever"],
            "text": c["text"],
            "word_count": c["word_count"],
        }
        for c in output["cards"]
    ]

    follow_ups = []
    for f in output["follow_ups"]:
        if f["measured_as_of"] != as_of:
            raise ValueError(
                f"follow-up {f['alert_id']} says measured_as_of {f['measured_as_of']} "
                f"but the run is as_of {as_of}"
            )
        follow_ups.append(
            {
                "alert_id": f["alert_id"],
                "measured_as_of": as_of,
                "raised_as_of": f["raised_as_of"],
                "moved": f["moved"],
                "before": f.get("before"),
                "after": f.get("after"),
                "target": f.get("target"),
                "verdict": f["verdict"],
            }
        )

    data_issues = [
        {
            "issue_id": i["issue_id"],
            "as_of": as_of,
            "store_id": i["store_id"],
            "kind": i["kind"],
            "title": i["title"],
            "days_affected": i["days_affected"],
        }
        for i in output["data_issues"]
    ]

    rows = {
        "runs": [
            {
                "as_of": as_of,
                "generated_at": output["generated_at"],
                "schema_version": output["schema_version"],
                "output": output,
            }
        ],
        "alerts": alerts,
        "cards": cards,
        "follow_ups": follow_ups,
        "data_issues": data_issues,
    }
    for table, id_col in (("alerts", "alert_id"), ("cards", "card_id"), ("follow_ups", "alert_id"), ("data_issues", "issue_id")):
        ids = [r[id_col] for r in rows[table]]
        twice = sorted({i for i in ids if ids.count(i) > 1})
        if twice:
            raise ValueError(f"{table}: {id_col} appears more than once in this run: {', '.join(twice)}")
    return rows


def row_counts(rows: dict[str, list[dict]]) -> dict[str, int]:
    return {table: len(r) for table, r in rows.items()}


def summary_markdown(output: dict) -> str:
    """A short job summary: as_of, alerts per area manager, data issues.

    Counts only. It adds up no rupee figures: every figure the engine publishes is a
    Check that scripts/verify.py recomputes, and a total made here would not be one.
    """
    lines = [
        f"## Store Coach run, as of {output['as_of']}",
        "",
        f"Generated at {output['generated_at']}.",
        "",
        "| Area manager | City | Alerts sent | Weekly cap | Held back |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    total = 0
    for b in output["area_managers"]:
        total += len(b["alerts"])
        lines.append(
            f"| {b['area_manager_id']} {b['name']} | {b['city']} | {len(b['alerts'])} "
            f"| {b['max_alerts_per_week']} | {len(b['held_back'])} |"
        )
    lines += [
        "",
        f"- Alerts sent: {total}",
        f"- Salesperson cards: {len(output['cards'])}",
        f"- Follow-ups measured: {len(output['follow_ups'])}",
        f"- Data issues (never sent as alerts): {len(output['data_issues'])}",
    ]
    for i in output["data_issues"]:
        label = i["title"] if i["store_id"] in i["title"] else f"{i['store_id']}: {i['title']}"
        lines.append(f"  - {label} ({i['days_affected']} days)")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------
# Publish
# ----------------------------------------------------------------------------


def _json_body(rows: list[dict]) -> bytes:
    return json.dumps(rows, ensure_ascii=False, allow_nan=False).encode("utf-8")


def publish(base_url: str, key: str, rows: dict[str, list[dict]]) -> None:
    rest = f"{base_url}/rest/v1"
    as_of = rows["runs"][0]["as_of"]
    write = {"Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"}

    # 1. The run itself. The child tables reference it, so it goes first.
    request("POST", f"{rest}/runs?on_conflict=as_of", key, _json_body(rows["runs"]), write)
    print(f"runs: upserted as_of {as_of}")

    # 2. Child rows: delete what an earlier publish of this as_of left, then insert.
    for table, date_col, pk in CHILD_TABLES:
        request("DELETE", f"{rest}/{table}?{date_col}=eq.{as_of}", key, headers={"Prefer": "return=minimal"})
        if rows[table]:
            request("POST", f"{rest}/{table}?on_conflict={pk}", key, _json_body(rows[table]), write)
        print(f"{table}: wrote {len(rows[table])} rows")

    # 3. Read back and compare, so a silent partial write fails the job.
    for table, date_col, pk in CHILD_TABLES:
        id_col = pk.split(",")[1]
        got = json.loads(request("GET", f"{rest}/{table}?{date_col}=eq.{as_of}&select={id_col}", key))
        if len(got) != len(rows[table]):
            raise OpsError(f"{table}: wrote {len(rows[table])} rows for {as_of} but read back {len(got)}")
    latest = json.loads(
        request("GET", f"{rest}/runs?select=as_of,generated_at&order=as_of.desc,generated_at.desc&limit=1", key)
    )
    if not latest:
        raise OpsError("runs: the table is empty after the upsert")
    print(f"read back: counts match; the newest run in Supabase is as_of {latest[0]['as_of']}")
    if latest[0]["as_of"] != as_of:
        print(f"note: the site shows the newest run ({latest[0]['as_of']}), not the one just published ({as_of})")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Write one engine run to Supabase")
    ap.add_argument("--file", default="web/public/data/latest.json", help="EngineOutput JSON written by engine.run")
    ap.add_argument("--dry-run", action="store_true", help="print the row counts and make no network call")
    ap.add_argument("--summary", action="store_true", help="print a Markdown summary of the run and make no network call")
    args = ap.parse_args(argv)

    try:
        path = Path(args.file)
        if not path.is_file():
            raise OpsError(f"{path} does not exist. Run the engine first: python -m engine.run")
        output = json.loads(path.read_text(encoding="utf-8"))
        try:
            rows = build_rows(output)
        except (ValueError, KeyError, TypeError) as e:
            raise OpsError(f"{path}: {e!r}") from None

        if args.summary:
            sys.stdout.write(summary_markdown(output))
            return 0
        if args.dry_run:
            print(f"dry run, nothing sent. as_of {output['as_of']}, generated_at {output['generated_at']}")
            for table, n in row_counts(rows).items():
                print(f"  {table}: {n} rows")
            return 0

        base_url, key = require_settings(load_env())
        publish(base_url, key, rows)
        return 0
    except OpsError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
