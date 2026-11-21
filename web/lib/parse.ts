// Turns the text of the engine's JSON file into EngineOutput, or says why it cannot.
// It checks every field the pages read, so a damaged file gives the
// "no engine run published" state instead of a half-rendered page.
// Pure functions only, so `node --test` can run them directly.

import type { EngineOutput } from "./types.ts";

export type ParseResult = { ok: true; data: EngineOutput } | { ok: false; reason: string };

type Rec = Record<string, unknown>;

const isRec = (v: unknown): v is Rec => typeof v === "object" && v !== null && !Array.isArray(v);
const isStr = (v: unknown): v is string => typeof v === "string";
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const isStrArr = (v: unknown): v is string[] => Array.isArray(v) && v.every(isStr);
const LEVERS = ["more_bills", "bigger_baskets", "more_repeat"];
const MOVED = ["improved", "no_change", "worse", "not_measurable"];

function need(cond: boolean, what: string): void {
  if (!cond) throw new Error(what);
}

function strings(rec: Rec, where: string, keys: string[]): void {
  for (const key of keys) need(isStr(rec[key]), `${where}.${key} must be text`);
}

function numbers(rec: Rec, where: string, keys: string[]): void {
  for (const key of keys) need(isNum(rec[key]), `${where}.${key} must be a number`);
}

function list(value: unknown, where: string): Rec[] {
  need(Array.isArray(value), `${where} must be a list`);
  const items = value as unknown[];
  items.forEach((item, i) => need(isRec(item), `${where}[${i}] must be an object`));
  return items as Rec[];
}

function record(value: unknown, where: string): Rec {
  need(isRec(value), `${where} must be an object`);
  return value as Rec;
}

function checks(value: unknown, where: string): void {
  list(value, where).forEach((check, i) => {
    strings(check, `${where}[${i}]`, ["id", "label", "display"]);
  });
}

function validate(root: unknown): void {
  const data = record(root, "file");
  need(data.schema_version === 1, "schema_version must be 1");
  strings(data, "file", ["as_of", "generated_at"]);
  const windows = record(data.windows, "windows");
  strings(record(windows.current, "windows.current"), "windows.current", ["start", "end"]);
  strings(record(windows.baseline, "windows.baseline"), "windows.baseline", ["start", "end"]);

  list(data.area_managers, "area_managers").forEach((manager, m) => {
    const at = `area_managers[${m}]`;
    strings(manager, at, ["area_manager_id", "name", "city"]);
    numbers(manager, at, ["max_alerts_per_week"]);
    need(isStrArr(manager.store_ids), `${at}.store_ids must be a list of text`);
    list(manager.alerts, `${at}.alerts`).forEach((alert, a) => {
      const aat = `${at}.alerts[${a}]`;
      strings(alert, aat, ["alert_id", "city", "headline", "cause", "benchmark_basis"]);
      numbers(alert, aat, ["rank", "rupees_at_stake_weekly"]);
      need(alert.scope === "store" || alert.scope === "city", `${aat}.scope must be store or city`);
      need(LEVERS.includes(alert.lever as string), `${aat}.lever is not a known lever`);
      need(isStrArr(alert.store_ids), `${aat}.store_ids must be a list of text`);
      strings(record(alert.action, `${aat}.action`), `${aat}.action`, ["who", "what", "when", "text"]);
      strings(record(alert.arithmetic, `${aat}.arithmetic`), `${aat}.arithmetic`, ["formula", "worked"]);
      checks(alert.checks, `${aat}.checks`);
    });
    list(manager.held_back, `${at}.held_back`).forEach((held, h) => {
      const hat = `${at}.held_back[${h}]`;
      strings(held, hat, ["headline", "reason"]);
      numbers(held, hat, ["rupees_at_stake_weekly"]);
      need(LEVERS.includes(held.lever as string), `${hat}.lever is not a known lever`);
    });
  });

  list(data.stores, "stores").forEach((store, s) => {
    const at = `stores[${s}]`;
    strings(store, at, ["store_id", "city", "state", "tier", "opened_on", "area_manager_id"]);
    need(typeof store.is_new_store === "boolean", `${at}.is_new_store must be true or false`);
    list(store.salespeople, `${at}.salespeople`).forEach((person, p) => {
      strings(person, `${at}.salespeople[${p}]`, ["salesperson_id", "name"]);
      need(typeof person.active === "boolean", `${at}.salespeople[${p}].active must be true or false`);
    });
    checks(store.summary, `${at}.summary`);
  });

  list(data.cards, "cards").forEach((card, c) => {
    const at = `cards[${c}]`;
    strings(card, at, ["card_id", "store_id", "salesperson_id", "salesperson_name", "text"]);
    need(LEVERS.includes(card.lever as string), `${at}.lever is not a known lever`);
    strings(record(card.peer, `${at}.peer`), `${at}.peer`, ["salesperson_id", "name"]);
  });

  list(data.follow_ups, "follow_ups").forEach((item, f) => {
    const at = `follow_ups[${f}]`;
    strings(item, at, [
      "alert_id",
      "area_manager_id",
      "headline",
      "action_text",
      "raised_as_of",
      "measured_as_of",
      "metric_label",
      "before_display",
      "after_display",
      "target_display",
      "verdict",
    ]);
    need(LEVERS.includes(item.lever as string), `${at}.lever is not a known lever`);
    need(MOVED.includes(item.moved as string), `${at}.moved is not a known result`);
    need(isStrArr(item.store_ids), `${at}.store_ids must be a list of text`);
    checks(item.checks, `${at}.checks`);
  });

  list(data.data_issues, "data_issues").forEach((issue, d) => {
    const at = `data_issues[${d}]`;
    strings(issue, at, ["issue_id", "store_id", "kind", "title", "detail", "first_date", "last_date", "handling"]);
    numbers(issue, at, ["days_affected"]);
    checks(issue.checks, `${at}.checks`);
  });
}

export function parseEngineOutput(text: string): ParseResult {
  let root: unknown;
  try {
    // Strip a byte-order mark if the writer left one.
    root = JSON.parse(text.charCodeAt(0) === 0xfeff ? text.slice(1) : text);
  } catch (error) {
    return { ok: false, reason: `not valid JSON: ${(error as Error).message}` };
  }
  try {
    validate(root);
  } catch (error) {
    return { ok: false, reason: (error as Error).message };
  }
  return { ok: true, data: root as EngineOutput };
}
