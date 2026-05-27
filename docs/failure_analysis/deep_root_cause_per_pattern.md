# Deep root-cause analysis — Kimi K2.6 `incorrect` failures, pattern by pattern

**Companion to** `analysis/kimi-k2.6/incorrect_failure_breakdown.md` (the
93-failure categorization) and `analysis/kimi-k2.6/root_cause_and_planner_fix.md`
(the planner-fix hypothesis).

Each section walks one bug pattern: representative trace, hypothesised cause,
verification on the actual data where possible, and an honest planner-
fixability assessment.

---

## Pattern A — Null-as-wildcard (the dominant bug)

**Already verified** in the previous memos. Recap:

- Manual.md line 95: *"If a field is set to null it means that it applies to
  all possible values of that field."*
- Kimi filters `is_credit == True` and excludes rows where `is_credit IS NULL`.
- Null rules should apply.

**Direct reproduction on real data**:

| Task | Question | Kimi filter | Kimi result | Gold filter | Gold result |
|---|---|---|---|---|---|
| 1275 | avg fee SwiftCharge credit, 10€ | `is_credit==True` | 0.122408 | `is_credit==True OR null` | **0.120609** ✓ |
| 1278 | avg fee NexPay credit, 50€ | `is_credit==True` | 0.353053 | `is_credit==True OR null` | **0.352294** ✓ |

**Estimated impact**: ≈25 of 32 delta_what_if failures + scattered cases elsewhere = **~25-28 of 93 total**.

**Planner-fixable (generic)?** YES. Planner meta-rule: "translate non-default
null/wildcard semantics into concrete code patterns."

---

## Pattern A2 — Definition-shift bug (fraud-rate convention)

This is a NEW finding from the deep dive. Adjacent to Pattern A but
distinct: it's not about null handling, it's about **applying a definition
documented in one context to a question that doesn't explicitly invoke
that context**.

### Verified case: task 17

- **Question**: *"What is the lowest avg fraud rate per merchant for the year 2023?"*
- **Gold**: `8.91`
- **Kimi pred**: `7.683437`

**Kimi's compute** (from trace, call 3):
```python
df_2023 = df[df['year']==2023]
fraud_rate = df_2023.groupby('merchant')['has_fraudulent_dispute'].mean()
# Lowest: Golfclub_Baron_Friso 0.076834 = 7.683437%
```
→ **Count-weighted** fraud rate = proportion of transactions flagged fraud.

**Verification on data**:

| Definition | Lowest per merchant |
|---|---|
| **Count-weighted** (mean of `has_fraudulent_dispute`, Kimi's) | **7.683437%** (Golfclub) |
| **Volume-weighted** (sum fraud €/total €) | **8.907926%** (Crossfit) ≈ gold 8.91 ✓ |
| Excluding `is_refused_by_adyen` | 8.215166% (Golfclub) — neither |

**Root cause**: manual.md defines fraud rate in the fee-rule section as
*"ratio between monthly total volume and monthly volume notified as fraud"*
— i.e., **volume-weighted**. Kimi reads this definition while studying the
fee-rule schema, but DOES NOT apply it when answering a general
"merchant fraud rate" question. Kimi defaults to count-weighted (the
pandas-default mean of a boolean column).

**Hypothesis class**: same as Pattern A. **The model knows the convention abstractly
but doesn't apply it broadly.** Pandas-style boolean mean is the lower-effort
pattern; the volume-weighted definition is "buried" in the fee-rule section.

**Impact estimate**: most fraud_metric numeric failures (17, 19, 58 confirmed
plausible; check 16, 18, 61 for the merchant-pick variants). Likely **~5-7
of 9 fraud_metric tasks** affected.

**Planner-fixable (generic)?** YES. Planner meta-rule: *"If the docs define
a metric (fraud rate, volume tier, etc.) and the question uses that metric
name, surface the docs-defined formula in the spec — even if the question
doesn't explicitly invoke the fee-rule / docs context."*

---

## Pattern B — Fee-rule sum-vs-pick convention (1739 cluster)

**Already deeply diagnosed** in `analysis/grafting_pilot/v2/1739_diagnosis.md`
and `1739_v21_followup.md`. Quick recap:

- Manual.md is silent on whether multiple matching rules SUM per transaction
  or only the most-specific applies.
- Kimi defaults to "one rule per transaction" (intuitive prior).
- Gold convention is "sum all matching rules per transaction".
- Verified by reproduction: H3 (sum all) = exactly gold 51.15; H1 (most-specific) = exactly Kimi's 28.92.

**Planner-fixable (generic)?** **NO** — verified across v2.0, v2.1, v2.2.
Sonnet planner CONFIDENTLY asserted the wrong "one rule per txn" convention
in every variant, even with session continuity, blind-spot detection, AND
`read_file` access. Sonnet shares Kimi's prior because the convention is in
NO docs at all (not even abstractly). This needs:

- Spec-extractor required to mark `convention: ambiguous_in_docs` when no
  explicit rule found, AND executor must then try both interpretations.
- OR stronger executor model (untested).

**Impact**: 8 of 93 (all 8 fee_rule incorrect tasks).

---

## Pattern C — Token corruption (generation glitch)

**Examples**:
- Task 15 (fraud_metric): pred = `"SF AGAIN彩彩 SF BY AGAIN上课时间..."` — 0 run_python calls
- Task 889 (aci_format): pred = `"Moonbeam-code7C0Deb786Ce1911cBE..."` — pure gibberish
- Task 1775 (fee_rule): pred = `"缓缓In pol pol缓缓缓缓..."`
- Task 1739: pred = `"′7′"` (Unicode quotes)

**Diagnosis**: model-side / inference-pipeline failure. Kimi never reached a
coherent answer text. Not a logic problem.

**Planner-fixable?** **NO** — sampling variance. Re-run usually succeeds.

**Impact**: 4 of 93. Sampling-variance recoverable.

---

## Pattern D — Truncated commits (prose without final value)

**Examples**:
- Task 1810: `"I'll follow the required workflow to find the applicable Fee IDs..."` — 2 calls, never finished
- Task 1750: `"Now let me read the payments README:"` — 25 calls, truncated mid-prose
- Task 70-style overcommit may also fall here in some cases

**Diagnosis**: similar to C — model emits an opener but the actual answer
doesn't make it into the assistant text channel. Often hits an implicit
streaming termination before committing.

**Planner-fixable?** **NO** — generation-side. Re-run helps.

**Impact**: 3 of 93. Sampling-variance recoverable.

---

## Pattern E — Single-vs-list answer shape

### Investigated cases: 1433, 1434

- **Q1433**: *"What is the most expensive MCC for a transaction of 1 euros,
  in general? If there are many MCCs with the same value, list all of them."*
- **Gold**: `5813` (single)
- **Kimi pred**: `3000, 3001, 3002, 3003, 7011, 7032, 7512, 7513` (8 MCCs)

**Verification**: I tested 4 aggregations on the data
(max-per-MCC, sum-all-rules-per-MCC, avg-per-MCC, empty-MCC-list-as-wildcard).
**None reproduces gold `5813`.**

| Aggregation | Result |
|---|---|
| max-per-MCC at 1€ (Kimi) | `3000, 3001, 3002, 3003, 7011, 7032, 7512, 7513` |
| sum-all-rules-per-MCC | `8011, 8021` |
| avg-per-MCC | `5814, 5815, 7832, 7922, 7995, 7999` |
| max-per-MCC w/ empty-MCC rules as wildcard | same as Kimi |
| **Gold** | **5813** (no aggregation tested produces this) |

**Root cause**: likely a **benchmark error** OR uses a convention not
documented anywhere (or that I haven't reconstructed). Listed in our
"suspect gold" section earlier.

**Planner-fixable?** **NO** — when the gold itself is suspect, no architectural
fix helps. Flag upstream.

**Impact**: 2 confirmed (1433, 1434) + the "list_when_single" bucket = 2.

---

## Pattern F — Format mismatch hiding correct content

### Verified case: 1489

- **Gold**: `5, 9, 20, 28, 29, 30, 48, 58, 61, 67, 76, 84, 90, 96, 101, 108, 110, 120, 122, 1...`
- **Kimi pred**: `5, 9, 20, 28, 29, 30, 48, 58, 61 67 76 84 90 96 101 108 110 120 122 128 131 140 ...`

Items are **set-equal**. Only difference: pred uses spaces between MOST items
where gold uses comma-spaces. The official `question_scorer` may or may not
flag this depending on its parsing.

**Root cause**: Kimi writes `' '.join(map(str, sorted(fee_ids)))` instead of
`', '.join(...)`. A one-character typo upstream of the final print().

**Planner-fixable (generic)?** YES — meta-rule #4 (FORMAT FIDELITY). Planner
should quote the exact separator verbatim in `expected_output_format` AND
include a worked one-line example.

**Impact**: 2 confirmed; possibly more hidden inside other categories.

---

## Pattern G — Yes/no when "Not Applicable" expected

### Verified case: task 70

- **Question**: *"Is Martinis_Fine_Steakhouse in danger of getting a
  high-fraud rate fine?"*
- **Guidelines**: *"Answer must be just either yes or no. If a question does not
  have a relevant or applicable answer for the task, please respond with 'Not
  Applicable'."*
- **Gold**: `Not Applicable`
- **Kimi pred**: `yes`

**Kimi's compute** (last reasoning):
- Computed Martinis fraud rate = 9.13% (> 8.3%).
- Found a single fee rule with `monthly_fraud_level: '>8.3%'` (rule 638)
  for MCC 5812 (Martinis's MCC).
- But rule 638 requires `account_type ['S', 'R']`, Martinis is `'H'`.
- So rule 638 doesn't actually apply to Martinis.
- **Despite no rule applying, Kimi answered "yes"** to the danger question.

**Root cause**: the question references **"fine"** — a concept NOT
documented in `manual.md`. The manual documents fee RULES (higher rates for
high-fraud merchants), but it never defines a "fine" mechanism. Gold
correctly says NA because the question is unanswerable from documented
material. Kimi conflated "fine" with "high-fee rule" and overcommitted to
"yes".

**Hypothesis class**: model overcommit when docs don't define the concept.
Same root cause as the SQL prior dominance — Kimi prefers committing a
confident answer over admitting the question is unanswerable from data.

**Planner-fixable (generic)?** YES — meta-rule #5 (NA DETECTION). The
planner can check: *"Does the question reference a concept (fine,
threshold, named metric, etc.) that's NOT defined in the source documents?
If yes, flag for the executor that the correct answer is 'Not Applicable'
per the guidelines."*

**Impact**: 2 confirmed (70, 71); likely 2-3 more disguised inside
`wrong_single_value` and `numeric_off`.

---

## Pattern I — Direction reversal (highest/lowest)

### Investigated cases

- **Task 16** ("**lowest** avg fraud rate for 2023"): gold `Crossfit_Hanna`,
  pred `Golfclub_Baron_Friso`.
  
  Looking at Kimi's compute: it correctly groupby-meaned `has_fraudulent_dispute`
  and picked the MINIMUM. But the MIN under count-weighted fraud rate is
  Golfclub (0.0768); under volume-weighted, the order changes and Crossfit
  becomes the minimum.
  
  So 16 is actually **Pattern A2 (definition shift)** — NOT direction reversal.
  Kimi's direction is correct; it's the definition that differs.

- **Task 18** ("**highest** avg fraud rate for 2023 by card_scheme"): gold
  `TransactPlus`, pred `SwiftCharge`. Same likely cause — definition shift
  (count- vs volume-weighted) changes which scheme is the max.

- **Task 61** ("highest fluctuation (std)"): probably also a definition
  shift on "fluctuation" — Kimi might compute std differently than gold.

**Reclassification**: most of what my heuristic labelled "direction
reversal" is actually **Pattern A2** — the merchant/scheme picked matches
the direction (min/max) but the underlying metric differs.

**Planner-fixable (generic)?** Already covered by meta-rule for A2
(surface docs-defined formula even when not explicitly invoked).

**Impact**: 3 confirmed; reclassified as Pattern A2. Net direction-only
errors: probably 0-1.

---

## Pattern J — Wrong filter / dataset slice

### Investigated case: 1519

- **Question**: *"In the average scenario, which card scheme would provide
  the cheapest fee for a transaction value of 4321 EUR?"*
- **Gold**: `GlobalCard`
- **Kimi pred**: `SwiftCharge`

**Verification on data**:

| Filter | Cheapest scheme |
|---|---|
| **All rules** (no filter) | **GlobalCard** (22.46) ✓ matches gold |
| `is_credit==True` only | GlobalCard (21.02) |
| `is_credit==True OR null` | GlobalCard (21.22) |

Under ANY natural filter, GlobalCard is the cheapest. So Kimi must have
used a filter that EXCLUDED a chunk of GlobalCard rules — possibly:
- Excluded rules with high fixed_amount even though the question is averages
- Applied an additional filter we didn't reconstruct (e.g., specific MCC,
  account_type, intracountry, etc.)

Without re-walking the full 13-call trace I can't pinpoint the exact bug.
But the PATTERN is clear: **Kimi's filter is over-narrow**, excluding rules
that should be included in the "average scenario."

**Planner-fixable (generic)?** Partial — meta-rule #6 (FILTER EXPLICITNESS):
*"Spell out filter predicates in pandas notation. Don't describe them in
English alone. If the question says 'in general' or 'in the average scenario',
explicitly state that the filter is the empty set (i.e., all rules)."*

**Impact**: scattered across `wrong_single_value` and `list_mostly_wrong`.
Estimate 5-8 of 93.

---

## Refined impact summary (after deep diagnosis)

| Pattern | Original count | Refined count | Planner-fixable | Generic instruction |
|---|---|---|---|---|
| A — null handling | ~25 | ~25 | YES | Translate non-default null semantics to code |
| A2 — definition-shift (fraud rate, etc.) | (was scattered) | **~5-8** | YES | Surface docs-defined formula even when not explicitly invoked |
| B — fee-rule sum-vs-pick | 8 | 8 | **NO** | (needs spec-layer flag + multi-convention probe) |
| C — token corruption | 4 | 4 | NO | (sampling variance) |
| D — truncation | 3 | 3 | NO | (sampling variance) |
| E — shape, single vs list | 2 | 2 (suspect benchmark) | (NO) | — |
| F — format mismatch | 2 | 2-4 | YES | Quote exact format string + worked example |
| G — yes/no vs NA (overcommit on undefined concept) | 2 | 2-3 | YES | Detect when question concept isn't in docs |
| H — suspect benchmark errors | ~5 | ~5 | NO | (flag upstream) |
| I — direction reversal | 3 | **~0** (reclassified to A2) | — | — |
| J — wrong filter | scattered | **~5-8** | partial | Spell out filter in pandas notation |

**Refined planner-fixable estimate**: A (~25) + A2 (~5-8) + F (~2-4) + G (~2-3) + J (~3-5 partial) = **~35-45 of 93 incorrect failures**.

Plus:
- Re-run corrupted/truncated cases (~5/7)
- Spec-layer fix for B (~5/8 if convention surfaced as ambiguous)
- Lenient set-based scorer (1-2 from F overlap)

**Combined ceiling: ~45-55 of 93 (~48-59%) recoverable** with generic
planner-side architecture + a few non-planner fixes.

---

## Honest unknowns

1. **Do the proposed planner meta-rules ACTUALLY change planner output?**
   The biggest test is whether adding meta-rule #1 (translate non-default
   semantics) makes the planner emit `OR is_credit IS NULL` in
   `computation_plan`, or whether the planner shares Kimi's prior and
   skips the translation. Untested.

2. **Pattern A2's exact scope.** We confirmed task 17. Need to check 18,
   58, 19, 60, 61 to see if they're all the count-vs-volume definition
   shift. Each one is a small extra script.

3. **Pattern J's scope.** Task 1519 doesn't reproduce easily. Some of these
   may also be A or A2 in disguise. Per-task investigation needed.

4. **Suspect benchmark cases (1433, 1453, 2715)** — would a Sonnet-as-
   executor produce the same answers Kimi did? If yes, that strengthens
   "benchmark gold is wrong" hypothesis.

## Recommended next experiment

**Generic planner-meta-rule test on a 10-task delta_what_if + fraud_metric mix**:

1. Patch `scripts/extract_specs.py` SYSTEM_PROMPT with the 6 meta-rules
   from `root_cause_and_planner_fix.md` (no DABStep-specific hints).
2. Re-extract specs for 5 delta_what_if + 5 fraud_metric incorrect tasks.
3. Inspect the new specs: do they now include `OR is_credit IS NULL`
   patterns? Do they invoke volume-weighted fraud rate?
4. Re-run Kimi on the patched specs.
5. Compare pass rate vs the v1 sonnet_kimi baseline (4/5 on the original
   5-task pilot).

Cost: ~$10. Time: ~1 hour. The key signal is whether the meta-rules
ACTUALLY trigger semantic translation in the planner output, not just
whether the final answer is right.

## Artefacts

- `analysis/kimi-k2.6/incorrect_failure_breakdown.md` — full 93-task categorization
- `analysis/kimi-k2.6/root_cause_and_planner_fix.md` — planner-as-translator hypothesis with proposed meta-rules
- `analysis/kimi-k2.6/incorrect_summary.csv`, `incorrect_categorized.csv`, `incorrect_traces/<task_id>.md` — per-task data
- This memo: `analysis/kimi-k2.6/deep_root_cause_per_pattern.md`
