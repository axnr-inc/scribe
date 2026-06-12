# LiveSQL pilot 10 — failure analysis

**Date:** 2026-06-06
**Setup:** Kimi-K2.6 executor (Fireworks) + GPT-5 spec_agent + GPT-5 planner_agent (OpenRouter) + EC5 + P1 verifiers active. LiveSQL config normalized to match DABStep/Krama defaults (no Sonnet planner, 40 iters, thinking:null).
**Task set:** 10 tasks from `data/splits/livesql_pilot10.jsonl`, sampled from `livesql_harness_tasks.jsonl`.

## Headline

**1/10 PASS (10%).** crypto_8 only.

For comparison:
- LiveSQLBench paper o3-mini: 44.81%
- Pre-P2 SCRIBE LiveSQL v3 on hand-picked failing15: 15/15 (NOT a fair comparison — those were tasks pre-selected to succeed)
- Krama same-day pilot: 42%

**LiveSQL is the worst performer in our 3-bench pilot.** Two structural reasons (discussed in `09_pandas_bias_in_architecture.md`):
1. Architecture is more pandas-flavored than SQL-flavored
2. SQL specs have more structured fields (cte_plan + kb_formulas + json_columns + join_path) — more surface area for spec_agent to get wrong

## What the harness layer did

- 15 escalations across 10 tasks (1.5 avg per task)
- **6 `SPEC_WRONG` verdicts** across 3 tasks (alien_3, crypto_6, virtual_10)
- **virtual_10 hit the 3-revision cap** (3 SPEC_WRONG, still wrong)
- 0 sqlglot parse failures (all SQL syntactically clean — Tier B `sqlglot_parses` did nothing because SQL was always parseable)
- 1 no_sql (archeology_6)
- 0 Python errors

## Failure taxonomy (the 9 failures)

| Task | Diff | Status | CTEs | KB formulas | Verdicts | Diagnosis |
|---|---|---|---|---|---|---|
| alien_3 | Simple | wrong | 4 | 2 | SPEC_WRONG ×2 → ANSWER | LIF formula likely wrong; 2 revisions didn't fix |
| **archeology_6** | Moderate | **no_sql** | 3 | 3 | ANSWER | Executor never emitted `FINAL SQL` despite planner ANSWER — **F-A pattern (compute-success commit-failure)** |
| archeology_9 | Moderate | wrong | 7 | 2 | ANSWER | Per-site averages: 7-CTE pipeline; aggregation level likely wrong |
| credit_5 | Simple | wrong | 2 | 1 | ANSWER | LTV ratio; simple but `json_extract` paths likely wrong |
| credit_7 | Moderate | wrong | 5 | 4 | ANSWER | Quarterly cohort logic — 5 CTEs + 4 KB formulas, high complexity |
| crypto_6 | Moderate | wrong | 4 | 1 | SPEC_WRONG → ANSWER | Spread Percentage from order book; planner caught 1 bug, executor still wrong |
| cybermarket_10 | Simple | wrong | 2 | 1 | ANSWER | VRS calculation; formula coefficient or weighting wrong |
| polar_4 | Moderate | wrong | 4 | 2 | ANSWER | Renewable equipment metrics; aggregation level issue likely |
| **virtual_10** | Moderate | wrong | 7 | 3 | **SPEC_WRONG ×3** (hit cap) | Fan Engagement Index — 3 revision cycles, planner kept finding new issues, never converged |

## crypto_8 (the one pass)

The simplest spec: 3 CTEs, 1 KB formula (Effective Leverage), no SPEC_WRONG. Clean structure → executor implemented → planner verified → committed.

Pattern: **complex specs fail more.** The 1 pass had 1 KB formula. The 9 failures had 1.9 KB formulas on average (range 1-4) and 4.0 CTEs on average (range 2-7).

## Critical pattern: SPEC_WRONG fires but doesn't fix

| Task | SPEC_WRONG count | Final result |
|---|---|---|
| alien_3 | 2 | wrong |
| crypto_6 | 1 | wrong |
| virtual_10 | 3 (hit cap) | wrong |

**6 SPEC_WRONG verdicts across 3 tasks, 0 of those 3 passed.** The planner can identify *some* bugs in the spec but the chosen revision doesn't always fix the underlying issue. Same pattern as Krama hard-2.

The planner's R1-R5 verification (added P4 cleanup) is finding *some* spec gaps — but the gap it identifies isn't necessarily the gap that distinguishes the executor's answer from gold.

## archeology_6 (no_sql) is structurally different

This is the LiveSQL analog of Krama easy-6's F-A:
- Planner emitted ANSWER (so executor was nominally cleared to commit)
- But no `FINAL SQL:` line was ever emitted in the executor's response
- Task graded as `no_sql` (no SQL extractable)

Why? Looking at the trace: the executor's last `assistant_response` may have explained its reasoning but didn't end with the explicit `FINAL SQL:` token the LiveSQL grader requires. F-A across paradigms is the same: executor stops before final commit. EC5 would have helped earlier in the trajectory, not here.

## Implications

1. **The LiveSQL spec schema (`cte_plan` + `tables_needed` + `kb_formulas` + `join_path` + `json_columns`) has more surface area for spec_agent errors than the Krama/DABStep schemas.** Each field is a potential source of mismatch with gold intent.

2. **`json_extract()` is the silent killer.** Many LiveSQL tasks involve nested JSON columns. The spec specifies the path. If the path is wrong, the executor produces NULLs or wrong types — no Python error, just silent wrong-answer. P1 Tier C `non_null` would catch this if the executor called it on the right columns.

3. **Multi-revision SPEC_WRONG doesn't converge.** virtual_10 went 3 rounds. Each round the planner found a *different* gap. None fixed the actual problem.

4. **LiveSQL prompt YAML's MANDATORY pre-commit gate is the strongest single intervention** — 15/10 escalation rate is the highest across all 3 benchmarks. But escalation ≠ correctness when the planner can't catch the real bug.

## What this validates about the harness

- ✓ Spec versioning works at scale: 6 SPEC_WRONG revisions across the pilot, no corruption, 3-revision cap enforced correctly
- ✓ Pre-commit gate is reliable (15/10)
- ✓ Cascade structure is paradigm-portable (same code path, just `run_sql` instead of `run_python`)
- ✓ sqlglot pre-flight works (0 fails because Kimi's SQL is always syntactically clean — verifier silent because there's nothing to verify)

## Per-component lift attribution

- **MANDATORY pre-commit gate**: Strong effect (15 escalations on 10 tasks). Without it we'd see DABStep-1712-style iter-caps.
- **sqlglot Tier B**: 0 fires. Either Kimi's SQL is always parseable (likely) or our regex pattern triggers don't catch errors before execution.
- **verify_step (Tier C)**: 0 fires. Executor never opted in. Probably because LiveSQL's spec is in CTE-language and executor doesn't think in DataFrames at runtime.
- **SPEC_WRONG cascade**: Mechanism works; chosen revisions don't fix the underlying problem.

## Why LiveSQL is more broken than Krama

1. **More complex spec schema** (5 fields vs Krama's 3 substantive)
2. **JSON extraction is fragile** — wrong path = silent NULL = wrong number
3. **Spec_agent doesn't see actual data values** during extraction — it sees schema + KB JSONL + column meanings only. For JSON-heavy tasks, this is insufficient.
4. **KB formulas are interpretation-dependent** — translating "Fan Engagement Index" prose into SQL requires creative judgment that's hard to verify against docs alone.

## Implications for next intervention

Priority order:
1. **P2b spec_agent tool surface** (the deferred item): Give spec_agent the ability to RUN sample queries against the sqlite DB during extraction. This is the single biggest lever.
2. **Tier C usage prompting**: Force the executor to call verify_step at least once before final commit (mandatory mode, similar to pre-commit gate).
3. **Multi-spec sampling**: Extract 3 specs per LiveSQL task with different temperatures; majority-vote or merge.
4. **External SQL execution verifier**: Run the executor's SQL against the gold SQL on a test DB; compare row counts and column shapes. Self-Debug pattern.

## Related docs

- `06_krama_failure_analysis.md` — companion Krama analysis
- `08_architecture_component_tool_inventory.md` — which component has which tools
- `09_pandas_bias_in_architecture.md` — why LiveSQL is second-class
- `10_stronger_spec_extraction_proposal.md` — proposed P2b roadmap
- `11_research_insights.md` — paper-worthy claims
