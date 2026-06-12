"""Surgically replace the 15 contaminated tasks' answers (75 cells) in the
existing 270-cell submission with the clean re-run answers, keeping the other
195 clean cells byte-for-byte. Writes a new submission JSON.

Re-run answers come from results/dab_clean_rerun/run{0..4}/summary.json.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path

# the 15 contaminated task_ids -> (dataset, query) as used in the submission
def split_tid(tid: str):
    ds, q = tid.rsplit("-q", 1)
    return ds, q

RERUN_TIDS = {
    "agnews-q1", "agnews-q2", "agnews-q3", "agnews-q4",
    "crmarenapro-q2", "crmarenapro-q6", "crmarenapro-q7",
    "crmarenapro-q10", "crmarenapro-q12", "crmarenapro-q13",
    "deps_dev_v1-q1", "pancancer_atlas-q1", "googlelocal-q2",
    "yelp-q1", "yelp-q5",
}


def load_run_answers(run_dir: Path) -> dict[str, str]:
    summ = run_dir / "summary.json"
    rows = json.loads(summ.read_text())
    return {r["task_id"]: (r.get("final_answer") or "").strip() for r in rows}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="inp", default="submissions/scribe_actioneer_opus47.json")
    p.add_argument("--rerun-base", default="results/dab_clean_rerun")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    cells = json.load(open(args.inp))
    base = Path(args.rerun_base)

    # (dataset, query, run) -> new answer
    new_ans = {}
    for run in range(5):
        ans = load_run_answers(base / f"run{run}")
        for tid in RERUN_TIDS:
            if tid not in ans:
                print(f"  WARN: {tid} missing from run{run}")
                continue
            ds, q = split_tid(tid)
            new_ans[(ds, q, str(run))] = ans[tid]

    # target dataset/query set
    target_dq = {split_tid(t) for t in RERUN_TIDS}

    swapped = 0
    for c in cells:
        key = (c["dataset"], str(c["query"]), str(c["run"]))
        if (c["dataset"], str(c["query"])) in target_dq:
            if key in new_ans:
                c["answer"] = new_ans[key]
                swapped += 1
            else:
                print(f"  WARN: no new answer for {key}")

    Path(args.out).write_text(json.dumps(cells, indent=2))
    print(f"swapped {swapped} cells (expected 75); wrote {args.out}")


if __name__ == "__main__":
    main()
