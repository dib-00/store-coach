# Method: follow-up, "more bills" cards and the small additions

This page adds to [METHOD.md](METHOD.md). Recipes for every figure are in
[CHECKS-followup.md](CHECKS-followup.md).

## 1. Follow-up: a week later, did the number move?

Every run looks for the run of exactly 7 days earlier, `runs/<as_of − 7 days>.json`.
If there is none, `follow_ups` is empty. If there is one, every alert that run sent
(every manager, every lever) is re-measured:

- **before**: the figure the alert showed (`follow_up.baseline_value`);
- **after**: the same recipe, same stores and people, on the 7 days after the alert was
  raised (`earlier as_of + 1 day` to `as_of`). Only the window changes;
- **target**: the fair benchmark the alert named (`follow_up.target_value`).

The run uses only data up to its own `as_of`, as every run does (`engine/load.py`).
`tests/test_followup.py` shows that rows after `as_of` cannot change a follow-up, and
that the earlier run is byte-identical whether or not later rows exist.

To see it:

```
python -X utf8 -m engine.run --as-of 2026-10-24 --dated-only   # writes runs/2026-10-24.json only
python -X utf8 -m engine.run --as-of 2026-10-31                # its follow_ups compare with the 24 Oct alerts
```

`--dated-only` leaves `latest.json` alone, so an earlier week can be rebuilt without
changing what the site shows.

### When is a move real?

One week in one store is a small sample. A store with 800 walk-ins and 11% conversion
moves by about one point from week to week with nothing having changed. So:

- **improved** or **worse** only when the change from before to after is at least two
  standard errors of the difference, `2 × sqrt(se_before² + se_after²)`, each
  `sqrt(p × (1 − p) / walk-ins)` for its own window;
- **no change** otherwise;
- **not measurable** when the week cannot be measured: for conversion, when more than
  20% of the store-days in the week have unusable footfall (the rule that also stops an
  alert) or there is nothing to count. The follow-up then shows no "after" figure
  rather than a guess.

For a measure that is not a rate on a count (the other levers' measures), the bar is two
standard deviations of the same 7-day figure over the 8 weeks before the alert, and at
least 4 of those weeks must have a value. When the figure was the same in every earlier
week (usually nought), one bill would look like a jump, so there is no verdict.

Why two standard errors and not one: before and after are separate samples, so both
errors count, and one standard error of the week alone would call a move on about one
quiet week in three. Printing "before" (four weeks or more) and "after" (one week) with
the bills and walk-ins behind them lets a reader judge the size for themselves.

### What the verdict may and may not say

The verdict states before, after, the sample and the target, then one of: improved
(and whether the target was reached), no real change, worse. It never says the action
caused the change. The engine does not know whether anybody acted.

### The result on this data, stated plainly

The data is a synthetic history that ends on 31 Oct 2026. Nobody received the 24 Oct
alerts and nobody acted on them. The follow-up on 31 Oct therefore shows what these
stores did on their own:

| Alert raised 24 Oct | Before | 7 days after | Target | Verdict |
| --- | --- | --- | --- | --- |
| LKO-02, salesperson left | 9.8% | 11.4% (92 bills from 805 walk-ins) | 12.3% | no real change: up, but within two standard errors |
| BLR-03, missed shifts | 11.1% | 9.4% (74 bills from 784 walk-ins) | 13.2% | no real change: down, but within two standard errors |

Both are reported as they are. The roster line of the BLR-03 follow-up states whether the
two salespeople were on the floor on the weekend days of that week, as a fact, without
crediting or blaming anything for the number. The 31 Oct run raises the same alert again.

## 2. Cards for the "more bills" lever

Salespeople have no footfall of their own, so no salesperson is given a conversion
figure. Two things can be read fairly from the roster and the bills, always inside one
store over the same 28 days. A salesperson gets at most one of them (A before B), and
`engine/cards.py` then keeps one card per salesperson across all levers.

Nobody is compared across stores. A new store (BLR-05) gets no cards, and no card is
written at all unless the roster covers the 28 days and the 13 weeks before them.
The salesperson and the named peer must both have a roster row in the last 7 days.

**A. Busy-day attendance.** Busy days are Saturdays, Sundays and the festival and
wedding dates of the state calendar. Among people rostered on every day of the window:

- present on at most half the busy days of the typical (median) colleague, and at least
  3 busy days fewer;
- at least 3 such colleagues to compare with;
- named peer: the colleague present on the most busy days;
- action: "Today, ask your store manager to roster you on (the busy dates in the next 9
  days, festivals named) and move your weekly off to a weekday."
- "Those are the days most customers walk in" is added only if the store's own walk-ins
  per day were higher on busy days in the window, and only if the card stays within 60
  words.

**B. Bills per day present.** Bills carrying the person's id divided by their days
marked Present. The person and every colleague compared were present on at least 14 of
the 28 days, and there are at least 3 such colleagues. A card is written only when all
of these hold:

- material: at most 75% of the typical colleague's bills per day present;
- real: with `E = typical rate × days present`, `(bills − E) / sqrt(E) <= −2.5`. Bills
  are a count, so `sqrt(E)` is its chance spread. About 130 salespeople are looked at
  on each run; at −2.5 fewer than one of them is expected to pass by chance;
- a habit, not one month: present at least 20 days in the 13 weeks before the window
  and below the typical colleague (those present at least 20 days) there too;
- the card can be used tomorrow: the salesperson's usual weekly off is not tomorrow's
  weekday, and the named peer is the colleague with the most bills per day present who
  is not usually off tomorrow either;
- action: "Today, serve your first three walk-ins alongside (peer) and watch how each
  sale is closed, then take the next walk-in on your own."

"Today" on a card is the day after `as_of`: the engine runs after the close and the
card is read the next morning.

Bills per day present depends on how busy the store is, which is why it is only ever
compared between people in the same store over the same dates. It does not say why
someone bills less (counter, section and seniority are not in the data), so the card
states the figures and one thing to try, not a judgement.

**Priority** (rupees a week, used only to choose one card per salesperson):

- B: `(typical bills per day present − own) × own days present ÷ 4 × the store's average bill value` in the window;
- A: `(typical busy days present − own) ÷ 4 × typical bills per day present × the store's average bill value`.

On 31 Oct 2026 the lever offers 16 candidates: 2 attendance cards (BLR-03, the two
people named in its alert) and 14 bills-per-day cards in BLR-01, BLR-02, KNP-01,
LKO-01, PAT-01 and PAT-02.

## 3. Small additions to the lever's alerts

- **Look-ahead of 9 days.** The busy dates named in an action are those in the 9 days
  after `as_of` (it was 7). Nine days always reach the end of the next full weekend. On
  31 Oct 2026 the actions now name Sun 1 Nov, Sat 7 Nov and Sun 8 Nov, and say
  "(Diwali)" after 8 Nov. Section 1 and section 6 of METHOD.md still say 7.
- **`definition`** on each alert: one sentence, without figures, saying that conversion
  is bills divided by walk-ins on days with a usable door count and which windows the
  headline compares.
- **`not_judged_reason`** on a store block, for a new store ("Opened 10 Oct 2026; too
  new to compare with established stores") and for a store whose footfall is unusable
  on more than 20% of a window. Its figures are checks in the store's summary.

Nothing else in the 31 Oct 2026 more-bills alerts changed: same two alerts, same
figures, same rupees, same ranks.
