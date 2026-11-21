# Method: the "more bills" lever

Conversion = bills ÷ walk-ins. This page says how the engine decides that a store has a
conversion problem, how it names the cause, how it builds the action and how it puts
rupees on it. The recipes for every figure are in [CHECKS.md](CHECKS.md).

The engine is deterministic: no LLM, no network, no randomness. Text comes from
templates filled with computed values.

## 1. What the engine is allowed to see

`--as-of` is applied once, in `engine/load.py`. Bills, bill lines, footfall and roster
rows dated after it are dropped, as are salespeople who joined and stores that opened
after it. Nothing downstream can reach a later row. `tests/test_as_of.py` proves it.

The calendar (festivals, wedding dates) is published in advance, so it is not cut. Its
future rows are used for one thing only: naming the busy days in the 7 days after as-of
inside an action ("Sun 1 Nov and Sat 7 Nov"). They are never used to measure anything.

There is no time of day anywhere in the data, so the engine never states hours. It
works in dates, weekdays and names.

## 2. Days that cannot be right

A store-day is valid only when `footfall > 0` and `bills <= footfall`. Anything else is
left out of both the bills and the walk-ins of every conversion figure, and is listed
under `data_issues`. It never becomes an alert.

- A day with bills but zero or blank footfall is a broken door counter, not a 0% or an
  infinite conversion.
- A day with zero footfall and zero bills is also left out. It adds nothing to
  conversion either way, and counting it would understate walk-ins a week.
- If more than 20% of a store's days in a window are invalid, the store's conversion is
  not judged in that window at all, and the data issue says so. With that much missing,
  the days that remain are not a fair sample (weekends may be over- or under-represented).

The rule is general. On 31 Oct 2026 it catches PAT-03: footfall 0 on 12 days
(5 to 16 Oct) with 24 bills on them. That is 12 of 28 days in the current window, so
PAT-03 is not judged.

## 3. Fair comparison

Same store first, then city, then state. Never the whole country.

- Current window: the 28 days ending on as-of. Baseline: the 91 days before it.
- A store that opened less than 180 days before as-of is new (`is_new_store`). It is
  not judged and is not part of any city figure. BLR-05 opened on 10 Oct 2026.
- Same month last year is not used. Festivals move (Diwali was 20 Oct in 2025 and is
  8 Nov in 2026), so the months are not like for like.
- Footfall roughly doubles in October and November. That is the season, not a problem:
  conversion stays in its usual band while footfall swings. The engine alerts on
  conversion, never on footfall.

In this lever every alert is benchmarked on the same store's own earlier weeks, so the
city and state steps were not needed. A city is only used to recognise a market-wide fall.

## 4. When is a drop real?

Small stores are noisy. A B store has 250 to 600 walk-ins a month, so its conversion
moves by two or three points from month to month by chance. The engine therefore asks
two things of every drop:

1. **Statistically real.** A two-proportion z test on bills ÷ walk-ins, current against
   benchmark.
2. **Material.** Current conversion at least 10% below the benchmark (for example
   13.2% to below 11.9%).

Two thresholds are used, for two different situations.

**The scan (z ≤ −2.9).** Every run tests every established store and every city: 19
stores and 6 cities, 25 tests, with nothing to say in advance which one should have
moved. At z ≤ −2.9 (one-sided p ≈ 0.002) the chance of even one false alert in a run is
about 5%. A looser bar fires on noise: at z ≤ −2 a store-by-store scan flagged at least
one store in close to half of 74 weekly back-test dates (Jun 2025 to Oct 2026).

**A dated cause (z ≤ −2.0).** When the roster shows a specific event in a specific
store (a strong seller's last day, the week two people began missing shifts), there is
one test, chosen by the event and not by the result: conversion since that date against
the 13 weeks before it. One test needs a lower bar (one-sided p ≈ 0.023), and it comes
on top of roster evidence that is not statistical at all.

### Why the dated test is needed (a deviation from the default windows)

The default "28 days against the previous 91" loses a problem once it is more than four
weeks old, because the bad weeks slide into the baseline. On 31 Oct 2026:

| Store | 28 days vs previous 91 | Since the cause began vs 13 weeks before |
| --- | --- | --- |
| BLR-03 | 10.7% vs 12.3%, z = −1.7 | 10.5% vs 13.2%, z = −3.40 |
| LKO-02 | 10.5% vs 12.0%, z = −1.6 | 10.4% vs 12.3%, z = −2.23 |

Both problems started in September. On the default windows BLR-03 stood at z ≈ −2.8 and
−2.9 on 3 and 10 Oct and then faded while nothing had been fixed. So for a dated cause the benchmark is the
same store in the 13 weeks before the cause began, and the test runs from the day it
began to as-of. `windows` in the JSON still holds the default pair; each alert's own
windows are in its checks and in `benchmark_basis`.

### Back-test

Run at 22 weekly as-of dates, 6 Jun to 31 Oct 2026 (the roster period):

- the scan sent nothing in any run;
- BLR-03 (missed shifts) is raised on every run from 26 Sep, three weeks after it began;
- LKO-02 (salesperson left) is raised on every run from 10 Oct;
- no other store is alerted on any date.

Across 64 further weekly dates from Jun 2025 to Aug 2026 the scan found a candidate in
6 runs (three episodes: LKO-02 in Aug 2025, MYS-02 in Feb 2026, Patna in Apr 2026).
None was sent, because there is no roster before 1 May 2026 and so no action could be
built (section 6).

## 5. Causes, in order of preference

Salespeople have no footfall of their own, so they are compared on bills per day
present against colleagues in the same store. Present days come from the roster.

1. **`salesperson_left`.** There is no exit date in the data; someone who left simply
   stops appearing on the roster. A leaver is a person whose last roster row is 14 to
   91 days before as-of while the store's roster continues. They count as a strong
   seller if, in the 91 days up to their last day, they were present at least 20 days
   and made at least 1.25 times the bills per present day of the median colleague.
   Then the dated test: store conversion from the day after they left to as-of, against
   the 91 days up to their last day (cut at the first roster date if that is later).
2. **`missed_shifts`.** Among salespeople rostered on every day of the current window,
   a person is flagged when present on at most 80% of the colleagues' median days and
   at least 4 days fewer. The start is found by stepping back week by week (7-day
   blocks ending on as-of) while a flagged person had a short week: present on 4 or
   fewer days and at least one day fewer than the colleagues' median. Then the dated
   test: conversion from that start to as-of against the 91 days before it. The cause
   sentence adds weekend and festival days only when the flagged people worked at most
   half of the busy days their colleagues did and the store converted less on them.
3. **`thin_floor_busy_days`.** Only for a drop found by the scan. Walk-ins per
   salesperson present on busy days (weekends, festival and wedding dates) at least
   1.25 times that on other days in the current window, and busy-day conversion below
   the baseline's busy days (z ≤ −2.0).
4. **`conversion_falling`.** A drop found by the scan with none of the above.

**A whole city.** If a city's established stores, pooled, pass the scan test and more
than half of them fell, the area manager gets one alert with scope `city` and cause
`market_slowdown`. A store in that city then gets its own alert only if its drop is at
least 10 points (relative) deeper than the city's.

One alert per store for this lever: the first cause in the list that holds.

### What the engine looked at and did not alert on (31 Oct 2026)

- **BLR-01, LKO-01, KNP-01, PAT-01** show lower conversion in October than in their
  previous 13 weeks, with z of about −1.2, −1.8, −1.6 and −0.4. None is near the scan
  bar. Their cities pooled: Bengaluru −1.2, Lucknow −1.5, Kanpur −0.8, Patna 0.0, so
  it is not a city effect either. Walk-ins per salesperson present rose 1.8 to 2.2 times
  in every judged store, including the ones converting normally, so a "thin floor" cannot be told
  apart from the season. The engine says nothing about them.
- **MZF-01** converted 5.9% on its 9 busy days (29 bills from 491 walk-ins) against
  9.9% on other days. With 18 stores looked at, one showing this by chance is not
  surprising; it had its usual 4 people on the floor on busy days, and the store-level
  test is at z ≈ −1.3. No alert.
- **Other leavers** (LKO-01, KNP-03, PAT-04, BLR-02, BLR-03, BLR-04, May to July) left
  more than 91 days before as-of, outside the look-back. Checked by hand anyway: none
  was a strong seller (at most about 1.1 times the colleagues' median bills per present
  day) and none of their stores shows a real drop since (z between −1.5 and +0.2).

## 6. The action rule

An alert is sent only with an action the store can do today with the people it already
has, naming who, what and when. Every part is computed:

- **who**: named salespeople (the ones missing shifts; the strongest current sellers
  by bills per present day; people whose usual weekly off falls on a busy day);
- **when**: the busy dates in the 7 days after as-of, from the calendar;
- **what**: how many people to keep on the floor (the median number present on busy
  days in the benchmark weeks, never more than the store has on its roster), and which
  weekday each weekly off moves to (the person's own usual off day in the benchmark
  weeks, or the store's quietest weekday by walk-ins).

If the engine cannot fill who, what and when from the data, the alert is not sent and
the run log says why. This is why nothing can be sent for dates before the roster starts.

A second gate checks the text itself: every number in `headline`, `cause`,
`action.text` and `arithmetic.worked` must be the display of one of the alert's checks,
or the alert is not sent.

## 7. Rupees at stake

```
(fair benchmark conversion − current conversion) × walk-ins a week × average bill value
```

- benchmark conversion: the alert's benchmark window (section 4);
- current conversion, walk-ins a week and average bill value: the current 28 days;
- all over valid store-days. Bill value is the sum of qty × selling price over the
  bill's lines.

The figure is worked out from the inputs as displayed (conversion to 0.1 point,
walk-ins to a whole number, bill value to a whole rupee) and rounded to the nearest
₹100, so multiplying the displayed inputs gives the displayed result.

Walk-ins a week are the current, in-season level, so the rupee figure is higher in
October than it would be for the same gap in July. That is intended: it is what the
gap costs this week.

## 8. Ranking and the weekly cap

Each area manager's alerts are ranked by rupees at stake. `engine/rank.py:apply_cap`
keeps the top `max_alerts_per_week` from `area_managers.csv` (5) and moves the rest to
`held_back` with the reason. Ties are broken by `alert_id`, so the order never changes
between runs.

`alert_id` is stable for the same issue: `<store or city>:more_bills:<cause>[:<salesperson>]`.

## 9. Limits

- The roster covers 1 May to 31 Oct 2026 only. Causes that need it cannot be found before that.
- A leaver is inferred from the roster stopping. A long leave of 14 days or more would look the same.
- "Bills per present day" depends on how busy the store is, so it is only ever compared
  between people in the same store over the same dates.
- `stores[].salespeople[].active` means a roster row in the last 7 days up to as-of
  (when there is no roster at all: a bill in the current window).
- Only the first lever is built here. `cards` and `follow_ups` are empty.
