"""Progressive scorer — polls results/krama_opus_104/summary.json every 30s,
applies the last-line extraction fix, runs the patched scorer at each
10-task milestone, and prints a running snapshot.

USAGE:
    PYTHONPATH=vendor/kramabench_eval python3 scripts/progressive_score_opus.py
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

RUN_DIR = Path("results/krama_opus_104")
SUMMARY = RUN_DIR / "summary.json"
TASKS_TOTAL = 104
MILESTONE = 10
POLL_INTERVAL = 30


def last_line(s: str) -> str:
    s = s or ""
    for ln in reversed(s.split("\n")):
        if ln.strip():
            return ln.strip()
    return s


def materialize(rows):
    """Convert summary.json rows to scorer-input shape with last-line fix."""
    return [
        {
            "task_id": r["task_id"],
            "final_answer": last_line(r.get("final_answer") or ""),
            "domain": r.get("task_id", "x-x-x").split("-")[0],
        }
        for r in rows
    ]


def score(rows, snapshot_dir):
    """Write rows to a file and invoke the patched scorer; return overall summary."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    inp = snapshot_dir / "final_results_lastline.json"
    inp.write_text(json.dumps(rows, indent=2))
    out = snapshot_dir / "official_scores"
    env = dict(os.environ)
    env["PYTHONPATH"] = "vendor/kramabench_eval"
    proc = subprocess.run(
        ["python3", "scripts/score_krama104_official.py",
         "--results", str(inp), "--out", str(out)],
        env=env, capture_output=True, text=True, timeout=600,
    )
    if proc.returncode != 0:
        print(f"  scorer failed: {proc.stderr[:300]}", flush=True)
        return None
    overall_path = out / "overall.json"
    if not overall_path.exists():
        return None
    return json.loads(overall_path.read_text())


def fmt_pct(n, d):
    return f"{n}/{d} = {100*n/d:.1f}%" if d else "—"


def main():
    print(f"[progressive scorer] watching {SUMMARY}, milestone every {MILESTONE} tasks, target {TASKS_TOTAL}", flush=True)
    last_scored = 0
    while True:
        if not SUMMARY.exists():
            time.sleep(POLL_INTERVAL)
            continue
        try:
            rows = json.loads(SUMMARY.read_text())
        except (json.JSONDecodeError, FileNotFoundError):
            time.sleep(POLL_INTERVAL)
            continue
        n = len(rows)
        crossed = n // MILESTONE
        if crossed > last_scored // MILESTONE or n == TASKS_TOTAL:
            snapshot = RUN_DIR / f"_progressive/at_n{n}"
            print(f"\n[t={time.strftime('%H:%M:%S')}] n={n}/{TASKS_TOTAL} — scoring…", flush=True)
            scored = score(materialize(rows), snapshot)
            if scored:
                strict = sum(v["pass_count_strict"] for v in scored.values())
                lenient = sum(v["pass_count_50pct"] for v in scored.values())
                total = sum(v["n_tasks"] for v in scored.values())
                print(f"  OVERALL strict={fmt_pct(strict,total)} lenient={fmt_pct(lenient,total)}", flush=True)
                for dom, v in sorted(scored.items()):
                    print(f"    {dom:13s} strict={fmt_pct(v['pass_count_strict'],v['n_tasks'])} lenient={fmt_pct(v['pass_count_50pct'],v['n_tasks'])}", flush=True)
            last_scored = n
            if n >= TASKS_TOTAL:
                print(f"\n[done] all {TASKS_TOTAL} tasks scored. Snapshot at {snapshot}", flush=True)
                return
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[interrupted]", flush=True)
        sys.exit(0)
