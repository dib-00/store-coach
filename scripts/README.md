# scripts

## verify.py: check every figure against the raw CSVs

`verify.py` is the independent check on the engine. It reads the engine's JSON and the
raw CSVs, recomputes every figure, and fails if anything differs.

It was written from [docs/CHECKS.md](../docs/CHECKS.md) alone. It imports nothing from
`engine/` and shares no code with it, so a bug in the engine cannot hide in both places.

```
python -X utf8 scripts/verify.py                         # web/public/data/latest.json against data/csv
python -X utf8 scripts/verify.py --file F --data-dir D   # any output, any CSV folder
python -X utf8 scripts/verify.py --strict                # warnings also fail
```

It needs only Python and pandas. It makes no network calls.

### Exit code

| Code | Meaning |
| --- | --- |
| 0 | Everything matches. |
| 1 | At least one mismatch, one broken rule, or one check kind with no recipe here. An unknown kind is a failure, never a skip. |
| 2 | It could not run: a CSV or the JSON is missing or unreadable. |

### What it checks

1. **Every check.** It walks the whole JSON. Any object with `id`, `kind`, `params`,
   `value` and `display` is a check, wherever it sits. The value is recomputed from the
   CSVs with the recipe for its `kind`. Params that the recipe does not document are a
   failure.
2. **Display.** Each check's `display` must be its `value` in the documented format
   (`10.7%`, `₹1,22,600`, `14 Sep 2026`).
3. **Rupees at stake.** An alert's `rupees_at_stake_weekly` must equal its own
   rupees-at-stake check. The `arithmetic.worked` line must show every input check and
   must multiply out to that figure.
4. **Numbers in text.** Every number in an alert's `headline`, `cause`, `action.text`
   and `arithmetic.worked` must appear in the display of one of that alert's checks.
   The same holds for a card's `text` and a follow-up's `verdict`. Store, salesperson
   and SKU ids (`LKO-02`, `SP1018`) are not numbers.
5. **Weekly cap and ranking.** No manager has more alerts than `max_alerts_per_week` in
   `area_managers.csv`. Alerts are ordered by rupees, ties by `alert_id`, with ranks 1, 2, 3.
   Nothing held back is bigger than something sent. Each alert's stores belong to that manager.
6. **Cards.** `text` is 60 words or fewer, `word_count` is right, the peer is a
   different salesperson of the same store in `salespeople.csv`, and the text names them.
7. **Nothing after as-of.** The CSVs are cut at `as_of` before anything is computed, so
   a figure built on a later row no longer matches. In addition, no check param, check
   value, window, data issue or follow-up may carry a date after `as_of`. The one
   documented exception is `upcoming_busy_dates`, whose window must be exactly the
   7 days after `as_of`.
8. **Follow-up baseline.** Each alert's `follow_up.baseline_value` is recomputed from
   its `kind` and `params`.

### Tolerance

Every figure is worked out in exact fractions and rounded half up to the decimals its
recipe documents. The JSON value must equal that to within 1e-9, which only absorbs how
a decimal is stored as a float. Whole numbers, dates and names must be equal.

A figure that sits exactly on a rounding half (472.25 to one decimal) is rounded up to
472.3, as the rule says. Plain float arithmetic can land at 472.2499… and round down.
The script flags that case in the mismatch line.

### Output

One line per check kind and per rule with counts, then every mismatch with its id,
kind, the value expected from the CSVs and the value found in the JSON, then warnings.

```
check   conversion                                 46 checked    46 ok    0 mismatch
rule    alert text numbers have a check             8 checked     8 ok    0 mismatch
MISMATCH [walkins_per_week] id=store:PAT-02:walkins_per_week_current kind=walkins_per_week
         expected from CSV: 472.3
         found in JSON:     472.2
RESULT   125 checks recomputed, 1 mismatch; 472 rule tests, 0 broken; 1 warnings -> FAIL
```

Warnings do not fail the run unless `--strict` is given. They cover things the
documents do not require: numbers in data-issue text with no check, a follow-up target
that is not the value of a check, a check repeated with identical content.

### Adding a check kind

One function in `verify.py`, in the registry. Nothing else changes.

```python
@recipe("items_per_bill", required=("store_ids", "start", "end"), display=fmt_2dp)
def items_per_bill(d, p, ctx):
    ...
    return rhu(Fraction(items, bills), 2)
```

- `d` is the CSV pack after the as-of cut (`class Data`). `d.read("items")` loads any other CSV as text.
- `p` is the check's params. List them in `required` and `optional`.
- `ctx.value_of(check_id)` recomputes another check of the same alert or card.
- Return an `int`, a `Fraction` rounded with `rhu(x, decimals)`, or a `str`.
- Raise `CannotCompute("why")` when the recipe has no answer.
- `display` is the formatter for section 5 of CHECKS.md.
- A kind that carries an alert's rupees at stake also sets `rupees_step` (the step the figure is rounded to).
- A kind the documents allow to read the calendar after `as_of` sets `future_calendar=True` and pins its own window, as `upcoming_busy_dates` does. Every other kind fails on a date after `as_of`.

Write the recipe from the document, not from the engine. If the document does not
reproduce the engine's value, that is a finding to report, not something to tune away.

### How the documents were read where they leave a choice

- `day_count` counts every date in the window. `calendar.csv` has a row for every date
  and state, so counting calendar rows gives the same number.
- `median_staff_present` and `footfall_per_present_staff` take "the store has a roster
  row" to mean `roster_daily.store_id`. In this data it always equals the person's
  store in `salespeople.csv`; the script warns if it ever does not.
- `walkins_per_week` over several stores adds the unrounded store figures and rounds once.
- Two footfall rows for one store and date stop the script (exit 2): no recipe says how to combine them.

### Tests

`tests/test_verify.py` builds a tiny CSV pack and a JSON whose figures were worked out
by hand. The clean file passes. Then one thing at a time is broken (a value, a display,
an unknown kind, a number with no check, rupees, the cap, a card, a date after as-of)
and each time the script must exit non-zero and name it. No real data is needed.

```
python -X utf8 -m pytest tests/test_verify.py
```
