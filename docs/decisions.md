# Decisions log

Places where the build plan was silent, ambiguous, or internally inconsistent, and what was decided.
Each entry names the plan text it touches. Entries marked **extends plan** add to the plan and should get the owner's sign-off.
The owner approved the recommended resolutions on 2026-09-24. They were reached through an independent spec-gap review and adversarial critique.

Anomaly specifics (dates, multipliers, which entities) are deliberately **not** recorded here. They live only in `generator/ground_truth.yaml`, the answer key.

## Raw schema

**D1. `installations.installer_id` (nullable FK → installers). Extends plan.**
The plan relies on the join path `warranty_claims → serial_units → installations → installers`, and `installer_claim_rate` needs units installed per installer as its denominator. The plan's `installations` table has no installer column, so neither was possible.
`warranty_claims.installer_id` is kept as the technician-recorded copy, and a dbt test asserts it matches `installations.installer_id` whenever both are set.

**D2. Durgapur runs one rotomoulded tank line (Line 2) alongside its pipe/CPVC extrusion (Line 1). Extends plan.**
The plan's plant list says "Durgapur (pipes/CPVC)", but elsewhere the plan needs serialised tank production at Durgapur. The plant list is described as narrative flavour, so it gives way.
`plants.plant_type` for Durgapur is `pipes_cpvc_and_tanks`.

**D3. Unit serialisation (QR serials) applies to tanks only. Extends plan.**
At the stated scale, serialising pipes and fittings would need about 40M rows against a 1.5–2.5M budget. This extends the plan's own rule that "serial is null for bulk/weight-sold pipe" to fittings and sanitaryware.
Consequences:
- `serial_units`, serial rows in `shipments`, `installations` and `warranty_claims` are all tank rows.
- Warranty claims are tank claims. `fitting_failure` means a tank's inlet/outlet fitting.
- Simulated physical volume is sized to the row budget. The ₹480 cr revenue figure is calibration only.

**D4. `raw.geo_pincodes` (pincode, district, state, region) reference table. Extends plan.**
The plan never maps a pincode to a district or region, yet it needs a district baseline (installer decoy), `dim_geo`, region-grain metrics and a region RLS claim. The generator writes this table and draws every pincode from it.
Region is the geo region of the pincode. Each sales rep's region must match their distributors' region (dbt test).
District and state names are real public geography. Pincodes are synthetic values inside real postal prefixes.

**D5. `raw.opening_channel_stock` (distributor_id, sku, qty, as_of_date). Extends plan.**
Days-of-stock is "cumulative primary − cumulative secondary", and there is no opening balance, so every distributor would start empty. The plan's example test, "secondary sales can't exceed opening stock + primary receipts", needs an opening stock.
"Primary shipped" is defined as `primary_invoice_lines.qty` on `primary_invoices.invoice_date`. `shipments` is the serial-level custody log. For non-serialised goods it holds one bulk row per dispatch, with a null serial.

**D6. Sanitaryware is traded, not manufactured.**
None of the three plants makes it. `primary_invoice_lines.batch_id` is nullable for sanitaryware lines only (dbt test), and sanitaryware is excluded from batch and claim cohorts.

**D7. Legacy installed base.**
Tanks made in the 12 months before month 1 exist in `production_batches` and `serial_units`, so warranty claims against them during the window have a valid serial. Their shipment history predates the warehouse and isn't included. This reads as the warehouse going live at month 1 with a migrated serial master.
Without it, claim counts would ramp up from zero for the first year and fake a trend.

**D8. Latent install date.**
The simulator gives every tank a true install date and applies all failure hazards against it. It writes `install_date` only for the ~70% that register.
- An `installations` row exists for every tank shipped in the window. Unregistered tanks carry null `install_date`, `pincode`, `registered_via` and `installer_id`.
- The cohort mart's in-service clock is defined in the dbt step.
- `claim_date >= install_date` is tested only where `install_date` is set.

## Channel mechanics and metric definitions

**D9. Scheme mechanics.**
- The `min_slab_units` slab is checked per invoice, on the lines in `applies_to_category`.
- The discount is taken on-invoice: `unit_price_inr = price × (1 − discount_pct)`.
- An invoice carries at most one scheme.

**D10. Channel metrics are computed in units, not value.**
Secondary value uses the current list price, while primary value uses historical, discounted prices. A value-based primary/secondary gap would therefore move with every price revision and scheme, regardless of channel behaviour. The health-score gap and all channel-stock logic use qty.

**D11. Registration calibration.**
About 30% of tanks never register (the plan's 30–40%). The plan's 90-day `warranty_registration_rate` therefore lands around 60–65% (the plan's 60–70%).

**D12. Secondary reporting.**
- A secondary row becomes visible once `reported_date ≤ as-of`, so the most recent weeks are always partly reported.
- Detectors and the health score use sale dates older than a completeness horizon (the p95 reporting lag). The dashboard marks the newest days as provisional.
- "Missing" reports are mostly late: skipped weeks get back-filled as catch-up records. Truly lost reports are capped at a tiny share, so implied channel stock doesn't drift upward forever.

**D13. Metric definitions settled now (full definitions come with the semantic layer).**
- `dso` is computed per invoice and weighted by amount, as of a date. Open invoices are aged to that date, so a distributor who stops paying shows up immediately instead of only once late payments land.
- `channel_days_of_stock` is computed per distributor, SKU and day. It is null when there were no secondary sales in the trailing 30 days, and those days are excluded from the stock-out and overstock rates.
- *Amended:* the stuffing baseline is the plan's literal trailing-90-day window, `[start − 90, start − 1]`, used identically by generator and detector.
  - An earlier version excluded prior scheme-window days. That leaves a repeat stuffer with only 4–6 baseline days, which is too noisy.
  - The literal window includes the previous window plus its drain, and the designed post-window drain makes the two cancel (net 0.97–1.00×).
- `scheme_concentration_ratio` compares against a leave-one-out baseline share: the median over the distributor's other quarters, floored at 15/91.

## Time and operations

**D14. Ground truth is pinned to absolute dates from a fixed anchor.**
`generator/config.yaml` pins `anchor_date`, and month labels (month 1 to month 36) are relative to it. The simulation is a pure function of (config, ground truth, as-of date):
- Re-running it for a later as-of date reproduces every earlier day exactly and adds the new days.
- The daily job therefore reseeds to yesterday and rebuilds, so a missed or doubled run can't drift.
- Evals always use the pinned as-of date.
- The anchor moves forward in 12-month steps (every September), which keeps each anomaly's seasonal placement.

**D15. `mart_installer_claim_cohorts`. Extends plan.**
The agent can only read marts, and none of the plan's §6 marts sits at installer grain, so `installer_claim_rate` would have nothing to query. This additional mart holds one row per installer × district × install month × months since install, with units installed and claims.

**D16. `installations._loaded_at`.**
This is the date the row became what it is: the registration date if the unit is registered, otherwise the ship date. Point-in-time replays use it to tell registered units from not-yet-registered ones. Other tables' visibility is already one of their own dates (`reported_date`, `claim_date`, `payment_date`, `invoice_date`), so they get no extra column.

**D17. `generator/ground_truth.yaml` is committed.**
Reproducing the data from a clean clone requires it. "Private to the generator" is enforced by policy:
- It is never loaded into Postgres, so the agent's marts-only role can't reach it.
- It is never used to compute eval golden answers; those come from the marts via SQL.
- The README doesn't point to it before the case-study reveal.

**D18. Detectors are pre-registered in `detectors/detectors.yaml`.**
It was committed before the first data generation. Every detector is a generic scan with a multiple-comparison correction, and none names an entity. Changing a rule after seeing data is a logged deviation here, and case-study numbers are then reported under both the old and the new rule.

**D19. Claim rates are deliberately higher than a real manufacturer's.**
Year-one tank claims run at about 0.5% a month (base crack about 0.2%). This buys the statistical power the anomaly checks need inside the row budget. The trade-off is disclosed in the case study rather than hidden.

**D20. Semantic layer: real MetricFlow, run as a compile-only engine inside the API (build prompt step 4, an "ask me" item).**
The 12 glossary metrics are defined once, in dbt 1.12's inline semantic spec under `warehouse/semantic_models/`. `dbt parse` validates them and writes `semantic_manifest.json`.

At query time the API loads that manifest into MetricFlow's Python engine (`metricflow` 0.213.0, already a dbt-core dependency) with a compile-only Postgres client. MetricFlow writes the SQL, including joins, non-additive stock snapshots and ratio metrics, and the API runs it on the read-only, region-filtered role.

A probe compiled every glossary metric, with group-bys and filters, without a database, a dbt adapter or the `mf` CLI. So the hand-written fallback compiler wasn't needed.

Trade-offs:
- The API image carries MetricFlow.
- Metric semantics are MetricFlow's. For example, stock metrics read the period's last day, and grouping by an entity uses its name (`distributor`), not its key column.

**D21. Extra marts beyond PLAN §6. Extends plan.**
- `fct_invoice_collections` (invoice grain) gives `dso` and `collections_efficiency` a home at the grain D13 needs.
- `mart_scheme_quarterly` gives `scheme_concentration_ratio` and the stuffing detector a governed table.
- `dim_date` (in marts) is the MetricFlow time spine, so compiled SQL never needs a schema the agent can't read.
- `mart_anomaly_flags` holds the pre-registered detectors' output for `get_anomalies`.

**D22. The cohort clock starts at shipment.**
`mart_batch_claim_cohorts` counts months since shipment, not since install, because about 30% of units never record an install date (D8). The PLAN §9 heatmap axis is labelled "months in service (from shipment)". This matches the pre-registered lot scan's `days_since_ship` exposure clock.

**D23. Thresholds.**
- Stock-out means under 7 days of stock and overstock means over 60 (target cover is 30).
- Days with no sell-out in the trailing 30 days have no days-of-stock value and count toward neither rate.
- The trailing average uses the days available at the window start, with a minimum of 14.
