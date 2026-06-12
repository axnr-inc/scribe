"""DataAgentBench paradigm-level SQL helpers.

Each DAB task's workspace contains one or more database files / connections:
  - SQLite (.db file)
  - DuckDB (.db or .duckdb file)
  - Postgres (seeded into the local cluster by scripts/seed_dab_dbs.py)
  - Mongo   (seeded into the local cluster by scripts/seed_dab_dbs.py)

The executor's Python REPL auto-loads these helpers via the preamble. The
DAB-recommended pattern is to query DBs directly (not load everything into
pandas). These helpers cut the boilerplate.

Postgres + Mongo connection convention matches scripts/seed_dab_dbs.py:
  PG_HOST=127.0.0.1 PG_PORT=5432 PG_USER=$USER PG_PASSWORD=''
  MONGO_URI=mongodb://localhost:27017
Override via environment variables.

Helpers:
  - open_sqlite(path):  sqlite3.Connection with row_factory=Row
  - open_duckdb(path):  duckdb.DuckDBPyConnection read-only
  - open_postgres(db_name): psycopg.Connection
  - open_mongo(db_name):    pymongo Database
  - list_tables_sqlite(conn) / _duckdb(conn) / _postgres(conn)
  - describe_*(conn, table)
  - sqlite_sample(conn, table, n) / duckdb_sample / postgres_sample
"""
from __future__ import annotations

import os
import sqlite3
from typing import Any

import duckdb


def open_sqlite(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def open_duckdb(path: str):
    """Open a DuckDB file read-only.

    DAB ships some DBs as `.db` (SQLite) and others as `.db` / `.duckdb` (DuckDB).
    If you're unsure, try open_sqlite first; on failure, fall back to open_duckdb.
    """
    return duckdb.connect(path, read_only=True)


def list_tables_sqlite(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    return [r[0] for r in cur.fetchall()]


def list_tables_duckdb(conn) -> list[str]:
    rows = conn.execute("SHOW TABLES").fetchall()
    return [r[0] for r in rows]


def describe_sqlite(conn: sqlite3.Connection, table: str) -> list[dict]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return [{"name": r[1], "type": r[2], "notnull": r[3], "pk": r[5]}
            for r in cur.fetchall()]


def describe_duckdb(conn, table: str) -> list[dict]:
    rows = conn.execute(f"DESCRIBE {table}").fetchall()
    return [{"name": r[0], "type": r[1], "null": r[2]} for r in rows]


def sqlite_sample(conn: sqlite3.Connection, table: str, n: int = 5) -> list[dict]:
    cur = conn.execute(f'SELECT * FROM "{table}" LIMIT {int(n)}')
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def duckdb_sample(conn, table: str, n: int = 5) -> list[dict]:
    rows = conn.execute(f'SELECT * FROM "{table}" LIMIT {int(n)}').fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, row)) for row in rows]


# ---------------------------------------------------------------------------
# Postgres helpers (seeded by scripts/seed_dab_dbs.py)
# ---------------------------------------------------------------------------

PG_HOST = os.environ.get("PG_HOST", "127.0.0.1")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_USER = os.environ.get("PG_USER", os.environ.get("USER", "postgres"))
PG_PASSWORD = os.environ.get("PG_PASSWORD", "")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")


def open_postgres(db_name: str):
    """Open a Postgres connection to a DAB-seeded DB. Returns psycopg.Connection."""
    import psycopg
    return psycopg.connect(
        host=PG_HOST, port=PG_PORT, user=PG_USER,
        password=PG_PASSWORD or None, dbname=db_name,
    )


def list_tables_postgres(conn) -> list[str]:
    cur = conn.execute(
        "SELECT table_schema || '.' || table_name FROM information_schema.tables "
        "WHERE table_schema NOT IN ('pg_catalog','information_schema') ORDER BY 1"
    )
    return [r[0] for r in cur.fetchall()]


def describe_postgres(conn, table: str) -> list[dict]:
    if "." in table:
        schema, t = table.split(".", 1)
    else:
        schema, t = "public", table
    cur = conn.execute(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position",
        (schema, t),
    )
    return [{"name": r[0], "type": r[1], "nullable": r[2]} for r in cur.fetchall()]


def postgres_sample(conn, table: str, n: int = 5) -> list[dict]:
    if "." in table:
        schema, t = table.split(".", 1)
    else:
        schema, t = "public", table
    cur = conn.execute(f'SELECT * FROM "{schema}"."{t}" LIMIT {int(n)}')
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# MongoDB helpers (seeded by scripts/seed_dab_dbs.py)
# ---------------------------------------------------------------------------

def open_mongo(db_name: str):
    """Open a Mongo client and return the DAB-seeded Database object."""
    from pymongo import MongoClient
    client = MongoClient(MONGO_URI)
    return client[db_name]


def list_collections_mongo(db) -> list[str]:
    return sorted(db.list_collection_names())


def mongo_sample(db, collection: str, n: int = 5) -> list[dict]:
    return list(db[collection].find().limit(int(n)))
