#!/usr/bin/env python3
"""Aggregate token usage and estimated cost for a Sentinel SCRIBE run.

Reads:
  - summary.json          executor + planner per task (from src/run.ts)
  - specs/*.json          spec-extraction _meta (input/output tokens)
  - run_manifest.json     model config (optional)

Writes:
  - usage.json            machine-readable totals + per-task breakdown

Usage:
    python3 scripts/sentinel_usage_report.py --out results/sentinel_smoke2_opus
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Mirror src/harness/services/token_tracker.ts (USD per 1M tokens).
PRICING: dict[str, dict[str, float]] = {
    "claude-opus-4-8": {"input": 5, "output": 25, "cacheWrite5m": 6.25, "cacheHit": 0.50},
    "claude-opus-4-7": {"input": 5, "output": 25, "cacheWrite5m": 6.25, "cacheHit": 0.50},
    "claude-opus-4-6": {"input": 5, "output": 25, "cacheWrite5m": 6.25, "cacheHit": 0.50},
    "claude-sonnet-4-6": {"input": 3, "output": 15, "cacheWrite5m": 3.75, "cacheHit": 0.30},
    "claude-sonnet-4-5": {"input": 3, "output": 15, "cacheWrite5m": 3.75, "cacheHit": 0.30},
    "claude-haiku-4-5": {"input": 1, "output": 5, "cacheWrite5m": 1.25, "cacheHit": 0.10},
    "kimi-k2p6": {"input": 0.60, "output": 2.50, "cacheWrite5m": 0.60, "cacheHit": 0.60},
    "gpt-5": {"input": 1.25, "output": 10.0, "cacheWrite5m": 1.25, "cacheHit": 0.125},
    "mercury-2": {"input": 0.25, "output": 0.75, "cacheWrite5m": 0.25, "cacheHit": 0.25},
}


def resolve_model(model: str) -> str:
    tail = model.split("/")[-1] if model else model
    for key in PRICING:
        if model == key or tail == key or key in model:
            return key
    return tail or model


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Uncached input pricing (spec extraction has no cache breakdown)."""
    key = resolve_model(model)
    p = PRICING.get(key)
    if not p:
        return 0.0
    return (input_tokens / 1_000_000) * p["input"] + (output_tokens / 1_000_000) * p["output"]


def parse_extractor(extractor: str) -> tuple[str, str]:
    if ":" in extractor:
        prov, model = extractor.split(":", 1)
        return prov, model
    return "", extractor


def load_spec_usage(specs_dir: Path) -> list[dict]:
    rows: list[dict] = []
    if not specs_dir.is_dir():
        return rows
    for path in sorted(specs_dir.glob("*.json")):
        name = path.name
        if any(x in name for x in (".original.", ".spec_session.", ".planner_session.")):
            continue
        try:
            obj = json.loads(path.read_text())
        except Exception:
            continue
        if not isinstance(obj, dict) or "_error" in obj:
            continue
        meta = obj.get("_meta") or {}
        extractor = meta.get("extractor", "unknown")
        _, model = parse_extractor(extractor)
        in_tok = int(meta.get("input_tokens") or 0)
        out_tok = int(meta.get("output_tokens") or 0)
        rows.append({
            "task_id": path.stem,
            "extractor": extractor,
            "model": model,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "cost_usd": estimate_cost(model, in_tok, out_tok) if in_tok or out_tok else 0.0,
            "tokens_recorded": bool(in_tok or out_tok),
        })
    return rows


def load_executor_usage(out_dir: Path) -> list[dict]:
    summary_path = out_dir / "summary.json"
    if summary_path.exists():
        rows = json.loads(summary_path.read_text())
        if isinstance(rows, list) and rows:
            out: list[dict] = []
            for r in rows:
                out.append({
                    "task_id": r.get("task_id"),
                    "wall_seconds": r.get("wall_seconds", 0),
                    "executor_model": r.get("executor_model", ""),
                    "executor_input_tokens": r.get("executor_input_tokens", 0),
                    "executor_output_tokens": r.get("executor_output_tokens", 0),
                    "executor_cost_usd": r.get("executor_cost_usd", 0),
                    "planner_model": r.get("planner_model"),
                    "planner_input_tokens": r.get("planner_input_tokens", 0),
                    "planner_output_tokens": r.get("planner_output_tokens", 0),
                    "planner_cost_usd": r.get("planner_cost_usd", 0),
                    "planner_calls": r.get("planner_calls", 0),
                    "cost_usd": r.get("cost_usd", 0),
                    "tool_calls": r.get("tool_calls", 0),
                    "ask_planner_calls": r.get("ask_planner_calls", 0),
                })
            return out

    # Partial run: planner sidecars only (executor totals unavailable).
    out = []
    for task_dir in sorted(out_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        pc_path = task_dir / "sessions" / "planner_cost.json"
        if not pc_path.exists():
            continue
        try:
            pc = json.loads(pc_path.read_text())
        except Exception:
            continue
        model = pc.get("model") or "claude-sonnet-4-6"
        pin = int(pc.get("input_tokens") or 0)
        pout = int(pc.get("output_tokens") or 0)
        out.append({
            "task_id": task_dir.name,
            "wall_seconds": 0,
            "executor_model": "",
            "executor_input_tokens": 0,
            "executor_output_tokens": 0,
            "executor_cost_usd": 0,
            "planner_model": model,
            "planner_input_tokens": pin,
            "planner_output_tokens": pout,
            "planner_cost_usd": estimate_cost(model, pin, pout),
            "planner_calls": pc.get("calls", 0),
            "cost_usd": estimate_cost(model, pin, pout),
            "tool_calls": 0,
            "ask_planner_calls": pc.get("calls", 0),
            "partial": True,
        })
    return out


def fmt_tokens(n: int) -> str:
    return f"{n:,}"


def print_report(report: dict) -> None:
    t = report["totals"]
    print()
    print("=" * 60)
    print("  TOKEN USAGE & ESTIMATED COST")
    print("=" * 60)
    print(f"  Output dir: {report['out_dir']}")
    if report.get("config"):
        print(f"  Config:     {report['config']}")
    if report.get("executor_model"):
        print(f"  Executor:   {report['executor_model']}")
    if report.get("planner_model"):
        print(f"  Planner:    {report['planner_model']}")
    print()

    # Per-task table
    tasks = report.get("per_task") or []
    if tasks:
        print(f"{'task_id':22s} {'spec in/out':>18s} {'exec in/out':>18s} {'plan in/out':>18s} {'$task':>8s}")
        print("-" * 90)
        for row in tasks:
            spec = f"{row['spec_in']}/{row['spec_out']}"
            exec_ = f"{row['exec_in']}/{row['exec_out']}"
            plan = f"{row['plan_in']}/{row['plan_out']}"
            print(f"{row['task_id']:22s} {spec:>18s} {exec_:>18s} {plan:>18s} {row['cost_usd']:>8.4f}")
        print("-" * 90)

    print()
    print("  Stage totals:")
    spec = t["spec"]
    exec_ = t["executor"]
    plan = t["planner"]
    print(f"    Spec extraction:  {fmt_tokens(spec['input_tokens']):>10s} in / {fmt_tokens(spec['output_tokens']):<10s} out   ${spec['cost_usd']:.4f}")
    if spec.get("tasks_without_tokens"):
        print(f"      (warning: {spec['tasks_without_tokens']} spec(s) missing token counts — re-run extract or estimate manually)")
    print(f"    Executor:         {fmt_tokens(exec_['input_tokens']):>10s} in / {fmt_tokens(exec_['output_tokens']):<10s} out   ${exec_['cost_usd']:.4f}")
    print(f"    Planner:          {fmt_tokens(plan['input_tokens']):>10s} in / {fmt_tokens(plan['output_tokens']):<10s} out   ${plan['cost_usd']:.4f}")
    print()
    print(f"    RUN TOTAL (exec+planner):  ${t['run_cost_usd']:.4f}")
    print(f"    PIPELINE TOTAL (+spec):    ${t['pipeline_cost_usd']:.4f}")
    if t.get("task_count"):
        print(f"    Per task (pipeline):       ${t['pipeline_cost_usd'] / t['task_count']:.4f}")
    if t.get("wall_seconds"):
        print(f"    Wall time (executor):        {t['wall_seconds'] / 60:.1f} min")
    if report.get("partial_run"):
        print()
        print("  Note: summary.json missing — executor tokens not included (planner sidecars only).")
    print()
    print(f"  Wrote {report['usage_path']}")
    print("=" * 60)


def build_report(out_dir: Path) -> dict:
    specs_dir = out_dir / "specs"
    spec_rows = load_spec_usage(specs_dir)
    exec_rows = load_executor_usage(out_dir)

    spec_by_task = {r["task_id"]: r for r in spec_rows}
    exec_by_task = {r["task_id"]: r for r in exec_rows}
    all_tasks = sorted(set(spec_by_task) | set(exec_by_task))

    per_task: list[dict] = []
    for tid in all_tasks:
        s = spec_by_task.get(tid, {})
        e = exec_by_task.get(tid, {})
        spec_cost = s.get("cost_usd", 0)
        exec_cost = e.get("executor_cost_usd", 0)
        plan_cost = e.get("planner_cost_usd", 0)
        per_task.append({
            "task_id": tid,
            "spec_in": s.get("input_tokens", 0),
            "spec_out": s.get("output_tokens", 0),
            "spec_cost_usd": spec_cost,
            "exec_in": e.get("executor_input_tokens", 0),
            "exec_out": e.get("executor_output_tokens", 0),
            "exec_cost_usd": exec_cost,
            "plan_in": e.get("planner_input_tokens", 0),
            "plan_out": e.get("planner_output_tokens", 0),
            "plan_cost_usd": plan_cost,
            "cost_usd": spec_cost + exec_cost + plan_cost,
            "wall_seconds": e.get("wall_seconds", 0),
        })

    spec_in = sum(r["input_tokens"] for r in spec_rows)
    spec_out = sum(r["output_tokens"] for r in spec_rows)
    spec_cost = sum(r["cost_usd"] for r in spec_rows)
    tasks_without_tokens = sum(1 for r in spec_rows if not r.get("tokens_recorded"))

    exec_in = sum(r["executor_input_tokens"] for r in exec_rows)
    exec_out = sum(r["executor_output_tokens"] for r in exec_rows)
    exec_cost = sum(r["executor_cost_usd"] for r in exec_rows)

    plan_in = sum(r["planner_input_tokens"] for r in exec_rows)
    plan_out = sum(r["planner_output_tokens"] for r in exec_rows)
    plan_cost = sum(r["planner_cost_usd"] for r in exec_rows)

    run_cost = exec_cost + plan_cost
    pipeline_cost = run_cost + spec_cost
    wall = sum(r.get("wall_seconds", 0) for r in exec_rows)

    manifest_path = out_dir / "run_manifest.json"
    config = executor_model = planner_model = None
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        config = m.get("config")
        if isinstance(m.get("model"), dict):
            executor_model = m["model"].get("model")
        if isinstance(m.get("planner"), dict):
            planner_model = m["planner"].get("model")

    usage_path = out_dir / "usage.json"
    partial_run = not (out_dir / "summary.json").exists() and bool(exec_rows)
    report = {
        "out_dir": str(out_dir.resolve()),
        "config": config,
        "executor_model": executor_model,
        "planner_model": planner_model,
        "partial_run": partial_run,
        "usage_path": str(usage_path),
        "per_task": per_task,
        "spec_extraction": spec_rows,
        "executor": exec_rows,
        "totals": {
            "spec": {
                "input_tokens": spec_in,
                "output_tokens": spec_out,
                "cost_usd": spec_cost,
                "tasks_without_tokens": tasks_without_tokens,
            },
            "executor": {
                "input_tokens": exec_in,
                "output_tokens": exec_out,
                "cost_usd": exec_cost,
            },
            "planner": {
                "input_tokens": plan_in,
                "output_tokens": plan_out,
                "cost_usd": plan_cost,
            },
            "run_cost_usd": run_cost,
            "pipeline_cost_usd": pipeline_cost,
            "task_count": len(all_tasks),
            "wall_seconds": wall,
        },
    }
    usage_path.write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description="Sentinel SCRIBE usage + cost report")
    ap.add_argument("--out", required=True, help="SCRIBE output directory")
    args = ap.parse_args()
    out_dir = Path(args.out).expanduser().resolve()
    if not out_dir.is_dir():
        raise SystemExit(f"Not a directory: {out_dir}")
    report = build_report(out_dir)
    print_report(report)


if __name__ == "__main__":
    main()
