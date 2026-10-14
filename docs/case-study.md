# Case study: four planted anomalies, found blind

> Spoilers. This page reveals what was planted in the data and whether the pre-registered detectors found it.

## The honesty protocol
The protocol is designed so that no result below could have been tuned to look good.

1. **Fixed before any data existed.** Commit `15b4b88` holds the answer key ([`generator/ground_truth.yaml`](../generator/ground_truth.yaml)) and every detector rule ([`detectors/detectors.yaml`](../detectors/detectors.yaml)): thresholds, peer sets, clocks and a Bonferroni correction. The data was generated afterwards, and the seed is never re-rolled to improve a result.
2. **Anomalies come from rules, not rows.** Each one is a mechanism in the simulator: a hazard multiplier, a behavioural modifier or an ordering policy. A black-box acceptance suite ([`generator/acceptance.py`](../generator/acceptance.py)) verifies each one against a same-seed run with that anomaly switched off. The suite never reads the generator's code. It also confirms the data carries no tells, such as tell-tale words or values unique to the planted entities.
3. **The detectors never read the answer key.** Their results are below as they fell, false positives and misses included.
4. **The eval's golden answers come from hand-written SQL against the marts** (`evals/questions.yaml`), not from the answer key or the agent. That SQL independently rediscovered two of the anomalies.

The data covers 2023-10-01 to 2026-09-23, 1.84M raw rows. The acceptance suite's final run gave **28 pass, 7 fail and 3 deferred**; every result is in `generator/acceptance_report.json`.

## 1. A bad resin lot (the headline claim)
**What was planted:** one resin lot on Durgapur Line 2, used from 2025-03-10 to 2025-04-20. Its tanks got a 4× hazard of base cracks in their first 12 months of service.

**Is it in the data?**
- The lot has 3,376 units.
- At 12 months since shipment they show **3.90×** the base-crack rate of same-line peer lots. With the anomaly off it's 1.00×.
- Other failure modes run at 0.93×, so there's no spillover.
- Durgapur's monthly base-crack count rises about 40% during the tail.

**Did the detector find it?** The pre-registered lot scan tests every (resin lot, failure mode) pair against its plant-line peers at equal days since shipment. It covers 680 entities over 142 weekly snapshots, at α = 5.2e-7 each.
- **It flagged `RL-DGP-L2-250310` for base cracks on 2025-05-18**, at 4.8× (p = 4.5e-7). That was about 9 weeks after the lot's first units left the plant.
- The naive view is the plant's monthly base-crack count on a standardised CUSUM, also pre-registered. It didn't alarm until **June 2025**. So the cohort view saw it **6.1 weeks earlier** than the raw monthly count would have shown it.

**Where the detector fell short:**
- It also flagged three Howrah lots in early 2024: a discolouration, a leak and a fitting-failure lot.
- These are false positives with a single cause. Those lots were first used in October–November 2023, so their "peers" were legacy lots with almost no shipment history, which left each peer rate resting on one or two claims.
- All three fell back to ordinary rates, 0.96–1.67× today.
- The pre-registered peer rule has no minimum peer exposure. That's the rule to change next, as a logged deviation (D18), not silently.

The eval's golden SQL for "why did base-crack claims rise at Durgapur in 2025?" independently singles out the same lot: 291 base-crack claims on 3,376 units, or 86.2 per 1,000 to date. (The acceptance check measures 77.6 per 1,000 at 12 months since shipment, against 19.9 for its peers.)

## 2. Silent distributor churn
**What was planted:** a Tier-2 distributor in Siliguri, `D0084`.
- Its sell-out declines about 45% over October 2025 to February 2026.
- Its sell-in stays flat for the first three months: the company keeps loading the channel.
- Then its payments slip.

**Is it in the data?**
- Sell-out is 0.54× its counterfactual by February.
- Sell-in is exactly 1.000× in October, November and December. It then drops to 0.26× in January and February, which is when the company's own top line would finally show it.
- Invoices due in January and February were paid a median 32 days late, against 3 days in 2025.

**Did the detector find it?** The pre-registered health score (five region-peer percentile components) marks a "flag week" when the score is under 30 and the sell-out-trend component is under 15. It flags the distributor at risk after three flag weeks in a row.
- `D0084` had its first flag week on **2025-11-30**, while sell-in was still flat.
- **It was flagged at risk only on 2026-02-15**, after the January sell-in drop was already visible. The target had been by 2026-01-31, so this is **a late detection**.
- The cause is the gate. The distributor's region has only about 28 peers, so the percentile components move in steps of about 3.6 points, and the sell-out-trend component hovered around the 15 cut-off instead of staying under it for three consecutive weeks.
- The rule's base rate is about 8 at-risk distributors a week (2.3%).
- **Detector v2 (D46, D47)** replaces the percentile gate with an absolute one: sell-out under 0.8× the same 8 weeks a year earlier while sell-in runs above 1.1× sell-out, with the score still under 30, for three weeks running.
  - It flags `D0084` on **2026-01-11**, before the January target, and flags fewer other distributors: 137 against v1's 172.
  - On a holdout seed nobody had inspected, it flags that seed's churn account on 2026-01-25 (v1: 2026-03-15). See *Detector v2* below.

## 3. Quarter-end stuffing (systemic)
**What was planted:** from the March 2024 fiscal year-end onwards, 15–20% of distributors each quarter order about 2.5× their own trailing rate in the scheme window, then carry the excess stock.

**Is it in the data?**
- Stuffers order 2.46–2.54× their trailing rate.
- On the acceptance suite's identification rule, 15.2–20.1% of active distributors stuff per quarter.
- The overhang holds for 60+ days after quarter-end.
- The acceptance suite caught a real generator bug here: the excess never drained, and repeat stuffers ratcheted to about 100 days of cover. It was fixed (D27).
- Non-June quarters now clear to within +1 to +2.8 days of the counterfactual by the next window.
- June quarters still end about 11–12 days over. Stock sized on the summer peak meets the monsoon trough, and distributors can't return stock. The acceptance check for this (S5) therefore still fails, and that's reported, not tuned away.

**Did the detector find it?** The pre-registered rule flags any distributor × window × category ordering at ≥ 2× its trailing-90-day rate. Against the planted stuffers, **recall is 96% but precision only 36%**: 1,228 of 1,926 flags are false positives. Smaller distributors order in lumpy packs, so 2× in a 15-day window happens often by chance. The dashboard pairs the flag with the concentration ratio and the post-quarter stock follow-through, which separate the two. The pre-registered rule on its own is too loose.

**Detector v2 (D46, D47)** works in two stages.
- **Provisional** (at the window's end): v1 and at least one scheme invoice in the window. That separates ordering that rides the scheme from a lumpy order that happens to land in the window. Precision rises to 50% with recall essentially unchanged.
- **Confirmed** (once 60 days after quarter-end are in): the provisional flag and either orders below the baseline rate for the next 30 days or a stock excess of at least 3 days. That's the drain loading leaves behind and demand doesn't. Precision rises to 64–65% at 87% recall.

Inside the window, the remaining false positives look like stuffers in rate, order size and scheme share. Only the post-quarter evidence separates them, which is why the second stage exists.

## 4. The decoy: an installer, not a product
**What was planted:** one installer in Kamrup Metropolitan, Assam, active from July 2024. Tanks they install fail at about 3× their district peers.
- The units come from two plants and dozens of resin lots, so a batch-level view shows nothing.
- This is the test of whether the analysis attributes the cause correctly instead of reaching for "bad batch".

**Is it in the data?**
- Against a leave-one-out district baseline at equal time since install, the installer's claim rate is **2.94× at 180 days and 2.58× at 365 days**.
- With the anomaly switched off, the same comparison gives 1.18× and 1.04×. The 365-day figure is just under the 2.6× acceptance floor; it's reported as measured, because the seed isn't re-rolled.
- Their units span 2 plants (73% Guwahati, 27% Howrah) and 73 resin lots, and no lot has more than 1.8% of its units from this installer. No batch looks unusual.

**Did the detector find it?** The pre-registered installer scan (leave-one-out, Bonferroni over 592 installers × 142 snapshots) **flagged `INS0227` alone, on 2025-02-09**, at 5.0× (p = 6.1e-8). No other installer was flagged. The eval's golden SQL independently finds the same installer as the outlier in Kamrup Metropolitan: 140 claims on 1,088 attributed installs, 2.40× the rest of the district.

## Detector v2: developed on one seed, tested on another
The protocol (Phase 2 spec, D46):
1. Develop v2 on the seed of record, 20260924, whose data had been inspected.
2. Freeze the rules and the holdout seed, 20261002, in one commit, before the holdout existed.
3. Generate the holdout in its own database.
4. Report v1 and v2 on both seeds, whichever way they fall.

Ground truth is the acceptance suite's rule, never a detector's: a stuffer cell's window units are at least 1.8× the stuffing-off run. The churn account is the generator's own pick: `D0084` on the seed of record, `D0089` on the holdout.

| | Seed of record (development) | Holdout seed (never inspected) |
|---|---|---|
| Stuffing v1: precision / recall | 34.0% / 95.8% | 34.6% / 94.9% |
| Stuffing v2 provisional | 50.5% / 95.4% | 50.5% / 94.8% |
| Stuffing v2 confirmed | 65.0% / 87.2% | 64.3% / 86.6% |
| Churn account flagged, v1 | 2026-02-15 (late) | 2026-03-15 (late) |
| Churn account flagged, v2 | **2026-01-11** | **2026-01-25** |
| Other distributors ever at risk, v1 → v2 | 172 → 137 | 171 → 130 |
| Stuffers at risk during their overhang, v1 → v2 | 13.2% → 11.5% | 11.7% → **12.6%** |

What generalised, and what didn't:
- **Stuffing.** The gains carry over almost exactly, which is the evidence that they aren't fitted to the development seed.
- **Churn.** The goal is met on both seeds, but only by 6 days on the holdout. The 0.8 sell-out gate was chosen on a seed where 0.75 missed the account entirely, so it sits close to the signal.
- **False positives.** v2 flags fewer distributors overall on both seeds. On the holdout it's slightly worse than v1 on the stuffer-overhang measure. Both versions fail the acceptance target of under 5% (C7).
- **Product.** v2 has been in production since 2026-10-02 (D48). Five of the eval's golden answers read detector flags, so they moved with the switch.

## Scorecard

| Anomaly | In the data (acceptance) | Pre-registered detector | Verdict |
|---|---|---|---|
| Resin lot | 3.90× vs peers (cf 1.00×) | flagged 2025-05-18, 6.1 weeks before the raw count; 3 early false positives | found early; peer rule needs a minimum |
| Silent churn | sell-out 0.54×, sell-in flat, 32 days late | v1 at risk 2026-02-15 (first flag week 2025-11-30); v2 2026-01-11, holdout 2026-01-25 | v1 late; v2 in time on both seeds, narrowly on the holdout |
| Quarter-end stuffing | 15–20% at ~2.5×; June overhang lingers | v1 recall 96%, precision 36%; v2 50% / 95% provisional, 64–65% / 87% confirmed, on both seeds | v1 too noisy alone; v2 confirmed holds up on a holdout seed |
| Installer decoy | 2.94×/2.58× vs district (1.18×/1.04× with it off) | uniquely flagged 2025-02-09 | found and attributed correctly |

## 5. The Ask agent: what the semantic layer is worth
The eval measures that by running the same model in two modes:
- **governed**, the agent as built;
- **raw**, a plain text-to-SQL agent with only `run_readonly_sql` and the mart schema. It has the same prompt rules, refusal rules, SQL validator, refusal router and row-level security.

The golden answers are hand-written SQL, independent of any model.

**No scored run yet.** The Claude runs come next: Sonnet 5.5 and Haiku 5.5, each governed and raw, on the same 102 questions (golden set v2, D39). The eval harness, the golden set and the scoring are unchanged.

## What I'd defend in an interview
- **Two anomalies came through cleanly: the resin lot and the decoy.** For the lot, the cohort view beat the raw monthly count by six weeks. For the decoy, the join path through installations points at the installer, while the batch view shows nothing.
- **The misses are more useful than a clean sweep would have been.** Each has a specific, fixable cause:
  - the lot scan's missing peer-exposure floor;
  - the health score's coarse regional percentiles;
  - the stuffing rule's lack of a concentration condition.

  Because the rules were pre-registered, none of this could be quietly tuned away. Every fix becomes a logged deviation, reported under both rules.
- **The acceptance suite found a real generator bug**, the stuffing drain. It also measured, rather than assumed, how closely the simulator hits its own targets.
