// Self-check for the date and number rules every page relies on. Run from the repo root: node web/lib/check.mjs
import assert from "node:assert/strict";
import { addMonths, bucketsBetween, fiscalYear, precedingWindow, presets, weekStart } from "./dates.ts";
import { fmtINR, fmtRange, formatDelta, formatValue } from "./format.ts";

// Indian fiscal years end in March and are named by that year.
assert.equal(fiscalYear("2026-09-23"), 2027);
assert.equal(fiscalYear("2026-03-31"), 2026);

// Presets relative to the as-of date, each with the window its delta compares against.
const [fytd, fy26, fy25, last90] = presets("2026-09-23");
assert.deepEqual([fytd.label, fytd.range, fytd.prior], ["FY27 to date", { from: "2026-04-01", to: "2026-09-23" }, { from: "2025-04-01", to: "2025-09-23" }]);
assert.deepEqual([fy26.label, fy26.range.from, fy26.range.to, fy26.prior.from], ["FY26", "2025-04-01", "2026-03-31", "2024-04-01"]);
assert.equal(fy25.label, "FY25");
assert.deepEqual(last90.range, { from: "2026-06-26", to: "2026-09-23" });
assert.deepEqual(last90.prior, { from: "2026-03-28", to: "2026-06-25" });
assert.deepEqual(precedingWindow({ from: "2026-09-01", to: "2026-09-10" }), { from: "2026-08-22", to: "2026-08-31" });
assert.equal(addMonths("2024-03-31", -1), "2024-02-29");

// Weeks start on Monday, like Postgres date_trunc('week'), which MetricFlow uses.
assert.equal(weekStart("2026-09-23"), "2026-09-21");
assert.equal(weekStart("2026-09-21"), "2026-09-21");
assert.deepEqual(bucketsBetween("2026-06-26", "2026-09-23", "month"), ["2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01"]);

// Money in lakh and crore; deltas signed with a real minus sign; no dashes in ranges.
assert.equal(fmtINR(2_312_000_000), "₹231.2 cr");
assert.equal(fmtINR(4_200_000), "₹42.0 lakh");
assert.equal(formatDelta("inr", 108, 100)?.text, "+8.0%");
assert.equal(formatDelta("days", 35.8, 39.9)?.text, "−4.1 days");
assert.equal(formatDelta("inr", 5, 0), null);
assert.equal(formatValue("pct", 0.032), "3.2%");
assert.equal(fmtRange({ from: "2026-04-01", to: "2026-09-23" }), "1 Apr to 23 Sep 2026");

console.log("web/lib checks passed");
