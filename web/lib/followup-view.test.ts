import assert from "node:assert/strict";
import { test } from "node:test";
import {
  NO_VALUE,
  NO_VERDICT_NOTE,
  addDays,
  afterFigure,
  beforeFigure,
  formatDateSpan,
  parseHistoryNote,
} from "./followup-view.ts";
import type { Check, FollowUp } from "./types.ts";

const ID = "LKO-02:more_bills:salesperson_left:SP1018";

function check(slug: string, value: number, display: string, start: string, end: string, label = ""): Check {
  return { id: `followup:${ID}:${slug}`, label, kind: "x", params: { start, end }, value, display };
}

function item(moved: FollowUp["moved"], checks: Check[]): FollowUp {
  return {
    alert_id: ID,
    area_manager_id: "AM1",
    store_ids: ["LKO-02"],
    lever: "more_bills",
    headline: "h",
    action_text: "a",
    raised_as_of: "2026-10-24",
    measured_as_of: "2026-10-31",
    metric_label: "Conversion",
    before: 0.098,
    after: moved === "not_measurable" ? (null as unknown as number) : 0.114,
    target: 0.12,
    before_display: "9.8%",
    after_display: moved === "not_measurable" ? "not measurable" : "11.4%",
    target_display: "12.0%",
    moved,
    verdict: "v",
    checks,
  };
}

const conversionChecks = [
  check("before", 0.098, "9.8%", "2026-09-27", "2026-10-24"),
  check("after", 0.114, "11.4%", "2026-10-25", "2026-10-31"),
  check("after_numerator", 92, "92", "2026-10-25", "2026-10-31", "Bills in those days"),
  check("after_denominator", 805, "805", "2026-10-25", "2026-10-31", "Walk-ins in those days"),
  check("before_numerator", 138, "138", "2026-09-27", "2026-10-24", "Bills behind the figure when raised"),
  check("before_denominator", 1415, "1,415", "2026-09-27", "2026-10-24", "Walk-ins behind the figure when raised"),
];

test("date spans read like 25 Oct to 31 Oct 2026", () => {
  assert.equal(formatDateSpan("2026-10-25", "2026-10-31"), "25 Oct to 31 Oct 2026");
  assert.equal(formatDateSpan("2025-12-29", "2026-01-04"), "29 Dec 2025 to 4 Jan 2026");
  assert.equal(addDays("2026-10-24", 1), "2026-10-25");
  assert.equal(addDays("2026-12-31", 1), "2027-01-01");
});

test("before and after carry their windows and the sample behind them", () => {
  const fu = item("no_change", conversionChecks);
  const b = beforeFigure(fu);
  const a = afterFigure(fu);
  assert.equal(b.display, "9.8%");
  assert.deepEqual(b.window, { start: "2026-09-27", end: "2026-10-24" });
  assert.equal(b.sample, "138 bills from 1,415 walk-ins");
  assert.equal(a.display, "11.4%");
  assert.deepEqual(a.window, { start: "2026-10-25", end: "2026-10-31" });
  assert.equal(a.sample, "92 bills from 805 walk-ins");
  assert.equal(a.note, null);
});

test("with no verdict the after figure is still shown, labelled honestly", () => {
  const a = afterFigure(item("not_measurable", conversionChecks.slice(0, 2)));
  assert.equal(a.display, "11.4%");
  assert.equal(a.note, NO_VERDICT_NOTE);
  assert.equal(a.sample, null);
});

test("no after check: 'no value', and the window is the 7 days after the alert", () => {
  const a = afterFigure(item("not_measurable", conversionChecks.slice(0, 1)));
  assert.equal(a.display, NO_VALUE);
  assert.deepEqual(a.window, { start: "2026-10-25", end: "2026-10-31" });
});

test("history.json is checked before use", () => {
  assert.equal(parseHistoryNote(null), null);
  assert.equal(parseHistoryNote({ raised_as_of: "x", measured_as_of: "2026-07-18", alert_id: "a" }), null);
  assert.deepEqual(
    parseHistoryNote({ raised_as_of: "2026-07-11", measured_as_of: "2026-07-18", alert_id: "a", note: "n" }),
    { raised_as_of: "2026-07-11", measured_as_of: "2026-07-18", alert_id: "a", note: "n" },
  );
});
