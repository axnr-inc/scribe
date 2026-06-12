"""Seed Postgres + Mongo databases for DataAgentBench.

For each dataset listed in DATASETS, reads db_config.yaml and:
- For db_type=postgres: runs `psql -d <db_name> -f <sql_file>` (after creating the DB)
- For db_type=mongo: runs `mongorestore --nsInclude=<db_name>.* <dump_folder>`

Idempotent: if a DB already exists, it is dropped + recreated. Safe to re-run.

Defaults match DAB convention:
  Postgres: host=127.0.0.1, port=5432, user=$USER, password='' (trust auth)
            DAB upstream expects user=postgres, but on brew the default user is
            $USER. We accept either via PG_USER env var.
  Mongo:    mongodb://localhost:27017, no auth.

PATENTS is skipped (5GB gdrive blob not available locally).

USAGE:
    python3 scripts/seed_dab_dbs.py                  # seed all 6 datasets
    python3 scripts/seed_dab_dbs.py --only bookreview agnews
    python3 scripts/seed_dab_dbs.py --check-only     # just verify connectivity
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

DAB_ROOT = Path("/tmp/dab_clone")

DATASETS = [
    "agnews",
    "bookreview",
    "crmarenapro",
    "googlelocal",
    "PANCANCER_ATLAS",
    "yelp",
]

PG_HOST = os.environ.get("PG_HOST", "127.0.0.1")
PG_PORT = os.environ.get("PG_PORT", "5432")
PG_USER = os.environ.get("PG_USER", os.environ.get("USER", "postgres"))
PG_PASSWORD = os.environ.get("PG_PASSWORD", "")
MONGO_URI = os.environ.get("MONGO_URI", "mongodb://localhost:27017")
PSQL = os.environ.get("PG_CLIENT", "/opt/homebrew/opt/postgresql@17/bin/psql")
MONGORESTORE = os.environ.get("MONGORESTORE", "/opt/homebrew/bin/mongorestore")


def pg_env() -> dict:
    env = os.environ.copy()
    if PG_PASSWORD:
        env["PGPASSWORD"] = PG_PASSWORD
    env["PGCLIENTENCODING"] = "UTF8"
    return env


def pg_run(args: list[str], dbname: str = "postgres") -> subprocess.CompletedProcess:
    cmd = [PSQL, "-h", PG_HOST, "-p", PG_PORT, "-U", PG_USER, "-d", dbname] + args
    return subprocess.run(cmd, env=pg_env(), capture_output=True, text=True)


def pg_db_exists(dbname: str) -> bool:
    r = pg_run(["-tAc", f"SELECT 1 FROM pg_database WHERE datname='{dbname}'"])
    return r.stdout.strip() == "1"


def pg_drop(dbname: str):
    pg_run(["-c", f'DROP DATABASE IF EXISTS "{dbname}"'])


def pg_create(dbname: str):
    pg_run([
        "-c",
        f'CREATE DATABASE "{dbname}" WITH ENCODING = \'UTF8\' '
        f"LC_COLLATE='C' LC_CTYPE='C' TEMPLATE=template0",
    ])


def pg_load(sql_file: Path, dbname: str):
    if pg_db_exists(dbname):
        print(f"    PG DB '{dbname}' exists — dropping and recreating")
        pg_drop(dbname)
    pg_create(dbname)
    cmd = [PSQL, "-h", PG_HOST, "-p", PG_PORT, "-U", PG_USER,
           "-d", dbname, "-f", str(sql_file), "-q"]
    r = subprocess.run(cmd, env=pg_env(), capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"psql -f failed for {dbname}: {r.stderr[:500]}")
    if r.stderr:
        # psql writes NOTICE / WARNING to stderr; only flag ERROR
        bad = [l for l in r.stderr.splitlines() if "ERROR" in l]
        if bad:
            print(f"    (psql had errors) {bad[:3]}")


def mongo_drop(dbname: str):
    from pymongo import MongoClient
    c = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    c.drop_database(dbname)
    c.close()


def mongo_load(dump_folder: Path, dbname: str):
    # mongorestore convention: dump_folder/<db_name>/<collection>.bson
    # Drop existing first for idempotency
    mongo_drop(dbname)
    cmd = [
        MONGORESTORE,
        "--uri", MONGO_URI,
        "--nsInclude", f"{dbname}.*",
        str(dump_folder),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"mongorestore failed for {dbname}: {r.stderr[:500]}")


def check_servers():
    """Verify Postgres + Mongo are reachable."""
    r = pg_run(["-c", "SELECT version();"])
    if r.returncode != 0:
        raise SystemExit(f"Postgres not reachable: {r.stderr[:300]}")
    print(f"  Postgres OK: {r.stdout.split(chr(10))[2].strip() if len(r.stdout.split(chr(10)))>2 else r.stdout[:100]}")

    from pymongo import MongoClient
    try:
        c = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        info = c.server_info()
        print(f"  MongoDB OK: v{info['version']}")
        c.close()
    except Exception as e:
        raise SystemExit(f"MongoDB not reachable: {e}")


def seed_dataset(dataset_dir: str) -> dict:
    cfg_path = DAB_ROOT / f"query_{dataset_dir}" / "db_config.yaml"
    cfg = yaml.safe_load(cfg_path.read_text())
    workspace = DAB_ROOT / f"query_{dataset_dir}"  # relative paths anchor here
    results = {"dataset": dataset_dir, "pg_loaded": [], "mongo_loaded": [], "skipped": []}
    for client_name, client in (cfg.get("db_clients") or {}).items():
        ty = client.get("db_type")
        if ty == "postgres":
            sql_file = workspace / client["sql_file"]
            db_name = client["db_name"]
            print(f"  PG seed: {client_name} → {db_name} ({sql_file.stat().st_size / 1024:.1f} KB)")
            pg_load(sql_file, db_name)
            results["pg_loaded"].append(db_name)
        elif ty == "mongo":
            dump_folder = workspace / client["dump_folder"]
            db_name = client["db_name"]
            print(f"  Mongo seed: {client_name} → {db_name} ({dump_folder})")
            mongo_load(dump_folder, db_name)
            results["mongo_loaded"].append(db_name)
        else:
            results["skipped"].append(f"{client_name}({ty})")
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--only", nargs="*", help="Only seed these dataset dirs")
    p.add_argument("--check-only", action="store_true",
                   help="Just verify Postgres + Mongo are up")
    args = p.parse_args()

    print(f"PG: {PG_USER}@{PG_HOST}:{PG_PORT}")
    print(f"Mongo: {MONGO_URI}")
    print()
    check_servers()
    if args.check_only:
        return 0

    targets = args.only if args.only else DATASETS
    print(f"\nSeeding {len(targets)} dataset(s): {targets}\n")
    summary = []
    for d in targets:
        print(f"=== {d} ===")
        try:
            r = seed_dataset(d)
            summary.append(r)
            print(f"  OK: pg={r['pg_loaded']}, mongo={r['mongo_loaded']}, "
                  f"skipped={r['skipped']}")
        except Exception as e:
            print(f"  FAILED: {e}")
            summary.append({"dataset": d, "error": str(e)})
        print()

    print("=" * 60)
    print("SUMMARY")
    for r in summary:
        if "error" in r:
            print(f"  {r['dataset']:<22} ERROR: {r['error'][:80]}")
        else:
            n_pg = len(r["pg_loaded"])
            n_mongo = len(r["mongo_loaded"])
            print(f"  {r['dataset']:<22} pg={n_pg} mongo={n_mongo}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
