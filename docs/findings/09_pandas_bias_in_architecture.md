# The pandas bias in SCRIBE's architecture

The SCRIBE harness was designed first for DABStep (pandas-heavy, fee-rule matching), extended cleanly to KramaBench (pandas-heavy, data-lake pipelines), and adapted (less cleanly) to LiveSQLBench (SQL CTEs over per-task sqlite DBs). Across multiple audit rounds we've normalized the cascade structure and tool dispatch — but the **PANDAS PARADIGM HAS A STRUCTURAL ADVANTAGE** in this stack. This document acknowledges the bias explicitly and catalogs each manifestation.

## Where the bias shows up

### 1. HELPER_MANIFEST (DABStep only)

`scripts/extract_specs.py:177-218` injects a ~40-line list of canonical Python helpers (`list_match`, `scal_match`, `rule_applies`, `fee_for_rule`) into the DABStep spec_agent's user prompt. The actual Python code is at `data/context/dabstep_helper.py` and gets loaded into the executor's REPL preamble. spec_agent says "use rule_applies(rule, txn, merchant_ctx)" instead of inlining 30 lines of wildcard-matching pandas. DABStep computation_plans go from ~25 steps to ~8.

**No LiveSQL or Krama equivalent.** Documented as Asymmetry 1 in `02_cross_benchmark_fairness.md`.

### 2. `query_fees` (DABStep only)

A planner_agent tool that does deterministic wildcard-matching over `fees.json` and returns matching `rule_id`s. Conditionally registered via `hasFeesJson(docsDir)` — exists only on DABStep. **No LiveSQL/Krama analog.**

### 3. P1 Tier C `verify_step` is DABStep+Krama-only

LiveSQL executor uses `run_sql`, not `run_python`. There are no DataFrames in the REPL view. `verify_step` is registered for DABStep+Krama only.

**Result**: LiveSQL gets 0 of the 9 Tier-C assertions.

### 4. P1 Tier A `[AUTO-INSPECT]` is pandas-only

Auto-prints `df.shape`, `df.dtypes`, `df.head(3)` when a DataFrame is the last expression. No SQL analog (run_sql already returns row samples).

### 5. P1 Tier B pattern-triggers are pandas-heavy

- `.groupby(` → row-count assertion (pandas only)
- `.merge(`/`.join(` → row-growth check (pandas only)
- boolean mask → non-empty-after-filter (pandas only)
- `sqlglot.parse_one(sql)` → SQL parseability check (LiveSQL only — but Kimi's SQL is always parseable, so this fires 0 times)

5 of 5 LiveSQL pilot tasks had clean SQL syntax → sqlglot caught nothing.

### 6. Structured-summary headers default to pandas

DABStep + Krama use `# Pseudo-code`. LiveSQL uses `# SQL`. Planner's R3 ("Verify the spec's structural plan") explicitly mentions "computation_plan / cte_plan / pipeline plan / matching logic" but the *default* framing of the planner system prompt was pandas-first (now generalized, but the bias is historical).

### 7. spec_agent meta-rules are pandas-flavored

`extract_specs.py`'s SYSTEM_PROMPT meta-rules say:
- "FORMULA-TO-CODE TRANSLATION" (pandas)
- "TRANSLATE NON-DEFAULT SEMANTICS INTO PANDAS PATTERNS"

`extract_specs_krama.py` says:
- "COMPUTATION PLAN IS CONCRETE PANDAS"
- "use pandas function names, actual column names from the samples"

`extract_specs_livesql.py` does explicitly use SQL semantics — but it had 11 meta-rules vs DABStep's 5 and Krama's 6, suggesting a more compensatory design. The audit flagged this as worth consolidating (deferred).

### 8. LiveSQL had to add its own MANDATORY pre-commit gate

The other 2 benchmarks had only soft iter-15 escalation rules. LiveSQL's prompt explicitly says "**YOU MUST call ask_planner_agent before printing FINAL SQL**" — a paradigm-specific compensation for the lack of mid-computation feedback (run_sql commits and you can't iterate easily). The recent audit-fix propagated a similar gate to DABStep+Krama.

## Why the bias

1. **DABStep was the first benchmark.** SCRIBE was designed against it. The pandas paradigm was the default.
2. **KramaBench fits the DABStep mental model** (data-lake → pandas pipeline). Adding it was straightforward.
3. **LiveSQLBench is a different paradigm** (text-to-SQL). It was retrofitted into a pandas-first architecture.

This is the standard "architecture was designed for paradigm A, extended to paradigm B at a cost" pattern.

## What does it cost?

Looking at pilot pass rates:
- DABStep historical: 269/450 (59.8%) on Hard split with original v3 helpers
- Krama archeology pilot 12: 5/12 (42%) with current stack
- LiveSQL pilot 10: 1/10 (10%) with current stack

The LiveSQL gap is large. Some of this is task-set selection (we sampled 10 from a larger distribution that includes hard tasks); some is the structural pandas-bias.

For comparison: LiveSQLBench paper reports o3-mini at 44.81%. Our 10% pilot is well below that — but our sample is small and includes hard tasks.

## What we've done about it

Across audit rounds (P2 → P4 cleanup):

| Asymmetry | Status |
|---|---|
| Planner system prompt was DABStep-flavored ("fee-rule catalogue", `query_fees`) | **Fixed** — generic-language rewrite in P4 (Agent 4 of round 2 audit) |
| LiveSQL extractor only supported Anthropic | **Fixed** — P4 cleanup added OpenRouter + Fireworks + Fireworks2 |
| LiveSQL config used Sonnet planner, 25 iters, thinking=high (Asymmetry 5) | **Fixed** — normalized to GPT-5, 40 iters, thinking=null |
| LiveSQL prompt YAML used old `ask_spec_agent` + flag format | **Fixed** — P2 port |
| LiveSQL spec_renderer was missing (used DABStep's, mostly empty output) | **Fixed** — `renderLivesqlSpec` added |
| LiveSQL validateRevisedSpec used DABStep required fields | **Fixed** — `requiredFieldsForSpec` dispatcher |
| LiveSQL spec_agent had dead R1-R5 block | **Fixed** — P4 cleanup removed |

## What we haven't done

| Asymmetry | Status |
|---|---|
| HELPER_MANIFEST is DABStep-only | **Open** — would require writing canonical helpers for LiveSQL (`latest_record_per_entity.sql`, `json_extract_with_default.sql`) and Krama. Substantial work. |
| `query_fees` is DABStep-only | **Open** — analogous tools for LiveSQL (e.g., `query_kb_formulas`) would help |
| `verify_step` is pandas-only | **Open** — SQL-side assertions (`column_exists_in_schema`, `query_returns_rows`) not yet built |
| spec_agent meta-rules count: LiveSQL 11 vs DABStep 5 / Krama 6 | **Open** — consolidate LiveSQL or amplify others. Currently asymmetric quantity. |
| spec_agent has no read_file/sample-data tools (P2b) | **Open** — most-impactful deferred item |

## Is this bias acceptable?

It depends on the research question:
- **"Can SCRIBE work on multiple paradigms?"** → Yes, demonstrated. All 3 work end-to-end.
- **"Does SCRIBE generalize equally across paradigms?"** → No. Pandas paradigms benefit more from the harness as currently designed.
- **"Should we publish cross-benchmark comparisons?"** → Yes, but disclose the asymmetries (HELPER_MANIFEST + verify_step are pandas-only) explicitly in the methodology section.

## What would equalize it

Three steps in priority order:

1. **SQL helpers for LiveSQL**: write `data/context/livesql_helper.sql` with canonical CTE patterns (latest-record-per-entity, json-extract-with-default, threshold-bucketing). Estimated lift: +5-10% on LiveSQL pilot.

2. **SQL Tier C assertions**: extend `verify_step` to accept SQL-side checks (`column_exists_in_schema`, `query_returns_rows`, `column_value_distribution`). Plumb into LiveSQL executor. Estimated lift: +3-7%.

3. **Spec_agent data-sampling**: P2b. Give spec_agent the ability to RUN small queries against the sqlite DB during extraction. Verify formula paths and JSON paths against actual values. Estimated lift: +10-20% on LiveSQL (the biggest lever).

## Related docs

- `02_cross_benchmark_fairness.md` — what asymmetries exist
- `08_architecture_component_tool_inventory.md` — per-component tool counts
- `10_stronger_spec_extraction_proposal.md` — P2b roadmap
- `11_research_insights.md` — paper-worthy methodology stance
