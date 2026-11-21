// The contract between engine/ (Python, writes the JSON) and web/ (reads it).
// The engine writes web/public/data/latest.json in exactly this shape.
// Change this file and the engine together, never one without the other.

export type Lever = "more_bills" | "bigger_baskets" | "more_repeat";

export interface DateWindow {
  start: string; // YYYY-MM-DD, inclusive
  end: string; // YYYY-MM-DD, inclusive
}

/**
 * One figure shown in the UI, with the recipe to recompute it from the raw CSVs.
 * `kind` and `params` are defined in docs/CHECKS.md. scripts/verify.py recomputes
 * every check from the CSVs without importing the engine, and fails on a mismatch.
 */
export interface Check {
  id: string; // unique within the file
  label: string; // plain-English label for the "show the numbers" expander
  kind: string; // recompute recipe name, see docs/CHECKS.md
  params: Record<string, string | number | boolean | string[]>;
  value: number | string; // raw value: ratios as fractions (0.106), money in rupees
  display: string; // formatted for people: "10.6%", "₹1,38,600", "14 Sep 2026"
}

/** How rupees at stake was worked out, so a judge can check it by hand. */
export interface Arithmetic {
  formula: string; // "(fair conversion − current conversion) × walk-ins a week × average bill value"
  worked: string; // "(13.3% − 10.6%) × 249 walk-ins a week × ₹9,870 = ₹66,400 a week"
  input_check_ids: string[]; // ids of the checks used in `worked`
}

/** Must be doable today with the people and stock the store already has. */
export interface Action {
  who: string;
  what: string;
  when: string;
  text: string; // the full sentence shown to the area manager
}

export interface Alert {
  alert_id: string; // stable across runs for the same issue: "<store or city>:<lever>:<cause_code>[:<subject>]"
  rank: number; // 1 = most rupees at stake for this area manager
  scope: "store" | "city"; // "city" = a market issue reported once, not per store
  store_ids: string[];
  city: string;
  lever: Lever;
  cause_code: string; // e.g. "salesperson_left", "missed_shifts", "thin_floor_busy_days", "market_slowdown"
  headline: string; // what moved, with the numbers
  /** Optional. One sentence stating exactly how the headline metric is defined. Shown in small print under the headline. */
  definition?: string;
  cause: string; // why, in one or two sentences, naming people where relevant
  action: Action;
  rupees_at_stake_weekly: number; // whole rupees
  arithmetic: Arithmetic;
  benchmark_basis: string; // "Same store, previous 13 weeks" — same store first, then city, then state
  salesperson_ids: string[]; // people named in the alert, may be empty
  checks: Check[]; // every number quoted in headline, cause, action and arithmetic
  /** What the follow-up re-measures a week later. */
  follow_up: {
    metric_label: string; // "Conversion at BLR-03"
    kind: string; // a Check kind
    params: Check["params"]; // window params are replaced by the follow-up week
    baseline_value: number; // value when the alert was raised
    target_value: number; // the fair benchmark
    higher_is_better: boolean;
  };
}

export interface HeldBackAlert {
  headline: string;
  lever: Lever;
  rupees_at_stake_weekly: number;
  reason: string; // "Below the top 5 this week"
}

export interface AreaManagerBlock {
  area_manager_id: string;
  name: string;
  city: string;
  store_ids: string[];
  max_alerts_per_week: number;
  alerts: Alert[]; // length <= max_alerts_per_week, sorted by rank
  held_back: HeldBackAlert[]; // real issues that did not make the cap
  /** A whole city converting clearly less than in the same weeks last year. Shown, never ranked as an alert. */
  market_notes?: MarketNote[];
}

export interface MarketNote {
  note_id: string; // "<city>:more_bills:market_vs_last_year"
  city: string;
  store_ids: string[];
  headline: string; // with both date ranges
  detail: string;
  checks: Check[];
}

export interface StoreBlock {
  store_id: string;
  city: string;
  state: string;
  tier: string;
  opened_on: string;
  area_manager_id: string;
  is_new_store: boolean; // too new to judge against established stores
  salespeople: { salesperson_id: string; name: string; active: boolean }[];
  summary: Check[]; // headline figures for the store page, may be empty
  /** Optional. Why this store is not judged this run, in one plain sentence. Shown on the store page and beside the store in lists. */
  not_judged_reason?: string;
}

/** Salesperson card: 60 words or fewer in `text`. */
export interface Card {
  card_id: string;
  store_id: string;
  salesperson_id: string;
  salesperson_name: string;
  lever: Lever;
  behaviour: string; // the one behaviour
  peer: { salesperson_id: string; name: string }; // same store
  action: string; // the one action for today
  text: string; // the whole card as shown, <= 60 words
  word_count: number;
  checks: Check[];
  /** Optional. One sentence stating how the quoted figure is defined. Shown under the card, outside the 60 words. */
  definition?: string;
}

export interface FollowUp {
  alert_id: string;
  area_manager_id: string;
  store_ids: string[];
  lever: Lever;
  headline: string; // the original alert headline
  action_text: string; // the action that was recommended
  raised_as_of: string;
  measured_as_of: string;
  metric_label: string;
  before: number;
  after: number;
  target: number;
  before_display: string;
  after_display: string;
  target_display: string;
  moved: "improved" | "no_change" | "worse" | "not_measurable";
  verdict: string; // one plain sentence: did the number move
  /** Optional. One sentence stating exactly how the metric is defined. Shown beside before and after. */
  definition?: string;
  checks: Check[];
}

/** Numbers that cannot be right. Listed here and never sent as alerts. */
export interface DataIssue {
  issue_id: string;
  store_id: string;
  kind: string; // e.g. "footfall_zero_with_bills"
  title: string;
  detail: string;
  first_date: string;
  last_date: string;
  days_affected: number;
  handling: string; // what the engine did about it, e.g. "These days are left out of conversion"
  checks: Check[];
}

export interface EngineOutput {
  schema_version: 1;
  as_of: string; // the engine saw no data after this date
  generated_at: string; // ISO 8601 UTC, when the engine ran
  windows: {
    current: DateWindow;
    baseline: DateWindow;
  };
  area_managers: AreaManagerBlock[];
  stores: StoreBlock[];
  cards: Card[];
  follow_ups: FollowUp[];
  data_issues: DataIssue[];
}
