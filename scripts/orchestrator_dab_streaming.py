"""orchestrator_dab_streaming.py — streaming spec->exec pipeline for DataAgentBench.

Design (matches the user's requested behavior):
  - ONE spec-extractor worker: runs extract_specs_dab.py per task, sequentially.
    As soon as a task's spec lands on disk, it pushes that task to a queue and
    immediately moves to extracting the NEXT task's spec.
  - N executor workers (default 4): each pulls a ready task and runs it through
    `npx tsx src/run.ts` with the Fable config + the just-written spec.
  - Spec extraction and execution OVERLAP — no wait-for-all-specs barrier.

All executors share the hardened sandbox (import + network egress block) via the
run.ts preamble. Self-audit afterward via scripts/dab_self_audit.py.

USAGE:
    python3 scripts/orchestrator_dab_streaming.py \\
        --tasks data/splits/dab_all54.jsonl \\
        --config configs/dab_scribe_fable.yaml \\
        --extractor anthropic:claude-fable-5 \\
        --specs results/dab_fable_specs \\
        --out results/dab_fable_scout \\
        --workers 4
"""
from __future__ import annotations
import argparse
import json
import queue
import subprocess
import threading
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def spec_worker(tasks, specs_dir, logs_dir, extractor, ready_q):
    """Extract specs one task at a time; push each finished task to ready_q."""
    for t in tasks:
        tid = str(t["task_id"])
        out_path = specs_dir / f"{tid}.json"
        if out_path.exists() and "_error" not in out_path.read_text():
            log(f"[SPEC] {tid} — already on disk, handing off")
            ready_q.put(t)
            continue
        single = logs_dir / f"spec_in_{tid}.jsonl"
        single.write_text(json.dumps(t) + "\n")
        log_path = logs_dir / f"spec_{tid}.log"
        cmd = ["python3", str(ROOT / "scripts" / "extract_specs_dab.py"),
               "--tasks", str(single), "--extractor", extractor, "--out", str(specs_dir)]
        log(f"[SPEC] {tid} — extracting ({extractor})")
        with log_path.open("w") as lf:
            r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT)
        if r.returncode != 0 or not out_path.exists():
            log(f"[SPEC] {tid} — FAILED (rc={r.returncode}); executor will see task-only")
        else:
            log(f"[SPEC] {tid} — spec landed; handing off to executor")
        ready_q.put(t)
    ready_q.put(None)  # end-of-stream sentinel


def executor_worker(wid, config, specs_dir, out_dir, logs_dir, ready_q, pending, plock, results, rlock):
    import os
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/opt/postgresql@17/bin:" + env.get("PATH", "")
    while True:
        # Drain ready_q into shared pending list.
        try:
            while True:
                t = ready_q.get_nowait()
                if t is None:
                    ready_q.put(None)  # re-broadcast for siblings
                    break
                with plock:
                    pending.append(t)
        except queue.Empty:
            pass
        claimed = None
        with plock:
            if pending:
                claimed = pending.pop(0)
        if claimed is None:
            try:
                t = ready_q.get(timeout=5)
            except queue.Empty:
                continue
            if t is None:
                ready_q.put(None)
                with plock:
                    if not pending:
                        log(f"[EXEC{wid}] no more work, exiting")
                        return
                continue
            with plock:
                pending.append(t)
            continue
        tid = str(claimed["task_id"])
        single = logs_dir / f"exec_in_{tid}.jsonl"
        single.write_text(json.dumps(claimed) + "\n")
        log_path = logs_dir / f"run_{tid}.log"
        # Per-task out dir avoids the summary.json race between concurrent workers.
        task_out = out_dir / "_runs" / tid
        task_out.mkdir(parents=True, exist_ok=True)
        cmd = ["npx", "tsx", str(ROOT / "src" / "run.ts"),
               "-c", str(config), "-d", str(single), "-o", str(task_out),
               "--specs", str(specs_dir), "-w", "1"]
        log(f"[EXEC{wid}] {tid} — running")
        with log_path.open("w") as lf:
            subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, env=env)
        summ = task_out / "summary.json"
        ans = None
        if summ.exists():
            try:
                rows = json.loads(summ.read_text())
                for row in rows:
                    if row["task_id"] == tid:
                        ans = row
            except Exception:
                pass
        with rlock:
            results.append({"task_id": tid, "summary": ans})
        log(f"[EXEC{wid}] {tid} — done ({len(results)} total)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--extractor", required=True)
    p.add_argument("--specs", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--workers", type=int, default=4)
    args = p.parse_args()

    tasks = [json.loads(l) for l in Path(args.tasks).read_text().splitlines() if l.strip()]
    specs_dir = Path(args.specs); specs_dir.mkdir(parents=True, exist_ok=True)
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = out_dir / "_pipeline_logs"; logs_dir.mkdir(parents=True, exist_ok=True)

    log(f"DAB streaming: {len(tasks)} tasks, extractor={args.extractor}, "
        f"config={Path(args.config).name}, {args.workers} executor workers")

    ready_q: "queue.Queue" = queue.Queue()
    pending: list = []
    plock = threading.Lock()
    results: list = []
    rlock = threading.Lock()

    sw = threading.Thread(target=spec_worker,
                          args=(tasks, specs_dir, logs_dir, args.extractor, ready_q), daemon=True)
    sw.start()
    workers = []
    for i in range(args.workers):
        w = threading.Thread(target=executor_worker,
                             args=(i, Path(args.config), specs_dir, out_dir, logs_dir,
                                   ready_q, pending, plock, results, rlock), daemon=True)
        w.start()
        workers.append(w)
    sw.join()
    for w in workers:
        w.join()

    log(f"DONE: {len(results)}/{len(tasks)} tasks executed. Per-task results in {out_dir}/<task>/")


if __name__ == "__main__":
    main()
