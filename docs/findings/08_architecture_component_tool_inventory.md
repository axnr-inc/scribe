# Architecture component tool inventory

Which model touches which tools, and what's deterministic vs LLM-driven. The complete picture as of 2026-06-06 (post-P2b spec_agent expansion).

## The component → tool matrix

| Component | Model | Provider | Tools accessible | Tool count | Type |
|---|---|---|---|---|---|
| **spec_agent** DABStep (P2b multi-shot) | GPT-5 | OpenRouter | `read_file`, `list_files`, `read_data_file`, `query_fees` (conditional on `fees.json`), `save_spec` | 5 | LLM with tool loop, MAX_TOOL_TURNS=5 |
| **spec_agent** Krama (P2b multi-shot) | GPT-5 | OpenRouter | `read_file`, `list_files`, `read_data_file`, `save_spec` | 4 | LLM with tool loop, MAX_TOOL_TURNS=5 |
| **spec_agent** LiveSQL (P2b multi-shot) | GPT-5 | OpenRouter | `read_file`, `list_files`, `sample_table`, `save_spec` | 4 | LLM with tool loop, MAX_TOOL_TURNS=5 |
| **executor** DABStep | Kimi-K2.6 | Fireworks2 | `run_python`, `ask_planner_agent`, `read_current_spec`, `verify_step` | 4 | ReAct loop |
| **executor** Krama | Kimi-K2.6 | Fireworks2 | `run_python`, `ask_planner_agent`, `read_current_spec`, `verify_step` (+ Krama helper manifest preloaded in REPL) | 4 | ReAct loop |
| **executor** LiveSQL | Kimi-K2.6 | Fireworks2 | `run_sql`, `ask_planner_agent`, `read_current_spec` | 3 | ReAct loop |
| **planner_agent** DABStep | GPT-5 | OpenRouter | `read_file`, `query_fees` (conditional on `fees.json` presence) | 2 | LLM with tool loop |
| **planner_agent** Krama | GPT-5 | OpenRouter | `read_file` | 1 | LLM with tool loop |
| **planner_agent** LiveSQL | GPT-5 | OpenRouter | `read_file` | 1 | LLM with tool loop |
| **EC5** (context-decay reminder) | — | — | iter counter, escalation counter | 0 | deterministic TS hook |
| **Tier A** (`[AUTO-INSPECT]`) | — | — | Python AST + DataFrame introspection | 0 | deterministic Python wrapper |
| **Tier B pattern-triggered** | — | — | Code regex + sqlglot AST | 0 | deterministic Python/TS |
| **Tier C `verify_step`** | — | — | 9 assertions (row_count, shape, column_exists, unique, non_null, null_rate_below, dtypes, value_in_range, value_in_set) | 0 | deterministic Python |
| **grader** | — | — | `question_scorer` (DABStep) / sqlite exec (LiveSQL) / per-answer_type (Krama) | 0 | deterministic Python |

## Key observations

### 1. spec_agent — P2b multi-shot loop (was starved, now armed)

**Pre-P2b state** (pilot v1, the 9/32 baseline): only `save_spec`, single LLM call, no iteration. Couldn't re-read docs, sample data, or verify before committing the spec.

**Post-P2b state** (current, used for pilot v2):
- 4-5 tools depending on benchmark (table above)
- Multi-shot via `scripts/spec_extraction_tools.py`: `MAX_TOOL_TURNS = 5`
- Penultimate-turn nudge prompts the model to finalize when 1 turn remains
- Final forced-save fallback if the model runs the tool budget without emitting a spec
- System prompt now mandates calling at least one verifier tool (`read_data_file` / `read_file` / `sample_table`) BEFORE `save_spec`, except when the user message already contains everything needed

This addresses the "spec_agent is the bottleneck" observation from docs 06+07. Effect to be measured in pilot v2.

### 2. Executor has the richest surface

5 tools registered for pandas benchmarks (incl. P1's `verify_step`); 3 for LiveSQL. The executor is where the most compute happens (Kimi-K2.6 + the bulk of token spend).

### 3. Planner is benchmark-aware via conditional tool registration

`query_fees` only registers when `fees.json` exists in `docsDir` (EC3 from earlier audit). For Krama and LiveSQL, the planner has only `read_file` — auto-listed manifest tells it which files exist per task.

### 4. Three deterministic layers (P1, EC5, graders)

These are 0-LLM components but do real work:
- **EC5** injects ~10-30 tokens per `tool_call_result` past iter 10 — modulates executor's working memory of escalation availability
- **Tier A/B** runs at every `run_python`/`run_sql` — costs ~5-20 ms per call
- **Tier C** runs only when invoked; ~5-10 ms per call
- **graders** run once per task at end

### 5. LiveSQL has fewest tools

3 executor tools vs DABStep+Krama's 4 (no `verify_step` — there's no DataFrame to verify in SQL paradigm). 1 planner tool (`read_file`). The LiveSQL paradigm has the LEANEST tool surface. This may be a factor in its weaker pilot result.

### 6. spec_agent R1-R5 — now actionable

R1-R5 (pre-reply re-read source documents, verify named concepts, etc.) was added to the **planner_agent** in P4 cleanup. With P2b's tool surface, the spec_agent can now act on R1-R5 patterns too (it has `read_file` + a sampler). The Krama spec_agent system prompt already requires at least one verifier-tool call before `save_spec`.

### 7. Krama HELPER_MANIFEST (paradigm-level helpers)

Krama tasks pre-load 5 paradigm-level helpers from `data/context/krama_helper.py` into the executor's Python REPL preamble (`src/run.ts:buildPreamble`, conditional on `task.context_dir`):

- `read_multi_header_excel(path, sheet, header_keywords)` — xlsx with non-row-0 headers
- `parse_missing_marker(df, cols, markers)` — sentinel-string missingness ("M" = NaN)
- `safe_dedupe(df, keys, agg)` — conflict-aware dedup (surfaces near-duplicate-key collisions)
- `linear_interp_by_key(df, key_col, value_col)` — chronology/year interpolation
- `bp_to_calendar_year(years_bp, reference_year=1950)` — BP → calendar year

The Krama spec_agent SYSTEM_PROMPT documents these so it can reference them by name in `computation_plan`. This is the Krama-paradigm analog of DABStep's domain-flavored `query_fees` — paradigm-level rather than domain-level because Krama spans 6 scientific domains with no shared business semantic. DABStep + LiveSQL do not get this preamble.

## Tool counts by benchmark (post-P2b)

| Benchmark | spec_agent tools | executor tools | planner tools | Deterministic tiers |
|---|---|---|---|---|
| DABStep | 5 (read_file, list_files, read_data_file, query_fees, save_spec) | 4 | 2 | EC5 + A + B + C |
| Krama | 4 (read_file, list_files, read_data_file, save_spec) + helper-manifest preamble | 4 | 1 | EC5 + A + B + C |
| LiveSQL | 4 (read_file, list_files, sample_table, save_spec) | 3 | 1 | EC5 + sqlglot only |

The asymmetry across benchmarks (e.g., `query_fees` for DABStep only) is now schema-driven: tools register conditionally on the presence of benchmark-specific artifacts (`fees.json` for DABStep, sqlite DB for LiveSQL, `context_dir` for Krama).

## What's still missing

- **No sub-task verifier when sub-task gold is available** (Krama provides this)
- **Executor doesn't have `query_fees` directly** — only spec_agent + planner do
- **No memorization-stripped evaluation** — pending obscured-input ablation per audit FLAG 2

## Related docs

- `02_cross_benchmark_fairness.md` — what asymmetries exist
- `09_pandas_bias_in_architecture.md` — by-design pandas-flavor of the stack
- `10_stronger_spec_extraction_proposal.md` — the proposed P2b roadmap
