#!/usr/bin/env python3
"""Check which Sentinel SQL backends are reachable from this machine."""
from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SENTINEL = Path(os.environ.get("SENTINEL_SDK_PATH", ROOT.parent / "sentinel-eval-sdk"))

from dotenv import load_dotenv
# Staging/prod switches in sentinel .env must win over stale shell exports.
load_dotenv(SENTINEL / ".env", override=True)
load_dotenv(ROOT / ".env", override=False)


def tcp_probe(host: str, port: int, timeout: float = 3.0) -> bool:
    if not host:
        return False
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def main() -> int:
    cs_url = os.getenv("CONNECTION_SERVICE_URL", "")
    cs_host = cs_url.replace("http://", "").replace("https://", "").split(":")[0] if cs_url else ""
    pg_host = os.getenv("PG_HOST", "")
    pg_port = int(os.getenv("PG_PORT", "5432"))

    print("Sentinel connectivity check")
    print(f"  sentinel root: {SENTINEL}")
    print(f"  CONNECTION_SERVICE_URL: {cs_url or '(not set)'}")
    print(f"  PG_HOST: {pg_host or '(not set)'}:{pg_port}")
    print()

    cs_ok = tcp_probe(cs_host, 8080) if cs_host else False
    pg_ok = tcp_probe(pg_host, pg_port) if pg_host else False

    print(f"  ConnectionService ({cs_host}:8080): {'OK' if cs_ok else 'UNREACHABLE'}")
    print(f"  PostgreSQL      ({pg_host}:{pg_port}): {'OK' if pg_ok else 'UNREACHABLE'}")
    print()

    if cs_ok:
        sys.path.insert(0, str(SENTINEL))
        try:
            from sql_executor import EvalSQLExecutor
            tables = EvalSQLExecutor().list_tables("eval_alien")
            print(f"  ConnectionService list_tables(eval_alien): OK ({len(tables)} tables)")
        except Exception as e:
            print(f"  ConnectionService list_tables: FAILED — {e}")
            cs_ok = False

    if pg_ok:
        try:
            sys.path.insert(0, str(ROOT / "data" / "context"))
            from sentinel_sql import list_tables
            tables = list_tables("eval_alien")
            print(f"  Direct PG list_tables(eval_alien): OK ({len(tables)} tables)")
            print()
            print("  → Set in scribe/.env:  SENTINEL_SQL_BACKEND=psycopg2")
        except Exception as e:
            print(f"  Direct PG list_tables: FAILED — {e}")
            pg_ok = False

    if not cs_ok and not pg_ok:
        print("Neither backend is reachable.")
        print()
        print("Likely fixes:")
        print("  1. Connect to your company VPN (prod uses 10.2.0.9 / 172.20.0.31)")
        print("  2. Ask your team for staging credentials (see commented STAGE block in sentinel .env)")
        print("  3. pip install psycopg2-binary  (for direct PG mode)")
        return 1

    if cs_ok and not pg_ok:
        print("  → Use default: SENTINEL_SQL_BACKEND=connection_service (or omit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
