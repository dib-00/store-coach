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
  assert.equal(data.follow_ups.length, 2);
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
