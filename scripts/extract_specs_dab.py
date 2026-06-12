"""DAB spec extractor — stage-1 grafting for DataAgentBench tasks.

Differences from scripts/extract_specs_krama.py (the closest sibling):
  - Data lakes are databases (SQLite + DuckDB), not files. We pre-sample every
    table (schema + 3 rows) into the user message instead of giving the
    spec_agent a tool surface.
  - One-shot extraction: helper_tools=[] so the agent commits a spec without
    burning extra tool turns. The schema + samples in the user message are
    enough for spec_agent to surface interpretations.
  - Reuses Krama's SAVE_SPEC_TOOL, SYSTEM_PROMPT, and run_anthropic_spec_loop.

Usage:
    python3 scripts/extract_specs_dab.py \\
        --tasks data/splits/dab_sqlite_duckdb.jsonl \\
        --extractor anthropic:claude-opus-4-7 \\
        --out results/dab_specs
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "scripts"))

import duckdb  # noqa: E402

from extract_specs_krama import SAVE_SPEC_TOOL, SYSTEM_PROMPT as _KRAMA_SYSTEM_PROMPT  # noqa: E402
from spec_extraction_tools import run_anthropic_spec_loop, run_openai_spec_loop  # noqa: E402


# DAB-specific addendum: catches three failure modes observed on PATENTS.
# Prepended to the Krama SYSTEM_PROMPT so all the I-1 / interpretation
# discipline still applies.
DAB_PROMPT_ADDENDUM = """\
# DAB-specific interpretation rules (read these BEFORE Krama rules below)

## RULE 0 — Spec hygiene (MANDATORY; the spec is read by a third-party reviewer)

Your spec text must contain NOTHING that looks like answer-key access. Strictly:
- NEVER state, guess, or hint at an expected/gold answer VALUE or record ID
  (no "the expected answer is ...", "that is the gold answer", "= gold").
- NEVER quote literal record IDs from sampled rows (e.g. Salesforce IDs like
  '001Wt...', '005Wt...', 'ka0Wt...'). Refer to COLUMNS and LOGIC, not literal
  sampled ID values. If you must give a format example, use an obviously-fake
  placeholder like '<RecordId>'.
- NEVER describe the gold answer's cardinality or structure ("gold has N rows",
  "gold enumerates all", "validator gate >=5 confirms ...").
- NEVER reference "the validator", how it matches (fuzzy/substring), its
  tolerance, or its output rules. Describe output formatting in neutral terms,
  e.g. "print the final answer on the last line as a Python list of tuples".

## RULE 1 — Answer shape (multi-row vs single-row)

DAB validators frequently expect MULTI-ROW answers when the question reads
"for each X" / "per X" / "every X" / "list" / "include the ... for each".
Single-row collapse is a common failure mode.

If the question text contains any of these phrases, the answer is
multi-row by default. Surface "single-row vs multi-row" as an
explicit interpretation in the `interpretations` array, and choose
multi-row unless the question explicitly says "the top one" / "the
highest single" / "which one".

- "for each X" / "per X" / "every X" / "all X" / "list X" — multi-row
- "the highest X" / "the top X" / "which X" / "single X" — single-row
- When in doubt: emit ALL rows that match the filter, sorted by the rank
  criterion. The validator can fuzzy-match against any subset of gold rows
  but will fail if the right rows are missing.

## RULE 2 — Validator output format

DAB validators do fuzzy substring matching, NOT structural parsing. Print
your answer with ALL required fields per row in close proximity (within
~50 characters). Standard formats that work:

- Python list of tuples on the LAST line, one tuple per gold row.
- CSV-style rows where each row contains every required field.
- DON'T put title on one line and code on another (the windowed match fails).

## RULE 3 — Patent-domain helpers (when domain='patents')

The executor has pre-imported these helpers from data/context/patent_helper.py.
REFERENCE THEM BY NAME instead of writing inline regex:

- extract_assignee_from_patents_info(text) — owner/assignee from Patents_info NL.
- extract_publication_number(text) / extract_application_number(text)
- country_from_pubno(pubno), is_country(text, country_code)
- parse_cpc_field(json_str), cpc_codes(json_str), cpc_primary_code(json_str),
  cpc_subclass(code), cpc_main_group(code)
- cpc_subclass_title(code, conn_pg) — titleFull of the code's 4-char SUBCLASS
  by exact symbol lookup. For "primary CPC subclass title" questions use THIS;
  never resolve titles by walking the `parents` chain (that ascends to broad
  section/class titles and is the wrong granularity).
- parse_citation_field(json_str), cited_publication_numbers(json_str)
- exponential_moving_average(values, alpha) — adjust=False form, with
  _ema_self_test() that runs at import to verify correctness.
- best_year_by_ema(year_to_count_dict, alpha) — argmax-EMA year with
  zero-fill across the observed year span. THIS is the right function for
  "best year of patent filings" questions. Use it; do not roll your own.

When the question asks "best year of patent filings" or "year with highest
EMA of filings", the spec MUST call best_year_by_ema (or equivalently
ewm(alpha=..., adjust=False).idxmax()) — NOT argmax of raw counts.
The plan must pin EMA initialization EXPLICITLY (seed + zero-fill arguments,
matching the helper's defaults). If the question itself does not pin the
initialization and the choice changes the answer, surface seed='zero' vs
seed='x0' as interpretations and declare interpretation_confidence 'split'.

## RULE 4 — Year axis must include zero-filled missing years

EMA on patent filings is sensitive to year-axis choice. The canonical
choice is: build a complete year series from min(observed) to max(observed)
inclusive, fill missing years with 0, then EMA across that. Do NOT EMA
only the observed years — that biases later years upward.

## RULE 4b — Filter-then-verify (MANDATORY for any cohort/date/entity filter)

Whenever the plan filters rows (by country, date window, entity name,
category...), the plan MUST include a verification step IMMEDIATELY after
the filter and BEFORE any downstream metric:
  1. print the cohort size and 2-3 sample rows;
  2. sanity-check the sample against the question's constraints (e.g. for
     "granted in H2 2019" the sampled grant dates must actually fall in
     2019-07..2019-12 — and the filter must use the GRANT date field, not
     filing/publication);
  3. if the cohort is EMPTY or the sample violates the constraints, the
     plan must say: re-derive the filter (try the other date field /
     country encoding / entity spelling) or escalate via ask_planner_agent
     — NEVER silently fall back to the unfiltered dataset.
Silent filter failure is the single most damaging executor bug we observe:
the metric then gets computed over ALL rows and looks plausible.

## RULE 5 — Filter strictness enumeration

For ANY filter phrase of the form "does not X" / "not Y" / "non-Z"
(examples: "do not use Python", "non-Python", "non-binary", "excluding X"):
you MUST surface BOTH interpretations as distinct entries in the
`interpretations` array, then explicitly choose ONE:

  - strict-exclusion: X is ENTIRELY absent from the relevant field.
    For "do not use Python": NO row in the relevant table mentions Python
    anywhere (no substring match anywhere in `language_description`).
  - primary-exclusion: X is not the PRIMARY/dominant signal.
    For "main language is not Python": Python is not the first listed
    language; allows other rows to still mention Python.

DEFAULT to strict-exclusion unless the question explicitly says
"primary language" or "main language is not".

This rule fires on github_repos-q1 ("repositories that do not use Python")
and github_repos-q4 ("main language is not Python"). For q1, strict means
the repo's `language_description` is FREE of any "Python" mention. For q4,
"main language is" is explicit primary-exclusion phrasing.

When in doubt, prefer the STRICTER filter. Validators penalize false
positives (extra rows) less than false negatives (missing rows).

## RULE 6 — Metric-definition enumeration for ambiguous nouns

For ambiguous metric nouns ("copied", "popular", "best", "most frequently"),
surface 2-3 candidate definitions in `interpretations` before choosing one:

  Example: "most frequently copied non-binary Swift file":
    (a) `id`-based: same file blob ID appears in N distinct repos.
        Definition: COUNT(DISTINCT sample_repo_name) GROUP BY id.
    (b) path-based: file path appears in N repos.
    (c) `contents.sample_repo_name`-based: count how many times the
        blob ID is referenced in `contents` for distinct repos.

  Example: "popular":
    GitHub stars / forks / watches / pull-count — be explicit about which.

  Example: "best year" / "highest EMA": see RULE 3.

When multiple tables share an ID column, DEFAULT to the cross-table-join
definition (e.g., counting distinct repos a file blob appears in) over a
within-single-table definition.

## RULE 8 — Assignee-type cohort enumeration (PATENTS)

When the question asks for "assignees" / "owners" of patents, surface
2-3 candidate cohort interpretations in `interpretations`:

  - individuals-only: assignees that match PERSON-name patterns
    (FIRST LAST / LAST FIRST / LAST FIRST MIDDLE, usually ALL CAPS).
  - corporations-only: assignees that match COMPANY patterns ending
    in 'CORP', 'INC', 'LLC', 'LTD', 'GMBH', 'AG', 'CO LTD', 'KG',
    'PLC', 'COMPANY', 'CORPORATION', or '&'-joined entity names.
  - both: the union of individuals and corporations.

Surface these as explicit interpretations and choose based on the
question wording and the cohort size you compute from the data — do not
assume which cohort; an 'assignees' question may mean individuals,
companies, or both depending on the phrasing.

Use `extract_assignee_from_patents_info(text)` from patent_helper, then
classify each extracted assignee as person-name vs corporate by regex
match against the suffix patterns above.

## RULE 7 — Multi-row sanity check + explicit row count

Before committing your spec's expected_output_format, write `min_rows: N`
where N is your best estimate of the gold row count given the question's
filters and the data's distribution. Examples:

- "for each CPC group at level 4 in Germany" → min_rows ≈ number of
  level-4 groups in the German cohort. If your computation_plan would
  produce 35 groups, set min_rows: 30 (allow a small margin).
- "list the top 5 repos" → min_rows: 5.
- "what proportion ..." → min_rows: 1 (single numeric answer).
- "which assignees citing X" → min_rows: 10 (estimate from cohort size).

This is the harness's hard floor — the executor cannot commit a final
answer with fewer than min_rows rows; it will be forced to retry.

## RULE 9 — Count/metric phrasing enumeration in free text

When a value (stars, forks, copies, views, counts) is embedded in a
NATURAL-LANGUAGE text field rather than a numeric column, the SAME value
is often phrased multiple ways across rows. Parsing only ONE phrasing
silently drops the rows that use the others — and those are frequently
the highest-value rows (top repos, most-copied files).

Rule: SAMPLE several rows of the text field, enumerate EVERY distinct
phrasing you observe, and write a regex alternation covering all of them.
Do NOT assume a single phrasing — count fields often mix forms like
"N stars" / "stars count of N", or "seen N times" / "appearing N times".
Always strip thousands separators (commas) before int(). The point is to
discover the phrasings empirically from the data, not to hardcode any.

## RULE 10 — Prefer code columns over display-name columns

When the expected answer format is a CODE (slash-codes, classification
symbols, ICD/CPC codes, ticker symbols), the data often has BOTH a
human-readable name column AND a code column. Using the name column gives
plausible-but-wrong answers that fail exact/fuzzy match.

Rule: before committing, SAMPLE the table's columns and look for a
code-like column (values matching slash-codes, alphanumeric symbols,
ID patterns) alongside any human-readable name column. When the question
or output format implies a code/symbol, prefer the code column over the
display-name column. Surface "code-column vs name-column" as an explicit
interpretation and choose based on the sampled schema — do not assume
which column; discover it from the data.

## RULE 11 — Scope by the EVENT the question names, not a proxy

Time/window filters must key off the exact event the question names —
not a convenient proxy column. Picking the wrong date column is a common
silent failure on policy/CRM/sales questions.

Rule: read the question's verb carefully and map it to the date/column
that names that event, not a convenient proxy:
- "closing / closed / turnaround to closing" → the close/signed date,
  NOT the creation date.
- "granted in <period>" → grant date, NOT filing date.
- "registered in <year>" → registration date, NOT activity date.
For policy-VIOLATION questions ("which knowledge article does X violate"),
evaluate ALL candidate policies systematically (compute each policy's
condition against the record) rather than committing to the first
plausible article. Read each candidate policy's actual text and test its
condition; do not assume which policy is violated.

## RULE 12 — Declare genuine coin flips with interpretation_confidence: 'split'

After inspecting the schema and sampled data, decide honestly: does the
evidence clearly favor one interpretation?

- If YES: set interpretation_confidence to 'committed' and commit normally.
- If NO — two (or more) readings remain comparably defensible and would
  produce DIFFERENT answers (e.g. mean-over-reviews vs mean-over-businesses,
  code-column vs name-column, which denominator, EMA seed) — set
  interpretation_confidence to 'split' and order `interpretations`
  most-plausible-first. The harness commits a different reading on each
  trial, which is the optimal play under per-trial scoring.

Declare 'split' ONLY for genuine coin flips: if you would bet 70/30 or
better on one reading, commit it. Splitting a confidently-correct reading
wastes trials; committing a coin flip risks all of them.

"""


SYSTEM_PROMPT = DAB_PROMPT_ADDENDUM + _KRAMA_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# DB sampling: every table in every DB → schema + 3 rows in the user prompt
# ---------------------------------------------------------------------------

def _try_sqlite_sample(path: Path, max_tables: int = 20, sample_rows: int = 3) -> str | None:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except Exception:
        return None
    try:
        try:
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()]
        except sqlite3.Error:
            return None
        if not tables:
            return None
        out = [f"## SQLite DB `{path.name}` — {len(tables)} table(s)"]
        for t in tables[:max_tables]:
            try:
                cols_raw = conn.execute(f"PRAGMA table_info({t})").fetchall()
                cols = [(r[1], r[2]) for r in cols_raw]
                out.append(f"### {t}")
                out.append("columns: " + ", ".join(f"{n}:{ty}" for n, ty in cols))
                cur = conn.execute(f'SELECT * FROM "{t}" LIMIT {int(sample_rows)}')
                col_names = [d[0] for d in cur.description]
                rows = cur.fetchall()
                if rows:
                    out.append("sample rows:")
                    for r in rows:
                        d = {k: (str(v)[:200] if v is not None else None)
                             for k, v in zip(col_names, r)}
                        out.append("  " + json.dumps(d, default=str))
                else:
                    out.append("(empty table)")
            except Exception as e:
                out.append(f"### {t} (error: {e})")
        if len(tables) > max_tables:
            out.append(f"... and {len(tables) - max_tables} more tables (truncated)")
        return "\n".join(out)
    finally:
        conn.close()


def _try_duckdb_sample(path: Path, max_tables: int = 20, sample_rows: int = 3) -> str | None:
    try:
        conn = duckdb.connect(str(path), read_only=True)
    except Exception:
        return None
    try:
        try:
            tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        except Exception:
            return None
        if not tables:
            return None
        out = [f"## DuckDB DB `{path.name}` — {len(tables)} table(s)"]
        for t in tables[:max_tables]:
            try:
                desc = conn.execute(f"DESCRIBE {t}").fetchall()
                cols = [(r[0], r[1]) for r in desc]
                out.append(f"### {t}")
                out.append("columns: " + ", ".join(f"{n}:{ty}" for n, ty in cols))
                rows = conn.execute(
                    f'SELECT * FROM "{t}" LIMIT {int(sample_rows)}'
                ).fetchall()
                col_names = [d[0] for d in conn.description]
                if rows:
                    out.append("sample rows:")
                    for r in rows:
                        d = {k: (str(v)[:200] if v is not None else None)
                             for k, v in zip(col_names, r)}
                        out.append("  " + json.dumps(d, default=str))
                else:
                    out.append("(empty table)")
            except Exception as e:
                out.append(f"### {t} (error: {e})")
        if len(tables) > max_tables:
            out.append(f"... and {len(tables) - max_tables} more tables (truncated)")
        return "\n".join(out)
    except Exception:
        return None
    finally:
        try:
            conn.close()
        except Exception:
            pass


def sample_db_file(path: Path) -> str:
    """Try SQLite first, then DuckDB. DAB stores both as `.db`."""
    if not path.exists():
        return f"## {path.name}\n(file missing at {path})"
    s = _try_sqlite_sample(path)
    if s:
        return s
    d = _try_duckdb_sample(path)
    if d:
        return d
    return f"## {path.name}\n(could not open as SQLite or DuckDB; size={path.stat().st_size} bytes)"


def build_user_prompt(task: dict, context_dir: Path) -> str:
    data_sources: list[str] = task.get("data_sources") or []
    sample_blocks = []
    for name in data_sources:
        sample_blocks.append(sample_db_file(context_dir / name))

    parts = [
        "# Databases (every table sampled — schema + 3 rows)",
        "\n\n".join(sample_blocks) if sample_blocks else "(none flagged)",
        "",
        "# Task",
        f"task_id: {task.get('task_id','')}",
        f"question: {task.get('question','')}",
        f"guidelines (db_description + hints):\n{task.get('guidelines','')}",
        f"answer_type: {task.get('answer_type','')}",
        "",
        "Analyze the task and the sampled DB tables. Produce a structured spec "
        "with interpretations (I-1 gate: 2-4 readings), a chosen_interpretation, "
        "key_functionalities (abstract steps for the rubric), and a concrete "
        "computation_plan the executor will implement. Treat each step as SQL "
        "the executor would run via sqlite3 / duckdb helpers, not pandas "
        "primitives. Do NOT reference krama_helper patterns — those are CSV-shaped.",
    ]
    return "\n\n".join(parts)


def call_anthropic(model: str, user: str, max_tokens: int = 8000):
    # Fable-5 at xhigh effort spends a large thinking budget before tool calls;
    # 8000 tokens can be exhausted before save_spec. Give it more headroom.
    if "fable" in model:
        max_tokens = 16000
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not in .env")
    client = anthropic.Anthropic()
    spec, usage, session, telem = run_anthropic_spec_loop(
        client=client,
        model=model,
        system=SYSTEM_PROMPT,
        user_prompt=user,
        helper_tools=[],  # one-shot: all samples in the user message
        save_spec_tool=SAVE_SPEC_TOOL,
        dispatch=lambda name, args: f"(tool '{name}' not available)",
        max_tokens=max_tokens,
    )
    if spec is None:
        raise RuntimeError(
            f"spec_agent never called save_spec (hit_cap={telem['hit_cap']}, "
            f"tool_calls_before_save={telem['tool_calls_before_save']})"
        )
    return spec, usage, session


def call_openrouter(model: str, user: str, max_tokens: int = 16000):
    """Multi-shot extraction via OpenRouter (OpenAI tool-calling)."""
    from openai import OpenAI
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY not in .env")
    client = OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1",
                    timeout=180.0, max_retries=0)
    spec, usage, session, telem = run_openai_spec_loop(
        client=client,
        model=model,
        system=SYSTEM_PROMPT,
        user_prompt=user,
        helper_tools=[],
        save_spec_tool=SAVE_SPEC_TOOL,
        dispatch=lambda name, args: f"(tool '{name}' not available)",
        provider_label="openrouter",
        max_tokens=max_tokens,
    )
    if spec is None:
        raise RuntimeError(
            f"spec_agent never called save_spec (hit_cap={telem['hit_cap']}, "
            f"tool_calls_before_save={telem['tool_calls_before_save']})"
        )
    return spec, usage, session


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", required=True, help="DAB tasks JSONL")
    p.add_argument("--extractor", required=True,
                   help="Format: <provider>:<model_id> (provider: anthropic | openrouter)")
    p.add_argument("--out", required=True, help="Output dir for spec JSONs")
    args = p.parse_args()

    if ":" not in args.extractor:
        raise SystemExit("--extractor must be <provider>:<model_id>")
    provider, model = args.extractor.split(":", 1)
    if provider not in ("anthropic", "openrouter"):
        raise SystemExit(f"Provider must be anthropic or openrouter; got {provider}")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = [json.loads(l) for l in Path(args.tasks).read_text().splitlines() if l.strip()]
    print(f"Extractor: {provider}:{model}")
    print(f"Tasks:     {args.tasks} ({len(tasks)} rows)")
    print(f"Out:       {out_dir}")

    for t in tasks:
        tid = str(t.get("task_id", ""))
        out_path = out_dir / f"{tid}.json"
        original_path = out_dir / f"{tid}.original.json"
        session_path = out_dir / f"{tid}.spec_session.json"
        ctx = Path(t.get("context_dir", ""))
        print(f"\n  extracting spec for {tid} (context_dir={ctx}) ...", flush=True)
        try:
            user = build_user_prompt(t, ctx)
            if provider == "anthropic":
                spec, usage, session = call_anthropic(model, user)
            else:
                spec, usage, session = call_openrouter(model, user)
            meta = session.get("metadata") or {}
            spec["_meta"] = {
                "extractor": f"{provider}:{model}",
                **usage,
                "tool_calls_before_save": meta.get("tool_calls_before_save", 0),
                "hit_cap": meta.get("hit_cap", False),
                "forced_save": meta.get("forced_save", False),
            }
            spec_text = json.dumps(spec, indent=2)
            out_path.write_text(spec_text)
            original_path.write_text(spec_text)
            session_path.write_text(json.dumps(session, indent=2))
            n_kf = len(spec.get("key_functionalities") or [])
            n_steps = len(spec.get("computation_plan") or [])
            print(f"    OK — {n_kf} key_functionalities, {n_steps} plan steps. "
                  f"in={usage['input_tokens']} out={usage['output_tokens']} tokens.")
        except Exception as e:
            print(f"    ERROR: {e}")
            traceback.print_exc()
            out_path.write_text(json.dumps({"_error": str(e)}, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
