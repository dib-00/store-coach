"""Data issues: numbers that cannot be right. Listed, left out of conversion, never alerted."""
from __future__ import annotations

from .checks import CheckBook, fmt_date
from .metrics import Metrics

MAX_INVALID_SHARE = 0.20  # above this share of a window, the store's conversion is not judged


def judgeable(m: Metrics, store: str, start: str, end: str) -> bool:
    """Enough valid store-days in the window to say anything about conversion."""
    _, f, _, nv, ni = m.parts([store], start, end)
    return nv > 0 and f > 0 and ni / (nv + ni) <= MAX_INVALID_SHARE


def find_data_issues(m: Metrics, windows: dict) -> list[dict]:
    """One issue per store and kind, over the days the engine measures (baseline start to as-of)."""
    start, end = windows["baseline"]["start"], windows["current"]["end"]
    cur = windows["current"]
    out = []
    for store in sorted(m.day):
        bad = [(dt, ff, bb) for _, dt, ff, bb, _, ok in m.store_days([store], start, end) if not ok]
        groups = {
            "bills_exceed_footfall": [x for x in bad if x[1] is not None and x[1] > 0],
            "footfall_zero_with_bills": [x for x in bad if x[1] is None or x[1] <= 0],
        }
        for kind in sorted(groups):
            rows = groups[kind]
            if not rows:
                continue
            if kind == "footfall_zero_with_bills" and not any(bb > 0 for _, _, bb in rows):
                # Zero footfall and zero bills contradict nothing. Such days are still left
                # out of conversion (0 of 0) but are not reported as an issue.
                continue
            first, last = rows[0][0], rows[-1][0]
            issue_id = f"{store}:{kind}"
            book = CheckBook(m, issue_id)
            rule = "footfall_zero" if kind == "footfall_zero_with_bills" else "bills_exceed_footfall"
            win = {"store_ids": [store], "start": first, "end": last, "rule": rule}
            n_bad = book.add("days_affected", "Days left out of conversion", "invalid_days", dict(win))
            n_bills = book.add("bills_on_those_days", "Bills made on those days", "bills_on_invalid_days", dict(win))
            cur_win = {"store_ids": [store], "start": cur["start"], "end": cur["end"]}
            cur_bad = book.add("invalid_days_current", "Days left out of the current window, any reason",
                               "invalid_days", dict(cur_win))
            cur_ok = book.add("valid_days_current", "Usable days left in the current window",
                              "valid_days", dict(cur_win))
            judged = judgeable(m, store, cur["start"], cur["end"])
            if kind == "footfall_zero_with_bills":
                title = f"{store}: door counter shows no walk-ins on days with bills"
                detail = (
                    f"Footfall is 0 or blank on {n_bad['display']} days between {fmt_date(first)} and "
                    f"{fmt_date(last)}, and {n_bills['display']} bills were made on those days. "
                    "A bill needs a walk-in, so the footfall count is wrong, not the sales."
                )
            else:
                title = f"{store}: more bills than walk-ins"
                detail = (
                    f"On {n_bad['display']} days between {fmt_date(first)} and {fmt_date(last)} the store "
                    f"made more bills than the door counter recorded walk-ins ({n_bills['display']} bills)."
                )
            handling = (
                "These days are left out of both bills and walk-ins wherever conversion is worked out, "
                "and no alert is raised from them."
            )
            if not judged:
                handling += (
                    f" {cur_bad['display']} of the {cur_bad['value'] + cur_ok['value']} days in the current "
                    f"window are unusable (more than {int(MAX_INVALID_SHARE * 100)}%), so the conversion of "
                    f"{store} is not judged this week."
                )
            out.append(
                {
                    "issue_id": issue_id,
                    "store_id": store,
                    "kind": kind,
                    "title": title,
                    "detail": detail,
                    "first_date": first,
                    "last_date": last,
                    "days_affected": len(rows),
                    "handling": handling,
                    "checks": book.items,
                }
            )
    return out
