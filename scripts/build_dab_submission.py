#!/usr/bin/env python3
"""Build a DataAgentBench leaderboard submission JSON from 5 SCRIBE executor runs.

Reads:
  - data/splits/dab_all51.jsonl  -> maps task_id (e.g. "deps_dev_v1-q1") to
                                    {dataset, query} as the leaderboard expects.
  - results/dab_leaderboard_run{0..4}/summary.json
       (run0 falls back to results/dab_all51_baseline_v1/summary.json if the
        explicit run0 directory does not exist; the baseline IS run 0.)

Optionally with --include-patents, also reads:
  - results/dab_leaderboard_patents_run{0..4}/summary.json

Writes:
  - submissions/scribe_actioneer_opus47.json

The leaderboard format (per https://github.com/ucbepic/DataAgentBench):
    [{"dataset": "<name>", "query": "<id>", "run": <int>, "answer": "<str>"}, ...]

Dataset names use the canonical (mostly lowercase) strings from the README dataset
table: agnews, bookreview, crmarenapro, deps_dev_v1, github_repos, googlelocal,
music_brainz_20k, pancancer_atlas, patents, stockindex, stockmarket, yelp.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
SPLIT_PATH = REPO_ROOT / "data" / "splits" / "dab_all51.jsonl"
RESULTS_DIR = REPO_ROOT / "results"
OUT_PATH = REPO_ROOT / "submissions" / "scribe_actioneer_opus47.json"

# Canonical leaderboard dataset names (lowercased) as listed in the upstream README
# "Dataset" column. Domains in our split that differ in case are mapped here.
CANONICAL_DATASETS = {
    "agnews",
    "bookreview",
    "crmarenapro",
    "deps_dev_v1",
    "github_repos",
    "googlelocal",
    "music_brainz_20k",
    "pancancer_atlas",
    "patents",
    "stockindex",
    "stockmarket",
    "yelp",
}

# Mapping from the {dataset} string inside each task's `answer` field to the
# canonical leaderboard dataset string. Most are just lowercase.
DATASET_NORMALIZATION = {
    "agnews": "agnews",
    "bookreview": "bookreview",
    "crmarenapro": "crmarenapro",
    "DEPS_DEV_V1": "deps_dev_v1",
    "GITHUB_REPOS": "github_repos",
    "googlelocal": "googlelocal",
    "music_brainz_20k": "music_brainz_20k",
    "PANCANCER_ATLAS": "pancancer_atlas",
    "PATENTS": "patents",
    "stockindex": "stockindex",
    "stockmarket": "stockmarket",
    "yelp": "yelp",
}


def normalize_dataset(raw: str) -> str:
    if raw in DATASET_NORMALIZATION:
        return DATASET_NORMALIZATION[raw]
    low = raw.lower()
    if low in CANONICAL_DATASETS:
        return low
    raise SystemExit(f"Unknown dataset name in split: {raw!r}")


def load_task_map(split_path: Path) -> dict[str, tuple[str, str]]:
    """task_id -> (canonical_dataset, query_id_as_string)."""
    task_map: dict[str, tuple[str, str]] = {}
    with split_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            task = json.loads(line)
            ans = json.loads(task["answer"])
            dataset = normalize_dataset(ans["dataset"])
            query = str(ans["query"])
            task_map[task["task_id"]] = (dataset, query)
    return task_map


def resolve_run_dir(run_idx: int, patents: bool) -> Path | None:
    """Return the directory for a given run index, or None if it doesn't exist."""
    if patents:
        d = RESULTS_DIR / f"dab_leaderboard_patents_run{run_idx}"
        return d if d.is_dir() else None
    # Main 51-task runs — prefer the merged variant (github_repos q1/q2/q4
    # updated with the patched-spec results) when present.
    merged = RESULTS_DIR / f"dab_leaderboard_merged_run{run_idx}"
    if merged.is_dir():
        return merged
    primary = RESULTS_DIR / f"dab_leaderboard_run{run_idx}"
    if primary.is_dir():
        return primary
    # Run 0 fallback: the baseline directory IS run 0.
    if run_idx == 0:
        fallback = RESULTS_DIR / "dab_all51_baseline_v1"
        if fallback.is_dir():
            return fallback
    return None


def load_run_answers(run_dir: Path) -> dict[str, str]:
    """task_id -> final_answer (string)."""
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        raise SystemExit(f"Missing summary.json in {run_dir}")
    with summary_path.open() as f:
        rows = json.load(f)
    out: dict[str, str] = {}
    for row in rows:
        ans = row.get("final_answer")
        if ans is None:
            ans = ""
        out[row["task_id"]] = str(ans)
    return out


def build_entries(
    task_map: dict[str, tuple[str, str]],
    run_idxs: Iterable[int],
    patents: bool,
) -> tuple[list[dict], list[str]]:
    entries: list[dict] = []
    warnings: list[str] = []
    expected_task_ids = set(task_map.keys())

    for run_idx in run_idxs:
        run_dir = resolve_run_dir(run_idx, patents=patents)
        if run_dir is None:
            warnings.append(
                f"Run {run_idx}{' (patents)' if patents else ''}: directory missing — skipped."
            )
            continue
        answers = load_run_answers(run_dir)
        missing = expected_task_ids - set(answers.keys())
        extra = set(answers.keys()) - expected_task_ids
        if missing:
            warnings.append(
                f"Run {run_idx} ({run_dir.name}): missing {len(missing)} task(s): "
                f"{sorted(missing)[:5]}{'...' if len(missing) > 5 else ''}"
            )
        if extra:
            warnings.append(
                f"Run {run_idx} ({run_dir.name}): {len(extra)} extra task(s) ignored: "
                f"{sorted(extra)[:5]}{'...' if len(extra) > 5 else ''}"
            )
        for task_id, (dataset, query) in task_map.items():
            if task_id not in answers:
                continue
            entries.append(
                {
                    "dataset": dataset,
                    "query": query,
                    "run": run_idx,
                    "answer": answers[task_id],
                }
            )
    return entries, warnings


def validate_matrix(
    entries: list[dict],
    task_map: dict[str, tuple[str, str]],
    run_idxs: list[int],
    label: str,
) -> list[str]:
    """Warn if any (dataset, query, run) triple from the expected matrix is missing."""
    present: set[tuple[str, str, int]] = {
        (e["dataset"], e["query"], e["run"]) for e in entries
    }
    expected: set[tuple[str, str, int]] = set()
    for dataset, query in task_map.values():
        for r in run_idxs:
            expected.add((dataset, query, r))
    missing = expected - present
    msgs: list[str] = []
    if missing:
        msgs.append(
            f"[{label}] Missing {len(missing)} (dataset, query, run) cells out of "
            f"{len(expected)} expected."
        )
        # show up to first 10
        for cell in sorted(missing)[:10]:
            msgs.append(f"  - missing: dataset={cell[0]} query={cell[1]} run={cell[2]}")
    else:
        msgs.append(f"[{label}] OK: all {len(expected)} expected cells present.")
    return msgs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--include-patents",
        action="store_true",
        help="Also include results from results/dab_leaderboard_patents_run{0..4}.",
    )
    ap.add_argument(
        "--runs",
        type=str,
        default="0,1,2,3,4",
        help="Comma-separated run indices for the main 51-task split (default 0,1,2,3,4).",
    )
    ap.add_argument(
        "--patents-runs",
        type=str,
        default="0,1,2,3,4",
        help="Comma-separated run indices for PATENTS (default 0,1,2,3,4).",
    )
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    args = ap.parse_args()

    run_idxs = [int(x) for x in args.runs.split(",") if x.strip()]
    patents_run_idxs = [int(x) for x in args.patents_runs.split(",") if x.strip()]

    task_map = load_task_map(SPLIT_PATH)
    print(f"Loaded {len(task_map)} tasks from split.", file=sys.stderr)

    all_entries: list[dict] = []
    all_warnings: list[str] = []

    main_entries, warns = build_entries(task_map, run_idxs, patents=False)
    all_entries.extend(main_entries)
    all_warnings.extend(warns)
    all_warnings.extend(
        validate_matrix(main_entries, task_map, run_idxs, label="main 51-task")
    )

    if args.include_patents:
        # PATENTS-only sub-split: filter task_map to just patents tasks.
        patents_task_map = {
            tid: dq for tid, dq in task_map.items() if dq[0] == "patents"
        }
        if not patents_task_map:
            # The 51-task split has no patents tasks; the patents runs use their
            # own task_ids. We can still pull whatever task_ids appear in those
            # summary.jsons by treating the run dir as the source of truth.
            # Fall back to a synthetic task_map built from the first available
            # patents run dir.
            for r in patents_run_idxs:
                d = resolve_run_dir(r, patents=True)
                if d and (d / "summary.json").is_file():
                    answers = load_run_answers(d)
                    for tid in answers:
                        # Expect format "patents-qN"; infer query from suffix.
                        if "-q" in tid:
                            qid = tid.split("-q", 1)[1]
                            patents_task_map[tid] = ("patents", qid)
                    break
        patents_entries, pwarns = build_entries(
            patents_task_map, patents_run_idxs, patents=True
        )
        all_entries.extend(patents_entries)
        all_warnings.extend(pwarns)
        all_warnings.extend(
            validate_matrix(
                patents_entries, patents_task_map, patents_run_idxs, label="patents"
            )
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w") as f:
        json.dump(all_entries, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(all_entries)} entries to {args.out}", file=sys.stderr)
    for w in all_warnings:
        print(w, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
