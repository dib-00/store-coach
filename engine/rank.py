"""The weekly cap and the action rule: the two gates every alert passes through."""
from __future__ import annotations


def apply_cap(candidates: list[dict], max_alerts: int) -> tuple[list[dict], list[dict]]:
    """Rank by rupees at stake (highest first), keep the top `max_alerts`, hold the rest back.

    Ties are broken by alert_id so the order is the same on every run.
    Returns (alerts with rank 1..n, held_back).
    """
    ordered = sorted(candidates, key=lambda a: (-a["rupees_at_stake_weekly"], a["alert_id"]))
    kept, held = [], []
    for i, alert in enumerate(ordered):
        if i < max_alerts:
            a = dict(alert)
            a["rank"] = i + 1
            kept.append(a)
        else:
            held.append(
                {
                    "headline": alert["headline"],
                    "lever": alert["lever"],
                    "rupees_at_stake_weekly": alert["rupees_at_stake_weekly"],
                    "reason": f"Below the top {max_alerts} this week",
                }
            )
    return kept, held


def has_who_what_when(action: dict | None) -> bool:
    """The action rule: an alert must name who, what and when, or it is not sent."""
    if not action:
        return False
    return all(isinstance(action.get(k), str) and action[k].strip() for k in ("who", "what", "when", "text"))


def sendable(alerts: list[dict]) -> list[dict]:
    """Drop every candidate whose action does not name who, what and when."""
    return [a for a in alerts if has_who_what_when(a.get("action"))]
