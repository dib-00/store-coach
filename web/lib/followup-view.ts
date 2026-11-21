// What the follow-up page shows for before and after: the figure, the days it covers and the
// sample behind it. Read only from the checks already in the follow-up, so every number shown
// is one a check carries. Pure functions only, so `node --test` can run them directly.

import { formatDate } from "./format.ts";
import type { Check, FollowUp } from "./types.ts";

export interface DateWindow {
  start: string;
  end: string;
}

export interface Figure {
  display: string; // "11.4%", or "no value"
  note: string | null; // "not enough history to call a move", shown beside the figure
  window: DateWindow | null;
  sample: string | null; // "92 bills from 805 walk-ins"
}

export const NO_VALUE = "no value";
export const NO_VERDICT_NOTE = "not enough to call a move either way";

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;

/** "25 Oct to 31 Oct 2026"; the first year is written too when the two years differ. */
export function formatDateSpan(start: string, end: string): string {
  const a = formatDate(start);
  const b = formatDate(end);
  if (ISO_DAY.test(start) && ISO_DAY.test(end) && start.slice(0, 4) === end.slice(0, 4) && a !== start) {
    return `${a.replace(/ \d{4}$/, "")} to ${b}`;
  }
  return `${a} to ${b}`;
}

/** An ISO day plus n days, or null if it is not a date. */
export function addDays(isoDay: string, n: number): string | null {
  if (!ISO_DAY.test(isoDay)) return null;
  const d = new Date(`${isoDay}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return null;
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** The follow-up's own check with id `followup:<alert_id>:<slug>`, if it was written. */
export function followUpCheck(item: Pick<FollowUp, "alert_id" | "checks">, slug: string): Check | null {
  const id = `followup:${item.alert_id}:${slug}`;
  return (item.checks ?? []).find((c) => c.id === id) ?? null;
}

function hasValue(check: Check | null): check is Check {
  if (!check) return false;
  const v = check.value;
  if (typeof v === "number") return Number.isFinite(v);
  return typeof v === "string" && v !== "";
}

/** The days a check measured, from its own params. */
export function checkWindow(check: Check | null): DateWindow | null {
  if (!check) return null;
  const { start, end } = check.params ?? {};
  if (typeof start === "string" && typeof end === "string" && ISO_DAY.test(start) && ISO_DAY.test(end)) {
    return { start, end };
  }
  return null;
}

/** "Bills in those days" -> "bills". */
function noun(check: Check): string {
  return (check.label ?? "").trim().split(/\s+/)[0]?.toLowerCase() ?? "";
}

function sample(item: FollowUp, side: "before" | "after"): string | null {
  const num = followUpCheck(item, `${side}_numerator`);
  const den = followUpCheck(item, `${side}_denominator`);
  if (!hasValue(num) || !hasValue(den)) return null;
  return `${num.display} ${noun(num)} from ${den.display} ${noun(den)}`;
}

export function beforeFigure(item: FollowUp): Figure {
  const check = followUpCheck(item, "before");
  return {
    display: hasValue(check) ? check.display : item.before_display || NO_VALUE,
    note: null,
    window: checkWindow(check),
    sample: sample(item, "before"),
  };
}

/** The after figure is shown whenever the "after" check has a value, even with no verdict. */
export function afterFigure(item: FollowUp): Figure {
  const check = followUpCheck(item, "after");
  let window = checkWindow(check);
  if (!window) {
    const start = addDays(item.raised_as_of, 1);
    if (start && ISO_DAY.test(item.measured_as_of)) window = { start, end: item.measured_as_of };
  }
  if (!hasValue(check)) return { display: NO_VALUE, note: null, window, sample: null };
  return {
    display: check.display,
    note: item.moved === "not_measurable" ? NO_VERDICT_NOTE : null,
    window,
    sample: sample(item, "after"),
  };
}

export interface HistoryNote {
  raised_as_of: string;
  measured_as_of: string;
  alert_id: string;
  note: string;
}

/** web/public/data/history.json, checked; null if it is not usable. */
export function parseHistoryNote(value: unknown): HistoryNote | null {
  if (!value || typeof value !== "object") return null;
  const v = value as Record<string, unknown>;
  const { raised_as_of, measured_as_of, alert_id, note } = v;
  if (typeof raised_as_of !== "string" || !ISO_DAY.test(raised_as_of)) return null;
  if (typeof measured_as_of !== "string" || !ISO_DAY.test(measured_as_of)) return null;
  if (typeof alert_id !== "string" || alert_id === "") return null;
  return { raised_as_of, measured_as_of, alert_id, note: typeof note === "string" ? note : "" };
}
