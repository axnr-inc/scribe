# Source → finding cross-reference

For paper-writing: each substantive design choice or empirical claim traced back to the source that motivated it. Sources include the user-shared blogs/papers + lit reviews we ran ourselves.

## User-shared sources

### Blog 1 — "The Six Failures of Text-to-SQL" (Karl Weinmeister, Google Cloud, Nov 2025)
- **Sequential vs LoopAgent pattern** → motivates our pre-commit gate as a deterministic check before final-answer emission. We DON'T adopt their full ADK SequentialAgent because the cascade design is more flexible.
- **`sqlglot.parse_one(sql)` AST validation** → Tier B sqlglot pre-flight (`docs/findings/05a_p1_verifiers_design.md`; `src/harness/tools/run_sql.ts`). Direct adoption.
- **`AfterAgentCallback` for output normalization** → our `after_tool` hook (EC5, AUTO-INSPECT). Same architectural pattern.
- **Specialist agents per failure mode** → Spec_agent / Executor / Planner_agent split (architectural precedent).
- **`FunctionTool` wrapping deterministic Python** → Tier C `verify_step` design pattern.

### Blog 2 — "Why text-to-SQL fails" (Jamie Davidson, Omni, April 2026)
- **"LLMs need governed definitions, not raw schema"** → motivates HELPER_MANIFEST for DABStep AND why LiveSQL needs equivalents (`09_pandas_bias_in_architecture.md`).
- **Semantic-layer thesis** → why P2b.2 includes `query_fees`/`sample_table`/`read_data_file` for spec_agent. Without governed access patterns, spec_agent hallucinates.
- **"Metric drift" from raw-schema generation** → reinforces our spec-versioning audit log (every revision traceable).

### Distyl AI — "The Death of Schema Linking?" (arxiv 2408.07702v2)
- **"Better models don't need filtered schema; full-context recall is fine"** → why our extractors load FULL `manual.md`/`fees.json`/`schema.txt`/KB into spec_agent's user message rather than RAG-filter (`08_architecture_component_tool_inventory.md`).
- **Empirical evidence schema-linking is a *crutch*, not durable** → motivates spending capability budget on spec_agent verification (P2b) rather than retrieval optimization.

### "Harness Updating Is Not Harness Benefit" (arxiv 2605.30621)
- **"Capability budget should sit in the task-solving agent"** → our asymmetric assignment (stronger executor Kimi-K2.6 + lighter-call planner GPT-5) (`11_research_insights.md` Insight 4).
- **"Harness updating is flat across capability tiers"** → why we don't try to make EC5/cascade self-evolving. Keep harness deterministic.
- **"Activation gap (SLR) vs adherence gap (HFR)"** → motivates EC5's *recurring* (not just initial) reminder design.

### DABStep paper (arxiv 2506.23719)
- **F-A iter-cap failure mode** (their A.4 trace: "the agent had the rule in memory but didn't use it") → directly mapped to our F-A category (`01_harness_vs_model_failure_modes.md`).
- **F-D no-escalation pattern** (their 90% under-escalation rate) → motivates EC5 + mandatory pre-commit gate.
- **Self-attention vs conceptual-similarity hypothesis** (their Appendix) → mechanistic explanation for F-A.
- **45% spec/planner-fixable; 30% benchmark-noise; 9% pure generation glitches** → realistic ceiling expectations.

### KramaBench paper (arxiv 2506.06541)
- **"Gold files lift accuracy only 0-7%"** → P1 expected-lift bound (+5-12% from Self-Debug envelope) (`05b_verifier_lit_review.md`).
- **Design / implementation / E2E decomposition** → motivates our future per-component scoring (deferred).
- **smolagents-DR's retrieve-revise-repeat winning** → architectural precedent for our cascade.
- **"24-43% failures from failure-to-ask-clarification"** → motivates verbose escalation prompts (`docs/findings/06_krama_failure_analysis.md`).
- **Sub-task gold scoring framework** → motivates P2b.5 (external-verifier-guided extraction).
- **Obscured-input experiment (62 → 13% drop)** → cautionary note for cross-benchmark generalization claims.

### Claude-chat synthesis you shared (the long meta-document)
- **"Durable vs crutch harness components" framework** → our `09_pandas_bias_in_architecture.md`. We acknowledge HELPER_MANIFEST/Tier-C-pandas-only are likely-durable (privileged-domain helpers) but spec extraction quality is reasoning that better models will absorb.
- **"Pipeline design vs implementation are decoupled"** (Krama Table 8) → motivates spec_agent + executor split, and why P2b strengthens spec extraction specifically.
- **"Smolagents-DR wins via tight feedback coupling"** → architectural precedent for executor↔planner cascade.

## Self-run lit reviews

### Verifier vocabulary lit review (during P1)
- **Great Expectations / pandera / dbt-expectations / Soda / deequ convergence on 6 families** → 9-assertion v1 vocab (`05a_p1_verifiers_design.md`).
- **AlphaCodium anchor-test pattern** (arxiv 2401.08500) — test-anchored iterative flow → motivates P2b.5.
- **Self-Debug (arxiv 2304.05128)** — execution-as-verifier → motivates always-on Tier A/B feedback.
- **"Judge's Verdict" (arxiv 2510.09738)** — LLM-judge κ=0.10-0.21 → explicit NO LLM-judge in inner loop policy (`05a_p1_verifiers_design.md`).
- **Snorkel "Self-Critique Paradox"** — unconditional self-critique hurts → motivates conditional EC5 + opt-in `verify_step`.

### Reflection-frequency lit review (during P1)
- **"Most debugging finishes in 3 rounds"** (Self-Debug) → 3-revision cap on SPEC_WRONG.
- **Huang et al. "LLMs Cannot Self-Correct Reasoning Yet"** (arxiv 2310.01798) — GPT-4 GSM8K 95% → 89% with 2 self-correction rounds → reinforces NO unconditional self-correction.
- **Stechly et al. "Self-Verification Limitations"** (arxiv 2402.08115) — performance collapse → motivates external-tool feedback over self-critique.

### Pattern-triggered hooks lit review (during P1)
- **DataSciBench TFC programmatic rules** (arxiv 2502.13897) → row-count, shape, null-rate assertion families.
- **Snowflake Cortex Analyst's Error Correction Agent** → motivates the pre-commit gate pattern.

## Things sources told us NOT to do

- **No LLM-judge in inner loop** ("Judge's Verdict" + KramaBench's Reflexion-vs-DR result)
- **No unconditional self-critique** (Snorkel + Huang)
- **No rigid plan-then-execute** (KramaBench PDT 7-12% vs DR 55%)
- **No multi-agent supervisor without strong base loop** (KramaBench Reflexion 55.37% vs single 55.83%)
- **No filter/schema-linking for strong models** (Distyl)
- **No retrieval optimization (gold-files lift 0-7%)** (KramaBench)
- **No always-on reflection** (Self-Debug saturates at 3 rounds; Huang shows degradation past 2)
- **No assertion-vocabulary maximalism** — picked 9 cross-stack-canonical assertions, not all 300 of Great Expectations.

## Things sources told us TO do (and we did)

- ✓ Specialist agents (spec / executor / planner) — Blog 1
- ✓ Governed-definition substitute (HELPER_MANIFEST) — Blog 2
- ✓ Full-context loading for strong models — Distyl
- ✓ Asymmetric model assignment — "Harness Updating ≠ Benefit"
- ✓ Cascade with deterministic feedback — KramaBench + Self-Debug
- ✓ sqlglot AST pre-flight — Blog 1
- ✓ AfterAgentCallback / hook pattern — Blog 1
- ✓ 3-iteration cap on revisions — Self-Debug
- ✓ Opt-in verify_step + auto deterministic checks — DataSciBench + lit review synthesis
- ✓ Recurring escalation reminder (EC5) — "Harness Updating ≠ Benefit" activation-gap finding + lost-in-the-middle literature
- ✓ Document cross-benchmark methodology asymmetries — KramaBench's obscured-input caution

## Things sources told us TO do but we HAVEN'T yet

- ✗ Per-subtask gold verification (KramaBench provides; we don't use it yet) → P2b.5
- ✗ Self-consistency sampling (mentioned in lit review) → P2b.4
- ✗ Symmetric helper libraries for non-pandas paradigms → `09_pandas_bias_in_architecture.md` open item
- ✗ External SQL execution verifier (Self-Debug pattern for SQL) → covered partially by sqlglot but not by gold-output comparison
- ✗ Multi-shot reasoning during spec extraction → P2b.3
- ✗ spec_agent tool surface → P2b.1 + P2b.2

The first 6 are NEXT-STEP work and are exactly what P2b proposes.

## Related docs

- `06_krama_failure_analysis.md` + `07_livesql_failure_analysis.md` — empirical basis
- `10_stronger_spec_extraction_proposal.md` — the next intervention
- `11_research_insights.md` — paper-worthy claims (also cross-references where they came from)
