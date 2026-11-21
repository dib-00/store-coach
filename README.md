# Store Coach

**Live:** https://store-coach-dib.vercel.app (no sign-in)

Built at Vibe Coders Hackathon Edition 3, Kolkata, for Manyavar (Vedant Fashions).

Manyavar's six area managers cannot see each morning which of their stores are slipping,
why, and what to do about it today. Store Coach runs on its own every morning and tells
them, and gives each salesperson one thing to do better today.

## What it produces

1. **Area manager alerts.** At most 5 a week per manager, ranked by rupees at stake. Each
   names the lever, the cause and one action the store can take today with the people and
   stock it already has, naming who, what and when. If the engine cannot name such an
   action, the alert is not sent.
2. **Salesperson cards.** 60 words or fewer: one behaviour, one named colleague from the
   same store, one action for today.
3. **Follow-up.** A week later, the number behind each alert is measured again, with dates
   and sample sizes, and the page says whether it really moved.
4. **Market notes and data issues.** A whole city slowing down is reported once, not as
   one alert per store. Numbers that cannot be right are listed and never alerted.

| Lever | Measure |
| --- | --- |
| More bills | Conversion = bills ÷ walk-ins |
| Bigger baskets | Items per bill, the obvious pairs, discounts, categories |
| More repeat | A customer billing again 30 to 180 days after their first bill |

### What it finds in the data (run of 31 Oct 2026)

| Area manager | Alert | Rupees a week |
| --- | --- | --- |
| Harish Gowda, Bengaluru | BLR-03: Manjunath K. and Vijay N. missing weekend shifts; conversion 13.2% → 10.7% | ₹98,100 |
| Rakesh Srivastava, Lucknow | LKO-02: Imran C., the strongest seller, left on 14 Sep; conversion 12.3% → 10.5% | ₹61,700 |
| Mahesh Shetty, Mysuru | MYS-02: Santosh B. and Mohan Y. at 1.37 and 1.36 items a bill against 1.86 for Madhu G. | ₹12,600 |
| Alok Tiwari, Kanpur | KNP-01: jacket with kurta set fell to 14.4%, from 23.5% (nine months before) and 24.2% (a year ago) | ₹8,100 |
| Nitin Sinha, Patna | PAT-01: Manoj N. and Sanjay K. give about 7% and 6% of MRP in discounts; colleagues about 1–2% | ₹7,000 |
| Harish Gowda, Bengaluru | BLR-02: Suresh K. sells no Indo-Western; colleagues 5.5% of bills | ₹6,400 |
| Harish Gowda, Bengaluru | BLR-01: Karthik J. is the repeat role model (15.9% of his customers return, store 5.7%) | ₹4,900 |
| Nitin Sinha, Patna | PAT-01: Faizan K.'s customers return least of 15 (1.6%, store 4.7%) | ₹2,300 |

- **Market note:** Bengaluru as a whole converts 12.5% against 14.3% in the same weeks last
  year, aligned on Dussehra. Bengaluru stores are charged only for what they lost beyond
  the rest of the city.
- **Data issues:**
  - PAT-03's door counter shows zero walk-ins on 11 days with bills, so those days are left out.
  - Customer number C99999999 is on 1,833 bills in 19 stores. It is a placeholder, so it is
    left out of repeat.
- **Not judged:** BLR-05 opened on 10 Oct 2026 and is too new to compare.
- **Follow-up example:** a replay of the engine shows the BLR-03 alert of 10 Oct followed by
  a real rise, 9.5% to 13.9%, a week later. Of the seven live follow-ups (24 → 31 Oct),
  three show no change beyond what a week moves by chance and four cannot be measured on one
  week yet. The page says which, with the figures and dates.

## How the numbers are checked

Every figure on the site is a *check*: a value plus the recipe to recompute it. The recipes
are written in [docs/CHECKS.md](docs/CHECKS.md) and the `docs/CHECKS-*.md` pages.
[scripts/verify.py](scripts/verify.py) shares no code with the engine. It recomputes every
check straight from the raw CSVs and fails loudly on any difference. It also checks:

- the rupee arithmetic multiplies out,
- every number quoted in an alert has a recipe,
- no manager gets more than 5 alerts,
- every card is 60 words or fewer and names a colleague from the same store,
- nothing after the as-of date was used.

| Run | Figures recomputed | Mismatches | Rule tests | Broken |
| --- | --- | --- | --- | --- |
| 31 Oct 2026 (live) | 530 | 0 | 2,287 | 0 |
| 24 Oct 2026 | 438 | 0 | 1,920 | 0 |
| 17 Oct 2026 (replay) | 426 | 0 | 1,818 | 0 |
| 10 Oct 2026 (replay) | 338 | 0 | 1,350 | 0 |

The daily job runs `verify.py` before it publishes anything, so a run with a wrong number
never reaches the site.

Tests: 155 engine tests (`pytest`) and 65 web tests (`node --test`). They include:

- the 60-word card limit,
- the 5-alert cap,
- an as-of run using no future data: it is byte-identical to a run on CSVs physically cut at that date,
- the action rule,
- the verifier catching a corrupted figure.

## Run it

Needs Python 3.13 and Node 24. The data (17 CSVs, owned by Vedant Fashions) is not in this
repository; put it in `data/csv/`.

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # bin/ instead of Scripts/ on Linux/macOS

# the engine: writes web/public/data/latest.json and runs/<as_of>.json
python -m engine.run --as-of 2026-10-31

# the follow-up demo: a run a week earlier, then the run that re-measures it
python -m engine.run --as-of 2026-10-24 --dated-only
python -m engine.run --as-of 2026-10-31

# check every figure against the raw CSVs (exit code 0 only if all match)
python scripts/verify.py

# tests
python -m pytest -q

# the site
cd web && npm install && npm test && npm run dev    # http://localhost:3000
```

`--as-of` uses only data up to that date. The engine is deterministic: no LLM calls, no
API keys, no randomness. Alert and card text come from templates filled with computed values.

## The daily run

[.github/workflows/daily.yml](.github/workflows/daily.yml) runs every morning at 06:00 IST,
and on demand from the Actions tab. In order:

1. Fetch the CSVs from a private Supabase Storage bucket.
2. Run the tests.
3. Run the engine.
4. Run `verify.py`. If anything differs, the job stops here.
5. Publish the run to Supabase.
6. Call a Vercel deploy hook.

The site's build pulls the newest run from Supabase and falls back to the JSON committed in
the repository, so the site keeps working if Supabase or the job is down. The job never
commits or pushes; its token is read-only.

Full detail, one-time setup and what happens when each part is down:
[docs/DAILY-RUN.md](docs/DAILY-RUN.md). Every run is listed under
[Actions](https://github.com/dib-00/store-coach/actions).

Supabase holds the runs, alerts, cards, follow-ups and data issues ([supabase/schema.sql](supabase/schema.sql)).
The public site can read them and can set only the "done" tick on an alert; it cannot
write anything else. The service key lives only in GitHub secrets.

## Layout

| Path | What |
| --- | --- |
| `engine/` | Python and pandas. `load.py` (the one as-of cut), `metrics.py`, `detect.py` (more bills), `baskets.py`, `repeat.py`, `cards.py`, `followup.py`, `run.py` |
| `scripts/` | `verify.py` (independent check), `fetch_data.py`, `publish_supabase.py`, `upload_data.py` |
| `web/` | Next.js app on Vercel; reads `web/public/data/` |
| `docs/` | Method and recipe for each lever, the follow-up and the daily run |
| `supabase/` | Database schema and access rules |
| `tests/` | Engine, verifier and ops tests |

## Method, in short

- Fair comparison is same store first, then city, never the whole country. A salesperson is
  compared only with colleagues in the same store.
- A drop must pass a statistical test (with the bar raised for the number of comparisons)
  and be large enough to matter. Small stores get longer windows, not guesses.
- Seasonal swings are not problems. Footfall doubles every October, so the engine judges
  conversion, not footfall, and compares a city with the same weeks last year aligned on the
  festival calendar.
- Rupees at stake = gap to a fair benchmark × weekly volume × average value, worked out from
  the figures as displayed so a judge can check it by hand.

Detail: [METHOD.md](docs/METHOD.md) · [METHOD-baskets.md](docs/METHOD-baskets.md) ·
[METHOD-repeat.md](docs/METHOD-repeat.md) · [METHOD-followup.md](docs/METHOD-followup.md)

## Known limits

- The roster covers only May to October 2026, so the roster-based causes (who left, who
  misses shifts) cannot be found before May 2026.
- There is no hour of day in the data, so actions name days, never hours.
- The data is synthetic and ends on 31 Oct 2026. Nobody acted on these alerts, so the live
  follow-ups show what the stores did on their own.
- The LKO-02 fall beyond the rest of Lucknow (1.3 points) is not large enough to rule out
  chance. The alert says so in its cause.
