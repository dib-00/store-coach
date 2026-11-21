# Method: the "bigger baskets" lever

Items per bill, and what goes into the basket. The recipe for every figure is in
[CHECKS-baskets.md](CHECKS-baskets.md); the thresholds below are the constants at the top
of `engine/baskets.py`.

All figures use **product lines only**: carry bags, covers and gift boxes (`is_packaging = 1`,
₹0) are left out. Safa, Mala and Stole are separate categories. Comparisons are always inside
one store (a salesperson against colleagues), or a store against its own earlier periods.
Regional taste is never a problem: no store or person is compared with another city.
The new store BLR-05 is not judged.

## What is tested

The current window is the 90 days ending on as-of.

| Test | Who against whom | Bar | Also needed |
| --- | --- | --- | --- |
| **Missing the obvious pair** (safa, mojari or mala with a sherwani; jacket with a kurta set) | the store's attach rate now against its own nine months before, and against the same 90 days a year earlier | z ≤ −3.2 against the nine months, and z ≤ −2.0 against a year earlier | 100 or more main-item bills in each window; at least 20% below the benchmark |
| **Discounts well above the store's norm** | each salesperson against the other salespeople of the store still on the roster | z ≥ 3.5 on the share of discounted bills | discount rate at least 2 points of MRP above colleagues; 30 bills, colleagues 60 |
| **Low items per bill** | each salesperson against colleagues in the same store (the best colleague is left out of the yardstick when there are three or more) | Welch z ≤ −3.5 | at least 15% fewer items per bill; 30 bills, colleagues 60 |
| **Avoiding a category the store buys** | each salesperson's share of bills with that category against colleagues, over 365 days | z ≤ −4.0 | own share at most half the colleagues' over the year **and** over the last 90 days; 100 bills; 10 expected |

Why the bars are high: about 115 salespeople are compared in each family of tests every
run, and there are 8 categories, so a bar like z = 2 would flag several people every week
by chance alone. One-sided 5% shared across the comparisons gives the figures in the table.

Inside a store already flagged for a missing pair, the salespeople who drive the fall are
named only at z ≤ −2.0 on their own attach rate and with 30 or more main-item bills.

### Small stores: the 180-day group test

A B-grade store can have fewer than 60 colleague bills in 90 days, so nobody there can be
compared. When the 90-day pass flags nobody in a store, the engine looks at the last 180
days: the salespeople whose items per bill are at least 15% below the store's best seller
are tested **together, as one group**, against the rest of the store, at the same bar
(Welch z ≤ −3.5). It is one test per store, so the bar stays strict. On 31 Oct 2026 it
fires in one store only: MYS-02, where Santosh B. and Mohan Y. average 1.37 and 1.36 items
a bill against 1.86 for Madhu G. (z −3.80).

## Rupees at stake (a week)

| Test | Rupees |
| --- | --- |
| Missing pair | (benchmark attach − current attach) × main-item bills a week × average value of the add-on |
| Discounts | (own discount rate − colleagues') × own sales at MRP a week. **Margin given away**, not sales lost. |
| Low items per bill | (colleagues' items per bill − own) × own bills a week × average value of an item at the store |
| Category avoided | (colleagues' share − own share) × own bills a week × (average bill with the category − without) |

Each is worked out from the figures as displayed and rounded to the nearest ₹100, so the
arithmetic on the alert multiplies out by hand.

## Actions and cards

Every action names the people, the pair or category, and the day. The day is "Today", or
the first of the next seven days on which nobody named has their usual weekly off. The
named role model is a colleague in the same store, still on the roster, who is not being
corrected on another lever. Cards repeat the one behaviour, name that colleague, and give
one thing to do today, in 60 words or fewer.

## Results on 31 Oct 2026

| Store | Test | People | Rupees a week |
| --- | --- | --- | --- |
| KNP-01 | Jacket with kurta set: 14.4% now, 23.5% in the nine months before, 24.2% a year earlier | drivers named on the alert | ₹8,100 |
| PAT-01 | Discounts | Manoj N. and Sanjay K. (about 7% and 6% of MRP against about 1–2% for colleagues) | ₹7,000 |
| BLR-02 | Indo-Western avoided | Suresh K. (no Indo-Western in his bills against about 5.5% for colleagues) | ₹6,400 |
| MYS-02 | Low items per bill (180-day group test) | Santosh B. and Mohan Y., model Madhu G. | ₹12,600 |

LKO-02's fall in basket size after Imran C. (SP1018) left in September is not raised on
this lever: it comes from his own large baskets leaving with him, and his leaving is already
the cause of the LKO-02 conversion alert.
