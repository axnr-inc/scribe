"""orchestrator_i2_multistance.py — I-2 multi-stance streaming orchestrator.

For each task:
  1. spec_worker runs extract_specs_krama_multi.py with 3 stances (literal / domain / strict)
  2. As each stance's spec lands on disk, push (tid, stance) to the executor queue
  3. Two executor workers (sharded across FW1/FW2) pull (tid, stance) and run independently
  4. After all 3 stances of a task have answers, adjudicate by:
     a) cluster answers (numeric tolerant or string normalized)
     b) majority wins (>=2 agree)
     c) tie-break via LLM-judge (gpt-5-mini) if all 3 disagree

Output:
  out_dir/specs/{literal,domain,strict}/<tid>.json    — the 3 specs
  out_dir/runs/<stance>/shard_w<id>/<tid>/...         — per-(task,stance) executor outputs
  out_dir/per_task_answers.json                       — {tid: {stance: answer}}
  out_dir/final_results.json                          — adjudicated winner per task

USAGE:
    python3 scripts/orchestrator_i2_multistance.py \\
        --tasks data/splits/krama_i2_failed.jsonl \\
        --out results/krama_i2 \\
        --stances literal,domain,strict
"""

from __future__ import annotations
import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(".env", override=True)

ROOT = Path(__file__).resolve().parents[1]

EXTRACTOR = "openrouter:deepseek/deepseek-chat-v3.1"
SHARD_CONFIGS = [
    ROOT / "configs" / "kramabench_scribe.yaml",       # fireworks2 / FW2 key
    ROOT / "configs" / "kramabench_scribe_fw1.yaml",   # fireworks  / FW1 key
]
DEFAULT_STANCES = ["literal", "domain", "strict"]


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


# -------- adjudication helpers --------
def _normalize_str(s: str) -> str:
    return (s or "").strip().lower()


def _answers_equal(a: str, b: str, answer_type: str) -> bool:
    if not a or not b:
        return False
    a, b = a.strip(), b.strip()
    if answer_type and "numeric" in answer_type:
        try:
            return abs(float(a) - float(b)) < 1e-3
        except Exception:
            return False
    return _normalize_str(a) == _normalize_str(b)


def adjudicate(answers_per_stance: dict, task: dict) -> tuple[str, str, str]:
    """Return (winner_answer, winner_stance, method)."""
    atype = task.get("answer_type", "")
    nonempty = [(s, a) for s, a in answers_per_stance.items() if a]
    if not nonempty:
        return "", "", "all_empty"
    if len(nonempty) == 1:
        s, a = nonempty[0]
        return a, s, "only_one_nonempty"
    # cluster
    clusters: list[list[tuple[str, str]]] = []
    for s, a in nonempty:
        placed = False
        for c in clusters:
            if _answers_equal(c[0][1], a, atype):
                c.append((s, a))
                placed = True
                break
        if not placed:
            clusters.append([(s, a)])
    clusters.sort(key=len, reverse=True)
    top = clusters[0]
    if len(top) >= 2:
        s, a = top[0]
        method = "unanimous" if len(top) == 3 else "majority"
        return a, s, method
    # all 3 disagree → LLM-judge tie-break
    return _llm_tiebreak(answers_per_stance, task)


def _llm_tiebreak(answers_per_stance: dict, task: dict) -> tuple[str, str, str]:
    """Ask gpt-5-mini to pick the most defensible of N candidates."""
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        candidates = "\n".join(
            f"- stance={s}: {a}" for s, a in answers_per_stance.items() if a
        )
        prompt = (
            f"Task question:\n{task.get('question','(no question)')}\n\n"
            f"Three SCRIBE pipelines produced different answers, each under a different "
            f"interpretation stance. Pick the most defensible answer.\n\n"
            f"Candidates:\n{candidates}\n\n"
            f"Reply with ONLY the chosen answer string. No reasoning, no extra text. "
            f"Just the answer."
        )
        resp = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=200,
        )
        text = (resp.choices[0].message.content or "").strip()
        # Match back to a stance if possible
        for s, a in answers_per_stance.items():
            if _normalize_str(a) == _normalize_str(text):
                return a, s, "tiebreak_llm"
        # Otherwise return the LLM's text directly with stance=judge
        return text, "judge", "tiebreak_llm_synthetic"
    except Exception as e:
        log(f"  llm_tiebreak failed: {e}; defaulting to 'domain' stance")
        if answers_per_stance.get("domain"):
            return answers_per_stance["domain"], "domain", "tiebreak_fallback_domain"
        # last resort: first nonempty
        for s, a in answers_per_stance.items():
            if a:
                return a, s, "tiebreak_fallback_first"
        return "", "", "all_empty"


# -------- pipeline --------
def spec_worker(
    tasks: list[dict],
    stances: list[str],
    specs_root: Path,
    logs_dir: Path,
    spec_done_queue: "queue.Queue",
) -> None:
    """Extract one (task, stance) at a time and push to executor queue immediately.

    Previous version called extract_specs_krama_multi.py once per task (3 stances
    inside one subprocess), which forced executors to idle for ~3 min waiting for
    all 3 specs of a task. This per-(task,stance) loop releases each spec to the
    executor as soon as it lands — finer streaming, ~30-60 min less wall time."""
    for t in tasks:
        tid = str(t["task_id"])
        single = logs_dir / f"single_{tid}.jsonl"
        single.write_text(json.dumps(t) + "\n")
        tmp_dir = specs_root / "tmp" / tid
        tmp_dir.mkdir(parents=True, exist_ok=True)
        for stance in stances:
            stance_log = logs_dir / f"spec_{tid}_{stance}.log"
            cmd = [
                "python3", str(ROOT / "scripts" / "extract_specs_krama_multi.py"),
                "--tasks", str(single),
                "--extractor", EXTRACTOR,
                "--out", str(tmp_dir),
                "--stances", stance,  # ONE stance per call
            ]
            log(f"[SPEC] {tid}/{stance} — extracting")
            with stance_log.open("w") as lf:
                r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT)
            src = tmp_dir / f"{tid}.stance_{stance}.json"
            dst = specs_root / stance / f"{tid}.json"
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.exists():
                shutil.copy(src, dst)
                spec_done_queue.put((t, stance))
                log(f"[SPEC] {tid}/{stance} — ready (rc={r.returncode}) → queued for exec")
            else:
                log(f"[SPEC] {tid}/{stance} — MISSING (rc={r.returncode}); pushing sentinel")
                spec_done_queue.put((t, stance, "missing"))
    spec_done_queue.put(None)


def executor_worker(
    worker_id: int,
    shard_config: Path,
    in_queue: "queue.Queue",
    pending: list,
    pending_lock: threading.Lock,
    specs_root: Path,
    runs_root: Path,
    logs_dir: Path,
    answers: dict,
    answers_lock: threading.Lock,
) -> None:
    """Pull (task, stance) pairs and run each through run.ts using the right
    stance's --specs dir. Records the final_answer into the shared answers dict."""
    while True:
        # Drain spec_done_queue into pending
        try:
            while True:
                item = in_queue.get_nowait()
                if item is None:
                    in_queue.put(None)
                    break
                with pending_lock:
                    pending.append(item)
        except queue.Empty:
            pass
        # Claim work
        claimed = None
        with pending_lock:
            if pending:
                claimed = pending.pop(0)
        if claimed is None:
            try:
                item = in_queue.get(timeout=5)
            except queue.Empty:
                continue
            if item is None:
                in_queue.put(None)
                with pending_lock:
                    if not pending:
                        log(f"[EXEC{worker_id}] no more work, exiting")
                        return
                continue
            with pending_lock:
                pending.append(item)
            continue
        # Handle missing-spec sentinel
        if len(claimed) == 3 and claimed[2] == "missing":
            t, stance, _ = claimed
            tid = str(t["task_id"])
            with answers_lock:
                answers.setdefault(tid, {})[stance] = ""
            log(f"[EXEC{worker_id}] {tid}/{stance} — skipped (spec missing)")
            continue
        t, stance = claimed
        tid = str(t["task_id"])
        single = logs_dir / f"exec_{tid}_{stance}.jsonl"
        single.write_text(json.dumps(t) + "\n")
        out_dir = runs_root / stance / f"shard_w{worker_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        log_path = logs_dir / f"run_{tid}_{stance}_w{worker_id}.log"
        cmd = [
            "npx", "tsx", str(ROOT / "src" / "run.ts"),
            "-d", str(single),
            "-c", str(shard_config),
            "-o", str(out_dir),
            "--specs", str(specs_root / stance),
            "-n", f"krama_i2 task={tid} stance={stance} worker={worker_id}",
        ]
        log(f"[EXEC{worker_id}] {tid}/{stance} — running")
        with log_path.open("w") as lf:
            subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=str(ROOT))
        # Read the summary.json for this worker, grab the row for this task
        sp = out_dir / "summary.json"
        ans = ""
        if sp.exists():
            try:
                rows = json.loads(sp.read_text())
                for row in rows:
                    if str(row.get("task_id")) == tid:
                        ans = row.get("final_answer") or ""
                        break
            except Exception:
                pass
        with answers_lock:
            answers.setdefault(tid, {})[stance] = ans
        log(f"[EXEC{worker_id}] {tid}/{stance} — done (ans={ans[:60] if ans else '(empty)'})")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--stances", default=",".join(DEFAULT_STANCES))
    p.add_argument("--workers", type=int, default=2)
    args = p.parse_args()

    stances = [s.strip() for s in args.stances.split(",") if s.strip()]
    out_dir = Path(args.out)
    specs_root = out_dir / "specs"
    runs_root = out_dir / "runs"
    logs_dir = out_dir / "logs"
    for d in (out_dir, specs_root, runs_root, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    tasks = [json.loads(l) for l in Path(args.tasks).read_text().splitlines() if l.strip()]
    log(f"Loaded {len(tasks)} tasks; stances = {stances}; workers = {args.workers}")
    log(f"Total executor jobs: {len(tasks) * len(stances)}")
    log(f"Specs:    {specs_root}/{{{'|'.join(stances)}}}")
    log(f"Runs:     {runs_root}/<stance>/shard_w<id>")

    spec_done_queue: "queue.Queue" = queue.Queue()
    pending: list = []
    pending_lock = threading.Lock()
    answers: dict = {}
    answers_lock = threading.Lock()

    sp = threading.Thread(
        target=spec_worker,
        args=(tasks, stances, specs_root, logs_dir, spec_done_queue),
        daemon=True,
    )
    sp.start()

    execs = []
    for i in range(args.workers):
        ex = threading.Thread(
            target=executor_worker,
            args=(i, SHARD_CONFIGS[i], spec_done_queue, pending, pending_lock,
                  specs_root, runs_root, logs_dir, answers, answers_lock),
            daemon=True,
        )
        ex.start()
        execs.append(ex)

    # Watcher: persist running state every 60s
    try:
        while any(e.is_alive() for e in execs) or sp.is_alive():
            time.sleep(30)
            with answers_lock:
                snap = {k: dict(v) for k, v in answers.items()}
            (out_dir / "running_answers.json").write_text(json.dumps(snap, indent=2))
    except KeyboardInterrupt:
        log("interrupted; persisting what we have")

    sp.join(timeout=30)
    for e in execs:
        e.join(timeout=30)

    (out_dir / "per_task_answers.json").write_text(json.dumps(answers, indent=2))

    # ---- adjudication ----
    log("\n━━━ Adjudicating ━━━")
    methods = defaultdict(int)
    final = []
    for t in tasks:
        tid = str(t["task_id"])
        per = answers.get(tid, {s: "" for s in stances})
        winner_ans, winner_stance, method = adjudicate(per, t)
        methods[method] += 1
        final.append({
            "task_id": tid,
            "domain": t.get("domain"),
            "level": t.get("level"),
            "final_answer": winner_ans,
            "winner_stance": winner_stance,
            "method": method,
            "per_stance_answers": per,
            "gold": t.get("answer", ""),
            "answer_type": t.get("answer_type", ""),
        })
    (out_dir / "final_results.json").write_text(json.dumps(final, indent=2))
    log("Adjudication method breakdown:")
    for m, n in sorted(methods.items(), key=lambda x: -x[1]):
        log(f"  {m}: {n}")
    log(f"\nWrote {out_dir}/final_results.json ({len(final)} tasks)")


if __name__ == "__main__":
    main()
