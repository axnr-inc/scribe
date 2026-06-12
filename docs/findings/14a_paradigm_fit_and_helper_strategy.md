# Paradigm fit: SCRIBE for docs-heavy iterative computation, not text-to-SQL

This document addresses two related questions:
1. Is LiveSQLBench fundamentally a different paradigm from DABStep/KramaBench?
2. Should we build HELPER_MANIFEST equivalents for LiveSQL and Krama?

The short answers: **yes, fundamentally different**, and **partially yes — but for a different reason than DABStep's helpers, and lower priority than P2b spec_agent enhancements.**

## The paradigm difference

SCRIBE's mental model is **"docs-grounded iterative computation"**:
1. Spec_agent reads docs → emits structured computation plan
2. Executor implements the plan iteratively (compute → inspect → refine via many `run_python` calls)
3. Planner reviews when executor is uncertain
4. EC5 keeps escalation option in working memory

This fits DABStep and Krama precisely. It does NOT fit LiveSQLBench, which is fundamentally text-to-SQL.

| Dimension | DABStep | Krama | LiveSQL |
|---|---|---|---|
| **Output unit** | Final answer (number/list) | Final answer (number/list) | **A SQL query** (`FINAL SQL: ...`) |
| **Compute style** | Iterative pandas (many `run_python` calls) | Iterative pandas (many `run_python` calls) | **Single SQL emission**, DB executes |
| **Source of truth** | manual.md + fees.json (docs) | data lake files (data) | KB JSONL + schema (docs) → SQL → DB |
| **Iteration scope** | 10-40 cells before commit | 5-15 cells before commit | **1-2 SQL refinements, then emit** |
| **What "correct" means** | Right number/string | Right number/string | **SQL that returns gold-equivalent rows** |

### Why SCRIBE struggles on LiveSQL

The harness is built for the LEFT TWO columns:
- ReAct loop with `run_python` → iterative inspection and refinement
- `verify_step` (Tier C) operates on DataFrames in the REPL — LiveSQL has no DataFrames
- `[AUTO-INSPECT]` shows `df.shape/dtypes/head()` — no DataFrame analog in SQL
- Pattern-triggered Tier B (`.groupby()`, `.merge()`) — pandas-only patterns

When applied to LiveSQL, the harness "works around" the paradigm:
- The MANDATORY pre-commit gate compensates for the lack of mid-computation feedback
- sqlglot pre-flight is the only SQL-paradigm verifier in P1 (and 0 fires in our pilot because Kimi's SQL is always syntactically clean)
- Spec rendering (`renderLivesqlSpec`) was added post-hoc

### What WOULD fit LiveSQL natively

A text-to-SQL-specific architecture would look more like:
- **AlphaCodium**: test-anchored iterative SQL refinement
- **Snowflake Cortex Analyst**: deterministic compile + retrieval-of-known-good queries
- **CHASE-SQL / DIN-SQL / ReFoRCE**: SQL self-debug with execution feedback

SCRIBE on LiveSQL = 1/10 pilot. CHASE-SQL on BIRD = 73%. The paradigm-fit gap is real.

### Implication for research paper framing

**The natural framing for SCRIBE is "docs-heavy iterative computation."** DABStep and Krama are its targets. LiveSQL gets included to demonstrate paradigm portability + honestly disclose limits.

Cross-benchmark numbers should disclose:
- DABStep and Krama are paradigm-fit; LiveSQL is portability-claim
- Pandas-specific tools (HELPER_MANIFEST, verify_step Tier C, AUTO-INSPECT) help paradigm-fit benchmarks more
- LiveSQL is harder for SCRIBE not just because text-to-SQL is harder generally, but because the harness shape is sub-optimal

## HELPER_MANIFEST for LiveSQL and Krama?

### Why DABStep's HELPER_MANIFEST works

DABStep has **structural homogeneity**: every one of 450 tasks is fee-rule matching. The same `rule_applies(rule, txn, merchant)` predicate applies to every task. The same `fee_for_rule(rule, eur_amount)` formula. Helpers encode the **single canonical interpretation** of business rules across the entire benchmark.

This is the *Omni semantic-layer thesis* (Blog 2): governed business definitions reduce LLM degrees of freedom. DABStep's helpers are the semantic layer for fee-rule matching.

### Why DABStep-style domain helpers don't translate

| Benchmark | Task domains | Why DABStep-style helpers fail |
|---|---|---|
| DABStep | 1 (fee-rule matching) | Same helpers apply to ALL tasks ✓ |
| LiveSQL | 15+ schemas (alien observatories, archeology, credit risk, crypto markets, fan engagement, ...) | Would need 15+ helper sets, each domain-specific |
| Krama | 6 domains (archeology, astronomy, biomedical, environment, legal, wildfire) | Would need 6 helper sets, each domain-specific |

LiveSQL's `credit_5` task is about LTV ratios; `alien_3` is about lunar phases. There is no shared business semantic that helpers could encode.

### What DOES translate: paradigm-level pattern helpers

Cross-domain, paradigm-specific helpers that catch common BUG patterns (not common business definitions):

**LiveSQL `data/context/livesql_helper.sql`** — canonical SQL/CTE patterns:
- `latest_record_per_entity(table, entity_col, date_col)` — the #1 most common LiveSQL pattern + #1 common error class
- `json_extract_with_default(col, path, default)` — handles missing JSON paths gracefully. **LiveSQL credit_5 failed here** (wrong path).
- `safe_division(num, den)` — avoids divide-by-zero in ratio computations. **LiveSQL cybermarket_10 VRS had this.**
- `cohort_quarter(date_col)` — quarterly cohort assignment. **LiveSQL credit_7 failed here.**
- `threshold_bucket(value, thresholds)` — categorical bucketing.

**Krama `data/context/krama_helper.py`** — canonical pandas data-cleaning patterns:
- `read_multi_header_excel(path, sheet, header_rows)` — multi-row headers. **Krama hard-2 needed this** (wet-dry index column).
- `parse_missing_marker(df, col, marker)` — "M means missing" type encoding.
- `safe_dedupe(df, keys, agg='last')` — dedup with explicit aggregation policy. **Krama hard-12 needed this** (3x overcount).
- `linear_interp_by_key(df, key_col, value_col)` — interpolation. **Krama hard-1 needed this.**
- `extract_year_from_bp(years_bp)` — BP-to-calendar conversion. **Krama hard-5 needed this.**

These are **paradigm-level**, not **domain-level**. They encode patterns that show up across multiple tasks AND map directly to pilot failures we observed.

### Expected lift

| Action | LOC | Estimated lift |
|---|---|---|
| Build LiveSQL paradigm helpers (5-7 CTE patterns) | ~200 + spec_agent prompt | **+5-10% on LiveSQL** (addresses 3-4 of our 9 pilot failures) |
| Build Krama paradigm helpers (5-7 pandas patterns) | ~200 + spec_agent prompt | **+3-5% on Krama** (addresses 2-3 of our 7 pilot failures) |
| Build DABStep-style domain helpers for LiveSQL/Krama | n/a | Wouldn't work — too domain-divergent |

## Priority: helpers AFTER P2b, not before

**P2b is the bigger lever.** If spec_agent can sample data + read files interactively (P2b.1 + P2b.2 + P2b.3), it will:
- Discover when to apply helper patterns (verifies JSON paths exist before specifying them)
- Catch the wrong-path JSON extractions (sample_table reveals actual values)
- Verify dedup policy choices (read sample rows, see what duplicates look like)
- Check interpolation assumptions (sample the data values)

**P2b somewhat substitutes for paradigm helpers** by making spec_agent smarter at extraction time. The spec it produces would already encode the correct path, the correct dedup policy, etc. — no need for canonical helpers to enforce them.

### Recommended sequence

1. **Finish P2b.1 + P2b.2 + P2b.3** (currently in flight). Measure lift.
2. If LiveSQL pilot improves to 20-30%, helpers may still help — implement LiveSQL paradigm helpers, measure marginal lift.
3. If LiveSQL pilot stays ≤ 15%, helpers are unlikely to close the gap on their own. The paradigm-fit issue dominates; consider a separate text-to-SQL-flavored architecture variant for that benchmark.
4. Krama helpers are lower priority — Krama is already at 42% which is competitive with smolagents-DR (44.4%). Diminishing returns to optimize further.

## The honest paper-writing implication

When framing SCRIBE for publication:
- **Lead with the paradigm-fit story**: SCRIBE is designed for docs-heavy iterative computation. DABStep and Krama are paradigm-fit benchmarks. LiveSQL is included to demonstrate portability + honestly disclose limits.
- **Don't over-claim LiveSQL**: a 10% pilot result on a sample of 10 tasks is not the main story. Be careful with extrapolation.
- **Lead with the Krama result**: 42% matching smolagents-DR Claude-3.7 with weaker base models is the cleanest empirical claim.
- **Disclose HELPER_MANIFEST asymmetry** as a known methodology limitation, with the planned mitigation (paradigm helpers).

## Open architectural questions

1. **Should LiveSQL get its own harness variant?** A text-to-SQL-focused SCRIBE could use sqlglot validation + LLM-judge for semantic equivalence + retrieved similar SQLs as prompts. Would be a separate research project.
2. **Are there other docs-heavy benchmarks SCRIBE should target?** BIRD-Interact, KramaBench's other domains, multi-step financial-analysis benchmarks. Worth scoping.
3. **Does the paradigm-fit story limit publication scope?** Probably. The honest paper is about docs-heavy iterative computation (DABStep + Krama), with LiveSQL as a portability nod. That's actually a stronger paper than a "we work on everything" framing.

## Related docs

- `09_pandas_bias_in_architecture.md` — the historical catalog of pandas-flavor in the stack
- `11_research_insights.md` — Insight 6 (pandas paradigm advantage)
- `12_3bench_pilot_synthesis.md` — the 3-bench numbers that motivate this analysis
- `10_stronger_spec_extraction_proposal.md` — why P2b is the bigger near-term lever
