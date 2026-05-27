# Root-cause analysis + planner-as-translator hypothesis

**Companion to**: `analysis/kimi-k2.6/incorrect_failure_breakdown.md` (the 93-failure categorization).

**Question raised by the user**:
> *"If we hardcode 'null = wildcard' in the prompt, isn't that overfitting?
> Why does Kimi skip the null rules anyway — is it a harness problem (fixable
> generically) or a model problem (intrinsic)? Can the planner agent — which
> already beat Opus on the 5-task pilot — solve this GENERICALLY without us
> hardcoding task-specific instructions?"*

This is the right framing. The memo below works through it.

## The core insight

The planner agent's job is **to translate ambiguous docs into concrete executable
instructions** for the executor. We've been treating the planner as a passive
spec writer, but it can be a much more active interpreter — anticipating
where the executor's pretraining prior would conflict with what the docs
actually say, and pre-empting that conflict.

**Critically**, this is GENERIC. We don't tell the planner anything DABStep-
specific. We tell it: *"when you spot non-default semantics, translate the
abstract rule into the concrete code pattern; don't leave it abstract."*
That instruction applies to any benchmark.

## Why does Kimi skip the null rules? (the answer to "harness vs model")

Three layered hypotheses:

| Hypothesis | Evidence for | Evidence against |
|---|---|---|
| **H1 — Harness problem** (agent doesn't read enough) | tool result occasionally truncated at 5K chars | memo 07: 97.5% of tasks read `manual.md`. Kimi DOES see line 95. |
| **H2 — Model problem** (pretraining prior dominates explicit rule) | Standard SQL/pandas: `WHERE x = True` excludes nulls. Kimi defaults to this trained instinct. Manual is one line in 337 — easy to read, hard to translate to code. | A stronger model (Sonnet/Opus) might handle it correctly; untested on delta_what_if directly. |
| **H3 — Docs problem** (manual states rule abstractly, doesn't show the code) | Manual says "null = applies to all" but never gives the pandas filter pattern. The translation step is left to the model. | Out of our control; we can't patch the manual. |

**Verdict**: dominantly **H2 (pretraining prior) exacerbated by H3 (abstract
docs)**. The model has the docs in context AND has the SQL prior. Under
pressure to write code fast, the prior wins.

Can the harness fix this? Partially — by inserting a translator step
**between** the docs and the executor. That's exactly what the planner is.

## How the planner solves H1 + H3 generically

Generic addition to the planner's system prompt (no DABStep references):

```
When you spot semantics in the source documents that DIVERGE from the
default behaviour the executor would assume from its pretraining (e.g.,
"null in a field means it applies to all values" vs the typical SQL/pandas
"null = absent"), translate the abstract rule into the concrete code
pattern the executor must use. State it positively in the computation
plan, e.g.:

    "filter rules where `is_credit == X OR is_credit IS NULL`"
    (NOT just "filter where is_credit == X" — that would exclude
     null-credit rules which the docs say also match)

Don't leave non-default semantics as abstract sentences. Translate
abstract → executable.
```

This is a meta-instruction about how to plan, not a task-specific hint. It
would apply equally to any benchmark whose docs define non-default
null/wildcard/match semantics.

## Pattern-by-pattern: what the planner can and can't fix

| Pattern | Count | Planner-fixable (generic)? | Generic planner-side instruction |
|---|---|---|---|
| **A. Null-as-wildcard handling** | ~25 | **YES** | Translate non-default null/wildcard semantics into concrete code patterns. |
| **B. Fee-rule sum-vs-pick convention** | 8 | **NO** | Planner shares the executor's prior (verified across v2.0, v2.1, v2.2). Convention isn't in any doc — no amount of planner sophistication surfaces it. Needs spec-layer fix or empirical multi-convention probe. |
| **C. Token corruption** | 4 | NO | Generation glitch (OpenRouter/Kimi). Sampling variance. |
| **D. Truncation / partial commits** | 3 | NO | Same — generation-side. Re-run helps. |
| **E. Single-vs-list answer shape** | 2 | **YES (partial)** | "If question has conditional formatting ('list all if tied; single if not'), state BOTH branches in expected_output_format." Doesn't help if Kimi's filter itself is wrong (some 1433-style cases are also Pattern J in disguise). |
| **F. Format mismatch (correct values)** | 2+ | **YES** | "Quote the exact format from the guidelines verbatim in `expected_output_format`. Provide a worked example with the correct separator." |
| **G. Yes/no when Not Applicable expected** | 2 | **YES** | "If the question asks about a concept (threshold, fine, named metric) NOT documented in the source materials, flag it in the plan: 'this question cannot be answered from available data; executor should return Not Applicable.'" |
| **H. Suspect benchmark errors** | ~5 | NO — flag upstream | Gold itself is wrong / ambiguous. Not fixable. |
| **I. Direction reversal (highest/lowest)** | ~3 | **YES** | "Identify all comparative/superlative adverbs in the question (highest/lowest/most/fewest/max/min/best/worst). State the direction positively in the plan ('find the merchant with MIN value of X', not just 'find the merchant'). Don't leave direction implicit." |
| **J. Wrong filter / dataset slice** | scattered | **YES (partial)** | "Spell out the EXACT filter predicate in pandas notation in computation_plan, not as an English description. Include all relevant fields with explicit null/wildcard handling." |

## Estimated lift if all planner-fixable patterns are addressed

| Pattern | Tasks | Estimated lift |
|---|---|---|
| A (null) | 25 | ~20 (~80% — direct semantic translation) |
| E (shape) | 2 | 1-2 |
| F (format) | 2 | 1-2 |
| G (NA detection) | 2 | 1-2 |
| I (direction) | 3 | 2-3 |
| J (filter) | ~5 of scattered | 2-4 |
| **TOTAL planner-fixable** | | **~27-33** |

Combined with:
- C/D recovery via re-run (sampling variance): ~5 of 7
- B fix via spec-layer convention patch: ~5 of 8
- H not fixable (suspect gold): 0 lift but at least correctly flagged

**Overall ceiling: ~37-46 of 93 incorrect failures (~40-50%) could be lifted
with generic planner-side improvements + spec-layer convention fix + re-runs
for corruption. NO task-specific prompt hardcoding required.**

## What's NOT planner-fixable (be honest)

1. **The fee-rule convention bug (Pattern B)** — we proved across v2.0,
   v2.1, v2.2 that the planner CONFIDENTLY asserts the wrong convention
   because Sonnet shares Kimi's prior. The planner can't surface a hidden
   semantic it doesn't believe in. This needs either:
   - Spec extractor explicitly required to mark conventions as
     `ambiguous_in_docs` when source is silent (forces executor to try both)
   - Stronger executor model that resists priors better
   - Multi-convention empirical probe at execution time

2. **Generation-side glitches (Patterns C, D)** — sampling variance, not a
   reasoning bug. Re-run typically succeeds.

3. **Suspect benchmark errors (Pattern H)** — gold is wrong/ambiguous.
   No engineering fix; surface upstream.

## Generic planner-side prompt additions (proposed for v2.3)

Concretely, the spec extractor's `SYSTEM_PROMPT` would gain these meta-rules
(none mention any specific DABStep field or rule):

```
PLANNING DISCIPLINE — for any task you're given:

1. SEMANTIC TRANSLATION. When the source documents define non-default
   semantics (null/missing/wildcard/match-all behaviour that diverges from
   what an executor would assume from SQL/pandas pretraining), translate
   the abstract rule into the concrete code pattern. Don't leave it
   abstract.

2. DIRECTION DISCIPLINE. Identify every comparative/superlative adverb in
   the question (highest, lowest, most, fewest, max, min, best, worst).
   State the direction explicitly and positively in the computation plan.

3. SHAPE DISCIPLINE. If the question contains conditional output
   formatting instructions (e.g. 'list all if tied; single value if not'),
   state BOTH branches in your expected_output_format.

4. FORMAT FIDELITY. Quote the exact format string from the task guidelines
   verbatim in expected_output_format. Provide a worked example with the
   correct separator/wrapper.

5. NA DETECTION. If the question asks about a concept (threshold, fine,
   named metric) that the source documents do not define, flag in the plan
   that the executor should return whatever the guidelines specify for
   unanswerable cases (e.g. 'Not Applicable').

6. FILTER EXPLICITNESS. Spell out filter predicates in pandas notation.
   Don't describe them in English alone.
```

These are GENERIC planning best-practices. They don't tell the planner
which fields are null-able for DABStep, which questions are about
thresholds, etc. — those are inferred per task from the docs the planner
already reads.

## Why this isn't overfitting

If we wrote *"is_credit null means it applies to credit transactions"* into the
executor's prompt — that would be overfitting. We'd be teaching the answer.

But teaching the PLANNER to *"recognise and translate non-default null
semantics in any docs it reads"* — that's teaching a transferable skill.
The planner re-derives the specific behaviour each time from the actual
docs. On a different benchmark with different null semantics, the planner
would translate THOSE semantics. No prompt hardcoding.

This is the right architectural intervention.

## Next experiment (proposed)

**Generic planner-prompt enhancement test on delta_what_if cluster**

1. Patch `scripts/extract_specs.py` SYSTEM_PROMPT to include the six
   meta-rules above.
2. Re-extract specs for 5-10 delta_what_if failures (a subset of the 32).
3. Re-run Kimi (no other changes) on the new specs.
4. Score. If ≥4 of the 5-10 now pass, the generic planner-side intervention
   is empirically validated. Scale to all 32 delta_what_if + the rest of
   the 93.

Cost: ~$5–10. Time: ~1 hour. No task-specific prompts.

## Open questions worth verifying empirically

- Does the planner-side meta-rule **actually** trigger semantic translation
  on the null case? Or does Sonnet also share the pandas-default prior and
  still write the abstract rule without translating it to code?
  → Test: extract spec for task 1275 with new SYSTEM_PROMPT, inspect
  whether `computation_plan` mentions `OR IS NULL`.

- For Pattern B (fee-rule convention), does adding meta-rule #1 trigger
  the planner to flag the convention as ambiguous? Or does the planner's
  own prior still dominate?
  → Test: re-extract spec for 1739; inspect whether the spec now contains
  `fee_application_convention: ambiguous_in_docs` (or similar self-flag).

- How does this compare to using a STRONGER planner (Opus 4.7)? Maybe the
  meta-rules are unnecessary with a better planner that already does this
  by default.
  → Test: extract spec for 1275 with Opus 4.7 vs Sonnet 4.6 (no meta-rule
  changes), compare planning quality.

## Artefacts

- `analysis/kimi-k2.6/incorrect_failure_breakdown.md` — the 93-failure categorization (companion memo)
- `analysis/kimi-k2.6/incorrect_summary.csv`, `incorrect_categorized.csv`,
  `incorrect_traces/<task_id>.md` — per-task data
- This memo: `analysis/kimi-k2.6/root_cause_and_planner_fix.md`
