# Detectors

`detectors.yaml` holds the pre-registered rules. `run.py` implements them; run it from the repo root with
`.venv\Scripts\python.exe -m detectors.run`. It reads as-of from `raw.generation_run` and writes two things:

- `marts.mart_anomaly_flags`, dropped and recreated in one transaction, with region RLS and a grant to `channelpulse_agent`;
- `results/latest.json`, which lists every flag, CUSUM alarm and lead time, false positives included.

The statistics live in `stats.py` as pure functions, and `tests/` tests them.

## Version 2 (D46)

`detectors.yaml` also pre-registers v2 of the stuffing and health rules, next to v1.
- **Stuffing v2:** a provisional flag at the window's end, then a confirmed flag once 60 days after quarter-end are in.
- **Health v2:** an absolute sell-out gate in place of v1's regional percentile.

v2 is in production since D48. The marts' unversioned columns carry it (`is_stuffing_flag` provisional, `is_stuffing_confirmed`, `is_at_risk`), and v1 stays on record as `is_stuffing_flag_v1` and `is_at_risk_v1`.
- In `mart_anomaly_flags`, a stuffing flag has a provisional row dated at the window's end. When it's confirmed, a second row is dated at QE+60, when its evidence exists, so as-of reads stay point-in-time.
- Health rows come from the v2 runs.

`python -m detectors.evaluate` scores both versions on whichever database the `POSTGRES_*` variables point at:
- stuffing precision and recall against the acceptance suite's stuffer rule, which needs the stuffing-off schema `raw_cf_quarter_end_stuffing`;
- the churn account's first at-risk week;
- the health flag's false positives.

It writes `results/evaluation_<seed>.json`. The protocol: develop on the seed of record, freeze the rules in a commit, generate the holdout seed in its own database, and report all four results.

## Interpretations

Where the spec is open, the code takes the most conservative reading:

1. **Point-in-time eligibility.** An entity is tested at snapshot S only once it meets its size rule by S: a lot needs ≥ 200 units shipped by S, and an installer needs ≥ 50 attributed installs with `_loaded_at ≤ S`. The Bonferroni entity count is taken at as-of, which is the largest count, and all weekly snapshots count.
2. **Failure modes.** All five modes in the `raw.warranty_claims` CHECK count as entities, including any with no claims.
3. **Lot first use.** A lot's first use is the earliest `mfg_date` of any batch that used it (`marts.dim_batch`, legacy batches included). Its peers are the other lots on the same plant and line whose first use falls in `[first_use − 12 calendar months, first_use)`. Peers have no minimum size.
4. **Exposure.** Exposure is unit-days counted through the end of the snapshot day. A unit that starts on day d has ages 0..S−d at S, so it contributes S−d+1 unit-days. Buckets are ages `[30j, 30j+30)`. A claim falls in the bucket of its age on its claim date.
5. **Unusable buckets.** A bucket where the reference (pooled peers, or the leave-one-out district) has no exposure has no rate, so it is dropped from both expected and observed. An entity whose expected total is 0 is not tested at that snapshot, since p would be 0 whenever it has any claim at all.
6. **Flag rule.** An entity flags when observed ≥ 5 and p ≤ α, where p = P(X ≥ observed | expected).
7. **Legacy units (D7).** They have no ship date, so they have no days-since-ship clock. They are outside the lot scan both as exposure and as claims. The CUSUM's raw monthly counts do include their claims. As a result, lots first used near month 1 have peers that are mostly legacy lots with little shipped exposure. See the caveat below.
8. **Installer baseline.** The baseline stratum is the unit's install district (from its pincode) × product category. Every serialised unit is a tank (D3), so category never splits anything. The baseline uses only other installers' attributed installs, not unattributed registrations. A claim counts only if its unit is visible at S. Attribution comes from `installations.installer_id`, not from the technician's copy on the claim.
9. **Installer details.** `plants_spanned` and `resin_lots_spanned` are counted over the installer's installs visible at S.
10. **Stuffing rows.** Each flagged window is its own flag event, so `first_flag_date = snapshot_date = min(window end, as_of)`. `concentration_ratio` and the follow-through stock are left out of `details` because they use later quarters or post-window days, which are not point-in-time.
11. **Health rows.** Consecutive at-risk weeks form a run. `first_flag_date` is the `snapshot_date` (the week end) of the run's first at-risk week.
12. **CUSUM.** S is 0 before month 17. A month whose μ_t is 0 leaves S unchanged. A month counts as complete when its last day is ≤ as_of. Only the first alarm per series is reported. Series cover every plant with claims × all five modes. Lead time is computed per flagged (lot, failure mode) from that entity's first flag date.
13. **Completeness horizon.** It stays at the pre-registered 17 days, although the generator reports a p95 lag of 19. Only the health mart's secondary-sales inputs use it; the scans read no secondary facts.

## Caveat seen in the results

Three lot-scan flags fall in Mar–May 2024, on lots first used in Oct–Nov 2023. Their expected counts are very small, 0.003–0.5 claims. Their peers are mostly legacy lots, whose units never shipped in the data. So the peer rate for each rests on 1–2 claims over 0.16–0.31M unit-days, with zero claims in most age buckets. By comparison, the 2025 flag's peers had 300 claims over 6.1M unit-days. In later snapshots, these three lots return to rate ratios of 0.96–1.67. These flags are reported as they fell. They are not suppressed, because any fix would change the pre-registered peer rule. A fix would need a logged deviation (D18).
