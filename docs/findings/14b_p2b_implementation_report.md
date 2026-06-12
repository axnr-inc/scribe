# P2b implementation report

Implementation of P2b.1 + P2b.2 + P2b.3 from `10_stronger_spec_extraction_proposal.md`.
P2b.4 (self-consistency) and P2b.5 (external-verifier-guided) remain DEFERRED.

## P2b.1 — read_file tool

**Files modified**:
- `scripts/spec_extraction_tools.py` (new shared module: `execute_read_file`,
  `make_read_file_tool`, `make_list_files_tool`, `make_file_manifest`)
- `scripts/extract_specs.py` (DABStep — wires read_file + list_files)
- `scripts/extract_specs_livesql.py` (LiveSQL — wires read_file + list_files
  scoped to per-task `db_dir/<db_name>/`)
- `scripts/extract_specs_krama.py` (Krama — wires read_file + list_files
  scoped to per-task `context_dir`)

**Semantics** (canonical pattern from `src/harness/tools/ask_planner.ts:executePlannerReadFile`):
- `read_file(filename)` is restricted to files in the task's docs directory.
  Resolves the path relative to the allowed root and refuses traversal.
- Binary extensions (xlsx/parquet/sqlite/etc.) return a clear error pointing
  the model at the right harness tool (`run_sql` for sqlite, `run_python` /
  `read_data_file` for other binaries).
- 250 K char truncation matches `READ_FILE_TRUNCATE` in `ask_planner.ts`.
- Manifest: DABStep gets the rich hand-written `DABSTEP_FILE_MANIFEST` ported
  from `ask_planner.ts`. LiveSQL + Krama get an auto-listed manifest with file
  sizes and binary-extension tags.

**Verification**:
- `python3 -c "import ast; ast.parse(...)"` clean on all 3 extractors and the
  shared module.
- DABStep smoke (`dabstep_smoke1.jsonl`, task 1712, openrouter:openai/gpt-5):
  3 `read_file` calls before `save_spec`.

## P2b.2 — sampling tools

**Files modified**: same as P2b.1.

**New tools per benchmark**:

| Benchmark | Tools added |
|---|---|
| DABStep   | `query_fees(filters, limit=50)` — ported from `executePlannerQueryFees` in `ask_planner.ts`; identical wildcard semantics (null OR empty list = matches anything). |
| LiveSQL   | `sample_table(table_name, n=10)` — runs `SELECT * FROM <table> LIMIT n` against the task's SQLite DB (read-only URI); `describe_table(table_name)` — `PRAGMA table_info` returning column name + type + notnull + pk. |
| Krama     | `read_data_file(path, n_rows=15)` — multi-format sampler (CSV / XLSX / JSON / TXT / MD / TSV / Parquet) scoped to `task.context_dir`. Reuses the same shape conventions as the existing `sample_csv` / `sample_xlsx` helpers (`pandas.read_csv`, `pd.ExcelFile`). |

All 3 benchmarks also share `list_files()` for context discovery.

**Verification**:
- Manual exercising of each tool against real artifacts succeeded:
  `manual.md` (22 KB), `query_fees({"card_scheme": "NexPay"})` (5 rules),
  `describe_table("fans")` (8 columns on the virtual DB),
  `read_data_file("climateMeasurements.xlsx")` (returns sheet list + head).
- Sanity tests below confirm the model actually invokes the right tool.

## P2b.3 — multi-shot reasoning loop

**Files modified**: same as P2b.1, plus the loop drivers live in
`scripts/spec_extraction_tools.py:run_anthropic_spec_loop` and
`scripts/spec_extraction_tools.py:run_openai_spec_loop`.

**Loop design** (adapted from `ask_planner.ts:callPlannerAnthropic` /
`callPlannerOpenRouter`):
- Anthropic path: native `tool_use`, NO forced `tool_choice`. Loop terminates
  the moment the model emits a `save_spec` tool_use block.
- OpenAI-compat path (OpenRouter / Fireworks / Fireworks2): switched from
  `response_format=json_object` to OpenAI **function tools**. `save_spec` is
  registered alongside the helpers; the loop terminates when the model picks
  it. Bare-text JSON output is accepted as a fallback for models that prefer
  not to use tools.
- `MAX_TOOL_TURNS = 5` tool turns (matches the P2b.3 cap in the proposal).
  On the penultimate turn the loop appends a nudge instructing the model to
  call `save_spec` next; if the cap is hit without a save, a final call with
  `tools=[save_spec]` and forced `tool_choice` runs as a fallback so a spec
  is always emitted unless the API itself fails.
- Telemetry written into `<tid>.spec_session.json` metadata:
  `tool_calls_before_save`, `tool_call_log`, `hit_cap`, `forced_save`. Also
  surfaced into `spec._meta` for downstream auditing.

**Spec schema unchanged**: `save_spec`'s `input_schema` is identical to the
pre-P2b version for each of the three benchmarks. Specs produced by the new
loop are drop-in replacements.

**Verification**:
- AST parse clean on all 3 extractors + shared module.
- Sanity tests below.

## Sanity test results

Run with `--extractor openrouter:openai/gpt-5` against the 1-task splits in
`data/splits/`. All three benchmarks produced specs with at least one
helper-tool call before `save_spec`.

| Benchmark | Task | Status | Tool calls before save | Tool-call sequence | hit_cap | forced_save |
|---|---|---|---|---|---|---|
| DABStep | 1712 (Belles_cookbook_store, 12/Jan/2023 total fees) | OK — 13 plan steps | 3 | read_file × 3 → save_spec | False | False |
| LiveSQL | virtual_3 (tierstep fan breakdown) | OK — 4 CTEs, tables=`[fans, membershipandspending]` | 2 | describe_table × 2 → save_spec | False | False |
| Krama | archeology-hard-1 (Maltese Potassium interpolation) | OK — 5 key_functionalities, 67 plan steps | 2 | read_data_file × 2 → save_spec | False | False |

The DABStep spec for 1712 made 3 read_file calls (manual.md + merchant_data.json + payments-readme.md style consultations) before committing. The LiveSQL extractor used `describe_table` to verify the column shape of both relevant tables before drafting the CTE plan. The Krama extractor sampled the two xlsx data sources before committing.

## Caveats / next steps

- **Default model behaviour**: without the new "Required tool-use discipline"
  paragraph in each system prompt, gpt-5 frequently shipped a spec on turn 1
  (the user message already contains all source material). The added paragraph
  raises tool-use rate from 0 to 2-3 calls per task in our smoke tests. Models
  weaker than gpt-5 may still skip helper tools; consider strengthening to
  "MUST" if early ablation shows under-utilization.
- **Token cost**: DABStep extraction now uses ~610 K input tokens (vs ~150 K
  pre-P2b) on task 1712 because the full doc bundle is replayed across tool
  turns. For full-DABStep runs (450 tasks × ~600 K) this is meaningful but
  still within budget. Krama and LiveSQL stay cheap because their per-task
  context is small.
- **Anthropic key**: untested in this session (key reportedly dead). Loop
  driver shares all logic with the OpenAI-compat path and the Anthropic
  branch mirrors `callPlannerAnthropic` in `ask_planner.ts`, which is live.
- **Audit format changed**: `<tid>.spec_session.json` now contains
  `metadata.tool_calls_before_save`, `metadata.tool_call_log`,
  `metadata.hit_cap`, `metadata.forced_save`. The `messages` array now
  spans multi-turn conversations (was 3-4 messages, now up to ~12). Any
  downstream analysis script that walked `session.messages[2]` assuming a
  fixed shape needs updating.
- **`spec._meta` augmented**: now also has `tool_calls_before_save`, `hit_cap`,
  `forced_save`. Existing readers that did `_meta["extractor"]` etc.
  continue to work.
- **CLI unchanged**: `--tasks`, `--extractor`, `--out`, and (LiveSQL only)
  `--db-dir`, `--workers`, `--overwrite` flags all preserved. Output paths
  unchanged: `<tid>.json`, `<tid>.original.json`, `<tid>.spec_session.json`.
- **Deferred**: P2b.4 (self-consistency, N=3-5 sampling) and P2b.5
  (external-verifier-guided extraction) are NOT implemented. The proposal
  recommends running P2b.1-3 first and re-evaluating before committing to
  the more expensive enhancements.

## Compile status

- `python3 -c "import ast; ast.parse(...)"` on all 3 extractors: clean.
- `python3 -c "import ast; ast.parse(...)"` on `scripts/spec_extraction_tools.py`: clean.
- Runtime import + manual tool exercise: passes for `read_file`,
  `list_files`, `query_fees`, `sample_table`, `describe_table`,
  `read_data_file`.
- Sanity tests: 3/3 benchmarks pass; specs are schema-valid and ≥1 tool
  call before `save_spec` confirmed via `tool_calls_before_save` metadata.
