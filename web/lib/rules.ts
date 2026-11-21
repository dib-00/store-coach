// Display rules the web app enforces whatever the JSON file says.
// Pure functions only: no Next.js, React or Node imports, so `node --test` can run them directly.

import type { Alert, AreaManagerBlock, Card, DataIssue, EngineOutput, StoreBlock } from "./types.ts";

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
