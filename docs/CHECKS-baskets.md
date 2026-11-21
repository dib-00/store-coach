# Check recipes: the "bigger baskets" lever

Every figure the basket lever shows is a Check (see `web/lib/types.ts`). This page gives the
recipe for each check kind the lever writes, using only the check's `params` and the raw
CSVs, so that anyone can recompute it without reading `engine/baskets.py`.
`scripts/verify.py` implements these recipes independently of the engine.

General rules from [CHECKS.md](CHECKS.md) apply: rows dated after the run's `as_of` are never
used; IDs are text; rounding is **half up** on the exact value (not banker's rounding).

## 1. The product bill

All basket kinds work on **product bills**:

- A bill from `bills.csv` made at one of `store_ids`, with `start <= bill_date <= end`
  (both dates included).
- When `salesperson_ids` is in the params, only bills whose `salesperson_id` is in that list.
  When `peer_salesperson_ids` is used (the `_z` kinds), the comparison group is the bills of
  those salespeople, same stores and dates.
- Only lines whose SKU has `items.is_packaging` not equal to 1 are used (carry bags and covers
  are left out). A bill with no such line is not a product bill. Every bill in the data has at
  least one product line.
- Line value = `qty × selling_price`. Line value at MRP = `qty × mrp`. A line is
  **discounted** when `selling_price < mrp`.
- A bill **has a category** when at least one of its product lines has that `items.category`.
  Safa, Mala and Stole are separate categories.
- The valid store-day rule of the conversion lever (footfall) plays no part here.

`window_days` = the number of days from `start` to `end`, both included.

## 2. Counts and shares

| kind | params | recipe | display |
| --- | --- | --- | --- |
| `window_days` | start, end | days from start to end, both included | whole number |
| `product_bills` | store_ids, start, end, [salesperson_ids] | number of product bills | whole number |
| `product_bills_per_week` | same | product_bills × 7 ÷ window_days, 1 decimal | `12.3` |
| `category_bills` | store_ids, start, end, category, [salesperson_ids] | product bills that have `category` | whole number |
| `category_bills_per_week` | same | category_bills × 7 ÷ window_days, 1 decimal | `1.7` |
| `category_bill_share` | same | category_bills ÷ product_bills, 4 decimals | percent, 1 decimal |
| `attach_rate` | store_ids, start, end, main_category, addon_category, [salesperson_ids] | of the product bills that have `main_category`, the share that also have `addon_category`, 4 decimals | percent, 1 decimal |
| `discount_rate` | store_ids, start, end, [salesperson_ids] | 1 − Σ line value ÷ Σ line value at MRP over the product lines of those bills, 4 decimals | percent, 1 decimal |
| `discounted_bill_share` | store_ids, start, end, [salesperson_ids] | product bills with at least one discounted line ÷ product bills, 4 decimals | percent, 1 decimal |

A share whose denominator is 0 cannot be computed (the engine writes no such check).

## 3. Values

| kind | params | recipe | display |
| --- | --- | --- | --- |
| `avg_addon_value` | store_ids, start, end, main_category, addon_category | over the product bills that have both categories: Σ line value of their `addon_category` lines ÷ number of those bills, 2 decimals | rupees, whole |
| `avg_bill_value_split` | store_ids, start, end, category, with_category | mean bill value (Σ product line value) of the product bills that have `category` (`with_category` true) or do not have it (false), 2 decimals | rupees, whole |
| `mrp_sales_per_week` | store_ids, start, end, [salesperson_ids] | Σ line value at MRP of the product bills × 7 ÷ window_days, whole rupees | rupees, whole |

## 4. Tests (z)

All three are the pooled two-proportion z of [CHECKS.md](CHECKS.md) section 2:
p = (k1 + k0) ÷ (n1 + n0), z = (k1 ÷ n1 − k0 ÷ n0) ÷ √(p (1 − p) (1 ÷ n1 + 1 ÷ n0)), 2 decimals.
Negative means the first group is lower.

| kind | first group (k1 of n1) | second group (k0 of n0) |
| --- | --- | --- |
| `attach_rate_z` | bills with `addon_category` among bills with `main_category`, dates `start..end` | the same, dates `base_start..base_end` (same stores and salespeople) |
| `category_bill_share_z` | category_bills of `salesperson_ids` out of their product bills | the same for `peer_salesperson_ids` |
| `discounted_bill_share_z` | discounted product bills of `salesperson_ids` out of their product bills | the same for `peer_salesperson_ids` |

Displayed to 2 decimals.

## 5. Rupees at stake (a week)

Each is computed from the other checks of the same alert **exactly as they are displayed**, so a
judge multiplying the figures in `arithmetic.worked` lands on the result. Rates are taken in
tenths of a percentage point as displayed (14.4% → 144), counts a week to 1 decimal, rupees
whole. The result is rounded half up to the nearest ₹100.

| kind | params (check ids) | recipe |
| --- | --- | --- |
| `attach_rupees_weekly` | benchmark_check_id, current_check_id, bills_per_week_check_id, addon_value_check_id | (benchmark − current, tenths) × main-item bills a week (1 decimal) × add-on value (whole ₹) ÷ 1000 |
| `discount_given_away_weekly` | own_check_id, norm_check_id, mrp_sales_check_id | (own − norm, tenths) × MRP sales a week (whole ₹) ÷ 1000. This is margin given away, not sales lost. |
| `category_rupees_weekly` | peer_check_id, own_check_id, bills_per_week_check_id, with_check_id, without_check_id | (peer − own, tenths) × bills a week (1 decimal) × (bill value with the category − bill value without, each whole ₹) ÷ 1000 |

The alert's `rupees_at_stake_weekly` equals the value of this check.

## 6. Items per bill (used by the small-store fallback)

| kind | params | recipe | display |
| --- | --- | --- | --- |
| `items_per_bill` | store_ids, start, end, [salesperson_ids] | Σ qty of product lines ÷ product bills, 2 decimals | `1.37` |
| `items_per_bill_z` | store_ids, start, end, peer_salesperson_ids, [salesperson_ids] | Welch z of items per bill, `salesperson_ids` against `peer_salesperson_ids`: (mean₁ − mean₂) ÷ √(s₁²/n₁ + s₂²/n₂) with sample variances (divide by n − 1), 2 decimals | `-3.37` |
| `avg_item_value` | store_ids, start, end, [salesperson_ids] | Σ line value ÷ Σ qty over the product lines, 2 decimals | rupees, whole |
| `items_rupees_weekly` | peer_check_id, own_check_id, bills_per_week_check_id, item_value_check_id | (peer − own items per bill, in hundredths as displayed) × bills a week (1 decimal) × item value (whole ₹) ÷ 100, rounded half up to the nearest ₹100 | rupees, whole |

`lines_above_mrp` (product lines with `selling_price > mrp`) is used only to decide that
discounts cannot be judged; it is not written into the output and has no recipe in
`scripts/verify.py`, so a run that emitted it would fail verification as an unknown kind.
