"""Two small rules shared by the levers, so that an action can really be done on the day it names.

1. The action day. An alert or card is read the day after as-of ("today"). An action that
   needs named people on the floor together is dated for the first of the next 7 days on
   which none of them has their usual weekly off, and, for phone calls, which is not a busy
   day (the walk-ins come first on those). The sentence then says "Today" or "On Tuesday".
   The weekday is recomputable: every usual off used is a `usual_off_weekday` check and the
   busy dates are an `upcoming_busy_dates` check (docs/CHECKS-baskets.md section 5).

2. Nobody is held up as the model on one lever while being corrected on another. Each lever
   adds the people it is correcting to `corrected(m)`; the levers that run after it do not
   name those people as a peer or coach.
"""
from __future__ import annotations

from .checks import CheckBook
from .metrics import WEEKDAYS, Metrics, add_days, d

OFF_WINDOW_DAYS = 28  # the usual weekly off is read from the last 28 days of the roster
LOOK_DAYS = 7  # an action is dated within the next 7 days or not at all
BUSY_LOOK_AHEAD_DAYS = 9  # the same look-ahead as the more-bills lever, so the check is the same recipe


def off_window(m: Metrics) -> dict:
    return {"start": add_days(m.as_of, -(OFF_WINDOW_DAYS - 1)), "end": m.as_of}


def usual_off(m: Metrics, sp: str):
    """The weekday this person is most often Off in the last 28 days, or None (no roster, never off)."""
    return m.compute("usual_off_weekday", {"salesperson_id": sp, **off_window(m)})


def off_tomorrow(m: Metrics, sp: str) -> bool:
    return usual_off(m, sp) == WEEKDAYS[d(add_days(m.as_of, 1)).weekday()]


def action_day(m: Metrics, book: CheckBook, people: list[str], state: str | None = None,
               avoid_busy: bool = False) -> tuple[str, str] | None:
    """(how the sentence starts, the `when` field): ("Today", "Today") or ("On Tuesday", "Tuesday").

    None when no day in the next 7 fits; the caller then does not send the action.
    When the day is not tomorrow, the reasons are added to `book` as checks.
    """
    offs = {sp: usual_off(m, sp) for sp in people}
    busy = set()
    if avoid_busy and state is not None:
        busy = {dt for dt in (add_days(m.as_of, k) for k in range(1, LOOK_DAYS + 1)) if m.is_busy(state, dt)}
    chosen = None
    for k in range(1, LOOK_DAYS + 1):
        dt = add_days(m.as_of, k)
        if dt in busy or WEEKDAYS[d(dt).weekday()] in offs.values():
            continue
        chosen = (k, dt)
        break
    if chosen is None:
        return None
    k, dt = chosen
    if k == 1:
        return "Today", "Today"
    w = off_window(m)
    for sp in people:
        slug = f"usual_off:{sp}"
        if offs[sp] is not None and f"{book.prefix}:{slug}" not in book._ids:
            book.add(slug, f"Usual weekly off of {m.sp_name.get(sp, sp)}, last {OFF_WINDOW_DAYS} days", "usual_off_weekday",
                     {"salesperson_id": sp, **w})
    if busy and f"{book.prefix}:upcoming_busy_dates" not in book._ids:
        book.add("upcoming_busy_dates",
                 f"Busy days in the next {BUSY_LOOK_AHEAD_DAYS} days (weekends, festivals, wedding dates); calls are not planned on them",
                 "upcoming_busy_dates",
                 {"state": state, "start": add_days(m.as_of, 1), "end": add_days(m.as_of, BUSY_LOOK_AHEAD_DAYS)})
    weekday = WEEKDAYS[d(dt).weekday()]
    return f"On {weekday}", weekday


def corrected(m: Metrics) -> set:
    """Salespeople an earlier lever is correcting this run (the subject of an alert or card)."""
    s = getattr(m, "_corrected", None)
    if s is None:
        s = set()
        m._corrected = s
    return s
