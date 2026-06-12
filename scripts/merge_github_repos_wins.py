"""Merge github_repos q1/q2/q4 new results into the 51-task leaderboard summaries.

We re-ran github_repos-q1, -q2, -q4 with patched RULE-5/RULE-6 specs (q4
recovered: 0/5 -> 5/5; q1/q2 still failing). The original 51-task runs at
results/dab_leaderboard_run{0..4}/summary.json hold the OLD wrong answers
for those 3 tasks. The fresh answers live at
results/dab_github_repos_run{0..4}/summary.json.

This script writes results/dab_leaderboard_merged_run{0..4}/summary.json that
copies everything from the original leaderboard run but replaces the 3
github_repos entries (q1, q2, q4) with the fresh ones. q3 stays from the
original since it was already passing and was not re-run.
"""
import json
import os
from pathlib import Path

OUT = Path("results")
PATCH_TASKS = {"github_repos-q1", "github_repos-q2", "github_repos-q4"}

for r in range(5):
    src = OUT / (f"dab_leaderboard_run{r}" if r > 0 else "dab_all51_baseline_v1") / "summary.json"
    fresh = OUT / f"dab_github_repos_run{r}" / "summary.json"
    dst_dir = OUT / f"dab_leaderboard_merged_run{r}"
    dst_dir.mkdir(parents=True, exist_ok=True)

    base = json.loads(src.read_text())
    new = {row["task_id"]: row for row in json.loads(fresh.read_text())}

    merged = []
    for row in base:
        if row["task_id"] in PATCH_TASKS and row["task_id"] in new:
            merged.append(new[row["task_id"]])
        else:
            merged.append(row)

    (dst_dir / "summary.json").write_text(json.dumps(merged, indent=2))
    print(f"run {r}: wrote {len(merged)} rows (replaced "
          f"{sum(1 for r2 in merged if r2['task_id'] in PATCH_TASKS)} github_repos)")
