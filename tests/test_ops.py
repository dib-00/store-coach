"""The daily-run plumbing: Supabase rows, the .env parser and the workflow files.

No network and no data pack: HTTP is replaced where a test would reach it, and the
workflow files are read as text.
"""
from __future__ import annotations

import base64
import io
import json
import re
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_data  # noqa: E402
import publish_supabase as ps  # noqa: E402

DAILY = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
SCHEMA = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")


def alert(alert_id: str, rank: int, rupees: int) -> dict:
    return {
        "alert_id": alert_id,
        "rank": rank,
        "scope": "store",
        "store_ids": ["AAA-01"],
        "city": "Anytown",
        "lever": "more_bills",
        "cause_code": "missed_shifts",
        "headline": "AAA-01 is converting 10.0% of walk-ins.",
        "cause": "Two people missed shifts.",
        "action": {"who": "Store manager", "what": "Call them", "when": "Today", "text": "Today, call them."},
        "rupees_at_stake_weekly": rupees,
        "checks": [],
    }


def small_output() -> dict:
    return {
        "schema_version": 1,
        "as_of": "2026-10-31",
        "generated_at": "2026-11-01T00:30:00Z",
        "windows": {
            "current": {"start": "2026-10-04", "end": "2026-10-31"},
            "baseline": {"start": "2026-07-05", "end": "2026-10-03"},
        },
        "area_managers": [
            {
                "area_manager_id": "AM-01",
                "name": "A Manager",
                "city": "Anytown",
                "store_ids": ["AAA-01"],
                "max_alerts_per_week": 5,
                "alerts": [alert("AAA-01:more_bills:missed_shifts", 1, 9000), alert("AAA-01:more_bills:other", 2, 4000)],
                "held_back": [{"headline": "h", "lever": "more_bills", "rupees_at_stake_weekly": 10, "reason": "r"}],
            },
            {
                "area_manager_id": "AM-02",
                "name": "B Manager",
                "city": "Othertown",
                "store_ids": ["BBB-01"],
                "max_alerts_per_week": 5,
                "alerts": [],
                "held_back": [],
            },
        ],
        "stores": [],
        "cards": [
            {
                "card_id": "AAA-01:SP1:more_bills",
                "store_id": "AAA-01",
                "salesperson_id": "SP1",
                "salesperson_name": "S One",
                "lever": "more_bills",
                "text": "Greet every walk-in today.",
                "word_count": 4,
                "checks": [],
            }
        ],
        "follow_ups": [
            {
                "alert_id": "AAA-01:more_bills:missed_shifts",
                "raised_as_of": "2026-10-24",
                "measured_as_of": "2026-10-31",
                "moved": "improved",
                "before": 0.1,
                "after": 0.12,
                "target": 0.13,
                "verdict": "Conversion rose.",
            }
        ],
        "data_issues": [
            {
                "issue_id": "AAA-01:footfall_zero_with_bills",
                "store_id": "AAA-01",
                "kind": "footfall_zero_with_bills",
                "title": "Door counter read zero",
                "days_affected": 3,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def test_rows_cover_every_table_and_carry_the_run_date():
    out = small_output()
    rows = ps.build_rows(out)
    assert ps.row_counts(rows) == {"runs": 1, "alerts": 2, "cards": 1, "follow_ups": 1, "data_issues": 1}
    assert "alert_status" not in rows  # the "done" ticks are never written by the job

    run = rows["runs"][0]
    assert run["as_of"] == "2026-10-31" and run["schema_version"] == 1
    assert run["generated_at"] == "2026-11-01T00:30:00Z"
    assert run["output"] == out  # the whole EngineOutput, untouched

    first = rows["alerts"][0]
    assert first == {
        "alert_id": "AAA-01:more_bills:missed_shifts",
        "as_of": "2026-10-31",
        "area_manager_id": "AM-01",
        "rank": 1,
        "lever": "more_bills",
        "cause_code": "missed_shifts",
        "store_ids": ["AAA-01"],
        "headline": "AAA-01 is converting 10.0% of walk-ins.",
        "cause": "Two people missed shifts.",
        "action_text": "Today, call them.",
        "rupees_at_stake_weekly": 9000,
    }
    assert rows["cards"][0] == {
        "card_id": "AAA-01:SP1:more_bills",
        "as_of": "2026-10-31",
        "store_id": "AAA-01",
        "salesperson_id": "SP1",
        "lever": "more_bills",
        "text": "Greet every walk-in today.",
        "word_count": 4,
    }
    assert rows["follow_ups"][0] == {
        "alert_id": "AAA-01:more_bills:missed_shifts",
        "measured_as_of": "2026-10-31",
        "raised_as_of": "2026-10-24",
        "moved": "improved",
        "before": 0.1,
        "after": 0.12,
        "target": 0.13,
        "verdict": "Conversion rose.",
    }
    assert rows["data_issues"][0] == {
        "issue_id": "AAA-01:footfall_zero_with_bills",
        "as_of": "2026-10-31",
        "store_id": "AAA-01",
        "kind": "footfall_zero_with_bills",
        "title": "Door counter read zero",
        "days_affected": 3,
    }


def test_rows_of_one_table_share_the_same_keys():
    # PostgREST needs every object of a bulk insert to have the same keys.
    rows = ps.build_rows(small_output())
    for table, items in rows.items():
        assert len({tuple(sorted(r)) for r in items}) <= 1, table


def test_row_columns_exist_in_the_schema():
    rows = ps.build_rows(small_output())
    for table, items in rows.items():
        block = re.search(rf"create table if not exists public\.{table} \((.*?)\n\);", SCHEMA, re.S)
        assert block, table
        columns = {line.split()[0] for line in block.group(1).splitlines() if line.strip()}
        for r in items:
            assert set(r) <= columns, (table, set(r) - columns)


def test_held_back_alerts_are_not_published_as_alerts():
    rows = ps.build_rows(small_output())
    assert all(r["headline"] != "h" for r in rows["alerts"])


def test_a_bad_file_is_refused():
    out = small_output()
    del out["cards"]
    with pytest.raises(ValueError, match="cards"):
        ps.build_rows(out)

    out = small_output()
    out["area_managers"][1]["alerts"] = [alert("AAA-01:more_bills:missed_shifts", 1, 1)]
    with pytest.raises(ValueError, match="more than once"):
        ps.build_rows(out)

    out = small_output()
    out["follow_ups"][0]["measured_as_of"] = "2026-10-30"
    with pytest.raises(ValueError, match="measured_as_of"):
        ps.build_rows(out)


def test_committed_output_builds_rows_within_the_weekly_cap():
    path = ROOT / "web" / "public" / "data" / "latest.json"
    if not path.is_file():
        pytest.skip("no committed engine output")
    out = json.loads(path.read_text(encoding="utf-8"))
    rows = ps.build_rows(out)
    assert len(rows["alerts"]) == sum(len(b["alerts"]) for b in out["area_managers"])
    for b in out["area_managers"]:
        mine = [r for r in rows["alerts"] if r["area_manager_id"] == b["area_manager_id"]]
        assert len(mine) <= b["max_alerts_per_week"]
    json.dumps(rows, allow_nan=False)  # everything is plain JSON


def test_summary_names_the_date_each_manager_and_the_data_issues():
    text = ps.summary_markdown(small_output())
    assert "as of 2026-10-31" in text
    assert "| AM-01 A Manager | Anytown | 2 | 5 | 1 |" in text
    assert "| AM-02 B Manager | Othertown | 0 | 5 | 0 |" in text
    assert "9000" not in text and "13000" not in text  # counts only, no rupee totals made up here
    assert "Data issues (never sent as alerts): 1" in text
    assert "AAA-01: Door counter read zero (3 days)" in text


# ---------------------------------------------------------------------------
# Dry run and publish order (HTTP replaced)
# ---------------------------------------------------------------------------


def test_dry_run_prints_counts_and_makes_no_network_call(tmp_path, monkeypatch, capsys):
    f = tmp_path / "latest.json"
    f.write_text(json.dumps(small_output()), encoding="utf-8")

    def no_network(*a, **k):
        raise AssertionError("dry run must not touch the network")

    monkeypatch.setattr(ps, "request", no_network)
    monkeypatch.setattr(ps.urllib.request, "urlopen", no_network)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    assert ps.main(["--file", str(f), "--dry-run"]) == 0
    printed = capsys.readouterr().out
    for line in ("runs: 1 rows", "alerts: 2 rows", "cards: 1 rows", "follow_ups: 1 rows", "data_issues: 1 rows"):
        assert line in printed


def test_publish_upserts_the_run_first_and_never_touches_alert_status(monkeypatch, capsys):
    rows = ps.build_rows(small_output())
    calls = []

    def fake(method, url, key, body=None, headers=None, **k):
        calls.append((method, url, headers or {}))
        if method != "GET":
            return b""
        if "/runs?" in url:
            return b'[{"as_of": "2026-10-31", "generated_at": "2026-11-01T00:30:00Z"}]'
        table = url.split("/rest/v1/")[1].split("?")[0]
        return json.dumps([{"id": i} for i in range(len(rows[table]))]).encode()

    monkeypatch.setattr(ps, "request", fake)
    ps.publish("https://example.supabase.co", "not-a-real-key", rows)

    assert calls[0][0] == "POST" and calls[0][1].endswith("/rest/v1/runs?on_conflict=as_of")
    assert "resolution=merge-duplicates" in calls[0][2]["Prefer"]
    assert all("alert_status" not in url for _, url, _ in calls)
    assert all(method != "DELETE" or "/runs" not in url for method, url, _ in calls)  # a run is never deleted
    for table, date_col in (("alerts", "as_of"), ("cards", "as_of"), ("follow_ups", "measured_as_of"), ("data_issues", "as_of")):
        mine = [(m, u) for m, u, _ in calls if f"/rest/v1/{table}?" in u and m != "GET"]
        assert [m for m, _ in mine] == ["DELETE", "POST"], table  # delete, then insert
        assert mine[0][1].endswith(f"/{table}?{date_col}=eq.2026-10-31")
    assert "not-a-real-key" not in capsys.readouterr().out


def test_publish_fails_when_the_read_back_does_not_match(monkeypatch):
    rows = ps.build_rows(small_output())
    monkeypatch.setattr(ps, "request", lambda method, url, key, body=None, headers=None, **k: b"[]")
    with pytest.raises(ps.OpsError, match="read back"):
        ps.publish("https://example.supabase.co", "k", rows)


# ---------------------------------------------------------------------------
# Settings and secrets
# ---------------------------------------------------------------------------


def test_env_parser():
    text = (
        ps.BOM + "# a comment\r\n"
        "\r\n"
        "SUPABASE_URL=https://abc.supabase.co\r\n"
        "export A_KEY = abc.def==\r\n"
        'QUOTED="has # hash and spaces "\r\n'
        "SINGLE='x=y'\r\n"
        "TRAILING=value # a note\r\n"
        "EMPTY=\r\n"
        "not a setting\r\n"
        "BAD KEY=1\r\n"
    )
    assert ps.parse_env(text) == {
        "SUPABASE_URL": "https://abc.supabase.co",
        "A_KEY": "abc.def==",
        "QUOTED": "has # hash and spaces ",
        "SINGLE": "x=y",
        "TRAILING": "value",
        "EMPTY": "",
    }


def test_environment_wins_over_the_env_file_unless_it_is_empty(tmp_path):
    f = tmp_path / ".env"
    f.write_text("SUPABASE_URL=https://file.supabase.co\nSUPABASE_SERVICE_ROLE_KEY=from-file\n", encoding="utf-8")
    got = ps.load_env(f, {"SUPABASE_URL": "https://env.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": ""})
    assert got["SUPABASE_URL"] == "https://env.supabase.co"
    assert got["SUPABASE_SERVICE_ROLE_KEY"] == "from-file"
    assert ps.load_env(tmp_path / "absent.env", {}) == {}


def fake_jwt(role: str) -> str:
    part = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{part({'alg': 'HS256'})}.{part({'role': role})}.signature"


def test_missing_settings_fail_loudly_and_name_the_variable():
    with pytest.raises(ps.OpsError, match="SUPABASE_SERVICE_ROLE_KEY"):
        ps.require_settings({"SUPABASE_URL": "https://abc.supabase.co"})
    with pytest.raises(ps.OpsError, match="SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY"):
        ps.require_settings({})
    with pytest.raises(ps.OpsError, match="https://"):
        ps.require_settings({"SUPABASE_URL": "abc.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "k"})


def test_settings_are_tidied_and_the_public_key_is_refused():
    service = fake_jwt("service_role")
    assert ps.require_settings({"SUPABASE_URL": " https://abc.supabase.co/rest/v1/ ", "SUPABASE_SERVICE_ROLE_KEY": service}) == (
        "https://abc.supabase.co",
        service,
    )
    assert ps.require_settings({"SUPABASE_URL": "https://abc.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_x"})[1] == "sb_secret_x"
    for public in (fake_jwt("anon"), "sb_publishable_abc"):
        with pytest.raises(ps.OpsError) as e:
            ps.require_settings({"SUPABASE_URL": "https://abc.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": public})
        assert public not in str(e.value)


def test_an_http_error_message_never_contains_the_key(monkeypatch):
    key = "super-secret-service-key"
    seen = {}

    def refuse(req, timeout=None):
        seen["headers"] = dict(req.header_items())
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", None, io.BytesIO(b'{"message":"bad token"}'))

    monkeypatch.setattr(ps.urllib.request, "urlopen", refuse)
    with pytest.raises(ps.OpsError) as e:
        ps.request("GET", "https://abc.supabase.co/rest/v1/runs?select=as_of", key)
    assert key not in str(e.value)
    assert "HTTP 401" in str(e.value) and "/rest/v1/runs" in str(e.value)
    assert seen["headers"]["Authorization"] == f"Bearer {key}"  # the key travels only in headers
    assert seen["headers"]["User-agent"] == ps.USER_AGENT


def test_a_missing_secret_stops_the_scripts_before_any_network_call(tmp_path, monkeypatch, capsys):
    f = tmp_path / "latest.json"
    f.write_text(json.dumps(small_output()), encoding="utf-8")

    def no_network(*a, **k):
        raise AssertionError("no network call without settings")

    monkeypatch.setattr(ps.urllib.request, "urlopen", no_network)
    monkeypatch.setattr(ps, "load_env", lambda *a, **k: {})
    monkeypatch.setattr(fetch_data, "load_env", lambda *a, **k: {})
    assert ps.main(["--file", str(f)]) == 1
    assert fetch_data.main(["--data-dir", str(tmp_path / "csv")]) == 1
    err = capsys.readouterr().err
    assert err.count("Missing SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY") == 2


# ---------------------------------------------------------------------------
# Fetching the inputs
# ---------------------------------------------------------------------------


def test_fetch_list_is_exactly_what_the_engine_reads():
    from engine.load import USED_FILES

    assert list(fetch_data.HEADERS) == USED_FILES


def test_downloaded_csv_must_be_non_empty_with_a_header_and_rows():
    assert fetch_data.check_csv("footfall_daily", b"date,store_id,footfall\n2026-10-31,AAA-01,40\n") == 1
    assert fetch_data.check_csv("footfall_daily", b"\xef\xbb\xbfdate,store_id,footfall\r\n2026-10-31,AAA-01,40\r\n\r\n") == 1
    for bad, why in (
        (b"", "empty"),
        (b"  \n", "empty"),
        (b"2026-10-31,AAA-01,40\n", "header"),
        (b"<html>Not found</html>\n", "header"),
        (b"date,store_id,footfall\n", "no data rows"),
    ):
        with pytest.raises(ps.OpsError, match=why):
            fetch_data.check_csv("footfall_daily", bad)


def test_fetch_writes_checked_files_and_reports_a_bad_one(tmp_path, monkeypatch):
    good = {name: (header + "\n" + ",".join("x" for _ in header.split(",")) + "\n").encode() for name, header in fetch_data.HEADERS.items()}
    urls = []

    def fake(method, url, key, *a, **k):
        urls.append(url)
        return good[url.rsplit("/", 1)[1].removesuffix(".csv")]

    monkeypatch.setattr(fetch_data, "request", fake)
    fetch_data.fetch_csvs("https://abc.supabase.co", "k", tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(f"{n}.csv" for n in fetch_data.HEADERS)
    assert urls[0] == "https://abc.supabase.co/storage/v1/object/store-coach-data/csv/stores.csv"

    good["bills"] = b""
    with pytest.raises(ps.OpsError, match="bills.csv is empty"):
        fetch_data.fetch_csvs("https://abc.supabase.co", "k", tmp_path / "second")
    assert not (tmp_path / "second" / "bills.csv").exists()


def test_last_weeks_run_is_restored_only_when_the_repo_lacks_it(tmp_path, monkeypatch):
    assert fetch_data.prior_run_date("2026-10-31") == "2026-10-24"
    assert fetch_data.prior_run_date("2026-03-05") == "2026-02-26"

    stored = {"as_of": "2026-10-24", "schema_version": 1}
    asked = []

    def fake(method, url, key, *a, **k):
        asked.append(url)
        return json.dumps([{"output": stored}]).encode()

    monkeypatch.setattr(fetch_data, "request", fake)
    note = fetch_data.restore_prior_run("https://abc.supabase.co", "k", "2026-10-31", tmp_path)
    assert "restored" in note and asked == ["https://abc.supabase.co/rest/v1/runs?as_of=eq.2026-10-24&select=output&limit=1"]
    assert json.loads((tmp_path / "2026-10-24.json").read_text(encoding="utf-8")) == stored

    (tmp_path / "2026-10-24.json").write_text('{"from": "repo"}', encoding="utf-8")
    note = fetch_data.restore_prior_run("https://abc.supabase.co", "k", "2026-10-31", tmp_path)
    assert "already there" in note and len(asked) == 1  # no second call, file untouched
    assert json.loads((tmp_path / "2026-10-24.json").read_text(encoding="utf-8")) == {"from": "repo"}

    monkeypatch.setattr(fetch_data, "request", lambda *a, **k: b"[]")
    note = fetch_data.restore_prior_run("https://abc.supabase.co", "k", "2026-11-07", tmp_path)
    assert "no follow-ups" in note and not (tmp_path / "2026-10-31.json").exists()


# ---------------------------------------------------------------------------
# The workflow files, read as text
# ---------------------------------------------------------------------------


def step_position(text: str, needle: str) -> int:
    assert needle in text, f"{needle!r} is not in the workflow"
    return text.index(needle)


def test_daily_job_never_writes_to_the_repository():
    lowered = DAILY.lower()
    for forbidden in ("git push", "git commit", "git add", "git tag", "contents: write", "write-all", "persist-credentials: true"):
        assert forbidden not in lowered, forbidden
    assert re.search(r"^permissions:\n  contents: read\n", DAILY, re.M)
    assert DAILY.count("permissions:") == 1  # no job-level override


def test_daily_job_is_scheduled_and_can_be_started_by_hand():
    assert re.search(r"^name: Daily engine run$", DAILY, re.M)
    assert 'cron: "30 0 * * *"' in DAILY and "06:00 IST" in DAILY
    assert "workflow_dispatch:" in DAILY and "as_of:" in DAILY
    assert 'python-version: "3.13"' in DAILY and "cache: pip" in DAILY


def test_daily_job_verifies_before_it_publishes_and_publishes_before_it_deploys():
    order = [
        "pip install -r requirements.txt",
        "python scripts/fetch_data.py --data-dir data/csv",
        "python -m pytest -q",
        "python -m engine.run",
        "run: python scripts/verify.py",
        "run: python scripts/publish_supabase.py --file web/public/data/latest.json",
        'curl -sS -o /dev/null -w \'%{http_code}\' --retry 3 --retry-delay 5 -X POST "$VERCEL_DEPLOY_HOOK_URL"',
        "actions/upload-artifact@",
        "GITHUB_STEP_SUMMARY",
    ]
    positions = [step_position(DAILY, needle) for needle in order]
    assert positions == sorted(positions)


def test_verify_and_publish_cannot_be_skipped_over():
    # Neither step may carry a condition or continue after a failure, so a mismatch stops the job.
    assert "continue-on-error" not in DAILY
    steps = re.split(r"\n      - name: ", DAILY)[1:]
    gated = [s for s in steps if s.startswith(("Verify every figure", "Publish the run", "Ask Vercel"))]
    assert len(gated) == 3
    for step in gated:
        assert "\n        if:" not in step, step.splitlines()[0]


def test_daily_job_uses_only_the_three_secrets_and_never_echoes_them():
    assert set(re.findall(r"secrets\.([A-Z_]+)", DAILY)) == {"SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "VERCEL_DEPLOY_HOOK_URL"}
    for line in DAILY.splitlines():
        if "echo" in line:
            assert "$SUPABASE_SERVICE_ROLE_KEY" not in line and "$VERCEL_DEPLOY_HOOK_URL" not in line
    assert "VERCEL_DEPLOY_HOOK_URL is not set" in DAILY  # skipped with a warning, not a failure


def test_ci_needs_no_secrets_and_runs_both_suites():
    assert "secrets." not in CI
    assert re.search(r"^on:\n  push:\n  pull_request:\n", CI, re.M)
    for needle in ("python -m pytest -q", "npm ci", "npm test", "npm run lint", "working-directory: web"):
        assert needle in CI, needle
    assert "contents: read" in CI and "git push" not in CI


# ---------------------------------------------------------------------------
# The schema and the settings template, read as text
# ---------------------------------------------------------------------------

TABLES = ("runs", "alerts", "cards", "follow_ups", "data_issues", "alert_status")


def test_schema_turns_row_level_security_on_for_every_table():
    for table in TABLES:
        assert f"create table if not exists public.{table} (" in SCHEMA
        assert re.search(rf"alter table public\.{table}\s+enable row level security;", SCHEMA), table
        assert f'create policy "anon reads {table}" on public.{table}' in SCHEMA


def test_schema_lets_anon_write_alert_status_and_nothing_else():
    writes = re.findall(r"^grant (insert|update|delete|all|truncate)[^;]*? on ([^;]*?) to (\w+);", SCHEMA, re.M | re.S)
    anon_writes = [(verb, target.strip()) for verb, target, role in writes if role != "service_role"]
    assert anon_writes == [("insert", "public.alert_status"), ("update", "public.alert_status")]
    write_policies = re.findall(r'create policy "[^"]+" on public\.(\w+)\s+for (insert|update|delete|all)', SCHEMA)
    assert write_policies == [("alert_status", "insert"), ("alert_status", "update")]
    assert "latest_run" in SCHEMA and "security_invoker = true" in SCHEMA


def test_schema_is_safe_to_run_twice():
    assert len(re.findall(r"^create table (?!if not exists)", SCHEMA, re.M)) == 0
    created = re.findall(r'^create policy ("[^"]+") on (public\.\w+)', SCHEMA, re.M)
    for name, table in created:
        assert f"drop policy if exists {name} on {table};" in SCHEMA
    assert "drop view if exists public.latest_run;" in SCHEMA


def test_env_example_has_names_only_and_is_the_one_env_file_git_keeps():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    settings = ps.parse_env(text)
    assert set(settings) == {
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "NEXT_PUBLIC_SUPABASE_URL",
        "NEXT_PUBLIC_SUPABASE_ANON_KEY",
        "VERCEL_DEPLOY_HOOK_URL",
    }
    assert all(value == "" for value in settings.values())  # no values, so no secret can be in it
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignore and ".env.*" in ignore and "!.env.example" in ignore
    assert ignore.index("!.env.example") > ignore.index(".env.*")
