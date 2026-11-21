"""Follow-up: a week later, re-measure last week's alerts and say whether the number moved.

The run for `as_of` looks for runs/<as_of minus 7 days>.json. For every alert sent in
that earlier run it re-measures `alert["follow_up"]` on the days after the alert was
raised (earlier as_of + 1 day .. as_of) and reports before, after and target.

It reports what happened to the number. It never says the action caused it.
The rule for "moved" is written out in docs/METHOD-followup.md.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .checks import CheckBook, display, numbers_not_in_checks
from .issues import judgeable
from .load import Data
from .metrics import Metrics, add_days

FOLLOW_UP_DAYS = 7  # the earlier run is the one exactly this many days before as-of
NOISE_WEEKS = 8  # measures without a counting rule: how many earlier weeks show the usual week-to-week movement
MIN_NOISE_WEEKS = 4  # fewer usable earlier weeks than this: no verdict

# Measures that are a rate on a count: kind -> (numerator kind, noun, denominator kind, noun).
# Both are computed with the same params as the measure. A lever module may add its own.
RATE_PARTS: dict[str, tuple[str, str, str, str]] = {
    "conversion": ("bills_count", "bills", "footfall_sum", "walk-ins"),
}

NOT_MEASURABLE = "not measurable"


def is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def safe_compute(m: Metrics, kind: str, params: dict):
    """The measure, or None when it cannot be worked out on these params."""
    try:
        v = m.compute(kind, params)
    except Exception:  # an unknown kind or params it cannot take: not measurable, never a crash
        return None
    return v if is_number(v) else None


def classify(before: float, after: float, noise: float, higher_is_better: bool = True) -> str:
    """improved / worse only when the change is at least `noise`; otherwise no_change."""
    change = (after - before) if higher_is_better else (before - after)
    if change > 0 and change >= noise:
        return "improved"
    if change < 0 and -change >= noise:
        return "worse"
    return "no_change"


def rate_standard_error(numerator: float, denominator: float) -> float | None:
    """Standard error of a rate on a count: sqrt(p x (1 - p) / n), p = numerator / denominator."""
    if not denominator or denominator <= 0:
        return None
    p = numerator / denominator
    if p < 0 or p > 1:
        return None
    return math.sqrt(p * (1 - p) / denominator)


def sample_sd(values: list[float]) -> float:
    mean = sum(values) / len(values)
    return math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1))


def _matching_check(alert: dict, kind: str, value) -> dict | None:
    """The alert's own check that carries this value (same kind first), so the recipe can be repeated."""
    checks = alert.get("checks", [])
    for c in checks:
        if c.get("kind") == kind and c.get("value") == value:
            return c
    return None


def one_follow_up(m: Metrics, alert: dict, area_manager_id: str, raised_as_of: str) -> dict:
    as_of = m.as_of
    fu = alert["follow_up"]
    kind = fu["kind"]
    label = fu["metric_label"]
    before, target = fu["baseline_value"], fu["target_value"]
    higher = bool(fu.get("higher_is_better", True))
    window = {"start": add_days(raised_as_of, 1), "end": as_of}
    params = {**fu["params"], **window}  # the same recipe, on the days after the alert was raised
    store_ids = list(alert.get("store_ids", []))
    book = CheckBook(m, f"followup:{alert['alert_id']}")

    before_display = display(kind, before)
    target_display = display(kind, target)
    after = None
    moved = "not_measurable"
    why_not = ""
    ending = ""
    sample = ""

    # "Before" is the figure the alert showed. It is kept only if the same recipe still gives it.
    stable = safe_compute(m, kind, dict(fu["params"])) == before
    if stable:
        book.add("before", f"{label}, when the alert was raised", kind, dict(fu["params"]), value=before)
        tc = _matching_check(alert, kind, target)
        if tc is not None and safe_compute(m, tc["kind"], dict(tc["params"])) == target:
            book.add("target", f"{label}, the target ({tc['label']})", tc["kind"], dict(tc["params"]), value=target)
        else:
            tc = None
        state = m.state.get(store_ids[0], "") if store_ids else ""
        days = book.add("days", "Days measured after the alert was raised", "day_count",
                        {"state": state, **window, "day_type": "all"})
    else:
        tc = days = None
        why_not = "the figure shown when the alert was raised no longer recomputes from the data"

    if stable:
        usable = True
        if kind == "conversion":
            # the same rule as for an alert: too many unusable footfall days and conversion is not judged
            for s in params.get("store_ids", []):
                if not judgeable(m, s, window["start"], window["end"]):
                    usable = False
            if not usable:
                sid = {"store_ids": sorted(params.get("store_ids", []))}
                book.add("after_invalid_days", "Days with unusable footfall in those days", "invalid_days",
                         {**sid, **window, "rule": "any"})
                book.add("after_valid_days", "Days with usable footfall in those days", "valid_days", {**sid, **window})
                why_not = "the door counter is unusable on too many of those days"
        value = safe_compute(m, kind, params) if usable else None
        if usable and value is None:
            why_not = "there is nothing to measure in those days"
        if value is not None:
            after = value
            book.add("after", f"{label}, the {days['display']} days after", kind, params, value=after)
            noise = None
            if kind in RATE_PARTS:
                num_kind, num_noun, den_kind, den_noun = RATE_PARTS[kind]
                num = book.add("after_numerator", f"{num_noun.capitalize()} in those days", num_kind, params)
                den = book.add("after_denominator", f"{den_noun.capitalize()} in those days", den_kind, params)
                if is_number(num["value"]) and is_number(den["value"]):
                    noise = rate_standard_error(num["value"], den["value"])
                    sample = f" ({num['display']} {num_noun} from {den['display']} {den_noun})"
            else:
                # no counting rule for this measure: use how much the same 7-day figure moved in earlier weeks
                weeks = []
                for k in range(NOISE_WEEKS):
                    end = add_days(raised_as_of, -FOLLOW_UP_DAYS * k)
                    w = {"start": add_days(end, -(FOLLOW_UP_DAYS - 1)), "end": end}
                    v = safe_compute(m, kind, {**fu["params"], **w})
                    if v is not None:
                        book.add(f"earlier_week_{k + 1}", f"{label}, {w['start']} to {w['end']}", kind,
                                 {**fu["params"], **w}, value=v)
                        weeks.append(v)
                if len(weeks) >= MIN_NOISE_WEEKS:
                    noise = sample_sd(weeks)
            if noise is None:
                why_not = "there are too few earlier weeks to tell a real change from chance"
            else:
                moved = classify(before, after, noise, higher)
                reached = after >= target if higher else after <= target
                if moved == "improved":
                    ending = ("Improved, and at or past the target this week, but one week is a small sample."
                              if reached else "Improved, but still short of the target, and one week is a small sample.")
                elif moved == "worse":
                    ending = "Worse than when raised, though one week is a small sample."
                else:
                    ending = "No real change: the difference is within what one week moves by chance."

    after_display = display(kind, after) if after is not None else NOT_MEASURABLE
    target_clause = f"; the target is {target_display}" if tc is not None else ""
    if not stable:
        verdict = f"{label} cannot be compared a week later, because {why_not}; no result is claimed."
    elif after is None:
        verdict = (f"{label} was {before_display} when raised{target_clause}. It cannot be measured for the "
                   f"{days['display']} days after, because {why_not}.")
    elif moved == "not_measurable":
        verdict = (f"{label} was {before_display} when raised and {after_display} in the {days['display']} days "
                   f"after{sample}{target_clause}. No verdict, because {why_not}.")
    else:
        verdict = (f"{label} was {before_display} when raised and {after_display} in the {days['display']} days "
                   f"after{sample}{target_clause}. {ending}")
    if numbers_not_in_checks([verdict], book.items):
        # a figure in the sentence has no check behind it (for example a number inside the label): say less
        verdict = ending or f"Not measurable a week later, because {why_not}."

    out = {
        "alert_id": alert["alert_id"],
        "area_manager_id": area_manager_id,
        "store_ids": store_ids,
        "lever": alert["lever"],
        "headline": alert["headline"],
        "action_text": alert["action"]["text"],
        "raised_as_of": raised_as_of,
        "measured_as_of": as_of,
        "metric_label": label,
        "before": before,
        "after": after,  # null when not measurable
        "target": target,
        "before_display": before_display,
        "after_display": after_display,
        "target_display": target_display,
        "moved": moved,
        "verdict": verdict,
    }
    if alert.get("definition"):
        out["definition"] = alert["definition"]
    out["checks"] = [c for c in book.items if c["value"] is not None]
    return out


def follow_ups(m: Metrics, data: Data, runs_dir: Path) -> list[dict]:
    """One FollowUp (web/lib/types.ts) per alert sent in the run of exactly a week earlier; [] if there is none."""
    raised_as_of = add_days(data.as_of, -FOLLOW_UP_DAYS)
    path = Path(runs_dir) / f"{raised_as_of}.json"
    if not path.is_file():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            earlier = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(earlier, dict) or earlier.get("as_of") != raised_as_of:
        return []
    out = []
    for block in earlier.get("area_managers", []):
        for alert in block.get("alerts", []):
            if not isinstance(alert.get("follow_up"), dict):
                continue
            out.append(one_follow_up(m, alert, block["area_manager_id"], raised_as_of))
    return out
