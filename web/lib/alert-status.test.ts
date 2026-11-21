import assert from "node:assert/strict";
import { test } from "node:test";
import {
  parseStatusRows,
  statusConfig,
  statusHeaders,
  statusQueryUrl,
  statusWriteBody,
  statusWriteHeaders,
  statusWriteUrl,
} from "./alert-status.ts";

const config = { url: "https://example.supabase.co", anonKey: "anon-key" };

test("there is no tick unless both the URL and the anon key are set", () => {
  assert.equal(statusConfig(undefined, undefined), null);
  assert.equal(statusConfig("https://example.supabase.co", undefined), null);
  assert.equal(statusConfig(undefined, "anon-key"), null);
  assert.equal(statusConfig("  ", "anon-key"), null);
  assert.equal(statusConfig("https://example.supabase.co", "  "), null);
  assert.equal(statusConfig("example.supabase.co", "anon-key"), null);
  assert.deepEqual(statusConfig(" https://example.supabase.co// ", " anon-key "), config);
});

test("the read asks for all the page's alerts in one request, each id quoted", () => {
  const url = statusQueryUrl(config, ["BLR-03:more_bills:missed_shifts", "New Delhi:more_bills:market_slowdown"]);
  assert.equal(
    url,
    "https://example.supabase.co/rest/v1/alert_status?select=alert_id,done&alert_id=in.(" +
      encodeURIComponent('"BLR-03:more_bills:missed_shifts","New Delhi:more_bills:market_slowdown"') +
      ")",
  );
  assert.equal(
    new URL(url).searchParams.get("alert_id"),
    'in.("BLR-03:more_bills:missed_shifts","New Delhi:more_bills:market_slowdown")',
  );
});

test("an id cannot break out of its quotes, and a repeated id is sent once", () => {
  const url = statusQueryUrl(config, ['a"b\\c,d)', "x", "x"]);
  assert.equal(new URL(url).searchParams.get("alert_id"), 'in.("a\\"b\\\\c,d)","x")');
});

test("the write is an upsert with the anon key and nothing else", () => {
  assert.equal(statusWriteUrl(config), "https://example.supabase.co/rest/v1/alert_status");
  assert.deepEqual(statusHeaders(config), { apikey: "anon-key", Authorization: "Bearer anon-key" });
  assert.deepEqual(statusWriteHeaders(config), {
    apikey: "anon-key",
    Authorization: "Bearer anon-key",
    "Content-Type": "application/json",
    Prefer: "resolution=merge-duplicates,return=minimal",
  });
  assert.deepEqual(JSON.parse(statusWriteBody("BLR-03:more_bills:x", true, new Date("2026-11-01T01:30:00Z"))), {
    alert_id: "BLR-03:more_bills:x",
    done: true,
    updated_at: "2026-11-01T01:30:00.000Z",
  });
});

test("the reply is read as ticks; an alert with no row is not ticked", () => {
  const ticks = parseStatusRows([
    { alert_id: "a", done: true },
    { alert_id: "b", done: false },
    { alert_id: "c", done: null },
  ]);
  assert.ok(ticks);
  assert.equal(ticks.get("a"), true);
  assert.equal(ticks.get("b"), false);
  assert.equal(ticks.get("c"), false);
  assert.equal(ticks.has("d"), false);
  assert.equal(parseStatusRows([])?.size, 0);
});

test("a reply that is not a list of rows counts as a failure", () => {
  assert.equal(parseStatusRows({ message: "permission denied" }), null);
  assert.equal(parseStatusRows(null), null);
  assert.equal(parseStatusRows([{ done: true }]), null);
  assert.equal(parseStatusRows(["a"]), null);
});
