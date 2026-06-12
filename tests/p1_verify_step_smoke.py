"""P1 Tier-C verify_step smoke test.

Exercises every assertion in the v1 vocabulary against a mock DataFrame in a
namespace that mirrors the PythonREPL's `globals()` view. The verify_step
tool's TypeScript wrapper emits a Python snippet that fetches a target var
from `globals()` and runs the assertion; here we run an equivalent snippet
in-process (the Python logic is the source of truth — TS just wires args
through JSON).

Run:
    python3 tests/p1_verify_step_smoke.py

Exit 0 = pass, non-zero = fail.
"""
from __future__ import annotations
import json
import sys
import pandas as pd
import numpy as np


# This is the same Python body that lives inside the TS template-literal in
# src/harness/tools/verify_step.ts. We test against the same code path; if the
# TS template changes, this snippet must change too (and vice versa).
VERIFY_STEP_BODY = r'''
import json as _p1_json
_p1_args = _p1_json.loads(_p1_test_arg_json)
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
        elif _p1_a == "column_exists":
            _p1_c = _p1_args.get("col")
            if not _p1_c:
                _p1_msg = "column_exists requires 'col'"
            else:
                _p1_cols_actual = list(getattr(_p1_target, "columns", []))
                _p1_status = "PASS" if _p1_c in _p1_cols_actual else "FAIL"
                _p1_msg = f"{_p1_name} columns: {_p1_cols_actual[:20]}{' ...' if len(_p1_cols_actual) > 20 else ''}; looking for '{_p1_c}'"
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

_p1_result = _p1_json.dumps({"status": _p1_status, "message": _p1_msg})
'''


def run_verify(ns: dict, args: dict) -> dict:
    """Execute the verify_step snippet against namespace `ns` with args `args`.

    Returns the parsed {"status", "message"} dict.
    """
    local_ns = dict(ns)
    local_ns["_p1_test_arg_json"] = json.dumps(args)
    exec(VERIFY_STEP_BODY, local_ns)
    return json.loads(local_ns["_p1_result"])


def _expect(case_name: str, result: dict, expected_status: str, msg_contains: str = "") -> bool:
    ok = result["status"] == expected_status and (msg_contains in result["message"])
    print(f"  [{'PASS' if ok else 'FAIL'}] {case_name}: status={result['status']}, msg={result['message'][:120]}")
    return ok


def main() -> int:
    # Build the namespace exactly the way the PythonREPL would: a `globals()`-like
    # dict that contains user variables.
    df = pd.DataFrame({
        "id": [1, 2, 3, 3, 5],          # has a duplicate
        "amount": [10.0, 20.0, 30.0, 40.0, np.nan],
        "scheme": ["A", "B", "A", "C", "B"],
    })
    df_no_dup = pd.DataFrame({
        "id": [1, 2, 3, 4, 5],
        "amount": [10.0, 20.0, 30.0, 40.0, 50.0],
    })
    ns = {"df": df, "df_no_dup": df_no_dup}

    cases: list[bool] = []

    # row_count
    cases.append(_expect("row_count >= 3 (pass)", run_verify(ns, {
        "assertion": "row_count", "target_var": "df", "op": ">=", "n": 3,
    }), "PASS", "len(df)=5"))
    cases.append(_expect("row_count == 7 (fail)", run_verify(ns, {
        "assertion": "row_count", "target_var": "df", "op": "==", "n": 7,
    }), "FAIL"))

    # shape
    cases.append(_expect("shape (5,3) (pass)", run_verify(ns, {
        "assertion": "shape", "target_var": "df", "expected_shape": [5, 3],
    }), "PASS"))
    cases.append(_expect("shape (5,4) (fail)", run_verify(ns, {
        "assertion": "shape", "target_var": "df", "expected_shape": [5, 4],
    }), "FAIL"))

    # unique — df has dup on id; df_no_dup does not
    cases.append(_expect("unique df_no_dup id (pass)", run_verify(ns, {
        "assertion": "unique", "target_var": "df_no_dup", "cols": ["id"],
    }), "PASS"))
    cases.append(_expect("unique df id (fail)", run_verify(ns, {
        "assertion": "unique", "target_var": "df", "cols": ["id"],
    }), "FAIL", "duplicates"))

    # non_null
    cases.append(_expect("non_null df.id (pass)", run_verify(ns, {
        "assertion": "non_null", "target_var": "df", "cols": ["id"],
    }), "PASS"))
    cases.append(_expect("non_null df.amount (fail — has NaN)", run_verify(ns, {
        "assertion": "non_null", "target_var": "df", "cols": ["amount"],
    }), "FAIL"))

    # dtypes
    cases.append(_expect("dtypes df.id contains 'int' (pass)", run_verify(ns, {
        "assertion": "dtypes", "target_var": "df", "col": "id", "expected_dtype": "int",
    }), "PASS"))
    cases.append(_expect("dtypes df.scheme contains 'int' (fail)", run_verify(ns, {
        "assertion": "dtypes", "target_var": "df", "col": "scheme", "expected_dtype": "int",
    }), "FAIL"))

    # value_in_range — df.amount has NaN which is neither < lo nor > hi → PASS
    cases.append(_expect("value_in_range df_no_dup.amount [0,100] (pass)", run_verify(ns, {
        "assertion": "value_in_range", "target_var": "df_no_dup",
        "col": "amount", "lo": 0, "hi": 100,
    }), "PASS"))
    cases.append(_expect("value_in_range df_no_dup.amount [0,25] (warn)", run_verify(ns, {
        "assertion": "value_in_range", "target_var": "df_no_dup",
        "col": "amount", "lo": 0, "hi": 25,
    }), "WARN", "outside"))

    # column_exists (added per docs/findings/05_verifier_lit_review.md — Top-3 in production stacks)
    cases.append(_expect("column_exists df.scheme (pass)", run_verify(ns, {
        "assertion": "column_exists", "target_var": "df", "col": "scheme",
    }), "PASS"))
    cases.append(_expect("column_exists df.missing_col (fail)", run_verify(ns, {
        "assertion": "column_exists", "target_var": "df", "col": "merchant_id",
    }), "FAIL", "looking for"))

    # null_rate_below (replaces strict non_null for sparse columns)
    cases.append(_expect("null_rate_below df.amount<0.5 (pass — 1/5 null)", run_verify(ns, {
        "assertion": "null_rate_below", "target_var": "df", "col": "amount", "threshold": 0.5,
    }), "PASS", "null rate 0.2000"))
    cases.append(_expect("null_rate_below df.amount<0.1 (fail — 1/5 = 0.2)", run_verify(ns, {
        "assertion": "null_rate_below", "target_var": "df", "col": "amount", "threshold": 0.1,
    }), "FAIL"))

    # value_in_set (for categorical / fee-class columns)
    cases.append(_expect("value_in_set df.scheme in {A,B,C} (pass)", run_verify(ns, {
        "assertion": "value_in_set", "target_var": "df", "col": "scheme", "allowed_set": ["A", "B", "C"],
    }), "PASS"))
    cases.append(_expect("value_in_set df.scheme in {A,B} (fail — has C)", run_verify(ns, {
        "assertion": "value_in_set", "target_var": "df", "col": "scheme", "allowed_set": ["A", "B"],
    }), "FAIL", "not in allowed_set"))

    # missing target var
    cases.append(_expect("missing target_var (fail)", run_verify(ns, {
        "assertion": "row_count", "target_var": "does_not_exist", "op": "==", "n": 0,
    }), "FAIL", "not found"))

    # unknown assertion
    cases.append(_expect("unknown assertion (fail)", run_verify(ns, {
        "assertion": "nonexistent_check", "target_var": "df",
    }), "FAIL", "unknown"))

    n_pass = sum(cases)
    n_total = len(cases)
    print(f"\n{n_pass}/{n_total} cases passed")
    return 0 if n_pass == n_total else 1


if __name__ == "__main__":
    sys.exit(main())
