#!/usr/bin/env python3
"""Evaluate Sentinel run outputs against ground-truth CSVs.

This evaluator consumes SCRIBE output directories that contain per-task
`pred_full.csv` files and compares them against Sentinel ground-truth CSVs
using sentinel-eval-sdk's `compare_dataframes`.

Default assumptions:
- tasks metadata: <out>/tasks.jsonl
- predictions:    <out>/<task_id>/pred_full.csv
- results emit:   <out>/eval_results.json + <out>/eval_results.csv

Example:
    python3 scripts/evaluate_sentinel_outputs.py \
      --out results/sentinel_smoke2_opus \
      --gt-root /Users/gulshan/Desktop/sentinel-eval-sdk/eval_gt/gt-csv \
      --sentinel-root /Users/gulshan/Desktop/sentinel-eval-sdk
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SENTINEL = ROOT.parent / "sentinel-eval-sdk"
DEFAULT_GT = DEFAULT_SENTINEL / "eval_gt" / "gt-csv"


def _to_debug_str(v) -> str:
    if pd.isna(v):
        return "<NA>"
    s = str(v).strip()
    # Normalize common numeric formatting noise.
    try:
        if s and all(ch in "0123456789+-.eE" for ch in s):
            return f"{float(s):.12g}"
    except Exception:
        pass
    return s


def build_diff_debug(pred_df: pd.DataFrame, gold_df: pd.DataFrame, sample_rows: int = 3) -> dict:
    pred_cols = list(pred_df.columns)
    gold_cols = list(gold_df.columns)
    common = [c for c in gold_cols if c in pred_cols]
    pred_only = [c for c in pred_cols if c not in gold_cols]
    gold_only = [c for c in gold_cols if c not in pred_cols]

    dtype_diff = {}
    for c in common:
        pdt = str(pred_df[c].dtype)
        gdt = str(gold_df[c].dtype)
        if pdt != gdt:
            dtype_diff[c] = {"pred": pdt, "gold": gdt}

    debug = {
        "common_columns": common,
        "pred_only_columns": pred_only,
        "gold_only_columns": gold_only,
        "dtype_differences": dtype_diff,
        "pred_head": pred_df.head(sample_rows).to_dict(orient="records"),
        "gold_head": gold_df.head(sample_rows).to_dict(orient="records"),
    }

    if not common:
        return debug

    psub = pred_df[common].copy()
    gsub = gold_df[common].copy()

    for c in common:
        psub[c] = psub[c].map(_to_debug_str)
        gsub[c] = gsub[c].map(_to_debug_str)

    try:
        # Row-level set mismatch (string-normalized across common columns).
        puniq = psub.drop_duplicates()
        guniq = gsub.drop_duplicates()
        only_pred = puniq.merge(guniq, on=common, how="left", indicator=True)
        only_pred = only_pred[only_pred["_merge"] == "left_only"].drop(columns=["_merge"])
        only_gold = guniq.merge(puniq, on=common, how="left", indicator=True)
        only_gold = only_gold[only_gold["_merge"] == "left_only"].drop(columns=["_merge"])

        debug["pred_only_sample"] = only_pred.head(sample_rows).to_dict(orient="records")
        debug["gold_only_sample"] = only_gold.head(sample_rows).to_dict(orient="records")
        debug["pred_only_count_estimate"] = int(len(only_pred))
        debug["gold_only_count_estimate"] = int(len(only_gold))
    except Exception as exc:
        debug["diff_error"] = str(exc)[:200]

    return debug


def resolve_sentinel_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("SENTINEL_SDK_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_SENTINEL.resolve()


def resolve_gold_path(task: dict, gt_root: Path) -> Path | None:
    raw = (task.get("gold_csv_path") or "").strip()
    if raw:
        p = Path(raw)
        if p.exists():
            return p
        # Try rewriting to a provided gt root using basename.
        candidate = gt_root / p.name
        if candidate.exists():
            return candidate
    # Last fallback: task_id.csv under gt root.
    task_id = str(task.get("task_id", "")).strip()
    if task_id:
        candidate = gt_root / f"{task_id}.csv"
        if candidate.exists():
            return candidate
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="SCRIBE output directory")
    ap.add_argument("--tasks", default=None, help="tasks.jsonl path (default: <out>/tasks.jsonl)")
    ap.add_argument("--gt-root", default=str(DEFAULT_GT), help="Ground-truth CSV folder")
    ap.add_argument("--sentinel-root", default=None, help="Path to sentinel-eval-sdk root")
    ap.add_argument("--debug-sample-rows", type=int, default=3, help="Rows to include in debug samples for failed tasks")
    args = ap.parse_args()

    out_dir = Path(args.out).expanduser().resolve()
    tasks_path = Path(args.tasks).expanduser().resolve() if args.tasks else out_dir / "tasks.jsonl"
    gt_root = Path(args.gt_root).expanduser().resolve()
    sentinel_root = resolve_sentinel_root(args.sentinel_root)

    if not out_dir.is_dir():
        raise SystemExit(f"--out not found: {out_dir}")
    if not tasks_path.exists():
        raise SystemExit(f"tasks file not found: {tasks_path}")
    if not gt_root.exists():
        raise SystemExit(f"--gt-root not found: {gt_root}")

    load_dotenv(sentinel_root / ".env", override=True)
    load_dotenv(ROOT / ".env", override=False)
    sys.path.insert(0, str(sentinel_root))
    from run_eval.evaluate import compare_dataframes  # noqa: WPS433

    tasks = [json.loads(line) for line in tasks_path.read_text().splitlines() if line.strip()]

    rows: list[dict] = []
    for t in tasks:
        task_id = t["task_id"]
        app_name = t.get("app_name", "")
        pred_path = out_dir / task_id / "pred_full.csv"
        gold_path = resolve_gold_path(t, gt_root)

        if not pred_path.exists():
            rows.append(
                {
                    "task_id": task_id,
                    "app_name": app_name,
                    "status": "missing_pred",
                    "score": 0.0,
                    "pred_rows": 0,
                    "gold_rows": 0,
                    "pred_path": str(pred_path),
                    "gold_path": str(gold_path) if gold_path else "",
                    "detail": "pred_full.csv not found",
                }
            )
            continue
        if not gold_path or not gold_path.exists():
            rows.append(
                {
                    "task_id": task_id,
                    "app_name": app_name,
                    "status": "missing_gold",
                    "score": 0.0,
                    "pred_rows": 0,
                    "gold_rows": 0,
                    "pred_path": str(pred_path),
                    "gold_path": "",
                    "detail": "gold csv not found",
                }
            )
            continue

        try:
            pred_df = pd.read_csv(pred_path)
            gold_df = pd.read_csv(gold_path)
            score, details = compare_dataframes(pred_df, gold_df)
            passed = score >= 1.0
            debug = {}
            if not passed:
                debug = build_diff_debug(pred_df, gold_df, sample_rows=max(1, args.debug_sample_rows))
            rows.append(
                {
                    "task_id": task_id,
                    "app_name": app_name,
                    "status": "pass" if passed else "fail",
                    "score": round(score, 4),
                    "pred_rows": int(len(pred_df)),
                    "gold_rows": int(len(gold_df)),
                    "gold_rows_matched": details.get("gold_rows_matched"),
                    "gold_rows_total": details.get("gold_rows_total"),
                    "pred_path": str(pred_path),
                    "gold_path": str(gold_path),
                    "detail": details.get("error", ""),
                    "debug": debug,
                }
            )
        except Exception as exc:
            rows.append(
                {
                    "task_id": task_id,
                    "app_name": app_name,
                    "status": "eval_error",
                    "score": 0.0,
                    "pred_rows": 0,
                    "gold_rows": 0,
                    "pred_path": str(pred_path),
                    "gold_path": str(gold_path),
                    "detail": str(exc)[:300],
                    "debug": {},
                }
            )

    print(f"\n{'task_id':22s} {'status':12s} {'score':>6s} {'rows(pred/gold)':>16s}")
    print("-" * 64)
    for r in rows:
        print(
            f"{r['task_id']:22s} {r['status']:12s} "
            f"{r.get('score', 0):6.3f} {str(r.get('pred_rows', 0)) + '/' + str(r.get('gold_rows', 0)):>16s}"
        )

    passes = sum(1 for r in rows if r["status"] == "pass")
    total = len(rows)
    print(f"\n{'=' * 64}")
    print(f"PASS: {passes}/{total} = {passes / total * 100:.1f}%" if total else "No tasks evaluated.")

    out_json = out_dir / "eval_results.json"
    out_csv = out_dir / "eval_results.csv"
    out_json.write_text(json.dumps(rows, indent=2))
    if rows:
        with out_csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    print(f"Wrote: {out_json}")
    print(f"Wrote: {out_csv}")


if __name__ == "__main__":
    main()

