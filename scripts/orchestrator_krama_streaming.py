"""orchestrator_krama_streaming.py — streaming spec→exec pipeline for Krama104.

Design:
  - One spec_extractor worker (sequential) — runs extract_specs_krama.py per task
  - Two executor workers (parallel) — each runs `npx tsx src/run.ts` on one task,
    using a different Fireworks key (FW2 → shard_a config, FW1 → shard_b config)
  - As soon as a spec is written to disk, the next available executor worker picks it up
  - Mid-run accuracy check every 20 tasks complete

This avoids the v2/v3 anti-pattern where ALL specs had to extract before ANY
executor could run. Now spec extraction and execution overlap.

USAGE:
    python3 scripts/orchestrator_krama_streaming.py \\
        --tasks data/splits/krama_all104.jsonl \\
        --out results/krama_all104 \\
        --gold-from-tasks   # uses the `answer` field in the tasks JSONL as gold
"""

from __future__ import annotations
import argparse
import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]

# Default models / configs — match Krama configs on disk.
EXTRACTOR = "openrouter:deepseek/deepseek-chat-v3.1"
SHARD_CONFIGS = [
    ROOT / "configs" / "kramabench_scribe.yaml",       # fireworks2 / FW2 key
    ROOT / "configs" / "kramabench_scribe_fw1.yaml",   # fireworks  / FW1 key
]


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def normalize_answer(s: str) -> str:
    """Strip whitespace + lowercase for tolerant string compare; keep as-is for numeric."""
    return (s or "").strip()


def compare_to_gold(predicted: str, gold: str, answer_type: str) -> bool:
    """Krama-style tolerant compare. Mirrors grade_krama.py's logic at a coarse level."""
    if not predicted or not gold:
        return False
    p, g = normalize_answer(predicted), normalize_answer(gold)
    if answer_type and "numeric" in answer_type:
        try:
            return abs(float(p) - float(g)) < 1e-3
        except Exception:
            return False
    return p.lower() == g.lower()


def spec_worker(
    tasks: list[dict],
    specs_dir: Path,
    logs_dir: Path,
    spec_done_queue: "queue.Queue[dict | None]",
) -> None:
    """Extract specs ONE TASK AT A TIME. As each one lands, push the task row to the queue
    so an executor worker can pick it up immediately."""
    for t in tasks:
        tid = str(t["task_id"])
        out_path = specs_dir / f"{tid}.json"
        if out_path.exists():
            # Already extracted (resume mode).
            log(f"[SPEC] {tid} — already on disk, skipping extraction")
            spec_done_queue.put(t)
            continue
        # Write the single-task JSONL the extractor expects.
        single = logs_dir / f"single_{tid}.jsonl"
        single.write_text(json.dumps(t) + "\n")
        log_path = logs_dir / f"spec_{tid}.log"
        cmd = [
            "python3", str(ROOT / "scripts" / "extract_specs_krama.py"),
            "--tasks", str(single),
            "--extractor", EXTRACTOR,
            "--out", str(specs_dir),
        ]
        log(f"[SPEC] {tid} — extracting (via {EXTRACTOR})")
        with log_path.open("w") as lf:
            r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT)
        if r.returncode != 0 or not out_path.exists():
            log(f"[SPEC] {tid} — FAILED (rc={r.returncode}); see {log_path.name}")
        else:
            log(f"[SPEC] {tid} — spec on disk")
        spec_done_queue.put(t)
    # Signal end of stream.
    spec_done_queue.put(None)


def executor_worker(
    worker_id: int,
    shard_config: Path,
    in_queue: "queue.Queue[dict | None]",
    pending: list[dict],
    pending_lock: threading.Lock,
    specs_dir: Path,
    out_dir: Path,
    logs_dir: Path,
    results: list[dict],
    results_lock: threading.Lock,
) -> None:
    """Pull tasks from the shared pending list and run them through `npx tsx src/run.ts`
    using the assigned shard config (FW2 or FW1).

    The spec worker puts items into in_queue, which we drain into the shared `pending`
    list. Both executor workers compete for items in `pending`."""
    while True:
        # First drain any new items from in_queue (non-blocking).
        try:
            while True:
                t = in_queue.get_nowait()
                if t is None:
                    # Sentinel — re-broadcast so the OTHER worker also sees it.
                    in_queue.put(None)
                    break
                with pending_lock:
                    pending.append(t)
        except queue.Empty:
            pass
        # Try to claim a task.
        claimed = None
        with pending_lock:
            if pending:
                claimed = pending.pop(0)
        if claimed is None:
            # No task ready — could be done, or just waiting for next spec.
            # Block on in_queue to wait for next signal.
            try:
                t = in_queue.get(timeout=5)
            except queue.Empty:
                continue
            if t is None:
                # End of stream; check if pending is also empty, then exit.
                in_queue.put(None)  # re-broadcast for sibling
                with pending_lock:
                    if not pending:
                        log(f"[EXEC{worker_id}] no more work, exiting")
                        return
                continue
            with pending_lock:
                pending.append(t)
            continue
        tid = str(claimed["task_id"])
        # Confirm spec is actually on disk.
        spec_path = specs_dir / f"{tid}.json"
        if not spec_path.exists():
            log(f"[EXEC{worker_id}] {tid} — spec missing, marking as ERROR")
            with results_lock:
                results.append({"task_id": tid, "final_answer": "", "error": "spec missing"})
            continue
        # Write a single-task JSONL for run.ts.
        single = logs_dir / f"exec_{tid}.jsonl"
        single.write_text(json.dumps(claimed) + "\n")
        task_out_dir = out_dir / f"shard_w{worker_id}"
        task_out_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"run_{tid}_w{worker_id}.log"
        cmd = [
            "npx", "tsx", str(ROOT / "src" / "run.ts"),
            "-d", str(single),
            "-c", str(shard_config),
            "-o", str(task_out_dir),
            "--specs", str(specs_dir),
            "-n", f"krama_all104 worker={worker_id} {claimed.get('domain','')}/{tid}",
        ]
        log(f"[EXEC{worker_id}] {tid} — running ({claimed.get('domain','?')})")
        with log_path.open("w") as lf:
            r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=str(ROOT))
        # Read this worker's summary.json and pluck the row for this task.
        summary_path = task_out_dir / "summary.json"
        ans = ""
        err = None
        if summary_path.exists():
            try:
                rows = json.loads(summary_path.read_text())
                for row in rows:
                    if str(row.get("task_id")) == tid:
                        ans = row.get("final_answer") or ""
                        err = row.get("error")
                        break
            except Exception as e:
                err = f"summary parse: {e}"
        gold = claimed.get("answer", "")
        atype = claimed.get("answer_type", "")
        passed = compare_to_gold(ans, gold, atype)
        with results_lock:
            results.append({
                "task_id": tid,
                "domain": claimed.get("domain"),
                "level": claimed.get("level"),
                "final_answer": ans,
                "gold": gold,
                "pass": passed,
                "error": err,
                "worker": worker_id,
            })
        log(f"[EXEC{worker_id}] {tid} — {'PASS' if passed else 'FAIL'} (ans={ans[:40] if ans else '(empty)'})")


def progress_snapshot(results: list[dict], every_n: int) -> None:
    """Print running accuracy every time results crosses a multiple of every_n."""
    n = len(results)
    if n == 0 or n % every_n != 0:
        return
    passed = sum(1 for r in results if r.get("pass"))
    by_dom: dict[str, list[int]] = {}
    for r in results:
        d = r.get("domain") or "?"
        by_dom.setdefault(d, [0, 0])
        by_dom[d][1] += 1
        if r.get("pass"):
            by_dom[d][0] += 1
    log(f"━━━ PROGRESS @ {n} tasks: {passed}/{n} = {100*passed/n:.1f}% ━━━")
    for d, (p, t) in sorted(by_dom.items()):
        log(f"     {d}: {p}/{t} = {100*p/t:.1f}%")


def main():
    # `global` declarations MUST precede any read of the module-level names that
    # will be assigned later in this function; Python's compiler rejects reads
    # before the global keyword in the same scope.
    global EXTRACTOR, SHARD_CONFIGS

    p = argparse.ArgumentParser()
    p.add_argument("--tasks", required=True)
    p.add_argument("--out", required=True, help="Output directory for results.")
    p.add_argument("--progress-every", type=int, default=20)
    p.add_argument("--workers", type=int, default=2,
                   help="Number of executor workers (= number of shard configs to use).")
    p.add_argument("--extractor", default=EXTRACTOR,
                   help="Spec-extractor model spec (overrides default). Format: <provider>:<model>.")
    p.add_argument("--configs", nargs="+", default=None,
                   help="Override SHARD_CONFIGS (list of YAML config paths, one per worker).")
    args = p.parse_args()

    EXTRACTOR = args.extractor
    if args.configs:
        SHARD_CONFIGS = [Path(c).resolve() for c in args.configs]

    out_dir = Path(args.out)
    specs_dir = out_dir / "specs"
    logs_dir = out_dir / "logs"
    for d in (out_dir, specs_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    tasks = [json.loads(l) for l in Path(args.tasks).read_text().splitlines() if l.strip()]
    log(f"Loaded {len(tasks)} tasks from {args.tasks}")
    log(f"Specs:    {specs_dir}")
    log(f"Logs:     {logs_dir}")
    log(f"Workers:  {args.workers}")
    log(f"Configs:  {[c.name for c in SHARD_CONFIGS[:args.workers]]}")
    log(f"Extractor: {EXTRACTOR}")

    # Shared state.
    spec_done_queue: "queue.Queue[dict | None]" = queue.Queue()
    pending: list[dict] = []
    pending_lock = threading.Lock()
    results: list[dict] = []
    results_lock = threading.Lock()

    # Launch spec worker.
    sp = threading.Thread(target=spec_worker, args=(tasks, specs_dir, logs_dir, spec_done_queue), daemon=True)
    sp.start()

    # Launch N executor workers.
    execs = []
    for i in range(args.workers):
        ex = threading.Thread(
            target=executor_worker,
            args=(i, SHARD_CONFIGS[i], spec_done_queue, pending, pending_lock,
                  specs_dir, out_dir, logs_dir, results, results_lock),
            daemon=True,
        )
        ex.start()
        execs.append(ex)

    # Watcher: poll results length, print snapshots, persist running stats.
    last_n_reported = 0
    try:
        while any(e.is_alive() for e in execs) or sp.is_alive():
            time.sleep(15)
            with results_lock:
                n = len(results)
                snap = list(results)
            if n >= last_n_reported + args.progress_every:
                progress_snapshot(snap, args.progress_every)
                last_n_reported = (n // args.progress_every) * args.progress_every
                # Also persist running CSV-ish.
                (out_dir / "running_results.json").write_text(json.dumps(snap, indent=2))
    except KeyboardInterrupt:
        log("interrupted; saving what we have")

    # Final.
    sp.join(timeout=30)
    for e in execs:
        e.join(timeout=30)
    (out_dir / "final_results.json").write_text(json.dumps(results, indent=2))
    n = len(results)
    passed = sum(1 for r in results if r.get("pass"))
    log(f"\n━━━ FINAL: {passed}/{n} = {100*passed/n:.1f}% ━━━")
    by_dom: dict[str, list[int]] = {}
    for r in results:
        d = r.get("domain") or "?"
        by_dom.setdefault(d, [0, 0])
        by_dom[d][1] += 1
        if r.get("pass"):
            by_dom[d][0] += 1
    for d, (pp, tt) in sorted(by_dom.items()):
        log(f"  {d}: {pp}/{tt} = {100*pp/tt:.1f}%")


if __name__ == "__main__":
    main()
