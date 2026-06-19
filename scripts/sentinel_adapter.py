#!/usr/bin/env python3
"""Convert sentinel-eval-sdk eval_input.json → SCRIBE harness tasks.jsonl.

Usage:
  python scripts/sentinel_adapter.py --group smoke --out results/sentinel_smoke/tasks.jsonl

Environment:
  SENTINEL_SDK_PATH  — path to sentinel-eval-sdk (default: ../sentinel-eval-sdk)
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SENTINEL = ROOT.parent / "sentinel-eval-sdk"


def resolve_sentinel_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    env = os.environ.get("SENTINEL_SDK_PATH", "").strip()
    if env:
        return Path(env).expanduser().resolve()
    return DEFAULT_SENTINEL.resolve()


GROUPS = {
    "smoke": {"smoke"},
    "regression": {"smoke", "regression"},
    "extended": {"extended"},
    "all": {"smoke", "regression", "extended"},
}


def main() -> None:
    ap = argparse.ArgumentParser(description="Sentinel eval → SCRIBE task JSONL")
    ap.add_argument("--input", default=None, help="eval_input.json path")
    ap.add_argument("--sentinel-root", default=None, help="sentinel-eval-sdk root")
    ap.add_argument("--group", default="smoke", choices=sorted(GROUPS))
    ap.add_argument("--limit", type=int, default=None,
                    help="Keep only the first N tasks (after group filter)")
    ap.add_argument("--task-ids", default=None,
                    help="Comma-separated question_ids to include (must also match --group)")
    ap.add_argument("--include-follow-ups", action="store_true",
                    help="Include questions with follow_ups (SCRIBE runs first turn only)")
    ap.add_argument("--out", required=True, help="Output tasks.jsonl")
    args = ap.parse_args()

    sentinel = resolve_sentinel_root(args.sentinel_root)
    input_path = Path(args.input) if args.input else sentinel / "eval_input.json"
    context_root = sentinel / "context_downloads"
    allowed = GROUPS[args.group]
    want_ids = {x.strip() for x in args.task_ids.split(",") if x.strip()} if args.task_ids else None

    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")
    if not context_root.exists():
        raise SystemExit(
            f"Context not found: {context_root}\n"
            f"Run: cd {sentinel} && python download_context.py"
        )

    rows: list[dict] = []
    for q in json.load(open(input_path)):
        meta = q.get("metadata") or {}
        if meta.get("group") not in allowed:
            continue
        if want_ids and q["question_id"] not in want_ids:
            continue
        if q.get("follow_ups") and not args.include_follow_ups:
            continue

        app = q["app_name"]
        ctx = context_root / app
        if not ctx.is_dir():
            print(f"  WARN: missing context for {q['question_id']} → {ctx}")

        gold_rel = meta.get("gold_csv_path")
        gold_abs = str(sentinel / gold_rel) if gold_rel else None

        guidelines = "\n".join([
            f"Database app: {app}",
            f"Dataset: {meta.get('dataset', '')}",
            f"Hardness: {meta.get('hardness_label', '')}",
            f"Context directory: {ctx}",
            "SQL dialect: PostgreSQL (via ConnectionService).",
            "Output: present results as a table matching the requested column names.",
        ])

        rows.append({
            "task_id": q["question_id"],
            "question": q["question"],
            "guidelines": guidelines,
            "level": meta.get("hardness_label", "medium"),
            "context_dir": str(ctx),
            "app_name": app,
            "gold_csv_path": gold_abs,
            "dataset": meta.get("dataset"),
        })

    if args.limit is not None and args.limit > 0:
        rows = rows[: args.limit]

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    manifest = {
        "sentinel_root": str(sentinel),
        "input": str(input_path),
        "group": args.group,
        "limit": args.limit,
        "task_ids": sorted(want_ids) if want_ids else None,
        "task_count": len(rows),
        "context_root": str(context_root),
    }
    out.with_name("sentinel_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote {len(rows)} tasks → {out}")


if __name__ == "__main__":
    main()
