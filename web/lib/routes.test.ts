import assert from "node:assert/strict";
import { test } from "node:test";
import { NO_RUN_PARAM, routeId, staticIds } from "./routes.ts";

test("every id gets a page, once", () => {
  assert.deepEqual(staticIds(["TST-01", "TST-02", "TST-01"]), [{ id: "TST-01" }, { id: "TST-02" }]);
});

test("with no ids, one placeholder page is built so the site still builds", () => {
  assert.deepEqual(staticIds([]), [{ id: NO_RUN_PARAM }]);
});

test("a percent-encoded id from the URL is decoded, and a plain one is left alone", () => {
  assert.equal(routeId("TST-01"), "TST-01");
  assert.equal(routeId("TST%2001"), "TST 01");
  assert.equal(routeId("100%"), "100%");
});
