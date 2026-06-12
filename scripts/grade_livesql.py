"""Grade LiveSQLBench predictions against gold SQL.

Execution accuracy: execute pred SQL and gold SQL against the template SQLite,
compare result sets (unordered by default, ordered if conditions.order=True).

Usage:
    python scripts/grade_livesql.py \\
        --results results/livesql_scribe \\
        --gt /Users/suraj/Downloads/livesqlbench/livesqlbench_sqlite_gt_kg_testcases_0528.jsonl \\
        --db-dir /Users/suraj/Downloads/livesqlbench/databases \\
        --tasks /Users/suraj/Downloads/livesqlbench/tasks.jsonl
"""
import argparse, json, sqlite3, pathlib
from collections import Counter


def preprocess(rows):
    out = []
    for row in rows:
        new_row = tuple(round(v, 2) if isinstance(v, float) else v for v in row)
        out.append(new_row)
    return out


def execute_sql(sql: str, db_path: str):
    try:
        conn = sqlite3.connect(db_path)
        cur  = conn.execute(sql)
        rows = cur.fetchall()
        conn.close()
        return rows, None
    except Exception as e:
        return None, str(e)


def score_one(pred_sql: str, gold_sql: str, db_path: str, ordered: bool):
    pr, pe = execute_sql(pred_sql, db_path)
    if pe:
        return "exec_error", pe
    gr, ge = execute_sql(gold_sql, db_path)
    if ge:
        return "gold_error", ge
    pp = preprocess(pr)
    gp = preprocess(gr)
    match = (pp == gp) if ordered else (set(pp) == set(gp))
    return ("pass" if match else "wrong_result"), None


def extract_final_sql_from_text(text: str) -> str | None:
    """Pull the FINAL SQL: line out of a full response text."""
    if not text:
        return None
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped.upper().startswith("FINAL SQL:"):
            candidate = stripped[len("FINAL SQL:"):].strip()
            if candidate and not candidate.startswith("--"):
                return candidate
    # fallback: extract from ```sql ... ``` code block if present
    import re
    code_block = re.search(r'```sql\s*(.*?)```', text, re.DOTALL | re.IGNORECASE)
    if code_block:
        return code_block.group(1).strip()
    # last WITH/SELECT block — truncate at first blank line after the SQL ends
    matches = list(re.finditer(r'(WITH\s+\w|\bSELECT\b)', text, re.IGNORECASE))
    if matches:
        last = matches[-1]
        fragment = text[last.start():]
        # Stop at first blank line or obvious prose (line not starting with SQL keywords/whitespace)
        sql_lines = []
        for line in fragment.splitlines():
            if re.match(r'^\s*$', line) and sql_lines:
                break
            sql_lines.append(line)
        return "\n".join(sql_lines).strip()
    return None


def find_final_sql(task_dir: pathlib.Path) -> str | None:
    """Extract final SQL from the task's summary or session log."""
    # Try summary.json first
    summary = task_dir.parent / "summary.json"
    if summary.exists():
        rows = json.load(open(summary))
        for r in rows:
            if r.get("task_id") == task_dir.name:
                raw = r.get("final_answer") or r.get("final_sql") or ""
                return extract_final_sql_from_text(raw)

    # Fall back to session JSONL
    for sess_file in sorted(task_dir.glob("sessions/*.jsonl")):
        events = [json.loads(l) for l in open(sess_file) if l.strip()]
        for e in reversed(events):
            if e.get("type") == "agent_done" or (isinstance(e, dict) and "final_answer" in e):
                ans = e.get("final_answer", "")
                if ans and not ans.startswith("--"):
                    return ans
        # scan assistant turns for FINAL SQL:
        for e in reversed(events):
            content = ""
            if isinstance(e.get("content"), str):
                content = e["content"]
            elif isinstance(e.get("content"), list):
                for block in e["content"]:
                    if isinstance(block, dict) and block.get("type") == "text":
                        content += block.get("text", "")
            for line in reversed(content.splitlines()):
                stripped = line.strip()
                if stripped.upper().startswith("FINAL SQL:"):
                    candidate = stripped[len("FINAL SQL:"):].strip()
                    if candidate and not candidate.startswith("--"):
                        return candidate
    return None


def main():
    parser = argparse.ArgumentParser()
    # `--results` is the historical flag; `--out` is the alias matching
    # grade.py / grade_krama.py conventions for the run output dir.
    parser.add_argument("--results", "--out", dest="results", required=True,
                        help="Run output dir (results/<arm>/) — alias: --out")
    parser.add_argument("--gt",      required=True, help="GT JSONL with sol_sql")
    parser.add_argument("--db-dir",  required=True, help="Databases root dir")
    parser.add_argument("--tasks",   required=True, help="LiveSQLBench tasks.jsonl (for conditions)")
    parser.add_argument("--out-csv", dest="out_csv", default=None, help="Output scored CSV path")
    args = parser.parse_args()

    results_dir = pathlib.Path(args.results)
    db_dir      = pathlib.Path(args.db_dir)

    gt       = {r["instance_id"]: r for r in [json.loads(l) for l in open(args.gt)]}
    tasks_map = {t["instance_id"]: t for t in [json.loads(l) for l in open(args.tasks)]}

    rows = []
    for task_dir in sorted(results_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        tid = task_dir.name
        if tid not in gt:
            continue

        task_meta = tasks_map.get(tid, {})
        db_name   = task_meta.get("selected_database", "")
        db_path   = str(db_dir / db_name / f"{db_name}_template.sqlite")
        ordered   = (task_meta.get("conditions") or {}).get("order", False)

        gold_sqls = gt[tid].get("sol_sql", [])
        if not gold_sqls:
            rows.append({"task_id": tid, "db": db_name,
                         "difficulty": task_meta.get("difficulty_tier","?"),
                         "status": "no_gold", "detail": ""})
            continue

        pred_sql = find_final_sql(task_dir)
        if not pred_sql:
            rows.append({"task_id": tid, "db": db_name,
                         "difficulty": task_meta.get("difficulty_tier","?"),
                         "status": "no_sql", "detail": ""})
            continue

        status, detail = score_one(pred_sql, gold_sqls[0], db_path, ordered)
        rows.append({
            "task_id":    tid,
            "db":         db_name,
            "difficulty": task_meta.get("difficulty_tier", "?"),
            "status":     status,
            "detail":     (detail or "")[:200],
            "pred_sql":   pred_sql[:300],
        })

    # Print table
    print(f"\n{'task_id':22s} {'diff':12s} {'status':14s}")
    print("-" * 55)
    for r in sorted(rows, key=lambda x: (x["status"], x["task_id"])):
        print(f"{r['task_id']:22s} {r['difficulty']:12s} {r['status']:14s}  {r['detail'][:50]}")

    counts = Counter(r["status"] for r in rows)
    total  = len(rows)
    print(f"\n{'='*55}")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:14s}: {v:3d}/{total}")
    passes = counts.get("pass", 0)
    print(f"\n  Execution accuracy: {passes}/{total} = {passes/total*100:.1f}%")

    # Canonical machine-readable per-task record — mirrors grade.py / grade_krama.py.
    (results_dir / "results.json").write_text(json.dumps(rows, indent=2))

    if args.out_csv:
        import csv
        with open(args.out_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"\nScores saved → {args.out_csv}")


if __name__ == "__main__":
    main()
