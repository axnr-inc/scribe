"""Convert LiveSQLBench JSONL tasks to the SCRIBE harness task format.

Output JSONL has fields: task_id, question, guidelines, level, db_path, db_name
The spec (if pre-extracted) is grafted into `question` as a markdown block.

Usage:
  # Baseline (no spec grafting)
  python scripts/livesqlbench_adapter.py \\
      --tasks /Users/suraj/Downloads/livesqlbench/tasks.jsonl \\
      --db-dir /Users/suraj/Downloads/livesqlbench/databases \\
      --out /Users/suraj/Downloads/livesqlbench/livesql_harness_tasks.jsonl

  # With spec grafting (after extract_specs_livesql.py ran)
  python scripts/livesqlbench_adapter.py \\
      --tasks /Users/suraj/Downloads/livesqlbench/tasks.jsonl \\
      --db-dir /Users/suraj/Downloads/livesqlbench/databases \\
      --specs results/livesql_scribe/specs \\
      --out /Users/suraj/Downloads/livesqlbench/livesql_harness_tasks_grafted.jsonl

  # Sample N tasks (stratified by difficulty, SELECT-only)
  python scripts/livesqlbench_adapter.py ... --sample 20 --seed 42
"""
import argparse, json, random, sys
from pathlib import Path


DIFFICULTY_MAP = {"Simple": "easy", "Moderate": "medium", "Challenging": "hard"}


def render_spec_markdown(spec: dict) -> str:
    """Render a LiveSQL spec dict as markdown for injection into the task question."""
    lines = ["## Query Plan Spec"]

    lines.append(f"\n**Tables needed:** {', '.join(spec.get('tables_needed', []))}")

    jp = spec.get("join_path", [])
    if jp:
        lines.append("\n**Join path:**")
        for j in jp:
            lines.append(f"- `{j['from_col']}` → `{j['to_col']}` ({j['join_type']})")

    jcols = spec.get("json_columns", [])
    if jcols:
        lines.append("\n**JSON extractions:**")
        for jc in jcols:
            cast = f" AS {jc['cast']}" if jc.get("cast") else ""
            lines.append(f"- `json_extract({jc['table']}.{jc['column']}, '{jc['path']}'){cast}` → `{jc['alias']}`")

    formulas = spec.get("kb_formulas", [])
    if formulas:
        lines.append("\n**KB formulas (implement exactly):**")
        for f in formulas:
            lines.append(f"- **{f['name']}** (KB id={f.get('kb_id','?')}): `{f['sql_expression']}`")
            if f.get("depends_on"):
                lines.append(f"  - Depends on: {', '.join(f['depends_on'])}")
            if f.get("threshold"):
                lines.append(f"  - Threshold: {f['threshold']}")
            if f.get("notes"):
                lines.append(f"  - Note: {f['notes']}")

    ctes = spec.get("cte_plan", [])
    if ctes:
        lines.append("\n**CTE plan (implement in this order):**")
        for i, cte in enumerate(ctes):
            lines.append(f"\n{i+1}. `{cte['name']}` — {cte['computes']}")
            lines.append(f"   ```sql\n   {cte['sql_sketch']}\n   ```")
            if cte.get("group_by"):
                lines.append(f"   GROUP BY: `{cte['group_by']}`")
            if cte.get("agg_note"):
                lines.append(f"   ⚠ Aggregation: {cte['agg_note']}")

    lines.append(f"\n**Output columns:** {', '.join(spec.get('output_columns', []))}")
    lines.append(f"\n**Ordering:** {spec.get('output_ordering', 'none')}")
    lines.append(f"\n**Expected format:** {spec.get('expected_output_format', '')}")

    edge = spec.get("edge_cases", [])
    if edge:
        lines.append("\n**Edge cases:**")
        for e in edge:
            lines.append(f"- {e}")

    notes = spec.get("notes_for_executor", "")
    if notes:
        lines.append(f"\n**SQLite notes:** {notes}")

    return "\n".join(lines)


def sample_tasks(tasks: list, n: int, seed: int) -> list:
    random.seed(seed)
    select = [t for t in tasks if t.get("category") == "Query"]
    simple      = [t for t in select if t["difficulty_tier"] == "Simple"]
    moderate    = [t for t in select if t["difficulty_tier"] == "Moderate"]
    challenging = [t for t in select if t["difficulty_tier"] == "Challenging"]

    s = max(1, n * 5 // 20)
    m = max(1, n * 10 // 20)
    c = max(1, n - s - m)

    return (
        random.sample(simple,      min(s, len(simple))) +
        random.sample(moderate,    min(m, len(moderate))) +
        random.sample(challenging,  min(c, len(challenging)))
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks",  required=True, help="LiveSQLBench tasks.jsonl")
    parser.add_argument("--db-dir", required=True, help="Databases root dir")
    parser.add_argument("--specs",  default=None,  help="Specs dir (from extract_specs_livesql.py)")
    parser.add_argument("--out",    required=True, help="Output harness JSONL")
    parser.add_argument("--sample", type=int, default=None, help="Sample N tasks (stratified)")
    parser.add_argument("--seed",   type=int, default=42)
    parser.add_argument("--select-only", action="store_true", default=True)
    args = parser.parse_args()

    db_dir   = Path(args.db_dir)
    specs_dir = Path(args.specs) if args.specs else None

    raw_tasks = [json.loads(l) for l in open(args.tasks) if l.strip()]

    if args.select_only:
        raw_tasks = [t for t in raw_tasks if t.get("category") == "Query"]

    if args.sample:
        raw_tasks = sample_tasks(raw_tasks, args.sample, args.seed)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    with open(out_path, "w") as f:
        for task in raw_tasks:
            db_name = task["selected_database"]
            db_file = db_dir / db_name / f"{db_name}_template.sqlite"

            # Build question: include task query
            question = task["query"]

            # Graft spec if available
            if specs_dir:
                spec_file = specs_dir / f"{task['instance_id']}.json"
                if spec_file.exists():
                    spec = json.load(open(spec_file))
                    question = question + "\n\n" + render_spec_markdown(spec)

            row = {
                "task_id":  task["instance_id"],
                "question": question,
                "level":    DIFFICULTY_MAP.get(task.get("difficulty_tier", ""), "medium"),
                "db_path":  str(db_file),
                "db_name":  db_name,
            }
            f.write(json.dumps(row) + "\n")
            written += 1

    print(f"Wrote {written} tasks → {out_path}")
    if specs_dir:
        grafted = sum(1 for t in raw_tasks
                      if (specs_dir / f"{t['instance_id']}.json").exists())
        print(f"  Grafted specs: {grafted}/{written}")


if __name__ == "__main__":
    main()
