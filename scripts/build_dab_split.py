"""Build data/splits/dab_sqlite_duckdb.jsonl from the DataAgentBench clone.

One row per query. Schema mirrors KramaBench splits so src/run.ts can ingest
without changes (it just needs context_dir + data_sources + question).

The `answer` field carries a JSON-encoded {dataset, query} pointer; the DAB
scorer uses it to locate the per-task validate.py + ground_truth.csv.

Hints are folded into `guidelines` (db_description.txt + db_description_withhint.txt).
The leaderboard tracks "Hints? Yes/No"; this split corresponds to "Hints? Yes".
"""
from __future__ import annotations

import json
import re
import yaml
from pathlib import Path

DAB_ROOT = Path("/Users/suraj/dab_clone")
SCRIBE_DATA = Path(__file__).resolve().parents[1] / "data" / "dataagentbench"
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "splits" / "dab_all51.jsonl"

# 11 of 12 DAB datasets (PATENTS skipped — 5GB gdrive blob).
DATASETS = [
    ("deps_dev_v1", "DEPS_DEV_V1"),
    ("github_repos", "GITHUB_REPOS"),
    ("music_brainz_20k", "music_brainz_20k"),
    ("stockindex", "stockindex"),
    ("stockmarket", "stockmarket"),
    ("agnews", "agnews"),
    ("bookreview", "bookreview"),
    ("crmarenapro", "crmarenapro"),
    ("googlelocal", "googlelocal"),
    ("pancancer_atlas", "PANCANCER_ATLAS"),
    ("yelp", "yelp"),
]


def db_files_for(query_dir: Path) -> list[str]:
    """Return one identifier per db_client.

    For sqlite/duckdb: bare filename relative to query_dataset/.
    For postgres/mongo: 'postgres:<db_name>' / 'mongo:<db_name>' so the executor
    knows to call open_postgres/open_mongo instead of opening a file.
    """
    cfg = yaml.safe_load((query_dir / "db_config.yaml").read_text())
    files = []
    for _, client in (cfg.get("db_clients") or {}).items():
        ty = client.get("db_type")
        if ty in ("sqlite", "duckdb"):
            v = client.get("db_path")
            if v:
                files.append(v.split("/")[-1])
        elif ty == "postgres":
            files.append(f"postgres:{client['db_name']}")
        elif ty == "mongo":
            files.append(f"mongo:{client['db_name']}")
    return files


def query_ids(query_dir: Path) -> list[str]:
    ids = []
    for d in sorted(query_dir.iterdir()):
        m = re.fullmatch(r"query(\d+)", d.name)
        if m and d.is_dir():
            ids.append(m.group(1))
    return sorted(ids, key=int)


def main():
    rows = []
    for domain, dataset_dir in DATASETS:
        query_root = DAB_ROOT / f"query_{dataset_dir}"
        symlink_root = SCRIBE_DATA / f"query_{dataset_dir}"
        context_dir = str((symlink_root / "query_dataset").resolve())
        data_sources = db_files_for(query_root)
        db_desc = (query_root / "db_description.txt").read_text().strip()
        db_hint = (query_root / "db_description_withhint.txt").read_text().strip()
        # Server-backed DBs (postgres / mongo) get an access hint so the executor
        # uses the right helper. File-only datasets ignore it.
        access_hints = []
        for ds in data_sources:
            if ds.startswith("postgres:"):
                name = ds.split(":", 1)[1]
                access_hints.append(
                    f"- Postgres DB '{name}' is seeded into the local cluster. "
                    f"Open with `conn = open_postgres('{name}')` and query via "
                    f"`conn.execute(sql).fetchall()`."
                )
            elif ds.startswith("mongo:"):
                name = ds.split(":", 1)[1]
                access_hints.append(
                    f"- MongoDB '{name}' is seeded into the local mongod. "
                    f"Open with `db = open_mongo('{name}')` and query via "
                    f"`list(db['<collection>'].find(...).limit(N))`."
                )
            elif ds.lower().endswith(".duckdb"):
                access_hints.append(
                    f"- DuckDB file '{ds}' lives in CONTEXT_DIR. Open with "
                    f"`conn = open_duckdb(context_path('{ds}'))`."
                )
            elif ds.lower().endswith(".db"):
                access_hints.append(
                    f"- Database file '{ds}' lives in CONTEXT_DIR. It is either "
                    f"SQLite or DuckDB; try `open_sqlite(context_path('{ds}'))` "
                    f"first, then `open_duckdb(...)` on failure."
                )
        access_block = "DB ACCESS:\n" + "\n".join(access_hints) if access_hints else ""

        guidelines_base = (
            "DATABASES (relative to your workspace `query_dataset/`):\n"
            + db_desc
            + "\n\nHINTS:\n"
            + db_hint
            + ("\n\n" + access_block if access_block else "")
            + "\n\nFINAL-ANSWER DISCIPLINE: "
            + "Output the final answer on its OWN LINE, as the LAST line. "
            + "No trailing prose. The scorer reads the last non-empty line."
        )
        for qid in query_ids(query_root):
            qdir = query_root / f"query{qid}"
            question = json.loads((qdir / "query.json").read_text())
            if not isinstance(question, str):
                question = str(question)
            task_id = f"{domain}-q{qid}"
            rows.append({
                "task_id": task_id,
                "question": question,
                "guidelines": guidelines_base,
                "level": "hard",
                "answer": json.dumps({"dataset": dataset_dir, "query": qid}),
                "answer_type": "dab_validate",
                "context_dir": context_dir,
                "data_sources": data_sources,
                "domain": domain,
            })

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {len(rows)} tasks → {OUT_PATH}")


if __name__ == "__main__":
    main()
