# Checks: how to recompute every figure from the raw CSVs

Every number the site shows is a `Check` in `web/public/data/latest.json`:

```json
{ "id": "...", "label": "...", "kind": "conversion",
  "params": { "store_ids": ["BLR-03"], "start": "2026-10-04", "end": "2026-10-31", "day_type": "all" },
  "value": 0.1071, "display": "10.7%" }
```

`kind` names a recipe below. `params` are its only inputs. `value` is the raw result.
`display` is the same value formatted for people. This page is enough to recompute
every `value` from the CSVs without reading the engine code.

## 1. Ground rules (apply to every recipe)

**Loading.** Read every CSV as text (`dtype=str`, no NA conversion). IDs are text.
Convert `footfall`, `qty`, `selling_price` to numbers. A blank footfall is "missing".

**As-of.** `as_of` is the top-level field of the JSON. Before anything else, drop
`bills` with `bill_date > as_of`, `bill_lines` of those bills, `footfall_daily` and
`roster_daily` rows with `date > as_of`, `salespeople` with `join_date > as_of` and
`stores` with `opened_on > as_of`. `calendar` is not cut (see `upcoming_busy_dates`).

**Windows.** `start` and `end` are dates, both inclusive.

**Store-day.** A (store, date) pair that has a `footfall_daily` row or at least one bill.
- `footfall` = the store's footfall that day (missing if there is no row or it is blank).
- `bills` = number of rows in `bills` with that `store_id` and `bill_date`.

**Valid store-day.** A store-day is **valid** when `footfall > 0` **and** `bills <= footfall`.
Otherwise it is **invalid**, for one of two reasons:
- `footfall_zero`: footfall is missing or 0;
- `bills_exceed_footfall`: footfall > 0 and bills > footfall.

Invalid store-days are left out of the numerator and the denominator of every
conversion figure, and out of walk-ins, bill value and day counts, as stated per recipe.

**Bill value.** For one bill: sum of `qty × selling_price` over its `bill_lines`
(packaging lines are ₹0 and change nothing).

**Busy day.** For a state and a date: the date is a Saturday or Sunday, **or** the
`calendar` row for that (date, state) has a non-blank `festival`, **or** has
`is_wedding_date = 1`. For a store, use the state in `stores.state`. For a
salesperson, use the state of their store in `salespeople.store_id`.

**`day_type`** (optional, default `"all"`): `"all"` = every day, `"busy"` = busy days
only, `"normal"` = days that are not busy.

**A store's salespeople.** Rows of `salespeople` with that `store_id` (after the as-of cut).

**Rounding.** Always round half up: `floor(x × 10^n + 0.5) / 10^n`.

**Median.** Sort the values; the middle one, or the mean of the two middle ones.

**Weekday order.** Monday, Tuesday, Wednesday, Thursday, Friday, Saturday, Sunday.

## 2. Store measures

| kind | params | value |
| --- | --- | --- |
| `bills_count` | `store_ids`, `start`, `end`, `day_type` | Total `bills` over the valid store-days of those stores in the window (of that day type). Integer. |
| `footfall_sum` | `store_ids`, `start`, `end`, `day_type` | Total `footfall` over the same valid store-days. Integer. |
| `conversion` | `store_ids`, `start`, `end`, `day_type` | `bills_count / footfall_sum` with the same params, rounded to 4 decimals. A fraction: 0.1071 means 10.71%. |
| `avg_bill_value` | `store_ids`, `start`, `end` | Sum of bill value of all bills on valid store-days in the window, divided by the number of those bills. Rupees, 2 decimals. |
| `walkins_per_week` | `store_ids`, `start`, `end` | For each store: `footfall on its valid store-days ÷ number of its valid store-days × 7`. Add the stores up. 1 decimal. |
| `valid_days` | `store_ids`, `start`, `end` | Number of valid store-days in the window. |
| `invalid_days` | `store_ids`, `start`, `end`, `rule` | Number of invalid store-days in the window. `rule` (default `"any"`) limits the count to one reason: `"footfall_zero"` or `"bills_exceed_footfall"`. |
| `bills_on_invalid_days` | same as `invalid_days` | Total `bills` on those same invalid store-days. |
| `two_proportion_z` | `store_ids`, `start`, `end`, `base_start`, `base_end`, `day_type` | See below. 2 decimals. Negative means the `start..end` window converts less. |
| `quietest_weekday` | `store_id`, `start`, `end` | Over the store's valid store-days in the window, the mean footfall of each weekday; the weekday with the lowest mean (a tie goes to the earlier weekday). A weekday name. |
| `day_count` | `state`, `start`, `end`, `day_type` | Number of calendar dates in the window of that day type for that state. |
| `upcoming_busy_dates` | `state`, `start`, `end` | The busy days (rule above) among the calendar dates `start..end`, as ISO dates joined by `", "`, in date order. `start..end` is the 7 days after `as_of`. This is the only recipe that reads calendar rows after `as_of`, and it is used only to name dates in an action. |

**`two_proportion_z`.** Let `b1`, `n1` = `bills_count`, `footfall_sum` for `start..end`
and `b0`, `n0` = the same for `base_start..base_end` (same `store_ids`, same `day_type`).

```
p  = (b1 + b0) / (n1 + n0)
se = sqrt( p × (1 − p) × (1/n1 + 1/n0) )
z  = (b1/n1 − b0/n0) / se
```

## 3. People measures (from `roster_daily` and `bills`)

| kind | params | value |
| --- | --- | --- |
| `present_days` | `salesperson_id`, `start`, `end`, `day_type` | Number of that person's roster rows in the window with `status = Present` (of that day type, using their store's state). |
| `peer_median_present_days` | `store_id`, `exclude_salesperson_ids`, `start`, `end`, `day_type` | Peers = the store's salespeople, minus the excluded ids, who have a roster row (any status) on **every** date of `start..end`. Median of their `present_days` with the same window and day type. 1 decimal. |
| `last_roster_date` | `salesperson_id`, `as_of` | The latest `date` of any roster row of that person (any status) on or before `as_of`. ISO date. |
| `bills_per_present_day` | `salesperson_id`, `start`, `end` | Number of bills with that `salesperson_id` and `bill_date` in the window, divided by `present_days` (day type `all`) in the same window. 2 decimals. Footfall and the valid-day rule play no part. |
| `peer_median_bills_per_present_day` | `store_id`, `exclude_salesperson_ids`, `start`, `end`, `min_present_days` | Peers = the store's salespeople, minus the excluded ids, with `present_days >= min_present_days` in the window. Median of their unrounded `bills_per_present_day`. 2 decimals. |
| `usual_off_weekday` | `salesperson_id`, `start`, `end` | Among that person's roster rows in the window with `status = Off`, the weekday that occurs most often (a tie goes to the earlier weekday). A weekday name. |
| `rostered_staff` | `store_id`, `date` | Number of the store's salespeople with a roster row (any status) on that date. |
| `median_staff_present` | `store_id`, `start`, `end`, `day_type` | For each date in the window (of that day type) on which the store has at least one roster row: the number of rows with `status = Present`. The median of those daily numbers, rounded half up to a whole number. |
| `footfall_per_present_staff` | `store_id`, `start`, `end`, `day_type` | Over the store's valid store-days in the window (of that day type) that also have at least one roster row for the store: total footfall ÷ total number of `Present` rows. 1 decimal. |

## 4. Rupees at stake

| kind | params | value |
| --- | --- | --- |
| `rupees_at_stake` | `benchmark_check_id`, `current_check_id`, `walkins_check_id`, `avg_bill_check_id` | See below. Whole rupees, a multiple of 100. Equals the alert's `rupees_at_stake_weekly`. |

The four params are ids of checks in the same alert. The figure is worked out from
those checks **as displayed**, so the line in `arithmetic.worked` multiplies out by hand:

```
B = benchmark conversion in percent, rounded to 1 decimal   (0.1324 → 13.2)
C = current conversion in percent, rounded to 1 decimal     (0.1071 → 10.7)
W = walk-ins a week, rounded to a whole number              (485.5 → 486)
V = average bill value, rounded to a whole rupee            (10092.04 → 10092)

rupees = (B − C) / 100 × W × V, rounded half up to the nearest 100
```

To avoid floating-point noise the engine works in tenths of a point:
`(round(B×10) − round(C×10)) × W × V / 1000`.

## 5. Display formats

| kind | display |
| --- | --- |
| `conversion` | percent with 1 decimal: `10.7%` |
| `avg_bill_value`, `rupees_at_stake` | whole rupees with Indian digit grouping: `₹1,22,600` |
| `bills_count`, `footfall_sum`, `walkins_per_week` | whole number with Indian digit grouping: `1,942` |
| `last_roster_date` | `14 Sep 2026` |
| `upcoming_busy_dates` | `Sun 1 Nov 2026, Sat 7 Nov 2026` |
| `bills_per_present_day`, `peer_median_bills_per_present_day`, `two_proportion_z` | 2 decimals |
| `footfall_per_present_staff` | 1 decimal |
| `peer_median_present_days` | 1 decimal, without a trailing `.0` |
| everything else | the value as it is |

## 5a. City-adjusted sizing and dated windows

| kind | params | recipe | display |
| --- | --- | --- | --- |
| `date_range` | start, end | the text `start..end` (start on or before end). It makes the dates quoted beside a figure a check. | `4 Oct 2026 to 31 Oct 2026` |
| `beyond_city_z` | store_ids, other_store_ids, start, end, base_start, base_end | p1, p0 = conversion of `store_ids` over `start..end` and `base_start..base_end`; q1, q0 = the same for `other_store_ids` (all over valid store-days, section 1). z = ((p1 − p0) − (q1 − q0)) ÷ √(Σ r(1 − r) ÷ n) over the four (rate r, walk-ins n). Unpooled. Negative = the store fell more than the others. 2 decimals, half up. | `-1.33` |
| `rupees_at_stake_city` | benchmark_check_id, current_check_id, city_benchmark_check_id, city_current_check_id, walkins_check_id, avg_bill_check_id | Each conversion in tenths of a point as displayed (12.3% → 123). city fall = max(0, city benchmark − city current). gap = (benchmark − current) − city fall. Rupees = gap × walk-ins a week (whole) × average bill (whole ₹) ÷ 1000, rounded half up to the nearest ₹100. | `₹61,700` |

A market note (`area_managers[].market_notes[]`) carries only existing kinds: `conversion`,
`two_proportion_z` (current window against the matching weeks last year), `date_range` and
`festival_name` for the two Dussehra dates used to align the years.

## 6. Where checks appear

- `area_managers[].alerts[].checks`: every number quoted in the alert's `headline`,
  `cause`, `action.text` and `arithmetic.worked` is the `display` of one of these checks.
  The engine refuses to send an alert that quotes a number without one.
- `stores[].summary`: current and baseline conversion, walk-ins a week and average
  bill value. A figure is left out when the store cannot be judged in that window
  (more than 20% of its store-days invalid) or, for the baseline, when the store is new.
- `data_issues[].checks`: the invalid days and the bills made on them.
- `alerts[].follow_up` names a `kind` and `params` from this page. A week later the same
  recipe is run on the follow-up week and compared with `baseline_value` and `target_value`.
