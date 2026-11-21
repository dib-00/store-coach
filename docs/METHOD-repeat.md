# Method: the "more repeat" lever

Code: `engine/repeat.py`. Recipes for every figure: `docs/CHECKS-repeat.md`. Tests: `tests/test_repeat.py`.

## The one definition

Used by every figure, printed in `definition` on every alert and card, and in every check label.

- A customer **belongs to** the salesperson and store of their **first bill in the data**.
- They **returned** if they billed again at **any store, 30 to 180 days** after that first bill.
- The **cohort** is customers whose first bill is on or before as-of minus 180 days, so each one has
  had the whole window. At as-of 31 Oct 2026 that is first bills up to 4 May 2026: 63,262 customers.
- **Placeholder** customer ids are excluded.

Hand checks at 31 Oct 2026, reproduced by the engine: SP1110 (BLR-01) 15.87% of 605 customers,
BLR-01 as a whole 5.74% of 7,910.

Bills 1 to 29 days after the first bill are not returns. There are about 7,000 of them, nearly all
within a week of the first bill: alteration pick-ups and second trips for the same occasion.

## The placeholder

`C99999999` is on 1,833 bills at 19 stores. The next most frequent customer id has 7 bills, and no
other id has billed at more than 4 stores. The rule (not a hard-coded id): a customer id that is
blank, or on 25 or more bills, or seen at 6 or more stores, is a number keyed in when the customer
gave none. It is reported once in `data_issues` (store `ALL`), its bills still count for conversion
and baskets, and it is left out of everything on this lever.

## The trap, and how the comparison avoids it

The data starts on 1 Nov 2024, so a "first bill" in the early months often belongs to an existing
regular. Return rate by first-bill quarter, all stores:

| 2024Q4 | 2025Q1 | 2025Q2 | 2025Q3 | 2025Q4 | 2026Q1 | 2026Q2 |
|---|---|---|---|---|---|---|
| 12.7% | 5.5% | 3.9% | 4.1% | 2.9% | 1.8% | 1.3% |

Within 2024Q4 the months differ as much again (Nov 2024 14.7%, Dec 2024 8.9%). A salesperson who
joined recently therefore looks bad against a veteran for that reason alone.

So nobody is compared on raw rates. The **fair rate** for a salesperson is the month-by-month
return rate of their same-store colleagues, applied to the salesperson's own mix of first-bill
**months**. The test is the Cochran-Mantel-Haenszel z, stratified by first-bill month: it only ever
compares customers first billed in the same month at the same store. Months, not quarters, because
of the Nov/Dec 2024 difference. A test in `tests/test_repeat.py` plants exactly this trap (a late
joiner whose raw rate is well under the veterans') and checks she is not flagged.

Fair comparison order: a salesperson against same-store colleagues; a store against the other
established stores of its city, then of its state if the city has none. Never the country.

## What is tested, and the thresholds

**A salesperson is a role model** when all of these hold:

| rule | threshold | why |
|---|---|---|
| sample | 200 or more cohort customers | below that the expected number of returns is a handful |
| real effect | z >= 3.6 against all same-store colleagues | about 160 salespeople, two directions: one-sided 0.05 / 320 gives z 3.6 |
| material | own rate >= 1.5 × fair rate | a difference worth copying |
| consistent | ahead in at least 75% of the first-bill quarters compared, at least 3 compared | not one lucky season; a quarter is compared when both sides have 30+ customers |

**A salesperson's customers do not come back** when: 200+ customers; z <= −3.6; own rate <= 0.67 ×
fair rate; behind in at least 75% of quarters compared. Here the colleagues **exclude the store's
role models**: being behind an exceptional colleague is not a problem, and one star should not
turn ordinary colleagues into alerts.

**A store's customers do not come back** when its customers first billed by salespeople **still on
its roster** have: 500+ customers; z <= −3.0 against the other stores of the city (19 stores, two
directions: 0.05 / 38 gives z 3.0); own rate <= 0.80 × fair; behind in 75% of quarters. Only the
current team is counted so that the people who can act today are not judged on the record of
someone who has left.

**Every alert also needs**: the salesperson (or role model) on the roster in the last 7 days; an
action with a non-empty call list; rupees above zero; and the follow-up figure (weekly return bills
per 100 customers, last 13 weeks) on the same side as the gap. That last gate means the problem is
still visible now, not only in history. An alert failing any gate is not sent and leaves a note.

The z-scores of all 162 salespeople with cohort customers have mean 0.05 and standard deviation
1.65 (1.4 without SP1110), wider than pure chance would give, so there is some real spread between
people. Against all colleagues 3 of 162 cross 3.6 (SP1110 above; SP1072 and SP1114 below); with the
role model left out of the yardstick SP1114 drops to −2.81, leaving one above and one below.

## Rupees at stake

(fair return rate − own return rate) × new customers a week × average value of a return bill.

- **The gap is taken among customers first billed in the latest 52 weeks of the cohort**
  (6 May 2025 to 4 May 2026 at this as-of), not over the whole cohort. Today's new customers return
  at 1 to 3%, not at the 13% of the first quarter of the data, so the whole-cohort gap would
  overstate the money. For SP1110 the whole-cohort gap is 15.9% − 4.9% = 11.0 points; the recent gap
  is 7.7% − 2.8% = 4.9 points. The test still uses the whole cohort (more customers, more power);
  both pairs of figures are checks, and the cause sentence says which pair the rupees use.
- New customers a week: first bills in the 91 days to as-of, divided by 13.
- Value of a return bill: mean value of bills made at that store in the 364 days to as-of, 30 to
  180 days after the customer's first bill. At least 20 such bills, or no rupee figure and no alert.
- One return bill per lost customer is counted, which is conservative.
- Computed from the figures as displayed and rounded to ₹100, so the worked line multiplies out.
- On a role-model alert: (role model's rate − colleagues' rate) × new customers a week of the two
  colleagues coached today. It is what is at stake if those two reached the role model's rate.

## The action

The store has its customers' phone numbers. The action is a call list for today: customers the
person first billed 30 to 60 days before as-of who have no second bill at all. If that is more than
30 customers the window shrinks to 30 to 44 days, then 30 to 37; if it is still more than 30 (or
empty) no action can be built and the alert is not sent. The count is a check, and so are the two
dates. "Starting with the N who bought a sherwani" is added only when N is at least 2.

A named colleague sits in on the first five calls: the store's role model if it has one, otherwise
the colleague on the roster that the person is furthest behind in a head-to-head test over the same
months (same thresholds: z <= −3.6, rate <= 0.67 ×, 75% of quarters). No such colleague, no name.

A role-model alert pairs the role model with the two colleagues on the roster who are furthest
behind them over the same months and have customers to call.

## Cards

A card goes to (a) a salesperson with a `customers_not_returning` alert, and (b) every colleague of
a role model who is on the roster, has 200+ customers and is clearly behind the role model
head-to-head over the same months (same thresholds as above). The card shows the recipient's own
rate, the named peer's rate over the recipient's own first-bill months, and the call list for
today. The role model never receives one. `priority` is the rupee figure against the named peer.
Colleagues who are above their store's fair rate but below the role model still get a card, with a
low priority, so a card from another lever wins when there is one.

## Follow-up measure

The return rate itself cannot move in 7 days. The follow-up re-measures
`repeat_weekly_returns_per_100`: return bills a week, at any store, per 100 of the person's (or
team's) customers who are 30 to 180 days past their first bill. Baseline: the 13 weeks to as-of.
Target: the same figure for the benchmark group.

Why not "share of the salesperson's bills that come from returning customers": 65% of return bills
are made at a different store from the first bill (2,219 of 3,434), and at the same store by
whoever is free. That share says who served returning customers, not whose customers came back.
The measure used here follows the person's own customers wherever they bill.

Honest limit: for one salesperson this is a small number (about 200 eligible customers, often 0 to
2 return bills in a week). One week can show movement after a day of calls; it cannot prove a
change in the underlying rate.

## What was controlled for

- **First-bill month** (the trap above): yes, by stratification.
- **Store**: yes, people are compared only inside their store.
- **Product mix**: checked and not needed. Return rate by what the first bill contained: with a
  sherwani 4.80%, without 4.75%; every category between 4.35% (Indo-Western, Mojari) and 4.90%
  (Jacket). By value of the first bill, in fifths: 4.87%, 4.76%, 4.55%, 4.73%, 4.86%. Nothing here
  that could explain a gap of two or three times.
- **Seasonality**: handled by month strata; a wedding-season month is compared with the same month.
- **New store**: BLR-05 (opened 10 Oct 2026) is not judged and is never a peer benchmark. None of
  its customers are in the cohort yet.

## Back-test

The detector run at ten as-of dates. About 130 salespeople are active at each.

| as-of | alerts | cards | role models found | low found | notes |
|---|---|---|---|---|---|
| 2025-12-27 | 2 | 7 | SP1110 | none | LKO-02 store alert sent |
| 2026-03-28 | 3 | 9 | SP1110 | SP1072 | LKO-02 store alert sent |
| 2026-06-06 | 3 | 9 | SP1110, SP1145, SP1172 | SP1072 | SP1145 and SP1172 not sent: nobody clearly behind them to coach. LKO-02 sent |
| 2026-07-04 | 3 | 9 | SP1110, SP1172 | SP1072 | SP1172 not sent, same reason. LKO-02 sent |
| 2026-08-01 | 2 | 9 | SP1110 | SP1072 | LKO-02 not sent: last 13 weeks do not show the gap |
| 2026-09-05 | 2 | 9 | SP1110 | SP1072 | LKO-02 not sent, same reason |
| 2026-10-03 | 2 | 9 | SP1110 | SP1072 | |
| 2026-10-17 | 2 | 9 | SP1110 | SP1072 | |
| 2026-10-24 | 2 | 9 | SP1110 | SP1072 | |
| 2026-10-31 | 2 | 9 | SP1110 | SP1072 | |

The same two people every week, 2 or 3 alerts across 19 stores, cards for 9 of about 130 active
salespeople (7%), eight of them in the one store that has a role model. Before 1 May 2026 there is
no roster, so "on the roster" falls back to "billed in the last 28 days" for the two earliest dates.

Because the return rate moves slowly, these alerts repeat week after week under the same
`alert_id` until the figures change. That is intended; the weekly cap decides whether they are shown.

## Looked at and not alerted, at 31 Oct 2026

| what | figures | why not |
|---|---|---|
| LKO-02 as a store | whole store 3.6% of 3,878 against 4.9% fair, z −3.34; current team 3.1% of 2,424 against 4.3%, z −2.92 | Under the z 3.0 bar once SP1018 (941 customers, 2.4%), who has left, is not counted. Behind in 7 of 7 quarters, so worth watching |
| SP1114 Manjunath C., BLR-01 | 3.1% of 778; z −3.70 against all colleagues, −2.81 without the role model | Below the bar once Karthik J. is left out of the yardstick. Gets a card, and is one of the two coached in the role-model alert |
| SP1120 Suresh V., BLR-01 | 2.8% of 716; z −3.32 and −2.51 | same |
| SP1145 Yogesh N., BLR-03 | 44 of 607 (7.2%) against 4.3% fair, z +3.33 | under 3.6; ahead in 5 of 7 quarters |
| SP1012 Manoj T., LKO-01 | 9.6% of 229 against 5.0%, z +3.15 | under 3.6; small sample |
| SP1030 Shivam M., LKO-03 | 9.6% of 323 against 4.9%, z +3.00 | under 3.6 |
| BLR-01 as a store | 5.7% against 4.6% fair, z +4.04 | It is Karthik J.: stores are not reported as role models, people are |
| Salespeople with fewer than 200 cohort customers | 32 of 162 people | sample too small to judge either way |
| Product mix as a cause | see above | no effect on return rate |

## Limits worth knowing

- "First bill in the data" is not always a customer's first ever bill. Month strata remove the
  bias between people; they cannot make the early months mean "new customer".
- The data cannot say why a customer came back. The alert says so, and the action is to make the
  calls and have the role model listen, not a claim about what the salesperson says at the counter.
- A customer who returns to a different salesperson or store still counts for the salesperson of
  their first bill. That is the definition; it credits whoever started the relationship.
