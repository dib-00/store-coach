# Store Coach

Built at Vibe Coders Hackathon Edition 3, Kolkata, for Manyavar (Vedant Fashions).

## The problem

Manyavar's six area managers cannot see each morning which of their stores are slipping, why, and what to do about it today.

## What Store Coach does

It runs on its own every day and produces three things:

1. **Area manager alerts.** At most 5 issues per manager per week, ranked by rupees at stake. Each names the lever, the cause, and one action.
2. **Salesperson cards.** 60 words or fewer: one behaviour, one named peer from the same store, one action for today.
3. **Follow-up.** A week later it checks whether the number moved and reports it.

The three levers:

| Lever | Measure |
| --- | --- |
| More bills | Conversion = bills / footfall |
| Bigger baskets | Items per bill |
| More repeat | A customer billing again 30+ days after their first bill |

An action must be doable today by the store, with the people and stock it already has, and must name who, what and when. If the engine cannot name such an action, it does not send the alert.

## How it is built

- `engine/` — Python and pandas. Reads the CSVs, finds the issues, and writes JSON. Deterministic: no LLM calls and no API keys. Alert and card text come from templates filled with computed values.
- `web/` — Next.js app on Vercel. It reads the engine's JSON, so the site keeps working if anything else is down.

The source data is not in this repository.

## Status

Work in progress. This README is updated as each part lands, and describes only what exists.

- [ ] Conversion lever end to end, deployed at a public link
- [ ] Basket and repeat levers, cause detection, rupee ranking, weekly cap, data issues
- [ ] Salesperson cards and follow-up view
- [ ] Daily automatic run
- [ ] Verification script that recomputes displayed figures from the raw CSVs
