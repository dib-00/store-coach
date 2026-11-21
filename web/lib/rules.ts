// Display rules the web app enforces whatever the JSON file says.
// Pure functions only: no Next.js, React or Node imports, so `node --test` can run them directly.

import { formatRupees } from "./format.ts";
import type { Alert, AreaManagerBlock, Card, DataIssue, EngineOutput, FollowUp, StoreBlock } from "./types.ts";

/** Product rule: an area manager never gets more than five alerts in a week. */
export const HARD_ALERT_CAP = 5;

/** Product rule: a salesperson card is 60 words or fewer. */
export const MAX_CARD_WORDS = 60;

/** The cap for one manager: their own max_alerts_per_week, never above the hard cap. */
export function alertCap(manager: Pick<AreaManagerBlock, "max_alerts_per_week">): number {
  const cap = manager.max_alerts_per_week;
  if (typeof cap !== "number" || !Number.isFinite(cap) || cap < 0) return HARD_ALERT_CAP;
  return Math.min(Math.floor(cap), HARD_ALERT_CAP);
}

type AlertList = Pick<AreaManagerBlock, "alerts" | "max_alerts_per_week">;

/**
 * The alerts an area manager is allowed to see: rank order, cut at the cap.
 * The engine should already send at most the cap; this slices again in case it did not.
 */
export function visibleAlerts(manager: AlertList): Alert[] {
  const alerts = Array.isArray(manager.alerts) ? manager.alerts : [];
  return [...alerts].sort((a, b) => a.rank - b.rank).slice(0, alertCap(manager));
}

/** Rupees at stake across the alerts the manager can see. A whole-rupee sum and nothing else. */
export function rupeesAtStakeShown(manager: AlertList): number {
  return visibleAlerts(manager).reduce((sum, alert) => sum + alert.rupees_at_stake_weekly, 0);
}

/** Words are counted by splitting on whitespace. */
export function countWords(text: string): number {
  const trimmed = text.trim();
  return trimmed === "" ? 0 : trimmed.split(/\s+/).length;
}

export type CardView =
  | { status: "show"; words: number; text: string }
  | { status: "withheld"; words: number };

/** A card over 60 words is never shown as-is. The count comes from the text, not from word_count. */
export function cardView(card: Pick<Card, "text">): CardView {
  const words = countWords(card.text);
  if (words > MAX_CARD_WORDS) return { status: "withheld", words };
  return { status: "show", words, text: card.text };
}

export function findManager(data: EngineOutput, id: string): AreaManagerBlock | undefined {
  return data.area_managers.find((m) => m.area_manager_id === id);
}

export function findStore(data: EngineOutput, id: string): StoreBlock | undefined {
  return data.stores.find((s) => s.store_id === id);
}

export function cardsForStore(data: EngineOutput, storeId: string): Card[] {
  return data.cards.filter((c) => c.store_id === storeId);
}

export function dataIssuesForStore(data: EngineOutput, storeId: string): DataIssue[] {
  return data.data_issues.filter((i) => i.store_id === storeId);
}

/** Store ids that have a page of their own. Links to any other id are shown as plain text. */
export function storeIdsWithPages(data: EngineOutput): Set<string> {
  return new Set(data.stores.map((s) => s.store_id));
}

/**
 * An optional sentence from the engine (a definition, a not-judged reason).
 * Anything that is not non-empty text counts as absent, so a stray null can never reach the page.
 */
export function optionalText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/** Said of a new store when the engine gives no reason of its own. */
export const NEW_STORE_REASON = "Too new to judge against established stores.";

/** Why a store is not judged this run, or null if it is judged. The engine's own sentence wins. */
export function notJudgedReason(store: Pick<StoreBlock, "is_new_store" | "not_judged_reason">): string | null {
  return optionalText(store.not_judged_reason) ?? (store.is_new_store === true ? NEW_STORE_REASON : null);
}

type ManagerCounts = AlertList & Pick<AreaManagerBlock, "held_back">;

/** The line at the top of a manager's page: "3 alerts this week, ₹2,01,000 a week at stake, 1 held back". */
export function managerSummaryLine(manager: ManagerCounts): string {
  const shown = visibleAlerts(manager).length;
  const held = Array.isArray(manager.held_back) ? manager.held_back.length : 0;
  const heldPart = held === 0 ? "none held back" : `${held} held back`;
  if (shown === 0) return `No alerts this week, ${heldPart}`;
  const alertPart = shown === 1 ? "1 alert this week" : `${shown} alerts this week`;
  return `${alertPart}, ${formatRupees(rupeesAtStakeShown(manager))} a week at stake, ${heldPart}`;
}

export interface FollowUpGroup {
  area_manager_id: string;
  manager: AreaManagerBlock | undefined; // undefined when the file names a manager it does not list
  items: FollowUp[];
}

/**
 * Follow-ups grouped by area manager, in the order the managers are listed.
 * A follow-up naming an unknown manager is kept, in a group of its own at the end, never dropped.
 */
export function followUpsByManager(data: Pick<EngineOutput, "area_managers" | "follow_ups">): FollowUpGroup[] {
  const groups = new Map<string, FollowUpGroup>();
  for (const manager of data.area_managers) {
    groups.set(manager.area_manager_id, { area_manager_id: manager.area_manager_id, manager, items: [] });
  }
  for (const item of data.follow_ups) {
    let group = groups.get(item.area_manager_id);
    if (!group) {
      group = { area_manager_id: item.area_manager_id, manager: undefined, items: [] };
      groups.set(item.area_manager_id, group);
    }
    group.items.push(item);
  }
  return [...groups.values()].filter((group) => group.items.length > 0);
}

const MOVED_ORDER: FollowUp["moved"][] = ["improved", "no_change", "worse", "not_measurable"];

/** How many follow-ups ended each way, in a fixed order, leaving out the ones that did not occur. */
export function movedCounts(items: Pick<FollowUp, "moved">[]): { moved: FollowUp["moved"]; count: number }[] {
  return MOVED_ORDER.map((moved) => ({ moved, count: items.filter((i) => i.moved === moved).length })).filter(
    (entry) => entry.count > 0,
  );
}
