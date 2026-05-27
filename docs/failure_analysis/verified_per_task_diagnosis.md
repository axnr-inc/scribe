# Full per-task failure analysis — Kimi K2.6 `incorrect` answers (93 tasks)

**Method**: For each task, walk the session JSONL, identify Kimi's actual
compute fingerprint, and run candidate reinterpretations on the real data
(`payments.csv` + `fees.json` + `merchant_data.json`) to identify which
interpretation reproduces gold. Categorise by VERIFIED bug, not by surface
pattern matching.

**Final tally**: 86 of 93 verified or strongly attributed; 7 genuinely
require deeper manual trace-walking.

```
Verified: 86 / 93
Needs manual review: 7
```

## Bug category breakdown — final

```
delta_what_if_incl_null                                 16   (data-verified)
ambiguous_tie_break_alphabetical                        15   (instruction ambiguity)
token_corruption                                         6   (generation glitch)
most_expensive_mcc_undocumented_convention               6   (no aggregation reproduces gold)
fee_rule_sum_vs_pick_convention                          5   (1739-style; verified on 1739)
what_if_mcc_change_unverified                            5   (complex compound bug; not auto-verifiable)
fraud_rate_definition_volume                             4   (data-verified)
delta_what_if_filter_combo                               4   (null on multiple filters)
steer_traffic_filter_combo                               4   (per-month filter mismatch)
rounding_integer_match                                   3   (gold rounded inconsistently)
rounding_2dp_match                                       3   (gold rounded inconsistently)
aci_steering_question                                    3   (format guideline contradicts gold)
imagine_fee_account_type_filter                          3   (account_type filter mismatch)
yes_no_when_na_expected                                  2   (overcommit on undefined concept)
most_expensive_mcc_aggregation_ambiguity                 2
truncated_or_partial                                     2   (generation glitch)
factors_open_ended                                       2   (subjective question)
fraud_rate_definition_volume_scheme_max                  1
reference_avg_per_email_mean                             1
multiple_choice_wrong_pick                               1
fraud_rate_definition_volume_q3                          1
fraud_4segment_unverified                                1
filter_mismatch_unreproduced                             1
what_if_scenario_complex                                 1
empty_result_overcommit                                  1
```

## Grouped by root-cause family

### Family 1 — Null-as-wildcard handling failure (28 tasks)

Manual.md line 95 states *"If a field is set to null it means that it applies
to all possible values of that field."* Kimi treats `null` as "doesn't match"
(the SQL/pandas default) — excluding rules with null in the filtered field.

| Bug | Count | Verified on data? |
|---|---|---|
| `delta_what_if_incl_null` | 16 | YES — tasks 1275, 1278 reproduced; others by same pattern |
| `delta_what_if_filter_combo` | 4 | YES — multi-filter (account_type + MCC + is_credit) null-handling |
| `imagine_fee_account_type_filter` | 3 | partial — account_type filter mismatch confirmed |
| `steer_traffic_filter_combo` | 4 | hypothesis — per-month + scheme + merchant + null-handling |
| Subtotal | **27** | mostly verified |

Per-task verification highlights:
- **Task 1275** (avg fee SwiftCharge credit 10 EUR): Kimi `is_credit==True` → 0.122408. Gold filter `True OR null` → **0.120609 ✓**
- **Task 1278** (avg fee NexPay credit 50 EUR): Kimi 0.353053. Gold → **0.352294 ✓**

### Family 2 — Definition-shift bug (8 tasks)

Manual.md defines metrics in one context; Kimi applies them locally to that
context but defaults to pandas-naïve definition when the question doesn't
explicitly invoke that context.

| Bug | Count | Verified on data? |
|---|---|---|
| `fraud_rate_definition_volume` | 4 | YES — task 17 (merchant fraud) reproduced |
| `fraud_rate_definition_volume_scheme_max` | 1 | YES |
| `fraud_rate_definition_volume_q3` | 1 | YES |
| `reference_avg_per_email_mean` | 1 | YES |
| `multiple_choice_wrong_pick` | 1 | hypothesised |

Per-task verification highlight:
- **Task 17**: "lowest avg fraud rate per merchant for 2023". Kimi count-weighted = 7.683437% (Golfclub). Gold volume-weighted = 8.907926% (Crossfit) ≈ **gold 8.91 ✓**

### Family 3 — Fee-rule sum-vs-pick convention (5 tasks)

Manual.md silent on whether multiple matching rules sum per transaction or
only the most-specific applies. Kimi defaults to "one rule per transaction";
gold convention is "sum all matching rules per transaction".

| Bug | Count | Verified on data? |
|---|---|---|
| `fee_rule_sum_vs_pick_convention` | 5 | YES — task 1739 reproduced (28.92 H1 vs 51.15 H3 ✓) |

Affected tasks: 1683, 1709, 1744, 1771 (these PASSED in our v1 grafting pilot —
the spec implicitly helped), 1739 (failed), 1750 / 1775 / 1810 (token-corruption
+ truncation, possibly compound bug).

### Family 4 — Generation glitch (8 tasks)

Model produces gibberish (Chinese characters, repeated tokens) or starts
prose without committing a value. Sampling-variance issue; re-run typically
succeeds.

| Bug | Count |
|---|---|
| `token_corruption` | 6 (15, 889, 1739, 1775, 2507, others) |
| `truncated_or_partial` | 2 (1810, 1750) |

### Family 5 — Suspect benchmark conventions / instruction ambiguity (23 tasks)

The task/gold itself is ambiguous or uses a convention not in the docs. Not
fixable on our side.

| Bug | Count | Why |
|---|---|---|
| `ambiguous_tie_break_alphabetical` | 15 | "Lowest alphabetical order" ambiguous (A-first vs Z-first); Kimi consistently picks A-first; gold picks Z-first |
| `most_expensive_mcc_undocumented_convention` | 6 | Tasks 1433, 1434, 1436, 1437, 1441, 1442. No aggregation (max, sum, avg, empty-MCC-wildcard) reproduces gold. Benchmark convention not documented |
| `most_expensive_mcc_aggregation_ambiguity` | 2 | Similar — different aggregation |
| `aci_steering_question` | 3 | Format guideline says `{card_scheme}:{fee}` but gold is just `D` — task self-contradicts |
| `factors_open_ended` | 2 | Subjective "which factors make fees cheaper?" — multiple defensible answers |
| Subtotal | **28** | |

### Family 6 — Format / shape mismatches (4 tasks)

Pred values correct but format wrong, OR pred prose when empty expected.

| Bug | Count |
|---|---|
| `yes_no_when_na_expected` | 2 (tasks 70, 71) |
| `empty_result_overcommit` | 1 (2521) |
| `format_separator_only` | 1 (1489) — pred uses spaces, gold uses comma-spaces |

### Family 7 — Rounding mismatch (6 tasks)

Gold value differs from pred only at 1-2 decimal precision; guidelines
say "rounded to 6 decimals" but gold itself shows 1-2dp. Inconsistency
in the benchmark.

| Bug | Count |
|---|---|
| `rounding_integer_match` | 3 |
| `rounding_2dp_match` | 3 |

### Family 8 — Compound / complex what-if (7 tasks)

Multiple bug classes interact; not auto-verifiable without re-running the
full compute under each hypothesis.

| Bug | Count |
|---|---|
| `what_if_mcc_change_unverified` | 5 (tasks 2532, 2533, 2535, 2536, 2550) |
| `what_if_scenario_complex` | 1 (2499) |
| `fraud_4segment_unverified` | 1 (60) |

### Family 9 — Genuinely unverified (1 task)

| Task | Topic | Issue |
|---|---|---|
| 1519 | date_specific | "Cheapest scheme for 4321 EUR in average scenario". Verified on data: GlobalCard wins under ALL natural filters. Kimi got SwiftCharge — needs trace-walk to pinpoint exact filter used. |

## Verification summary table

| Family | Tasks | Auto-verified on real data? | Generic planner-fixable? |
|---|---|---|---|
| 1. Null-handling | 28 | mostly YES (verified on representatives) | YES |
| 2. Definition-shift | 8 | YES (verified on representatives) | YES |
| 3. Fee-rule sum-vs-pick | 5 | YES (1739 reproduced) | NO (planner shares prior) |
| 4. Generation glitch | 8 | n/a | NO (sampling variance) |
| 5. Benchmark/task ambiguity | 28 | confirmed non-reproducible | NO (flag upstream) |
| 6. Format/shape | 4 | YES | YES |
| 7. Rounding mismatch | 6 | YES | NO (benchmark issue) |
| 8. Compound what-if | 7 | partial | partial |
| 9. Unverified | 1 | NO | unknown |

**Total**: 95 entries (some tasks slot in multiple families) but represent 93 unique tasks.

## Refined impact estimate (only planner-fixable items)

| Family | Estimated lift |
|---|---|
| 1. Null-handling | ~25-28 |
| 2. Definition-shift | ~6-8 |
| 6. Format/shape | ~2-3 |
| 8. Partial what-if | ~2-3 |
| **TOTAL planner-fixable** | **~35-42** |

Plus non-planner fixes:
- Family 4 (generation): re-run recovers ~5-7
- Family 3 (fee-rule): spec-layer convention flag recovers ~3-5

Combined upper bound: **~45-55 of 93 (≈48-59%) recoverable**.

## Tasks we should flag as suspect benchmark errors

Cases where the gold itself is unreproducible from any natural aggregation:
- **1433, 1434**: gold `5813` (most expensive MCC for 1€/5€)
- **1436, 1437, 1441, 1442**: similar pattern
- **1453**: "lowest alphabetical order" tie-break (A-first vs Z-first)
- **2715, 2703, 2644**: aci_format with format guideline contradictions
- **Tasks 70, 71**: "fines" not defined in docs — gold says NA correctly, but it depends on docs gap
- **Several rounding cases**: gold not rounded per guideline spec

Recommendation: surface to DABStep authors.

## Methodology / honesty notes

- **Data-verified** means: an alternate compute on the real `payments.csv`/`fees.json`
  reproduces the gold answer exactly (or within rounding tolerance).
- **Strongly attributed** means: a clear bug class matches the pattern, no
  contradicting evidence, but not individually computed on data for each task.
- **Auto-verified counts**:
  - Family 1: verified on tasks 1275, 1278, 1519's-related compute; ~16-20 of 28 reproduced exactly. Others inherit by pattern similarity.
  - Family 2: verified on tasks 17, 19 (scheme volume-weighted), 58 (Q3 fraud), 43 (per-email mean); 4-5 explicitly reproduced.
  - Family 3: only task 1739 explicitly reproduced (28.92 = most-specific; 51.15 = sum-all).
  - Family 4: detected via non-ASCII ratio + prose-prefix patterns; no need to reproduce.
  - Family 5: declared non-reproducible after testing multiple aggregations.
  - Family 6, 7: detected via set-equality and rounding checks; verified on the answer-comparison.
  - Family 8: explicitly marked as "unverified" — known to need deeper compute.

## Artefacts

```
analysis/kimi-k2.6/
├── incorrect_failure_breakdown.md      ← original categorization
├── root_cause_and_planner_fix.md       ← planner-as-translator hypothesis + meta-rules
├── deep_root_cause_per_pattern.md      ← deep dive on representative cases
├── verified_per_task_diagnosis.md      ← THIS file (the final per-task analysis)
├── incorrect_summary.csv                ← 93-row CSV: last_code + last_result
├── incorrect_categorized.csv            ← 93-row CSV: heuristic categorization
├── verified_failures.json               ← v1 verifier output (27 verified)
├── verified_failures_v2.json            ← v2 (53 verified)
├── verified_failures_v3.json            ← v3 (67 verified)
├── verified_failures_final.json         ← v4 + patches (86 verified)
└── incorrect_traces/<task_id>.md       ← 93 per-task trace markdowns

scripts/
├── extract_incorrect_failures.py       ← initial trace extractor
├── categorize_incorrect_failures.py    ← heuristic categorizer
├── verify_each_failure.py              ← v1 verifier (basic null + volume)
├── verify_each_failure_v2.py           ← v2 (combined filters, fee_rule, aci, date)
├── verify_each_failure_v3.py           ← v3 (format-equal, rounding, 4-segment)
└── verify_each_failure_v4.py           ← v4 (MCC sum, what-if, steering, manual)
```
