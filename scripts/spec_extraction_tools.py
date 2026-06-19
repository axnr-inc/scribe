"""Shared tool surface + multi-shot driver for spec_agent extractors (P2b.1-3).

This module factors out the spec_agent's *enhanced* tool surface introduced by
P2b.1 (read_file) + P2b.2 (benchmark-specific samplers) + P2b.3 (multi-shot
reasoning loop). Each of the three extractor scripts (DABStep, LiveSQL, Krama)
imports from here so the loop pattern and tool semantics stay identical across
benchmarks.

Design notes:

- Tool surface is benchmark-specific (DABStep gets query_fees; LiveSQL gets
  sample_table + describe_table; Krama gets read_data_file). All three share
  read_file (P2b.1) and list_files. save_spec is always last.
- The multi-shot loop runs at most MAX_TOOL_TURNS=5 turns. After that we
  re-prompt the model with a forced-save instruction asking it to call
  save_spec immediately.
- Anthropic uses native tool_use; OpenAI-compat providers (OpenRouter,
  Fireworks, Fireworks2) use OpenAI-style function tools. The save_spec
  "tool" in OpenAI mode is also a function; the loop terminates when the
  model calls save_spec OR returns a final assistant message with no
  tool calls.
- READ_FILE_TRUNCATE matches src/harness/tools/ask_planner.ts.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Constants — match src/harness/tools/ask_planner.ts where relevant
# ---------------------------------------------------------------------------

READ_FILE_TRUNCATE = 250_000
MAX_TOOL_TURNS = 5  # tool-call turns BEFORE save_spec; cap per P2b.3 spec.

BINARY_EXTENSIONS = {
    ".xlsx", ".xls", ".parquet", ".pq",
    ".sqlite", ".sqlite3", ".db",
    ".gpkg", ".shp", ".dbf",
    ".npy", ".npz", ".pkl", ".pickle",
    ".zip", ".gz", ".tar", ".bz2", ".7z",
    ".png", ".jpg", ".jpeg", ".pdf",
    ".dat", ".sp3",
}

SQLITE_EXTENSIONS = {".sqlite", ".sqlite3", ".db"}


def _is_binary_ext(name: str) -> bool:
    return Path(name).suffix.lower() in BINARY_EXTENSIONS


def _is_sqlite_ext(name: str) -> bool:
    return Path(name).suffix.lower() in SQLITE_EXTENSIONS


# ---------------------------------------------------------------------------
# File manifest (used in read_file description so the LLM picks a real file)
# ---------------------------------------------------------------------------

DABSTEP_FILE_MANIFEST = """Files available via read_file(filename):

- manual.md (~6K tokens): Authoritative business reference. Defines
  fee-rule matching semantics (wildcard, specificity tiebreaker), the
  per-txn fee formula (fixed_amount + rate*eur_amount/10000), and ALL
  named metrics the task may reference (fraud_rate, settlement_volume,
  etc.). Read FIRST when verifying what a NAMED metric, formula, or
  convention in the question MEANS.

- fees.json (~50K tokens, ~1000 rule entries): One JSON object per fee
  rule. Schema per rule: {rule_id, card_scheme, account_type[list],
  merchant_category_code[list], is_credit, monthly_volume, intracountry,
  capture_delay, monthly_fraud_level, fixed_amount, rate}. Wildcards:
  null OR empty-list = "matches any value". When you need to enumerate
  rules matching specific filter criteria, prefer query_fees(filters)
  over scanning the file.

- merchant_data.json (~3K tokens): Per-merchant attributes used as txn
  context during rule matching: {merchant_name, account_type,
  capture_delay, mcc}. Read to look up a merchant's attributes before
  applying rules.

- payments-readme.md (~2K tokens): Column meanings and dtypes for the
  payments.csv transaction table. Read when interpreting raw txn fields
  or resolving "which column holds X?"."""


def _auto_list_manifest(docs_dir: Path, suggest_for_sqlite: bool = False) -> str:
    """Generic file manifest for non-DABStep extractors.

    suggest_for_sqlite: if True, sqlite-family files get a hint to use
    sample_table/describe_table instead of run_python.
    """
    if not docs_dir.exists():
        return f"(directory not found: {docs_dir})"
    lines: list[str] = [f"Files available via read_file(filename) in {docs_dir}:", ""]
    try:
        entries = sorted(p.name for p in docs_dir.iterdir() if not p.name.startswith("."))
    except OSError as e:
        return f"(unable to list {docs_dir}: {e})"
    if not entries:
        return f"(empty directory: {docs_dir})"
    for name in entries:
        fp = docs_dir / name
        try:
            if fp.is_dir():
                lines.append(f"- {name}/  (directory)")
                continue
            size_kb = max(1, fp.stat().st_size // 1024)
            tag = ""
            if _is_sqlite_ext(name):
                if suggest_for_sqlite:
                    tag = "  [BINARY — use sample_table / describe_table instead of read_file]"
                else:
                    tag = "  [BINARY — read_file will fail; ask the harness to load via run_sql]"
            elif _is_binary_ext(name):
                tag = "  [BINARY — read_file will fail; ask the harness to load via run_python or read_data_file]"
            lines.append(f"- {name}  (~{size_kb} KB){tag}")
        except OSError:
            lines.append(f"- {name}  (unreadable)")
    lines.append("")
    lines.append(
        "read_file returns plain text and cannot decode binary formats "
        "(xlsx, parquet, sqlite, geopackage, etc.) — those are flagged [BINARY] above."
    )
    return "\n".join(lines)


def make_file_manifest(docs_dir: Path, suggest_for_sqlite: bool = False) -> str:
    """Return a manifest string for the read_file tool description."""
    if (docs_dir / "manual.md").exists() and (docs_dir / "fees.json").exists():
        return DABSTEP_FILE_MANIFEST
    return _auto_list_manifest(docs_dir, suggest_for_sqlite=suggest_for_sqlite)


# ---------------------------------------------------------------------------
# Tool: read_file
# ---------------------------------------------------------------------------

def execute_read_file(filename: str, docs_dir: Path) -> str:
    allowed = docs_dir.resolve()
    target = (allowed / filename).resolve()
    try:
        target.relative_to(allowed)
    except ValueError:
        return f"Error: filename '{filename}' is outside the allowed docs directory."
    if not target.exists():
        return f"Error: file not found: {filename}"
    if _is_binary_ext(filename):
        ext = Path(filename).suffix.lower()
        if _is_sqlite_ext(filename):
            return (
                f"Error: '{filename}' is a SQLite database ({ext}) that read_file "
                f"cannot decode. Use sample_table(table_name) or describe_table(table_name) instead."
            )
        return (
            f"Error: '{filename}' is a binary format ({ext}) that read_file cannot decode. "
            f"Ask the harness to load it via run_python or use the benchmark sampler "
            f"(e.g. read_data_file for Krama)."
        )
    try:
        raw = target.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"Error reading {filename}: {e}"
    if len(raw) > READ_FILE_TRUNCATE:
        return raw[:READ_FILE_TRUNCATE] + f"\n\n[truncated at {READ_FILE_TRUNCATE} chars]"
    return raw


# ---------------------------------------------------------------------------
# Tool: list_files
# ---------------------------------------------------------------------------

def execute_list_files(docs_dir: Path) -> str:
    if not docs_dir.exists():
        return f"(directory not found: {docs_dir})"
    try:
        entries = sorted(p for p in docs_dir.iterdir() if not p.name.startswith("."))
    except OSError as e:
        return f"(unable to list {docs_dir}: {e})"
    if not entries:
        return f"(empty directory: {docs_dir})"
    out = [f"Files in {docs_dir}:"]
    for p in entries:
        try:
            if p.is_dir():
                out.append(f"- {p.name}/  (directory)")
            else:
                size_kb = max(1, p.stat().st_size // 1024)
                out.append(f"- {p.name}  (~{size_kb} KB)")
        except OSError:
            out.append(f"- {p.name}  (unreadable)")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Tool: query_fees (DABStep)
# ---------------------------------------------------------------------------

_fees_cache: dict[str, list[dict]] = {}


def _load_fees(docs_dir: Path) -> list[dict]:
    key = str(docs_dir.resolve())
    if key in _fees_cache:
        return _fees_cache[key]
    fees_path = docs_dir / "fees.json"
    if not fees_path.exists():
        raise FileNotFoundError(f"fees.json not found at {fees_path}")
    data = json.loads(fees_path.read_text())
    _fees_cache[key] = data
    return data


def _rule_field_matches(rule_val: Any, query_val: Any) -> bool:
    """Wildcard semantics matching ask_planner.ts:ruleFieldMatches.
    null/undefined → always matches; empty list → always matches.
    """
    if rule_val is None:
        return True
    if isinstance(rule_val, list):
        if len(rule_val) == 0:
            return True
        return query_val in rule_val
    return rule_val == query_val


def execute_query_fees(filters: dict, limit: int, docs_dir: Path) -> str:
    try:
        fees = _load_fees(docs_dir)
    except Exception as e:
        return f"Error loading fees.json: {e}"
    safe_limit = max(1, min(1000, int(limit or 50)))
    matches: list[dict] = []
    filter_items = list((filters or {}).items())
    for rule in fees:
        ok = True
        for k, v in filter_items:
            if not _rule_field_matches(rule.get(k), v):
                ok = False
                break
        if ok:
            matches.append(rule)
            if len(matches) >= safe_limit:
                break
    return json.dumps({
        "matched_count": len(matches),
        "total_rules_searched": len(fees),
        "limit_applied": safe_limit,
        "rules": matches,
    }, indent=2)


# ---------------------------------------------------------------------------
# Tool: sample_table + describe_table (LiveSQL)
# ---------------------------------------------------------------------------

def _open_sqlite(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite DB not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def execute_sample_table(table_name: str, n: int, db_path: Path) -> str:
    if not table_name or not table_name.replace("_", "").replace(".", "").isalnum():
        return f"Error: invalid table_name '{table_name}'. Use a bare identifier."
    safe_n = max(1, min(200, int(n or 10)))
    try:
        conn = _open_sqlite(db_path)
    except Exception as e:
        return f"Error opening DB: {e}"
    try:
        cur = conn.execute(f"SELECT * FROM {table_name} LIMIT {safe_n}")
        rows = [dict(r) for r in cur.fetchall()]
        return json.dumps({
            "table": table_name,
            "limit_applied": safe_n,
            "row_count": len(rows),
            "rows": rows,
        }, indent=2, default=str)
    except sqlite3.Error as e:
        return f"Error sampling {table_name}: {e}"
    finally:
        conn.close()


def execute_describe_table(table_name: str, db_path: Path) -> str:
    if not table_name or not table_name.replace("_", "").replace(".", "").isalnum():
        return f"Error: invalid table_name '{table_name}'. Use a bare identifier."
    try:
        conn = _open_sqlite(db_path)
    except Exception as e:
        return f"Error opening DB: {e}"
    try:
        cur = conn.execute(f"PRAGMA table_info({table_name})")
        cols = [
            {"cid": r["cid"], "name": r["name"], "type": r["type"],
             "notnull": bool(r["notnull"]), "pk": bool(r["pk"])}
            for r in cur.fetchall()
        ]
        if not cols:
            return f"Error: table '{table_name}' not found or has no columns."
        return json.dumps({"table": table_name, "columns": cols}, indent=2)
    except sqlite3.Error as e:
        return f"Error describing {table_name}: {e}"
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tool: read_data_file (Krama) — multi-format sampler
# ---------------------------------------------------------------------------

def execute_read_data_file(rel_path: str, n_rows: int, context_dir: Path) -> str:
    allowed = context_dir.resolve()
    target = (allowed / rel_path).resolve()
    try:
        target.relative_to(allowed)
    except ValueError:
        return f"Error: path '{rel_path}' is outside the allowed context_dir."
    if not target.exists():
        return f"Error: file not found: {rel_path}"
    safe_n = max(1, min(200, int(n_rows or 15)))
    ext = target.suffix.lower()
    try:
        if ext == ".csv":
            import pandas as pd
            df = pd.read_csv(target, nrows=safe_n, low_memory=False)
            return (
                f"shape (head): {df.shape}; columns: {list(df.columns)}\n"
                f"dtypes:\n{df.dtypes.to_string()}\n"
                f"head:\n{df.to_string(index=False)}\n"
            )
        if ext in (".xlsx", ".xls"):
            import pandas as pd
            xls = pd.ExcelFile(target)
            out = [f"sheets: {xls.sheet_names}"]
            for sn in xls.sheet_names[:3]:
                try:
                    df = pd.read_excel(target, sheet_name=sn, nrows=safe_n)
                    out.append(f"--- sheet '{sn}' ---")
                    out.append(f"shape (head): {df.shape}; columns: {list(df.columns)[:20]}")
                    out.append(f"head:\n{df.head(safe_n).to_string(index=False)}")
                except Exception as e:
                    out.append(f"--- sheet '{sn}' (error: {e}) ---")
            return "\n".join(out)
        if ext == ".json":
            raw = target.read_text(encoding="utf-8", errors="replace")
            return f"head (4000 chars):\n{raw[:4000]}"
        if ext in (".txt", ".md", ".tsv"):
            raw = target.read_text(encoding="utf-8", errors="replace")
            return f"head (4000 chars):\n{raw[:4000]}"
        if ext in (".parquet", ".pq"):
            import pandas as pd
            df = pd.read_parquet(target)
            head = df.head(safe_n)
            return (
                f"shape (full): {df.shape}; columns: {list(df.columns)}\n"
                f"dtypes:\n{df.dtypes.to_string()}\n"
                f"head:\n{head.to_string(index=False)}\n"
            )
        return f"(no sampler for extension '{ext}' — file size {target.stat().st_size} bytes)"
    except Exception as e:
        return f"(unable to sample {rel_path}: {e})"


# ---------------------------------------------------------------------------
# Tool spec factories (Anthropic shape)
# ---------------------------------------------------------------------------

def make_read_file_tool(docs_dir: Path, suggest_for_sqlite: bool = False) -> dict:
    return {
        "name": "read_file",
        "description": (
            f"Re-read a source document from this task's docs directory ({docs_dir}).\n\n"
            + make_file_manifest(docs_dir, suggest_for_sqlite=suggest_for_sqlite)
            + f"\n\nReturns plain text, truncated to {READ_FILE_TRUNCATE} chars."
        ),
        "input_schema": {
            "type": "object",
            "required": ["filename"],
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "File name in the docs directory. See manifest above.",
                },
            },
        },
    }


def make_list_files_tool(docs_dir: Path) -> dict:
    return {
        "name": "list_files",
        "description": (
            f"List every file in this task's docs directory ({docs_dir}). "
            "Call this if you're unsure what's available before deciding which "
            "files to read or sample."
        ),
        "input_schema": {"type": "object", "properties": {}},
    }


def make_query_fees_tool() -> dict:
    return {
        "name": "query_fees",
        "description": (
            "Programmatic lookup over fees.json with correct wildcard semantics "
            "(null OR empty-list = matches any value). Pass a subset of rule fields "
            "as filters; returns the list of matching rules. Use this instead of "
            "scanning fees.json by eye when you need to enumerate applicable rules "
            "for a specific transaction context."
        ),
        "input_schema": {
            "type": "object",
            "required": ["filters"],
            "properties": {
                "filters": {
                    "type": "object",
                    "description": (
                        "Filter dict. Any subset of: card_scheme (str), account_type (str), "
                        "merchant_category_code (int), is_credit (bool), monthly_volume (str), "
                        "intracountry (bool), capture_delay (str), monthly_fraud_level (str)."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rules to return (default 50; max 1000).",
                },
            },
        },
    }


def make_sample_table_tool() -> dict:
    return {
        "name": "sample_table",
        "description": (
            "Sample rows from a table in this task's SQLite database. Returns "
            "the first n rows as JSON. Use to verify column meanings, JSON-column "
            "shapes (e.g. confirm `$.field` exists), and value distributions BEFORE "
            "committing a CTE plan."
        ),
        "input_schema": {
            "type": "object",
            "required": ["table_name"],
            "properties": {
                "table_name": {"type": "string"},
                "n": {"type": "integer", "description": "Rows to return (default 10; max 200)."},
            },
        },
    }


def make_describe_table_tool() -> dict:
    return {
        "name": "describe_table",
        "description": (
            "Return column names + SQLite types for a table in this task's database. "
            "Use to verify the exact column casing and types referenced in your spec."
        ),
        "input_schema": {
            "type": "object",
            "required": ["table_name"],
            "properties": {
                "table_name": {"type": "string"},
            },
        },
    }


def make_read_data_file_tool() -> dict:
    return {
        "name": "read_data_file",
        "description": (
            "Sample a data file from this task's context_dir. Supports CSV, XLSX, "
            "JSON, TXT/MD/TSV, Parquet. Returns shape, columns, dtypes, and the "
            "first n_rows. Use to verify column names and value distributions "
            "BEFORE committing a computation_plan."
        ),
        "input_schema": {
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to the task's context_dir (e.g. 'climateMeasurements.xlsx').",
                },
                "n_rows": {
                    "type": "integer",
                    "description": "Rows to return (default 15; max 200).",
                },
            },
        },
    }


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

ToolExecutor = Callable[[str, dict], str]


def make_dabstep_dispatcher(docs_dir: Path) -> ToolExecutor:
    def dispatch(name: str, args: dict) -> str:
        if name == "read_file":
            return execute_read_file(str(args.get("filename", "")), docs_dir)
        if name == "list_files":
            return execute_list_files(docs_dir)
        if name == "query_fees":
            return execute_query_fees(args.get("filters") or {}, int(args.get("limit") or 50), docs_dir)
        return f"Error: unsupported tool '{name}'."
    return dispatch


def make_livesql_dispatcher(docs_dir: Path, db_path: Path) -> ToolExecutor:
    def dispatch(name: str, args: dict) -> str:
        if name == "read_file":
            return execute_read_file(str(args.get("filename", "")), docs_dir)
        if name == "list_files":
            return execute_list_files(docs_dir)
        if name == "sample_table":
            return execute_sample_table(str(args.get("table_name", "")), int(args.get("n") or 10), db_path)
        if name == "describe_table":
            return execute_describe_table(str(args.get("table_name", "")), db_path)
        return f"Error: unsupported tool '{name}'."
    return dispatch


def _valid_table_name(table_name: str) -> bool:
    return bool(table_name) and table_name.replace("_", "").replace(".", "").isalnum()


def _get_sentinel_executor(sdk_path: Path):
    import sys
    sdk = str(sdk_path.resolve())
    if sdk not in sys.path:
        sys.path.insert(0, sdk)
    from sql_executor import EvalSQLExecutor  # noqa: WPS433
    return EvalSQLExecutor()


def _sentinel_sql_backend() -> str:
    return os.environ.get("SENTINEL_SQL_BACKEND", "connection_service").strip().lower()


def _scribe_context_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "context"


def execute_sentinel_sample_table(table_name: str, n: int, app_name: str, sdk_path: Path) -> str:
    if not _valid_table_name(table_name):
        return f"Error: invalid table_name '{table_name}'. Use a bare identifier."
    if _sentinel_sql_backend() == "psycopg2":
        import sys
        ctx = str(_scribe_context_dir())
        if ctx not in sys.path:
            sys.path.insert(0, ctx)
        from sentinel_sql import sample_table  # noqa: WPS433
        return sample_table(app_name, table_name, n)
    safe_n = max(1, min(200, int(n or 10)))
    try:
        executor = _get_sentinel_executor(sdk_path)
        result = executor.execute(app_name, f'SELECT * FROM "{table_name}" LIMIT {safe_n}', max_rows=safe_n)
        if not result.get("success"):
            return f"Error sampling {table_name}: {result.get('message', 'query failed')}"
        rows = result.get("rows", [])
        return json.dumps({
            "table": table_name,
            "limit_applied": safe_n,
            "row_count": len(rows),
            "rows": rows,
        }, indent=2, default=str)
    except Exception as e:
        return f"Error sampling {table_name}: {e}"


def execute_sentinel_describe_table(table_name: str, app_name: str, sdk_path: Path) -> str:
    if not _valid_table_name(table_name):
        return f"Error: invalid table_name '{table_name}'. Use a bare identifier."
    if _sentinel_sql_backend() == "psycopg2":
        import sys
        ctx = str(_scribe_context_dir())
        if ctx not in sys.path:
            sys.path.insert(0, ctx)
        from sentinel_sql import describe_table  # noqa: WPS433
        return describe_table(app_name, table_name)
    sql = (
        "SELECT column_name, data_type, is_nullable "
        "FROM information_schema.columns "
        f"WHERE table_schema = 'public' AND lower(table_name) = lower('{table_name}') "
        "ORDER BY ordinal_position"
    )
    try:
        executor = _get_sentinel_executor(sdk_path)
        result = executor.execute(app_name, sql, max_rows=500)
        if not result.get("success"):
            return f"Error describing {table_name}: {result.get('message', 'query failed')}"
        rows = result.get("rows", [])
        if not rows:
            return f"Error: table '{table_name}' not found or has no columns."
        cols = [
            {"name": r.get("column_name"), "type": r.get("data_type"),
             "nullable": r.get("is_nullable")}
            for r in rows
        ]
        return json.dumps({"table": table_name, "columns": cols}, indent=2)
    except Exception as e:
        return f"Error describing {table_name}: {e}"


def execute_sentinel_list_tables(app_name: str, sdk_path: Path) -> str:
    if _sentinel_sql_backend() == "psycopg2":
        import sys
        ctx = str(_scribe_context_dir())
        if ctx not in sys.path:
            sys.path.insert(0, ctx)
        from sentinel_sql import list_tables  # noqa: WPS433
        try:
            tables = list_tables(app_name)
            return json.dumps({"app_name": app_name, "tables": tables}, indent=2, default=str)
        except Exception as e:
            return f"Error listing tables: {e}"
    try:
        executor = _get_sentinel_executor(sdk_path)
        tables = executor.list_tables(app_name)
        return json.dumps({"app_name": app_name, "tables": tables}, indent=2, default=str)
    except Exception as e:
        return f"Error listing tables: {e}"


def make_sentinel_sample_table_tool() -> dict:
    return {
        "name": "sample_table",
        "description": (
            "Sample rows from a table in this task's PostgreSQL database (Sentinel eval). "
            "Returns the first n rows as JSON. Use to verify column meanings and value "
            "distributions BEFORE committing a CTE plan."
        ),
        "input_schema": {
            "type": "object",
            "required": ["table_name"],
            "properties": {
                "table_name": {"type": "string"},
                "n": {"type": "integer", "description": "Rows to return (default 10; max 200)."},
            },
        },
    }


def make_sentinel_describe_table_tool() -> dict:
    return {
        "name": "describe_table",
        "description": (
            "Return column names + PostgreSQL types for a table via information_schema. "
            "Use to verify exact column casing and types referenced in your spec."
        ),
        "input_schema": {
            "type": "object",
            "required": ["table_name"],
            "properties": {
                "table_name": {"type": "string"},
            },
        },
    }


def make_sentinel_list_tables_tool() -> dict:
    return {
        "name": "list_tables",
        "description": (
            "List all tables in this task's PostgreSQL database. "
            "Returns schema, tableName, and tableType for each table."
        ),
        "input_schema": {"type": "object", "properties": {}},
    }


def make_sentinel_dispatcher(docs_dir: Path, app_name: str, sdk_path: Path) -> ToolExecutor:
    def dispatch(name: str, args: dict) -> str:
        if name == "read_file":
            return execute_read_file(str(args.get("filename", "")), docs_dir)
        if name == "list_files":
            return execute_list_files(docs_dir)
        if name == "sample_table":
            return execute_sentinel_sample_table(
                str(args.get("table_name", "")), int(args.get("n") or 10), app_name, sdk_path,
            )
        if name == "describe_table":
            return execute_sentinel_describe_table(str(args.get("table_name", "")), app_name, sdk_path)
        if name == "list_tables":
            return execute_sentinel_list_tables(app_name, sdk_path)
        return f"Error: unsupported tool '{name}'."
    return dispatch


def make_krama_dispatcher(context_dir: Path) -> ToolExecutor:
    def dispatch(name: str, args: dict) -> str:
        if name == "read_file":
            return execute_read_file(str(args.get("filename", "")), context_dir)
        if name == "list_files":
            return execute_list_files(context_dir)
        if name == "read_data_file":
            return execute_read_data_file(
                str(args.get("path", "")), int(args.get("n_rows") or 15), context_dir
            )
        return f"Error: unsupported tool '{name}'."
    return dispatch


# ---------------------------------------------------------------------------
# Multi-shot loop: Anthropic native tool_use
# ---------------------------------------------------------------------------

def run_anthropic_spec_loop(
    *,
    client,
    model: str,
    system: str,
    user_prompt: str,
    helper_tools: list[dict],
    save_spec_tool: dict,
    dispatch: ToolExecutor,
    max_tokens: int = 8000,
    max_tool_turns: int = MAX_TOOL_TURNS,
) -> tuple[Optional[dict], dict, dict, dict]:
    """Drive a multi-shot extraction with Anthropic until save_spec is called or
    the tool-turn cap is hit.

    Returns (spec_dict_or_None, usage_dict, session_dict, telemetry_dict).
    telemetry has:
      - tool_calls_before_save: int
      - tool_call_log: list[{turn, name}]
      - hit_cap: bool
      - forced_save: bool
    """
    tools = list(helper_tools) + [save_spec_tool]
    messages: list[dict] = [{"role": "user", "content": user_prompt}]
    total_input = 0
    total_output = 0
    tool_call_log: list[dict] = []
    spec: Optional[dict] = None
    hit_cap = False
    forced_save = False

    for turn in range(max_tool_turns + 1):
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=messages,
        )
        total_input += resp.usage.input_tokens
        total_output += resp.usage.output_tokens

        blocks = [b.model_dump() for b in resp.content]
        messages.append({"role": "assistant", "content": blocks})

        tool_uses = [b for b in blocks if b.get("type") == "tool_use"]

        # Did the model call save_spec? If so, we're done.
        save_calls = [b for b in tool_uses if b.get("name") == "save_spec"]
        if save_calls:
            spec = save_calls[0].get("input")
            # Synthesise tool_result blocks for every tool_use so session is valid for resume.
            tool_results = [
                {
                    "type": "tool_result",
                    "tool_use_id": b["id"],
                    "content": "Spec saved." if b.get("name") == "save_spec"
                               else dispatch(b.get("name", ""), b.get("input") or {}),
                }
                for b in tool_uses
            ]
            messages.append({"role": "user", "content": tool_results})
            for b in tool_uses:
                tool_call_log.append({"turn": turn, "name": b.get("name")})
            break

        if not tool_uses:
            # No tool calls, no save_spec — model returned bare text. Nudge once.
            if turn >= max_tool_turns:
                hit_cap = True
                break
            messages.append({
                "role": "user",
                "content": (
                    "You returned text without calling any tool. "
                    "Either call a helper tool to gather more evidence, "
                    "OR call save_spec NOW with the final spec."
                ),
            })
            continue

        # Helper tools called — dispatch and feed results.
        tool_results: list[dict] = []
        for b in tool_uses:
            name = b.get("name", "")
            args = b.get("input") or {}
            result = dispatch(name, args)
            tool_call_log.append({"turn": turn, "name": name})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": b["id"],
                "content": result,
            })
        messages.append({"role": "user", "content": tool_results})

        if turn == max_tool_turns - 1:
            # One more turn allowed — force save_spec on next call.
            messages.append({
                "role": "user",
                "content": (
                    "You have ONE more turn. Call save_spec NOW with your best "
                    "spec. Do not call any other helper tool."
                ),
            })
            forced_save = True

    # If we ran out of turns without a save_spec call, do a final forced attempt.
    if spec is None and not hit_cap:
        hit_cap = True

    if spec is None:
        # Last-chance forced save: append a strong instruction and re-call once
        # with only save_spec in tools.
        try:
            messages.append({
                "role": "user",
                "content": (
                    "Tool-turn cap reached. Call save_spec NOW with your best "
                    "current spec. Do not call any other tool."
                ),
            })
            forced_save = True
            # Forced tool_choice is incompatible with extended/adaptive thinking
            # (the API 400s). Disable thinking on this final forced call so the
            # model is compelled to emit the save_spec tool_use.
            _force_kwargs = dict(
                model=model,
                max_tokens=max_tokens,
                system=system,
                tools=[save_spec_tool],
                tool_choice={"type": "tool", "name": "save_spec"},
                messages=messages,
            )
            try:
                final_resp = client.messages.create(
                    thinking={"type": "disabled"}, **_force_kwargs
                )
            except Exception:
                # Older models without a thinking param: retry without it.
                final_resp = client.messages.create(**_force_kwargs)
            total_input += final_resp.usage.input_tokens
            total_output += final_resp.usage.output_tokens
            blocks = [b.model_dump() for b in final_resp.content]
            messages.append({"role": "assistant", "content": blocks})
            for b in blocks:
                if b.get("type") == "tool_use" and b.get("name") == "save_spec":
                    spec = b.get("input")
                    messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": b["id"],
                            "content": "Spec saved.",
                        }],
                    })
                    break
        except Exception:
            pass

    n_tools_before_save = sum(1 for c in tool_call_log if c["name"] != "save_spec")
    usage = {"input_tokens": total_input, "output_tokens": total_output}
    session = {
        "provider": "anthropic",
        "model": model,
        "system": system,
        "tools": tools,
        "messages": messages,
        "metadata": {
            "tool_calls_before_save": n_tools_before_save,
            "tool_call_log": tool_call_log,
            "hit_cap": hit_cap,
            "forced_save": forced_save,
        },
    }
    telemetry = {
        "tool_calls_before_save": n_tools_before_save,
        "tool_call_log": tool_call_log,
        "hit_cap": hit_cap,
        "forced_save": forced_save,
    }
    return spec, usage, session, telemetry


# ---------------------------------------------------------------------------
# Multi-shot loop: OpenAI-compat (OpenRouter / Fireworks / Fireworks2)
# ---------------------------------------------------------------------------

def _to_openai_tool(t: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }


def run_openai_spec_loop(
    *,
    client,
    model: str,
    system: str,
    user_prompt: str,
    helper_tools: list[dict],
    save_spec_tool: dict,
    dispatch: ToolExecutor,
    provider_label: str,
    max_tokens: int = 16000,
    max_tool_turns: int = MAX_TOOL_TURNS,
) -> tuple[Optional[dict], dict, dict, dict]:
    """OpenAI-compat multi-shot loop using function-calling tools. Loop stops
    when the model calls save_spec OR hits the turn cap.
    """
    oa_tools = [_to_openai_tool(t) for t in (helper_tools + [save_spec_tool])]
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]
    total_input = 0
    total_output = 0
    tool_call_log: list[dict] = []
    spec: Optional[dict] = None
    hit_cap = False
    forced_save = False

    for turn in range(max_tool_turns + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                tools=oa_tools,
            )
        except Exception as e:
            raise RuntimeError(f"{provider_label} API error on turn {turn}: {e}")

        usage = getattr(resp, "usage", None)
        if usage is not None:
            total_input += getattr(usage, "prompt_tokens", 0) or 0
            total_output += getattr(usage, "completion_tokens", 0) or 0

        msg = resp.choices[0].message
        # Persist assistant turn as a dict the OpenAI SDK can serialise on resume.
        assistant_dict: dict = {"role": "assistant"}
        if getattr(msg, "content", None):
            assistant_dict["content"] = msg.content
        else:
            assistant_dict["content"] = None
        if getattr(msg, "tool_calls", None):
            assistant_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant_dict)

        tool_calls = getattr(msg, "tool_calls", None) or []

        # Look for save_spec.
        save_call = next((tc for tc in tool_calls if tc.function.name == "save_spec"), None)
        if save_call is not None:
            try:
                spec = json.loads(save_call.function.arguments or "{}")
            except Exception as e:
                spec = None
                last_err = f"save_spec arguments parse error: {e}"
            # Emit tool messages for ALL tool_calls (OpenAI requires one per id).
            for tc in tool_calls:
                if tc.function.name == "save_spec":
                    content = "Spec saved." if spec is not None else "Error: invalid JSON in save_spec arguments."
                else:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except Exception:
                        args = {}
                    content = dispatch(tc.function.name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": content,
                })
                tool_call_log.append({"turn": turn, "name": tc.function.name})
            if spec is not None:
                break

        if not tool_calls:
            # Bare text. If content looks like a JSON object matching the schema,
            # accept it as a fallback (some models prefer text JSON over tools).
            content = (msg.content or "").strip()
            parsed_fallback = None
            if content.startswith("{"):
                try:
                    parsed_fallback = json.loads(content)
                except Exception:
                    parsed_fallback = None
            if parsed_fallback is not None and isinstance(parsed_fallback, dict):
                spec = parsed_fallback
                forced_save = True
                break
            if turn >= max_tool_turns:
                hit_cap = True
                break
            messages.append({
                "role": "user",
                "content": (
                    "You returned text without calling any tool. "
                    "Either call a helper tool to gather more evidence, "
                    "OR call save_spec NOW with the final spec."
                ),
            })
            continue

        # Helper tools only — dispatch each and feed results.
        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            result = dispatch(name, args)
            tool_call_log.append({"turn": turn, "name": name})
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        if turn == max_tool_turns - 1:
            messages.append({
                "role": "user",
                "content": (
                    "You have ONE more turn. Call save_spec NOW with your best "
                    "spec. Do not call any other helper tool."
                ),
            })
            forced_save = True

    # Forced final attempt if we never got a save_spec.
    if spec is None:
        hit_cap = True
        try:
            messages.append({
                "role": "user",
                "content": (
                    "Tool-turn cap reached. Call save_spec NOW with your best "
                    "current spec. Do not call any other tool."
                ),
            })
            forced_save = True
            final_resp = client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=messages,
                tools=[_to_openai_tool(save_spec_tool)],
                tool_choice={"type": "function", "function": {"name": "save_spec"}},
            )
            usage = getattr(final_resp, "usage", None)
            if usage is not None:
                total_input += getattr(usage, "prompt_tokens", 0) or 0
                total_output += getattr(usage, "completion_tokens", 0) or 0
            msg = final_resp.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []
            assistant_dict = {"role": "assistant", "content": msg.content or None}
            if tool_calls:
                assistant_dict["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ]
            messages.append(assistant_dict)
            for tc in tool_calls:
                if tc.function.name == "save_spec":
                    try:
                        spec = json.loads(tc.function.arguments or "{}")
                    except Exception:
                        spec = None
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "Spec saved." if spec is not None else "Error: invalid JSON.",
                    })
                    if spec is not None:
                        break
        except Exception:
            pass

    n_tools_before_save = sum(1 for c in tool_call_log if c["name"] != "save_spec")
    usage_dict = {"input_tokens": total_input, "output_tokens": total_output}
    session = {
        "provider": provider_label,
        "model": model,
        "system": system,
        "tools": oa_tools,
        "messages": messages,
        "metadata": {
            "tool_calls_before_save": n_tools_before_save,
            "tool_call_log": tool_call_log,
            "hit_cap": hit_cap,
            "forced_save": forced_save,
        },
    }
    telemetry = {
        "tool_calls_before_save": n_tools_before_save,
        "tool_call_log": tool_call_log,
        "hit_cap": hit_cap,
        "forced_save": forced_save,
    }
    return spec, usage_dict, session, telemetry
