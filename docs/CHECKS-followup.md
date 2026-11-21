# Checks: follow-up, "more bills" cards and the small additions

This page adds to [CHECKS.md](CHECKS.md). The ground rules there (loading, the as-of
cut, valid store-days, busy days, rounding half up) apply unchanged.

## 1. New check kinds

| kind | params | value | display |
| --- | --- | --- | --- |
| `festival_name` | `state`, `date` | The `festival` cell, with surrounding spaces removed, of the `calendar` row with that `date` and `state`. Text. The check is only written when the cell is not blank. | the value as it is: `Diwali` |
| `store_opened_on` | `store_id` | `stores.opened_on` of that store. ISO date. | `10 Oct 2026` |

`festival_name` may read a calendar row after `as_of`, like `upcoming_busy_dates`. The
calendar is published in advance. It is used only to name a date in an action or on a
card, never to measure anything.

## 2. A changed window: `upcoming_busy_dates`

The recipe is unchanged (the busy days among the calendar dates `start..end`, in date
order, joined by `", "`). The window the engine asks for is now the **9** days after
`as_of` instead of 7: `start = as_of + 1 day`, `end = as_of + 9 days`. The window is in
the check's own `params`, so the check recomputes from them as before.

Why 9: the engine runs on any day of the week, and 9 days always reach the end of the
next full weekend. On Sat 31 Oct 2026 that names Sun 1 Nov, Sat 7 Nov and Sun 8 Nov,
and 8 Nov is Diwali. With 7 days the look-ahead stopped on Sat 7 Nov.

Each festival named in the text has its own `festival_name` check with id
`<alert or card prefix>:festival:<date>`.

## 3. Follow-up (`follow_ups[]`)

Check ids are `followup:<alert_id>:<slug>`. Every kind is one that already exists.
`raised` is `raised_as_of` (the earlier run), `as_of` is this run.

| slug | kind | params | what it is |
| --- | --- | --- | --- |
| `before` | the alert's `follow_up.kind` | the alert's `follow_up.params`, unchanged | The figure the alert showed. Equal to `follow_up.baseline_value` and to `before`. |
| `target` | the kind of the alert's own check that carried `follow_up.target_value` | that check's params, unchanged | The fair benchmark. Equal to `target`. |
| `days` | `day_count` | `state` of the first store, `start = raised + 1 day`, `end = as_of`, `day_type = "all"` | Days measured after the alert. 7. |
| `after` | the alert's `follow_up.kind` | the alert's `follow_up.params` with `start = raised + 1 day` and `end = as_of`; nothing else changes | The same recipe on the days after the alert. Equal to `after`. |
| `after_numerator` | `bills_count` | same params as `after` | Conversion only: the bills behind `after`. |
| `after_denominator` | `footfall_sum` | same params as `after` | Conversion only: the walk-ins behind `after`. |
| `after_invalid_days`, `after_valid_days` | `invalid_days` (`rule = "any"`), `valid_days` | the stores, `start = raised + 1 day`, `end = as_of` | Conversion only, and only when the week cannot be measured. |
| `earlier_week_1` .. `earlier_week_8` | the alert's `follow_up.kind` | the alert's `follow_up.params` with the window replaced by `raised − 7(k−1) − 6 days .. raised − 7(k−1) days` for `k = 1..8` | Only for a measure that is not a rate on a count (section 3.2). Weeks with no value are left out. |

`before` and `target` are copied from the earlier run, and they are only written when
the same recipe still gives the same value on this run's data. Their windows end on or
before `raised`, so later rows cannot change them.

`before_display`, `after_display` and `target_display` use the display format of the
measure's kind (CHECKS.md section 5 and the lever pages), so they read as the alert did.
When the week cannot be measured, `after` is `null` and `after_display` is
`"not measurable"`.

### 3.1 `moved`, for conversion (a rate on a count)

```
b  = after_numerator,  n  = after_denominator       (bills and walk-ins in the 7 days after)
b0 = before_numerator, n0 = before_denominator      (bills and walk-ins behind the figure when raised;
                                                     same params as the alert's follow_up)
se_after  = sqrt( (b/n)   × (1 − b/n)   / n  )
se_before = sqrt( (b0/n0) × (1 − b0/n0) / n0 )
noise  = 2 × sqrt( se_before² + se_after² )         (2 standard errors of after − before)
change = after − before                             (before − after when higher_is_better is false)

improved    if change > 0 and  change >= noise
worse       if change < 0 and −change >= noise
no_change   otherwise
```

`after` and `before` are the check values (fractions to 4 decimals). `noise` is not rounded.
Why 2 and not 1: before and after are separate samples, so their errors add, and one standard
error of the week alone would call a move on about one quiet week in three.

`not_measurable`, for conversion, when for any store of the alert the window
`raised + 1 day .. as_of` has no valid store-day or more than 20% of its store-days are
invalid (the same rule that stops an alert, CHECKS.md section 1), or when the recipe
gives no value.

Worked, 31 Oct 2026, LKO-02: change = +0.0168 (0.0975 to 0.1143), which is under 2 standard
errors of the difference, so `no_change`. BLR-03: change = −0.0167 (0.1111 to 0.0944), also
under the bar, so `no_change`. One week of a small store's walk-ins rarely settles anything,
and the verdict says so.

### 3.2 `moved`, for any other measure

There is no counting rule to give a standard error, so the noise is how much the same
7-day figure moved in the weeks before the alert:

```
w1..w8 = the earlier_week checks that have a value
noise  = 2 × sample standard deviation of those values (divide by count − 1)
```

Then the same three lines as in 3.1. With fewer than 4 earlier weeks the result is
`not_measurable`. When every earlier week has the same value (usually nought, as for a
salesperson's share of returning customers), the standard deviation is 0, a single bill would
look like a jump, and the result is also `not_measurable`. The verdict says why in each case.

### 3.3 The verdict

One template, filled with check displays only:

```
<metric_label> was <before> when raised and <after> in the <days> days after
(<after_numerator> bills from <after_denominator> walk-ins); the target is <target>. <ending>
```

The bracket is written for conversion only. If `metric_label` itself quotes a number
that no check shows, the sentence starts with "The figure" instead (the label is printed
beside it). The ending says improved, worse or no change, and always that one week is a
small sample. It never says the action caused the change.

## 4. Cards for the "more bills" lever (`cards[]`, `lever = "more_bills"`)

Check ids are `card:<store_id>:<salesperson_id>:more_bills:<slug>`. `cur` is
`windows.current` (28 days ending on `as_of`).

**Attendance card**

| slug | kind | params |
| --- | --- | --- |
| `busy_days_present` | `present_days` | the salesperson, `cur`, `day_type = "busy"` |
| `busy_days_in_window` | `day_count` | the store's state, `cur`, `day_type = "busy"` |
| `peer_busy_days_present` | `present_days` | the named peer, `cur`, `day_type = "busy"` |
| `typical_busy_days_present` | `peer_median_present_days` | the store, `exclude_salesperson_ids = [the salesperson]`, `cur`, `day_type = "busy"` |
| `upcoming_busy_dates` | `upcoming_busy_dates` | the store's state, `as_of + 1 .. as_of + 9` |
| `festival:<date>` | `festival_name` | the store's state, that date |

**Bills-per-day card**

| slug | kind | params |
| --- | --- | --- |
| `days_in_window` | `day_count` | the store's state, `cur`, `day_type = "all"` |
| `bills_per_present_day` | `bills_per_present_day` | the salesperson, `cur` |
| `peer_bills_per_present_day` | `bills_per_present_day` | the named peer, `cur` |
| `typical_bills_per_present_day` | `peer_median_bills_per_present_day` | the store, `exclude_salesperson_ids = [the salesperson]`, `cur`, `min_present_days = 14` |
| `present_days` | `present_days` | the salesperson, `cur`, `day_type = "all"` |

Who gets a card, and how `priority` is worked out, is in
[METHOD-followup.md](METHOD-followup.md). `priority` is used only to choose between a
salesperson's candidate cards across levers and is not written to the JSON.

## 5. Store blocks (`stores[]`)

`not_judged_reason` is present only when the store is not judged this run. Every figure
in it is a check in the same store's `summary`:

| id | kind | params | when |
| --- | --- | --- | --- |
| `store:<id>:opened_on` | `store_opened_on` | `store_id` | new store (opened less than 180 days before `as_of`) |
| `store:<id>:invalid_days_current`, `store:<id>:valid_days_current` | `invalid_days` (`rule = "any"`), `valid_days` | the store, `windows.current` | more than 20% of the store-days in the current window are invalid |
| `store:<id>:invalid_days_baseline`, `store:<id>:valid_days_baseline` | the same | the store, `windows.baseline` | the current window is usable but the baseline is not |

## 6. `definition`

`alerts[].definition` (more-bills alerts), `cards[].definition` and
`follow_ups[].definition` (copied from the alert) say in words how the figure is
measured. They quote no figures, so they need no checks.
