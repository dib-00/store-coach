# The daily run

Store Coach runs on its own. Nobody presses a button: every morning GitHub starts the
job in [`.github/workflows/daily.yml`](../.github/workflows/daily.yml), named
**Daily engine run**.

This page says what the job does, how to set it up once, how to start it by hand, how
to confirm it really ran on its own, and what happens when a part of it is down.

## What happens every morning

The job starts at 00:30 UTC, which is 06:00 IST. GitHub can start a scheduled job a few
minutes late.

| Step | What it does | If it fails |
| --- | --- | --- |
| 1 | Checks out the code and installs Python 3.13 with the pinned dependencies. | The job stops. |
| 2 | `scripts/fetch_data.py` downloads the nine CSVs the engine reads from a private Supabase Storage bucket. Each file must be non-empty, start with its header row and hold data rows. | The job stops. |
| 3 | `python -m pytest -q` runs the tests. | The job stops. |
| 4 | Works out the as-of date: the last bill date in the data, or the date typed in when the job was started by hand. | The job stops. |
| 5 | Makes last week's run available for the follow-up (see below). | The job stops. |
| 6 | `python -m engine.run` writes the alerts, cards, follow-ups and data issues as JSON. | The job stops. |
| 7 | `scripts/verify.py` recomputes every published figure from the raw CSVs. It shares no code with the engine. | **The job stops and nothing is published.** |
| 8 | `scripts/publish_supabase.py` writes the run to Supabase, then reads the row counts back and compares them. | The job stops. The site keeps showing the last run. |
| 9 | Calls a Vercel deploy hook, so the site rebuilds and picks up the new run. | The run is safe in Supabase. The site shows it after its next build. |
| 10 | Keeps the output as a workflow artifact for 30 days and writes a job summary: the as-of date, alerts per area manager and the data issues. | Runs even when an earlier step failed, so there is always something to read. |

Steps 8 and 9 run only when step 7 passed. A wrong number is never published.

### The job never writes to the repository

The job does not commit and does not push. Its GitHub token is read-only
(`permissions: contents: read`), so it could not even if a step tried.
`tests/test_ops.py` reads the workflow file and fails if a commit or push command, or a
write permission, ever appears in it.

The run goes to Supabase instead. That is the store of record.

### How a new run reaches the site without a commit

1. The job writes the run to the Supabase table `runs`.
2. The job calls the Vercel deploy hook. Vercel rebuilds the site from the same commit.
3. Before the build, `web/scripts/fetch-latest.mjs` asks Supabase for the newest run and
   uses it for that build. If Supabase does not answer, or the run is older than the
   JSON committed in the repo, the build keeps the committed JSON.

So the site always has data: either the newest run from Supabase, or the JSON in the repo.

### Last week's run and the follow-up

A week after an alert, the engine re-measures it. To do that it reads the run of seven
days earlier from `web/public/data/runs/<as_of minus 7 days>.json`.

- If that file is in the repo, the job uses it as it is.
- If it is not, step 5 restores it from the Supabase table `runs`. The job never
  commits, so this is how one run finds the run of the week before.
- If Supabase has no run for that date either, the engine reports no follow-ups for
  this run. The job says which of the three happened in a notice on the run page.

## What is stored in Supabase

Defined in [`supabase/schema.sql`](../supabase/schema.sql).

| Table | One row is | Written by |
| --- | --- | --- |
| `runs` | One engine run. `output` holds the whole JSON the site reads. | The daily job |
| `alerts` | One alert sent to an area manager in a run | The daily job |
| `cards` | One salesperson card in a run | The daily job |
| `follow_ups` | One alert re-measured in a run | The daily job |
| `data_issues` | One data issue in a run | The daily job |
| `alert_status` | The "done" tick on one alert | The site. The daily job never touches it. |

There is also a view, `latest_run`: the newest row of `runs`.

Publishing the same date twice leaves one copy. The run row is replaced, and the alert,
card, follow-up and data-issue rows for that date are deleted and written again.

The CSVs are in a private Storage bucket, `store-coach-data`, as `csv/<name>.csv`.

### Who can do what

Row level security is on for every table.

| Key | Where it lives | What it can do |
| --- | --- | --- |
| Service-role key (secret) | GitHub secret, and your own `.env` for the one-off upload | Everything, including reading the private CSV bucket |
| Anon key (public) | Vercel environment variable; it is in the browser | Read the tables. Insert and update `alert_status`. Nothing else: it cannot write a run or an alert, cannot delete anything and cannot read the CSV bucket. |

The service-role key is never in the web app, never in Vercel and never in Git.

## One-time setup

Do these in order. Steps 1 to 4 and 6 to 8 are done in a browser or on your own machine
and need no commit. Variable names are in [`.env.example`](../.env.example).

1. **Create a Supabase project.** At supabase.com, New project. Note the project URL
   (`https://<project-ref>.supabase.co`) and, under Project Settings > API Keys, the
   anon (publishable) key and the service-role (secret) key.

2. **Create the tables.** In Supabase, open SQL Editor, paste the whole of
   `supabase/schema.sql` and press Run. The editor warns that the query drops things
   (it drops and recreates the policies and the view); confirm. The file is safe to run
   again.

3. **Put the keys in `.env`.** Copy `.env.example` to `.env` in the repo root and fill
   in `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. `.env` is git-ignored.

4. **Upload the CSVs.** From the repo root:

   ```
   .venv/Scripts/python -X utf8 scripts/upload_data.py
   ```

   It creates the private bucket `store-coach-data` if it is missing, uploads every
   `data/csv/*.csv` and prints each file's size and a final count. It never prints the key.

5. **Push the code to GitHub.** The schedule only runs once `daily.yml` is on the
   default branch of the GitHub repository.

6. **Add three GitHub secrets.** In the repository: Settings > Secrets and variables >
   Actions > New repository secret.

   | Secret | Value |
   | --- | --- |
   | `SUPABASE_URL` | The project URL |
   | `SUPABASE_SERVICE_ROLE_KEY` | The service-role key |
   | `VERCEL_DEPLOY_HOOK_URL` | The deploy hook URL from step 8 |

7. **Add two Vercel environment variables.** In the Vercel project: Settings >
   Environment Variables, for Production.

   | Variable | Value |
   | --- | --- |
   | `NEXT_PUBLIC_SUPABASE_URL` | The project URL |
   | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | The anon key. Never the service-role key. |

8. **Create the Vercel deploy hook.** In the Vercel project: Settings > Git > Deploy
   Hooks. Give it a name, choose the production branch, create it, and copy the URL into
   the GitHub secret `VERCEL_DEPLOY_HOOK_URL`.

9. **Start the job once by hand** (next section) and check the result.

Without the secret `VERCEL_DEPLOY_HOOK_URL` the job still runs and still publishes to
Supabase. It prints a warning and skips the rebuild. Without the two Supabase secrets
the job stops at step 2 with a message naming the missing secret.

## Starting it by hand

In GitHub: Actions > Daily engine run > Run workflow. Leave `as_of` empty to use the
last bill date in the data, or type a date such as `2026-10-31`.

From a terminal with the GitHub CLI:

```
gh workflow run daily.yml
gh workflow run daily.yml -f as_of=2026-10-31
gh run watch
```

To try the publish step on your own machine without sending anything:

```
.venv/Scripts/python -X utf8 scripts/publish_supabase.py --file web/public/data/latest.json --dry-run
```

It prints the number of rows it would write to each table and makes no network call.

## How to confirm it ran on its own

- **GitHub.** Actions > Daily engine run. A run started by the schedule shows the event
  `schedule`; one started by a person shows `workflow_dispatch` and their name.
- **The job summary.** Open a run. The summary lists the as-of date, alerts per area
  manager, the data issues, whether the figures were re-checked, whether the run was
  written to Supabase and whether Vercel was asked to rebuild.
- **Supabase.** Table Editor > `runs`. `generated_at` is when the engine ran.
- **The site.** The status line shows when the engine last ran.

The data pack for this hackathon is fixed: its last bill date is 31 Oct 2026. So each
daily run is as of 2026-10-31 and replaces the row for that date; `generated_at` is what
changes from day to day. When new CSVs are uploaded to the bucket, the as-of date moves
forward on its own, because the default is the last bill date in the data.

## What happens when a part is down

| What is down | What happens | What the area managers see |
| --- | --- | --- |
| GitHub Actions, or the schedule is skipped | No run that day. Each run recomputes everything from the CSVs, so the next run loses nothing. | The last published run |
| Supabase, when the job fetches the CSVs | The job stops at step 2. Nothing is published. | The last published run |
| A bad upload (an empty file, a wrong header) | `fetch_data.py` names the file and the job stops at step 2. | The last published run |
| A test fails, or `verify.py` finds a mismatch | The job stops before step 8. Nothing is published. The output is kept as an artifact for inspection. | The last published run |
| Supabase, when the job publishes | The job fails. If it stopped part-way, the next run cleans up: rows for the date are deleted and written again. | The last published run |
| The Vercel deploy hook is missing or refuses | The run is in Supabase. A warning (missing) or a failed job (refused). | The last built site, until the next build |
| Supabase, when the site builds | The build waits a few seconds, then keeps the JSON committed in the repo. The build does not fail. | The committed run |
| Supabase, when someone is using the site | The pages were built with their data, so they still load. Only the "done" tick is unavailable. | The site, without the tick |
| Vercel | The site is unreachable. The runs are safe in Supabase. | Nothing until Vercel is back |

## Things to know

- GitHub runs a schedule only from the default branch.
- In a public repository GitHub switches a schedule off after 60 days with no activity
  in the repository. Switch it back on in Actions > Daily engine run > Enable workflow.
- Two daily runs never overlap: a second one waits for the first.
- The engine is deterministic. Two runs on the same CSVs give the same output apart
  from `generated_at`.
- A run started by hand for an older date is stored under that date. The site shows the
  newest date, so an older run does not replace what the managers see.

## The files

| File | What it is |
| --- | --- |
| `.github/workflows/daily.yml` | The daily job |
| `.github/workflows/ci.yml` | Tests and lint on every push and pull request. Needs no data and no secrets. |
| `supabase/schema.sql` | Tables, row level security, policies and the `latest_run` view |
| `scripts/upload_data.py` | One-off: creates the private bucket and uploads the CSVs |
| `scripts/fetch_data.py` | Downloads the CSVs, and last week's run when the repo lacks it |
| `scripts/publish_supabase.py` | Writes a run to Supabase. `--dry-run` sends nothing. |
| `tests/test_ops.py` | Tests for all of the above. No network. |
| `.env.example` | The names of the settings and where each one goes |
