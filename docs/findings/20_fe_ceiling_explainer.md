# The F-E ceiling: what it is, when it hits, how to mitigate it

Internal engineering explainer for the KramaBench results. Audience: has read the paper draft, needs the operational picture.

## What "F-E" stands for

F-E is the fifth entry (alphabet position E) in the internal harness-vs-model failure taxonomy first written down in `01_harness_vs_model_failure_modes.md` (F-A through F-E). It originally stood for the literal pattern observed there: **executor and planner agree (an Equivalence between the two cascade agents) on the same wrong answer**. The paper repurposes the label and re-glosses it more precisely:

> "F-E: cascade consensus on a plausible-but-wrong interpretation"
> (`paper/scribe.tex` line 415)

Read it as **Frame-Equivalent**: the spec, the executor, and the reviewer share one self-consistent *frame* for the question; the answer is wrong only relative to the *task author's* frame. Inside the harness everything looks right, because every cascade agent is reasoning inside the same wrong frame.

## Mechanical definition

F-E describes the regime where all four of the following hold simultaneously:

1. The `spec_agent` picks a defensible interpretation of an ambiguous question.
2. The `executor` implements that interpretation correctly.
3. The `planner_agent` (reviewer) verifies the executor's result is consistent with the spec.
4. The committed answer is still wrong, because the chosen interpretation is not the one the task author meant.

None of the five (or six, counting `SPEC_DOUBT`) cascade verdicts has the authority to second-guess (1). The cascade can only check internal consistency, and on F-E tasks internal consistency is satisfied by the wrong frame. Quoting the paper verbatim:

> "None of the five (or six, with SPEC\_DOUBT) cascade verdicts has authority to second-guess this."
> (`paper/scribe.tex` line 415)

## How we originally identified it (three-stack convergence)

We isolated F-E with the ablation in Table VII of the paper (`paper/scribe.tex` lines 384–405), running three independently configured stacks on the five hardest Krama-archeology tasks. Each stack swaps one role to a different model family so that no two stacks share spec, planner, or executor model:

- **v2:** GPT-5 spec+planner with Kimi-K2.6 executor.
- **v3:** DeepSeek-V3.1 spec+planner with Qwen3-Coder-30B executor.
- **v3b:** DeepSeek-V3.1 spec+planner with Kimi-K2.6 executor.

The load-bearing observation is `archeology-hard-9`, where the gold answer is **+0.015648** and all three stacks return **identical** **−0.210104** to six decimals:

| Task    | Gold        | v2 (GPT-5+Kimi) | v3 (DS+Qwen) | v3b (DS+Kimi) |
|---------|-------------|-----------------|--------------|---------------|
| hard-9  | +0.015648   | −0.210104       | −0.210104    | −0.210104     |

(`paper/scribe.tex` line 396, with caveats on lines 403–404)

This is a sign flip plus ~13× magnitude error. The fact that three families with no shared model converge on the *same* wrong number to six decimals means the gap is **upstream of any cascade verdict**: each spec_agent commits to the same plausible reading (Barrington Atlas rank = ordinal importance instead of inverse-ordinal importance), and the cascade then verifies inside that reading.

We additionally tested cascade-level interventions and confirmed none of them flip an F-E verdict:

- **I-1 question-restating gate** (`interpretations[2-4]` plus `chosen_interpretation` in the spec). Active in v3, v3b. Did not flip hard-9.
- **SPEC_DOUBT** (sixth cascade verdict that lets the reviewer switch to a listed alternative interpretation). Never fired on hard-9 — the planner had no doc passage to ground a dissent.
- **Multi-spec sampling** (three stances per task: most-literal, most-conventional, most-strict). On seven tasks adjudicated, zero flipped to PASS; three of seven had unanimous wrong-answer convergence across all three stances. (`paper/scribe.tex` line 413)

These three negative results are what justify the paper's "architectural ceiling" framing: F-E is not a tuning problem, it is a property of where the cascade can and cannot get evidence.

## F-E broken: what just happened with Opus 4.7

We re-ran the same KramaBench hard subset with **Claude Opus 4.7 across all three roles** (spec, executor, reviewer), single-pass, no re-extraction. Results from `_opus_failure_index.json` cross-referenced against `results/krama_opus_104/official_scores_v2/`:

### Archeology hard — ceiling holds

Opus 4.7: **1/6 pass** (only `archeology-hard-7` flipped to PASS). The five failures are `hard-1, 2, 5, 9, 12`.

Critically, **`archeology-hard-9` still produces exactly −0.210104** (Opus raw answer, `_opus_failure_index.json` line 100). Same number, same sign flip, same six-decimal match against v2/v3/v3b. **F-E ceiling holds on archeology hard.**

The one task that did flip (`hard-7`) is the cleanest in the bunch: "count modern cities with population > 100,000 that lie within 0.1 degrees of any ancient Roman-era city" — a mechanical join question with no interpretation ambiguity. It was bounded by spec-mechanical issues, not F-E.

### Astronomy hard — ceiling partially broken

DeepSeek-V3.1 run: 0/6 on astronomy hard (per `results/krama_all104/official_scores/astronomy/summary.json` — `hard-7, 8, 9, 10, 11, 12` all zero).

Opus 4.7: **3/6 pass** — `astronomy-hard-7`, `astronomy-hard-10`, and `astronomy-hard-11` all flipped to PASS. The three remaining failures are `hard-8`, `hard-9`, `hard-12`.

The tasks that flipped:

- **hard-7:** Train a VAR(1) density prediction model using OMNI2 (F10.7, Kp, Dst) and GOES X-ray flux as features.
- **hard-10:** Compute Swarm-A hourly altitude changes from POD SP3 files, align to OMNI2 hourly variables and Sat_Density, find max Pearson correlation.
- **hard-11:** Run **NRLMSISE-00** atmospheric model for Swarm-B throughout 2024, driving it with F10.7/F10.7A/Ap, compare predicted vs POD-derived density via RMSE.

These are mainstream space-physics / orbit-mechanics workloads. **F-E ceiling broken on astronomy.**

## Why it broke on astronomy but not archeology

A defensible hypothesis (not overclaimed, since n=6 per domain):

**F-E severity is a function of two factors operating jointly:**

1. **The interpretation is implicit in the domain** — no source document the cascade can read disambiguates it. (Both archeology and astronomy hard satisfy this.)
2. **The interpretation is not well-represented in pre-training corpora** — the model family has no internal prior to fall back on. (Archeology satisfies this; astronomy does not.)

Astronomy hard-7/10/11 lean on mainstream scientific computing: NRLMSISE-00 (a 1990s NRL atmospheric model with extensive documentation in the open literature), Swarm Precise Orbit Determination, OMNI2 space-weather indices, VAR(1) modeling. Any frontier model trained on broad scientific text has dense representations of these conventions — what "predicted density" means, what RMSE is comparing, how to align SP3 epochs to hourly OMNI2 cadence. The spec_agent's "plausible interpretation" tends to *coincide* with the task author's intent, because both are drawing from the same well-trodden conventions.

Archeology hard-9 leans on the opposite: the **Barrington Atlas inverse-rank convention** (low rank = more important, an inversion specific to that one atlas), radiocarbon BP-versus-calibrated-years semantics on hard-5, conflict-deduplication-by-name-and-year on hard-12. These conventions are not in any data source the spec_agent reads, AND they are not common-scientific-knowledge prior. So a stronger model family cannot route around them by recall — it just produces the same defensible-but-wrong frame faster and more articulately.

The refined claim: **F-E is severe when the missing interpretation is (a) document-implicit AND (b) training-corpus-thin.** Stronger spec/reviewer models erode F-E on (b) but not on (a).

## How to fix F-E (path forward)

Ordered by architectural honesty for the deepest F-E cases:

1. **Sub-task gold (KramaBench-style intermediate checkpoints).** Many KramaBench tasks ship intermediate ground-truth artifacts (e.g., "the intermediate dataframe should have these N rows"). A `verify_step` tier that checks against these would catch the wrong frame **mechanically** rather than via cascade consensus. This is the only honest path for archeology-hard-9: there is no way for any cascade verdict to know the Barrington rank is inverse without external ground truth. The paper marks this as the empirical next step (`paper/scribe.tex` lines 415, 439).
2. **Domain-knowledge layer above the cascade.** A `knowledge_base.md` (or extension to `HELPER_MANIFEST`) loaded into the spec_agent's context whenever a task is tagged with a convention-heavy domain, encoding the conventions explicitly: "Barrington Atlas rank is inverse-importance," "radiocarbon dates in this column are uncalibrated BP." This is a maintenance burden but it short-circuits F-E on the specific known conventions.
3. **Stronger spec_agent model family.** What the Opus 4.7 result demonstrated: a model with denser training-corpus coverage of the domain partially escapes F-E on astronomy. Necessary but not sufficient — it does not help on archeology hard, and even on astronomy it is 3/6 not 6/6.
4. **Question-restating with a human-in-the-loop stakeholder check.** For production deployments where stakes are high, surface the `interpretations[]` array to a human before the executor commits. This catches F-E by externalizing the disambiguation step, but it is not an architectural fix — it just moves the work to a human.

For pure F-E like `archeology-hard-9`, **none of (2), (3), or (4) purely-architectural moves will work in isolation.** Sub-task gold (or some equivalent external ground-truth grounding) is the only honest mitigation. (3) extends the regime where F-E is escapable but does not eliminate the regime where it is not.

## How to detect F-E in practice

Operational signals (from the v2/v3/v3b ablation and the Opus run):

- The spec reads coherent on first inspection and the `interpretations` array is populated but the chosen interpretation does not pin down a value the task author would call obviously correct.
- The cascade emits `[Verdict: ANSWER]` with no `SPEC_DOUBT` and no SPEC_WRONG revisions.
- Multiple independent stacks (different model families) converge on the **same wrong number to many decimals**. This is the strongest possible F-E signature: identical wrong answers across stacks rule out per-stack bugs and isolate the failure to the question-frame translation.
- The task domain is convention-heavy: archeology, astronomy, geology — anywhere the question's intended interpretation lives in implicit field convention rather than in source documents.

## What this means for the paper

- The **three-stack convergence claim still holds**. v2, v3, v3b all produced −0.210104 on `archeology-hard-9`; that has not changed. The paper's load-bearing evidence for "the gap is upstream of any cascade verdict" survives.
- A **fourth, single-model stack (Opus 4.7 throughout)** is now available and demonstrates F-E is **partially escapable** on some domains. Worth a sentence noting this if the draft is updated: "A single-model Opus 4.7 stack escapes F-E on 3/6 astronomy hard tasks but reproduces the identical −0.210104 on archeology-hard-9, consistent with the document-implicit-AND-training-corpus-thin characterization."
- **Do not oversell the break.** The deepest F-E cases — where the missing interpretation is not in any document AND not in any training corpus — remain bounded. The architectural ceiling is real; it just shifts position with model family. The published claim (cascade-level interventions don't flip F-E verdicts) is unchanged; the new claim (model-strength interventions flip *some* F-E verdicts in *some* domains) is additive.
- The Limitations note at `paper/scribe.tex` line 443 should arguably be expanded: "(ii) Memorization is not stripped on KramaBench; the F-E ceiling claim should be retested under obscured inputs" — because the Opus astronomy lift could be partially memorization-driven, and the obscured-input retest is the cleanest way to separate "Opus knows NRLMSISE-00" from "Opus saw this task."

## TL;DR for the on-call engineer

If you see a SCRIBE deployment producing a wrong answer with a clean cascade transcript and no escalations, and the wrong answer is **stable across model swaps**, you are looking at F-E. The fix is not in the harness. Either (a) provide sub-task gold for that task class, (b) ship an explicit conventions document to the spec_agent, or (c) accept the ceiling for that domain and route those questions to a human.

## Related artifacts

- `/Users/suraj/Downloads/scribe/paper/scribe.tex` §7 (`sec:paradigm-fit`, lines 371–415) — published F-E discussion and Table VII three-stack ablation
- `/Users/suraj/Downloads/scribe/docs/findings/01_harness_vs_model_failure_modes.md` — original F-A through F-E taxonomy
- `/Users/suraj/Downloads/scribe/docs/findings/17_pilot_v2_diagnosis.md` — first F-E-dominance diagnosis with intervention sketches
- `/Users/suraj/Downloads/scribe/docs/findings/18_krama104_results.md` — DS-V3.1 + Kimi-K2.6 full-104 run that produced the original archeology/astronomy ceilings
- `/Users/suraj/Downloads/scribe/docs/findings/_opus_failure_index.json` — Opus 4.7 single-pass failure records (this run)
- `/Users/suraj/Downloads/scribe/results/krama_opus_104/official_scores_v2/{archeology,astronomy}/summary.json` — per-task pass map for the Opus run
- `/Users/suraj/Downloads/scribe/results/krama_all104/official_scores/{archeology,astronomy}/summary.json` — DS-V3.1 baseline per-task pass map for comparison
