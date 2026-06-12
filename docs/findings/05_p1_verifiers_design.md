# P1 — Per-step deterministic verifiers (design)

Date: 2026-06-06
Status: implemented (v1); not yet validated by smoke
Touches: `src/harness/tools/run_python.ts`, `src/harness/tools/run_sql.ts`,
`src/harness/tools/verify_step.ts` (new), `src/run.ts`, the 3 prompt YAMLs,
`src/harness/tools/ask_planner.ts` (R5 note).

## Why

EC5 (see `04_ec5_context_decay_mitigation.md`) addressed F-A (compute-success,
commit-failure caused by context decay). It does not address F-B (confidently-
wrong commits without uncertainty) or F-E (executor + planner consensus on a
wrong answer because they share the same bad spec).

Both F-B and F-E share a root cause: there is no MECHANICAL check between
"executor wrote some code" and "answer was committed". The trace contains row
counts and shapes, but they are buried inside `tool_call_result` blocks and the
executor is the only one parsing them. A deterministic post-condition check that
fires automatically — without the executor having to read or pause — is the
intervention.

## The 3 tiers

### Tier A — universal auto-print (Python)
After every `run_python` cell whose LAST expression evaluates to a pandas
DataFrame or Series (and that did not already print shape/dtypes itself), the
harness appends an `[AUTO-INSPECT]` block: `shape`, `dtypes`, and the first 3
rows. This is purely informational — the executor cannot ignore it because it
is in the recent context window, not buried in a stale tool result.

Implementation: `src/harness/tools/run_python.ts` wraps the user code with a
small Python prologue/epilogue. The prologue snapshots `_p1_pre` row counts of
all DataFrames already in `globals()`. The user code runs in `globals()` exactly
as before. The epilogue uses `ast.parse(user_src)` to find the last expression
statement, re-evaluates it to bind `_p1_last`, and if `_p1_last` is a
DataFrame/Series and the cell did not already print shape/dtypes, emits the
block. Working names are popped at the end so the executor's namespace stays
clean.

Skip rule: if the cell text matches `print|display\([^)]*\.(?:shape|dtypes|head)\b`
the cell is already inspecting itself — AUTO-INSPECT stays silent to avoid
duplicating output.

LiveSQL: no Tier-A for `run_sql` — the tool already returns up to 100 rows of
the result. Adding shape/dtypes there would be redundant.

### Tier B — pattern-triggered deterministic assertions

Pre-scan the user code (regex on a stripped source) for known operation
patterns. After the cell runs, emit one `[VERIFY: PASS|WARN|FAIL <name>]` tag
per matched pattern with concrete counts in the message:

- `groupby(` → `row_count_after_groupby` — assert
  `result_row_count <= max(_p1_pre.values())`. FAIL if the groupby grew the
  row count (almost always a real bug — usually wrong agg or missing groupby).
- `merge(` / `join(` / `pd.merge(` → `row_growth_after_join` — assert
  `result_row_count <= 2 * max(left_rows, right_rows)`. WARN if violated
  (cardinality blowup; usually means a join key duplicates on one side).
- Boolean-mask filter (`df[df[...]<op>...]`) → `non_empty_after_filter`.
  WARN if the result is 0 rows (often a sign the filter condition or constants
  are wrong).

LiveSQL (run_sql): pre-flight parse with `sqlglot.parse_one(sql, read="sqlite")`.
On parse failure, return `[VERIFY: FAIL sqlglot_parse] <error>` and SKIP
execution. The query never reached SQLite. PASS-level tags are not emitted for
run_sql in v1 — semantic checks against the result set are deferred.

All Tier-B probes are wrapped in `try/except` and CANNOT break user code.

### Tier C — opt-in `verify_step` tool

`verify_step(assertion, target_var, ...)` is a separate tool the executor
chooses to call. It fetches `target_var` from the REPL globals and runs a
structured assertion. Returns
`{"status": "PASS" | "FAIL" | "WARN", "message": "..."}` as a JSON-line tool
result. Cheap; no LLM call.

v1 assertion vocabulary (universal — works on any DataFrame/Series):
- `row_count(op, n)` — `len(target) <op> n` where `<op> ∈ {>=, >, ==, <=, <}`.
- `shape(expected_shape: [rows, cols])` — exact match.
- `unique(cols: [...])` — `target.duplicated(subset=cols).sum() == 0`.
- `non_null(cols: [...])` — sum of `isna()` across cols == 0.
- `dtypes(col, expected_dtype)` — `expected_dtype` is a substring of
  `str(target[col].dtype)`. Avoids the pandas-version-specific exact dtype
  hell (`int64` vs `Int64` vs `np.int64`).
- `value_in_range(col, lo, hi)` — count of `target[col] < lo or > hi`. WARN
  if any out-of-range, PASS otherwise.

Wired in `src/run.ts` for DABStep + Krama (the run_python paths). LiveSQL
skips it — the executor only sees `run_sql` and has no DataFrames in its
REPL view.

## Tag flow to the planner

In `src/harness/tools/ask_planner.ts`, the `PLANNER_AGENT_SYSTEM_PROMPT` R5
step now notes:

> any `[VERIFY: FAIL ...]` or `[VERIFY: WARN ...]` tag in the executor's
> trace counts as concrete EXECUTION_TRACE evidence and may be cited
> directly — those tags come from the harness's deterministic per-step
> verifiers, not the executor's interpretation.

When the executor escalates, the planner's `# Executor trace events (NEW
since your last reply)` block contains the `tool_call_result` text including
any verifier tags. The planner can quote them as `[Source: execution_trace]`
evidence for a SPEC_WRONG or EXECUTOR_WRONG verdict without re-deriving them.

## Inline tagging convention

```
<original stdout>

[AUTO-INSPECT]
shape: (47, 6)
dtypes:
  scheme: object
  ...
head:
  ...

[VERIFY: PASS row_count_after_groupby] result=12 <= max_input=47
[VERIFY: WARN non_empty_after_filter] 0 rows after boolean-mask filter — confirm intentional
[VERIFY: FAIL sqlglot_parse] ParseError: Unexpected token at line 3: 'INSER INTO'
```

The executor prompt YAMLs tell the executor how to interpret each level:

- PASS = informational, keep going
- WARN = pause, confirm intent (do not silently keep going if WARN
  contradicts intent)
- FAIL = the op produced something almost certainly wrong; fix or escalate

## Test cases the next smoke should exercise

- DABStep / Krama: a cell whose last expression is a groupby result —
  expect PASS row_count_after_groupby + AUTO-INSPECT.
- Krama: a merge that produces a known row-count blowup (cardinality bug) —
  expect WARN row_growth_after_join.
- DABStep: a filter `df[df['amount'] > 1e10]` known to be empty —
  expect WARN non_empty_after_filter.
- LiveSQL: a SQL string with a typo (`SELCT * FROM ...`) — expect FAIL
  sqlglot_parse and NO database execution.
- Cross-bench: executor calls `verify_step(row_count, target_var, ==, expected)`
  on a final aggregate before committing.

## Open questions for v2

1. **Semantic SQL checks**. Right now `run_sql` only does parse-validation.
   A v2 could check structural properties (no SELECT *, every JOIN has an ON,
   GROUP BY columns match the non-aggregated SELECT columns). sqlglot can
   support this; risk is false positives on legitimately-clever SQL.
2. **FK-intact / referential-integrity checks** for run_sql results.
   Could be expressed as a follow-up sqlglot AST walk + a probe query.
3. **Monotonic / sorted-by checks** for final-answer outputs (e.g. spec says
   ORDER BY x DESC; check that the result is in fact sorted that way).
4. **AUTO-INSPECT for dicts / lists of named tuples** — Krama executors
   sometimes leave a dict as the last expression of an aggregation cell.
5. **Per-benchmark assertion vocabulary**. Krama could add a `file_exists`
   assertion; DABStep could add a `valid_fee_rule_id` assertion. Universal
   set is the v1 baseline.
6. **Verifier output suppression** when the executor's cell already printed
   the same info. The current `already_prints_shape` regex is brittle; an
   AST-based check would be cleaner if false positives show up.
7. **Verifier failure escalation**. Right now a FAIL is a string in the
   tool result — the executor can still ignore it. A future v3 could
   auto-escalate to the planner on FAIL.
