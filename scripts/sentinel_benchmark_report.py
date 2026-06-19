#!/usr/bin/env python3
"""Build a benchmark summary table across Sentinel run arms.

Usage examples:

  # Single arm
  python3 scripts/sentinel_benchmark_report.py \
    --arm "Opus 4.7 first run:results/sentinel_regression"

  # Compare two arms
  python3 scripts/sentinel_benchmark_report.py \
    --arm "Opus 4.6:results/sentinel_regression_opus46" \
    --arm "Opus 4.7 first run:results/sentinel_regression"

  # 3-pass arm (comma-separated run dirs)
  python3 scripts/sentinel_benchmark_report.py \
    --arm "Opus 4.7 3-pass:results/sentinel_reg_run1,results/sentinel_reg_run2,results/sentinel_reg_run3"
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PASS_STATUSES = {"pass"}
SCORED_STATUSES = {"pass", "fail"}


@dataclass
class ArmStats:
    label: str
    run_dirs: list[Path]
    k_text: str
    total_questions: int
    total_attempts: int
    scored_questions: int
    passed_questions: int
    failed_questions: int
    skipped_questions: int
    attempt_passes: int
    scored_attempts: int
    total_cost_usd: float
    total_time_sec: float

    @property
    def pass_at_k_scored(self) -> float:
        return (self.passed_questions / self.scored_questions) if self.scored_questions else 0.0

    @property
    def strict_pass_over_questions(self) -> float:
        return (self.passed_questions / self.total_questions) if self.total_questions else 0.0

    @property
    def raw_pass_over_scored_attempts(self) -> float:
        return (self.attempt_passes / self.scored_attempts) if self.scored_attempts else 0.0

    @property
    def strict_raw_pass_over_all_attempts(self) -> float:
        return (self.attempt_passes / self.total_attempts) if self.total_attempts else 0.0

    @property
    def avg_cost_scored_questions(self) -> float:
        return self.total_cost_usd / self.scored_questions if self.scored_questions else 0.0

    @property
    def avg_cost_all_attempts(self) -> float:
        return self.total_cost_usd / self.total_attempts if self.total_attempts else 0.0

    @property
    def avg_time_scored_questions(self) -> float:
        return self.total_time_sec / self.scored_questions if self.scored_questions else 0.0

    @property
    def avg_time_all_attempts(self) -> float:
        return self.total_time_sec / self.total_attempts if self.total_attempts else 0.0


def parse_arm(raw: str) -> tuple[str, list[Path]]:
    if ":" not in raw:
        raise SystemExit(f"--arm must be label:path[,path2,...], got: {raw}")
    label, dirs_raw = raw.split(":", 1)
    run_dirs = [Path(p.strip()).expanduser().resolve() for p in dirs_raw.split(",") if p.strip()]
    if not run_dirs:
        raise SystemExit(f"--arm has no paths: {raw}")
    return label.strip(), run_dirs


def load_json(path: Path):
    return json.loads(path.read_text())


def pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def delta_pct(base: float, val: float) -> str:
    if base == 0:
        return "—"
    d = (val - base) / base
    sign = "+" if d >= 0 else ""
    return f"{sign}{d * 100:.1f}%"


def fmt_num(v: float, digits: int = 4) -> str:
    return f"{v:.{digits}f}"


def fmt_pair(a: int, b: int) -> str:
    return f"{a}/{b}"


def resolve_eval_rows(run_dir: Path) -> list[dict]:
    for name in ("eval_results.json", "results.json"):
        path = run_dir / name
        if path.exists():
            return load_json(path)
    raise SystemExit(
        f"Missing eval_results.json or results.json in {run_dir} (run grade_sentinel first)"
    )


def load_cost_and_time(
    run_dir: Path,
    task_ids: set[str],
    cost_mode: str,
) -> tuple[float, float]:
    if cost_mode == "pipeline":
        usage_path = run_dir / "usage.json"
        if usage_path.exists():
            per_task = {r["task_id"]: r for r in load_json(usage_path).get("per_task", [])}
            total_cost = sum(float(per_task[tid].get("cost_usd") or 0.0) for tid in task_ids if tid in per_task)
            total_time = sum(float(per_task[tid].get("wall_seconds") or 0.0) for tid in task_ids if tid in per_task)
            if total_cost or total_time:
                return total_cost, total_time

    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        return 0.0, 0.0
    summary_rows = load_json(summary_path)
    by_id = {str(r.get("task_id", "")): r for r in summary_rows}
    total_cost = sum(float(by_id[tid].get("cost_usd") or 0.0) for tid in task_ids if tid in by_id)
    total_time = sum(float(by_id[tid].get("wall_seconds") or 0.0) for tid in task_ids if tid in by_id)
    return total_cost, total_time


def read_arm(label: str, run_dirs: list[Path], *, cost_mode: str = "exec") -> ArmStats:
    all_question_ids: set[str] = set()
    attempts_by_q: dict[str, list[str]] = {}
    total_attempts = 0
    attempt_passes = 0
    scored_attempts = 0
    total_cost = 0.0
    total_time = 0.0
    attempts_per_question: dict[str, int] = {}

    for run_dir in run_dirs:
        if not run_dir.is_dir():
            raise SystemExit(f"Run dir not found: {run_dir}")

        tasks_path = run_dir / "tasks.jsonl"

        if not tasks_path.exists():
            raise SystemExit(f"Missing tasks.jsonl in {run_dir}")

        # Question universe from tasks (preferred source of denominator).
        task_ids = {
            json.loads(line)["task_id"]
            for line in tasks_path.read_text().splitlines()
            if line.strip()
        }
        all_question_ids.update(task_ids)

        rows = resolve_eval_rows(run_dir)
        for r in rows:
            tid = str(r.get("task_id", ""))
            status = str(r.get("status", ""))
            if not tid:
                continue
            attempts_by_q.setdefault(tid, []).append(status)
            attempts_per_question[tid] = attempts_per_question.get(tid, 0) + 1
            total_attempts += 1
            if status in PASS_STATUSES:
                attempt_passes += 1
            if status in SCORED_STATUSES:
                scored_attempts += 1

        cost, wall = load_cost_and_time(run_dir, task_ids, cost_mode)
        total_cost += cost
        total_time += wall

    scored_questions = 0
    passed_questions = 0
    for qid in sorted(all_question_ids):
        statuses = attempts_by_q.get(qid, [])
        any_scored = any(s in SCORED_STATUSES for s in statuses)
        any_pass = any(s in PASS_STATUSES for s in statuses)
        if any_scored:
            scored_questions += 1
        if any_pass:
            passed_questions += 1

    total_questions = len(all_question_ids)
    failed_questions = max(0, scored_questions - passed_questions)
    skipped_questions = max(0, total_questions - scored_questions)

    if attempts_per_question:
        vals = set(attempts_per_question.values())
        k_text = str(next(iter(vals))) if len(vals) == 1 else "mixed"
    else:
        k_text = "0"

    return ArmStats(
        label=label,
        run_dirs=run_dirs,
        k_text=k_text,
        total_questions=total_questions,
        total_attempts=total_attempts,
        scored_questions=scored_questions,
        passed_questions=passed_questions,
        failed_questions=failed_questions,
        skipped_questions=skipped_questions,
        attempt_passes=attempt_passes,
        scored_attempts=scored_attempts,
        total_cost_usd=total_cost,
        total_time_sec=total_time,
    )


def metric_rows(arms: list[ArmStats]) -> list[tuple[str, list[str]]]:
    base = arms[0]
    rows: list[tuple[str, list[str]]] = []

    def one(metric: str, values: Iterable[str]) -> None:
        rows.append((metric, list(values)))

    one("k", (a.k_text for a in arms))
    one("total questions / question-runs", (fmt_pair(a.total_questions, a.total_attempts) for a in arms))
    one("scored questions", (str(a.scored_questions) for a in arms))
    one("passed questions", (str(a.passed_questions) for a in arms))
    one("failed questions", (str(a.failed_questions) for a in arms))
    one("skipped questions", (str(a.skipped_questions) for a in arms))
    one(
        "accuracy / pass@k over scored",
        (f"{a.passed_questions}/{a.scored_questions} = {pct(a.pass_at_k_scored)}" for a in arms),
    )
    one(
        "strict accuracy over all questions",
        (f"{a.passed_questions}/{a.total_questions} = {pct(a.strict_pass_over_questions)}" for a in arms),
    )
    one("attempt passes", (str(a.attempt_passes) for a in arms))
    one("scored attempts", (str(a.scored_attempts) for a in arms))
    one("total attempted question-runs incl skips", (str(a.total_attempts) for a in arms))
    one(
        "raw pass rate over scored attempts",
        (f"{a.attempt_passes}/{a.scored_attempts} = {pct(a.raw_pass_over_scored_attempts)}" for a in arms),
    )
    one(
        "strict raw pass rate over all attempts",
        (f"{a.attempt_passes}/{a.total_attempts} = {pct(a.strict_raw_pass_over_all_attempts)}" for a in arms),
    )
    one("total cost USD", (fmt_num(a.total_cost_usd, 4) for a in arms))
    one("avg cost USD over scored questions", (fmt_num(a.avg_cost_scored_questions, 4) for a in arms))
    one("avg cost USD over all question-runs", (fmt_num(a.avg_cost_all_attempts, 4) for a in arms))
    one("total time sec", (fmt_num(a.total_time_sec, 2) for a in arms))
    one("avg time sec over scored questions", (fmt_num(a.avg_time_scored_questions, 2) for a in arms))
    one("avg time sec over all question-runs", (fmt_num(a.avg_time_all_attempts, 2) for a in arms))

    # Add delta rows in output rendering; this function returns main metric values.
    return rows


def render_table(arms: list[ArmStats]) -> str:
    rows = metric_rows(arms)
    headers = ["metric"] + [a.label for a in arms]
    # Add delta columns against baseline for each non-baseline arm.
    for i in range(1, len(arms)):
        headers.append(f"Δ {arms[i].label} vs {arms[0].label}")

    lines = []
    matrix = []
    for metric, vals in rows:
        row = [metric] + vals
        # Delta calculations for numeric rates/cost/time where meaningful.
        for i in range(1, len(arms)):
            a0 = arms[0]
            ai = arms[i]
            delta = "—"
            if metric == "accuracy / pass@k over scored":
                delta = delta_pct(a0.pass_at_k_scored, ai.pass_at_k_scored)
            elif metric == "strict accuracy over all questions":
                delta = delta_pct(a0.strict_pass_over_questions, ai.strict_pass_over_questions)
            elif metric == "raw pass rate over scored attempts":
                delta = delta_pct(a0.raw_pass_over_scored_attempts, ai.raw_pass_over_scored_attempts)
            elif metric == "strict raw pass rate over all attempts":
                delta = delta_pct(a0.strict_raw_pass_over_all_attempts, ai.strict_raw_pass_over_all_attempts)
            elif metric == "total cost USD":
                delta = delta_pct(a0.total_cost_usd, ai.total_cost_usd)
            elif metric == "avg cost USD over scored questions":
                delta = delta_pct(a0.avg_cost_scored_questions, ai.avg_cost_scored_questions)
            elif metric == "avg cost USD over all question-runs":
                delta = delta_pct(a0.avg_cost_all_attempts, ai.avg_cost_all_attempts)
            elif metric == "total time sec":
                delta = delta_pct(a0.total_time_sec, ai.total_time_sec)
            elif metric == "avg time sec over scored questions":
                delta = delta_pct(a0.avg_time_scored_questions, ai.avg_time_scored_questions)
            elif metric == "avg time sec over all question-runs":
                delta = delta_pct(a0.avg_time_all_attempts, ai.avg_time_all_attempts)
            row.append(delta)
        matrix.append(row)

    col_widths = [max(len(str(h)), *(len(str(r[c])) for r in matrix)) for c, h in enumerate(headers)]
    header_line = " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers))
    sep = "-+-".join("-" * col_widths[i] for i in range(len(headers)))
    lines.append(header_line)
    lines.append(sep)
    for r in matrix:
        lines.append(" | ".join(str(r[i]).ljust(col_widths[i]) for i in range(len(headers))))
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Sentinel benchmark summary table")
    ap.add_argument(
        "--arm",
        action="append",
        required=True,
        help="Format: 'Label:path' or 'Label:path1,path2,path3'",
    )
    ap.add_argument(
        "--out-json",
        default=None,
        help="Optional path to write computed arm stats JSON",
    )
    ap.add_argument(
        "--cost-mode",
        choices=("exec", "pipeline"),
        default="exec",
        help="exec = executor+planner from summary.json; pipeline = spec+exec+planner from usage.json",
    )
    args = ap.parse_args()

    arms = []
    for raw in args.arm:
        label, run_dirs = parse_arm(raw)
        arms.append(read_arm(label, run_dirs, cost_mode=args.cost_mode))

    print()
    print(render_table(arms))
    print()

    if args.out_json:
        out = Path(args.out_json).expanduser().resolve()
        payload = {
            "arms": [
                {
                    "label": a.label,
                    "run_dirs": [str(p) for p in a.run_dirs],
                    "k": a.k_text,
                    "total_questions": a.total_questions,
                    "total_attempts": a.total_attempts,
                    "scored_questions": a.scored_questions,
                    "passed_questions": a.passed_questions,
                    "failed_questions": a.failed_questions,
                    "skipped_questions": a.skipped_questions,
                    "attempt_passes": a.attempt_passes,
                    "scored_attempts": a.scored_attempts,
                    "pass_at_k_scored": a.pass_at_k_scored,
                    "strict_pass_over_questions": a.strict_pass_over_questions,
                    "raw_pass_over_scored_attempts": a.raw_pass_over_scored_attempts,
                    "strict_raw_pass_over_all_attempts": a.strict_raw_pass_over_all_attempts,
                    "total_cost_usd": a.total_cost_usd,
                    "avg_cost_scored_questions": a.avg_cost_scored_questions,
                    "avg_cost_all_attempts": a.avg_cost_all_attempts,
                    "total_time_sec": a.total_time_sec,
                    "avg_time_scored_questions": a.avg_time_scored_questions,
                    "avg_time_all_attempts": a.avg_time_all_attempts,
                }
                for a in arms
            ]
        }
        out.write_text(json.dumps(payload, indent=2))
        print(f"Wrote: {out}")


if __name__ == "__main__":
    main()

