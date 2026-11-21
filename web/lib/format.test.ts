import assert from "node:assert/strict";
import { test } from "node:test";
import { formatDate, formatDateRange, formatIstDateTime, formatRupees, leverLabel } from "./format.ts";

test("rupees use Indian digit grouping", () => {
  assert.equal(formatRupees(138600), "₹1,38,600");
  assert.equal(formatRupees(66400), "₹66,400");
  assert.equal(formatRupees(12345678), "₹1,23,45,678");
  assert.equal(formatRupees(999), "₹999");
  assert.equal(formatRupees(0), "₹0");
});

test("rupees are shown whole, and a missing figure is never shown as a number", () => {
  assert.equal(formatRupees(1999.6), "₹2,000");
  assert.equal(formatRupees(Number.NaN), "not available");
  assert.equal(formatRupees(undefined as unknown as number), "not available");
});

test("dates read like 31 Oct 2026", () => {
  assert.equal(formatDate("2026-10-31"), "31 Oct 2026");
  assert.equal(formatDate("2026-09-01"), "1 Sep 2026");
  assert.equal(formatDateRange("2026-10-25", "2026-10-31"), "25 Oct 2026 to 31 Oct 2026");
});

test("something that is not a calendar date is shown as it came", () => {
  assert.equal(formatDate("2026-02-30"), "2026-02-30");
  assert.equal(formatDate("soon"), "soon");
});

test("the engine run time is shown in IST", () => {
  assert.equal(formatIstDateTime("2026-11-01T01:30:00Z"), "1 Nov 2026, 7:00 am IST");
  // 18:45 UTC is 00:15 the next day in India.
  assert.equal(formatIstDateTime("2026-10-31T18:45:00Z"), "1 Nov 2026, 12:15 am IST");
  assert.equal(formatIstDateTime("2026-11-21T06:40:12.123456+00:00"), "21 Nov 2026, 12:10 pm IST");
  assert.equal(formatIstDateTime("2026-11-21T12:10:00+05:30"), "21 Nov 2026, 12:10 pm IST");
});

test("a run time with no zone is read as UTC, as the contract states", () => {
  assert.equal(formatIstDateTime("2026-11-01T01:30:00"), "1 Nov 2026, 7:00 am IST");
});

test("an unreadable run time is shown as it came", () => {
  assert.equal(formatIstDateTime("yesterday"), "yesterday");
});

test("levers have their plain names", () => {
  assert.equal(leverLabel("more_bills"), "More bills");
  assert.equal(leverLabel("bigger_baskets"), "Bigger baskets");
  assert.equal(leverLabel("more_repeat"), "More repeat");
});
