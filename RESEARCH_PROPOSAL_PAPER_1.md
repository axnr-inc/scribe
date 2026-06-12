# Research Proposal — Paper 1 (Research Track / Method Paper)

**Working title:** *SCRIBE: Spec-Conditioned ReAct with Inline Backreview Escalation — A Dataset-Agnostic Methodology for Docs-Heavy Agent Harnesses*

**Target venue:** ICDM 2026 Research Track (alternative: KDD 2026, NeurIPS Datasets & Benchmarks 2026)
**Track:** Regular Research Paper (10 pages IEEE 2-column)
**Status:** Redesign in progress. Original draft at `/Users/suraj/Downloads/scribe/paper/scribe.tex` to be substantially rewritten.

---

## 1. Central thesis (one sentence)

> *We present a dataset-agnostic methodology for designing docs-heavy agent harnesses, instantiate it as SCRIBE, and show that role-orchestrated zero-shot deployment matches learning-based systems on familiar benchmarks (DABStep) and outperforms them on unfamiliar ones (LiveSQLBench) — at a fraction of the per-task cost.*

The paper makes a **methodological claim** (failure-mode-driven harness design) and a **deployment claim** (zero-shot cross-schema generalization). The methodology produces a verifiable design discipline; the deployment evidence shows it works on benchmarks the methodology was never tuned to.

---

## 2. The problem we solve

Docs-heavy data-analysis tasks (DABStep, LiveSQLBench, Kramabench) require an
agent to read a manual/schema/KB, then write code/SQL against tabular data.
Three failure modes have been documented in literature (Lost-in-the-Middle,
Same-Task-More-Tokens, Self-RAG) but never explicitly mapped to harness-design
decisions:

- **F-DefShift:** model quotes docs correctly, writes contradicting code
- **F-ActBias:** model commits to interpretation without flagging ambiguity
- **F-IterCap:** model grinds past iteration budget without committing

Current leaders on DABStep (NVIDIA NeMo KGMON: 89.95% hard, OceanBase DataPilot,
DS-STAR) use **dataset-specific learning loops** — offline corpus mining to
build helper libraries, asset registries, or domain-knowledge stores. This
produces strong in-domain numbers but does not generalize to unseen schemas
without a re-learning phase. We argue this is the wrong default for production
agentic systems, which face heterogeneous, novel tabular data daily.

---

## 3. Our contribution (four pillars)

### Pillar 1: Failure-mode-to-architecture mapping (the methodology)
A documented design discipline that translates each known model incapability
into a specific architectural mitigation:

| Incapability | Failure mode | Mitigation role |
|---|---|---|
| Long-context degradation | F-DefShift | Spec Agent (reads docs once, freezes contract) |
| No internal stop signal | F-ActBias | Review Agent (mandatory pre-commit verification) |
| Action-bias on ambiguity | F-IterCap | Backreview Escalation (in-loop spec consultation) |

The methodology is presented as a reusable design pattern (Section 3 of paper),
not just a SCRIBE-specific recipe.

### Pillar 2: SCRIBE — concrete instantiation
- Spec Agent (frontier model, reads schema+KB once)
- ReAct Executor (open-weights model, executes against frozen spec)
- Review Agent (frontier model, mandatory pre-commit verification + on-demand)
- Asymmetric model assignment: GPT-5 at edges, Kimi-K2.6 in the middle
- **Honestly named:** task-matched assignment, NOT capability tiering. Section 4
  explicitly acknowledges Kimi-K2.6 outranks GPT-5 on Artificial Analysis
  Intelligence Index v4.0; the choice is about role-fit, not strength-tiering.

### Pillar 3: Zero-shot cross-schema generalization (the deployment claim)
SCRIBE deploys on unseen docs-heavy schemas without learning corpus. We show:
- DABStep: 59.8% combined (95.8% easy, 52.9% hard) — matches DS-STAR, behind
  NVIDIA which uses 8-hour offline learning per corpus.
- LiveSQLBench (held-out, no learning): predicted 75% (TBD experiment) — direct
  test of generalization.
- Per-task cost: $0.33 (DABStep), TBD (LiveSQLBench).

### Pillar 4: Lightweight spec template library (the SCRIBE-flavored offline component)
*New for this revision.* Unlike NVIDIA's `helper.py` (executable code library
specific to one corpus), SCRIBE mines **structural spec patterns** across
successful runs:

- Common CTE shapes (pre-aggregation patterns, window functions, JSON path
  extraction templates)
- Formula translation patterns (e.g., "X = A × B × C with C = mapping(category, dict)")
- Edge-case branches (empty result, divide-by-zero, NULL semantics)

This library is *structural and corpus-agnostic*. It does not contain DABStep
fee tables or LiveSQL schema names. We show it transfers from DABStep → LiveSQL
without re-mining, giving a small lift (predicted +3-5pp) on the cross-benchmark
deployment.

---

## 4. Experiments to run

### E-Paper1-1: Full 8-cell role-separation ablation (closes Reviewer Audit Major Weakness #5)

Run all combinations of (Spec model) × (Executor model) × (Review model) where
each axis is {Kimi-K2.6, GPT-5}. Eight cells total. Report on DABStep hard-378.

| Cell | Spec | Executor | Review | Expected accuracy |
|---|---|---|---|---|
| A | Kimi | Kimi | Kimi | 40.5% (Kimi solo upper bound) |
| B | GPT-5 | GPT-5 | GPT-5 | 50-55% (GPT-5 solo + review) |
| C (canonical SCRIBE) | GPT-5 | Kimi | GPT-5 | 52.9% (measured) |
| D (inverted) | Kimi | GPT-5 | Kimi | 45-50% (weak spec, strong exec) |
| E | GPT-5 | Kimi | Kimi | 48-52% (weak review) |
| F | Kimi | Kimi | GPT-5 | 45-50% (weak spec) |
| G | GPT-5 | GPT-5 | Kimi | 48-52% (weak review) |
| H | Kimi | GPT-5 | GPT-5 | 50-55% (weak spec) |

Cost: ~$400, 5 days wall-clock with 2× Fireworks keys parallel.

**What this proves or falsifies:** if C (canonical) is significantly better than
B (all-GPT-5) and A (all-Kimi), the role-separation claim survives. If B ≥ C,
the lift is just GPT-5 capability and the role-separation framing fails — we
report this honestly.

### E-Paper1-2: Hidden test set submission (closes Major Weakness #2, #7)

Submit SCRIBE to DABStep official hidden test set via leaderboard API. Direct
apples-to-apples comparison with DS-STAR (GPT-5: 50.4%, Gemini-2.5: 52.0%) and
NVIDIA NeMo (89.95% hard). Removes the dev-vs-hidden caveat.

Cost: ~$50, 1 day.

### E-Paper1-3: LiveSQLBench full 270-task deployment (closes Major Weakness #4)

Run SCRIBE on LiveSQLBench-base-lite-sqlite (270 tasks, 18 schemas) with the
*same* spec/review prompts and meta-rules used on DABStep. No re-tuning. This
is the zero-shot generalization claim.

Cost: ~$90, 3 days.

### E-Paper1-4: 5-seed CI on canonical SCRIBE (closes Major Weakness #3)

Run canonical SCRIBE 5 independent times with different random seeds. Report
mean ± 95% bootstrap CI. Separate canonical (no recovery pass) from
post-recovery numbers.

Cost: ~$200, 5 days (can parallelize with E-Paper1-1).

### E-Paper1-5: Spec template library mining + transfer (validates Pillar 4)

Extract structural spec patterns from the 218 SCRIBE-successful DABStep runs.
Deploy the resulting library on LiveSQLBench. Measure delta vs. zero-shot
LiveSQL deployment.

Cost: ~$30 (mining is offline), 2 days.

### E-Paper1-6: DS-STAR with current models (additional fairness, optional)

Re-run DS-STAR pipeline with Kimi-K2.6 + Gemini-2.5 Pro on DABStep dev. Shows
DS-STAR's architecture doesn't catch up even with current models, isolating
the SCRIBE design contribution from the model upgrade.

Cost: ~$80, 2 days. **Optional** — only if E-Paper1-2 hidden-test submission
doesn't fully resolve the time-fairness concern.

**Total Paper 1 experiment cost: ~$770 (without E-Paper1-6), ~$850 with.**

---

## 5. Paper structure (10 pages, IEEE 2-col)

| § | Title | Pages | Content |
|---|---|---|---|
| 1 | Introduction | 1.0 | Problem, contributions, cross-domain headline |
| 2 | Background and three failure modes | 1.0 | Literature-grounded definitions of F-DefShift, F-ActBias, F-IterCap |
| 3 | Methodology: failure-mode-to-architecture mapping | 1.5 | Design discipline, incapability→role table, five spec meta-rules |
| 4 | SCRIBE architecture | 1.5 | Three roles, asymmetric assignment, task-matched honest framing, spec template library |
| 5 | Evaluation | 2.5 | DABStep results + hidden test, LiveSQL zero-shot, 8-cell ablation, 5-seed CIs |
| 6 | Failure analysis (brief) | 0.5 | 3-4 example families, pointer to Paper 2 for full taxonomy |
| 7 | Related work | 0.5 | DS-STAR, NVIDIA NeMo, OceanBase, CMU primitives, AgentBench |
| 8 | Discussion and limitations | 0.5 | Honest acknowledgement of NVIDIA's leaderboard position; cross-domain deployment as our distinct value |
| 9 | Conclusion | 0.5 | One paragraph |
| Refs | | 0.5 | |

**Total: 10 pages exactly.**

---

## 6. What's intentionally NOT in Paper 1

- Full 13-family failure taxonomy → Paper 2
- Per-family verdict (AF/MB) → Paper 2
- Cross-architecture comparative study → Paper 2
- Open-source orchestration benchmark across 4 executor models → Paper 2
- Capability ceiling analysis → Paper 2

Paper 1 stays method-focused. Paper 2 owns the empirical breadth.

---

## 7. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Hidden test submission shows SCRIBE below DS-STAR | Low | Run E-Paper1-1 ablation first, see which cell wins, submit best cell |
| LiveSQL zero-shot accuracy below 50% | Medium | Already in progress; if low, reframe as "first SCRIBE deployment on relational schemas — baseline for future work" |
| Spec template library doesn't transfer | Medium | E-Paper1-5 is exploratory; if it fails, drop Pillar 4 and rely on three pillars |
| Reviewer 2 attacks "but Kimi is stronger than GPT-5" | High | E-Paper1-1 cell B (all-GPT-5) directly addresses this; if cell B ≥ C, we report it |
| NVIDIA publishes a stronger paper before submission | Medium | Our cross-domain angle is structurally different from their per-corpus learning |

---

## 8. Open questions for human author input

1. **Should we explicitly mention OceanBase's "asset engineering" stack** as
   related work, or cite it as a closed-source product comparison?
2. **Spec template library — how aggressive should the library be?**
   Just structural patterns, or also corpus-agnostic computed primitives
   (e.g., "weighted average" template)?
3. **For the LiveSQL zero-shot run, do we use the v3 SCRIBE with mandatory
   pre-commit gate**, or strip it back to v1 simpler configuration?
4. **Do we run multi-executor study (Kimi/GLM/DeepSeek/Qwen) in Paper 1**
   or save it for Paper 2?

---

## 9. Timeline

Assuming parallel execution with 2× Fireworks keys + 1 author writing:

| Week | Activity |
|---|---|
| 1 | Run E-Paper1-1 (8 cells, hard-378) + E-Paper1-3 (LiveSQL 270) in parallel |
| 2 | Run E-Paper1-2 (hidden test) + E-Paper1-4 (5 seeds) + start spec library mining (E-Paper1-5) |
| 3 | Analyze all results; rewrite Sections 1-4 of paper |
| 4 | Rewrite Sections 5-9; complete figures and tables |
| 5 | Internal review, polish, submit |

Total: 5 weeks from approval to submission.
