"""Grade a run using the official DABStep question_scorer.

Walks a results dir produced by `npx tsx src/run.ts` (looks for sessions/normal_agent.jsonl
under each task subdir), extracts the final assistant_response, scores against gold,
and writes results.csv + results.json + a 1-page summary.

Example:
  python scripts/grade.py --out results/sonnet_kimi --gold data/verified_answers.json
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from scorer import question_scorer


def load_gold(path: Path) -> dict:
    d = json.load(open(path))
    out = {}
    for tid, v in d.items():
        if isinstance(v, dict):
            out[str(tid)] = v.get("verified_answer", v.get("answer", ""))
        else:
            out[str(tid)] = str(v)
    return out


def session_summary(session_log: Path) -> dict:
    rows = [json.loads(l) for l in session_log.read_text().splitlines() if l.strip()]
    responses = [r.get("content","") for r in rows
                 if (r.get("event") or r.get("type")) == "assistant_response"
                 and r.get("content","").strip()]
    final = responses[-1] if responses else ""
    return {
        "final_answer": final,
        "events": len(rows),
        "tool_calls": sum(1 for r in rows if (r.get("event") or r.get("type")) == "tool_call"),
        "thinking_blocks": sum(1 for r in rows if (r.get("event") or r.get("type")) == "assistant_thinking"),
        "repl_timeouts": sum(1 for r in rows
                             if (r.get("event") or r.get("type")) == "tool_call_result"
                             and "timed out" in r.get("content","")),
    }


def extract_final_value(response: str) -> str:
    """Take the last non-empty line of the response as the answer (DABStep convention)."""
    if not response: return ""
    lines = [ln.strip() for ln in response.strip().split("\n") if ln.strip()]
    if not lines: return ""
    last = lines[-1].lstrip("*•- >").rstrip("*•- ")
    if last.startswith("`") and last.endswith("`"):
        last = last.strip("`")
    return last.strip()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="Run output directory (contains <task_id>/sessions/...)")
    p.add_argument("--gold", required=True, help="Gold answers JSON")
    args = p.parse_args()

    out_dir = Path(args.out)
    gold = load_gold(Path(args.gold))

    # The harness writes per-task subdirs containing sessions/normal_agent.jsonl
    task_dirs = sorted(d for d in out_dir.iterdir() if d.is_dir() and (d / "sessions/normal_agent.jsonl").exists())
    if not task_dirs:
        raise SystemExit(f"No task session logs found under {out_dir}")

    results = []
    for td in task_dirs:
        tid = td.name
        log = td / "sessions/normal_agent.jsonl"
        summ = session_summary(log)
        pred_final = extract_final_value(summ["final_answer"])
        gold_v = gold.get(tid)
        correct = False
        if gold_v and pred_final:
            try:
                correct = bool(question_scorer(pred_final, gold_v))
            except Exception:
                correct = False
        results.append({
            "task_id": tid,
            "correct": correct,
            "tool_calls": summ["tool_calls"],
            "thinking_blocks": summ["thinking_blocks"],
            "repl_timeouts": summ["repl_timeouts"],
            "events": summ["events"],
            "pred_final": pred_final[:200],
            "gold": (gold_v or "")[:200],
            "trace_path": str(log),
        })

    # Write CSV
    csv_path = out_dir / "results.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        for r in results: w.writerow(r)

    # Write JSON
    (out_dir / "results.json").write_text(json.dumps(results, indent=2))

    # Summary
    n = len(results)
    passed = sum(1 for r in results if r["correct"])
    print(f"\n=== Results for {out_dir.name} ===")
    print(f"  pass rate: {passed}/{n}  ({100*passed/n:.0f}%)")
    print()
    print(f"  {'task':<8} {'tc':>4} {'tb':>4} {'cap':>4}  {'gold':<40} {'pred':<40}  {'✓/✗':>4}")
    print(f"  {'-'*100}")
    for r in results:
        mark = "✓" if r["correct"] else "✗"
        print(f"  {r['task_id']:<8} {r['tool_calls']:>4} {r['thinking_blocks']:>4} {r['repl_timeouts']:>4}  {r['gold'][:38]:<40} {r['pred_final'][:38]:<40}  {mark:>4}")
    print()
    print(f"Wrote {csv_path} and {out_dir/'results.json'}")


if __name__ == "__main__":
    main()
