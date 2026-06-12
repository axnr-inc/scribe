"""Build a tasks.jsonl that the harness can consume.

Two modes:
  --mode baseline   : copy target_tasks.jsonl verbatim (no spec appended)
  --mode grafted    : append the spec from --specs <dir>/<task_id>.json to each task's question

Output is a single tasks.jsonl file the harness reads.

Example:
  # Baseline (no spec):
  python scripts/build_dataset.py \\
      --tasks data/target_tasks.jsonl \\
      --mode baseline \\
      --out results/opus_baseline/tasks.jsonl

  # Grafted (from a spec dir):
  python scripts/build_dataset.py \\
      --tasks data/target_tasks.jsonl \\
      --mode grafted \\
      --specs results/sonnet_kimi/specs \\
      --out results/sonnet_kimi/tasks.jsonl
"""
import argparse
import json
from pathlib import Path


def render_spec_for_prompt(spec: dict) -> str:
    """Render the spec as a markdown block to append to the question."""
    m = spec.get("merchant", {}) or {}
    d = spec.get("date_filter", {}) or {}
    ml = spec.get("matching_logic", {}) or {}

    lines = [
        "## Rule-extraction summary (from a planning step — trust these facts, do not re-derive)",
        "",
        f"**Question summary**: {spec.get('question_summary','')}",
        f"**Answer type**: {spec.get('answer_type','')}",
        "",
        "**Merchant facts:**",
        f"- name: {m.get('name')}",
        f"- account_type: {m.get('account_type')}",
        f"- merchant_category_code: {m.get('merchant_category_code')}",
        f"- capture_delay: {m.get('capture_delay')}",
        f"- acquirers: {m.get('acquirers')}",
    ]
    if m.get("notes"):
        lines.append(f"- notes: {m['notes']}")
    lines += [
        "",
        "**Date filter:**",
        f"- kind: {d.get('kind')}",
        f"- year: {d.get('year')}",
        f"- month: {d.get('month')}",
        f"- day_of_year: {d.get('day_of_year')}",
        f"- iso_date: {d.get('iso_date')}",
        "",
        f"**Applicable card schemes**: {', '.join(spec.get('applicable_card_schemes') or [])}",
        "",
        "**Matching logic:**",
        f"- convention: {ml.get('convention')}",
        f"- fields_to_match: {', '.join(ml.get('fields_to_match') or [])}",
        "- derived_fields:",
    ]
    for df in ml.get("derived_fields") or []:
        lines.append(f"  - {df}")
    lines += ["", "**Computation plan:**"]
    for i, step in enumerate(spec.get("computation_plan") or [], 1):
        lines.append(f"  {i}. {step}")
    lines += [
        "",
        f"**Expected output format**: {spec.get('expected_output_format','')}",
    ]
    notes = spec.get("notes_for_executor") or ""
    if notes:
        lines += ["", f"**Notes**: {notes}"]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", required=True, help="Source tasks JSONL")
    p.add_argument("--mode", required=True, choices=["baseline", "grafted"])
    p.add_argument("--specs", help="Directory of <task_id>.json spec files (required for --mode grafted)")
    p.add_argument("--out", required=True, help="Output tasks JSONL")
    args = p.parse_args()

    if args.mode == "grafted" and not args.specs:
        raise SystemExit("--specs is required for grafted mode")

    tasks = [json.loads(l) for l in Path(args.tasks).read_text().splitlines() if l.strip()]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for t in tasks:
        tid = str(t.get("task_id", t.get("id", "")))
        question = t["question"]
        if args.mode == "grafted":
            # Bug 4 fix: previously this branch appended the rendered spec to
            # the question. That caused DOUBLE-INJECTION because src/run.ts
            # now renders + appends the CURRENT spec from disk at runtime
            # (which is the correct behaviour — disk reflects planner revisions).
            # Here we only validate that a usable spec exists, so callers get a
            # clean warning if extraction failed. The actual injection happens
            # in run.ts via --specs <dir>.
            spec_path = Path(args.specs) / f"{tid}.json"
            if not spec_path.exists():
                print(f"  WARN: no spec for {tid}, run.ts will see task only")
            else:
                try:
                    spec = json.loads(spec_path.read_text())
                    if "_error" in spec:
                        print(f"  WARN: spec for {tid} had error; run.ts will skip injection")
                except Exception as e:
                    print(f"  WARN: spec for {tid} unparseable ({e}); run.ts will skip injection")
        rows.append({
            "task_id": tid,
            "question": question,
            "guidelines": t.get("guidelines", ""),
            "level": t.get("level", "hard"),
            "answer": t.get("answer", ""),
        })

    with out.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    print(f"Mode: {args.mode}, Wrote {len(rows)} rows to {out}")


if __name__ == "__main__":
    main()
