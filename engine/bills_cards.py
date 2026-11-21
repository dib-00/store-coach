"""Salesperson card candidates for lever 1, "more bills". See engine/cards.py for the shape.

Salespeople have no footfall of their own, so nobody is given a conversion figure.
Two things can be read fairly from the roster and the bills, always inside one store
over the same dates:

  A. busy-day attendance   present on far fewer weekend and festival days than colleagues;
  B. bills per day present far fewer bills for each day on the floor than colleagues.

A card is written only when the gap is real and material, a peer still on the roster
can be named, and there is one thing to do today. The rules and thresholds are
explained in docs/METHOD-followup.md.
"""
from __future__ import annotations

import math

from .checks import CheckBook, numbers_not_in_checks
from .cards import MAX_CARD_WORDS, word_count
from .detect import LEVER, is_new_store, make_windows, upcoming_busy_dates
from .metrics import WEEKDAYS, Metrics, add_days, d

ACTIVE_WITHIN_DAYS = 7  # "still on the roster": a roster row in the last 7 days up to as-of
MIN_PEERS = 3  # colleagues needed for a comparison to mean anything

# A. busy-day attendance
BUSY_MAX_SHARE = 0.5  # present on at most half the busy days a typical colleague worked
BUSY_MIN_GAP = 3  # and at least 3 busy days fewer

# B. bills per day present
MIN_PRESENT_DAYS = 14  # present at least half of the 28 days, the person and every colleague compared
MIN_BASE_PRESENT_DAYS = 20  # and at least 20 days in the 13 weeks before
MAX_RATE_SHARE = 0.75  # at most three quarters of the typical colleague's bills per day present
Z_GAP = -2.5  # and too far below it to be chance (bills counted as a Poisson count)

DEF_ATTENDANCE = ("Weekend and festival days are Saturdays, Sundays and the festival and wedding dates in the state "
                  "calendar; a day on the floor is a day marked Present on the roster, over the last four weeks, "
                  "compared only with colleagues at the same store.")
DEF_RATE = ("Bills for each day on the floor are the bills carrying the salesperson's id divided by the days marked "
            "Present on the roster, over the last four weeks; compared only with colleagues at the same store over "
            "the same dates, because a salesperson has no walk-in count of their own.")


def first_name(name: str) -> str:
    return name.split()[0] if name.split() else name


def is_active(m: Metrics, sp: str) -> bool:
    last = m.last_roster_date(sp)
    return last is not None and (d(m.as_of) - d(last)).days < ACTIVE_WITHIN_DAYS


def _card(store: str, sp: str, m: Metrics, peer: str, behaviour: str, action: str, book: CheckBook,
          priority: float, definition: str) -> dict | None:
    text = f"{behaviour} {action}"
    if word_count(text) > MAX_CARD_WORDS or not book.usable() or numbers_not_in_checks([text], book.items):
        return None  # over 60 words, or a figure without a check: say nothing
    return {
        "store_id": store,
        "salesperson_id": sp,
        "salesperson_name": m.sp_name[sp],
        "lever": LEVER,
        "behaviour": behaviour,
        "peer": {"salesperson_id": peer, "name": m.sp_name[peer]},
        "action": action,
        "text": text,
        "checks": book.items,
        "priority": float(priority),
        "definition": definition,
    }


def attendance_card(m: Metrics, store: str, state: str, sp: str, cur: dict, abv: float) -> dict | None:
    """A: on the floor on far fewer weekend and festival days than colleagues."""
    if not m.rostered_every_day(sp, cur["start"], cur["end"]):
        return None
    peers = [x for x in m.full_window_peers(store, [sp], cur["start"], cur["end"]) if is_active(m, x)]
    if len(peers) < MIN_PEERS:
        return None
    busy = {**cur, "day_type": "busy"}
    mine = m.present_days(sp, **busy)
    typical = m.compute("peer_median_present_days", {"store_id": store, "exclude_salesperson_ids": [sp], **busy})
    if not typical or mine > BUSY_MAX_SHARE * typical or typical - mine < BUSY_MIN_GAP:
        return None
    # the named peer: the colleague on the floor on the most busy days (then most bills per day present, then id)
    peer = sorted(peers, key=lambda x: (-m.present_days(x, **busy), -(m.bills_per_present_day(x, **cur) or 0), x))[0]

    book = CheckBook(m, f"card:{store}:{sp}:{LEVER}")
    c_mine = book.add("busy_days_present", f"Weekend and festival days on the floor, {m.sp_name[sp]}", "present_days",
                      {"salesperson_id": sp, **busy})
    c_all = book.add("busy_days_in_window", "Weekend and festival days in the window", "day_count",
                     {"state": state, **busy})
    c_peer = book.add("peer_busy_days_present", f"Weekend and festival days on the floor, {m.sp_name[peer]}",
                      "present_days", {"salesperson_id": peer, **busy})
    book.add("typical_busy_days_present", f"Weekend and festival days on the floor, typical colleague at {store}",
             "peer_median_present_days", {"store_id": store, "exclude_salesperson_ids": [sp], **busy})
    dates, when = upcoming_busy_dates(m, book, state)
    if not dates:
        return None
    behaviour = (f"{first_name(m.sp_name[sp])}, you were on the floor on {c_mine['display']} of the last "
                 f"{c_all['display']} weekend and festival days at {store}; {m.sp_name[peer]} was there on "
                 f"{c_peer['display']}.")
    action = f"Today, ask your store manager to roster you on {when} and move your weekly off to a weekday."
    # say that these are the busier days only if this store's own walk-ins show it, and only if it fits
    _, f_busy, _, n_busy, _ = m.parts([store], cur["start"], cur["end"], "busy")
    _, f_norm, _, n_norm, _ = m.parts([store], cur["start"], cur["end"], "normal")
    why = " Those are the days most customers walk in."
    if n_busy and n_norm and f_busy / n_busy > f_norm / n_norm and word_count(behaviour + why + " " + action) <= MAX_CARD_WORDS:
        behaviour += why
    # rupees a week: busy days missed a week x what a typical colleague bills in a day x the store's average bill
    typical_rate = m.compute("peer_median_bills_per_present_day", {
        "store_id": store, "exclude_salesperson_ids": [sp], **cur, "min_present_days": MIN_PRESENT_DAYS}) or 0
    weeks = ((d(cur["end"]) - d(cur["start"])).days + 1) / 7
    priority = (typical - mine) / weeks * typical_rate * abv
    return _card(store, sp, m, peer, behaviour, action, book, priority, DEF_ATTENDANCE)


def rate_card(m: Metrics, store: str, state: str, sp: str, cur: dict, base: dict, abv: float) -> dict | None:
    """B: far fewer bills for each day on the floor than colleagues at the same store."""
    present = m.present_days(sp, **cur)
    if present < MIN_PRESENT_DAYS or m.present_days(sp, **base) < MIN_BASE_PRESENT_DAYS:
        return None
    colleagues = [x for x in m.store_sps.get(store, []) if x != sp and m.present_days(x, **cur) >= MIN_PRESENT_DAYS]
    if len(colleagues) < MIN_PEERS:
        return None
    median_params = {"store_id": store, "exclude_salesperson_ids": [sp], **cur, "min_present_days": MIN_PRESENT_DAYS}
    typical = m.compute("peer_median_bills_per_present_day", median_params)
    bills = m.sp_bill_count(sp, **cur)
    if not typical or bills / present > MAX_RATE_SHARE * typical:
        return None
    expected = typical * present  # bills this person would have made at the typical colleague's rate
    if (bills - expected) / math.sqrt(expected) > Z_GAP:
        return None
    # not a one-month blip: also below the typical colleague in the 13 weeks before
    base_typical = m.compute("peer_median_bills_per_present_day", {
        "store_id": store, "exclude_salesperson_ids": [sp], **base, "min_present_days": MIN_BASE_PRESENT_DAYS})
    base_rate = m.bills_per_present_day(sp, **base)
    if base_typical is None or base_rate is None or base_rate >= base_typical:
        return None
    # a card is for someone expected on the floor tomorrow, the day it is read
    tomorrow = WEEKDAYS[d(add_days(m.as_of, 1)).weekday()]
    usual_off = lambda x: m.compute("usual_off_weekday", {"salesperson_id": x, **cur})
    if usual_off(sp) == tomorrow:
        return None
    # the named peer: the colleague with the most bills per day present who is still on the roster
    # and not usually off tomorrow
    ranked = sorted((x for x in colleagues if is_active(m, x) and usual_off(x) != tomorrow),
                    key=lambda x: (-m.bills_per_present_day(x, **cur), x))
    if not ranked:
        return None
    peer = ranked[0]
    if m.bills_per_present_day(peer, **cur) <= typical:
        return None

    book = CheckBook(m, f"card:{store}:{sp}:{LEVER}")
    c_days = book.add("days_in_window", "Days in the window", "day_count", {"state": state, **cur, "day_type": "all"})
    c_mine = book.add("bills_per_present_day", f"Bills per day present, {m.sp_name[sp]}", "bills_per_present_day",
                      {"salesperson_id": sp, **cur})
    c_peer = book.add("peer_bills_per_present_day", f"Bills per day present, {m.sp_name[peer]}",
                      "bills_per_present_day", {"salesperson_id": peer, **cur})
    c_typ = book.add("typical_bills_per_present_day", f"Bills per day present, typical colleague at {store}",
                     "peer_median_bills_per_present_day", median_params)
    book.add("present_days", f"Days present, {m.sp_name[sp]}", "present_days", {"salesperson_id": sp, **cur, "day_type": "all"})
    behaviour = (f"{first_name(m.sp_name[sp])}, over the last {c_days['display']} days you made {c_mine['display']} "
                 f"bills for each day on the floor at {store}; {m.sp_name[peer]} made {c_peer['display']} and a "
                 f"typical colleague {c_typ['display']}.")
    action = (f"Today, serve your first three walk-ins alongside {m.sp_name[peer]} and watch how each "
              f"sale is closed, then take the next walk-in on your own.")
    # rupees a week: gap in bills per day present x days present a week x the store's average bill
    weeks = ((d(cur["end"]) - d(cur["start"])).days + 1) / 7
    priority = (typical - bills / present) * (present / weeks) * abv
    return _card(store, sp, m, peer, behaviour, action, book, priority, DEF_RATE)


def card_candidates(m: Metrics) -> list[dict]:
    """At most one candidate per salesperson for this lever. Within-store comparisons only."""
    if m.roster_min is None:
        return []
    windows = make_windows(m.as_of)
    cur, base = windows["current"], windows["baseline"]
    if m.roster_min > base["start"]:
        return []  # the roster does not reach back 17 weeks: too little history to call a gap a habit
    out = []
    for r in m.data.stores.to_dict("records"):
        store = r["store_id"]
        if is_new_store(r["opened_on"], m.as_of):
            continue  # a new store is not compared with anyone, and has too little history of its own
        bills, _, value, _, _ = m.parts([store], cur["start"], cur["end"])
        if not bills:
            continue
        abv = value / bills
        for sp in m.store_sps.get(store, []):
            if not is_active(m, sp):
                continue
            card = attendance_card(m, store, r["state"], sp, cur, abv)
            if card is None:
                card = rate_card(m, store, r["state"], sp, cur, base, abv)
            if card is not None:
                out.append(card)
    return out
