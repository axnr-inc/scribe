"""KramaBench adapter — converts workload/<domain>.json into SCRIBE TaskRow JSONL.

Each KramaBench task has the shape:
  {
    "id": "archeology-hard-1",
    "query": "What is the average Potassium ...",
    "answer": 8577.5298,
    "answer_type": "numeric_exact",
    "data_sources": ["radiocarbon_database_regional.xlsx", ...],
    "subtasks": [...],
    "deepresearch_subset": [...]
  }

We emit:
  {
    "task_id": "archeology-hard-1",
    "question": "What is the average Potassium ...",
    "guidelines": "<derived from answer_type>",
    "level": "hard",
    "answer": "8577.5298",
    "answer_type": "numeric_exact",
    "context_dir": "/abs/path/to/data/kramabench/data/archeology/input",
    "data_sources": [...]
  }

`context_dir` overrides the harness's global CONTEXT_DIR for this task, so the
executor's Python REPL sees the right per-domain data lake.

Examples:
  python3 scripts/kramabench_adapter.py \
      --domains archeology \
      --out data/splits/krama_archeology12.jsonl

  python3 scripts/kramabench_adapter.py \
      --domains archeology legal \
      --hard-only \
      --out data/splits/krama_hard_2dom.jsonl
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KRAMA_ROOT = ROOT / "data" / "kramabench"
WORKLOAD_DIR = KRAMA_ROOT / "workload"
DATA_DIR = KRAMA_ROOT / "data"

DOMAINS = ("archeology", "astronomy", "biomedical", "environment", "legal", "wildfire")


def guidelines_for(answer_type: str) -> str:
    """Map KramaBench's answer_type to a natural-language guideline the executor
    will see appended to the question. Matches the DABStep convention of stating
    the expected format explicitly so the model doesn't over-decorate the answer."""
    a = (answer_type or "").lower()
    if a == "numeric_exact":
        return "Answer must be just a number, no units, no commas. Round to the precision the question requests."
    if a == "numeric_approximate":
        return "Answer must be just a number, no units, no commas. Reasonable rounding is acceptable."
    if a == "string_exact":
        return "Answer must be just the string value, no extra prose."
    if a == "string_approximate":
        return "Answer must be just the string value (case-insensitive)."
    if a == "list_exact":
        return "Answer must be a list of values, comma-separated on one line, in the order the question implies."
    if a == "list_approximate":
        return "Answer must be a list of values, comma-separated on one line. Order does not need to match exactly."
    if a == "boolean":
        return "Answer must be exactly 'True' or 'False'."
    return "Answer must match the format the question implies. If no relevant answer is applicable, respond with 'Not Applicable'."


def task_to_row(task: dict, domain: str) -> dict:
    tid = str(task["id"])
    # KramaBench ids encode difficulty: "archeology-hard-1" or "archeology-easy-3".
    level = "hard" if "-hard-" in tid else ("easy" if "-easy-" in tid else "unknown")
    ctx = (DATA_DIR / domain / "input").resolve()
    if not ctx.exists():
        print(f"  WARN: data lake input dir missing for {domain}: {ctx}", file=sys.stderr)
    return {
        "task_id": tid,
        "question": task["query"],
        "guidelines": guidelines_for(task.get("answer_type", "")),
        "level": level,
        "answer": str(task.get("answer", "")),
        "answer_type": task.get("answer_type", ""),
        "context_dir": str(ctx),
        "data_sources": task.get("data_sources", []),
        "domain": domain,
    }


def load_domain_tasks(domain: str) -> list[dict]:
    path = WORKLOAD_DIR / f"{domain}.json"
    if not path.exists():
        raise SystemExit(
            f"Workload file not found: {path}\n"
            "Run: python3 scripts/fetch_kramabench_data.py --domains " + domain
        )
    return json.loads(path.read_text())


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--domains", nargs="+", default=["archeology"],
                   help=f"Domains to include. Choices: {', '.join(DOMAINS)}")
    p.add_argument("--hard-only", action="store_true", help="Keep only `*-hard-*` tasks.")
    p.add_argument("--easy-only", action="store_true", help="Keep only `*-easy-*` tasks.")
    p.add_argument("--limit", type=int, default=0, help="Cap total rows (0 = no cap).")
    p.add_argument("--out", required=True, help="Output JSONL path (e.g., data/splits/krama_archeology12.jsonl).")
    args = p.parse_args()

    if args.hard_only and args.easy_only:
        raise SystemExit("--hard-only and --easy-only are mutually exclusive.")
    for d in args.domains:
        if d not in DOMAINS:
            raise SystemExit(f"Unknown domain '{d}'. Choices: {', '.join(DOMAINS)}")

    rows: list[dict] = []
    for domain in args.domains:
        tasks = load_domain_tasks(domain)
        for t in tasks:
            row = task_to_row(t, domain)
            if args.hard_only and row["level"] != "hard":
                continue
            if args.easy_only and row["level"] != "easy":
                continue
            rows.append(row)
            if args.limit and len(rows) >= args.limit:
                break
        if args.limit and len(rows) >= args.limit:
            break

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    print(f"Wrote {len(rows)} task(s) to {out_path}")
    # Per-domain summary
    by_dom: dict[str, int] = {}
    for r in rows:
        by_dom[r["domain"]] = by_dom.get(r["domain"], 0) + 1
    for d, n in by_dom.items():
        print(f"  {d}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
