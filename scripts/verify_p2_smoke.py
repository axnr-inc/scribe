#!/usr/bin/env python3
"""
Post-run verification for the P2 smoke test.

Scans the session logs under results/<run>/ for evidence that each P2
behavior fired:

  - Spec injection: did the executor's user message contain `# Spec produced
    by spec_agent` + a JSON code fence?
  - Verdict headers: did every `ask_planner_agent` / `ask_spec_agent` reply
    start with `[Verdict: X]`?
  - Spec revisions: were `<task_id>.rev{N}.json` files written when SPEC_WRONG
    fired? Did the audit log `<task_id>.revisions.jsonl` get a row each time?
  - read_current_spec: did the executor invoke it after a SPEC_WRONG verdict?
  - EC4 retry: how often did the malformed-verdict retry fire? How often did
    it fix the verdict?
  - Revision cap: are all per-task revision counts <= 3?

Usage:
  python3 scripts/verify_p2_smoke.py --out results/p2_smoke
"""
import argparse
import collections
import json
import re
from pathlib import Path


VERDICT_PAT = re.compile(r"\[Verdict:\s*(SPEC_WRONG|BLIND_SPOT|EXECUTOR_WRONG|NA_CONFIRMED|ANSWER)\]")
RETRY_FIXED_PAT = re.compile(r"verdict retry:.*corrected on retry", re.IGNORECASE)
RETRY_STILL_MAL_PAT = re.compile(r"verdict retry:.*still malformed", re.IGNORECASE)
REVISION_FOOTER_PAT = re.compile(r"spec revision rev(\d+) persisted")


def scan_task(task_dir: Path, specs_dir: Path) -> dict:
    tid = task_dir.name
    log_path = task_dir / "sessions" / "normal_agent.jsonl"
    if not log_path.exists():
        return {"task_id": tid, "log_missing": True}

    out = {
        "task_id": tid,
        "spec_injected": False,
        "planner_calls": 0,
        "verdict_counts": collections.Counter(),
        "read_current_spec_calls": 0,
        "ec4_retry_fired": 0,
        "ec4_retry_fixed": 0,
        "ec4_retry_still_malformed": 0,
        "revisions_seen_in_footer": [],
    }

    lines = log_path.read_text().splitlines()
    for line in lines:
        if not line.strip():
            continue
        try:
            evt = json.loads(line)
        except Exception:
            continue
        t = evt.get("type")
        if t == "user_message":
            content = str(evt.get("content", ""))
            # Detect either format: legacy JSON-fence or renderSpecForPrompt markdown.
            if (
                ("# Spec produced by spec_agent" in content and "```json" in content)
                or "Rule-extraction summary (from a planning step" in content
            ):
                out["spec_injected"] = True
        elif t == "tool_call":
            name = evt.get("toolName") or ""
            if name in ("ask_planner_agent", "ask_spec_agent"):
                out["planner_calls"] += 1
            if name == "read_current_spec":
                out["read_current_spec_calls"] += 1
        elif t == "tool_call_result":
            content = str(evt.get("content", ""))
            # Verdict counting
            m = VERDICT_PAT.search(content)
            if m:
                out["verdict_counts"][m.group(1)] += 1
            # EC4 retry markers (in footer)
            if RETRY_FIXED_PAT.search(content):
                out["ec4_retry_fired"] += 1
                out["ec4_retry_fixed"] += 1
            if RETRY_STILL_MAL_PAT.search(content):
                out["ec4_retry_fired"] += 1
                out["ec4_retry_still_malformed"] += 1
            # Revision footer ("spec revision revN persisted")
            for rm in REVISION_FOOTER_PAT.finditer(content):
                out["revisions_seen_in_footer"].append(int(rm.group(1)))

    # Cross-check disk state for revisions.
    rev_files = sorted(specs_dir.glob(f"{tid}.rev*.json"), key=lambda p: int(re.search(r"rev(\d+)", p.name).group(1)))
    out["revision_files_on_disk"] = [p.name for p in rev_files]
    rev_log = specs_dir / f"{tid}.revisions.jsonl"
    out["revision_log_rows"] = (
        sum(1 for ln in rev_log.read_text().splitlines() if ln.strip()) if rev_log.exists() else 0
    )
    original_path = specs_dir / f"{tid}.original.json"
    current_path = specs_dir / f"{tid}.json"
    out["has_original_snapshot"] = original_path.exists()
    out["has_current_spec"] = current_path.exists()
    if out["has_original_snapshot"] and out["has_current_spec"]:
        out["spec_was_revised"] = original_path.read_text() != current_path.read_text()
    else:
        out["spec_was_revised"] = False

    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="Path to the run output dir (e.g. results/p2_smoke)")
    args = p.parse_args()

    run_dir = Path(args.out)
    specs_dir = run_dir / "specs"
    if not specs_dir.exists():
        raise SystemExit(f"specs dir not found: {specs_dir}")

    # Each task dir under run_dir is a folder named by task_id with sessions/ inside.
    task_dirs = sorted([
        d for d in run_dir.iterdir()
        if d.is_dir() and d.name != "specs" and (d / "sessions").exists()
    ])
    if not task_dirs:
        raise SystemExit(f"no task dirs with sessions/ found under {run_dir}")

    print(f"Scanning {len(task_dirs)} task(s) under {run_dir}\n")

    totals = collections.Counter()
    rows = []
    for td in task_dirs:
        row = scan_task(td, specs_dir)
        rows.append(row)
        totals["spec_injected"] += int(row.get("spec_injected", False))
        totals["planner_calls"] += row.get("planner_calls", 0)
        totals["read_current_spec_calls"] += row.get("read_current_spec_calls", 0)
        totals["ec4_retry_fired"] += row.get("ec4_retry_fired", 0)
        totals["ec4_retry_fixed"] += row.get("ec4_retry_fixed", 0)
        totals["ec4_retry_still_malformed"] += row.get("ec4_retry_still_malformed", 0)
        totals["spec_revised"] += int(row.get("spec_was_revised", False))
        for v, n in row.get("verdict_counts", {}).items():
            totals[f"verdict_{v}"] += n

    # Per-task table
    print(f"{'task':>6}  {'inj':>3}  {'plnr':>4}  {'rcs':>3}  {'rev':>3}  verdicts")
    print("-" * 70)
    for r in rows:
        verdicts = ",".join(f"{v}={n}" for v, n in r.get("verdict_counts", {}).items()) or "-"
        print(f"{r['task_id']:>6}  {'Y' if r.get('spec_injected') else 'N':>3}  "
              f"{r.get('planner_calls', 0):>4}  {r.get('read_current_spec_calls', 0):>3}  "
              f"{len(r.get('revision_files_on_disk', [])):>3}  {verdicts}")

    print("\n=== Totals ===")
    for k in [
        "spec_injected", "planner_calls", "read_current_spec_calls",
        "ec4_retry_fired", "ec4_retry_fixed", "ec4_retry_still_malformed",
        "spec_revised",
    ]:
        print(f"  {k:<32} {totals[k]}")
    print("\n=== Verdict mix ===")
    for v in ("SPEC_WRONG", "BLIND_SPOT", "EXECUTOR_WRONG", "NA_CONFIRMED", "ANSWER"):
        print(f"  {v:<20} {totals[f'verdict_{v}']}")

    # Sanity checks
    print("\n=== Sanity checks ===")
    bad = []
    for r in rows:
        rev_files = r.get("revision_files_on_disk", [])
        rev_in_footer = r.get("revisions_seen_in_footer", [])
        if len(rev_files) != r.get("revision_log_rows", 0):
            bad.append(f"  {r['task_id']}: rev files on disk ({len(rev_files)}) != revisions.jsonl rows ({r.get('revision_log_rows', 0)})")
        if len(rev_files) > 3:
            bad.append(f"  {r['task_id']}: revision cap exceeded ({len(rev_files)} > 3)")
        if rev_files and not r.get("spec_was_revised"):
            bad.append(f"  {r['task_id']}: rev files exist but current spec matches original")
        # Verdict-of-SPEC_WRONG should produce a rev (unless rejected — but smoke shouldn't hit cap)
        sw_count = r.get("verdict_counts", {}).get("SPEC_WRONG", 0)
        if sw_count > 0 and len(rev_files) == 0:
            bad.append(f"  {r['task_id']}: {sw_count} SPEC_WRONG verdict(s) but no rev files written")
    if bad:
        print("FAIL:")
        for b in bad:
            print(b)
    else:
        print("OK: all sanity checks pass")


if __name__ == "__main__":
    main()
