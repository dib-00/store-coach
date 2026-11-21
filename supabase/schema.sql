-- Store Coach: the store of record.
-- Paste this whole file into Supabase > SQL Editor and press Run.
-- It is safe to run again: tables are created only if missing, and grants, policies
-- and the view are dropped and recreated.
--
-- Who can do what
--   service role (the daily GitHub job, scripts/publish_supabase.py): everything. It bypasses row level security.
--   anon (the public website, no sign-in): read every table; insert and update alert_status only.
--   anon can never write a run, an alert, a card, a follow-up or a data issue.

-- ---------------------------------------------------------------------------
-- Tables
-- ---------------------------------------------------------------------------

-- One row per engine run. `output` is the whole EngineOutput JSON (web/lib/types.ts).
create table if not exists public.runs (
  as_of          date primary key,
  generated_at   timestamptz not null,
  schema_version int not null,
  output         jsonb not null,
  inserted_at    timestamptz default now()
);

-- The rows below repeat parts of runs.output so they can be queried with plain SQL.

create table if not exists public.alerts (
  alert_id               text,
  as_of                  date references public.runs on delete cascade,
  area_manager_id        text,
  rank                   int,
  lever                  text,
  cause_code             text,
  store_ids              text[],
  headline               text,
  cause                  text,
  action_text            text,
  rupees_at_stake_weekly bigint,
  primary key (as_of, alert_id)
);

create table if not exists public.cards (
  card_id        text,
  as_of          date references public.runs on delete cascade,
  store_id       text,
  salesperson_id text,
  lever          text,
  text           text,
  word_count     int,
  primary key (as_of, card_id)
);

create table if not exists public.follow_ups (
  alert_id       text,
  measured_as_of date references public.runs (as_of) on delete cascade,
  raised_as_of   date,
  moved          text,
  before         numeric,
  after          numeric,
  target         numeric,
  verdict        text,
  primary key (measured_as_of, alert_id)
);

create table if not exists public.data_issues (
  issue_id      text,
  as_of         date references public.runs on delete cascade,
  store_id      text,
  kind          text,
  title         text,
  days_affected int,
  primary key (as_of, issue_id)
);

-- The "done" tick an area manager sets on the site. No sign-in.
-- alert_id is stable across runs for the same issue, so a tick survives the next run.
-- The daily job never touches this table.
create table if not exists public.alert_status (
  alert_id   text primary key,
  done       boolean not null default false,
  updated_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Row level security: on for every table
-- ---------------------------------------------------------------------------

alter table public.runs         enable row level security;
alter table public.alerts       enable row level security;
alter table public.cards        enable row level security;
alter table public.follow_ups   enable row level security;
alter table public.data_issues  enable row level security;
alter table public.alert_status enable row level security;

-- ---------------------------------------------------------------------------
-- Grants: start from nothing for the public roles, then give exactly what is needed
-- ---------------------------------------------------------------------------

revoke all on public.runs, public.alerts, public.cards, public.follow_ups,
              public.data_issues, public.alert_status
  from anon, authenticated;

grant select on public.runs, public.alerts, public.cards, public.follow_ups,
                public.data_issues, public.alert_status
  to anon;

grant insert (alert_id, done, updated_at) on public.alert_status to anon;
grant update (alert_id, done, updated_at) on public.alert_status to anon;

grant all on public.runs, public.alerts, public.cards, public.follow_ups,
             public.data_issues, public.alert_status
  to service_role;

-- ---------------------------------------------------------------------------
-- Policies
-- ---------------------------------------------------------------------------

drop policy if exists "anon reads runs" on public.runs;
create policy "anon reads runs" on public.runs
  for select to anon using (true);

drop policy if exists "anon reads alerts" on public.alerts;
create policy "anon reads alerts" on public.alerts
  for select to anon using (true);

drop policy if exists "anon reads cards" on public.cards;
create policy "anon reads cards" on public.cards
  for select to anon using (true);

drop policy if exists "anon reads follow_ups" on public.follow_ups;
create policy "anon reads follow_ups" on public.follow_ups
  for select to anon using (true);

drop policy if exists "anon reads data_issues" on public.data_issues;
create policy "anon reads data_issues" on public.data_issues
  for select to anon using (true);

drop policy if exists "anon reads alert_status" on public.alert_status;
create policy "anon reads alert_status" on public.alert_status
  for select to anon using (true);

-- An alert_id is short text such as "LKO-02:more_bills:salesperson_left:SP1018".
drop policy if exists "anon inserts alert_status" on public.alert_status;
create policy "anon inserts alert_status" on public.alert_status
  for insert to anon
  with check (char_length(alert_id) between 1 and 200);

drop policy if exists "anon updates alert_status" on public.alert_status;
create policy "anon updates alert_status" on public.alert_status
  for update to anon
  using (true)
  with check (char_length(alert_id) between 1 and 200);

-- No delete policy and no delete grant: anon cannot remove a tick, only set done to false.

-- ---------------------------------------------------------------------------
-- View: the newest run
-- ---------------------------------------------------------------------------

-- security_invoker makes the view obey the caller's grants and policies on runs.
drop view if exists public.latest_run;
create view public.latest_run
  with (security_invoker = true) as
  select as_of, generated_at, schema_version, output, inserted_at
  from public.runs
  order by as_of desc, generated_at desc
  limit 1;

revoke all on public.latest_run from anon, authenticated;
grant select on public.latest_run to anon;
grant select on public.latest_run to service_role;

-- Ask the API layer to pick up the new tables straight away.
notify pgrst, 'reload schema';
