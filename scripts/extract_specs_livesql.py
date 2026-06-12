"""Spec extractor for LiveSQLBench — Stage 1 of SCRIBE grafting.

Reads schema.txt + kb.jsonl + column_meaning_base.json for the task's database,
plus the task question, and emits a structured query-plan spec via Anthropic tool_use.
One spec per task. Saves spec JSON + session JSON to --out directory.

Usage:
    python scripts/extract_specs_livesql.py \\
        --tasks /Users/suraj/Downloads/livesqlbench/livesql_harness_tasks.jsonl \\
        --db-dir /Users/suraj/Downloads/livesqlbench/databases \\
        --extractor anthropic:claude-sonnet-4-6 \\
        --out results/livesql_scribe/specs
"""
import argparse, json, os, sys, time, threading
import concurrent.futures
from pathlib import Path
import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "scripts"))

from spec_extraction_tools import (  # noqa: E402
    make_read_file_tool,
    make_list_files_tool,
    make_sample_table_tool,
    make_describe_table_tool,
    make_livesql_dispatcher,
    run_anthropic_spec_loop,
    run_openai_spec_loop,
)

# ── Save-spec tool schema ──────────────────────────────────────────────────────

SAVE_SPEC_TOOL = {
    "name": "save_spec",
    "description": (
        "Save the query-plan spec for this task. This is the single output of the spec-extraction step. "
        "After calling this tool, do not call anything else."
    ),
    "input_schema": {
        "type": "object",
        "required": [
            "question_summary",
            "tables_needed",
            "join_path",
            "json_columns",
            "kb_formulas",
            "cte_plan",
            "output_columns",
            "output_ordering",
            "expected_output_format",
        ],
        "properties": {
            "question_summary": {
                "type": "string",
                "description": "One sentence: what this task asks for.",
            },
            "tables_needed": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Exact table names (case as in DDL) needed to answer this task.",
            },
            "join_path": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["from_col", "to_col", "join_type"],
                    "properties": {
                        "from_col": {"type": "string", "description": "table.column"},
                        "to_col":   {"type": "string", "description": "table.column"},
                        "join_type": {"type": "string", "enum": ["JOIN", "LEFT JOIN"]},
                    },
                },
                "description": "Full FK chain to join all tables_needed. Empty array if only one table.",
            },
            "json_columns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["table", "column", "path", "alias"],
                    "properties": {
                        "table":  {"type": "string"},
                        "column": {"type": "string"},
                        "path":   {"type": "string", "description": "JSON path e.g. '$.field.subfield'"},
                        "alias":  {"type": "string", "description": "SQL alias for the extracted value"},
                        "cast":   {"type": "string", "description": "SQL cast e.g. 'REAL', 'INTEGER', 'TEXT'. Omit if no cast needed."},
                    },
                },
                "description": "Every JSON extraction needed. Use json_extract(column, path) form.",
            },
            "kb_formulas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "kb_id", "sql_expression"],
                    "properties": {
                        "name":           {"type": "string", "description": "Metric name as in the KB"},
                        "kb_id":          {"type": "integer", "description": "KB entry id"},
                        "sql_expression": {"type": "string", "description": "SQL expression implementing this formula using the exact column names/aliases"},
                        "depends_on":     {"type": "array", "items": {"type": "string"}, "description": "Names of other kb_formulas this formula depends on"},
                        "threshold":      {"type": "string", "description": "If the formula has a high/low/category threshold, state it here (e.g. 'LIF > 0.5 = High Interference')"},
                        "notes":          {"type": "string", "description": "Disambiguation note — especially for 'event'/'occurrence' terms: state which table's rows they are"},
                    },
                },
                "description": "ALL KB formulas needed for this task, including dependencies. Resolve recursively.",
            },
            "cte_plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "computes", "sql_sketch"],
                    "properties": {
                        "name":      {"type": "string", "description": "CTE name in snake_case"},
                        "computes":  {"type": "string", "description": "One sentence: what this CTE produces"},
                        "sql_sketch": {"type": "string", "description": "SQL sketch with actual column names. May omit WHERE/HAVING details but must name tables and columns."},
                        "group_by":  {"type": "string", "description": "GROUP BY expression if this CTE aggregates"},
                        "agg_note":  {"type": "string", "description": "If a formula must be pre-aggregated here before being used in a later CTE, state it explicitly"},
                    },
                },
                "description": "Ordered list of CTEs. Each intermediate metric gets its own CTE. The last entry should be the final SELECT.",
            },
            "output_columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Output column names in order, matching what the task asks to display.",
            },
            "output_ordering": {
                "type": "string",
                "description": "ORDER BY clause. Empty string if no ordering.",
            },
            "expected_output_format": {
                "type": "string",
                "description": "One sentence: shape of result (e.g. 'one row per (ObservStation, LunarStage) pair, ordered by avg_lif DESC').",
            },
            "edge_cases": {
                "type": "array",
                "items": {"type": "string"},
                "description": "How to handle: empty result, NULL values, divide-by-zero, 'no matching rule'.",
            },
            "notes_for_executor": {
                "type": "string",
                "description": "Any SQLite-specific syntax the executor must use (e.g. FILTER(WHERE ...), strftime patterns, JSON_GROUP_OBJECT).",
            },
        },
    },
}


# ── System prompt ──────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a spec agent for LiveSQLBench. You read a SQLite database schema, a domain \
knowledge base (KB), and column meanings for a specific database, then produce a \
structured query-plan spec an executor agent will use to write and run the SQL query.

This is a MULTI-SHOT extraction. You may call helper tools to verify facts before \
committing the spec. You have up to 5 tool turns total; use them deliberately.

# Tools available to you

- read_file(filename): re-read a source artifact from the task's docs directory
  (schema.txt / kb.jsonl / column_meaning_base.json). See the manifest in the
  tool description for what's present.
- list_files(): list every file in the docs directory.
- sample_table(table_name, n=10): run `SELECT * FROM <table> LIMIT n` against
  the task's SQLite DB. Use to verify JSON-column paths (e.g. confirm
  `$.propvalue` exists on `propfinancialdata`) and value distributions BEFORE
  finalising the cte_plan.
- describe_table(table_name): return column names + types via PRAGMA table_info.
- save_spec(...): emit your final query-plan spec. Terminates extraction.

Required tool-use discipline: BEFORE calling save_spec, you SHOULD verify at
least one key fact via a helper tool. Typical patterns:
- If the question references JSON columns (e.g. propfinancialdata.propvalue),
  call sample_table on that table to CONFIRM the JSON path actually exists.
  Inferring a path from column meanings alone is the single most common
  source of wrong specs.
- If you're unsure of a column's exact name/casing, call describe_table.
- If the question references a KB metric whose definition is summarised in
  the user message, call read_file on the kb.jsonl to re-verify the formula
  before translating it to SQL.

Calling save_spec on turn 1 without any helper-tool verification is a sign you
didn't actually check the data; do that only when the user message above
already contains everything you need.

# Meta-rules for high-quality specs

1. CONNECT KB FORMULAS TO EXACT SQL EXPRESSIONS.
   For every named metric in the task, find its KB entry and translate the formula
   into a concrete SQL expression using the actual column names. Do not leave a
   KB formula in mathematical notation — the executor needs runnable SQL.
   Example: "LIF = (1 - LunarDistDeg/180) × (1 - AtmosTransparency)"
   → sql_expression: "(1.0 - LunarDistDeg/180.0) * (1.0 - AtmosTransparency)"

2. RESOLVE KB DEPENDENCIES RECURSIVELY.
   If a KB formula depends on another named metric (e.g. FEE depends on PCDR),
   add BOTH to kb_formulas, with the dependency listed in depends_on. The executor
   must compute PCDR before FEE. Never reference a named metric in a formula
   without also specifying that metric's own sql_expression.

3. TRACE THE FULL JOIN PATH FROM THE DDL.
   Examine every FOREIGN KEY constraint in the schema. Determine the minimal set of
   tables needed and the exact join chain (table_a.col → table_b.col). Include this
   in join_path. If the task requires only one table, join_path is empty.

4. SPECIFY JSON EXTRACTIONS EXACTLY.
   For every JSON column in the query, specify the exact json_extract() path and
   alias. Use the column_meanings doc to find the nested field path. Always cast
   numeric fields (CAST(json_extract(col, '$.field') AS REAL)).

5. SPECIFY AGGREGATION LEVEL.
   When a formula component must be averaged or summed per entity BEFORE being used
   in an outer formula (e.g. avg OMI per trader, then OMI feeds ATI), create a
   separate CTE for that pre-aggregation and document it in agg_note. This is the
   most common cause of wrong results.

6. DISAMBIGUATE "EVENTS" / "OCCURRENCES" / "CASES".
   When the KB uses "events where X" or "cases where Y", determine which table's
   rows constitute one event. Inspect the schema: is it the primary entity table
   (one row per event), or a related table joined in? State this in the formula's
   notes field.

7. TRANSLATE THRESHOLD LOGIC TO SQL.
   If a KB entry defines a category or classification threshold (e.g. "High LIF = LIF > 0.5",
   "Energy-Sustainable = REC > 70"), express this as a CASE WHEN / FILTER(WHERE ...) in
   the sql_sketch for the relevant CTE.

8. EDGE CASES.
   Explicitly state: empty result set behaviour, NULL handling (NULLIF, COALESCE),
   divide-by-zero guards, and what to return if no rows match a filter.

9. VERIFY THE MINIMAL TABLE SET — NO SPURIOUS JOINS.
   Before listing a table in tables_needed, confirm it contributes at least one
   column that cannot be found in the tables already listed. If all required columns
   exist in a single table, tables_needed contains only that table and join_path is
   empty. Do not pull in extra tables just because they are related — only add a
   table when one of its columns is literally referenced in a SELECT, WHERE, or JOIN ON
   clause of the query. Test: for each table T in tables_needed, name the specific
   column from T that appears in the query. If you cannot name one, remove T.

   SPECIAL CASE — "events/occurrences/cases where X": when a KB threshold says
   "events where LIF > 0.5" or similar, the "events" are rows of the TABLE WHOSE
   COLUMNS APPEAR IN THE FORMULA, not rows of a related events/records table.
   LIF uses only LunarDistDeg and AtmosTransparency from Observatories → "events"
   are Observatories rows, and COUNT(*) FILTER(WHERE LIF > 0.5) runs on Observatories
   alone. Never join to a child table (Signals, Transactions, Records) just to count
   "events" unless the formula itself uses columns from that child table.

10. COUNT EVERY MULTIPLICATIVE FACTOR IN KB FORMULAS.
    For every KB formula, count the multiplicative terms in its mathematical
    definition and verify your sql_expression contains the exact same number of
    factors. Do not simplify or drop terms — a formula defined as A × B × C must
    appear as A * B * C in SQL, never as A * B with C silently omitted.
    Example: CCS = SignalStrength × FrequencyStability × AtmosClarity requires
    all three factors in sql_expression.

11. CREATE DEDICATED CTEs FOR PER-ENTITY PRE-AGGREGATIONS.
    For each sub-formula that must be averaged or summed per entity GROUP before
    being used in an outer formula, create a dedicated CTE for that pre-aggregation
    and reference it by name in later CTEs. Never inline a per-entity aggregate
    directly into a join condition or outer SELECT — doing so produces wrong results
    because the aggregate runs at the wrong granularity.
    Example: if avg signal strength per observatory feeds a later formula, compute
    avg_signal_per_obs in its own CTE first, then join that CTE downstream.

# Output (initial extraction)
Use the `save_spec` tool to emit the structured spec. Do not output anything else.
"""


# ── Context loading ────────────────────────────────────────────────────────────

def load_context(db_dir: Path, db_name: str) -> str:
    db_path = db_dir / db_name
    parts = []

    schema_file = db_path / f"{db_name}_schema.txt"
    if schema_file.exists():
        parts.append(f"## Schema (DDL + sample rows)\n{schema_file.read_text()}")

    kb_file = db_path / f"{db_name}_kb.jsonl"
    if kb_file.exists():
        entries = []
        for line in kb_file.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                block = f"[id={e.get('id','?')} type={e.get('type','?')}] {e.get('knowledge','')}"
                if e.get("description"):
                    block += f"\n  Description: {e['description']}"
                if e.get("definition"):
                    block += f"\n  Definition: {e['definition']}"
                entries.append(block)
            except Exception:
                pass
        parts.append(f"## Knowledge Base ({len(entries)} entries)\n" + "\n\n".join(entries))

    cm_file = db_path / f"{db_name}_column_meaning_base.json"
    if cm_file.exists():
        try:
            cm = json.load(open(cm_file))
            lines = [f"  {k}: {v[:200] if isinstance(v,str) else json.dumps(v)[:200]}"
                     for k, v in cm.items()]
            parts.append(f"## Column Meanings\n" + "\n".join(lines))
        except Exception:
            pass

    return "\n\n".join(parts)


def build_user_message(context: str, question: str) -> str:
    return f"{context}\n\n## Task\n{question}"


# ── Spec extraction ────────────────────────────────────────────────────────────

def _livesql_helper_tools(docs_dir: Path) -> list[dict]:
    return [
        make_read_file_tool(docs_dir, suggest_for_sqlite=True),
        make_list_files_tool(docs_dir),
        make_sample_table_tool(),
        make_describe_table_tool(),
    ]


def _resolve_db_file(docs_dir: Path, db_name: str, task: dict) -> Path:
    """Find the actual SQLite file used by this task. Prefer task['db_path']
    if set; otherwise look for <db_name>_template.sqlite in docs_dir."""
    explicit = task.get("db_path")
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
    candidate = docs_dir / f"{db_name}_template.sqlite"
    if candidate.exists():
        return candidate
    # Fallback: any .sqlite in docs_dir.
    matches = list(docs_dir.glob("*.sqlite")) + list(docs_dir.glob("*.sqlite3")) + list(docs_dir.glob("*.db"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"No SQLite DB found for task in {docs_dir}")


def extract_spec_anthropic(
    model: str,
    context: str,
    question: str,
    task_id: str,
    docs_dir: Path,
    db_path: Path,
) -> tuple[dict, dict]:
    """Multi-shot extraction via Anthropic native tool_use. Returns (spec, session)."""
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    user_msg = build_user_message(context, question)
    spec, _usage, session, telem = run_anthropic_spec_loop(
        client=client,
        model=model,
        system=SYSTEM_PROMPT,
        user_prompt=user_msg,
        helper_tools=_livesql_helper_tools(docs_dir),
        save_spec_tool=SAVE_SPEC_TOOL,
        dispatch=make_livesql_dispatcher(docs_dir, db_path),
        max_tokens=4096,
    )
    if spec is None:
        raise ValueError(
            f"No save_spec call from spec_agent for {task_id} "
            f"(hit_cap={telem['hit_cap']}, tool_calls_before_save={telem['tool_calls_before_save']})"
        )
    return spec, session


# ── OpenAI-compatible providers (OpenRouter / Fireworks / Fireworks2) ─────────
#
# These all use OpenAI's chat completions schema with json_object response_format
# (no tool_use forcing). We embed the save_spec input_schema directly into the
# system prompt so the model knows the required shape.

def _extract_spec_openai_compat(
    base_url: str,
    api_key: str,
    api_key_env_name: str,
    model: str,
    context: str,
    question: str,
    task_id: str,
    docs_dir: Path,
    db_path: Path,
    provider_label: str,
    max_tokens: int = 16000,
) -> tuple[dict, dict]:
    """Generic OpenAI-compatible multi-shot spec extractor. Returns (spec, session)."""
    from openai import OpenAI
    if not api_key:
        raise SystemExit(f"{api_key_env_name} not in .env")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=180.0, max_retries=0)
    user_msg = build_user_message(context, question)
    spec, _usage, session, telem = run_openai_spec_loop(
        client=client,
        model=model,
        system=SYSTEM_PROMPT,
        user_prompt=user_msg,
        helper_tools=_livesql_helper_tools(docs_dir),
        save_spec_tool=SAVE_SPEC_TOOL,
        dispatch=make_livesql_dispatcher(docs_dir, db_path),
        provider_label=provider_label,
        max_tokens=max_tokens,
    )
    if spec is None:
        raise ValueError(
            f"No save_spec call from spec_agent for {task_id} "
            f"(hit_cap={telem['hit_cap']}, tool_calls_before_save={telem['tool_calls_before_save']})"
        )
    return spec, session


def extract_spec_openrouter(model, context, question, task_id, docs_dir, db_path):
    return _extract_spec_openai_compat(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ.get("OPENROUTER_API_KEY", ""),
        api_key_env_name="OPENROUTER_API_KEY",
        model=model, context=context, question=question, task_id=task_id,
        docs_dir=docs_dir, db_path=db_path,
        provider_label="openrouter",
    )


def extract_spec_fireworks(model, context, question, task_id, docs_dir, db_path):
    return _extract_spec_openai_compat(
        base_url="https://api.fireworks.ai/inference/v1",
        api_key=os.environ.get("FIREWORKS_API_KEY", ""),
        api_key_env_name="FIREWORKS_API_KEY",
        model=model, context=context, question=question, task_id=task_id,
        docs_dir=docs_dir, db_path=db_path,
        provider_label="fireworks",
    )


def extract_spec_fireworks2(model, context, question, task_id, docs_dir, db_path):
    return _extract_spec_openai_compat(
        base_url="https://api.fireworks.ai/inference/v1",
        api_key=os.environ.get("FIREWORKS_API_KEY2", ""),
        api_key_env_name="FIREWORKS_API_KEY2",
        model=model, context=context, question=question, task_id=task_id,
        docs_dir=docs_dir, db_path=db_path,
        provider_label="fireworks2",
    )


# ── Main ──────────────────────────────────────────────────────────────────────

print_lock = threading.Lock()


_PROVIDER_DISPATCH = {
    "anthropic":  extract_spec_anthropic,
    "openrouter": extract_spec_openrouter,
    "fireworks":  extract_spec_fireworks,
    "fireworks2": extract_spec_fireworks2,
}


def process_one(args_tuple):
    task, out_dir, db_dir, provider, model, overwrite = args_tuple
    tid          = task["task_id"]
    spec_path    = out_dir / f"{tid}.json"
    # Bug 8 fix: rename `<tid>.session.json` -> `<tid>.spec_session.json`
    # to match DABStep/Krama extractor conventions.
    session_path = out_dir / f"{tid}.spec_session.json"
    # Bug 8 fix: also write `<tid>.original.json` as an immutable snapshot of
    # the spec_agent's initial emission (mirrors DABStep/Krama extractors).
    original_path = out_dir / f"{tid}.original.json"

    if spec_path.exists() and not overwrite:
        with print_lock:
            print(f"  [skip] {tid}", flush=True)
        return "skip", tid, None

    db_name  = task.get("db_name") or task.get("selected_database", "")
    question = task["question"]
    docs_dir = db_dir / db_name
    t0 = time.time()
    try:
        context = load_context(db_dir, db_name)
        db_path = _resolve_db_file(docs_dir, db_name, task)
        extract_fn = _PROVIDER_DISPATCH[provider]
        spec, session = extract_fn(model, context, question, tid, docs_dir, db_path)
        # Stamp telemetry into spec._meta for downstream auditing.
        meta = (session.get("metadata") or {})
        spec.setdefault("_meta", {})
        spec["_meta"].update({
            "extractor": f"{provider}:{model}",
            "tool_calls_before_save": meta.get("tool_calls_before_save", 0),
            "hit_cap": meta.get("hit_cap", False),
            "forced_save": meta.get("forced_save", False),
        })
        spec_path.write_text(json.dumps(spec, indent=2))
        original_path.write_text(json.dumps(spec, indent=2))
        session_path.write_text(json.dumps(session, indent=2))
        elapsed = round(time.time() - t0, 1)
        n_tools = meta.get("tool_calls_before_save", 0)
        with print_lock:
            print(f"  [ok]   {tid} ({elapsed}s)  tables={spec.get('tables_needed',[])}  ctes={len(spec.get('cte_plan',[]))}  tools={n_tools}", flush=True)
        return "ok", tid, None
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        with print_lock:
            print(f"  [err]  {tid} ({elapsed}s): {e}", flush=True)
        return "err", tid, str(e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks",     required=True)
    parser.add_argument("--db-dir",    required=True)
    parser.add_argument("--extractor", default="anthropic:claude-sonnet-4-6")
    parser.add_argument("--out",       required=True)
    parser.add_argument("--workers",   type=int, default=5)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    db_dir  = Path(args.db_dir)

    provider, model = args.extractor.split(":", 1)
    if provider not in _PROVIDER_DISPATCH:
        print(
            f"Unknown extractor provider: {provider}. "
            f"Supported: {sorted(_PROVIDER_DISPATCH)}",
            file=sys.stderr,
        )
        sys.exit(1)

    tasks = [json.loads(l) for l in open(args.tasks) if l.strip()]
    print(f"Extracting specs for {len(tasks)} tasks with {args.workers} workers → {out_dir} "
          f"(provider={provider}, model={model})", flush=True)

    work = [(t, out_dir, db_dir, provider, model, args.overwrite) for t in tasks]
    counts = {"ok": 0, "err": 0, "skip": 0}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for status, tid, detail in pool.map(process_one, work):
            counts[status] += 1

    print(f"\nDone: {counts['ok']} ok / {counts['err']} errors / {counts['skip']} skipped")


if __name__ == "__main__":
    main()
