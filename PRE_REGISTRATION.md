# Pre-Registration: SCRIBE Comprehensive Experimental Analysis (Paper 2)

**Filed:** 2026-05-31 (before any experiment in this batch is launched)
**Repository:** github.com/axnr-inc/scribe @ commit `[to be filled at file freeze]`
**Authors:** Anonymous (ICDM 2026 triple-blind submission)
**Target venue:** ICDM 2026 Applied Track — Comprehensive Experimental Analysis

This document commits to specific hypotheses, predicted outcomes, and analysis
plans BEFORE running E1-E6, the multi-executor study, and the cross-benchmark
study. It will be included verbatim as an appendix in the paper. The point is
falsifiability: the paper will report actual outcomes against these predictions,
including any that contradict our hypothesis.

---

## Central thesis

Docs-heavy LLM-agent failures on data-analysis benchmarks decompose into a
finite taxonomy of failure families. Each family is either:

- **Architecture-fixable (AF):** specific role decompositions (spec / executor /
  review) recover the family without changing the base model.
- **Model-bound (MB):** the family persists even with the strongest current
  frontier model, indicating a capability ceiling that no harness engineering
  bridges.

The taxonomy and the AF/MB verdicts generalize across at least one additional
docs-heavy benchmark beyond DABStep (LiveSQLBench or Kramabench).

---

## Pre-registered hypotheses

### H1 — Counterfactual on full DABStep dev (450 tasks)

**Prediction:**
- Kimi-K2.6 solo:        46% combined  (measured baseline, included for table consistency)
- Opus 4.6 solo:         58–66% combined  (with thinking=high, prompt_caching=on)
- GPT-5 solo:            55–63% combined
- SCRIBE (current):      59.8% combined  (measured)

**Implication if confirmed:** SCRIBE matches or beats Opus solo while spending
5x less per task. Frontier scale is not the right axis; orchestration is.

**Implication if falsified (Opus > 66% on combined):** Frontier scale wins
solo. The paper re-frames as: "SCRIBE matches frontier solo on combined accuracy
at 5x lower cost, AND wins on specific failure families X, Y, Z." The taxonomy
stands; the orchestration headline weakens.

### H2 — Per-rule ablation isolates causal contributions

For each of the 11 meta-rules in the spec-extraction prompt
(rules R1-R8 in current `extract_specs.py` + R9-R11 in
`extract_specs_livesql.py`), running SCRIBE with that single rule disabled will
cause a measurable drop on at least one specific failure family.

**Prediction:**
- R1 (formula-to-code translation) → primary driver of recovery for F1 (null-as-wildcard) and F2 (over-strict matching)
- R3 (non-default semantics) → primary driver for F5 (definition-shift)
- R5 (filter explicitness) → primary driver for F11 (fee-IDs list)
- R9 (minimal table set) → primary driver for F-LiveSQL-3 (multi-hop FK join error)
- R11 (per-entity pre-aggregation CTEs) → primary driver for F-LiveSQL-F3 (aggregation level error)

**Implication if confirmed:** Per-family verdicts in the paper are causally
attributed to specific harness components, not just correlated.

**Implication if falsified (no single rule isolates a single family):** The
spec prompt is a tightly-coupled artifact; mitigations cannot be cleanly
attributed. The paper reframes: "harness components are not independently
attributable; the spec prompt acts as a holistic intervention." Less satisfying
but more honest.

### H3 — Cross-benchmark transfer (DABStep → LiveSQLBench → Kramabench)

**Prediction:**
- At least 8 of the 13 families identified on DABStep will also appear on
  LiveSQLBench.
- At least 5 of the 13 will also appear on Kramabench.
- Each benchmark will contribute 1-3 new families not present in DABStep
  (e.g., LiveSQL's "JSON path ambiguity" is new).

**Implication if confirmed:** Taxonomy is a general lens for docs-heavy
agentic tasks, not a DABStep artifact.

**Implication if falsified (≤5 families transfer):** Taxonomy is partly
benchmark-specific. The paper reframes: "we identify 5 universal failure
modes and 8 benchmark-specific ones." Still a contribution.

### H4 — Open-source orchestration beats frontier solo (multi-executor study)

Holding the SCRIBE spec/review configuration fixed (GPT-5 at edges), swapping
the open-source executor among {Kimi-K2.6, GLM-5.1, DeepSeek V4 Pro,
Qwen3-27B} produces results that all beat Opus solo and GPT-5 solo on combined
DABStep accuracy.

**Prediction:**
- Kimi-K2.6 executor:   59.8% combined  (measured, our headline)
- GLM-5.1 executor:     56-62%
- DeepSeek V4 Pro:      54-60%
- Qwen3-27B executor:   48-54%  (smaller; tests the floor)

All four exceed predicted Opus solo (58-66%) and GPT-5 solo (55-63%) ranges?
Likely the top three (Kimi, GLM, DeepSeek). Qwen3-27B may not.

**Implication if confirmed:** "Open-source orchestration beats frontier solo"
is robust across executor choice, not Kimi-specific. Strong headline for
Paper 1.

**Implication if falsified (only Kimi works in SCRIBE):** SCRIBE has a
Kimi-specific quirk. The paper reframes as a Kimi+GPT-5 case study, not a
general orchestration claim. Paper 1 loses some punch; Paper 2 still has the
taxonomy.

### H5 — Held-out replication of mitigation roadmap

The roadmap in scribe-supplement.tex S5 projects 55-95 additional recoveries
on the 184 residual hard failures. We will pre-register the predicted lift on
a held-out 50-task slice never used during prompt iteration.

**Prediction:**
- Held-out 50 tasks sampled by stratified-random from the 184 residual.
- Baseline SCRIBE pass rate on this slice: predicted 0% (these are residual
  failures by definition) — actual will be measured because the spec
  prompt has evolved since the original failure measurement.
- After applying the top-5 mitigations from the roadmap: predicted +12 to
  +18 tasks recovered (24-36% of the slice).

**Implication if confirmed:** Mitigation roadmap is real, not a wish list.

**Implication if falsified (<8 recovered):** The roadmap was optimistic. The
paper reframes: "we measure the actual recoverable fraction at X%, below our
projected ceiling, suggesting some failure families are more capability-bound
than initially classified." Updates AF/MB verdicts accordingly.

### H6 — Mechanism-based re-labeling de-overlaps the taxonomy

The current taxonomy has F1 ∩ F13 overlap (~25 tasks counted in both). After
mechanism-based re-labeling, the 184 residual failures will deduplicate to
≤180 unique tasks across families, and family definitions will be mechanism-
based (not outcome-based) for F3, F4, F6, F7.

**Implication if confirmed:** Taxonomy is reviewer-defensible against
"vague families" attack.

**Implication if falsified (re-labeling introduces more ambiguity):** We
report the failure and present both labelings, letting reviewers judge.

---

## Predictions ledger (snapshot before experiments)

| Metric | Predicted | Actual | Δ |
|---|---|---|---|
| Opus 4.6 solo, DABStep combined | 58-66% | TBD | TBD |
| GPT-5 solo, DABStep combined | 55-63% | TBD | TBD |
| SCRIBE (Kimi exec), DABStep combined | 59.8% (measured) | 59.8% | 0 |
| SCRIBE (GLM exec), DABStep combined | 56-62% | TBD | TBD |
| SCRIBE (DeepSeek exec), DABStep combined | 54-60% | TBD | TBD |
| SCRIBE (Qwen3 exec), DABStep combined | 48-54% | TBD | TBD |
| Families transferring DABStep → LiveSQLBench | ≥8 of 13 | TBD | TBD |
| Families transferring DABStep → Kramabench | ≥5 of 13 | TBD | TBD |
| Held-out 50-task recovery (top-5 mitigations) | +12 to +18 | TBD | TBD |

---

## Analysis plan (committed before data collection)

1. **All accuracy numbers reported as point estimates with bootstrap 95% CIs**
   (1000 resamples). Single-seed numbers are not acceptable.

2. **Per-family verdict (AF or MB)** assigned by the following rule:
   - AF: at least one architecture variant in {SCRIBE, monolithic, sequential}
     recovers ≥50% of the family's failures.
   - MB: no architecture variant recovers ≥30% of the family's failures.
   - Mixed: 30-50% recovery → "partial AF" category.

3. **Per-rule ablation** uses leave-one-out: disable rule R_i, run SCRIBE on
   the full 450, measure pass-rate delta per family. Significance reported via
   McNemar's test (paired pass/fail).

4. **Cross-benchmark transfer** uses Jaccard similarity between family sets
   and per-family conditional pass rates.

5. **No post-hoc family invention.** Families are frozen at the start of
   experiments (after E6 re-labeling). Any new failure observed during E1-E5
   that doesn't fit an existing family is recorded as "unclassified" and
   reported as a residual count, not folded into a new family.

6. **Pre-registered held-out slice (E5) is sealed until experiment completion.**
   No prompt iteration, no spec re-extraction, no looking at the slice's
   failure traces until E1-E4 results are written.

---

## What invalidates the paper's contribution (kill criteria)

If any of these are observed, we will report the result and NOT submit Paper 2
in its current form:

- **K1:** ≥4 of 6 hypotheses falsified. Indicates the taxonomy lens is wrong.
- **K2:** Cross-benchmark transfer below 3 families (out of 13). Indicates
  DABStep-specific artifact.
- **K3:** Per-rule ablation shows zero rules with isolated effects. Indicates
  the spec prompt is an inseparable artifact and the paper has no causal claim.

In any of these cases, we will pivot to a single-benchmark case study with
honest negative-result framing, or absorb the analysis into Paper 1's
supplement and not submit Paper 2 separately.

---

## Reproducibility commitments

1. All experiment scripts will be under `experiments/` in the public repo.
2. Each experiment branch will contain a `run.sh` reproducing it from a clean
   checkout.
3. Random seeds will be fixed (`seed=42`) and reported in `summary.json`.
4. Raw session JSONLs will be released under `results/<experiment>/sessions/`
   (excluded from default git ignore for this paper).
5. Cost and wall-clock per task will be logged for every run.
