# Recipes for the "more repeat" checks

Every figure the repeat lever shows is a Check with a `kind` and `params`. This page says how to
recompute each kind from the raw CSVs using only its params. Nothing here needs the engine's code.

All kinds below start with `repeat_`. They are registered by `engine/repeat.py`.

## Shared rules (apply to every kind)

**Files.** `bills.csv` (bill_id, bill_date, store_id, salesperson_id, customer_id), `bill_lines.csv`
(bill_id, sku_id, qty, mrp, selling_price), `items.csv` (sku_id, category, is_packaging). Read every
column as text; convert `qty` and `selling_price` to numbers.

**As-of.** Drop every bill dated after the file's `as_of`. Nothing later is ever used.

**Placeholder customers.** A customer id is a placeholder, not a person, when it is blank, or is on
25 or more bills, or has bills at 6 or more different stores (counted over all bills up to as-of).
Remove every bill of a placeholder id before doing anything else. Each check that depends on this
carries the ids removed in `params.exclude_customer_ids`, so you can simply drop bills whose
`customer_id` is in that list. In this data the list is `["C99999999"]`. The two
`repeat_placeholder_*` kinds are the only ones that look at those bills.

**First bill.** Sort a customer's bills by `bill_date`, then by `bill_id` (text order). The first
row is the customer's first bill. The customer **belongs to** the `store_id` and `salesperson_id`
on that row, and that row's `bill_date` is the customer's **first date**. (In this data no customer
has two bills on their first date, so the tie-break never decides anything.)

**Gap.** For any bill, gap = bill date minus the customer's first date, in whole days. The first
bill has gap 0.

**Group.** `store_ids` (always present) and `salesperson_ids` (optional) pick customers by the
store and salesperson they belong to: the first bill's store is in `store_ids` and, when
`salesperson_ids` is present, the first bill's salesperson is in it. `peer_store_ids` and
`peer_salesperson_ids` pick the comparison group the same way. The engine never lets the two
groups overlap.

**Cohort.** `first_bill_to` (always present on cohort kinds) and `first_bill_from` (optional): keep
customers whose first date is on or before `first_bill_to` and, when `first_bill_from` is present,
on or after it. The engine sets `first_bill_to` = as-of minus 180 days, so every customer has had
the whole return window.

**Returned.** A customer returned when at least one of their bills, at ANY store and with any
salesperson, has `min_gap_days` <= gap <= `max_gap_days` (30 and 180).

**Rounding.** "Half up" means floor(x × 10^n + 0.5) / 10^n. For a negative number this rounds
towards plus infinity (−4.255 becomes −4.25).

**Month and quarter.** The month of a customer is the first 7 characters of the first date
(`2025-03`). Its quarter is the calendar quarter of that month (`2025Q1` = Jan to Mar).

## Cohort kinds

| kind | value |
|---|---|
| `repeat_customers` | Number of customers in the group and the cohort. |
| `repeat_returned` | Of those, the number who returned. |
| `repeat_return_rate` | `repeat_returned` / `repeat_customers`, half up to 4 decimals (0.1587). Null when there are no customers. |

Hand check at as-of 2026-10-31 (`first_bill_to` 2026-05-04): SP1110 at BLR-01 has 605 customers,
96 returned, 0.1587. BLR-01 as a whole has 7,910 customers, 454 returned, 0.0574.

### `repeat_fair_rate`

The return rate the subject would have if each of its first-bill months returned at the peers'
rate for that month. Params: group, peer group, cohort, gap window.

1. For the subject group, count customers n_S(m) per first-bill month m. For the peer group, count
   customers n_P(m) and returned customers r_P(m) per month.
2. If any month with n_S(m) > 0 has n_P(m) = 0, the value is null.
3. expected = sum over months with n_S(m) > 0 of n_S(m) × r_P(m) / n_P(m).
4. value = expected / (sum of n_S(m)), half up to 4 decimals.

### `repeat_z`

Cochran-Mantel-Haenszel z, stratified by first-bill month. Same params as `repeat_fair_rate`.
Positive means the subject's customers return more than the peers'.

1. Per month m with n_S(m) > 0 (null if any such month has n_P(m) = 0, as above), with r_S(m) and
   r_P(m) the returned customers on each side: N = n_S + n_P, R = r_S + r_P.
2. A = sum of r_S(m). E = sum of n_S × R / N. V = sum of n_S × n_P × R × (N − R) / (N² × (N − 1)),
   leaving out a month with N = 1.
3. value = (A − E) / sqrt(V), half up to 2 decimals. Null when V = 0.

### `repeat_quarters`

Extra params: `min_customers` (30) and `count` (`compared`, `ahead` or `behind`).

1. Add the subject's and the peers' customers and returned customers up by first-bill quarter.
2. A quarter is compared when the subject has at least `min_customers` customers in it AND the
   peers have at least `min_customers`.
3. In a compared quarter the subject is ahead when r_S / n_S > r_P / n_P, behind when it is lower
   (compare r_S × n_P with r_P × n_S to avoid rounding), neither when equal.
4. value = number of quarters compared, ahead or behind, as `count` says.

## Kinds that use a date window

### `repeat_new_customers_per_week`

Params: group, `start`, `end`. Count customers of the group whose first date is from `start` to
`end` inclusive. Divide by (number of days from `start` to `end` inclusive) / 7. Half up to 1
decimal. The engine uses the 91 days ending at as-of, so the divisor is 13.

### `repeat_return_bill_count` and `repeat_avg_return_bill_value`

Params: `store_ids`, `start`, `end`, `min_gap_days`, `max_gap_days`. Here `store_ids` is the store
the BILL was made at (not the store the customer belongs to), and there is no salesperson filter.

Take bills made at one of `store_ids`, dated `start` to `end` inclusive, with `min_gap_days` <= gap
<= `max_gap_days`. The count is `repeat_return_bill_count`. A bill's value is the sum of
qty × selling_price over its lines (packaging lines are ₹0). `repeat_avg_return_bill_value` is
the mean value of those bills, half up to 2 decimals; null when there are none. The engine uses the
364 days ending at as-of.

### `repeat_call_list`

Params: group, `first_from`, `first_to`, `no_bill_through`, optional `category`.

Count customers of the group whose first date is from `first_from` to `first_to` inclusive and who
have exactly one bill dated on or before `no_bill_through` (so: no second bill of any kind, at any
store). When `category` is present, keep only customers whose first bill has at least one line
whose SKU has that `category` in `items.csv` and `is_packaging` not equal to 1.

### `repeat_weekly_returns_per_100` (the follow-up measure)

Params: group, `start`, `end`, `min_gap_days`, `max_gap_days`.

1. Numerator: bills dated `start` to `end` inclusive, made at ANY store, with `min_gap_days` <= gap
   <= `max_gap_days`, whose customer belongs to the group. No cohort date limit.
2. Eligible customers: customers of the group whose first date is from (`end` − `max_gap_days`) to
   (`end` − `min_gap_days`) inclusive. These are the customers inside their return window on `end`.
3. value = numerator / (days from `start` to `end` inclusive / 7) / eligible × 100, half up to 2
   decimals. Null when there are no eligible customers.

It is a per-week figure, so a 91-day window (the baseline on the alert) and a 7-day window (the
follow-up) are comparable. **The follow-up replaces `start` and `end` only.** `min_gap_days`,
`max_gap_days`, `store_ids`, `salesperson_ids` and `exclude_customer_ids` stay as they are.

### `repeat_date_offset`

Params: `date`, `days`. value = `date` plus `days` days (days is negative for the past), as
YYYY-MM-DD. Used for the dates quoted in text: the two ends of the call list (as-of − 60, − 44 or
− 37, and as-of − 30) and the start of the latest 52 weeks of the cohort (as-of − 543).

## Rupees

### `repeat_rupees_at_stake`

Self-contained: params are `fair_rate`, `own_rate` (fractions, as stored on the two rate checks
named in `arithmetic.input_check_ids`), `new_customers_per_week` and `avg_return_bill_value`.

1. T(x) = (round(x × 10000) + 5) integer-divided by 10. This is the rate in tenths of a percentage
   point, half up: 0.0773 gives 77, shown as 7.7%.
2. gap = T(fair_rate) − T(own_rate).
3. n10 = new customers a week × 10, half up to a whole number. v = bill value half up to a whole rupee.
4. raw = gap × n10 × v / 10000. value = raw / 100 half up to a whole number, × 100.

This is exactly "the displayed gap × the displayed customers × the displayed rupees, to the nearest
₹100". Example: (7.7% − 2.8%) × 10.8 × ₹9,341 = 49 × 108 × 9341 / 10000 = 4,943.3, shown as ₹4,900.
On a role-model alert `fair_rate` holds the role model's rate and `own_rate` the colleagues'.

## Placeholder

| kind | params | value |
|---|---|---|
| `repeat_placeholder_bills` | `customer_id` | Number of bills (up to as-of) carrying that customer id. |
| `repeat_placeholder_stores` | `customer_id` | Number of different `store_id` on those bills. |
| `repeat_placeholder_days` | `customer_id` | Number of different `bill_date` on those bills. |

At as-of 2026-10-31: C99999999 has 1,833 bills at 19 stores.

## Display

| kind | display |
|---|---|
| `repeat_return_rate`, `repeat_fair_rate` | percent to 1 decimal, half up from the 4-decimal value: 0.1587 is `15.9%` |
| `repeat_customers`, `repeat_returned`, `repeat_quarters`, `repeat_call_list`, `repeat_return_bill_count`, `repeat_placeholder_*` | whole number, Indian digit grouping: `7,910` |
| `repeat_z`, `repeat_weekly_returns_per_100` | 2 decimals: `-4.26`, `0.14` |
| `repeat_new_customers_per_week` | 1 decimal: `10.8` |
| `repeat_avg_return_bill_value`, `repeat_rupees_at_stake` | whole rupees, half up, Indian grouping: `₹9,341` |
| `repeat_date_offset` | `1 Sep 2026` |

## Which checks an alert carries

| check id ends with | kind | what it is |
|---|---|---|
| `customers`, `returned`, `return_rate` | cohort kinds | the subject over the whole cohort |
| `fair_rate`, `z` | `repeat_fair_rate`, `repeat_z` | subject against peers, same first-bill months |
| `quarters_compared`, `quarters_ahead` or `quarters_behind` | `repeat_quarters` | consistency across quarters |
| `recent_from` | `repeat_date_offset` | start of the latest 52 weeks of the cohort |
| `return_rate_recent`, `fair_rate_recent` | rate kinds with `first_bill_from` | the two rates the rupees use |
| `new_customers_per_week`, `return_bill_count`, `avg_return_bill_value`, `rupees_at_stake` | as named | the rupee line |
| `call_list`, `call_list_sherwani`, `call_from`, `call_to` | `repeat_call_list`, `repeat_date_offset` | the calls to make today (on a role-model alert the list ids end with the colleague's id) |
| `peer_rate` | `repeat_fair_rate` with the coach as the only peer | the coach's customers over the subject's months |
| `weekly_returns`, `weekly_returns_benchmark` | `repeat_weekly_returns_per_100` | follow-up baseline and target |

`peer_rate` reads: params `store_ids` / `salesperson_ids` are the person the alert is about,
`peer_salesperson_ids` is the coach; the value is the coach's month-by-month return rate applied to
the subject's mix of months. A card's `fair_rate` check is the same thing with the named peer.
