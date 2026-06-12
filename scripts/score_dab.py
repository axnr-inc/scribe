"""score_dab.py — score a SCRIBE DataAgentBench run by invoking each task's
per-query validate.py.

Each DAB task's `answer` field carries a JSON-encoded pointer
{dataset, query} that locates the validate.py + ground_truth.csv inside the
DAB clone (default: /tmp/dab_clone).

USAGE:
    python3 scripts/score_dab.py \\
        --results results/dab_smoke/final_results.json \\
        --tasks   data/splits/dab_sqlite_duckdb.jsonl \\
        --out     results/dab_smoke/score.json

If multiple results rows share the same task_id (multi-trial), pass@1 is
reported as (# tasks with ≥1 passing trial) / (# tasks).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

DAB_ROOT = Path("/tmp/dab_clone")

# Some validators (e.g. github_repos-q2) import from `common_scaffold` in the
# DAB repo. Add the repo root to sys.path so those imports resolve.
if str(DAB_ROOT) not in sys.path:
    sys.path.insert(0, str(DAB_ROOT))


def load_validator(dataset: str, query: str):
    vpath = DAB_ROOT / f"query_{dataset}" / f"query{query}" / "validate.py"
    if not vpath.exists():
        raise FileNotFoundError(f"validate.py not found: {vpath}")
    spec = importlib.util.spec_from_file_location(
        f"dab_validate_{dataset}_{query}", vpath
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "validate"):
        raise AttributeError(f"validate.py missing validate(): {vpath}")
    return mod.validate


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results", required=True,
                   help="Path to summary.json (or final_results.json) from src/run.ts")
    p.add_argument("--tasks", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    tasks = {}
    for line in Path(args.tasks).read_text().splitlines():
        if not line.strip():
            continue
        t = json.loads(line)
        tasks[t["task_id"]] = t

    results = json.loads(Path(args.results).read_text())
    # results may be list[dict] or dict["results"] = list[dict] depending on caller
    if isinstance(results, dict) and "results" in results:
        results = results["results"]

    # Group by task_id (supports multi-trial pass@1).
    trials = defaultdict(list)
    for r in results:
        trials[r["task_id"]].append(r)

    per_task = []
    for tid, t in tasks.items():
        ptr = json.loads(t["answer"])
        dataset = ptr["dataset"]
        query = str(ptr["query"])
        validator = load_validator(dataset, query)
        runs = trials.get(tid, [])
        trial_results = []
        for r in runs:
            ans = (r.get("final_answer") or "").strip()
            try:
                ok, reason = validator(ans)
            except Exception as e:
                ok, reason = False, f"validator raised: {e}"
            trial_results.append({"answer": ans, "pass": bool(ok), "reason": reason})
        pass_any = any(tr["pass"] for tr in trial_results) if trial_results else False
        per_task.append({
            "task_id": tid,
            "domain": t["domain"],
            "dataset": dataset,
            "query": query,
            "n_trials": len(trial_results),
            "pass": pass_any,
            "trials": trial_results,
        })

    # Aggregate.
    by_domain = defaultdict(lambda: {"n": 0, "pass": 0})
    total_n = total_pass = 0
    for row in per_task:
        d = row["domain"]
        by_domain[d]["n"] += 1
        by_domain[d]["pass"] += int(row["pass"])
        total_n += 1
        total_pass += int(row["pass"])

    summary = {
        "n_tasks": total_n,
        "n_pass": total_pass,
        "pass_at_1": total_pass / total_n if total_n else 0.0,
        "by_domain": {
            d: {
                "n": v["n"],
                "pass": v["pass"],
                "rate": v["pass"] / v["n"] if v["n"] else 0.0,
            } for d, v in by_domain.items()
        },
        "per_task": per_task,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(summary, indent=2))

    print("=" * 72)
    print(f"DataAgentBench (SQLite/DuckDB subset) — pass@1")
    print("=" * 72)
    print(f"{'domain':<22}{'tasks':>8}{'pass':>8}{'rate':>10}")
    for d, v in sorted(by_domain.items()):
        rate = v["pass"] / v["n"] if v["n"] else 0
        print(f"{d:<22}{v['n']:>8}{v['pass']:>8}{f'{100*rate:.1f}%':>10}")
    print("-" * 72)
    rate = total_pass / total_n if total_n else 0
    print(f"{'OVERALL':<22}{total_n:>8}{total_pass:>8}{f'{100*rate:.1f}%':>10}")
    print(f"\nWrote: {args.out}")


if __name__ == "__main__":
    main()
