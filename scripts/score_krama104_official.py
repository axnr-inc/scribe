"""score_krama104_official.py — run the patched official KramaBench evaluator
on results/krama_all104/final_results.json.

Bridges our SCRIBE output format ({"task_id", "final_answer", "domain"})
to the format Evaluator.evaluate_results expects ({"task_id", "answer"}).
Iterates per-domain (one workload JSON each), aggregates a final score.

Uses the patched evaluator at vendor/kramabench_eval/ — all 4 bug fixes apply.

USAGE:
    PYTHONPATH=vendor/kramabench_eval python3 scripts/score_krama104_official.py \\
        --results results/krama_all104/final_results.json \\
        --out results/krama_all104/official_scores
"""

from __future__ import annotations
import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(".env", override=True)

# After dotenv. Evaluator import triggers GPTInterface init which reads OPENAI_API_KEY.
from benchmark.evaluator import Evaluator  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ["archeology", "astronomy", "biomedical", "environment", "legal", "wildfire"]


def score_domain(domain: str, responses_for_domain: list[dict], out_dir: Path) -> dict:
    """Return per-task scores + per-metric aggregation for one domain."""
    workload_path = ROOT / "data" / "kramabench" / "workload" / f"{domain}.json"
    fixtures_dir  = ROOT / "vendor" / "kramabench_eval" / "benchmark" / "fixtures"
    domain_out    = out_dir / domain
    domain_out.mkdir(parents=True, exist_ok=True)

    evaluator = Evaluator(
        workload_path=str(workload_path),
        task_fixture_directory=str(fixtures_dir),
        results_directory=str(domain_out),
        run_subtasks=False,
        evaluate_pipeline=False,  # skip LLM-pipeline-eval to keep cost down
    )

    # Bridge: Evaluator expects model_output to be a DICT-like object with an
    # 'answer' key (see evaluator.py line 69: system_answer = system_response["answer"]).
    # A bare string fails with "string indices must be integers" — that's how
    # the unpatched evaluator silently sank all our wildfire scores in the
    # first run.
    bridged_responses = []
    for r in responses_for_domain:
        ans = r.get("final_answer", "") or ""
        bridged_responses.append({
            "task_id": r["task_id"],
            "answer": ans,
            "code": "",
            "model_output": {"answer": ans},  # dict-shaped per evaluator contract
        })

    print(f"\n=== Domain: {domain} ({len(bridged_responses)} responses) ===")
    eval_results = evaluator.evaluate_results(bridged_responses)
    # `eval_results` is a flat list of {task_id, metric_name: score, ...} dicts.
    (domain_out / "raw_eval_results.json").write_text(json.dumps(eval_results, indent=2))

    # Compute aggregate per-metric.
    by_metric = defaultdict(lambda: {"sum": 0.0, "n": 0, "n_none": 0})
    metric_keys = ["success", "llm_paraphrase", "f1", "precision", "recall",
                   "f1_approximate", "rae_score",
                   "mean_absolute_error", "mean_squared_error"]
    for row in eval_results:
        for k in metric_keys:
            if k in row:
                v = row[k]
                if v is None:
                    by_metric[k]["n_none"] += 1
                else:
                    try:
                        by_metric[k]["sum"] += float(v)
                        by_metric[k]["n"] += 1
                    except (TypeError, ValueError):
                        by_metric[k]["n_none"] += 1

    # Compute per-task PASS. Priority order for picking the primary metric:
    #   1. success           — numeric_exact, string_exact, boolean (binary 0/1)
    #   2. llm_paraphrase    — string_approximate (binary 0/1, GPT-5-mini judge)
    #   3. rae_score         — numeric_approximate (continuous, 1.0 = perfect)
    #   4. f1_approximate    — list_approximate (continuous)
    #   5. f1                — list_exact (continuous)
    # Strict pass: primary >= 0.999. Lenient pass: primary >= 0.5.
    # Previously the chain stopped at f1, dropping rae_score (numeric_approximate)
    # and f1_approximate (list_approximate) entirely — those tasks were always
    # graded 0 even when the answer was numerically perfect.
    per_task_pass = {}
    for row in eval_results:
        tid = row["task_id"]
        primary = (row.get("success") if row.get("success") is not None
                   else row.get("llm_paraphrase") if row.get("llm_paraphrase") is not None
                   else row.get("rae_score") if row.get("rae_score") is not None
                   else row.get("f1_approximate") if row.get("f1_approximate") is not None
                   else (row.get("f1", 0) if row.get("f1") is not None else 0))
        if isinstance(primary, str):
            try: primary = float(primary)
            except: primary = 0
        per_task_pass[tid] = float(primary or 0)

    summary = {
        "domain": domain,
        "n_tasks": len(eval_results),
        "metric_means": {k: (v["sum"]/v["n"] if v["n"] else None) for k, v in by_metric.items()},
        "metric_counts": {k: {"n": v["n"], "n_none": v["n_none"]} for k, v in by_metric.items()},
        "per_task_pass": per_task_pass,
        "pass_count_strict": sum(1 for v in per_task_pass.values() if v >= 0.999),
        "pass_count_50pct":  sum(1 for v in per_task_pass.values() if v >= 0.5),
    }
    (domain_out / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--results", required=True, help="Path to final_results.json from orchestrator.")
    p.add_argument("--out", required=True, help="Output dir for official scores.")
    args = p.parse_args()

    results = json.loads(Path(args.results).read_text())
    by_domain = defaultdict(list)
    for r in results:
        by_domain[r.get("domain", "?")].append(r)

    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    overall = {}
    for d in DOMAINS:
        if d not in by_domain:
            print(f"WARN: no results for domain {d}; skipping")
            continue
        s = score_domain(d, by_domain[d], out_dir)
        overall[d] = s

    # Final report
    total_n = sum(s["n_tasks"] for s in overall.values())
    total_strict = sum(s["pass_count_strict"] for s in overall.values())
    total_50 = sum(s["pass_count_50pct"] for s in overall.values())
    print("\n" + "="*72)
    print(f"OFFICIAL KRAMABENCH SCORE (patched evaluator)")
    print("="*72)
    print(f"{'domain':<15}{'tasks':>8}{'pass(strict)':>16}{'pass(>=0.5)':>14}")
    for d, s in overall.items():
        n = s["n_tasks"]
        ps = s["pass_count_strict"]
        p5 = s["pass_count_50pct"]
        print(f"{d:<15}{n:>8}{f'{ps}/{n} = {100*ps/n:.1f}%':>16}{f'{p5}/{n} = {100*p5/n:.1f}%':>14}")
    print("-"*72)
    print(f"{'OVERALL':<15}{total_n:>8}"
          f"{f'{total_strict}/{total_n} = {100*total_strict/total_n:.1f}%':>16}"
          f"{f'{total_50}/{total_n} = {100*total_50/total_n:.1f}%':>14}")
    (out_dir / "overall.json").write_text(json.dumps(overall, indent=2))
    print(f"\nWrote: {out_dir}/overall.json + per-domain summaries")


if __name__ == "__main__":
    main()
