/**
 * `run_python(code: str) -> str` — the ONLY tool the agent has in scribe.
 *
 * Hands the code string to a `PythonREPL` process (persistent across calls within
 * a single task — so variables, imports, and loaded DataFrames stay alive between
 * tool calls). Returns whatever the REPL printed to stdout/stderr.
 *
 * The preamble code that boots the REPL (loaded once before any tool call) is
 * built in `src/run.ts` (`buildPreamble`) and exposes:
 *   - `CONTEXT_DIR` (absolute path string)
 *   - `context_path(*parts)` (joins paths under CONTEXT_DIR)
 *   - pre-imported: pd, np, json, csv, os
 *
 * P1 deterministic verifiers (Tier A + Tier B) are layered on by wrapping the
 * user code with a small Python instrumentation block that:
 *   - Tier A: auto-prints shape/dtypes/head when the LAST expression of the cell
 *     evaluates to a pandas DataFrame or Series — unless the cell already printed
 *     shape/dtypes itself (cheap regex check).
 *   - Tier B: pattern-triggered assertions for groupby/merge/join/boolean-mask
 *     filter operations. The triggers are detected in TS via regex on the source,
 *     then the Python instrumentation block executes the corresponding cheap
 *     post-condition checks against the cell's modified namespace and emits one
 *     of [VERIFY: PASS|WARN|FAIL <name>] tags.
 *
 * Output format is appended AFTER the original stdout, separated by a blank line.
 * If no triggers fire and no last-DF, the output is unchanged.
 */
import { Type } from "@sinclair/typebox";
import type { AgentToolResult } from "@mariozechner/pi-agent-core";
import type { PythonREPL } from "../services/python_repl.js";
import type { ToolDefinition } from "./index.js";

// ---------------------------------------------------------------------------
// Pattern detection (TS regex pre-scan).
// We detect the patterns up-front so the Python instrumentation knows which
// post-condition probes to emit. Patterns are stripped of trivial comments
// before scanning.
// ---------------------------------------------------------------------------

function stripCommentsAndStrings(src: string): string {
  // Strip # comments and triple/single-quoted strings, but only enough to avoid
  // false positives. Keep newlines for line preservation. This is best-effort —
  // a robust AST scan is overkill for a smoke test.
  let out = src;
  // Triple-quoted strings.
  out = out.replace(/"""[\s\S]*?"""/g, "");
  out = out.replace(/'''[\s\S]*?'''/g, "");
  // Single/double-quoted strings (non-greedy, single line).
  out = out.replace(/"(?:\\.|[^"\\\n])*"/g, "\"\"");
  out = out.replace(/'(?:\\.|[^'\\\n])*'/g, "''");
  // # comments to EOL.
  out = out.replace(/#[^\n]*/g, "");
  return out;
}

interface CellPatterns {
  hasGroupby: boolean;
  hasMergeOrJoin: boolean;
  hasBoolMask: boolean;
  alreadyPrintsShape: boolean;
}

function scanCellPatterns(src: string): CellPatterns {
  const stripped = stripCommentsAndStrings(src);
  // Pandas .groupby( anywhere.
  const hasGroupby = /\.groupby\s*\(/.test(stripped);
  // .merge( or .join( — pd.merge() also covered by .merge(
  const hasMergeOrJoin = /\.(?:merge|join)\s*\(/.test(stripped) || /\bpd\.merge\s*\(/.test(stripped);
  // Boolean mask filter: df[df[...]...]  or  df[(...)] with a comparison operator.
  // Heuristic: an indexer that contains a comparator (==, !=, <, >, <=, >=, &, |) and a [ inside.
  const hasBoolMask = /\b[A-Za-z_][\w]*\s*\[\s*[A-Za-z_][\w]*\s*\[/.test(stripped)
    || /\b[A-Za-z_][\w]*\s*\[\s*\(?[^[\]\n]*[<>=!]=?[^[\]\n]*\)?\s*\]/.test(stripped);
  // Did the cell already print shape/dtypes? Cheap signal — skip AUTO-INSPECT.
  const alreadyPrintsShape = /\b(?:print\s*\([^\n]*\.(?:shape|dtypes|head)\b|display\s*\([^\n]*\.(?:shape|dtypes|head)\b)/.test(stripped);
  return { hasGroupby, hasMergeOrJoin, hasBoolMask, alreadyPrintsShape };
}

// ---------------------------------------------------------------------------
// Python instrumentation builder.
// We wrap the user code so the same exec() run captures:
//   - input row counts of all candidate DataFrames in scope BEFORE
//   - the last-expression value
//   - post-condition checks for the detected patterns
// All probes are wrapped in try/except so they NEVER break user code.
// ---------------------------------------------------------------------------

function buildInstrumentedCode(userCode: string, p: CellPatterns): string {
  // We split into:
  //   prologue — captures `_p1_pre`: a snapshot of DataFrame names → row counts.
  //   user_code — exactly as supplied, with the last-expression value bound to _p1_last.
  //   epilogue — auto-inspect + pattern-triggered assertions, emits [AUTO-INSPECT] + [VERIFY: ...].
  //
  // The "last expression value" trick: we wrap user code in `_p1_last = None` then
  // use compile()+exec() of the original code, then reuse the Python AST module
  // inline to find the last simple expression statement and re-evaluate it for
  // _p1_last. This is cheaper than re-parsing in JS: we just embed a tiny Python
  // helper that introspects ast.parse(user_code) and grabs the last Expression.

  // Emit flags as Python boolean literals — NOT JSON, since JS booleans
  // (true/false/null) are lowercase and Python expects True/False/None. Embedding
  // raw JSON into Python code triggered `NameError: name 'false' is not defined`
  // on every run_python call in the v3 smoke. Fix: emit Python literals directly.
  const pyBool = (b: boolean) => (b ? "True" : "False");
  const flagsLiteral =
    `{"has_groupby": ${pyBool(p.hasGroupby)}, ` +
    `"has_merge_or_join": ${pyBool(p.hasMergeOrJoin)}, ` +
    `"has_bool_mask": ${pyBool(p.hasBoolMask)}, ` +
    `"already_prints_shape": ${pyBool(p.alreadyPrintsShape)}}`;
  // Use a unique sentinel marker — the agent should never need to grep this in its own code.
  const SRC_VAR = "_p1_user_src__";

  // Build the wrapped code. Note: the entire wrapper runs inside the REPL's
  // persistent `_ns` namespace, so any `_p1_*` names persist between calls —
  // harmless, but we clean up at the end.
  const lines = [
    `import ast as _p1_ast, pandas as _p1_pd`,
    `_p1_flags = ${flagsLiteral}`,
    `${SRC_VAR} = ${JSON.stringify(userCode)}`,
    // Snapshot pre-existing DataFrames (names + row counts) for row-growth checks.
    `_p1_pre = {}`,
    `try:`,
    `    for _p1_k, _p1_v in list(globals().items()):`,
    `        if isinstance(_p1_v, _p1_pd.DataFrame):`,
    `            _p1_pre[_p1_k] = len(_p1_v)`,
    `except Exception:`,
    `    pass`,
    // Parse user source so we can find the last expression for AUTO-INSPECT.
    `_p1_last_expr_src = None`,
    `try:`,
    `    _p1_tree = _p1_ast.parse(${SRC_VAR})`,
    `    if _p1_tree.body and isinstance(_p1_tree.body[-1], _p1_ast.Expr):`,
    `        _p1_last_expr_src = _p1_ast.get_source_segment(${SRC_VAR}, _p1_tree.body[-1])`,
    `except Exception:`,
    `    pass`,
    // Execute the user code in the current (module-level) namespace.
    // We must exec in globals() so persistence works the same as the bare wrapper.
    `exec(compile(${SRC_VAR}, "<agent>", "exec"), globals())`,
    // Capture last-expression value if available.
    `_p1_last = None`,
    `try:`,
    `    if _p1_last_expr_src is not None:`,
    `        _p1_last = eval(compile(_p1_last_expr_src, "<agent-last>", "eval"), globals())`,
    `except Exception:`,
    `    _p1_last = None`,
    // Build the appended report.
    `_p1_report_lines = []`,
    // ── Tier A: AUTO-INSPECT ───────────────────────────────────────────────
    `try:`,
    `    if (not _p1_flags["already_prints_shape"]) and isinstance(_p1_last, (_p1_pd.DataFrame, _p1_pd.Series)):`,
    `        _p1_report_lines.append("[AUTO-INSPECT]")`,
    `        if isinstance(_p1_last, _p1_pd.DataFrame):`,
    `            _p1_report_lines.append(f"shape: {_p1_last.shape}")`,
    `            _p1_report_lines.append("dtypes:")`,
    `            for _p1_c, _p1_t in _p1_last.dtypes.items():`,
    `                _p1_report_lines.append(f"  {_p1_c}: {_p1_t}")`,
    `            _p1_report_lines.append("head:")`,
    `            _p1_report_lines.append(_p1_last.head(3).to_string())`,
    `        else:`,
    `            _p1_report_lines.append(f"length: {len(_p1_last)}, dtype: {_p1_last.dtype}")`,
    `            _p1_report_lines.append("head:")`,
    `            _p1_report_lines.append(_p1_last.head(3).to_string())`,
    `except Exception as _p1_e:`,
    `    pass`,
    // ── Tier B: pattern-triggered assertions ──────────────────────────────
    // groupby — if last value is a DataFrame, assert result_row_count <= max_input_row_count
    `try:`,
    `    if _p1_flags["has_groupby"] and isinstance(_p1_last, (_p1_pd.DataFrame, _p1_pd.Series)):`,
    `        _p1_out_rows = len(_p1_last)`,
    `        _p1_max_in = max(_p1_pre.values()) if _p1_pre else None`,
    `        if _p1_max_in is not None and _p1_out_rows <= _p1_max_in:`,
    `            _p1_report_lines.append(f"[VERIFY: PASS row_count_after_groupby] result={_p1_out_rows} <= max_input={_p1_max_in}")`,
    `        elif _p1_max_in is not None:`,
    `            _p1_report_lines.append(f"[VERIFY: FAIL row_count_after_groupby] result={_p1_out_rows} > max_input={_p1_max_in} — groupby should not grow row count")`,
    `except Exception:`,
    `    pass`,
    // merge/join — assert result_row_count <= 2 * max(left_rows, right_rows)
    `try:`,
    `    if _p1_flags["has_merge_or_join"] and isinstance(_p1_last, _p1_pd.DataFrame):`,
    `        _p1_out_rows = len(_p1_last)`,
    `        _p1_max_in = max(_p1_pre.values()) if _p1_pre else None`,
    `        if _p1_max_in is not None:`,
    `            _p1_threshold = 2 * _p1_max_in`,
    `            if _p1_out_rows <= _p1_threshold:`,
    `                _p1_report_lines.append(f"[VERIFY: PASS row_growth_after_join] result={_p1_out_rows} <= 2*max_input={_p1_threshold}")`,
    `            else:`,
    `                _p1_report_lines.append(f"[VERIFY: WARN row_growth_after_join] result={_p1_out_rows} > 2*max_input={_p1_threshold} — possible cardinality blowup; check join keys")`,
    `except Exception:`,
    `    pass`,
    // boolean-mask filter — if result is 0 rows, emit WARN
    `try:`,
    `    if _p1_flags["has_bool_mask"] and isinstance(_p1_last, _p1_pd.DataFrame) and len(_p1_last) == 0:`,
    `        _p1_report_lines.append("[VERIFY: WARN non_empty_after_filter] 0 rows after boolean-mask filter — confirm intentional")`,
    `except Exception:`,
    `    pass`,
    // Emit report.
    `if _p1_report_lines:`,
    `    print("\\n" + "\\n".join(_p1_report_lines))`,
    // Clean up working names (best-effort).
    `for _p1_n in ("_p1_ast","_p1_pd","_p1_flags","${SRC_VAR}","_p1_pre","_p1_last_expr_src","_p1_last","_p1_report_lines","_p1_tree","_p1_k","_p1_v","_p1_c","_p1_t","_p1_e","_p1_out_rows","_p1_max_in","_p1_threshold","_p1_n"):`,
    `    globals().pop(_p1_n, None)`,
  ];
  return lines.join("\n");
}

export function makeRunPythonTool(repl: PythonREPL, descriptionOverride?: string): ToolDefinition {
  return {
    name: "run_python",
    label: "Run Python",
    description: descriptionOverride ?? "Execute Python code in a persistent session. Use print() for output.",
    parameters: Type.Object({
      code: Type.String({ description: "Python code to execute. Use print() for output." }),
    }),
    execute: async (_toolCallId: string, params: any): Promise<AgentToolResult<unknown>> => {
      const userCode = params.code as string;
      const patterns = scanCellPatterns(userCode);
      const instrumented = buildInstrumentedCode(userCode, patterns);
      const { output } = await repl.execute(instrumented);
      return { content: [{ type: "text", text: output }], details: {} };
    },
  };
}
