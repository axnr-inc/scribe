"""Direct PostgreSQL access for Sentinel eval (bypasses ConnectionService).

Uses PG_HOST / PG_PORT / PG_USER / PG_PASSWORD from sentinel-eval-sdk/.env.
Database name = app_name (e.g. eval_alien).

Set SENTINEL_SQL_BACKEND=psycopg2 in scribe/.env when ConnectionService is unreachable
but PostgreSQL is (common on VPN: PG works, ConnectionService may not, or vice versa).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SENTINEL = Path(os.environ.get("SENTINEL_SDK_PATH", _ROOT.parent / "sentinel-eval-sdk"))

try:
    from dotenv import load_dotenv
    load_dotenv(_SENTINEL / ".env", override=True)
    load_dotenv(_ROOT / ".env", override=False)
except ImportError:
    pass


def _valid_table_name(table_name: str) -> bool:
    return bool(table_name) and table_name.replace("_", "").replace(".", "").isalnum()


def _connect(db_name: str):
    import psycopg2
    return psycopg2.connect(
        host=os.environ["PG_HOST"],
        port=int(os.environ.get("PG_PORT", "5432")),
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASSWORD"],
        dbname=db_name,
        connect_timeout=int(os.environ.get("PG_CONNECT_TIMEOUT", "10")),
    )


def execute(app_name: str, sql: str, max_rows: int = 100) -> dict:
    """ConnectionService-compatible result shape."""
    try:
        import psycopg2.extras
        with _connect(app_name) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql)
                if cur.description is None:
                    return {"success": True, "columns": [], "rows": [], "rowCount": 0}
                rows = cur.fetchmany(max_rows)
                columns = [d.name for d in cur.description]
                out = [dict(r) for r in rows]
                return {
                    "success": True,
                    "columns": columns,
                    "rows": out,
                    "rowCount": len(out),
                }
    except Exception as e:
        return {"success": False, "message": str(e), "columns": [], "rows": [], "rowCount": 0}


def execute_df(app_name: str, sql: str, max_rows: int | None = 50000):
    import pandas as pd
    lim = f" LIMIT {max_rows}" if max_rows else ""
    clean = sql.rstrip().rstrip(";")
    if max_rows and not re.search(r"\blimit\b", clean, re.I):
        clean = f"{clean}{lim}"
    result = execute(app_name, clean, max_rows=max_rows or 50000)
    if not result.get("success"):
        raise RuntimeError(result.get("message", "Query failed"))
    return pd.DataFrame(result.get("rows") or [], columns=result.get("columns") or [])


def list_tables(app_name: str) -> list:
    result = execute(
        app_name,
        "SELECT table_schema AS schema, table_name AS \"tableName\", table_type AS \"tableType\" "
        "FROM information_schema.tables "
        "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') "
        "ORDER BY table_schema, table_name",
        max_rows=500,
    )
    if not result.get("success"):
        raise RuntimeError(result.get("message", "list_tables failed"))
    return result["rows"]


def sample_table(app_name: str, table_name: str, n: int = 10) -> str:
    if not _valid_table_name(table_name):
        return json.dumps({"error": f"invalid table_name: {table_name}"})
    safe_n = max(1, min(200, int(n or 10)))
    result = execute(app_name, f'SELECT * FROM "{table_name}" LIMIT {safe_n}', max_rows=safe_n)
    if not result.get("success"):
        return json.dumps({"error": result.get("message")})
    return json.dumps({
        "table": table_name,
        "limit_applied": safe_n,
        "row_count": len(result["rows"]),
        "rows": result["rows"],
    }, indent=2, default=str)


def describe_table(app_name: str, table_name: str) -> str:
    if not _valid_table_name(table_name):
        return json.dumps({"error": f"invalid table_name: {table_name}"})
    try:
        import psycopg2.extras
        with _connect(app_name) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND lower(table_name) = lower(%s) "
                    "ORDER BY ordinal_position",
                    (table_name,),
                )
                rows = [dict(r) for r in cur.fetchall()]
    except Exception as e:
        return json.dumps({"error": str(e)})
    if not rows:
        return json.dumps({"error": f"table '{table_name}' not found"})
    cols = [{"name": r["column_name"], "type": r["data_type"], "nullable": r["is_nullable"]} for r in rows]
    return json.dumps({"table": table_name, "columns": cols}, indent=2)
