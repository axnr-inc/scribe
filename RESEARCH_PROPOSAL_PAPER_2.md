# Research Proposal — Paper 2 (Applied Track / Comprehensive Experimental Analysis)

**Working title:** *An Empirical Failure-Mode Taxonomy of LLM Agents on Docs-Heavy Data Analysis: Capability Ceilings and Architecture-Sensitive Recoveries Across Three Benchmarks*

**Target venue:** ICDM 2026 Applied Track — "Comprehensive experimental analysis" category
**Track:** Applied Paper (10 pages IEEE 2-column)
**Status:** New paper. Builds on existing failure analysis in `scribe-supplement.tex` S1-S6 and `livesqlbench/EXPERIMENT_FINDINGS.md`.

---

## 1. Central thesis (one sentence)

> *We present an empirically-validated taxonomy of 13+ failure families for LLM agents on docs-heavy data analysis tasks, classified by per-family verdict — model-bound (capability ceiling) or architecture-fixable (specific role decompositions recover it) — validated across three benchmarks (DABStep, LiveSQLBench, Kramabench) and four open-source executor models.*

The paper does **not propose a new method**. The contribution is the taxonomy,
the per-family verdicts, the cross-benchmark transfer evidence, and the
architecture-sensitivity analysis. This is exactly what ICDM Applied Track #4
("Comprehensive experimental analysis") solicits: *"providing new fundamental
insights into the strengths and weaknesses of existing methods."*

---

## 2. Why this paper exists

The agent-research community has many proposed architectures (DS-STAR, NVIDIA
NeMo KGMON, OceanBase DataPilot, SCRIBE, CMU primitive induction) but no
shared framework for *understanding when each works*. Researchers report
leaderboard numbers but rarely diagnose which failure modes their architecture
addresses and which it doesn't. Practitioners deploying these systems lack
a guide for picking the right architecture for their failure profile.

We close this gap by:
1. Defining a mechanism-based failure taxonomy applicable across architectures
2. Measuring per-family pass rates across four architectures and three benchmarks
3. Assigning a verdict per family: AF (architecture-fixable) or MB (model-bound)
4. Releasing per-task labels, traces, and re-runnable scripts so any new
   architecture can be evaluated against the same taxonomy

---

## 3. Pre-existing assets we leverage

| Asset | Source | Volume |
|---|---|---|
| 13 residual failure families (F1-F13) on DABStep | scribe-supplement.tex S5 | 184 hard tasks |
| 8 Kimi-solo bug families (F1-F8) on DABStep | scribe-supplement.tex S1 | 93 incorrect + 97 iter-capped |
| Per-task trace markdowns | analysis/kimi-k2.6/incorrect_traces/ | 95 detailed analyses |
| Per-task failure CSVs | analysis/kimi-k2.6/*.csv | 226 labeled tasks |
| 10 LiveSQL failure patterns (E1-E10) | livesqlbench/EXPERIMENT_FINDINGS.md | 20 tasks |
| 34 LiveSQL session traces (v1+v2) | livesqlbench/traces/ | 34 sessions |
| Cross-model comparison (Kimi vs Opus vs DeepSeek) | analysis/research_notes/05_opus_vs_kimi_capability_ceiling.md | 10 fee-rule tasks |
| Opus 4.6 vs Kimi capability gap | 100% vs 20% on fee-rule iter-capped | killer empirical fact |
| 595+ task runs across architectural variants | grafting_v2/results/ | multiple architectures |

**This is more raw material than most published failure-analysis papers have.**

---

## 4. The new experimental work needed

The pre-existing assets are strong on DABStep but thin on cross-benchmark
transfer and per-family causal attribution. Paper 2 requires the following
new experiments:

### E-Paper2-A: Mechanism-based re-labeling of 184 residual failures

**$0, 3 days analysis only.** Re-label every residual failure by mechanism
(not outcome). Current families like F3 ("most-expensive-MCC pick"), F4
("volume-vs-count weighting"), F6 ("counterfactual-MCC"), F7 ("scheme pick")
are outcome-based. Re-define as: *"the model selects element X from a set
without applying constraint Y stated in the docs"* — mechanism-based.

Resolves F1∩F13 overlap (~25 tasks double-counted). Closes "vague families"
reviewer attack. Produces taxonomy ready for verdict assignment.

### E-Paper2-B: Per-rule ablation matrix on hard-378

**~$200, 4 days.** For each of the 11 spec-extraction meta-rules:
- Run SCRIBE with that single rule disabled
- Measure pass rate on each of the 13+ families
- Apply McNemar's test for paired significance per family

Output: a 13-family × 11-rule matrix showing which rule fixes which family.
Provides causal attribution of harness components to failure families.

### E-Paper2-C: Cross-architecture comparison on DABStep hard-378

**~$500, 6 days.** Run the same 378 hard tasks through 4 architectures:
- Monolithic ReAct (Kimi solo, GPT-5 solo)
- Sequential decomposition (plan-then-execute, no review)
- SCRIBE (canonical, GPT-5/Kimi/GPT-5)
- SCRIBE + offline spec template library (Pillar 4 from Paper 1)

Label each failure by family. Per-family pass rate per architecture.
This is the verdict-assignment data: a family is AF if any architecture
recovers ≥50%; MB if no architecture exceeds 30%.

### E-Paper2-D: Multi-executor study (open-source orchestration claim)

**~$200, 4 days.** Hold SCRIBE spec/review fixed (GPT-5 at edges). Vary
executor among:
- Kimi-K2.6 (baseline)
- GLM-5.1 (similar size, different training)
- DeepSeek-V4 Pro (different family)
- Qwen3-27B (smaller, tests floor)

Per-family pass rate per executor. Identifies which families are
executor-model-sensitive vs. spec-driven. Critical evidence for the
"orchestration with open-source models" thesis.

### E-Paper2-E: Cross-benchmark transfer

**~$200, 5 days.** Apply the DABStep taxonomy as a lens on:
- LiveSQLBench (270 tasks, 18 schemas) — already partly done
- Kramabench (multi-modal data analytics)

Questions:
- Do the same 13 families appear?
- Which families are universal vs. benchmark-specific?
- Which architecture verdicts transfer (AF→AF, MB→MB) and which don't?

### E-Paper2-F: Capability ceiling scaling

**~$300, 4 days.** Extend the existing Kimi/Opus 10-task fee-rule comparison
to all 13 families:
- Identify 10-15 tasks per family
- Run Kimi solo, Opus 4.6 solo, GPT-5 solo, SCRIBE
- Per-family pass rates

Empirically isolates: which families are unfixed even by frontier-solo? Which
become AF only under role separation?

### E-Paper2-G: Pre-registered held-out replication

**~$50, 1 day (after E-Paper2-A through F).** Take the top-5 mitigations
from the resulting roadmap. Apply to a 50-task held-out slice never touched
during taxonomy iteration. Compare actual to predicted lift.

Defends against "test-set leakage" attack. Closes the loop on the supplement's
55-95 task recovery projection.

**Total Paper 2 experiment cost: ~$1,450, ~6 weeks wall-clock with parallelism.**

---

## 5. Hypothesis updating philosophy (replacing rigid pre-registration)

Per your point: research IS iterative hypothesis updating. We commit to:

1. **Document all predictions BEFORE experiments** (timestamp them) — this is
   not "pre-registration" in the falsifiability sense, but transparent recording
   of expectations so reviewers can see what we believed.
2. **Report actual vs. predicted in the paper** — wherever predictions were
   updated mid-experiment, explain why (new data, taxonomy refinement, etc.).
3. **Reserve E-Paper2-G as the kept-sealed slice.** Predictions on E-Paper2-G
   are made BEFORE the slice is touched and are not updated. This single
   pre-registered slice gives reviewers a falsifiability anchor without
   straitjacketing the rest.

This is honest research workflow, not rigid pre-registration.

---

## 6. Per-family verdict assignment rule

For each of the 13+ families:

| Verdict | Criterion |
|---|---|
| **AF (Architecture-Fixable)** | At least one architecture in {Sequential, SCRIBE, SCRIBE+library} achieves ≥50% pass rate on tasks in this family |
| **Partial AF** | Best architecture achieves 30-50% pass rate |
| **MB (Model-Bound)** | No architecture exceeds 30% pass rate, AND solo-Opus also fails majority |
| **BC (Benchmark-Caveat)** | Tasks have benchmark-level issues (KB inconsistency, non-standard SQL, output format gap) that no architecture can address — explicitly carved out |

This produces a per-family table that becomes the paper's central artifact.

---

## 7. Paper structure (10 pages, IEEE 2-col)

| § | Title | Pages | Content |
|---|---|---|---|
| 1 | Introduction | 0.75 | Problem: leaderboards without diagnosis. Contribution: taxonomy + verdicts |
| 2 | Methodology | 1.25 | Mechanism-based family definitions, verdict criteria, ablation protocol, cross-benchmark transfer protocol |
| 3 | Benchmarks and architectures | 1.0 | DABStep, LiveSQLBench, Kramabench characteristics; 4 architectures evaluated |
| 4 | Architecture-fixable failure families | 2.5 | F1, F2, F5, F8, etc. — per-family root cause, per-architecture recovery, ablation showing which rule fixes it |
| 5 | Model-bound failure families | 2.0 | F3, F6, F11 — per-family root cause, evidence even frontier-solo fails, capability ceiling per family |
| 6 | Cross-benchmark transfer | 1.0 | Which families appear across DABStep/LiveSQL/Kramabench; new families introduced by each |
| 7 | Multi-executor study | 0.75 | Open-source orchestration evidence — Kimi/GLM/DeepSeek/Qwen as executors |
| 8 | Held-out replication and limitations | 0.5 | E-Paper2-G results, taxonomy gaps, what's not in the analysis |
| 9 | Implications for practitioners | 0.25 | Concrete "use architecture X if your failure profile is dominated by family Y" guidance |
| Refs | | 0.5 | |

**Total: 10 pages exactly.**

---

## 8. The paper's central artifact (Table 4, conceptual)

| Family | Mechanism | Tasks | DABStep verdict | LiveSQL verdict | Kramabench verdict | Top fixing rule |
|---|---|---|---|---|---|---|
| F1 | Null-as-wildcard mishandling | 25 | AF | AF (E1) | TBD | R3 (non-default semantics) |
| F2 | Over-strict matching | 38 | AF | AF | TBD | R5 (filter explicitness) |
| F3 | Most-expensive-MCC pick | 10 | MB | n/a | n/a | none |
| F5 | Definition-shift | 15 | AF | AF (F-LiveSQL-4) | TBD | R1 (formula-to-code) |
| F6 | Counterfactual-MCC | 18 | MB | n/a | n/a | none |
| F-LiveSQL-3 | Multi-hop FK join error | n/a | n/a | AF | TBD | R9 (minimal table set) |
| ... | ... | ... | ... | ... | ... | ... |

This is the artifact every practitioner takes away from the paper.

---

## 9. Open questions for human author input

1. **Should the paper include CMU primitive induction** (arXiv 2606.02994) as
   a fifth architecture? They're orthogonal but adding them complicates the
   ablation matrix.
2. **NVIDIA NeMo KGMON's 89.95% on hard** — should we attempt to recreate
   their architecture as a 5th architecture row, to show even SoTA doesn't
   fix MB families? Cost: ~$200 extra. Likely controversial.
3. **OceanBase has no released code** — do we acknowledge them as related
   work without comparison numbers?
4. **Multi-executor study models** — confirmed: Kimi-K2.6, GLM-5.1,
   DeepSeek-V4 Pro, Qwen3-27B. Anything else?
5. **Pre-registration scope** — agreed: only E-Paper2-G is sealed. Rest is
   transparent iterative updating with predictions logged.

---

## 10. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Taxonomy doesn't transfer to LiveSQL/Kramabench | Medium | Reframe as "5 universal families + N benchmark-specific ones" |
| Per-rule ablation shows rules are too coupled to isolate | High | Pivot to "spec prompt is a holistic intervention" — still a contribution |
| All families end up AF (none MB) | Low | Unlikely given Opus vs Kimi capability gap evidence; if so, paper becomes "no model-bound families found, architecture wins" |
| Multi-executor study shows only Kimi works | Medium | Then paper conclusion shifts: "open-source orchestration works for specific executor families, not all" |
| Held-out E-Paper2-G shows zero recovery | Low | Honest reporting; reframe roadmap as ceiling not achievable |

---

## 11. Relationship to Paper 1

| Topic | Paper 1 | Paper 2 |
|---|---|---|
| Architecture description | Full SCRIBE design | Used as one of 4 architectures |
| Failure modes | 3 high-level (F-DefShift, F-ActBias, F-IterCap) + 3-4 example families | Full 13+ family taxonomy with verdicts |
| Cross-benchmark | DABStep + LiveSQL (zero-shot deployment claim) | DABStep + LiveSQL + Kramabench (taxonomy transfer) |
| Ablation | 8-cell role separation matrix | Per-rule × per-family ablation, multi-executor |
| Cost analysis | Cost per task, frontier vs executor tokens | Per-architecture cost-per-correct |
| Spec template library | Pillar 4 — generalization mechanism | One of 4 architectures in the comparative study |
| Held-out validation | LiveSQL zero-shot is the held-out check | Pre-registered E-Paper2-G slice |
| Reviewer concern addressed | "Methodology + dataset-agnostic deployment" | "Why does each architecture work and where does it fail" |

**The papers reinforce each other but each stands alone.** A reader of Paper 1
gets the method and validation. A reader of Paper 2 gets the comprehensive
empirical understanding. Cross-citations only, no shared headline claims.

---

## 12. Timeline (assuming both papers run in parallel)

Both papers' experiments overlap significantly (same DABStep runs serve both).
Coordinated experiment plan:

| Week | Paper 1 work | Paper 2 work | Shared |
|---|---|---|---|
| 1 | E-Paper1-1 (8 cells) | E-Paper2-A (re-labeling) | E-Paper1-1 outputs feed Paper 2 architectures |
| 2 | E-Paper1-2 (hidden test), E-Paper1-3 (LiveSQL) | E-Paper2-B (per-rule ablation) | LiveSQL results shared |
| 3 | E-Paper1-4 (5 seeds), E-Paper1-5 (spec library) | E-Paper2-C (cross-arch), E-Paper2-D (multi-exec) | Spec library is Paper 2's 4th architecture |
| 4 | Paper 1 draft Sections 1-5 | E-Paper2-E (Kramabench) | |
| 5 | Paper 1 draft Sections 6-9, polish | E-Paper2-F (capability ceiling) | |
| 6 | Internal review, submit Paper 1 | E-Paper2-G (held-out, pre-registered) | |
| 7 | — | Paper 2 draft Sections 1-5 | |
| 8 | — | Paper 2 draft Sections 6-9, polish | |
| 9 | — | Internal review, submit Paper 2 | |

Both papers can submit within 9 weeks if experiments succeed.
