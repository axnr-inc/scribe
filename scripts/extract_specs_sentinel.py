"""Spec extractor for Sentinel eval SDK — Stage 1 of SCRIBE grafting.

Reads table_context + knowledge markdown from context_downloads/{app_name}/,
optionally samples the live PostgreSQL database via EvalSQLExecutor, and emits
a structured query-plan spec.

Usage:
    python scripts/extract_specs_sentinel.py \\
        --tasks results/sentinel_smoke/tasks.jsonl \\
        --extractor openrouter:openai/gpt-5 \\
        --out results/sentinel_smoke/specs
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

import anthropic
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "scripts"))

from spec_extraction_tools import (  # noqa: E402
    make_read_file_tool,
    make_list_files_tool,
    make_sentinel_dispatcher,
    make_sentinel_describe_table_tool,
    make_sentinel_list_tables_tool,
    make_sentinel_sample_table_tool,
    run_anthropic_spec_loop,
    run_openai_spec_loop,
)
from langfuse_utils import trace_spec_extraction  # noqa: E402

DEFAULT_SENTINEL = ROOT.parent / "sentinel-eval-sdk"

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
            "question_summary": {"type": "string"},
            "tables_needed": {
                "type": "array",
                "items": {"type": "string"},
            },
            "join_path": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["from_col", "to_col", "join_type"],
                    "properties": {
                        "from_col": {"type": "string"},
                        "to_col": {"type": "string"},
                        "join_type": {"type": "string", "enum": ["JOIN", "LEFT JOIN"]},
                    },
                },
            },
            "json_columns": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["table", "column", "path", "alias"],
                    "properties": {
                        "table": {"type": "string"},
                        "column": {"type": "string"},
                        "path": {"type": "string"},
                        "alias": {"type": "string"},
                        "cast": {"type": "string"},
                    },
                },
            },
            "kb_formulas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "kb_id", "sql_expression"],
                    "properties": {
                        "name": {"type": "string"},
                        "kb_id": {"type": ["integer", "string"]},
                        "sql_expression": {"type": "string"},
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                        "threshold": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                },
            },
            "cte_plan": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name", "computes", "sql_sketch"],
                    "properties": {
                        "name": {"type": "string"},
                        "computes": {"type": "string"},
                        "sql_sketch": {"type": "string"},
                        "group_by": {"type": "string"},
                        "agg_note": {"type": "string"},
                    },
                },
            },
            "output_columns": {"type": "array", "items": {"type": "string"}},
            "output_ordering": {"type": "string"},
            "expected_output_format": {"type": "string"},
            "edge_cases": {"type": "array", "items": {"type": "string"}},
            "notes_for_executor": {
                "type": "string",
                "description": "PostgreSQL-specific syntax notes (jsonb operators, window functions, etc.).",
            },
        },
    },
}

SYSTEM_PROMPT = """\
You are a spec agent for the Sentinel text-to-SQL eval benchmark. You read table \
context markdown (DDL, sample rows, column meanings) and domain knowledge markdown, \
then produce a structured query-plan spec an executor will use to write PostgreSQL.

This is a MULTI-SHOT extraction. You may call helper tools before save_spec (up to 5 turns).

# Tools

- read_file(filename): re-read a markdown from the task's context directory.
- list_files(): list available context files.
- list_tables(): list tables in the live PostgreSQL database.
- sample_table(table_name, n=10): sample rows from PostgreSQL.
- describe_table(table_name): column names + types via information_schema.
- save_spec(...): emit the final spec. Terminates extraction.

Before save_spec, verify at least one fact via sample_table, describe_table, or list_tables
when the question references specific tables or JSON/jsonb columns.

# Rules

1. Use PostgreSQL syntax in all sql_sketch fields (jsonb `->` / `->>`, ILIKE, etc.).
2. Trace join paths from FOREIGN KEY constraints in the table context DDL.
3. Translate every named metric/formula from knowledge markdown into sql_expression.
4. Specify aggregation level explicitly — pre-aggregate per entity in separate CTEs when needed.
5. output_columns must match the column names the question asks to display.
6. tables_needed must be minimal — only tables whose columns appear in the query.

Use save_spec as your only output.
"""

print_lock = threading.Lock()

_PROVIDER_DISPATCH: dict = {}

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "in", "is",
    "it", "of", "on", "or", "that", "the", "to", "was", "were", "with", "what", "which",
    "where", "when", "who", "how", "why", "all", "any", "each", "per", "into", "than",
    "then", "this", "those", "these", "their", "them", "its", "our", "your", "you",
    "can", "could", "should", "would", "will", "must", "may", "might", "across", "between",
}


def resolve_sentinel_root(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).expanduser().resolve()
    else:
        env = os.environ.get("SENTINEL_SDK_PATH", "").strip()
        p = Path(env).expanduser().resolve() if env else DEFAULT_SENTINEL.resolve()
    load_dotenv(p / ".env", override=True)
    return p


def load_context_full(docs_dir: Path) -> str:
    parts = []
    for fp in sorted(docs_dir.glob("*.md")):
        parts.append(f"## {fp.name}\n{fp.read_text(encoding='utf-8', errors='replace')}")
    if not parts:
        return f"(no markdown files in {docs_dir})"
    return "\n\n".join(parts)


def _tokenize(text: str) -> list[str]:
    toks = re.findall(r"[A-Za-z_][A-Za-z0-9_]{1,}", (text or "").lower())
    return [t for t in toks if t not in STOPWORDS and len(t) > 2]


def _chunk_text(text: str, chunk_chars: int, overlap_chars: int) -> list[tuple[int, int, str]]:
    if not text:
        return []
    if len(text) <= chunk_chars:
        return [(0, len(text), text)]
    chunks: list[tuple[int, int, str]] = []
    step = max(200, chunk_chars - overlap_chars)
    i = 0
    n = len(text)
    while i < n:
        j = min(n, i + chunk_chars)
        chunks.append((i, j, text[i:j]))
        if j == n:
            break
        i += step
    return chunks


def build_context_rag(
    docs_dir: Path,
    question: str,
    guidelines: str,
    top_k: int,
    chunk_chars: int,
    overlap_chars: int,
    max_context_chars: int,
    include_full_file_under: int,
) -> tuple[str, dict]:
    md_files = sorted(docs_dir.glob("*.md"))
    if not md_files:
        return f"(no markdown files in {docs_dir})", {"mode": "rag", "files": 0}

    query_tokens = _tokenize(f"{question}\n{guidelines}")
    if not query_tokens:
        query_tokens = _tokenize(question)
    qtf = Counter(query_tokens)

    rows: list[dict] = []
    for fp in md_files:
        raw = fp.read_text(encoding="utf-8", errors="replace")
        if len(raw) <= include_full_file_under:
            rows.append({
                "file": fp.name,
                "start": 0,
                "end": len(raw),
                "text": raw,
                "tokens": _tokenize(raw),
                "is_full_file": True,
            })
            continue
        for start, end, chunk in _chunk_text(raw, chunk_chars, overlap_chars):
            rows.append({
                "file": fp.name,
                "start": start,
                "end": end,
                "text": chunk,
                "tokens": _tokenize(chunk),
                "is_full_file": False,
            })

    if not rows:
        return f"(no readable markdown files in {docs_dir})", {"mode": "rag", "files": len(md_files)}

    df = defaultdict(int)
    for r in rows:
        seen = set(r["tokens"])
        for t in seen:
            df[t] += 1

    n_docs = max(1, len(rows))
    avg_len = sum(max(1, len(r["tokens"])) for r in rows) / n_docs
    k1 = 1.2
    b = 0.75

    scored = []
    qset = set(qtf.keys())
    for i, r in enumerate(rows):
        dtf = Counter(r["tokens"])
        dl = max(1, len(r["tokens"]))
        score = 0.0
        overlap = 0
        for term in qset:
            tf = dtf.get(term, 0)
            if tf <= 0:
                continue
            overlap += 1
            idf = math.log(1 + (n_docs - df.get(term, 0) + 0.5) / (df.get(term, 0) + 0.5))
            num = tf * (k1 + 1.0)
            den = tf + k1 * (1.0 - b + b * (dl / max(1.0, avg_len)))
            score += idf * (num / den) * (1.0 + 0.1 * min(3, qtf.get(term, 1) - 1))
        if overlap > 0:
            score += 0.15 * overlap
        scored.append((score, i, r))

    scored.sort(key=lambda x: (x[0], -x[1]), reverse=True)

    selected: list[dict] = []
    seen_signatures = set()
    total_chars = 0
    for score, _, r in scored:
        if len(selected) >= top_k:
            break
        sig = (r["file"], r["start"], r["end"])
        if sig in seen_signatures:
            continue
        text = r["text"].strip()
        if not text:
            continue
        block = (
            f"### {r['file']} [{r['start']}:{r['end']}] score={score:.3f}\n"
            f"{text}"
        )
        extra = len(block) + 2
        if total_chars + extra > max_context_chars and selected:
            continue
        selected.append({
            "file": r["file"],
            "start": r["start"],
            "end": r["end"],
            "score": round(score, 4),
            "chars": len(r["text"]),
            "is_full_file": r["is_full_file"],
        })
        seen_signatures.add(sig)
        total_chars += extra

    if not selected:
        fallback = rows[0]
        selected = [{
            "file": fallback["file"],
            "start": fallback["start"],
            "end": fallback["end"],
            "score": 0.0,
            "chars": len(fallback["text"]),
            "is_full_file": fallback["is_full_file"],
        }]

    selected_blocks = []
    for s in selected:
        text = next(
            (
                r["text"] for r in rows
                if r["file"] == s["file"] and r["start"] == s["start"] and r["end"] == s["end"]
            ),
            "",
        )
        selected_blocks.append(
            f"### {s['file']} [{s['start']}:{s['end']}] score={s['score']:.3f}\n{text.strip()}"
        )

    context = (
        "## Retrieved Context (RAG)\n"
        "Only the highest-relevance markdown chunks are preloaded below. "
        "If evidence is missing, use read_file(filename) to fetch additional sections.\n\n"
        + "\n\n".join(selected_blocks)
    )
    meta = {
        "mode": "rag",
        "files": len(md_files),
        "query_terms": len(qset),
        "candidate_chunks": len(rows),
        "selected_chunks": len(selected),
        "selected_chars": total_chars,
        "top_k": top_k,
        "chunk_chars": chunk_chars,
        "overlap_chars": overlap_chars,
        "max_context_chars": max_context_chars,
        "include_full_file_under": include_full_file_under,
    }
    return context, meta


def build_context(
    docs_dir: Path,
    question: str,
    guidelines: str,
    mode: str,
    top_k: int,
    chunk_chars: int,
    overlap_chars: int,
    max_context_chars: int,
    include_full_file_under: int,
) -> tuple[str, dict]:
    if mode == "full":
        ctx = load_context_full(docs_dir)
        return ctx, {"mode": "full", "chars": len(ctx)}
    return build_context_rag(
        docs_dir,
        question,
        guidelines,
        top_k,
        chunk_chars,
        overlap_chars,
        max_context_chars,
        include_full_file_under,
    )


def build_user_message(context: str, question: str, guidelines: str = "") -> str:
    body = f"{context}\n\n## Task\n{question}"
    if guidelines and guidelines.strip():
        body += f"\n\n## Guidelines\n{guidelines.strip()}"
    return body


def _helper_tools(docs_dir: Path) -> list[dict]:
    return [
        make_read_file_tool(docs_dir),
        make_list_files_tool(docs_dir),
        make_sentinel_list_tables_tool(),
        make_sentinel_sample_table_tool(),
        make_sentinel_describe_table_tool(),
    ]


def extract_spec_anthropic(model, context, question, guidelines, task_id, docs_dir, app_name, sdk_path):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    spec, usage, session, telem = run_anthropic_spec_loop(
        client=client,
        model=model,
        system=SYSTEM_PROMPT,
        user_prompt=build_user_message(context, question, guidelines),
        helper_tools=_helper_tools(docs_dir),
        save_spec_tool=SAVE_SPEC_TOOL,
        dispatch=make_sentinel_dispatcher(docs_dir, app_name, sdk_path),
        max_tokens=4096,
    )
    if spec is None:
        raise ValueError(
            f"No save_spec for {task_id} (hit_cap={telem['hit_cap']}, "
            f"tools={telem['tool_calls_before_save']})"
        )
    return spec, session, usage


def _extract_openai_compat(provider_label, base_url, api_key, api_key_env, model,
                           context, question, guidelines, task_id, docs_dir, app_name, sdk_path):
    from openai import OpenAI
    if not api_key:
        raise SystemExit(f"{api_key_env} not in .env")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=180.0, max_retries=0)
    spec, usage, session, telem = run_openai_spec_loop(
        client=client,
        model=model,
        system=SYSTEM_PROMPT,
        user_prompt=build_user_message(context, question, guidelines),
        helper_tools=_helper_tools(docs_dir),
        save_spec_tool=SAVE_SPEC_TOOL,
        dispatch=make_sentinel_dispatcher(docs_dir, app_name, sdk_path),
        provider_label=provider_label,
        max_tokens=16000,
    )
    if spec is None:
        raise ValueError(
            f"No save_spec for {task_id} (hit_cap={telem['hit_cap']}, "
            f"tools={telem['tool_calls_before_save']})"
        )
    return spec, session, usage


def process_one(args_tuple):
    (
        task,
        out_dir,
        sdk_path,
        provider,
        model,
        overwrite,
        context_mode,
        rag_top_k,
        rag_chunk_chars,
        rag_overlap_chars,
        rag_max_context_chars,
        rag_include_full_file_under,
        run_out_dir,
    ) = args_tuple
    tid = task["task_id"]
    spec_path = out_dir / f"{tid}.json"
    session_path = out_dir / f"{tid}.spec_session.json"
    original_path = out_dir / f"{tid}.original.json"

    if spec_path.exists() and not overwrite:
        try:
            existing = json.loads(spec_path.read_text())
            if isinstance(existing, dict) and "_error" not in existing:
                with print_lock:
                    print(f"  [skip] {tid}", flush=True)
                return "skip", tid, None
        except Exception:
            pass  # unreadable → re-extract below

    docs_dir = Path(task["context_dir"])
    app_name = task["app_name"]
    question = task["question"]
    guidelines = task.get("guidelines", "")
    t0 = time.time()

    try:
        context, context_meta = build_context(
            docs_dir=docs_dir,
            question=question,
            guidelines=guidelines,
            mode=context_mode,
            top_k=rag_top_k,
            chunk_chars=rag_chunk_chars,
            overlap_chars=rag_overlap_chars,
            max_context_chars=rag_max_context_chars,
            include_full_file_under=rag_include_full_file_under,
        )
        if provider == "anthropic":
            spec, session, usage = extract_spec_anthropic(
                model, context, question, guidelines, tid, docs_dir, app_name, sdk_path,
            )
        elif provider == "openrouter":
            spec, session, usage = _extract_openai_compat(
                "openrouter", "https://openrouter.ai/api/v1",
                os.environ.get("OPENROUTER_API_KEY", ""), "OPENROUTER_API_KEY",
                model, context, question, guidelines, tid, docs_dir, app_name, sdk_path,
            )
        elif provider == "fireworks":
            spec, session, usage = _extract_openai_compat(
                "fireworks", "https://api.fireworks.ai/inference/v1",
                os.environ.get("FIREWORKS_API_KEY", ""), "FIREWORKS_API_KEY",
                model, context, question, guidelines, tid, docs_dir, app_name, sdk_path,
            )
        elif provider == "fireworks2":
            spec, session, usage = _extract_openai_compat(
                "fireworks2", "https://api.fireworks.ai/inference/v1",
                os.environ.get("FIREWORKS_API_KEY2", ""), "FIREWORKS_API_KEY2",
                model, context, question, guidelines, tid, docs_dir, app_name, sdk_path,
            )
        else:
            raise ValueError(f"Unknown provider: {provider}")

        meta = session.get("metadata") or {}
        spec.setdefault("_meta", {})
        spec["_meta"].update({
            "extractor": f"{provider}:{model}",
            "app_name": app_name,
            "tool_calls_before_save": meta.get("tool_calls_before_save", 0),
            "hit_cap": meta.get("hit_cap", False),
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
            "context_mode": context_mode,
            "context_meta": context_meta,
        })
        lf_info = trace_spec_extraction(
            run_out_dir=str(run_out_dir),
            task_id=tid,
            model=model,
            provider=provider,
            question=question,
            input_tokens=int(usage.get("input_tokens", 0) or 0),
            output_tokens=int(usage.get("output_tokens", 0) or 0),
            wall_seconds=time.time() - t0,
            ok=True,
        )
        if lf_info:
            spec["_meta"].update(lf_info)
        spec_path.write_text(json.dumps(spec, indent=2))
        original_path.write_text(json.dumps(spec, indent=2))
        session_path.write_text(json.dumps(session, indent=2))
        elapsed = round(time.time() - t0, 1)
        with print_lock:
            print(
                f"  [ok]   {tid} ({elapsed}s)  tables={spec.get('tables_needed', [])}  "
                f"ctes={len(spec.get('cte_plan', []))}",
                flush=True,
            )
        return "ok", tid, None
    except Exception as e:
        elapsed = round(time.time() - t0, 1)
        with print_lock:
            print(f"  [err]  {tid} ({elapsed}s): {e}", flush=True)
        err_spec = {"_error": str(e), "task_id": tid}
        spec_path.write_text(json.dumps(err_spec, indent=2))
        return "err", tid, str(e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--extractor", default="openrouter:openai/gpt-5")
    parser.add_argument("--sentinel-root", default=None)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--run-out",
        default=None,
        help="SCRIBE run output dir (for Langfuse trace id correlation). Defaults to parent of --out.",
    )
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--context-mode", choices=["full", "rag"], default="rag")
    parser.add_argument("--rag-top-k", type=int, default=12)
    parser.add_argument("--rag-chunk-chars", type=int, default=1800)
    parser.add_argument("--rag-overlap-chars", type=int, default=250)
    parser.add_argument("--rag-max-context-chars", type=int, default=45000)
    parser.add_argument("--rag-include-full-file-under", type=int, default=7000)
    args = parser.parse_args()

    sdk_path = resolve_sentinel_root(args.sentinel_root)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_out_dir = Path(args.run_out).expanduser().resolve() if args.run_out else out_dir.parent.resolve()

    provider, model = args.extractor.split(":", 1)
    if provider not in {"anthropic", "openrouter", "fireworks", "fireworks2"}:
        print(f"Unknown provider: {provider}", file=sys.stderr)
        sys.exit(1)

    tasks = [json.loads(l) for l in open(args.tasks) if l.strip()]
    print(
        f"Extracting specs for {len(tasks)} Sentinel tasks → {out_dir} "
        f"(provider={provider}, model={model}, sdk={sdk_path}, context_mode={args.context_mode})",
        flush=True,
    )

    work = [
        (
            t,
            out_dir,
            sdk_path,
            provider,
            model,
            args.overwrite,
            args.context_mode,
            args.rag_top_k,
            args.rag_chunk_chars,
            args.rag_overlap_chars,
            args.rag_max_context_chars,
            args.rag_include_full_file_under,
            run_out_dir,
        )
        for t in tasks
    ]
    counts = {"ok": 0, "err": 0, "skip": 0}
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for status, tid, _ in pool.map(process_one, work):
            counts[status] += 1

    print(f"\nDone: {counts['ok']} ok / {counts['err']} errors / {counts['skip']} skipped")


if __name__ == "__main__":
    main()
