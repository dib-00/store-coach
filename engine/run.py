"""Command line entry point.

    python -m engine.run --as-of 2026-10-31

Writes web/public/data/latest.json and web/public/data/runs/<as_of>.json in the shape
of EngineOutput (web/lib/types.ts). Apart from generated_at, two runs on the same
inputs produce byte-identical files.

Follow-up reads runs/<as_of minus 7 days>.json, so to show last week's alerts a week
later, build that run first without touching latest.json:

    python -m engine.run --as-of 2026-10-24 --dated-only
    python -m engine.run --as-of 2026-10-31
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import baskets, bills_cards, repeat
from .cards import select_cards
from .checks import CheckBook, fmt_date
from .detect import Detector, is_new_store, make_windows
from .followup import follow_ups
from .issues import find_data_issues, judgeable
from .load import Data, last_bill_date, load
from .metrics import Metrics, add_days, d
from .rank import apply_cap, sendable


def store_blocks(m: Metrics, data: Data, windows: dict) -> list[dict]:
    cur, base = windows["current"], windows["baseline"]
    span = lambda w: f"{fmt_date(w['start'])} to {fmt_date(w['end'])}"
    has_roster = m.roster_min is not None
    out = []
    for r in data.stores.to_dict("records"):
        s = r["store_id"]
        new = is_new_store(r["opened_on"], data.as_of)
        people = []
        for p in m.store_sps.get(s, []):
            if has_roster:
                last = m.last_roster_date(p)
                active = last is not None and (d(data.as_of) - d(last)).days <= 6
            else:
                active = m.sp_bill_count(p, cur["start"], cur["end"]) > 0
            people.append({"salesperson_id": p, "name": m.sp_name[p], "active": bool(active)})
        book = CheckBook(m, f"store:{s}")
        sid = {"store_ids": [s]}
        if judgeable(m, s, cur["start"], cur["end"]):
            book.add("conversion_current", f"Conversion, {span(cur)}", "conversion", {**sid, **cur, "day_type": "all"})
            book.add("walkins_per_week_current", f"Walk-ins a week, {span(cur)}", "walkins_per_week", {**sid, **cur})
            book.add("avg_bill_value_current", f"Average bill value, {span(cur)}", "avg_bill_value", {**sid, **cur})
        if not new and judgeable(m, s, base["start"], base["end"]):
            book.add("conversion_baseline", f"Conversion, {span(base)}", "conversion", {**sid, **base, "day_type": "all"})
        # Why the store is not judged this run, if it is not. Every figure in the sentence is a check.
        reason = None
        if new:
            c = book.add("opened_on", "Opened on", "store_opened_on", {"store_id": s})
            reason = f"Opened {c['display']}; too new to compare with established stores"
        else:
            for name, w in (("current", cur), ("baseline", base)):
                if judgeable(m, s, w["start"], w["end"]):
                    continue
                bad = book.add(f"invalid_days_{name}", f"Days with unusable footfall, {span(w)}", "invalid_days",
                               {**sid, **w, "rule": "any"})
                ok = book.add(f"valid_days_{name}", f"Days with usable footfall, {span(w)}", "valid_days", {**sid, **w})
                reason = (f"Footfall is unusable on {bad['display']} days of the {name} window and usable on "
                          f"{ok['display']}, so conversion is not judged this week (see data issues)")
                break
        out.append(
            {
                "store_id": s,
                "city": r["city"],
                "state": r["state"],
                "tier": r["tier"],
                "opened_on": r["opened_on"],
                "area_manager_id": r["area_manager_id"],
                "is_new_store": new,
                "salespeople": people,
                "summary": [c for c in book.items if c["value"] is not None],
            }
        )
        if reason:
            out[-1]["not_judged_reason"] = reason
    return out


def manager_blocks(data: Data, candidates: list[dict], notes: list[dict] | None = None) -> list[dict]:
    store_manager = dict(zip(data.stores["store_id"], data.stores["area_manager_id"]))
    out = []
    for r in data.managers.to_dict("records"):
        am = r["area_manager_id"]
        store_ids = sorted(s for s, a in store_manager.items() if a == am)
        mine = [a for a in candidates if store_manager.get(a["store_ids"][0]) == am]
        alerts, held = apply_cap(sendable(mine), int(r["max_alerts_per_week"]))
        market = [n for n in (notes or []) if store_manager.get(n["store_ids"][0]) == am]
        out.append(
            {
                "area_manager_id": am,
                "name": r["name"],
                "city": r["city"],
                "store_ids": store_ids,
                "max_alerts_per_week": int(r["max_alerts_per_week"]),
                "alerts": alerts,
                "held_back": held,
                "market_notes": market,  # a whole city down: shown to the manager, never ranked as an alert
            }
        )
    return out


def build_output(data: Data, generated_at: str, runs_dir: Path | None = None) -> tuple[dict, list[str]]:
    m = Metrics(data)
    det = Detector(m)
    windows = make_windows(data.as_of)
    candidates = det.run()
    notes = det.notes
    card_candidates: list[dict] = []
    issues = find_data_issues(m, windows)
    # The other levers plug in here. Each module returns (alert candidates, notes),
    # card candidates and its own data issues; the cap and the card rule apply to all.
    for lever in (baskets, repeat):
        found, lever_notes = lever.detect(m)
        candidates += found
        notes += lever_notes
        card_candidates += lever.card_candidates(m)
        issues += lever.data_issues(m, windows)
    # The more-bills cards come last: by now engine.workday.corrected(m) holds everyone the other
    # levers are correcting today, and none of them is named as the colleague to learn from.
    card_candidates += bills_cards.card_candidates(m)
    issues.sort(key=lambda i: i["issue_id"])
    output = {
        "schema_version": 1,
        "as_of": data.as_of,
        "generated_at": generated_at,
        "windows": windows,
        "area_managers": manager_blocks(data, candidates, det.market_notes()),
        "stores": store_blocks(m, data, windows),
        "cards": select_cards(card_candidates),
        "follow_ups": follow_ups(m, data, runs_dir) if runs_dir is not None else [],
        "data_issues": issues,
    }
    return output, notes


def to_json(output: dict) -> str:
    return json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Store Coach engine")
    ap.add_argument("--as-of", help="YYYY-MM-DD; default: the last bill date in the data")
    ap.add_argument("--data-dir", default="data/csv")
    ap.add_argument("--out-dir", default="web/public/data")
    ap.add_argument("--generated-at", help="ISO 8601 UTC timestamp to stamp the file with (default: now)")
    ap.add_argument("--dated-only", action="store_true",
                    help="write only runs/<as_of>.json and leave latest.json alone (to rebuild an earlier week's run)")
    args = ap.parse_args(argv)

    as_of = args.as_of or last_bill_date(Path(args.data_dir))
    date.fromisoformat(as_of)  # fail early on a malformed date
    generated_at = args.generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    data = load(args.data_dir, as_of)
    output, notes = build_output(data, generated_at, Path(args.out_dir) / "runs")
    text = to_json(output)

    out_dir = Path(args.out_dir)
    (out_dir / "runs").mkdir(parents=True, exist_ok=True)
    dated = out_dir / "runs" / f"{as_of}.json"
    paths = [dated] if args.dated_only else [out_dir / "latest.json", dated]
    for path in paths:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    n_alerts = sum(len(b["alerts"]) for b in output["area_managers"])
    print(f"as_of {as_of}: {n_alerts} alerts, {len(output['cards'])} cards, {len(output['follow_ups'])} follow-ups, "
          f"{len(output['data_issues'])} data issues -> {paths[0]}")
    for b in output["area_managers"]:
        for a in b["alerts"]:
            print(f"  {b['area_manager_id']} #{a['rank']} {a['alert_id']}  Rs {a['rupees_at_stake_weekly']} a week")
    for f in output["follow_ups"]:
        print(f"  follow-up {f['alert_id']}: {f['moved']}  {f['before_display']} -> {f['after_display']} "
              f"(target {f['target_display']})")
    for n in notes:
        print(f"  note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
