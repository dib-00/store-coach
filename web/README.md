# Store Coach web app

Next.js app that shows the engine's output. Deployed on Vercel with `web/` as the root directory.
Every page is built as static HTML from one file, `public/data/latest.json`, which the engine writes.
There is no sign-in. The pages make no API call at request time; the one exception is the optional
"Done" tick described below, and the pages work without it.

## Pages

| Route | Shows |
| --- | --- |
| `/` | That the engine runs on its own every morning, when it last ran, the data date, and the area managers with alerts shown this week and rupees at stake a week |
| `/manager/[id]` | A one-line summary, that manager's alerts in rank order (lever, rupees at stake, the action, a link to each store), the held-back list, and their stores with any "not judged" reason |
| `/store/[id]` | Store facts, the "not judged" reason if there is one, summary figures, salesperson cards, the store's data issues |
| `/follow-up` | Before, after and target for last week's alerts, grouped by area manager, with the verdict |
| `/data-issues` | Numbers that cannot be right, and what the engine did about each |

## Rules the app enforces itself

These hold whatever the JSON file says. The code is in `lib/rules.ts` and the tests are beside it.

- An area manager never sees more than `max_alerts_per_week` alerts, and never more than 5.
- A salesperson card over 60 words (split on whitespace) is not shown; a "card withheld" note is shown instead.
  The count shown as "n of 60 words" is taken from the card text itself. A card's `definition` is shown
  under the card, outside the 60 words.
- If `latest.json` is missing, is not valid JSON or fails the checks in `lib/parse.ts`, every page says
  "No engine run has been published yet". The app never falls back to sample data.
- Figures the engine sends preformatted (`Check.display`) and the engine's sentences are shown untouched.
  The app formats only raw rupee amounts and dates. It adds up one figure, rupees at stake across the
  alerts shown to a manager, and it counts things (alerts shown, alerts held back, follow-ups by outcome).
- The optional fields (`definition` on alerts, cards and follow-ups; `not_judged_reason` on stores) are
  shown only when they are non-empty text. A file without them is accepted as before.

## The daily run reaches the site without a Git commit

`scripts/fetch-latest.mjs` runs before every build (`prebuild` in `package.json`). When
`NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY` are set in the build environment, it asks
the Supabase table `runs` for the newest run and writes it over `public/data/latest.json` for that build
only. The committed file stays the safe default. The published run replaces it only if all of these hold:

- it has `schema_version` 1;
- its `as_of` is the same as the committed file's or later (the site never goes back to older data);
- its `generated_at` is later than the committed file's;
- it passes the same checks the pages apply (`lib/parse.ts`).

In every other case (a setting missing, a network error, no answer within 8 seconds, a bad reply, an
older run) it logs one line starting `[store-coach] fetch-latest:` and leaves the committed file as it
was. It always exits 0, so it can never fail a build.

The script reads the two settings from the environment only, not from `.env` files, so a local build
keeps the committed file unless you export them in your shell.

## The "Done" tick

Each alert has a "Mark as done" tick under its action (`components/done-tick.tsx`). There is no sign-in.
It reads and writes one Supabase table through its REST interface with plain `fetch`:
`alert_status(alert_id text primary key, done boolean, updated_at timestamptz)`.

- It uses `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`. The anon key is public by
  design. No other key may ever appear in `web/`.
- If either setting is missing, no tick is rendered at all.
- If the read fails, "Saving unavailable" is shown in small print in place of the tick. If a save fails,
  the tick goes back to what it was and the same note appears beside it. The alert is never affected.
- The row is keyed on `alert_id`, which stays the same from run to run for the same issue. So a tick
  stays set for as long as the engine keeps raising that same alert.

## Commands

```bash
npm install
npm run dev     # http://localhost:3000
npm run lint
npm test        # Node's built-in test runner, no build needed
npm run build   # runs scripts/fetch-latest.mjs first
```

## Developing without engine output

`fixtures/sample.json` is a made-up file with fictional ids (`TST-01`, "Sample Manager One"). It shows a
manager at the cap of five alerts across all three levers, cards, three follow-ups and every optional field.
Point the loader at it with an environment variable:

```bash
STORE_COACH_DATA_FILE=fixtures/sample.json npm run dev
```

While the variable is set, a banner on every page says the data is a development sample.
The variable is ignored on Vercel, so the deployed site can only show the published file.
