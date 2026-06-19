#!/usr/bin/env python3
"""Grade SCRIBE Sentinel eval runs against gold CSVs.

Executes the executor's FINAL SQL via EvalSQLExecutor and compares to
eval_gt/gt-csv using sentinel-eval-sdk's compare_dataframes.

Usage:
    python scripts/grade_sentinel.py \\
        --out results/sentinel_smoke \\
        --tasks results/sentinel_smoke/tasks.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SENTINEL = ROOT.parent / "sentinel-eval-sdk"


def resolve_sentinel_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("SENTINEL_SDK_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_SENTINEL.resolve()


def extract_final_sql_from_text(text: str) -> str | None:
    if not text:
        return None
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.upper().startswith("FINAL SQL:"):
            candidate = stripped[len("FINAL SQL:"):].strip()
            if candidate and not candidate.startswith("--"):
                return candidate
    code_block = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if code_block:
        return code_block.group(1).strip()
    return None


def find_final_sql(task_dir: Path, summary_rows: list[dict]) -> str | None:
    tid = task_dir.name
    for r in summary_rows:
        if r.get("task_id") == tid:
            raw = r.get("final_answer") or ""
            sql = extract_final_sql_from_text(raw)
            if sql:
                return sql

    # Only executor output — never scrape user_message (spec SQL blocks look like answers).
    for sess_file in sorted(task_dir.glob("sessions/*.jsonl")):
        events = [json.loads(l) for l in open(sess_file) if l.strip()]
        for e in reversed(events):
            if e.get("type") not in ("assistant_response", "tool_call_result"):
                continue
            content = e.get("content", "")
            if isinstance(content, str) and content.strip():
                sql = extract_final_sql_from_text(content)
                if sql:
                    return sql
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="SCRIBE run output dir")
    ap.add_argument("--tasks", required=True, help="tasks.jsonl with app_name + gold_csv_path")
    ap.add_argument("--sentinel-root", default=None)
    args = ap.parse_args()

    sentinel = resolve_sentinel_root(args.sentinel_root)
    load_dotenv(sentinel / ".env", override=True)
    load_dotenv(ROOT / ".env", override=False)

    sys.path.insert(0, str(sentinel))
    sys.path.insert(0, str(ROOT / "data" / "context"))
    from run_eval.evaluate import compare_dataframes  # noqa: WPS433

    backend = os.environ.get("SENTINEL_SQL_BACKEND", "connection_service").strip().lower()
    if backend == "psycopg2":
        from sentinel_sql import execute_df  # noqa: WPS433
    else:
        from sql_executor import EvalSQLExecutor  # noqa: WPS433
        executor = EvalSQLExecutor()
        def execute_df(app_name, sql, max_rows=50000):  # noqa: ANN001
            return executor.execute_df(app_name, sql, max_rows=max_rows)

    results_dir = Path(args.out)
    tasks_map = {t["task_id"]: t for t in [json.loads(l) for l in open(args.tasks) if l.strip()]}

    summary_path = results_dir / "summary.json"
    summary_rows: list[dict] = []
    if summary_path.exists():
        summary_rows = json.load(open(summary_path))

    rows: list[dict] = []

    for task_dir in sorted(results_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        tid = task_dir.name
        if tid not in tasks_map:
            continue

        meta = tasks_map[tid]
        app_name = meta.get("app_name")
        gold_path = meta.get("gold_csv_path")
        if not app_name or not gold_path or not Path(gold_path).exists():
            rows.append({
                "task_id": tid,
                "status": "no_gold",
                "score": 0.0,
                "detail": f"missing gold or app_name (gold={gold_path})",
            })
            continue

        pred_sql = find_final_sql(task_dir, summary_rows)
        if not pred_sql:
            rows.append({"task_id": tid, "status": "no_sql", "score": 0.0, "detail": ""})
            continue

        try:
            pred_df = execute_df(app_name, pred_sql, max_rows=50000)
            pred_dump_path = task_dir / "pred_full.csv"
            pred_df.to_csv(pred_dump_path, index=False)
            gold_df = pd.read_csv(gold_path)
            score, details = compare_dataframes(pred_df, gold_df)
            passed = score >= 1.0
            rows.append({
                "task_id": tid,
                "app_name": app_name,
                "status": "pass" if passed else "fail",
                "score": round(score, 4),
                "gold_rows_matched": details.get("gold_rows_matched"),
                "gold_rows_total": details.get("gold_rows_total"),
                "pred_sql": pred_sql[:400],
                "pred_rows": int(len(pred_df)),
                "pred_full_csv": str(pred_dump_path),
                "detail": details.get("error", ""),
            })
        except Exception as e:
            rows.append({
                "task_id": tid,
                "app_name": app_name,
                "status": "exec_error",
                "score": 0.0,
                "pred_sql": pred_sql[:400],
                "detail": str(e)[:300],
            })

    print(f"\n{'task_id':22s} {'status':12s} {'score':>6s}")
    print("-" * 45)
    for r in sorted(rows, key=lambda x: (x["status"], x["task_id"])):
        print(f"{r['task_id']:22s} {r['status']:12s} {r.get('score', 0):6.3f}")

    passes = sum(1 for r in rows if r["status"] == "pass")
    total = len(rows)
    print(f"\n{'='*45}")
    print(f"  PASS: {passes}/{total} = {passes/total*100:.1f}%" if total else "  No tasks graded")

    # Attach Langfuse trace ids from executor summary when present.
    if summary_path.exists():
        trace_by_task = {
            str(s.get("task_id")): {
                "langfuse_trace_id": s.get("langfuse_trace_id"),
                "langfuse_url": s.get("langfuse_url"),
            }
            for s in summary_rows
            if s.get("langfuse_trace_id")
        }
        for r in rows:
            extra = trace_by_task.get(r["task_id"])
            if extra:
                r.update(extra)

    (results_dir / "results.json").write_text(json.dumps(rows, indent=2))
    csv_path = results_dir / "results.csv"
    if rows:
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"  Wrote {csv_path}")


if __name__ == "__main__":
    main()
