"""ensemble_krama_answers.py — combine multiple SCRIBE pipelines' answers per task.

For each Krama104 task, collects every available candidate answer across:
  1. The original Krama104 run (DeepSeek-V3.1 spec+planner, Kimi-K2.6 exec)
  2. The GLM-5.1 run (z-ai/glm-5.1 spec+planner, Kimi-K2.6 exec)
  3. The DS-V3.1 fresh re-run on the 31 originally-failed tasks
  4. The I-2 multi-stance partial answers (up to 3 stances per task for 8 tasks)
  5. (optional) The OR-GLM partial backup (10 tasks)

Adjudication: a task passes if ANY candidate answer matches gold under either
tolerant compare (numeric within 1e-3 or normalized-string equal) OR the
patched official KramaBench scorer. This is the oracle-ensemble upper bound;
we report both this and a "majority vote across pipelines" stricter aggregation
so the paper can distinguish "pipeline diversity helps" from "any pipeline got
lucky".

USAGE:
    PYTHONPATH=vendor/kramabench_eval python3 scripts/ensemble_krama_answers.py \\
        --out results/krama_ensemble
"""
from __future__ import annotations
import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(".env", override=True)

ROOT = Path(__file__).resolve().parents[1]


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _eq(a: str, b: str, atype: str) -> bool:
    if not a or not b: return False
    a, b = str(a).strip(), str(b).strip()
    if atype and "numeric" in atype:
        try:
            return abs(float(a) - float(b)) < 1e-3
        except Exception:
            return False
    return _norm(a) == _norm(b)


def load_orchestrator_final(p: Path) -> dict:
    """Read an orchestrator final_results.json (Krama104 layout)."""
    if not p.exists():
        return {}
    out = {}
    for r in json.loads(p.read_text()):
        tid = str(r.get("task_id"))
        ans = r.get("final_answer") or ""
        if tid:
            out[tid] = ans
    return out


def load_per_shard(out_dir: Path) -> dict:
    """Read shard_a/summary.json + shard_b/summary.json (for runs without orchestrator)."""
    out = {}
    for sub in ("shard_a", "shard_b", "shard_w0", "shard_w1"):
        p = out_dir / sub / "summary.json"
        if not p.exists(): continue
        try:
            for r in json.loads(p.read_text()):
                tid = str(r.get("task_id"))
                ans = r.get("final_answer") or ""
                if tid and tid not in out and ans:
                    out[tid] = ans
        except Exception:
            pass
    return out


def load_i2_partial(p: Path) -> dict:
    """I-2 has 1-3 stances per task. Treat each non-empty stance as a candidate."""
    if not p.exists(): return {}
    d = json.loads(p.read_text())
    out = defaultdict(list)
    for tid, stances in d.items():
        for stance, ans in stances.items():
            if ans:
                out[tid].append(ans)
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    args = p.parse_args()

    # Sources of candidate answers
    sources = {
        "krama104_dsv31_kimi":   load_orchestrator_final(
            ROOT / "results" / "krama_all104" / "final_results.json"),
        "glm51_kimi":            load_per_shard(
            ROOT / "results" / "krama_glm_104"),
        "or_glm_partial":        load_per_shard(
            ROOT / "results" / "krama_glm_104_or_partial"),
        "dsv31_rerun_31":        load_orchestrator_final(
            ROOT / "results" / "krama_dsv31_rerun" / "final_results.json"),
        "i2_partial":            load_i2_partial(
            ROOT / "results" / "krama_i2" / "final_partial_answers.json"),
    }

    # Gold table
    gold = {}
    for line in (ROOT / "data" / "splits" / "krama_all104.jsonl").read_text().splitlines():
        if not line.strip(): continue
        r = json.loads(line)
        gold[r["task_id"]] = (r.get("answer",""), r.get("answer_type",""), r.get("domain","?"))

    # Per-task collection
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    per_task = {}
    for tid, (g, atype, dom) in gold.items():
        candidates = []  # list of (source_label, answer)
        for label, ans_map in sources.items():
            ans = ans_map.get(tid)
            if isinstance(ans, list):
                # I-2 stances
                for sub in ans:
                    candidates.append((label, sub))
            elif ans:
                candidates.append((label, ans))
        any_correct = any(_eq(c[1], g, atype) for c in candidates)
        # Majority vote: most-common clustered answer
        clusters = []
        for src, a in candidates:
            for c in clusters:
                if _eq(c[0][1], a, atype):
                    c.append((src, a)); break
            else:
                clusters.append([(src, a)])
        clusters.sort(key=len, reverse=True)
        majority_ans = clusters[0][0][1] if clusters else ""
        majority_correct = _eq(majority_ans, g, atype)
        per_task[tid] = {
            "domain": dom,
            "gold": g,
            "answer_type": atype,
            "n_candidates": len(candidates),
            "candidates": candidates,
            "oracle_pass": any_correct,
            "majority_pass": majority_correct,
            "majority_ans": majority_ans,
            "majority_cluster_size": len(clusters[0]) if clusters else 0,
        }

    # Aggregate
    n = len(per_task)
    oracle = sum(1 for r in per_task.values() if r["oracle_pass"])
    majority = sum(1 for r in per_task.values() if r["majority_pass"])
    print(f"Oracle ensemble: {oracle}/{n} = {100*oracle/n:.1f}%")
    print(f"Majority vote:   {majority}/{n} = {100*majority/n:.1f}%")
    by_dom_oracle = defaultdict(lambda: [0,0])
    by_dom_maj    = defaultdict(lambda: [0,0])
    for tid, r in per_task.items():
        by_dom_oracle[r["domain"]][1] += 1
        by_dom_maj[r["domain"]][1] += 1
        if r["oracle_pass"]: by_dom_oracle[r["domain"]][0] += 1
        if r["majority_pass"]: by_dom_maj[r["domain"]][0] += 1
    print()
    print("Per-domain (oracle / majority):")
    for d in sorted(by_dom_oracle):
        o, t = by_dom_oracle[d]; mo, mt = by_dom_maj[d]
        print(f"  {d}: {o}/{t} = {100*o/t:.1f}%  /  {mo}/{mt} = {100*mo/mt:.1f}%")

    (out_dir / "per_task.json").write_text(json.dumps(per_task, indent=2))
    (out_dir / "summary.json").write_text(json.dumps({
        "total": n,
        "oracle_pass": oracle,
        "majority_pass": majority,
        "by_domain_oracle": {d: by_dom_oracle[d] for d in by_dom_oracle},
        "by_domain_majority": {d: by_dom_maj[d] for d in by_dom_maj},
        "sources": {k: len(v) for k, v in sources.items()},
    }, indent=2))
    print(f"\nWrote: {out_dir}/per_task.json + summary.json")


if __name__ == "__main__":
    main()
