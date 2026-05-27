# Kimi K2.6 DABStep — thorough failure analysis of `incorrect` failures (n=93)

**Scope**: Of Kimi's 228 DABStep failures, this memo analyses the 93 with
`classification = incorrect` — i.e., Kimi committed a concrete answer that was
wrong (excluding iter_capped, no_assistant_response, na_answered). For each
failure we walked the session trace, identified the exact compute Kimi
performed, and where possible reproduced an alternative interpretation on
the actual data to identify the upstream bug.

## TL;DR — the single root cause that dominates

**`null` in fee-rule fields means "matches any value of that field"** (per
`manual.md` line 95: *"If a field is set to null it means that it applies to
all possible values of that field."*). Kimi systematically treats `null` as
"doesn't apply" — when the user asks about credit transactions, Kimi filters
to `is_credit == True` only, missing the rules with `is_credit IS NULL`
(which DO apply to credit transactions).

This single bug, **verified by direct reproduction on tasks 1275 and 1278**,
explains the bulk of the delta_what_if cluster (likely 25+ of 32 failures
there). It's a single conceptual error with massive downstream impact.

## Categorization across all 93 failures

```
wrong_single_value             31   (mostly aci_format + date_specific)
numeric_close (<5% diff)       15   (all delta_what_if)
numeric_off (<50% diff)        11   (delta_what_if + fraud_metric + transaction_count)
list_no_overlap                 8   (merchant_lookup + date_specific)
numeric_very_wrong (>=50%)      7   (delta_what_if + reference_lookup)
token_corruption                4   (fee_rule + date_specific + fraud_metric)
list_mostly_wrong               3
numeric_near_miss (<0.5%)       3   (all delta_what_if)
truncated_or_partial            3   (fee_rule + date_specific)
yes_no_when_na_expected         2   (fraud_metric + other)
list_when_single_expected       2   (merchant_lookup)
list_near_match                 2   (fee_rule)
list_partial_overlap            2   (fee_rule + other)
```

## Verified bug patterns

### Pattern A — Null-as-wildcard handling failure  ← DOMINANT

**Symptom**: numeric answer slightly to moderately wrong on filtered-aggregate
questions (avg fee, total fee, count).
**Bug**: Kimi filters with strict equality (`is_credit == True`) and excludes
rules where the field is `null`. Per the docs, null means "applies to all
values of this field" — null rules should be INCLUDED.

**Verification — task 1275**: "average fee SwiftCharge would charge for a credit
transaction of 10 EUR"

| Filter | Rule count | Mean fee | Match? |
|---|---|---|---|
| `is_credit == True` (Kimi's) | 125 | **0.122408** | matches Kimi pred |
| `is_credit == True OR IS NULL` | 156 | **0.120609** | **matches gold exactly** |

**Verification — task 1278**: "average fee NexPay would charge for a credit
transaction of 50 EUR"

| Filter | Rule count | Mean fee |
|---|---|---|
| `is_credit == True` only (Kimi's) | 95 | **0.353053** |
| `True OR null` | 109 | **0.352294** (gold ✓) |

**Both reproductions exact to 6 decimal places.** Same bug.

**Affected categories (estimated)**:
- numeric_near_miss (3) + numeric_close (15) = 18 — all delta_what_if, all likely this bug
- numeric_off (11) — at least the 7 delta_what_if ones likely this bug; others mixed
- numeric_very_wrong (6 delta_what_if) — may be the same bug compounded by additional filter mistakes

**Estimated total affected**: ≈25 of 93 failures (≈27%) are this single class.

### Pattern B — Fee-rule application convention (sum vs pick)

**Already diagnosed in detail** in `analysis/grafting_pilot/v2/1739_diagnosis.md`.
Manual.md is silent on whether multiple matching rules SUM per transaction or
only the most-specific applies. Kimi (and every other model tested) defaults
to "one rule per transaction"; gold uses "sum all matching".

**Affected tasks**: fee_rule cluster — tasks 1683, 1709, 1739, 1744, 1771,
1775, 1810, 1750 (n=8). Categories: list_near_match (2), list_partial_overlap
(1), token_corruption (2), truncated_or_partial (2), numeric (1).

### Pattern C — Token corruption / generation failure

**Symptom**: Kimi's `pred` is gibberish — Chinese characters, random tokens,
repeated nonsense.

**Examples**:
- Task 15 (fraud_metric): pred = `"SF AGAIN彩彩 SF BY AGAIN上课时间 BY AGAIN..."` — 0 run_python calls, 1 assistant response.
- Task 889 (aci_format): pred = `"Moonbeam-code7C0Deb786Ce1911cBE19111C1918Ec7BE..."` — pure gibberish.
- Task 1775 (fee_rule): pred = `"缓缓In pol pol缓缓缓缓 缓缓..."`
- Task 1739: pred = `"′7′"` (truncation + non-ASCII)

**Diagnosis**: OpenRouter/Kimi inference glitch. Not a model logic failure —
the model failed to emit coherent text at all. Cannot be fixed by prompting
or planner help; would require retry with sampling variation.

**Count**: 4 tasks. Re-running these would likely succeed (sampling variance).

### Pattern D — Truncated/partial commits

**Symptom**: pred is a prose preamble that never reaches the answer — e.g.
`"I'll follow the required workflow to find the applicable Fee IDs..."` or
`"Now let me read the payments README:"`.

**Examples**:
- Task 1810: pred = `"I'll follow the required workflow..."` (2 run_python calls — never finished)
- Task 1750: pred = `"Now let me read the payments README:"` (25 calls, then truncated)

**Diagnosis**: same model-side failure as Pattern C but different shape —
Kimi commits a prose response but the actual answer never makes it into the
text channel. Likely max-token or streaming truncation.

**Count**: 3 tasks. Also sampling-variance recoverable.

### Pattern E — Single-vs-list answer shape

**Symptom**: question asks for ONE value, Kimi gives a LIST (or vice versa).

**Examples**:
- Task 1433: gold `5813` (single MCC), Kimi `3000, 3001, 3002, 3003, 7011, 7032, 7512, 7513` (list of 8).
- Task 1434: same pattern.

**Diagnosis**: question phrasing ("most expensive MCC ... If there are many MCCs with the same value, list all of them") allows for either shape, but
gold expects a tie at 1 — Kimi found a different tie at 8.

**Count**: 2 tasks (list_when_single_expected) — but related to broader
"different aggregation gave different answer" pattern.

### Pattern F — Format mismatch hiding correct content

**Symptom**: answer values correct, format different from gold.

**Confirmed example — task 1489**:
- Gold: `5, 9, 20, 28, 29, 30, 48, 58, 61, 67, 76, 84, 90, 96, 101, 108, 110, 120, 122, 1...`
- Pred: `5, 9, 20, 28, 29, 30, 48, 58, 61 67 76 84 90 96 101 108 110 120 122 128 131 140 ...`
- Difference: pred uses spaces between most items, gold uses commas. Sets equal.

**Diagnosis**: Kimi knows the right values but emits them with wrong separator.
Strict scorer marks this wrong even though it's correct in spirit.

**Count**: 2 tasks (format_only_mismatch). Plus possibly some hidden inside other categories where the scorer treated a format diff as content diff.

### Pattern G — "Yes/No" when "Not Applicable" expected

**Examples**:
- Task 70 (fraud_metric): gold `Not Applicable`, pred `yes`.
- Task 71 (other): gold `Not Applicable`, pred `yes`.

**Diagnosis**: question asks something like "is there a merchant matching X?" — Kimi answers yes/no when the gold expects acknowledgement that the
data can't answer the question. Format guideline says "If a question does
not have a relevant or applicable answer for the task, please respond with
'Not Applicable'", but Kimi treats the question as answerable yes/no.

**Count**: 2.

### Pattern H — Question/task ambiguity (gold = arguably wrong)

**Symptom**: Kimi's compute looks defensible; gold doesn't reproduce from
natural aggregations.

**Suspect cases**:
- **Task 1453** (aci_format): "most expensive ACI ... in case of draw, return ACI with **lowest alphabetical order**." Kimi finds B and C both tie at 1.08, picks B (B precedes C alphabetically). Gold = `C`. The phrase "lowest alphabetical order" is genuinely ambiguous — Kimi's reading is defensible.

- **Task 1433/1434** (merchant_lookup): no aggregation I tested reproduces gold `5813`. Tested: max-per-MCC, sum-all-rules-per-MCC, avg-per-MCC, empty-MCC-list-as-wildcard. None produce 5813. Gold may be a benchmark error or use a convention not documented.

- **Task 2715** (aci_format): guidelines say "{card_scheme}:{fee}" but gold is just `D`. Format guidelines contradict gold itself.

**Count**: ≥5 tasks where the failure is at least partly a task-spec problem.

### Pattern I — Direction reversal (highest vs lowest)

**Symptom**: Kimi picks the OPPOSITE end of an ordering — e.g. picks lowest
merchant when "highest fraud rate" was asked, or vice versa.

**Likely examples (need question-text confirmation per task)**:
- Task 16: gold `Crossfit_Hanna`, pred `Golfclub_Baron_Friso`. From the trace
  data: Golfclub had lowest fraud rate, Crossfit highest. Kimi picked lowest;
  question likely asks for highest.

**Count**: likely 3–6 cases inside the `wrong_single_value` bucket.

### Pattern J — Different filter / dataset slice

**Symptom**: Kimi's filter differs from gold's filter — e.g., includes/excludes
a year, excludes a card scheme, miscomputes date range.

**Likely examples**:
- Task 17, 19, 58 (fraud_metric numeric): all close-but-wrong; likely
  including/excluding the wrong time range.
- Task 1519 (date_specific): gold `GlobalCard`, pred `SwiftCharge`. Different
  card scheme picked from the same comparison.

**Count**: scattered across `numeric_off` and `wrong_single_value`.

## Per-topic breakdown summary

| Topic | n | Dominant pattern(s) |
|---|---|---|
| **delta_what_if** | 32 | **A (null handling)** — 25+ tasks likely |
| **aci_format** | 20 | I (direction), F (format), H (ambiguity) |
| **date_specific** | 12 | J (filter), F (format), C (corruption — 1) |
| **fraud_metric** | 9 | I (direction), J (filter), G (yes/no vs NA) |
| **fee_rule** | 8 | B (convention) — all 8 |
| **merchant_lookup** | 6 | E (shape), H (ambiguity) |
| **other** | 3 | G, E |
| **reference_lookup** | 2 | J (filter) |
| **transaction_count** | 1 | A (likely null handling) |

## What this implies

1. **Pattern A is the single highest-impact fix.** A one-line clarification in
   the prompt or spec — "when filtering rules by a field value X, INCLUDE
   rules where that field is null (null = matches all values)" — would lift
   a likely 25+ of 93 failures. ROI is enormous.

2. **Pattern B (fee-rule convention) is structural, already diagnosed.** The
   1739 follow-up memos show no harness change fixes this; only docs/spec
   layer fixes work.

3. **Patterns C and D (corruption / truncation) are sampling variance.** Re-running these 7 tasks would likely succeed.

4. **Patterns F (format) and H (gold ambiguity) point to scorer/benchmark
   limitations**, not Kimi failures. With a more lenient set-based scorer
   we'd lift 2-5 more tasks. With a benchmark-error filter we'd reclassify
   another few.

5. **Patterns E, G, I, J are genuine model reasoning errors** but each
   affects only 2-6 tasks. Smaller individual impact; harder to fix uniformly.

## Estimated upper bound on what can be lifted

If we built ALL of the following fixes:

| Fix | Tasks recoverable |
|---|---|
| Null-as-wildcard clarification in prompt/spec | ~25 |
| Multi-rule convention clarification (fee_rule) | ~5 of 8 |
| Re-run corrupted/truncated traces (sampling variance) | ~5 of 7 |
| Lenient set-based list scorer | ~3 |
| Better Not-Applicable detection | ~2 |
| Direction-keyword sanity check | ~3 |

**Combined: ~43 of 93 (~46%)** of Kimi's `incorrect` failures could plausibly be
lifted with focused, low-cost interventions — most of them on the prompt/spec
side rather than model swap.

## Tasks that are suspect benchmark errors (do NOT fix, FLAG)

Tasks where no defensible compute produces the gold answer:
- **1433, 1434** (merchant_lookup): gold `5813`, no natural aggregation reproduces it.
- **1453** (aci_format): "lowest alphabetical order" tie-break is genuinely
  ambiguous (A-first vs Z-first).
- **2715** (aci_format): format guideline contradicts gold.

Recommendation: surface these to whoever owns the DABStep dataset.

## Artefacts referenced

```
analysis/kimi-k2.6/incorrect_summary.csv         — 93-row CSV with last_code + last_result per task
analysis/kimi-k2.6/incorrect_categorized.csv     — 93-row CSV with category + subcategory + notes
analysis/kimi-k2.6/incorrect_traces/<task_id>.md — per-task full trace markdown (93 files)
scripts/extract_incorrect_failures.py            — trace extractor
scripts/categorize_incorrect_failures.py         — categorizer
```

This memo: `analysis/kimi-k2.6/incorrect_failure_breakdown.md`
