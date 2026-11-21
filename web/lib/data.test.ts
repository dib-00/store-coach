import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { developmentOverrideFile, readEngineFile } from "./data.ts";
import { parseEngineOutput } from "./parse.ts";
import { cardView, countWords, visibleAlerts } from "./rules.ts";

const FIXTURE = path.join(import.meta.dirname, "..", "fixtures", "sample.json");
const fixtureText = fs.readFileSync(FIXTURE, "utf8");

test("the sample fixture is accepted", () => {
  const data = readEngineFile(FIXTURE);
  assert.ok(data);
  assert.equal(data.area_managers.length, 2);
  assert.equal(data.cards.length, 3);
  assert.equal(data.follow_ups.length, 3);
  assert.equal(data.data_issues.length, 1);
});

test("the sample fixture obeys the rules it is used to demonstrate", () => {
  const data = readEngineFile(FIXTURE);
  assert.ok(data);
  for (const manager of data.area_managers) {
    assert.ok(manager.alerts.length <= manager.max_alerts_per_week);
    assert.deepEqual(visibleAlerts(manager), manager.alerts);
  }
  for (const card of data.cards) {
    assert.equal(card.word_count, countWords(card.text), card.card_id);
    assert.equal(cardView(card).status, "show", card.card_id);
  }
  // Fictional ids only, so the fixture can never be mistaken for real output.
  for (const store of data.stores) assert.match(store.store_id, /^TST-/);
});

test("a missing file gives null, not an error and not sample data", () => {
  assert.equal(readEngineFile(path.join(import.meta.dirname, "no-such-file.json")), null);
});

test("text that is not JSON is rejected", () => {
  const result = parseEngineOutput("{ not json");
  assert.equal(result.ok, false);
});

test("JSON with NaN in it, as Python can write, is rejected", () => {
  const result = parseEngineOutput(fixtureText.replace('"rupees_at_stake_weekly": 96000', '"rupees_at_stake_weekly": NaN'));
  assert.equal(result.ok, false);
});

test("a file with the wrong schema version is rejected", () => {
  const result = parseEngineOutput(fixtureText.replace('"schema_version": 1', '"schema_version": 2'));
  assert.deepEqual(result, { ok: false, reason: "schema_version must be 1" });
});

test("a file with a required part missing is rejected with the field named", () => {
  const broken = JSON.parse(fixtureText);
  delete broken.area_managers[0].alerts[0].action;
  const result = parseEngineOutput(JSON.stringify(broken));
  assert.deepEqual(result, { ok: false, reason: "area_managers[0].alerts[0].action must be an object" });
});

test("a rupee figure sent as text is rejected", () => {
  const broken = JSON.parse(fixtureText);
  broken.area_managers[0].alerts[0].rupees_at_stake_weekly = "96000";
  assert.equal(parseEngineOutput(JSON.stringify(broken)).ok, false);
});

test("a byte-order mark at the start of the file is tolerated", () => {
  assert.equal(parseEngineOutput(`﻿${fixtureText}`).ok, true);
});

test("the development override is honoured locally and ignored on Vercel", () => {
  assert.equal(developmentOverrideFile({}), null);
  assert.equal(developmentOverrideFile({ STORE_COACH_DATA_FILE: "  " }), null);
  assert.equal(developmentOverrideFile({ STORE_COACH_DATA_FILE: FIXTURE }), path.resolve(FIXTURE));
  assert.equal(developmentOverrideFile({ STORE_COACH_DATA_FILE: FIXTURE, VERCEL: "1" }), null);
});

test("the sample fixture shows a manager at the cap of five, with all three levers", () => {
  const data = readEngineFile(FIXTURE);
  assert.ok(data);
  const shown = visibleAlerts(data.area_managers[0]);
  assert.equal(shown.length, 5);
  assert.deepEqual([...new Set(shown.map((a) => a.lever))].sort(), ["bigger_baskets", "more_bills", "more_repeat"]);
  // Ranked by rupees at stake, biggest first.
  const rupees = shown.map((a) => a.rupees_at_stake_weekly);
  assert.deepEqual(rupees, [...rupees].sort((a, b) => b - a));
});

test("the sample fixture uses the optional fields, and states no hour of day", () => {
  const data = readEngineFile(FIXTURE);
  assert.ok(data);
  for (const manager of data.area_managers) {
    for (const alert of manager.alerts) assert.equal(typeof alert.definition, "string", alert.alert_id);
  }
  for (const card of data.cards) assert.equal(typeof card.definition, "string", card.card_id);
  for (const item of data.follow_ups) assert.equal(typeof item.definition, "string", item.alert_id);
  assert.equal(data.stores.filter((s) => typeof s.not_judged_reason === "string").length, 1);
  assert.doesNotMatch(fixtureText, /\b\d{1,2}(:\d{2})?\s?(am|pm)\b|\bnoon\b/i);
});

test("a file without the optional fields is still accepted", () => {
  const stripped = JSON.parse(fixtureText);
  for (const manager of stripped.area_managers) for (const alert of manager.alerts) delete alert.definition;
  for (const card of stripped.cards) delete card.definition;
  for (const item of stripped.follow_ups) delete item.definition;
  for (const store of stripped.stores) delete store.not_judged_reason;
  assert.equal(parseEngineOutput(JSON.stringify(stripped)).ok, true);
});

test("an optional field sent as null does not reject the whole file", () => {
  const odd = JSON.parse(fixtureText);
  odd.area_managers[0].alerts[0].definition = null;
  odd.stores[0].not_judged_reason = null;
  assert.equal(parseEngineOutput(JSON.stringify(odd)).ok, true);
});
