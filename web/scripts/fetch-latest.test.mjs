import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { chooseLatest, fetchLatest, instantMs, latestRunRequest } from "./fetch-latest.mjs";

const committed = { schema_version: 1, as_of: "2026-10-31", generated_at: "2026-11-01T01:30:00Z" };
const run = (overrides = {}) => ({
  schema_version: 1,
  as_of: "2026-10-31",
  generated_at: "2026-11-02T01:30:00Z",
  ...overrides,
});

// ---- which one wins -------------------------------------------------------------------------

test("a published run generated after the committed file wins", () => {
  assert.equal(chooseLatest(committed, run()).use, "remote");
  assert.equal(chooseLatest(committed, run({ as_of: "2026-11-01" })).use, "remote");
});

test("a published run that is not newer loses, including an exact tie", () => {
  assert.equal(chooseLatest(committed, run({ generated_at: "2026-11-01T01:30:00Z" })).use, "committed");
  assert.equal(chooseLatest(committed, run({ generated_at: "2026-10-31T23:59:59Z" })).use, "committed");
});

test("times are compared as instants, not as text", () => {
  // 07:00 at +05:30 is 01:30 UTC: the same instant as the committed file, so not newer.
  assert.equal(chooseLatest(committed, run({ generated_at: "2026-11-01T07:00:00+05:30" })).use, "committed");
  // 07:01 at +05:30 is one minute later.
  assert.equal(chooseLatest(committed, run({ generated_at: "2026-11-01T07:01:00+05:30" })).use, "remote");
  // No zone is read as UTC, the same way the pages read it.
  assert.equal(chooseLatest(committed, run({ generated_at: "2026-11-01T01:30:01" })).use, "remote");
  assert.equal(instantMs("2026-11-01T01:30:00"), instantMs("2026-11-01T01:30:00Z"));
});

test("a run for an older data date loses even if it was generated later", () => {
  const decision = chooseLatest(committed, run({ as_of: "2026-10-30", generated_at: "2026-12-01T00:00:00Z" }));
  assert.equal(decision.use, "committed");
  assert.match(decision.reason, /older data/);
});

test("a run with the wrong schema version, or no valid dates, loses", () => {
  assert.equal(chooseLatest(committed, run({ schema_version: 2 })).use, "committed");
  assert.equal(chooseLatest(committed, run({ schema_version: "1" })).use, "committed");
  assert.equal(chooseLatest(committed, run({ generated_at: "yesterday" })).use, "committed");
  assert.equal(chooseLatest(committed, run({ generated_at: undefined })).use, "committed");
  assert.equal(chooseLatest(committed, run({ as_of: "31 Oct 2026" })).use, "committed");
});

test("no published run at all keeps the committed file", () => {
  for (const nothing of [null, undefined, "text", 7, []]) {
    assert.equal(chooseLatest(committed, nothing).use, "committed");
  }
});

test("with no usable committed file, a sound published run wins and an unsound one still loses", () => {
  assert.equal(chooseLatest(null, run()).use, "remote");
  assert.equal(chooseLatest({ as_of: "2026-10-31", generated_at: "not a time" }, run()).use, "remote");
  assert.equal(chooseLatest(null, run({ schema_version: 2 })).use, "committed");
});

// ---- the request ----------------------------------------------------------------------------

test("the request needs both settings and sends only the anon key", () => {
  assert.equal(latestRunRequest({}), null);
  assert.equal(latestRunRequest({ NEXT_PUBLIC_SUPABASE_URL: "https://x.supabase.co" }), null);
  assert.equal(latestRunRequest({ NEXT_PUBLIC_SUPABASE_ANON_KEY: "anon" }), null);
  assert.equal(latestRunRequest({ NEXT_PUBLIC_SUPABASE_URL: " ", NEXT_PUBLIC_SUPABASE_ANON_KEY: "anon" }), null);
  assert.deepEqual(
    latestRunRequest({ NEXT_PUBLIC_SUPABASE_URL: "https://x.supabase.co/", NEXT_PUBLIC_SUPABASE_ANON_KEY: "anon" }),
    {
      url: "https://x.supabase.co/rest/v1/runs?select=output,as_of,generated_at&order=as_of.desc,generated_at.desc&limit=1",
      headers: { apikey: "anon", Authorization: "Bearer anon" },
    },
  );
});

// ---- the whole job, against a temporary file and a stand-in for the network ------------------

const FIXTURE = path.join(import.meta.dirname, "..", "fixtures", "sample.json");
const fixture = JSON.parse(fs.readFileSync(FIXTURE, "utf8")); // generated_at 2026-11-01T01:30:00Z
const env = { NEXT_PUBLIC_SUPABASE_URL: "https://x.supabase.co", NEXT_PUBLIC_SUPABASE_ANON_KEY: "anon" };

function tempCopyOfFixture() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "sc-fetch-latest-"));
  const file = path.join(dir, "latest.json");
  fs.copyFileSync(FIXTURE, file);
  return file;
}

const answering = (status, body) => async () => ({ ok: status >= 200 && status < 300, status, json: async () => body });

test("a newer, sound published run is written over the file", async () => {
  const file = tempCopyOfFixture();
  const newer = { ...fixture, generated_at: "2026-11-02T01:30:00Z" };
  const result = await fetchLatest({ env, file, fetchImpl: answering(200, [{ output: newer }]) });
  assert.equal(result.wrote, true);
  assert.equal(JSON.parse(fs.readFileSync(file, "utf8")).generated_at, "2026-11-02T01:30:00Z");
});

test("a run stored as JSON text is read the same way", async () => {
  const file = tempCopyOfFixture();
  const newer = JSON.stringify({ ...fixture, generated_at: "2026-11-02T01:30:00Z" });
  const result = await fetchLatest({ env, file, fetchImpl: answering(200, [{ output: newer }]) });
  assert.equal(result.wrote, true);
});

test("the file is left byte for byte as it was in every other case", async () => {
  const before = fs.readFileSync(FIXTURE);
  const newer = { ...fixture, generated_at: "2026-11-02T01:30:00Z" };
  const damaged = { ...newer, area_managers: "none" }; // newer, but the pages would reject it
  const timeout = Object.assign(new Error("timed out"), { name: "TimeoutError" });
  const cases = [
    ["settings missing", { env: {}, fetchImpl: answering(200, [{ output: newer }]) }, /not set/],
    ["HTTP error", { env, fetchImpl: answering(500, { message: "down" }) }, /HTTP 500/],
    ["not a list", { env, fetchImpl: answering(200, { message: "permission denied" }) }, /list of rows/],
    ["no rows", { env, fetchImpl: answering(200, []) }, /no published run/],
    ["same run", { env, fetchImpl: answering(200, [{ output: fixture }]) }, /not newer/],
    ["older data", { env, fetchImpl: answering(200, [{ output: { ...newer, as_of: "2026-10-01" } }]) }, /older data/],
    ["damaged run", { env, fetchImpl: answering(200, [{ output: damaged }]) }, /failed the site's checks/],
    ["bad JSON text", { env, fetchImpl: answering(200, [{ output: "{ not json" }]) }, /kept the committed file/],
    ["network error", { env, fetchImpl: async () => Promise.reject(new Error("getaddrinfo ENOTFOUND")) }, /ENOTFOUND/],
    ["timeout", { env, fetchImpl: async () => Promise.reject(timeout) }, /no answer within 8 s/],
  ];
  for (const [name, options, expected] of cases) {
    const file = tempCopyOfFixture();
    const result = await fetchLatest({ file, ...options });
    assert.equal(result.wrote, false, name);
    assert.match(result.message, expected, name);
    assert.deepEqual(fs.readFileSync(file), before, name);
  }
});

test("a request that never answers is given up on, and the file is untouched", async () => {
  const file = tempCopyOfFixture();
  const before = fs.readFileSync(file);
  const never = (_url, { signal }) =>
    new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(signal.reason)));
  const result = await fetchLatest({ env, file, fetchImpl: never, timeoutMs: 50 });
  assert.equal(result.wrote, false);
  assert.match(result.message, /no answer within 0\.05 s/);
  assert.deepEqual(fs.readFileSync(file), before);
});
