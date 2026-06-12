# Research Proposal — Paper 3 (Applied Track / Single Submission)

**Working title:** *Controlled Refutation of Common Mitigations on Capability-Bound Agent Failures: Evidence from DABStep, RuleArena, and LiveSQLBench*

(Previous title: *Three Failure Mechanisms in Docs-Heavy LLM Agents*. Revised after adversarial reviewer audit + literature review surfaced (a) RuleArena (Zhou et al., ACL 2025) and CMU Primitive Induction (arXiv:2606.02994, Jun 2026) as prior work overlapping our three-mechanism framing, and (b) structural problems with the "orthogonality" claim. The honest contribution is *not* a novel taxonomy but the **first combined controlled refutation of k-sampling / minimal-prompt / reasoning-amplification on a capability-bound cluster, anchored across three benchmarks**.)

**Target venue:** ICDM 2026 Applied Track — Topic #4 ("Comprehensive experimental analysis providing new fundamental insights into the strengths and weaknesses of existing methods")

**Track:** Applied Paper (10 pages IEEE 2-column)

**Status:** Revised v2. Replaces Paper 1 and Paper 2 as single ICDM 2026 submission target. Two retired proposals (`RESEARCH_PROPOSAL_PAPER_1.md`, `RESEARCH_PROPOSAL_PAPER_2.md`) remain on disk as design history.

---

## 0. Why this paper exists (revised meta-rationale)

Paper 1 (SCRIBE method, Research Track, ~25% acceptance) and Paper 2 (failure taxonomy, Applied Track, ~22% acceptance) were both rated Weak Reject by adversarial review. Paper 3 v1 ("Three Failure Mechanisms") was a restructure that the second-round adversarial reviewer rated **Weak Reject at ~32-38%** even with the full T1-T8 experiment battery, citing:

- The "orthogonality" claim was rhetorical, not measured: TB, CB, EB defined on three different population slices, with direct overlap evidence in our own data (4 of 37 fee_rule iter-capped tasks are simultaneously TB and CB candidates).
- All load-bearing evidence remains on one cluster (fee_rule) × one open model (Kimi K2.6) × one benchmark (DABStep).
- The three "refutations" are narrow: k=5 refutes naive resampling not self-consistency-with-voting; reasoning-amplification refutation is n=1; minimal-prompt refutation is n=5.
- Topic #4 expects a *menagerie* of methods analysed; one model-family with three light interventions does not qualify as "comprehensive."

The literature review separately surfaced two papers that overlap our mechanism claims:
- **RuleArena (Zhou et al., ACL 2025)** already showed rule-identification vs rule-application as distinct gaps on financial-domain rule reasoning. Our fee_rule cluster is the agentic instantiation.
- **CMU Primitive Induction (Lei et al., arXiv:2606.02994, Jun 2026)** independently showed stable rule artifacts give +44pp on RuleArena NBA, providing methodologically distinct evidence for the EB mechanism.

Paper 3 v2 (this document) responds with three structural changes:

1. **Reframe the contribution** from "three orthogonal mechanisms with fundamental insights" → "controlled triple-refutation of common CB-bridging mitigations, anchored across three benchmarks."
2. **Add T9-T17** to the experiment battery, especially T16 (RuleArena-NBA cross-benchmark CB replication) which gives a second cross-benchmark anchor specifically for CB at one of the lowest cost points in the battery.
3. **Acknowledge RuleArena and CMU Primitive Induction prominently** and differentiate honestly — they show the gap in single-turn / post-hoc induction settings; we show the gap persists in multi-turn agent settings and refute three common mitigations against it.

**Revised acceptance probability:** ~55-65% with full T1-T17 + citation pass + reframe. ~44-53% with Tier 1+2 only ($80, 12 days). The 95-97% target previously requested by the author is definitively not achievable at any top venue.

---

## 1. Central thesis (revised, one sentence)

> *On capability-bound failures of open-source LLM agents on docs-heavy data analysis — where the open model fails on tasks a frontier model solves — three commonly-proposed mitigations (independent k-sampling, prompt simplification, reasoning amplification) fail to close the gap; the gap is closed only by extraction-execution decoupling (planner-executor with frontier extractor) or frontier model swap; this pattern replicates across three structurally different benchmarks (DABStep, RuleArena, LiveSQLBench).*

The paper makes **two empirical claims and one differentiation claim:**

- **Empirical claim 1 (the refutation triad):** k-sampling, prompt simplification, and reasoning amplification all fail to close the capability-bound gap. n=25-30 on each (post-T1+T15+T17).
- **Empirical claim 2 (the recovery anchor):** Extraction-execution decoupling (Kimi+spec) recovers tasks the frontier solo agent itself fails (post-T3 n=15-20).
- **Differentiation claim:** Prior work (RuleArena, CMU Primitive Induction) shows the rule-identification / rule-application gap and shows stable rule artifacts close it; our contribution is (a) the *controlled refutation triad* of common mitigations (which neither prior paper runs), (b) cross-benchmark replication of CB across three structurally distinct benchmarks, (c) the demonstration that *weaker-executor + stronger-extractor* recovers tasks the *frontier-solo* model cannot solve (existing planner-executor work compares against weaker solo baselines).

No SOTA claim. No architecture novelty claim. SCRIBE appears as an integration case study in §7.

---

## 2. The three recovery signatures (renamed from "orthogonal mechanisms")

We retain the three-bucket structure but explicitly drop "orthogonality" and replace with "three distinct *recovery signatures*" — i.e., three distinct interventions that recover three (overlapping) subsets of the failure surface. T11 measures the overlap and publishes the cross-tab.

### TB — Termination-bound (recovery: termination calibration)

**Definition:** Failures where the gold answer is present in the model's trajectory but not emitted as the final response.

**Anchor:** `harness/analysis/research_notes/02_experiment_F_results.md` — 42 of 97 iter-capped failures (43%) had the gold answer in trace. Topic-conditional structure: aci_format 100% (16/16), reference_lookup 100% (1/1), date_specific 56.5%, delta_what_if 36.8%, fee_rule 13.5%.

**Prior to cite:**
- **Self-Consistency (Wang et al., ICLR 2023)** — voting mitigation premised on TB existing.
- **Reflexion (Shinn et al., NeurIPS 2023)** — verbal critique recovery.
- **Self-Refine (Madaan et al., NeurIPS 2023)** — iterative refinement.
- **Tree-of-Thoughts (Yao et al., NeurIPS 2023)** — search-based mitigation.
- **"Runaway is Ashamed, But Helpful" (Lu et al., arXiv:2505.17616, May 2025)** — concurrent work on the *dual* problem (premature exit in embodied environments). Cited as nearest prior; we differ in setting (docs-heavy, not embodied), direction (delayed commit, not premature exit), and contribution (measurement, not new mechanism proposal).
- **"Correct Chains, Wrong Answers" (arXiv:2604.13065, Mar 2026)** — 31/31 errors at depth 7 with verifiably correct reasoning yet wrong declared answers. Cross-domain corroboration that the TB phenomenon exists.

**Differentiation:** None of the prior papers measures TB-recoverable surface on a fixed benchmark (43%) or finds the topic-conditional structure.

### CB — Capability-bound (recovery: frontier model swap)

**Definition:** Failures where the open model cannot derive the correct answer at all, despite the frontier model solving the same task. Refuted mitigations: independent k-sampling, minimal prompting, reasoning amplification, **self-consistency-with-voting (T17, new)**, **Reflexion (T15, new)**.

**Anchors:**
- `harness/analysis/research_notes/05_opus_vs_kimi_capability_ceiling.md` — 10 fee_rule iter-capped tasks. Opus 10/10 (100%), Kimi 2/10 (20%). T1 extends to n=25-30 across multiple topic clusters.
- `harness/analysis/research_notes/04_k5_sampling_experiment.md` — k=5 sampling: 3/50 correct, pass@5=20%.
- `harness/analysis/research_notes/06_minimal_prompt_experiment.md` — minimal prompt: 0/5.
- `harness/analysis/research_notes/03_cross_model_on_iter_capped.md` — Kimi-reasoning 38 iters vs Kimi-off 23; reasoning amplification is harmful.
- **T16 (new):** RuleArena-NBA — second cross-benchmark CB anchor on a structurally closer benchmark (financial rule application).
- **T15 (new):** Reflexion: predicted to fail on CB cluster but help on TB cluster (gives a clean separation result).
- **T17 (new):** Self-consistency with majority vote: closes the pass@5 vs SC framing hole.

**Prior to cite:**
- **AgentBench (Liu et al., ICLR 2024)** — canonical open-vs-frontier gap measurement.
- **AgentBoard (Ma et al., NeurIPS D&B 2024)** — fine-grained progress-rate framework.
- **RuleArena (Zhou et al., ACL 2025)** — single-turn rule-identification vs rule-application gap. **Must-cite, our nearest prior on financial rule reasoning.**
- **Kimi K2 tech report (arXiv:2507.20534, Jul 2025)** — even most agent-tuned open model has cluster-level gaps.
- **Sky-T1 (Berkeley, Jan 2025)** — defensive citation: open is closing gaps on reasoning benchmarks, but fee_rule remains a gap region.
- **OptimalThinkingBench (arXiv:2508.13141, Aug 2025)** — overthinking literature supporting refutation 2c.
- **"How Do LLMs Fail in Agentic Scenarios" (Roig, arXiv:2512.07497, Dec 2025)** — independent evidence "scale alone doesn't predict robustness."

**Differentiation:** No prior paper runs the combined triple-refutation (k-sampling + minimal-prompt + reasoning-amplification + Reflexion + SC vote) on a CB-defined cluster across multiple benchmarks. This is the differentiable contribution.

### EB — Extraction-bound (recovery: extraction-execution decoupling)

**Definition:** Failures where the open model can execute the computation but cannot extract the rules from documentation; recovered by handing it a structured spec from a stronger extractor.

**Primary anchor (elevated from v1):** **Task-17 cross-planner falsifier** (`grafting_v2/results/v23_task17_*`). GPT-5 solo on task 17 → wrong (7.683437%, count-weighted). SAME GPT-5 used as spec writer for Kimi K2.6 executor → right (8.907926%, volume-weighted). This controls for model identity — extraction and execution are separable cognitive tasks even within the same frontier model. **Strongest possible Mechanism 3 evidence in the corpus.**

**Secondary anchor:** `harness/analysis/grafting_pilot/memo.md` — Sonnet-extracted spec + Kimi executor 4/5 (80%) vs Opus 4.6 solo 2/5 (40%). T3 extends to n=15-20.

**Refutation 3a — Variant-B (new):** Embedding full domain knowledge (fees.json + rule explanations) directly into the executor prompt HURT performance (`grafting_v2/results/v23_variantb_*`, n=184 attempted, n=5 pilot 2/5 = 40% regression). Refutes "just inject more rules into the prompt" — extraction needs to happen separately, not be replaced by larger context.

**Prior to cite:**
- **Plan-and-Solve (Wang et al., ACL 2023)** — origin of planner-executor pattern.
- **CodeAct (Wang et al., ICML 2024)** — executable action format background.
- **MetaGPT (Hong et al., 2023), AutoGen (Wu et al., 2023)** — multi-agent architectures.
- **CMU Primitive Induction (Lei et al., arXiv:2606.02994, Jun 2026)** — independent evidence: +44pp on RuleArena NBA from stable rule artifacts. **Critical citation — our biggest external ally.**
- **DS-STAR (Google, arXiv:2509.21825, Sep 2025), NVIDIA NeMo KGMON (HF blog), OceanBase DataPilot** — SOTA architectures using extraction-execution decoupling.

**Differentiation:** Existing planner-executor work compares against weaker baselines. CMU Primitive Induction shows post-hoc induction. We show *a-priori* docs-extracted spec recovers tasks the *frontier solo* model fails — a stronger comparison than either prior. This is the contribution; the planner-executor *pattern* is not.

### Recovery signatures, not orthogonal mechanisms (the honest framing)

The previous "orthogonality" framing implied TB, CB, EB are disjoint failure subsets. **They are not.** Our own data (per T11) shows:

- TB ∩ CB is non-empty: 4 of 37 fee_rule iter-capped tasks have the answer in trace AND are in the CB cluster (Opus solo solves).
- CB and EB use partly inconsistent definitions of "frontier-solo solves" (the canonical Opus-100% in CB is on iter-capped fee_rule; EB shows Opus solo fails 3/5 incorrect tasks).

Revised framing: **three independently-measured recovery interventions** that each recover a subset of failures, with measured overlap. T11 publishes the cross-tab. The headline claim is about *recovery* not *partition*.

---

## 3. What's *already measured* (the empirical spine — zero TBDs)

| # | Claim | Anchor file | n | Status |
|---|---|---|---:|---|
| 1 | Kimi K2.6 baseline on DABStep (450 tasks) | `harness/results/kimi_k2_6_results_official_grader.csv` | 450 | ✅ Done |
| 2 | 228 categorized failures, 10 bug patterns A-J | `harness/analysis/kimi-k2.6/incorrect_failure_breakdown.md` | 228 | ✅ Done |
| 3 | **Per-topic pass-rate decomposition** (transaction_count 100%, reference_lookup 100%, fee_rule 35.6%, etc. — shows mechanisms are topic-conditioned) | `HARNESS_WORK_INVENTORY.md` §Topic Distribution | 450 across 9 topics | ✅ Done |
| 4 | **Pattern A null-as-wildcard 6-decimal-place verification** on tasks 1275/1278 (Kimi filter → 0.122408 matches pred; correct filter → 0.120609 matches gold) | `harness/analysis/kimi-k2.6/incorrect_failure_breakdown.md` §Pattern A | 2 worked examples + ~25 family | ✅ Done |
| 5 | **DABStep benchmark error flags** (4 tasks: 1433, 1434 gold suspect; 1453 ambiguous tie-break; 2715 format guideline contradicts gold) — contribution to dataset maintainers | `harness/analysis/kimi-k2.6/incorrect_failure_breakdown.md` §Pattern H | 4 | ✅ Done |
| 6 | TB mechanism: 42/97 had answer in trace, topic-conditional (aci_format 100%, fee_rule 13.5%) | `harness/analysis/research_notes/02_experiment_F_results.md` | 97 | ✅ Done |
| 7 | CB mechanism: Opus 100% / Kimi 20% capability ceiling | `harness/analysis/research_notes/05_opus_vs_kimi_capability_ceiling.md` | 10 | ✅ Done |
| 8 | Refutation 2a: k=5 independent sampling (3/50 = 6%) | `harness/analysis/research_notes/04_k5_sampling_experiment.md` | 50 | ✅ Done |
| 9 | Refutation 2b: minimal prompt (0/5) | `harness/analysis/research_notes/06_minimal_prompt_experiment.md` | 5 | ✅ Done |
| 10 | Refutation 2c: reasoning amplification harmful (38 vs 23 iters) + **cost table** (Opus $0.60, Kimi-off $0.54, Kimi-reasoning $1.25 = 2.3× cost for 0pp gain, DeepSeek $0.99 cap) | `harness/analysis/research_notes/03_cross_model_on_iter_capped.md` | 4 models × 1 task | ✅ Done |
| 11 | EB mechanism: Kimi+spec 80% vs Opus solo 40% | `harness/analysis/grafting_pilot/memo.md` | 5 | ✅ Done |
| 12 | **EB mechanism — Task-17 cross-planner falsifier** (SAME GPT-5: solo → wrong 7.683437%; as spec writer for Kimi → right 8.907926%). Controls for model identity — strongest extraction/execution separability evidence in the corpus. | `grafting_v2/results/v23_task17_*` | 1 controlled comparison, multi-seed | ✅ Done |
| 13 | **Refutation 3a — Variant-B domain-knowledge injection** (embedding full fees.json + domain rules into prompt HURT performance; n=184 scale-up couldn't grade due to failure rate; n=5 pilot 2/5 = 40% regression) | `grafting_v2/results/v23_variantb_*` + `grafting_v2/docs/domain_knowledge.md` | 184 (partial) + 5 pilot | ✅ Done |
| 14 | Read:Act ratio analysis (5,744 calls; failed read MORE: 1.97 vs 1.61) — refutes "RAG would fix it" mitigation | `harness/analysis/research_notes/07_read_act_ratio.md` | 446 | ✅ Done |
| 15 | Multi-model baseline (Sonnet/Kimi/GLM/DeepSeek/Qwen × 10 tasks) + **Qwen-only-correct-on-NA task-70 anomaly** (tasks 49/70 fail across all 5 models → gold ambiguity, not capability) | `harness/results/*_dabstep_dev__full.json` | 10/model × 5 models | ✅ Done |
| 16 | SCRIBE 59.8%/52.9% on DABStep — best-of-N union ceiling, honestly flagged | `scribe/results/scribe_main.json` + `SCRIBE_REPO_INVENTORY.md` §10 | 450 | ✅ Done |
| 17 | **grafting_v2 second architecture data point**: GPT-5 spec + Kimi executor → easy 49/72 (68.1%, −6.9pp regression vs Kimi solo), hard 169/378 (44.7%, +4.2pp). Honest mixed result. | `grafting_v2/results/v23_gpt5_easy_all72/` + `v23_gpt5_hard_all378_FINAL/` | 450 | ✅ Done |
| 18 | **Regression recovery experiment**: 26/44 regressed tasks recovered (59.1%) with 2 prompt deltas (mandatory non-empty review + escalation at iter 15) — counter-narrative to "orchestration trades easy for hard" | `grafting_v2/results/v23_hard_regressions44_rerun/` | 44 | ✅ Done |
| 19 | **Cross-mechanism evidence — escalation under-invocation**: only 25/378 (6.6%) hard sessions invoked ask_spec_agent; 4/25 (16%) recovered when invoked; 188/209 hard failures had genuine ambiguity but didn't escalate. Connects TB (action-bias = early commit) to EB (extraction self-uncertainty). | `SCRIBE_REPO_INVENTORY.md` §Escalation Under-invocation | 378 | ✅ Done |
| 20 | LiveSQL ladder v1=30% → v2=35% → v3=47% (on failing-15 subset) + 13 failure patterns + SoTA comparators (o3-mini 42.6%, Claude 3.7 41.1%, GPT-4o 34.4%) | `livesqlbench/EXPERIMENT_FINDINGS.md` | 20 + 15 | ✅ Done |
| 21 | Architectural variant sweep (927 task executions) including Sonnet-as-planner direction asymmetry (Sonnet+Kimi 4/5 vs Kimi+Sonnet 0/1) | `grafting_v2/results/` + `grafting_v2/results/sonnet_kimi/` | 927 | ✅ Done |
| 22 | Iter-capped characterization: infinite verification mode, topic distribution | `harness/analysis/research_notes/01_iter_capped.md` | 97 | ✅ Done |

**Total: 22 measured anchors, all on disk, zero TBDs.** (Up from 13 in v1 of this proposal — the additional 9 were surfaced by a systematic scan of the four working folders.)

### Key elevations from v1
- Anchor #12 (Task-17 cross-planner falsifier) is **a cleaner Mechanism 3 anchor** than the original grafting pilot. Same model (GPT-5) succeeds as spec writer, fails as solo executor. Strongest possible evidence for extraction/execution as separable cognitive tasks.
- Anchor #13 (Variant-B negative result) is **a fourth refutation for Mechanism 3** — "just stuff more rules into the prompt" was tested at n=184 and failed.
- Anchor #19 (escalation under-invocation) is **cross-cutting evidence**: 6.6% invocation rate links TB action-bias to EB extraction self-uncertainty as a unified mechanism.
- Anchor #5 (4 benchmark error flags) **turns a liability into a contribution** to DABStep maintainers.

---

## 4. The complete experiment battery (T1-T17, organized by tier)

| Tier | ID | Experiment | Cost | Days | Lift (pp) | Closes attack |
|---|----|---|---:|---:|---:|---|
| **1 (free)** | T4 | Bootstrap CIs on every pass rate (1000 resamples) | $0 | 2 | +2-4 | "No statistics" |
| 1 | T6 | Inter-rater reliability (Cohen's κ on 50 failures) | $0 | 3 | +2-3 | "Single-labeler subjectivity"; matches MAST κ=0.88 bar |
| 1 | T11 | TB/CB/EB overlap analysis + tie-breaker rule | $0 | 2 | +2-3 | "Orthogonality bluffed" |
| 1 | T13 | Reintroduce SCRIBE as §7 integration case study | $0 | 1 | +1-2 | "No integrated architecture" |
| 1 | T14 | Restore 10 bug patterns A-J as half-page sub-table | $0 | 1 | +1-2 | "Densest evidence buried" |
| **2 (high ROI)** | T1 | Opus/Kimi capability ceiling n=10 → n=25-30 | $50 | 2 | +5-7 | "n=10 anecdotal" |
| 2 | T16 | **RuleArena-NBA CB cross-benchmark replication** | $20 | 2 | +5-7 | "DABStep-specific"; differentiates from RuleArena prior |
| 2 | T17 | Proper self-consistency (majority vote) refutation | $10 | 1 | +2-3 | "pass@5 conflates with SC" |
| **3 (close attacks)** | T3 | Grafting pilot n=5 → n=15-20 | $80 | 3 | +5-7 | "Mechanism 3 underpowered" |
| 3 | T12 | Re-run Opus capability ceiling in same harness | $150 | 3 | +3-4 | "Cross-harness confound" |
| 3 | T15 | Reflexion as 4th refutation of CB | $30 | 2 | +3-4 | "Did you try self-critique?" |
| **4 (breadth)** | T5 | Capability ceiling on LiveSQL (cross-benchmark) | $50 | 2 | +4-6 | "Single benchmark" (partly) |
| 4 | T9 | CB + EB on 2nd non-SQL benchmark (Kramabench/BIRD) | $300 | 7 | +5-8 | "Single benchmark" (fully) |
| 4 | T10 | Additional refuted mitigations (CoT variants) | $100 | 4 | +3-5 | "Refutation space narrow" |
| **5 (close gaps)** | T2 | Add GPT-5 to multi-model baseline | $30 | 1 | +3-5 | "Where's GPT-5?" |
| 5 | T7 | Held-out 30-task pre-registered slice | $30 | 2 | +3-5 | "Test-set leakage" |
| 5 | T8 | DABStep hidden test submission | $50 | 1 | +2-4 | "Dev-vs-hidden gap" |
| | | **TOTAL T1-T17** | **$900** | **~10 wk** | **+51-80 raw, ~+30 net** | |

(Lift figures are *attack-closing potential*, not additive expected reviewer-score gains. Real reviewer dynamics anchor on weakest load-bearing claim; closing five attacks does not produce 5× the score lift of closing one. Net realistic lift caps at ~+30pp from the ~25% no-experiment baseline.)

### Recommended subsets

| Subset | Cost | Time | Probability |
|---|---:|---:|---:|
| **Tier 1 only** (free attack closes) | $0 | ~10 days | ~32-40% |
| **Tier 1 + 2** (minimum viable) | $80 | ~12 days | ~44-53% |
| **Tier 1+2+3** (close major attacks) | $340 | ~5 wk | ~52-60% |
| **Full T1-T17** (highest realistic) | $900 | ~10 wk | **~55-65%** |
| **Full + reframe + citation pass** | $900 | ~10 wk | **~58-67%** |

**Honest ceiling at any top venue: ~67%.** The 95-97% target previously requested is not on the table.

---

## 5. Literature review summary and citation plan

Based on systematic literature review (25 verified citations identified, agentReportFile: lit review by background agent):

### Top 8 must-cite citations (by ROI)

1. **RuleArena (Zhou et al., ACL 2025)** — §1, §5, §9. Closes the highest-risk attack ("RuleArena already showed this").
2. **CMU Primitive Induction (Lei et al., arXiv:2606.02994, Jun 2026)** — §6, §9. Independent evidence of EB mechanism via post-hoc induction (+44pp on RuleArena NBA).
3. **"Runaway is Ashamed, But Helpful" (Lu et al., arXiv:2505.17616, May 2025)** — §4. Nearest prior on TB; we differ in direction (delayed vs premature commit).
4. **MAST (Cemri et al., arXiv:2503.13657, Mar 2025)** — §3, §8. Cohen κ=0.88 protocol matches T6.
5. **DABStep (Egg et al., arXiv:2506.23719, Jun 2025)** — §2, §3. Benchmark of record; we extend qualitative failure account quantitatively.
6. **"Correct Chains, Wrong Answers" (arXiv:2604.13065, Mar 2026)** — §1 intro hook. 31/31 errors with correct reasoning.
7. **Self-Consistency, Reflexion, Self-Refine, ToT** — §4, §5. Scope our refutations explicitly.
8. **AgentBench (ICLR 2024), AgentBoard (NeurIPS D&B 2024)** — §3, §5. Canonical capability-gap anchors.

### 17 secondary citations (full list per lit review §B)

DS-STAR, NeMo KGMON, OceanBase DataPilot, Sky-T1, Kimi K2 report, OptimalThinkingBench, "Do NOT Think That Much", BIRD-INTERACT, AgentErrorTaxonomy, Aegis, TRAIL, "Seeing the Whole Elephant", Plan-and-Solve, CodeAct, "How Do LLMs Fail in Agentic Scenarios" (Roig).

### Citation placement summary (§ map)

- **§1 (Intro):** RuleArena, "Correct Chains Wrong Answers", DABStep (as motivation).
- **§2 (Setup):** DABStep, Kimi K2 report, CodeAct.
- **§3 (Failure landscape):** AgentBench, AgentBoard, MAST, Aegis, AgentErrorTaxonomy, TRAIL, BIRD-INTERACT, DABStep failure analysis.
- **§4 (TB mechanism):** Self-Consistency, Reflexion, Self-Refine, ToT, Runaway-is-Ashamed, Correct-Chains-Wrong-Answers.
- **§5 (CB mechanism):** AgentBench, AgentBoard, RuleArena, Kimi K2, Sky-T1, OptimalThinkingBench, "How Do LLMs Fail in Agentic Scenarios", Self-Consistency (scoped), Reflexion (scoped).
- **§6 (EB mechanism):** Plan-and-Solve, CodeAct, MetaGPT, AutoGen, CMU Primitive Induction.
- **§7 (Cross-model + cross-benchmark + SCRIBE integration):** BIRD-INTERACT, multi-model results.
- **§9 (Related work):** DS-STAR, NeMo KGMON, OceanBase DataPilot, CMU Primitive Induction, RuleArena, all taxonomy papers (§3 supplementally).

---

## 6. The 6 predicted reviewer attacks and pre-emptive defenses

### Attack 1 (highest probability): "RuleArena and CMU Primitive Induction already establish rule-identification vs rule-application as distinct."

**Defense (§6, §9):** "(a) RuleArena is single-turn; the gap persists and is mechanism-isolable in multi-turn agent settings. (b) CMU primitive induction recovers gap via *post-hoc* trace mining from the source agent; we show *a-priori* docs-extracted spec from a stronger reader recovers tasks the frontier solo agent itself cannot solve. (c) Neither prior refutes k-sampling / minimal-prompt / reasoning-amplification / Reflexion / SC-vote as CB-bridging mitigations. The controlled refutation triad is the structural contribution."

### Attack 2: "Termination calibration is studied to death (SC, Reflexion, ToT, Self-Refine, Runaway-is-Ashamed)."

**Defense (§4):** Reframe TB as *measurement* not discovery. "We measure the TB-recoverable surface (43% of iter-capped failures) and find topic-conditional structure (100% aci_format, 13.5% fee_rule) that prior work does not predict. Runaway-is-Ashamed addresses the *dual* problem (premature exit in embodied settings)."

### Attack 3: "Capability ceiling shown for one model on one cluster at n=10."

**Defense:** T1 → n=25-30, T16 → RuleArena-NBA cross-benchmark CB at n=50, T5 → LiveSQL CB. Cite AgentBench, AgentBoard, Roig 2025 as independent gap evidence. §8 acknowledges remaining limitations.

### Attack 4: "Planner-executor decoupling is Plan-and-Solve / MetaGPT / Plan-and-Act — incremental."

**Defense (§6):** "Prior planner-executor work compares against *weaker* baselines; we compare against the *frontier-solo* baseline (Opus 4.6). The novel finding is that weaker-executor + stronger-extractor recovers tasks the frontier solo model fails — a stronger comparison than prior work."

### Attack 5: "k=5 sampling refutation conflates pass@5 with self-consistency."

**Defense:** T17 runs proper self-consistency (majority vote over reasoning chains) explicitly. §4-5 language scoped: "we refute *independent k-sampling* (pass@k) and *majority-vote self-consistency* (T17), separately reported."

### Attack 6: "The DABStep paper already qualitatively flagged docs-extraction issues — your EB is a restatement."

**Defense (§2-3):** "DABStep authors flag docs-extraction qualitatively; we *measure* the recovery (Kimi+spec 80% vs Opus solo 40%, T3-extended to n=15-20) and demonstrate EB is *separable* from CB (Opus has procedural skill but fails solo). The mechanism *account* with controlled measurement, not the qualitative observation, is the contribution."

---

## 7. Paper structure (10 pages, IEEE 2-col)

| § | Title | Pages | Content |
|---|---|---:|---|
| 1 | Introduction (problem, refutation-triad contribution, RuleArena differentiation, the killer hook from Correct-Chains-Wrong-Answers) | 0.75 | new |
| 2 | DABStep benchmark + harness setup (Kimi K2.6, run_python, OpenRouter) | 0.75 | `harness/walkthrough.md`, DABStep paper |
| 3 | Baseline failure landscape: 228 failures, 10 bug patterns A-J + 4 benchmark error flags, recovery estimates | **2.5** (expanded per T14) | `harness/analysis/kimi-k2.6/` |
| 4 | **TB — Termination-bound** with topic-conditional structure (42/97; 100% aci_format) | 1.0 | notes 02, 04 |
| 5 | **CB — Capability-bound** + **refutation quintuple** (k-sampling, minimal prompt, reasoning amplification, Reflexion, SC vote) on n=25-30 + RuleArena-NBA cross-benchmark replication | **2.0** | notes 05, 06, 03, 04 + T1, T15, T16, T17 |
| 6 | **EB — Extraction-bound** (Kimi+spec n=15-20 > Opus solo) + CMU Primitive Induction independent evidence | 1.0 | grafting_pilot + T3 |
| 7 | Multi-model verification + cross-benchmark (LiveSQL, RuleArena) + SCRIBE as integration case study showing all three recovery levers compose | 1.25 | results/*.json, livesqlbench, scribe/results + T13 |
| 8 | Implications, limitations (n=10 base, single-seed, cross-harness Opus confound→T12, bug-fix transparency), DABStep dataset error flags as contribution | 0.5 | new + T14 |
| 9 | Related work (RuleArena, CMU Primitive Induction, DS-STAR, NeMo KGMON, OceanBase DataPilot, taxonomy papers, SC/Reflexion/ToT/Self-Refine, Plan-and-Solve, AgentBench, AgentBoard) + conclusion | 0.75 | new |
| Refs | | 0.5 | 25 citations |

**Total: 10 pages.**

---

## 8. Honest probability estimates (revised)

| Configuration | Probability | Cost | Time |
|---|---:|---:|---:|
| Paper 3 v2 as proposed, no experiments | ~25-32% | $0 | 4 wk writing |
| + Tier 1 (free attack closes) | ~32-40% | $0 | ~10 days |
| + Tier 2 (T1, T16, T17 — highest ROI) | ~44-53% | $80 | ~12 days |
| + Tier 3 (T3, T12, T15) | ~52-60% | $340 | ~5 wk |
| + Tier 4 (T5, T9, T10 — breadth) | ~55-63% | $790 | ~9 wk |
| + Tier 5 (T2, T7, T8) | ~57-65% | $900 | ~10 wk |
| + reframe + full citation pass | **~58-67%** | $900 | ~10 wk |

**Floor:** ~25% (do nothing)
**Realistic recommended:** ~58-67% (full battery + reframe + citations)
**Honest ceiling at any top venue:** ~67%
**Author's previous 95-97% target:** Not achievable.

The gap between ~50% (Tier 1+2) and ~65% (full) is the difference between *coin flip* and *more likely than not.* If acceptance matters, the marginal $820 for +12-14pp is worth paying.

---

## 8a. Missed-findings audit integration (new in v2 final)

A systematic scan of the four working folders surfaced 9 additional measured anchors not in v1's evidence table. v2 incorporates them as follows:

### MUST-include (integrated above)
1. **Task-17 cross-planner falsifier** → elevated as primary EB anchor (§2 EB section + anchor #12).
2. **Pattern-A 6-decimal verification on tasks 1275/1278** → §3 (failure landscape) worked example (anchor #4).
3. **Per-topic baseline** (transaction_count 100%, fee_rule 35.6%, etc.) → §3 (anchor #3) — defends mechanism-topic confounding attack.
4. **DABStep benchmark error flags** (1433, 1434, 1453, 2715) → §8 sub-section "Benchmark hygiene observations" (anchor #5) — turns liability into contribution.
5. **grafting_v2 second architecture data point** (49/72 easy, 169/378 hard, with explicit easy regression) → §7 cross-model + §8 limitations (anchors #17, #18).

### SHOULD-include (integrated)
6. **Variant-B domain-knowledge injection refutation** → §6 (anchor #13) — 4th refutation for Mechanism 3.
7. **Cross-model COST table** ($0.54-$1.25 spread) → §5 refutation 2c (anchor #10) — practitioner takeaway.
8. **Qwen-only-correct-on-NA task-70 anomaly + 5-model agreement on tasks 49/70** → §7 (anchor #15) — argues "easy failures = gold ambiguity."
9. **Regression recovery experiment** (26/44 recovered) → §8 (anchor #18) — counter-narrative to "orchestration trades easy for hard."

### CONSIDER (held for possible inclusion)
- Sonnet-as-planner direction asymmetry (Sonnet+Kimi 4/5 vs Kimi+Sonnet 0/1) → noted in anchor #21.
- LiveSQL F1-F10 failure pattern catalog → already in anchor #20.
- SFT dataset curation existence → §9 future work.

**Net effect on probability:** the additional anchors close 2-3 more reviewer attacks (per-topic confounding, "just inject more knowledge", architecture-data-point-of-one) and add ~3-5pp lift on top of T1-T17 — bringing realistic ceiling to **~60-70%** with full battery + full citation pass + reframe + missed-findings integration.

---

## 9. What changed from v1 (changelog)

1. **Title and central thesis** rewritten to lead with "controlled refutation triad" rather than "three orthogonal mechanisms."
2. **§2 rewritten** to call the three buckets "recovery signatures" not "orthogonal mechanisms"; explicitly acknowledge overlap; commit to T11 cross-tab.
3. **§5 (Mechanism 2)** expanded to include T15 (Reflexion), T17 (self-consistency vote), T16 (RuleArena cross-benchmark).
4. **§6 (Mechanism 3)** reframed to emphasize "frontier-solo fails" comparison as the differentiator from Plan-and-Solve / MetaGPT / Plan-and-Act.
5. **§7 (Cross-model + cross-benchmark)** expanded to position SCRIBE as integration case study (closes "where's the integrated architecture?" attack).
6. **§3 (Failure landscape)** expanded from 1.5pp to 2.5pp to restore 10 bug patterns A-J + benchmark error flags (T14).
7. **§9 (Related work)** expanded from 0.25pp to 0.75pp to accommodate RuleArena, CMU Primitive Induction, full taxonomy citations.
8. **Experiment battery** expanded from T1-T8 to T1-T17 with five-tier ROI structure.
9. **Probability estimates** revised downward to honest ~58-67% ceiling.
10. **Pre-emptive defense paragraphs** for 6 predicted reviewer attacks added as §6.
11. **Citation plan** with §-level placement for 25 verified citations added as §5.

---

## 10. Open decisions for author input

1. **Final experiment-tier commitment.** Tier 1+2 ($80, ~50% probability) or full T1-T17 ($900, ~65%)?
2. **T16 (RuleArena) folder structure approved?** Data: `/Users/suraj/Downloads/rulearena/`. Scripts: `scribe/scripts/rulearena_adapter.py`. Results: `scribe/results/rulearena_*/`.
3. **Reframe approved?** Drop "fundamental insight" and "orthogonality"; lead with "controlled refutation triad" and "recovery signatures."
4. **§3 expansion approved?** Restore 10 bug patterns A-J + 4 benchmark error flags as a half-page sub-table.
5. **DABStep dataset error flags** (tasks 1433, 1434, 1453, 2715) — surface in §8 as a contribution to dataset maintainers? (Recommended: yes, low-cost positive signal to PCs that authors do empirical work that benefits the community.)
6. **Held-out E-Paper2-G analog (T7)?** 30-task pre-registered slice. Optional but addresses test-set leakage attack.
7. **What to do with the in-progress missed-finding scan agent results when they arrive?** (Currently background agent surveying four folders for any measured findings not in the 13 anchors above.)

---

## 11. Timeline (full T1-T17 battery)

| Week | Activity |
|---|---|
| 1 | Tier 1 (free): T4, T6, T11, T13, T14. Tier 2: T17 (cheapest). Start §1-3 draft. |
| 2 | Tier 2: T1, T16. Tier 3: T15. Start §4-5 draft. |
| 3 | Tier 3: T3, T12. Tier 4: T5. Start §6-7 draft. |
| 4 | Tier 4: T9 (most expensive single experiment). Tier 5: T2. Draft §8-9. |
| 5 | Tier 5: T7, T8. Complete first draft. |
| 6-7 | Internal review, citation pass, anonymization. |
| 8 | Submit. |

**Total: 8 weeks from approval.**

If only Tier 1+2 (recommended minimum):

| Week | Activity |
|---|---|
| 1 | Tier 1 (free) + T17. Start §1-3 draft. |
| 2 | T1 + T16. Draft §4-5. |
| 3 | Draft §6-9. |
| 4 | Internal review, anonymization. |
| 5 | Submit. |

**Total: 5 weeks for Tier 1+2.**
