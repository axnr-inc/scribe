# Definition-Shift: A Failure Mode in Agentic Data Analysis

**Status**: Empirical investigation, ongoing
**Last updated**: 2026-05-21
**Scope**: Documented on DABStep (Adyen fee/transaction benchmark) using the grafting_v2 two-stage architecture (Sonnet/Opus spec agent + Kimi K2.6 executor)

---

## TL;DR

When a benchmark task asks for a metric whose definition is non-default — i.e., the
source documents define the metric in a way that diverges from what a typical
SQL/pandas one-liner would compute — current frontier LLMs (Kimi K2.6, Sonnet 4.6,
Opus 4.7) systematically default to the pandas-naive computation, **even after
reading and quoting the docs-defined formula verbatim**.

We call this **definition-shift**: the model surfaces the correct definition
in prose, then silently substitutes a different (default) computation when
writing code. The bug is robust across:

- Model scale (Sonnet 4.6 → Opus 4.7 makes it worse, not better)
- Architectural intervention (a separate "spec agent" with read_file access)
- Explicit meta-rules in the system prompt telling the agent to "surface
  docs-defined formulas verbatim"

On DABStep, definition-shift accounts for ~8 of 93 (~9%) of Kimi's `incorrect`
failures we deep-analysed. For data-analysis benchmarks where ground truth is
docs-grounded, this is a structurally important and under-discussed failure mode.

---

## 1. Background

### 1.1 The grafting_v2 architecture (one-paragraph version)

grafting_v2 is a two-stage harness:

- **Stage 1 — Spec agent (Sonnet/Opus)**: reads the task + source docs
  (`manual.md`, `fees.json`, schemas) and emits a structured spec via a
  `save_spec` tool. The spec contains a question summary, matching logic,
  computation plan, edge cases, expected output format.
- **Stage 2 — Executor (Kimi K2.6)**: receives the spec, runs a ReAct loop
  with `run_python`, can escalate questions back to the spec agent via
  `ask_spec_agent`. Spec agent has `read_file` access; on review calls it
  re-reads docs and either flags a mistake (returning a revised spec) or
  confirms with doc quotes.

The hope: planner-side semantic translation lets a smaller/cheaper executor
focus on compute, while the spec agent handles meaning.

### 1.2 What we expected definition-shift to look like

From the 93-task analysis of Kimi solo runs (see
`analysis/kimi-k2.6/verified_per_task_diagnosis.md` in the harness repo),
we identified ~8 tasks where:

> Manual.md defines metrics in one context; Kimi applies them locally to that
> context but defaults to pandas-naïve definition when the question doesn't
> explicitly invoke that context.

Hypothesis going in: a spec agent that reads the manual and translates the
docs-defined metric into the computation_plan should fix this. The executor
would inherit a correct formula and compute it.

This document records what actually happened.

---

## 2. The canonical case study — DABStep Task 17

### 2.1 The task

> *What is the lowest avg fraud rate per merchant for the year 2023?*

**Gold answer**: `8.91` (Crossfit_Hanna).

### 2.2 The docs

`manual.md` section 7 contains the only definition of "fraud" in the source
material:

> *"Fraud is defined as the ratio of fraudulent volume over total volume."*

A separate section ("monthly_fraud_level") uses the word "monthly" but only
as a bucket for fee-rule matching, not as a definition of the rate itself.

### 2.3 Reproducing the gold

We computed five candidate interpretations on the real 2023 data and asked
which one reproduces gold `8.91`:

| Hypothesis | Crossfit_Hanna % | min merchant | round2 | matches 8.91? |
|---|---|---|---|---|
| **H1: pooled-annual VOLUME-weighted** | **8.907926** | **Crossfit_Hanna** | **8.91** | **yes** |
| H2: pooled-annual COUNT-weighted | 7.845627 | Golfclub_Baron_Friso | 7.85 | no |
| H3: monthly-then-mean VOLUME-weighted | 8.894813 | Crossfit_Hanna | 8.89 | no |
| H4: monthly-then-mean COUNT-weighted | 7.838506 | Rafa_AI | 7.84 | no |
| H5: daily-then-mean VOLUME-weighted | 8.872442 | Crossfit_Hanna | 8.87 | no |

Only **H1** matches. Two distinct semantic choices have to land correctly
for gold:

1. **Weighting**: volume-weighted, not count-weighted.
2. **Aggregation order**: pool numerator and denominator over the full window
   first, then divide — not "compute ratios per sub-window, then average".

### 2.4 Sonnet 4.6 as spec agent (pilot run, 2026-05-21)

Sonnet's spec for task 17:

```
question_summary: "Fraud rate is defined as the ratio of fraudulent volume
                   over total volume (from section 7) ..."
computation_plan step 3: "For each (merchant, month) group compute:
                          total_volume = sum(eur_amount);
                          fraud_volume = sum(eur_amount where has_fraudulent_dispute == True)"
computation_plan step ~: "compute monthly fraud rate per merchant per month,
                          then average across months"
```

Kimi faithfully executed this spec.

**Result**: `8.894813` — **rounds to 8.89, fails gold tolerance (8.91)**.

What Sonnet got right:
- Surfaced the docs-defined volume-weighted formula verbatim (meta-rule #2 fired).
- Picked the correct merchant (Crossfit_Hanna).

What Sonnet got wrong:
- Added a monthly granularity that is nowhere in the docs.
- Computed "mean of monthly ratios" instead of "single pooled annual ratio".
- The word "average" in the question triggered Sonnet to introduce a temporal
  sub-bucket that doesn't exist in the docs definition.

### 2.5 Opus 4.7 as spec agent (follow-up run, 2026-05-21)

To test whether a more capable planner would close the gap, we re-extracted
the spec with `claude-opus-4-7` (identical prompt, single-task pilot,
`results/v23_task17_opus/`).

Opus's spec, full `notes_for_executor`:

> *Manual section 7: 'Fraud is defined as the ratio of fraudulent volume over
> total volume.' The question asks for the LOWEST avg fraud rate per merchant
> in 2023. Compute per-merchant fraud rate (fraction of fraudulent transactions),
> then return the minimum. ... Note: 'fraudulent volume' could also be
> interpreted as sum(eur_amount where has_fraudulent_dispute) / sum(eur_amount).
> **Default to count-based ratio (mean of has_fraudulent_dispute), but verify
> if executor finds ambiguity.***

Opus's computation_plan step 4:

> *For each merchant, compute fraud rate = sum(has_fraudulent_dispute) /
> count(\*) — this gives the average fraud rate per merchant*

Kimi executed:
```python
fraud_rate = df_2023.groupby('merchant')['has_fraudulent_dispute'].mean()
```

**Result**: `7.683437` — wrong merchant (Golfclub_Baron_Friso), categorically
off, well outside scorer tolerance.

What Opus got right:
- Surfaced the docs-defined volume-weighted formula in notes.
- Explicitly named the volume-vs-count ambiguity in prose.
- Got the aggregation ORDER right (no spurious monthly granularity).

What Opus got wrong:
- Quoted the volume-weighted definition then **chose count-weighted as
  the default**.
- The hedge "but verify if executor finds ambiguity" placed the burden
  on the executor — and Kimi did not escalate.

### 2.6 GPT-5.5 as spec agent (follow-up run, 2026-05-21)

For a third data point we re-extracted the spec with `openai/gpt-5.5` via
OpenRouter (`results/v23_task17_gpt55/`). Same task, same executor, same
system prompt.

GPT-5.5's computation_plan (abridged to the key steps):

> *Step 3: Use the manual's fraud definition: fraud is the ratio of fraudulent
> volume over total volume. Therefore **do not** compute a transaction-count
> mean of has_fraudulent_dispute; compute a euro-volume ratio.*
>
> *Step 5: Group by merchant — agg(total_volume=sum('eur_amount'),
> fraudulent_volume=sum('fraudulent_volume_component')).*
>
> *Step 7: per_merchant['fraud_rate'] = fraudulent_volume / total_volume.*
>
> *Step 8: Return the lowest per-merchant fraud rate. **Interpret 'avg fraud
> rate per merchant' as the annual per-merchant fraud rate over all 2023
> volume, because the docs define fraud rate as a volume ratio and the
> question does not request monthly averaging.***

Kimi executed it faithfully.

**Result**: `8.907926%` → rounds to `8.91`, **PASSES gold**.

Notable structural differences in GPT-5.5's spec:

1. **Anti-pattern call-out (step 3)** explicitly forbids the count-mean
   interpretation — pre-empts Opus's failure mode.
2. **Aggregation-order disambiguation (step 8)** explicitly addresses the
   "monthly average" reading and rejects it with a doc-grounded argument —
   pre-empts Sonnet's failure mode.
3. **Generated 12 plan steps** (vs Sonnet 7, Opus 7) — significantly more
   granular, including separate branches for empty result, irrelevant fee
   rules, and missing columns.

GPT-5.5 wrote a **defensive** spec; Sonnet and Opus wrote **permissive**
specs that allowed the failure modes through.

### 2.7 Side-by-side

| Planner | Surfaced formula? | Used surfaced formula? | Aggregation order | Result | Gap to gold |
|---|---|---|---|---|---|
| Sonnet 4.6 | yes (volume) | yes | wrong (monthly mean) | 8.894813 | -0.013pp |
| Opus 4.7 | yes (volume) | **no** (substituted count) | right | 7.683437 | -1.23pp, wrong merchant |
| **GPT-5.5** | **yes (volume)** | **yes + anti-pattern call-out** | **right (pooled annual + explicit rejection of monthly)** | **8.907926%** | **0 — PASS** |
| Gold (H1) | — | volume-weighted | pooled annual | 8.907926 | — |

**Sonnet and Opus** showed definition-shift, in different forms:
- Sonnet: surfaced and weighted correctly, then overlaid a non-docs aggregation.
- Opus: surfaced correctly, then substituted a non-docs weighting at code time.

**GPT-5.5** avoided both failure modes by writing the spec defensively —
naming the specific bad interpretations and instructing the executor not
to use them. This is the same docs and the same generic meta-rules; only
the planner changed.

### 2.8 Did the review apparatus catch it?

The `ask_spec_agent` review tool was available to Kimi in all three runs.
Kimi did **not** invoke it on task 17 in any of them — the spec text always
read coherent enough to push through without escalation.

Even with Opus's explicit hedge ("verify if executor finds ambiguity"),
the executor pushed through. Kimi's prior is to execute the spec it was given
rather than to ask. On other pilot tasks (1453, 1739) Kimi did escalate, and
the spec agent's `read_file`-based verification fired correctly — but on
task 17 it stayed silent.

This suggests definition-shift is hard to catch from the executor side:
when the spec text reads coherent and matches the executor's prior, there
is no surface uncertainty to trigger an escalation.

---

## 3. The pattern across 93 tasks

Definition-shift is one of eight bug families we identified in the 93-task
deep failure analysis (`harness/analysis/kimi-k2.6/verified_per_task_diagnosis.md`).
Quantitatively:

| Bug | Count | Data-verified |
|---|---|---|
| `fraud_rate_definition_volume` | 4 | yes — task 17, others reproduced |
| `fraud_rate_definition_volume_scheme_max` | 1 | yes |
| `fraud_rate_definition_volume_q3` | 1 | yes |
| `reference_avg_per_email_mean` | 1 | yes |
| `multiple_choice_wrong_pick` | 1 | hypothesised |
| **Family 2 total** | **8** | mostly verified |

That is ~9% of the failure set, comparable in size to the more-discussed
null-as-wildcard family (28 tasks). And definition-shift is more insidious
than null-handling because:

- Null-handling produces a visible miscount (the executor sees their filter
  drops rows and may notice).
- Definition-shift produces a coherent-looking number from a coherent-looking
  formula. There is no internal inconsistency to alarm on.

### 3.1 Representative cases beyond task 17

- **Task 17 / 19 / 58 (fraud rate)**: volume-weighted in docs, count-weighted
  in default pandas. Documented above.
- **Task 43 (per-email reference fee)**: docs define "average fee per email"
  as `sum(fees) / count(unique emails)`; Kimi computes `mean(fees per email)`.
  Mathematically identical only if every email has equal transaction count.
- **Family-adjacent (counted in benchmark-ambiguity, but related)**: a few
  "most expensive MCC" tasks where the docs are silent on aggregation order
  across rules.

The unifying signal: the question uses an unqualified metric name ("fraud
rate", "average fee per X"), the docs define the metric one specific way,
and the model defaults to the pandas-natural computation.

---

## 4. Why this is a real problem in agentic data analysis

### 4.1 Beyond DABStep

DABStep is a fee/transaction benchmark, but the failure structure is generic.
Wherever an analysis task involves:

- A named metric that the source documentation defines with specific
  numerator/denominator/weighting/aggregation rules
- And the question phrasing does not explicitly remind the agent of the
  custom definition

...we expect definition-shift to occur. Likely affected domains:

- **Financial analysis**: "ROI", "churn rate", "ARPU", "gross margin" —
  every accounting standard has a precise definition; pandas defaults
  rarely match.
- **Healthcare analytics**: "case fatality rate" vs "mortality rate"; the
  WHO definition differs from the colloquial one; an LLM will pick the
  colloquial one even after reading WHO docs.
- **Marketing**: "conversion rate" can mean several different ratios;
  product-spec docs define one; the LLM defaults to another.
- **A/B testing**: relative lift vs absolute lift; pooled vs stratified.

The pattern is structural, not benchmark-specific: docs encode domain
convention, models encode pandas convention, and reading the docs does
not transfer the convention to code.

### 4.2 Why "just read the docs harder" does not work

Our pilot data shows that:

1. Both Sonnet and Opus **did** read manual.md before writing the spec.
2. Both **did** quote the volume-weighted definition in their spec output.
3. Both **then wrote a different formula in the computation_plan** (Sonnet
   added granularity; Opus inverted to count-weighted).

This is the surprising part. The models can surface the rule in prose but
cannot reliably propagate it through to the code-generation step. It's a
prose-to-code translation failure, not a reading-comprehension failure.

### 4.3 Why bigger models can be worse

Opus's failure is more total than Sonnet's. We hypothesise that more
capable planners are more willing to "interpret" ambiguous wording. Opus
saw the question phrase "average fraud rate" and reasoned that the user
probably meant `mean(has_fraudulent_dispute)`, then over-rode the docs.
Sonnet stayed closer to the docs formula but introduced a granularity
choice that wasn't grounded.

Both behaviors are *plausible reasoning under ambiguity*. The problem is
that the docs are not actually ambiguous — section 7 defines fraud rate
unambiguously — but the question phrasing creates apparent ambiguity, and
the models resolve it against the docs rather than for them.

### 4.4 Why review apparatuses do not catch it

The `ask_spec_agent` review mechanism in grafting_v2 fires when the
executor is uncertain. Definition-shift produces specs that look certain
because the surface text is well-formed. The executor has no signal to
escalate. We observed this directly on task 17 with both planners.

This generalises: any "ask if unsure" mechanism is gated on the executor's
calibrated uncertainty. When the executor has no internal contradiction,
no uncertainty signal fires, no escalation happens. Definition-shift is
specifically the failure mode where the spec is coherent-but-wrong, so
the executor cannot detect it.

---

## 5. Root cause hypotheses

We do not have definitive root cause yet. Three hypotheses, in order of
plausibility based on the evidence:

### H-Prior dominance
LLMs have a strong prior over what "fraud rate" / "conversion rate" /
"average X" means in pandas/SQL idiom. Reading a docs passage that says
otherwise updates the model's prose ("the docs say volume-weighted") but
does not update the model's code-generation distribution ("when writing
pandas, I write `.mean()`"). The two channels are not aligned.

This matches the observation that the model can quote the doc and then
write code that contradicts the quote.

### H-Question phrasing override
The natural-language phrasing of the question ("average X per Y") supplies
a stronger prior than the docs definition. Phrases like "average", "rate",
"per merchant", "fraction of" each have default pandas mappings. When
question phrasing and docs definition conflict, the question wins. This
fits Opus's explicit choice (count-based default, "verify if ambiguous").

### H-No mechanism for "metric definition" as a first-class object
The spec format treats `question_summary`, `computation_plan`, `notes_for_executor`
as separate fields. A formula can appear in `notes` (as quote) and a
different formula in `computation_plan` (as code) without any consistency
check. There is no slot in the spec schema for "the canonical computation
of metric X, locked in", and no mechanism that forces `computation_plan`
to derive from the surfaced formula.

This is testable: if we add a `metric_definitions` field to the spec
schema and require `computation_plan` steps to cite specific metric
definitions, we can mechanically check consistency.

---

## 6. What we have tried

| Intervention | Effect on task 17 | Cost |
|---|---|---|
| Generic meta-rules in spec prompt ("surface docs-defined formula") | Surfaced but not applied (Sonnet/Opus) | included in base spec extraction |
| Larger spec agent (Sonnet → Opus) | Worse (different failure) | +0.087 USD per task |
| Different model family (Sonnet → GPT-5.5) | **Fixed** | $0.075 per task |
| Review apparatus (ask_spec_agent + read_file) | Not invoked by executor | 0 (not triggered) |

The cross-family planner swap (Sonnet/Opus → GPT-5.5) is the only intervention
that fixed the task. This is a one-task result and could be a model-specific
behavior or a stylistic difference in how the prompt was followed. Needs
validation across the rest of Family 2 (the other 7 definition-shift tasks)
before claiming planner choice is *the* solution.

What we have **not** yet tried:

- A meta-rule explicitly addressing ratio-aggregation order ("mean of ratios
  ≠ ratio of means; aggregate numerator and denominator over the full
  window before dividing").
- A spec-schema change adding a `metric_definitions` slot with
  cross-field consistency.
- Forcing the executor to escalate at least once on tasks involving
  named metrics defined in docs.
- An adversarial/self-critique pass where the spec agent re-reads its
  own spec and explicitly checks whether `computation_plan` derives from
  `notes_for_executor`.

---

## 7. Open questions

1. **Is definition-shift a calibration problem or a structural one?** If we
   could give the spec agent ground truth labels for "this metric is
   volume-weighted, not count-weighted" on a training set, would it
   generalise? Or does the bug live in the LLM's code-generation circuit
   regardless of supervision?

2. **Does it scale with task complexity?** Task 17 has one metric ("fraud
   rate"). Tasks with two or three named metrics (some defined, some not)
   may show worse rates because the spec agent has more places to slip.

3. **Is there a difference between docs-defined-once vs docs-defined-
   repeatedly?** Manual.md mentions fraud once in section 7. If the
   definition were repeated in multiple sections, would the spec agent
   weight it more heavily? Or does the bug not depend on doc frequency?

4. **Can a spec-level diff tool catch it?** If we generated specs from
   both Sonnet and Opus and surfaced disagreements ("Sonnet says volume-
   weighted with monthly mean; Opus says count-weighted"), an ensemble
   layer could flag the metric as a high-risk one and trigger mandatory
   docs re-read. We have not tested this.

---

## 8. References

- `analysis/kimi-k2.6/verified_per_task_diagnosis.md` (in the harness repo):
  the 93-task failure analysis, including the verified_failures_v4 categorisation.
- `results/v23_pilot5/specs/17.json`: the Sonnet spec for task 17.
- `results/v23_pilot5/17/sessions/normal_agent.jsonl`: Kimi's execution trace
  with the Sonnet spec.
- `results/v23_task17_opus/specs/17.json`: the Opus spec for task 17.
- `results/v23_task17_opus/17/sessions/normal_agent.jsonl`: Kimi's execution
  trace with the Opus spec.
- `results/v23_task17_gpt55/specs/17.json`: the GPT-5.5 spec for task 17 (the
  defensive spec that passed).
- `results/v23_task17_gpt55/17/sessions/normal_agent.jsonl`: Kimi's execution
  trace with the GPT-5.5 spec.
- `analysis/reference/dabstep_official_grader/scorer.py`: the DABStep
  scoring function (numeric tolerance: `min(decimals)` rounding plus
  `rel_tol=1e-4 / abs_tol=1e-4` `isclose`).

---

## 9. Reproducing the results in this doc

```bash
cd /Users/suraj/Downloads/grafting_v2

# Sonnet spec + Kimi run
python3 scripts/extract_specs.py \
    --tasks data/target_task17.jsonl \
    --extractor anthropic:claude-sonnet-4-6 \
    --out results/repro_sonnet/specs

python3 scripts/build_dataset.py \
    --tasks data/target_task17.jsonl --mode grafted \
    --specs results/repro_sonnet/specs \
    --out results/repro_sonnet/tasks.jsonl

npx tsx src/run.ts \
    -d results/repro_sonnet/tasks.jsonl \
    -c configs/kimi_grafted_iterative.yaml \
    -o results/repro_sonnet \
    --specs results/repro_sonnet/specs \
    -n "repro task17 Sonnet planner"

python3 scripts/grade.py --out results/repro_sonnet --gold data/verified_answers.json

# Opus spec + Kimi run
python3 scripts/extract_specs.py \
    --tasks data/target_task17.jsonl \
    --extractor anthropic:claude-opus-4-7 \
    --out results/repro_opus/specs
# (then build / run / grade with configs/kimi_grafted_iterative_opus_planner.yaml)
```

---

## Appendix A — Verification script for the H1–H5 candidate computations

```python
import pandas as pd
from pathlib import Path

DATA = Path("/Users/suraj/Downloads/harness/sandbox/dabstep-data/data/context")
df = pd.read_csv(DATA / "payments.csv")
df_2023 = df[df['year']==2023].copy()
df_2023['date'] = pd.to_datetime(
    df_2023['year'].astype(str)+'-'+df_2023['day_of_year'].astype(str),
    format='%Y-%j'
)
df_2023['month'] = df_2023['date'].dt.month
df_2023['fraud_amt'] = df_2023['eur_amount'].where(df_2023['has_fraudulent_dispute'], 0.0)

# H1 — pooled annual volume-weighted (matches gold)
agg = df_2023.groupby('merchant').agg(
    fraud_vol=('fraud_amt','sum'),
    total_vol=('eur_amount','sum'),
)
agg['vol_rate'] = agg['fraud_vol'] / agg['total_vol'] * 100
print("H1 min:", agg['vol_rate'].idxmin(), agg['vol_rate'].min())
# → Crossfit_Hanna 8.907926

# H3 — monthly-then-mean (what Sonnet/Kimi produced)
monthly = df_2023.groupby(['merchant','month']).agg(
    fv=('fraud_amt','sum'), tv=('eur_amount','sum')
).reset_index()
monthly['vol_rate'] = monthly['fv'] / monthly['tv']
mm = monthly.groupby('merchant')['vol_rate'].mean() * 100
print("H3 min:", mm.idxmin(), mm.min())
# → Crossfit_Hanna 8.894813
```
