import assert from "node:assert/strict";
import { test } from "node:test";
import {
  HARD_ALERT_CAP,
  MAX_CARD_WORDS,
  alertCap,
  cardView,
  countWords,
  followUpsByManager,
  managerSummaryLine,
  movedCounts,
  notJudgedReason,
  optionalText,
  rupeesAtStakeShown,
  visibleAlerts,
} from "./rules.ts";
import type { Alert, AreaManagerBlock, FollowUp, HeldBackAlert } from "./types.ts";

function alert(rank: number, rupees: number): Alert {
  return {
    alert_id: `TST-0${rank}:more_bills:test`,
    rank,
    scope: "store",
    store_ids: [`TST-0${rank}`],
    city: "Testpur",
    lever: "more_bills",
    cause_code: "test",
    headline: `Alert ranked ${rank}`,
    cause: "Test cause.",
    action: { who: "Who", what: "What", when: "When", text: "Who does what when." },
    rupees_at_stake_weekly: rupees,
    arithmetic: { formula: "a × b", worked: "1 × 1 = 1", input_check_ids: [] },
    benchmark_basis: "Same store, previous 13 weeks",
    salesperson_ids: [],
    checks: [],
    follow_up: {
      metric_label: "Conversion",
      kind: "conversion",
      params: {},
      baseline_value: 0.1,
      target_value: 0.12,
      higher_is_better: true,
    },
  };
}

test("a manager never sees more than max_alerts_per_week alerts", () => {
  const alerts = [1, 2, 3, 4, 5, 6, 7].map((rank) => alert(rank, 1000 * (8 - rank)));
  const shown = visibleAlerts({ alerts, max_alerts_per_week: 3 });
  assert.equal(shown.length, 3);
  assert.deepEqual(shown.map((a) => a.rank), [1, 2, 3]);
});

test("the cap never goes above five, even if the file asks for more", () => {
  const alerts = [1, 2, 3, 4, 5, 6, 7, 8].map((rank) => alert(rank, 1000));
  assert.equal(alertCap({ max_alerts_per_week: 12 }), HARD_ALERT_CAP);
  assert.equal(visibleAlerts({ alerts, max_alerts_per_week: 12 }).length, 5);
});

test("a missing or nonsense cap falls back to five, never to unlimited", () => {
  const alerts = [1, 2, 3, 4, 5, 6, 7].map((rank) => alert(rank, 1000));
  for (const bad of [Number.NaN, -1, Number.POSITIVE_INFINITY, undefined as unknown as number]) {
    assert.equal(visibleAlerts({ alerts, max_alerts_per_week: bad }).length, 5);
  }
});

test("a cap of zero shows nothing", () => {
  assert.equal(visibleAlerts({ alerts: [alert(1, 1000)], max_alerts_per_week: 0 }).length, 0);
});

test("alerts are put in rank order before the cut, so the top ranks survive", () => {
  const alerts = [alert(4, 10), alert(2, 30), alert(6, 5), alert(1, 40), alert(3, 20), alert(5, 8)];
  const shown = visibleAlerts({ alerts, max_alerts_per_week: 5 });
  assert.deepEqual(shown.map((a) => a.rank), [1, 2, 3, 4, 5]);
});

test("visibleAlerts does not reorder the engine's own list", () => {
  const alerts = [alert(2, 30), alert(1, 40)];
  visibleAlerts({ alerts, max_alerts_per_week: 5 });
  assert.deepEqual(alerts.map((a) => a.rank), [2, 1]);
});

test("rupees at stake counts only the alerts that are shown", () => {
  const alerts = [alert(1, 96000), alert(2, 60000), alert(3, 45000)];
  assert.equal(rupeesAtStakeShown({ alerts, max_alerts_per_week: 5 }), 201000);
  assert.equal(rupeesAtStakeShown({ alerts, max_alerts_per_week: 2 }), 156000);
  assert.equal(rupeesAtStakeShown({ alerts: [], max_alerts_per_week: 5 }), 0);
});

test("words are counted by splitting on whitespace", () => {
  assert.equal(countWords(""), 0);
  assert.equal(countWords("   \n\t "), 0);
  assert.equal(countWords("one"), 1);
  assert.equal(countWords("  greet   every\nwalk-in\ttoday  "), 4);
  assert.equal(countWords("₹1,38,600 a week"), 3);
});

test("a card of exactly 60 words is shown", () => {
  const text = Array.from({ length: MAX_CARD_WORDS }, (_, i) => `w${i}`).join(" ");
  const view = cardView({ text });
  assert.equal(view.status, "show");
  assert.equal(view.words, 60);
});

test("a card of 61 words is withheld and its text is not passed on", () => {
  const text = Array.from({ length: MAX_CARD_WORDS + 1 }, (_, i) => `w${i}`).join(" ");
  const view = cardView({ text });
  assert.equal(view.status, "withheld");
  assert.equal(view.words, 61);
  assert.equal("text" in view, false);
});

test("the 60-word rule uses the text itself, not the word_count the file claims", () => {
  const text = Array.from({ length: 75 }, (_, i) => `w${i}`).join(" ");
  const view = cardView({ text, word_count: 40 } as { text: string });
  assert.equal(view.status, "withheld");
  assert.equal(view.words, 75);
});

const held: HeldBackAlert = {
  headline: "Held",
  lever: "more_bills",
  rupees_at_stake_weekly: 500,
  reason: "Below the top 5",
};

test("the summary line counts alerts shown, rupees at stake and alerts held back", () => {
  const alerts = [alert(1, 96000), alert(2, 60000), alert(3, 45000)];
  assert.equal(
    managerSummaryLine({ alerts, max_alerts_per_week: 5, held_back: [held] }),
    "3 alerts this week, ₹2,01,000 a week at stake, 1 held back",
  );
  assert.equal(
    managerSummaryLine({ alerts: [alert(1, 96000)], max_alerts_per_week: 5, held_back: [] }),
    "1 alert this week, ₹96,000 a week at stake, none held back",
  );
  assert.equal(
    managerSummaryLine({ alerts: [], max_alerts_per_week: 5, held_back: [] }),
    "No alerts this week, none held back",
  );
  assert.equal(
    managerSummaryLine({ alerts: [], max_alerts_per_week: 5, held_back: [held, held] }),
    "No alerts this week, 2 held back",
  );
});

test("the summary line counts only what the cap lets the manager see", () => {
  const alerts = [1, 2, 3, 4, 5, 6, 7].map((rank) => alert(rank, 1000));
  assert.equal(
    managerSummaryLine({ alerts, max_alerts_per_week: 9, held_back: [] }),
    "5 alerts this week, ₹5,000 a week at stake, none held back",
  );
});

test("an optional sentence is shown only if it is non-empty text", () => {
  assert.equal(optionalText("  Conversion is bills divided by walk-ins.  "), "Conversion is bills divided by walk-ins.");
  for (const absent of [undefined, null, "", "   ", 0, 12, {}, []]) assert.equal(optionalText(absent), null);
});

test("a store is not judged when the engine gives a reason, or when it is new", () => {
  assert.equal(notJudgedReason({ is_new_store: false }), null);
  assert.equal(notJudgedReason({ is_new_store: false, not_judged_reason: " Closed for refit. " }), "Closed for refit.");
  assert.equal(notJudgedReason({ is_new_store: true, not_judged_reason: "Opened 1 Sep 2026." }), "Opened 1 Sep 2026.");
  assert.equal(notJudgedReason({ is_new_store: true }), "Too new to judge against established stores.");
});

function followUp(alertId: string, managerId: string, moved: FollowUp["moved"]): FollowUp {
  return {
    alert_id: alertId,
    area_manager_id: managerId,
    store_ids: ["TST-01"],
    lever: "more_bills",
    headline: "Headline",
    action_text: "Action",
    raised_as_of: "2026-10-24",
    measured_as_of: "2026-10-31",
    metric_label: "Conversion",
    before: 0.1,
    after: 0.1,
    target: 0.12,
    before_display: "10.0%",
    after_display: "10.0%",
    target_display: "12.0%",
    moved,
    verdict: "Verdict.",
    checks: [],
  };
}

function managerBlock(id: string): AreaManagerBlock {
  return {
    area_manager_id: id,
    name: id,
    city: "Testpur",
    store_ids: [],
    max_alerts_per_week: 5,
    alerts: [],
    held_back: [],
  };
}

test("follow-ups are grouped by area manager, in manager order, and none is dropped", () => {
  const groups = followUpsByManager({
    area_managers: [managerBlock("AM-1"), managerBlock("AM-2"), managerBlock("AM-3")],
    follow_ups: [
      followUp("a", "AM-2", "improved"),
      followUp("b", "AM-GONE", "worse"),
      followUp("c", "AM-1", "no_change"),
      followUp("d", "AM-2", "not_measurable"),
    ],
  });
  assert.deepEqual(
    groups.map((g) => [g.area_manager_id, g.items.map((i) => i.alert_id)]),
    [
      ["AM-1", ["c"]],
      ["AM-2", ["a", "d"]],
      ["AM-GONE", ["b"]],
    ],
  );
  assert.equal(groups[2].manager, undefined);
  assert.equal(
    groups.reduce((sum, g) => sum + g.items.length, 0),
    4,
  );
});

test("the follow-up tally names every outcome that occurred, including the bad ones", () => {
  const items = [
    followUp("a", "AM-1", "worse"),
    followUp("b", "AM-1", "improved"),
    followUp("c", "AM-1", "worse"),
    followUp("d", "AM-1", "not_measurable"),
  ];
  assert.deepEqual(movedCounts(items), [
    { moved: "improved", count: 1 },
    { moved: "worse", count: 2 },
    { moved: "not_measurable", count: 1 },
  ]);
  assert.deepEqual(movedCounts([]), []);
});
