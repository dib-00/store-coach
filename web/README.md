# Store Coach web app

Next.js app that shows the engine's output. Deployed on Vercel with `web/` as the root directory.
Every page is built as static HTML from one file, `public/data/latest.json`, which the engine writes.
There is no sign-in, no database and no API call at request time.

## Pages

| Route | Shows |
| --- | --- |
| `/` | The area managers, with alerts shown this week and rupees at stake a week |
| `/manager/[id]` | That manager's alerts in rank order, the held-back list, links to their stores |
| `/store/[id]` | Store facts, summary figures, salesperson cards, the store's data issues |
| `/follow-up` | Before and after for last week's alerts |
| `/data-issues` | Numbers that cannot be right, and what the engine did about each |

## Rules the app enforces itself

These hold whatever the JSON file says. The code is in `lib/rules.ts` and the tests are beside it.

- An area manager never sees more than `max_alerts_per_week` alerts, and never more than 5.
- A salesperson card over 60 words (split on whitespace) is not shown; a "card withheld" note is shown instead.
- If `latest.json` is missing, is not valid JSON or fails the checks in `lib/parse.ts`, every page says
  "No engine run has been published yet". The app never falls back to sample data.
- Figures the engine sends preformatted (`Check.display`) are shown untouched. The app formats only raw
  rupee amounts and dates, and adds up one figure: rupees at stake across the alerts shown to a manager.

## Commands

```bash
npm install
npm run dev     # http://localhost:3000
npm run lint
npm test        # Node's built-in test runner, no build needed
npm run build
```

## Developing without engine output

`fixtures/sample.json` is a made-up file with fictional ids (`TST-01`, "Sample Manager One").
Point the loader at it with an environment variable:

```bash
STORE_COACH_DATA_FILE=fixtures/sample.json npm run dev
```

While the variable is set, a banner on every page says the data is a development sample.
The variable is ignored on Vercel, so the deployed site can only show the published file.
