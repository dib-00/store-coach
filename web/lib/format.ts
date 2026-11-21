// Formatting for values the engine sends raw (rupees, dates, the run time).
// Figures that arrive preformatted in Check.display are shown untouched.
// Pure functions only, so `node --test` can run them directly.

import type { Lever } from "./types.ts";

const RUPEE_DIGITS = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

/** 138600 -> "₹1,38,600" (Indian digit grouping, whole rupees). */
export function formatRupees(value: number): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "not available";
  const rounded = Math.round(value);
  const digits = RUPEE_DIGITS.format(Math.abs(rounded));
  return rounded < 0 ? `-₹${digits}` : `₹${digits}`;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-10-31" -> "31 Oct 2026". Anything that is not a real calendar date is returned unchanged. */
export function formatDate(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(typeof isoDate === "string" ? isoDate : "");
  if (!match) return String(isoDate);
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const check = new Date(Date.UTC(year, month - 1, day));
  if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) {
    return isoDate;
  }
  return `${day} ${MONTHS[month - 1]} ${year}`;
}

/** "25 Oct 2026 to 31 Oct 2026" */
export function formatDateRange(start: string, end: string): string {
  return `${formatDate(start)} to ${formatDate(end)}`;
}

const IST_OFFSET_MS = (5 * 60 + 30) * 60 * 1000;

/**
 * ISO 8601 instant -> the wall-clock time in India, e.g. "1 Nov 2026, 7:00 am IST".
 * IST is UTC+05:30 all year, so the offset is applied directly.
 * A timestamp with no zone is read as UTC, which is what the contract says the engine writes.
 */
export function formatIstDateTime(isoInstant: string): string {
  const text = typeof isoInstant === "string" ? isoInstant.trim() : "";
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/i.test(text);
  const ms = Date.parse(hasZone ? text : `${text}Z`);
  if (text === "" || Number.isNaN(ms)) return String(isoInstant);
  const ist = new Date(ms + IST_OFFSET_MS);
  const hours24 = ist.getUTCHours();
  const hours12 = hours24 % 12 === 0 ? 12 : hours24 % 12;
  const minutes = String(ist.getUTCMinutes()).padStart(2, "0");
  const meridiem = hours24 < 12 ? "am" : "pm";
  return `${ist.getUTCDate()} ${MONTHS[ist.getUTCMonth()]} ${ist.getUTCFullYear()}, ${hours12}:${minutes} ${meridiem} IST`;
}

const LEVER_LABELS: Record<Lever, string> = {
  more_bills: "More bills",
  bigger_baskets: "Bigger baskets",
  more_repeat: "More repeat",
};

export function leverLabel(lever: Lever): string {
  return LEVER_LABELS[lever] ?? String(lever);
}
