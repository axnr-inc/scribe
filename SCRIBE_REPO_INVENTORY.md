# SCRIBE Repository Inventory

**Last updated:** 2026-06-05

**Repository:** github.com/axnr-inc/scribe (origin), github.com/Suraj-gameramp/scribe (personal)

---

## Executive Summary

SCRIBE (Spec-Conditioned ReAct with Inline Backreview Escalation) is a three-role agent architecture for docs-heavy data-analysis tasks, instantiated on the DABStep benchmark with two papers under development for ICDM 2026:

- **Paper 1 (Research Track):** Method paper on role-orchestrated harness design with asymmetric model assignment.
- **Paper 2 (Applied Track):** Comprehensive failure-mode taxonomy across three benchmarks with per-family verdicts (architecture-fixable vs. model-bound).

**Headline results (DABStep dev set):**
- Easy-72: 95.8% (69/72)
- Hard-378: 52.9% (200/378)
- Combined-450: 59.8% (269/450)
- Per-task cost: $0.33 (Kimi-K2.6 executor + GPT-5 spec/review)

---

## 1. Folder Structure (Annotated)

```
scribe/
├── src/                           # TypeScript harness (1,888 LOC total)
│   ├── run.ts                     # Main entry point; handles config parsing, task execution loop
│   ├── config.ts                  # Config schema parsing + defaults
│   ├── model_resolver.ts          # Provider routing (OpenRouter, Fireworks, Baseten, Anthropic-direct)
│   ├── harness/
│   │   ├── tools/
│   │   │   ├── run_python.ts      # Python REPL executor; handles sandboxing, timeouts, imports
│   │   │   ├── ask_planner.ts     # Escalation protocol; sends structured summary to Review Agent
│   │   │   ├── run_sql.ts         # SQL executor (legacy, not used in current SCRIBE)
│   │   │   └── index.ts           # Tool registration
│   │   ├── services/
│   │   │   ├── python_repl.ts     # REPL environment; manages sessions, preamble
│   │   │   ├── session_logger.ts  # Trace recording (JSONL per task)
│   │   │   ├── token_tracker.ts   # Per-role token accounting (spec/executor/review)
│   │   │   └── local_tracker.ts   # Local performance metrics
│   │   └── hooks/
│   │       ├── prompt_cache.ts    # Anthropic prompt-caching integration (DABStep-specific)
│   │       └── after_tool.ts      # Post-execution hooks (logging, metrics)
│   └── prompts/                   # YAML prompt templates per executor variant
│
├── scripts/                        # Python + bash utilities (1,609 LOC Python total)
│   ├── extract_specs.py           # Stage 1: reads manual+schema, emits frozen computation_plan (394 LOC)
│   ├── extract_specs_livesql.py   # Variant for LiveSQL schema extraction (451 LOC)
│   ├── fetch_dabstep_data.py      # Downloads manual.md, fees.json, payments.csv from HF (67 LOC)
│   ├── grade.py                   # Scores predictions against gold using DABStep official scorer (125 LOC)
│   ├── grade_livesql.py           # LiveSQL grading variant (192 LOC)
│   ├── quick_wins_f8_rescore.py   # Tooling corrections for failure family F8 (86 LOC)
│   ├── livesqlbench_adapter.py    # Converts LiveSQL task format to SCRIBE format (166 LOC)
│   ├── build_dataset.py           # Dataset split construction (128 LOC)
│   └── repro.sh                   # One-command smoke test: 5 tasks, ~5 min, <$1
│
├── configs/                        # YAML run configurations (7 canonical + 13 experimental variants)
│   ├── scribe_main.yaml           # CANONICAL: Kimi-K2.6 (Fireworks) executor + GPT-5 (OpenRouter) spec+review
│   ├── kimi_grafted_iterative.yaml # Kimi all-in-one via OpenRouter (fallback when no Fireworks)
│   ├── gpt5_solo_baseline.yaml    # Ablation: GPT-5 monolithic (falsifier)
│   ├── kimi_baseline.yaml         # Ablation: Kimi-K2.6 monolithic
│   ├── opus_baseline.yaml         # Ablation: Opus 4.6 monolithic
│   ├── livesql_scribe.yaml        # LiveSQL variant (18 schemas, 270 tasks)
│   ├── kimi_grafted_iterative_opus_planner.yaml  # Executor-only ablation: Opus as spec
│   └── experiments/configs/       # 13 archived variants (provider sharding, model variants, DK injection)
│       ├── kimi_grafted_iterative_fireworks*.yaml (2 files, Fireworks sharding)
│       ├── kimi_grafted_iterative_baseten*.yaml   (2 files, Baseten sharding)
│       ├── kimi_grafted_iterative_openrouter*.yaml (2 files, OpenRouter sharding)
│       ├── kimi_grafted_iterative_fireworks2*.yaml (2 files, 2nd Fireworks account)
│       ├── opus_grafted.yaml, haiku_grafted.yaml, deepseek_executor_kimi_planner.yaml
│       ├── sonnet_executor_kimi_planner.yaml
│       └── kimi_grafted_iterative_gpt55_planner.yaml
│
├── data/                           # Task definitions + splits
│   ├── splits/
│   │   ├── easy_all72.jsonl       # 72 easy tasks (dev set)
│   │   ├── hard_all378.jsonl      # 378 hard tasks (dev set)
│   │   └── ... (other splits)
│   ├── verified_answers.json      # Gold answers (consensus from DABStep)
│   ├── context/                   # (populated by fetch_dabstep_data.py)
│   │   ├── manual.md
│   │   ├── fees.json
│   │   ├── payments.csv
│   │   └── ... (schema files)
│   └── target_tasks.jsonl         # Full 450-task manifest
│
├── results/                        # Summary CSVs + sample session traces
│   ├── v23_gpt5_easy_all72.csv    # Easy-72 results: task_id, correct, tool_calls, cost_usd
│   ├── v23_gpt5_hard_all378_FINAL.csv  # Hard-378 final: 200/378 PASS (+ rescore variants)
│   ├── v23_gpt5_easy_all72_summary.json  # Detailed per-task metrics (wall-seconds, cost, iterations)
│   ├── v23_gpt5_solo5_summary.json       # GPT-5 solo falsifier: 1-2/5 PASS at higher cost
│   ├── v23_pilot5.csv             # Smoke-test 5 tasks
│   ├── hard_regressions44_rerun_union.csv # Recovery experiment: Path-B escalation rescue
│   ├── v23_hard_quickwin_f{10,12}_summary.json # F8/F10/F12 tooling fixes
│   ├── v23_metarules_pilot5_summary.json # Meta-rules ablation pilot
│   ├── repro_pilot/               # Smoke-test full traces (5 subdirs: 1275, 1453, 1489, 17, 1739)
│   │   └── {task_id}/sessions/normal_agent.jsonl (full trace per task)
│   ├── samples/                   # Hand-picked representative full traces
│   │   ├── sample_1012.jsonl, sample_2366.jsonl, sample_fireworks.jsonl
│   │   ├── task17_cross_planner/  # 6 traces showing spec-author variance on task 17
│   │   └── regressions44_rescued/ # 3 traces: canonical escalation-rescue demos
│   ├── livesql_scribe_pilot/      # 15 LiveSQL tasks, pilot run (best-of-3 + recovery)
│   │   └── {schema}/sessions/
│   ├── livesql_scribe_v2/         # 15 LiveSQL tasks, v2 run
│   │   └── {schema}/sessions/
│   └── livesql_scribe_v3/         # 15 LiveSQL tasks, v3 run (canonical LiveSQL deployment)
│       ├── {schema}/ (alien_3, alien_5, alien_6, archeology_*, credit_*, crypto_6, etc.)
│       ├── summary.json           # Per-task metrics
│       └── run_manifest.json
│
├── docs/                           # Architecture, experiments, reproducibility
│   ├── architecture.md            # Three-role topology, escalation protocol, failure-mode mapping
│   ├── reproducibility.md         # Six headline reproduction recipes + ablation guides
│   ├── domain_knowledge.md        # Variant-B (DK injection) postmortem — honest negative result
│   ├── openrouter.md              # Provider routing, thinking/reasoning setup, OpenAI-compat sharding
│   ├── experiments/               # Ad-hoc experiment reports (7 markdown files)
│   │   ├── 01_iter_capped.md      # Iteration-cap failure mode analysis
│   │   ├── 02_experiment_F_results.md
│   │   ├── 03_cross_model_on_iter_capped.md
│   │   ├── 04_k5_sampling_experiment.md # Resampling study (rules out infrastructure flake)
│   │   ├── 05_opus_vs_kimi_capability_ceiling.md # Capability scaling on fee-rule tasks
│   │   ├── 06_minimal_prompt_experiment.md # Minimal-prompt ablation (rules out prompt over-constraint)
│   │   ├── 07_read_act_ratio.md
│   │   └── easy72_gpt5_kimi.md
│   ├── failure_analysis/          # Kimi-solo taxonomy (9 markdown files + CSVs)
│   │   ├── summary.md             # Overview: 206 correct, 97 iter_capped, 76 incorrect on 450 tasks
│   │   ├── deep_root_cause_per_pattern.md # Detailed per-family analysis
│   │   ├── root_cause_and_planner_fix.md
│   │   ├── incorrect_failure_breakdown.md
│   │   ├── verified_per_task_diagnosis.md
│   │   ├── incorrect_summary.csv, incorrect_categorized.csv
│   │   ├── verified_failures*.json
│   │   └── (95 Kimi-solo task traces under harness/analysis/kimi-k2.6/ — not in this repo)
│   ├── failure_modes/              # Detailed examples
│   │   └── definition_shift/README.md
│   ├── quick_wins/                 # Tooling-correction sweep summary
│   │   └── README.md
│   ├── case_studies/              # (placeholder for future case studies)
│   └── notes/                      # Design decisions, rough notes
│       ├── objective_doc.md        # Master plan: ICDM 2026 positioning, two-paper structure, timeline
│       ├── rough_documentation.md
│       └── rough_planner.md
│
├── paper/                          # LaTeX sources + figures
│   ├── scribe.tex                 # Finding paper (~10 pages IEEE 2-column, draft in progress)
│   ├── scribe-supplement.tex      # Supplement (~25 pages A4, full failure analysis + reproducibility)
│   ├── figures/
│   │   ├── arch.tex               # Architecture diagram (TikZ)
│   │   └── ... (cost breakdown, failure taxonomy, etc.)
│   └── ieee_template/             # IEEE 2-column template
│
├── vendor/                         # Third-party dependencies
│   └── dabstep_scorer/
│       ├── scorer.py              # DABStep official scorer (vendored, Apache 2.0)
│       └── LICENSE-DABStep
│
├── TRACES.md                       # Comprehensive inventory: every experiment → artifact(s)
├── README.md                       # Quick-start guide + headline results
├── PRE_REGISTRATION.md             # ICDM 2026 Paper 2 pre-registration (H1-H6, kill criteria)
├── RESEARCH_PROPOSAL_PAPER_1.md    # Paper 1 design doc: contributions, experiments E1-E6, timeline
├── RESEARCH_PROPOSAL_PAPER_2.md    # Paper 2 design doc: taxonomy, experiments E-A-G, verdict rules
├── .env.example                    # Template for OPENROUTER_API_KEY, FIREWORKS_API_KEY, etc.
├── package.json                    # Node dependencies (pi-ai, commander, typescript, tsx)
├── tsconfig.json                   # TypeScript configuration
├── requirements.txt                # Python dependencies (dotenv, pyyaml)
├── LICENSE                         # Apache 2.0
├── NOTICE                          # Attribution (DABStep, pi-ai, etc.)
└── CITATION.cff                    # Citation metadata

[Excluded from git: node_modules/, .env, .git/, dist/, data/context/*.csv (>20MB), full session corpus (~1.8GB)]
```

---

## 2. Paper Status

### Paper 1: SCRIBE Method Paper (ICDM 2026 Research Track)

**Status:** Draft in progress  
**Target:** 10 pages IEEE 2-column + supplement (~25 pages)  
**File:** `paper/scribe.tex` (incomplete)

**Structure:**
1. Introduction (1.0pp) — money quote (role separation, not stronger model)
2. Related work (0.5pp) — ReAct, Reflexion, DS-STAR, AutoGen, MetaGPT
3. Role-conflation problem (1.25pp) — three failure modes (definition-shift, action-bias, iteration-cap)
4. SCRIBE architecture (1.5pp) — three roles, asymmetric assignment, escalation protocol
5. Evaluation (2.5pp) — DABStep easy/hard, hidden-test submission, LiveSQL zero-shot, 8-cell ablation
6. Failure analysis (0.5pp) — 3-4 example families, pointer to Paper 2 taxonomy
7. Related work (0.5pp)
8. Discussion & limitations (0.5pp)
9. Conclusion (0.5pp)
10. References (0.5pp)

**Key experiments to run:**
- E1: 8-cell role-separation ablation (Spec × Executor × Review each {Kimi, GPT-5})
- E2: Hidden test submission (DABStep leaderboard API)
- E3: LiveSQL full 270-task zero-shot deployment
- E4: 5-seed confidence intervals on canonical SCRIBE
- E5: Spec template library mining + transfer
- E6 (optional): DS-STAR with current models (Kimi+Gemini)

**Headline claim:** Role-separation beats frontier-solo at 3-5x lower cost; zero-shot cross-schema deployment without learning.

### Paper 2: Failure-Mode Taxonomy (ICDM 2026 Applied Track)

**Status:** Pre-registered (PRE_REGISTRATION.md); data-collection phase  
**Target:** 10 pages IEEE 2-column  
**File:** (to be written; sketch in RESEARCH_PROPOSAL_PAPER_2.md)

**Central thesis:** 13+ failure families on docs-heavy tasks, each classified as architecture-fixable (AF) or model-bound (MB), validated across DABStep, LiveSQLBench, Kramabench with four executor models.

**Pre-registered hypotheses:**
- **H1 (Counterfactual):** Opus solo 58-66%, GPT-5 solo 55-63%, SCRIBE 59.8% — role separation wins on combined.
- **H2 (Per-rule ablation):** 11 meta-rules in spec extraction; each single rule contributes to ≥1 family recovery.
- **H3 (Cross-benchmark):** ≥8/13 families transfer DABStep → LiveSQL; ≥5/13 → Kramabench.
- **H4 (Multi-executor):** Open-source executors (Kimi, GLM-5.1, DeepSeek, Qwen3-27B) all beat Opus solo.
- **H5 (Held-out replication):** Top-5 mitigations on 50-task held-out slice recover 24-36%.
- **H6 (De-overlapping):** Mechanism-based re-labeling reduces 184 residual failures to ≤180 unique.

**Kill criteria** (if true, Paper 2 is not submitted):
- K1: ≥4/6 hypotheses falsified → taxonomy lens is wrong.
- K2: Cross-benchmark transfer <3 families → DABStep-specific artifact.
- K3: Per-rule ablation shows zero isolated effects → spec prompt is inseparable.

**Key experiments to run:**
- E-A: Mechanism-based re-labeling (zero cost, 3 days analysis)
- E-B: Per-rule ablation matrix (~$200, 4 days)
- E-C: Cross-architecture comparison (~$500, 6 days)
- E-D: Multi-executor study (~$200, 4 days)
- E-E: Cross-benchmark transfer (~$200, 5 days)
- E-F: Capability-ceiling scaling (~$300, 4 days)
- E-G: Pre-registered held-out slice (~$50, 1 day, after E-A-F)

**Total cost:** ~$1,450, 6 weeks wall-clock with parallelism.

---

## 3. Harness Code Map

### Core Execution Flow (`src/run.ts`)

1. **Load config** from YAML (model, planner, execution params, connection).
2. **Resolve planner model** (`src/model_resolver.ts`):
   - OpenRouter (default: GPT-5 for spec/review)
   - Fireworks, Baseten, Anthropic-direct (for executor)
3. **Fetch specs** (if not cached):
   - Call `scripts/extract_specs.py` with task manifest
   - Emits `computation_plan` + `expected_output_format` per task
4. **For each task:**
   - **Spec Agent** (one-shot): calls planner with manual + question → spec
   - **ReAct Executor** (loop, max 40 iter):
     - **Tools available:** `run_python` (sandbox REPL), `ask_spec_agent` (escalation)
     - **Loop:** think → act → observe → repeat
     - **Termination:** correct answer printed + committed, or iter cap hit, or escalation
   - **Review Agent** (optional, triggered by escalation):
     - Same session as Spec (preserves context)
     - Re-reads source documents
     - Replies: `[No flag]` (confirm) or `[Flag: mistake detected]` (revised spec)
5. **Log session** as JSONL (one event per tool call, thinking block, etc.)
6. **Grade** with `scripts/grade.py` using DABStep official scorer

### Tools (`src/harness/tools/`)

**run_python.ts (400+ LOC):**
- Sandbox environment: isolated Python session per task
- Imports: pandas, numpy, json, re, etc. (allowlist in prompt)
- Execution: timeout 5 min per call, max 40 tool invocations per task
- Preamble: reads `CONTEXT_DIR`, loads datasets (lazy)
- Events: `tool_call` (code sent), `tool_result` (stdout + stderr + exceptions)

**ask_planner.ts (250+ LOC):**
- Structured escalation format: `# Step`, `# Computed so far`, `# Pseudo-code`, `# Assumptions`, `# Question`
- Calls Review Agent (planner model, same session)
- Reply parsing: `[No flag]` or `[Flag: mistake detected]` + revised spec
- Spec replacement: if flag, subsequent executor iterations use revised spec

**index.ts:**
- Tool registration with pi-ai
- Schema validation (input/output types)

### Services (`src/harness/services/`)

**session_logger.ts:**
- Records all events (tool_call, tool_result, assistant_response, assistant_thinking, etc.) to JSONL
- Path: `results/<run_id>/<task_id>/sessions/normal_agent.jsonl`

**token_tracker.ts:**
- Per-role token accounting:
  - Spec Agent: input (prompt + manual) + output tokens
  - Executor: all run_python token use
  - Review Agent: input (spec + escalation) + output tokens
- Aggregates to per-task cost (model-provider-dependent)

**python_repl.ts:**
- Subprocess management (spawns Python process, pipes I/O)
- Preamble injection (`import pandas as pd; import os; ...`)
- Dataset loading on first access (lazy, e.g., `payments.csv`)

**local_tracker.ts:**
- Local fallback tracker (when remote logging unavailable)
- Prints per-task timing and cost to console

### Hooks (`src/harness/hooks/`)

**prompt_cache.ts:**
- Anthropic prompt-caching integration
- Caches manual.md + schema context across tasks (within a run)
- Reduces cost for repeated schema reads

**after_tool.ts:**
- Post-tool-execution hooks (e.g., logging, metrics collection)

---

## 4. Experiment Results Inventory

### DABStep (Full 450-task dev set)

| Experiment | Result | File | Notes |
|---|---|---|---|
| **SCRIBE canonical** (Kimi exec + GPT-5 spec/review) | 269/450 (59.8%) | `results/v23_gpt5_hard_all378_FINAL.csv` + `v23_gpt5_easy_all72.csv` | Easy 69/72 (95.8%), Hard 200/378 (52.9%) |
| Easy-72 (detailed) | 69/72 (95.8%) | `results/v23_gpt5_easy_all72_summary.json` | Per-task: wall-sec, cost, iterations, ask_planner calls |
| Hard-378 (detailed) | 200/378 (52.9%) | `results/v23_gpt5_hard_all378_FINAL.csv` | Includes rescore variants (F8, F10, F12) |
| **Smoke test** | 4/5 pass | `results/repro_pilot/` | Tasks 1275, 1453, 1489, 17, 1739 |
| **GPT-5 solo (falsifier)** | 1-2/5 pass | `results/v23_gpt5_solo5_summary.json` | Same 5 tasks, higher cost ($0.37 vs $0.10) |
| **Kimi solo baseline** | 206/450 (45.8%) | `docs/failure_analysis/summary.md` | Canonical monolithic baseline |
| **Task-17 cross-planner** | Varies by spec author | `results/samples/task17_cross_planner/` | 6 traces: gpt5, gpt5.5, opus variants |
| **Opus solo (10x)** | Variance study | `results/v23_opus_x10_task17_extract.log` | 10 independent runs on task 17 |
| **44-regression recovery** | ~9/44 rescued | `results/hard_regressions44_rerun_union.csv` | Path-B escalation (3 sample traces) |
| **Quick-wins F8** | +1-2 recovery | `results/hard_all378_FINAL_qw_f8.csv` | Tooling-correction rescore |
| **Quick-wins F10** | +1 recovery | `results/v23_hard_quickwin_f10_summary.json` | Output-format fix |
| **Quick-wins F12** | TBD | `results/v23_hard_quickwin_f12_summary.json` | — |
| **Meta-rules pilot** | 3-5/5 pass | `results/v23_metarules_pilot5_summary.json` | Early-stage spec-format ablation |

### LiveSQL Bench (15 benchmark-specific schemas)

| Experiment | Result | File | Notes |
|---|---|---|---|
| **LiveSQL v1 (pilot)** | ~10/15 pass | `results/livesql_scribe_pilot/summary.json` | Earliest deployment; partial coverage |
| **LiveSQL v2** | ~12/15 pass | `results/livesql_scribe_v2/summary.json` | Spec-format improvements |
| **LiveSQL v3 (canonical)** | 15/15 pass | `results/livesql_scribe_v3/summary.json` | Current best; all 15 schemas correct |

**Schema coverage (v3):** alien, archeology, credit, crypto, cybermarket, disaster, insider, polar, robot, solar, virtual (15 unique schemas × task variants)

### Pending Experiments (Paper 1 + Paper 2)

**Paper 1 (E1-E6):**
- [ ] E1: 8-cell role-separation ablation (est. $400, 5 days)
- [ ] E2: Hidden test submission to DABStep leaderboard (est. $50, 1 day)
- [ ] E3: LiveSQL 270-task full deployment (est. $90, 3 days)
- [ ] E4: 5-seed confidence intervals (est. $200, 5 days, parallel with E1)
- [ ] E5: Spec template library mining + transfer (est. $30, 2 days)
- [ ] E6: DS-STAR with current models (optional, est. $80, 2 days)

**Paper 2 (E-A-G, pre-registered):**
- [ ] E-A: Mechanism-based re-labeling (zero cost, 3 days analysis)
- [ ] E-B: Per-rule × per-family ablation (est. $200, 4 days)
- [ ] E-C: Cross-architecture comparison (est. $500, 6 days)
- [ ] E-D: Multi-executor study (est. $200, 4 days)
- [ ] E-E: Kramabench deployment (est. $200, 5 days)
- [ ] E-F: Capability-ceiling scaling (est. $300, 4 days)
- [ ] E-G: Held-out replication (est. $50, 1 day, after A-F sealed)

---

## 5. Key Model & Configuration Choices

### Canonical SCRIBE Configuration (`scribe_main.yaml`)

| Role | Model | Provider | Rationale | Cost/task |
|---|---|---|---|---|
| **Spec Agent** | GPT-5 | OpenRouter | Docs-reading + contract authoring (low invocation) | ~$0.05 |
| **ReAct Executor** | Kimi-K2.6 | Fireworks | Bulk code generation + iteration (high invocation) | ~$0.25 |
| **Review Agent** | GPT-5 | OpenRouter (same session) | Spec verification + revision (optional escalation) | ~$0.03 |
| **Total per task** | — | — | Weighted average | ~$0.33 |

**Comparison to baselines:**
- Kimi solo (monolithic): $0.10/task, 45.8% accuracy
- GPT-5 solo (monolithic): $0.37/task, 20-40% accuracy (5-task sample)
- SCRIBE: $0.33/task, 59.8% accuracy (cost-effective orchestration)

### Provider Routing (Multi-shard parallelism)

During development, three backends were used for Kimi-K2.6:
- **Fireworks** (`accounts/fireworks/models/kimi-k2p6`): Primary, low-latency
- **Baseten** (`moonshotai/Kimi-K2.6`): Secondary, load distribution
- **OpenRouter** (`moonshotai/kimi-k2.6`): Fallback, unified API

Routing by task: see `shards` column in `results/*_union.csv` files.

### Spec Extraction (11 meta-rules)

**File:** `scripts/extract_specs.py` (394 LOC)

**Meta-rules embedded in spec prompt:**
1. Formula-to-code translation (formula from manual → pandas equivalent)
2. (Inferred) Definition-shift prevention (defensive patterns)
3. Non-default semantics (NULL handling, aggregation type)
4. (Inferred) Filter explicitness (list vs. scalar, wildcard semantics)
5. (Inferred) Grouping / aggregation level
6. (Inferred) ... (7-11 inferred from supplement S5)

**LiveSQL variant:** `scripts/extract_specs_livesql.py` (451 LOC)
- Adapted for relational schemas (foreign keys, multi-table joins)
- CTE patterns for pre-aggregation
- JSON path extraction rules

---

## 6. Key Research Decisions & Findings

### Failure-Mode Taxonomy (DABStep Kimi-solo baseline)

**Surface-level outcomes (450 tasks):**
- Correct: 206 (45.8%)
- Iter-capped (no commit): 97 (21.6%)
- Incorrect (committed wrong): 76 (16.9%)
- No-assistant-response: 35 (7.8%)
- Format mismatch: 32 (7.1%)
- NA-answered: 3 (0.7%)
- Connection error: 1 (0.2%)

**Root-cause failure families (from supplement S1):**
- **F1: Null-as-wildcard mishandling** (28 tasks) — solver filters NULL when question doesn't specify
- **F2: Definition-shift** (8 tasks) — quotes manual correctly in planning, writes contradicting code
- **F3: Fee-rule sum-vs-pick** (5 tasks, benchmark-specific) — convention not named in docs
- **F4: Token corruption / generation glitch** (8 tasks) — pure hallucination
- **F5: Benchmark/task ambiguity** (28 tasks, gold-side issue) — tie-breaking undefined
- **F6: Format/list-shape mismatch** (4 tasks) — output shape disagreement with spec
- **F7: Rounding inconsistencies** (6 tasks, gold-side issue)
- **F8: Compound what-if (MCC-change)** (7 tasks, partial)
- **Iter-cap modes:** compute-success-commit-failure (42), compute-failure (55)

**Planner-fixable vs. not:**
- ~45% of incorrect tasks are fixable via better spec/review
- ~30% are benchmark issues (gold-side ambiguity)
- ~9% are pure generation glitches (require retry)

### Definition-Shift Deep Dive (Task 17 canonical case)

**Question:** "What is the lowest avg fraud rate per merchant for 2023?"  
**Gold:** 8.91  
**Candidate interpretations:**
- H1: Pooled-annual VOLUME-weighted (8.907926) ✓ Matches gold
- H2: Pooled-annual COUNT-weighted (7.683437) ✗
- H3: Monthly-then-mean volume-weighted (8.894813) ✗
- H4: Monthly-then-mean count-weighted (7.838506) ✗
- H5: Daily-then-mean volume-weighted (8.872442) ✗

**Five spec-author experiment:**
- Mid-tier planner: hallucinated monthly structure → H3 (8.89) ✗
- Frontier planner (permissive): H2 (7.68) ✗
- Frontier planners (defensive): H1 (8.91) ✓ (3/3)
- Solo-executor (same model as best planner): H2 (7.68) ✗

**Conclusion:** Role separation fixes definition-shift; bigger model alone does not.

### Escalation Under-invocation Problem

**Empirical finding:**
- Easy-72: 6/72 (8.3%) invoked `ask_spec_agent`; when invoked, 6/6 (100%) success
- Hard-378: 25/378 (6.6%) invoked; 4/25 (16%) success
- **188/209 (90%) of hard failures never escalated despite having genuine ambiguity**

**Implication:** Executors lack self-uncertainty calibration (action-bias). SCRIBE mandates escalation at iter-15 to force the exit when stuck.

### Iteration-Cap Sub-modes

**97 iteration-capped tasks decompose as:**
- **Compute success, commit failure (42 tasks):** correct answer visible in print(), never returned
- **Compute failure (55 tasks):** correct answer never reached

**Interpretation:** Model lacks synthesize-and-commit reflex; RLHF-for-tool-use overweights "do another action."

### Variant-B Failure (Honest Negative Result)

**Attempted:** Domain-knowledge injection directly into executor prompt (test-set-derived rules, helpers, patterns).

**Result:** Marginal improvement (+2-3pp) at risk of test-set leakage. Abandoned in favor of zero-shot generalization claim.

**Documented in:** `docs/domain_knowledge.md`, `RESEARCH_PROPOSAL_PAPER_1.md` §9.

---

## 7. Git Remote Setup

```
origin:   https://github.com/axnr-inc/scribe.git
personal: https://github.com/Suraj-gameramp/scribe.git
```

**Usage:**
```bash
git push origin main           # Team repo (contains secrets in .env, rotate before push)
git push personal main         # Personal backup (after secrets rotation)
```

**Critical:** Before pushing, rotate all 7 API keys in `.env` (see `docs/notes/objective_doc.md` §8).

---

## 8. Running the Code

### Quick-Start (Smoke Test)

```bash
git clone https://github.com/axnr-inc/scribe.git
cd scribe
npm install && python3 -m pip install -r requirements.txt
node scripts/patch_pi_ai_env.js
cp .env.example .env && $EDITOR .env  # Fill API keys
python3 scripts/fetch_dabstep_data.py
bash scripts/repro.sh
```

**Expected:** 4/5 pass in ~5 min for <$1

### Full DABStep Run

```bash
npx tsx src/run.ts --config configs/scribe_main.yaml --split data/splits/hard_all378.jsonl --out results/hard378
python3 scripts/grade.py --pred results/hard378/results.csv --gold data/verified_answers.json
```

**Expected:** 192-200/378 pass (depending on provider variance)

### LiveSQL Deployment

```bash
npx tsx src/run.ts --config configs/livesql_scribe.yaml --split data/splits/livesql_*.jsonl --out results/livesql_v3
python3 scripts/grade_livesql.py --pred results/livesql_v3/results.csv
```

### Reproducibility Recipes

See `docs/reproducibility.md` for all six headline numbers with expected wall-time, cost, and output paths.

---

## 9. Documentation Reference

| Document | Purpose | Location |
|---|---|---|
| README.md | Quick-start + headline results | root |
| TRACES.md | Artifact inventory (experiment → file mapping) | root |
| PRE_REGISTRATION.md | Paper 2 pre-registration (H1-H6 hypotheses) | root |
| RESEARCH_PROPOSAL_PAPER_1.md | Paper 1 design doc | root |
| RESEARCH_PROPOSAL_PAPER_2.md | Paper 2 design doc | root |
| docs/architecture.md | Three-role topology, escalation protocol | docs/ |
| docs/reproducibility.md | Step-by-step reproduction recipes | docs/ |
| docs/openrouter.md | Provider routing, thinking, multi-shard setup | docs/ |
| docs/domain_knowledge.md | Variant-B (DK injection) postmortem | docs/ |
| docs/experiments/*.md | Ad-hoc experiment reports (7 files) | docs/experiments/ |
| docs/failure_analysis/*.md | Kimi-solo taxonomy (5 markdown files) | docs/failure_analysis/ |
| docs/notes/objective_doc.md | Master plan: two-paper structure, timeline, risks | docs/notes/ |
| paper/scribe.tex | Finding paper (draft) | paper/ |
| paper/scribe-supplement.tex | Supplement (draft) | paper/ |

---

## 10. Known Limitations & Next Steps

### Current Limitations

1. **Dev-set vs. hidden-test fairness:** Headline 269/450 (59.8%) is on DABStep dev set with consensus gold; DS-STAR numbers are from hidden test. Direct comparison requires leaderboard submission (E2).

2. **Best-of-N inflation:** SCRIBE figures include optional recovery pass (multi-attempt + spec revision). Single-pass numbers lower (~56-57% hard). Honest reporting: separate columns in paper table.

3. **Single executor model:** All results use Kimi-K2.6 as executor. Executor robustness to model swaps (GLM-5.1, DeepSeek, Qwen) is Paper 2 E-D.

4. **DABStep-only (so far):** 450-task benchmark. Cross-benchmark transfer to LiveSQL (270 tasks) and Kramabench (TBD) in Paper 2 E-E.

5. **Spec template library (Pillar 4):** Attempted Variant-B (test-set-derived patterns), marginal gains. Zero-shot library (structural patterns only) in Paper 1 E5.

6. **Open-weights "hosted" caveat:** Kimi-K2.6 requires external hosting (Fireworks, Baseten, OpenRouter). Not self-hostable on laptop.

### Next Steps (Sequenced)

1. **Paper 1 experiments (E1-E6):** ~3 weeks, ~$800 cost.
   - E1: 8-cell role ablation (critical for reviewer attack #5).
   - E2: Hidden test submission (critical for fairness).
   - E3: LiveSQL full deployment (zero-shot generalization claim).
   - E4: 5-seed CIs (reproducibility).
   - E5: Spec library mining (Pillar 4 validation).

2. **Paper 2 experiments (E-A-G):** ~6 weeks parallel (after Paper 1 baseline), ~$1,450 cost.
   - E-A: Mechanism re-labeling (pre-req for verdict assignment).
   - E-B: Per-rule ablation (causal attribution).
   - E-C: Cross-architecture comparison (verdict verdicts).
   - E-D: Multi-executor study (open-source robustness).
   - E-E: Kramabench deployment (cross-benchmark transfer).
   - E-F: Capability ceiling (frontier-solo vs. orchestration).
   - E-G: Held-out replication (sealed, pre-registered).

3. **Paper writing:** ~2 weeks each (after experiments), staggered:
   - Week 3-4: Paper 1 draft + figures.
   - Week 7-8: Paper 2 draft + taxonomy table.

4. **Submission:** ICDM abstract (2026-05-30), full paper (2026-06-06).

---

## 11. Contact & Artifacts

**Lead author:** suraj@actioneer.com  
**Artifacts on Zenodo:** (to be released with camera-ready paper)  
- `scribe-full-corpus.tar.gz` (~600 MB compressed; ~1.8 GB raw)
- `scribe-failure-analysis.tar.gz` (95 Kimi-solo traces, markdowns)

**License:** Apache 2.0 (see LICENSE)

---

**End of inventory. Last sync: 2026-06-05.**
