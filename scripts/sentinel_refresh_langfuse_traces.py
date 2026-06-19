#!/usr/bin/env python3
"""Fetch Langfuse trace metrics for a SCRIBE Sentinel run and merge into summary.

Reads per-task langfuse_trace_id from summary.json (or specs/*/_meta), calls
Langfuse public API, and writes:
  - <out>/langfuse_traces.json   per-task fetched metrics
  - updates summary.json entries with langfuse_trace field when present

Usage:
    LANGFUSE_ENABLED=1 python3 scripts/sentinel_refresh_langfuse_traces.py \\
        --out results/sentinel_regression
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def load_trace_ids(out_dir: Path) -> dict[str, str]:
    ids: dict[str, str] = {}

    summary_path = out_dir / "summary.json"
    if summary_path.exists():
        for row in json.loads(summary_path.read_text()):
            tid = row.get("task_id")
            trace_id = row.get("langfuse_trace_id")
            if tid and trace_id:
                ids[str(tid)] = str(trace_id)

    specs_dir = out_dir / "specs"
    if specs_dir.is_dir():
        for spec_path in specs_dir.glob("*.json"):
            name = spec_path.name
            if any(x in name for x in (".original.", ".spec_session.", ".planner_session.")):
                continue
            try:
                obj = json.loads(spec_path.read_text())
            except Exception:
                continue
            meta = obj.get("_meta") or {}
            trace_id = meta.get("langfuse_trace_id")
            if trace_id:
                ids[spec_path.stem] = str(trace_id)

    for task_dir in out_dir.iterdir():
        if not task_dir.is_dir():
            continue
        sidecar = task_dir / "langfuse.json"
        if sidecar.exists():
            try:
                obj = json.loads(sidecar.read_text())
                if obj.get("langfuse_trace_id"):
                    ids[task_dir.name] = str(obj["langfuse_trace_id"])
            except Exception:
                pass

    return ids


def main() -> None:
    ap = argparse.ArgumentParser(description="Refresh Langfuse trace metrics for a SCRIBE run")
    ap.add_argument("--out", required=True, help="SCRIBE run output directory")
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--delay", type=float, default=5.0)
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")

    from langfuse_utils import fetch_langfuse_trace, is_langfuse_enabled

    out_dir = Path(args.out).expanduser().resolve()
    if not out_dir.is_dir():
        raise SystemExit(f"Not found: {out_dir}")
    if not is_langfuse_enabled():
        raise SystemExit("LANGFUSE_ENABLED=1 and API keys required")

    trace_ids = load_trace_ids(out_dir)
    if not trace_ids:
        raise SystemExit(f"No langfuse_trace_id found under {out_dir}")

    rows: list[dict] = []
    for task_id in sorted(trace_ids):
        trace_id = trace_ids[task_id]
        data = fetch_langfuse_trace(trace_id, retries=args.retries, delay=args.delay) or {}
        row = {"task_id": task_id, **data}
        rows.append(row)
        status = "ok" if data.get("total_cost_usd") is not None else "pending"
        print(f"  {task_id}: {status}  {data.get('langfuse_url', trace_id)}")

    out_path = out_dir / "langfuse_traces.json"
    out_path.write_text(json.dumps(rows, indent=2))
    print(f"\nWrote {out_path} ({len(rows)} traces)")

    summary_path = out_dir / "summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        by_task = {r["task_id"]: r for r in rows}
        for entry in summary:
            tid = entry.get("task_id")
            if tid in by_task:
                entry["langfuse_trace"] = by_task[tid]
        summary_path.write_text(json.dumps(summary, indent=2))
        print(f"Updated {summary_path}")


if __name__ == "__main__":
    main()
