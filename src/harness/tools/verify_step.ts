/**
 * `verify_step` — opt-in Tier C deterministic verifier.
 *
 * The executor can call this tool with a target variable name (a name already
 * present in the persistent Python REPL's globals) and a structured assertion.
 * The tool issues a one-shot Python snippet that fetches the variable and
 * checks the assertion, returning `{status: "PASS" | "FAIL" | "WARN", message}`.
 *
 * Available assertions (P1 v1 vocabulary — universal to any pandas DataFrame /
 * Series; matches the 6-family convergence across GE / pandera / dbt-expectations /
 * Soda / deequ per docs/findings/05_verifier_lit_review.md):
 *   - row_count      : len(target) <op> n
 *   - shape          : target.shape == expected_shape (list of two ints)
 *   - column_exists  : `col` is a column of `target` (Top-3 in every production stack)
 *   - unique         : all cols in `cols` have no duplicates jointly
 *   - non_null       : col(s) in `cols` have zero NaN / null
 *   - null_rate_below: target[col] null fraction < threshold (lower-FP than non_null)
 *   - dtypes         : col → expected_dtype (substring match against str(dtype))
 *   - value_in_range : target[col] is within [lo, hi] (inclusive)
 *   - value_in_set   : target[col] all values ∈ allowed_set
 *
 * The tool ONLY reports — it does not mutate the REPL state. It writes nothing
 * outside `_p1_*` scratch names which are cleaned up at the end.
 */
import { Type } from "@sinclair/typebox";
import type { AgentToolResult } from "@mariozechner/pi-agent-core";
import type { PythonREPL } from "../services/python_repl.js";
import type { ToolDefinition } from "./index.js";

export function makeVerifyStepTool(repl: PythonREPL): ToolDefinition {
  return {
    name: "verify_step",
    label: "Verify Step",
    description:
      "Deterministic, opt-in sanity check on a variable in the Python session. " +
      "Pass an assertion type, the target variable name, and assertion-specific " +
      "parameters. Returns PASS / FAIL / WARN with a message. Use near final " +
      "answer for cross-step sanity checks (row counts, shapes, dtypes, ranges) " +
      "or right after a tricky merge/groupby to confirm structure. " +
      "Assertions: row_count (op, n), shape (expected_shape), column_exists (col), " +
      "unique (cols), non_null (cols), null_rate_below (col, threshold), " +
      "dtypes (col, expected_dtype), value_in_range (col, lo, hi), value_in_set (col, allowed_set).",
    parameters: Type.Object({
      assertion: Type.Union(
        [
          Type.Literal("row_count"),
          Type.Literal("shape"),
          Type.Literal("column_exists"),
          Type.Literal("unique"),
          Type.Literal("non_null"),
          Type.Literal("null_rate_below"),
          Type.Literal("dtypes"),
          Type.Literal("value_in_range"),
          Type.Literal("value_in_set"),
        ],
        { description: "Which assertion to run." },
      ),
      target_var: Type.String({ description: "Variable name in the REPL globals." }),
      op: Type.Optional(Type.String({ description: "Comparison operator for row_count: one of >=, >, ==, <=, <." })),
      n: Type.Optional(Type.Number({ description: "Reference count for row_count." })),
      expected_shape: Type.Optional(Type.Array(Type.Number(), { description: "[rows, cols] for shape." })),
      cols: Type.Optional(Type.Array(Type.String(), { description: "Column names for unique / non_null." })),
      col: Type.Optional(Type.String({ description: "Single column name for column_exists / dtypes / null_rate_below / value_in_range / value_in_set." })),
      expected_dtype: Type.Optional(Type.String({ description: "Expected dtype substring (e.g. 'int', 'float', 'object')." })),
      lo: Type.Optional(Type.Number({ description: "Lower bound (inclusive) for value_in_range." })),
      hi: Type.Optional(Type.Number({ description: "Upper bound (inclusive) for value_in_range." })),
      threshold: Type.Optional(Type.Number({ description: "Null fraction threshold for null_rate_below (0.0-1.0). Returns FAIL if null fraction exceeds threshold." })),
      allowed_set: Type.Optional(Type.Array(Type.Unknown(), { description: "Allowed values for value_in_set. Values may be strings, numbers, or booleans." })),
    }),
    execute: async (_toolCallId: string, params: any): Promise<AgentToolResult<unknown>> => {
      const argJson = JSON.stringify(params || {});
      const code = `
import json as _p1_json
_p1_args = _p1_json.loads(${JSON.stringify(argJson)})
_p1_status = "FAIL"
_p1_msg = ""
_p1_name = _p1_args.get("target_var", "")
try:
    if _p1_name not in globals():
        _p1_msg = f"target_var '{_p1_name}' not found in REPL globals"
    else:
        _p1_target = globals()[_p1_name]
        _p1_a = _p1_args.get("assertion")
        if _p1_a == "row_count":
            import operator as _p1_op
            _p1_ops = {">=": _p1_op.ge, ">": _p1_op.gt, "==": _p1_op.eq, "<=": _p1_op.le, "<": _p1_op.lt}
            _p1_o = _p1_ops.get(_p1_args.get("op"))
            _p1_n = _p1_args.get("n")
            if _p1_o is None or _p1_n is None:
                _p1_msg = "row_count requires 'op' and 'n'"
            else:
                _p1_count = len(_p1_target)
                _p1_status = "PASS" if _p1_o(_p1_count, _p1_n) else "FAIL"
                _p1_msg = f"len({_p1_name})={_p1_count}, expected {_p1_args.get('op')} {_p1_n}"
        elif _p1_a == "shape":
            _p1_expected = tuple(_p1_args.get("expected_shape") or [])
            _p1_actual = tuple(getattr(_p1_target, "shape", ()))
            _p1_status = "PASS" if _p1_actual == _p1_expected else "FAIL"
            _p1_msg = f"{_p1_name}.shape={_p1_actual}, expected {_p1_expected}"
        elif _p1_a == "column_exists":
            _p1_c = _p1_args.get("col")
            if not _p1_c:
                _p1_msg = "column_exists requires 'col'"
            else:
                _p1_cols_actual = list(getattr(_p1_target, "columns", []))
                _p1_status = "PASS" if _p1_c in _p1_cols_actual else "FAIL"
                _p1_msg = f"{_p1_name} columns: {_p1_cols_actual[:20]}{' ...' if len(_p1_cols_actual) > 20 else ''}; looking for '{_p1_c}'"
        elif _p1_a == "unique":
            _p1_cols = _p1_args.get("cols") or []
            if not _p1_cols:
                _p1_msg = "unique requires 'cols'"
            else:
                _p1_dup_count = int(_p1_target.duplicated(subset=_p1_cols).sum())
                _p1_status = "PASS" if _p1_dup_count == 0 else "FAIL"
                _p1_msg = f"{_p1_name} duplicates on {_p1_cols}: {_p1_dup_count}"
        elif _p1_a == "non_null":
            _p1_cols = _p1_args.get("cols") or []
            if not _p1_cols:
                _p1_msg = "non_null requires 'cols'"
            else:
                _p1_null_counts = {c: int(_p1_target[c].isna().sum()) for c in _p1_cols}
                _p1_total_nulls = sum(_p1_null_counts.values())
                _p1_status = "PASS" if _p1_total_nulls == 0 else "FAIL"
                _p1_msg = f"{_p1_name} null counts {_p1_null_counts}"
        elif _p1_a == "null_rate_below":
            _p1_c = _p1_args.get("col")
            _p1_threshold = _p1_args.get("threshold")
            if _p1_c is None or _p1_threshold is None:
                _p1_msg = "null_rate_below requires 'col' and 'threshold' (0.0-1.0)"
            else:
                _p1_total = len(_p1_target)
                if _p1_total == 0:
                    _p1_msg = f"{_p1_name} is empty"
                else:
                    _p1_nulls = int(_p1_target[_p1_c].isna().sum())
                    _p1_rate = _p1_nulls / _p1_total
                    _p1_status = "PASS" if _p1_rate < _p1_threshold else "FAIL"
                    _p1_msg = f"{_p1_name}[{_p1_c}]: null rate {_p1_rate:.4f} ({_p1_nulls}/{_p1_total}), threshold {_p1_threshold}"
        elif _p1_a == "dtypes":
            _p1_c = _p1_args.get("col")
            _p1_expected = _p1_args.get("expected_dtype", "")
            if not _p1_c or not _p1_expected:
                _p1_msg = "dtypes requires 'col' and 'expected_dtype'"
            else:
                _p1_actual = str(_p1_target[_p1_c].dtype)
                _p1_status = "PASS" if _p1_expected in _p1_actual else "FAIL"
                _p1_msg = f"{_p1_name}[{_p1_c}].dtype={_p1_actual}, expected to contain '{_p1_expected}'"
        elif _p1_a == "value_in_range":
            _p1_c = _p1_args.get("col")
            _p1_lo = _p1_args.get("lo")
            _p1_hi = _p1_args.get("hi")
            if _p1_c is None or _p1_lo is None or _p1_hi is None:
                _p1_msg = "value_in_range requires 'col', 'lo', 'hi'"
            else:
                _p1_series = _p1_target[_p1_c]
                _p1_oob = int(((_p1_series < _p1_lo) | (_p1_series > _p1_hi)).sum())
                _p1_status = "PASS" if _p1_oob == 0 else "WARN"
                _p1_msg = f"{_p1_name}[{_p1_c}]: {_p1_oob} values outside [{_p1_lo}, {_p1_hi}]"
        elif _p1_a == "value_in_set":
            _p1_c = _p1_args.get("col")
            _p1_allowed = _p1_args.get("allowed_set")
            if _p1_c is None or _p1_allowed is None:
                _p1_msg = "value_in_set requires 'col' and 'allowed_set' (list)"
            else:
                _p1_allowed_s = set(_p1_allowed)
                _p1_series = _p1_target[_p1_c]
                _p1_unexpected = _p1_series[~_p1_series.isin(_p1_allowed_s)]
                _p1_uniq_unexpected = sorted(set(map(str, _p1_unexpected.head(20))))
                _p1_n_unexpected = int(len(_p1_unexpected))
                _p1_status = "PASS" if _p1_n_unexpected == 0 else "FAIL"
                _p1_msg = f"{_p1_name}[{_p1_c}]: {_p1_n_unexpected} values not in allowed_set (sample: {_p1_uniq_unexpected})"
        else:
            _p1_msg = f"unknown assertion '{_p1_a}'"
except Exception as _p1_e:
    _p1_status = "FAIL"
    _p1_msg = f"{type(_p1_e).__name__}: {_p1_e}"

print(_p1_json.dumps({"status": _p1_status, "message": _p1_msg}))

for _p1_k in ("_p1_json","_p1_args","_p1_status","_p1_msg","_p1_name","_p1_target","_p1_a","_p1_op","_p1_ops","_p1_o","_p1_n","_p1_count","_p1_expected","_p1_actual","_p1_cols","_p1_cols_actual","_p1_dup_count","_p1_null_counts","_p1_total_nulls","_p1_c","_p1_lo","_p1_hi","_p1_series","_p1_oob","_p1_threshold","_p1_total","_p1_nulls","_p1_rate","_p1_allowed","_p1_allowed_s","_p1_unexpected","_p1_uniq_unexpected","_p1_n_unexpected","_p1_e","_p1_k"):
    globals().pop(_p1_k, None)
`.trim();
      const { output } = await repl.execute(code);
      // Pass through Python's JSON line as the tool result text.
      return { content: [{ type: "text", text: output.trim() }], details: {} };
    },
  };
}
