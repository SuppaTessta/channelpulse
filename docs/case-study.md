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
- A v2 would score trends against peers nationally within tier, or use a rolling 3-of-4-week rule. That change would be logged and reported under both rules.

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

## 4. The decoy: an installer, not a product
**What was planted:** one installer in Kamrup Metropolitan, Assam, active from July 2024. Tanks they install fail at about 3× their district peers.
- The units come from two plants and dozens of resin lots, so a batch-level view shows nothing.
- This is the test of whether the analysis attributes the cause correctly instead of reaching for "bad batch".

**Is it in the data?**
- Against a leave-one-out district baseline at equal time since install, the installer's claim rate is **2.94× at 180 days and 2.58× at 365 days**.
- With the anomaly switched off, the same comparison gives 1.18× and 1.04×. The 365-day figure is just under the 2.6× acceptance floor; it's reported as measured, because the seed isn't re-rolled.
- Their units span 2 plants (73% Guwahati, 27% Howrah) and 73 resin lots, and no lot has more than 1.8% of its units from this installer. No batch looks unusual.

**Did the detector find it?** The pre-registered installer scan (leave-one-out, Bonferroni over 592 installers × 142 snapshots) **flagged `INS0227` alone, on 2025-02-09**, at 5.0× (p = 6.1e-8). No other installer was flagged. The eval's golden SQL independently finds the same installer as the outlier in Kamrup Metropolitan: 140 claims on 1,088 attributed installs, 2.40× the rest of the district.

## Scorecard

| Anomaly | In the data (acceptance) | Pre-registered detector | Verdict |
|---|---|---|---|
| Resin lot | 3.90× vs peers (cf 1.00×) | flagged 2025-05-18, 6.1 weeks before the raw count; 3 early false positives | found early; peer rule needs a minimum |
| Silent churn | sell-out 0.54×, sell-in flat, 32 days late | at risk 2026-02-15 (first flag week 2025-11-30) | found, but late |
| Quarter-end stuffing | 15–20% at ~2.5×; June overhang lingers | recall 96%, precision 36% | found, too noisy alone |
| Installer decoy | 2.94×/2.58× vs district (1.18×/1.04× with it off) | uniquely flagged 2025-02-09 | found and attributed correctly |

## 5. The Ask agent, measured: what the semantic layer is worth
The Ask agent was evaluated on two free providers:
- `gemini-3.5-flash-lite`, on the Gemini API free tier;
- `qwen3.8-27b-64k`: Qwen3.8 27B at `Q4_K_M`, served by Ollama on a Kaggle 2x T4 session.

Both answered the same 102 questions (golden set v2, D39) in two modes:
- **governed**, the agent as built;
- **raw**, a plain text-to-SQL agent with only `run_readonly_sql` and the mart schema. It has the same prompt rules, refusal rules, SQL validator, refusal router and row-level security.

The golden answers are hand-written SQL, independent of any model. The agent was **not** evaluated on Claude: the Anthropic adapter exists and is unit-tested, but no Claude run was made. Every figure below comes from the committed run files, and the README tables are generated from them (`make scorecard`).

**Each result is one run at temperature 0.** That doesn't make a model deterministic: in Part B, Gemini flipped SL06 between two runs at temperature 0. Small differences should be read with that in mind.

| Model | Raw | Governed | Lift | Wrong to right | Right to wrong | McNemar exact p |
|---|---|---|---|---|---|---|
| `gemini-3.5-flash-lite` | 72.1% | 88.2% | +16.2 points | 15 | 4 | 0.019 |
| `qwen3.8-27b-64k` | 69.1% | 97.1% | +27.9 points | 20 | 1 | 0.00002 |

Accuracy is execution accuracy on the 68 answerable questions. The last three columns pair the two modes question by question on those 68. The McNemar exact test asks whether the discordant pairs could plausibly split this way by chance. For Qwen they couldn't. For Gemini the gain is real but smaller, at p = 0.019, from a single run per mode.

**"Confidently wrong" was three different failures.** Split apart:

| Run | Wrong answers (of 68) | Ambiguous answered without asking (of 16) | Traps answered (of 18) |
|---|---|---|---|
| Gemini governed | 8 | 12 | 0 |
| Gemini raw | 19 | 14 | 1 |
| Qwen governed | 2 | 8 | 2 |
| Qwen raw | 20 | 6 | 0 |

Only the first column is wrong figures. The semantic layer cuts wrong figures by more than half on Gemini, and from 20 to 2 on Qwen.

The second column is the weakest category for every run: the models usually pick a reasonable reading and answer it rather than ask. Gemini asked on 4 of 16 governed and 2 of 16 raw. Qwen asked on 8 of 16 governed and **10 of 16 raw**: with governed metrics to hand it was more willing to just answer. None of the four runs asked needlessly on an unambiguous question, apart from one in Qwen raw.

**Trap refusals, two ways.** The refusal router refuses 9 of the 18 traps before any model call, in both modes, because their wording settles it: writes, raw or system tables, prompt injection, "don't show the SQL". The model handles the other 9:

| Run | Router | Model, of the other 9 |
|---|---|---|
| Gemini governed | 9 | 9 |
| Gemini raw | 9 | 8 (answered TR01) |
| Qwen governed | 9 | 7 (answered TR01, TR12) |
| Qwen raw | 9 | 9 |

**This is a trade-off, not noise to drop.** Qwen refused every model-handled trap in raw mode and missed two in governed mode. Both misses are forecasts:
- **TR01:** next quarter's sales.
- **TR12:** which distributors will default.

In both, Qwen said plainly that it can't forecast, then added governed context it could compute. For TR01 that was last year's actuals for the same quarter. For TR12 it was the detector's current at-risk list. It didn't set `refused`, so the response carries SQL and data, and the strict scoring counts each as a trap answered. The rubric stays as written: it was fixed before the runs, and changing it after seeing results would be the wrong lesson. The behaviour is a partial refusal, arguably helpful, but it's not a refusal. With governed tools that make context cheap to fetch, the model fetched it. Gemini raw's TR01 miss is the same shape: it said the future isn't in the data, but answered rather than refused.

**Why raw mode fails: definition drift, on the same questions for both models.** 18 questions are wrong in both raw runs. Apart from four multi-hop questions, they are business definitions the model re-derived and got subtly wrong:
- DSO as a plain average, where the governed metric is amount-weighted (D13);
- collections efficiency ignoring "within payment terms";
- days of stock, overstock and stock-out rates under its own rules;
- installer claim rate, registration rate and secondary value with the wrong denominator or valuation.

Two different models fail on the same definitions. That's the strongest evidence here that the problem is the missing definition, not the model. In governed mode those definitions aren't the model's to invent: `query_metric` compiles them, and the free tier checks each governed call against independent SQL on every PR.

**Where governed mode loses, question by question:**
- **Qwen, 1 question, SL10:** it gave the three monthly claim-cost figures instead of the quarter's total.
- **Gemini, 4 questions:**
  - **MH04** is partly by design. Raw mode drops a "why" question's required evidence tools (D32), since raw has only SQL. The governed answer named the right cause but skipped the metric query its rubric requires.
  - **SL11** asked what is owed "as of 23 September". Gemini filtered `open_receivables` to invoices raised that day, because the metric's time dimension is the invoice date. That's a real usability gap in how an "as of" question maps onto a governed metric.
  - **SL16** counted result rows itself, which the prompt's rule 4 forbids, so its figure isn't in the evidence. Its "6" was right.
  - **TC14** queried every quarter, not just FY26's, where the question allows no extra periods. Its FY26 values were right.

  SL16 and TC14 are strict scoring, kept as written.
- **MH09, all four runs:** neither model reproduced the golden's "heaviest loading" window. They used other loading measures, or the right quarter with the wrong region.

**The layer kept improving during the evaluation, and each change is logged and reported, not silently re-run:**
- **D34:** `get_anomalies` filters and ordering.
- **D36:** the Indian fiscal year as a time grain.
- **D37:** every filter on a two-hop dimension had been broken, 41 metric-and-dimension pairs.
- **D39:** the free tier found a fiscal-grain query that took 10 s and timed out: TC01 had hit it in every governed run since D36. One planner setting took it to 0.15 s.
- **D42:** Ollama replies are streamed, after a Cloudflare tunnel cut a long, silent generation at 100 s. That's transport only.

On the first 40-question set, the governed runs reached 93.8% on both models, against 71.9% (Gemini) and 56.2% (Qwen) raw. Those runs stay in the table, labelled `v1-40q`.

**Caveats, stated plainly:**
- One run per configuration, at temperature 0.
- Gemini raw spanned two days, because the free tier's daily quota ran out at question 31. Nothing in Gemini's path changed in between.
- Qwen governed's first 23 answers came before streaming (D42); its other 79 came after.
- MH04's evidence-tool requirement applies to governed mode only, by design (D32).
- Governed mode costs about 3–4x the input tokens of raw mode, because the metric glossary rides in every prompt. It's $0 on these free tiers, not on a paid one.

## What I'd defend in an interview
- **The semantic layer is worth 16 to 28 points of accuracy on cheap models, measured question by question.** On 102 questions, governed mode took Gemini 3.5 Flash-Lite from 72.1% to 88.2% and Qwen3.8 27B from 69.1% to 97.1%. Paired on the same 68 answerable questions, the gains are 15 against 4 and 20 against 1 (McNemar p = 0.019 and 0.00002), each from a single run at temperature 0. Wrong figures fall from 19 to 8 and from 20 to 2. The raw-mode failures are definition drift on the same questions for both models, which a governed metric makes impossible. The trade-offs are reported too: Qwen answered two forecast traps in governed mode that it refused in raw, and every model answers most ambiguous questions instead of asking.
- **Two anomalies came through cleanly: the resin lot and the decoy.** For the lot, the cohort view beat the raw monthly count by six weeks. For the decoy, the join path through installations points at the installer, while the batch view shows nothing.
- **The misses are more useful than a clean sweep would have been.** Each has a specific, fixable cause:
  - the lot scan's missing peer-exposure floor;
  - the health score's coarse regional percentiles;
  - the stuffing rule's lack of a concentration condition.

  Because the rules were pre-registered, none of this could be quietly tuned away. Every fix becomes a logged deviation, reported under both rules.
- **The acceptance suite found a real generator bug**, the stuffing drain. It also measured, rather than assumed, how closely the simulator hits its own targets.
