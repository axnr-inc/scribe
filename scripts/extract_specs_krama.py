"""KramaBench spec extractor — Stage 1 of grafting for the Krama benchmark.

Differences from scripts/extract_specs.py (DABStep variant):
  - No global manual.md / fees.json / helper manifest. Krama is data-lake-first;
    each task has its own per-domain data lake.
  - Spec schema has KramaBench-flavored fields: data_sources_to_use,
    key_functionalities, computation_plan, expected_output_format.
  - User message includes auto-generated file samples from the task's
    context_dir for every file in task.data_sources (mirrors KramaBench's
    "one-shot" DS-Guru variant: schema + a small sample).

Examples:
  python3 scripts/extract_specs_krama.py \\
      --tasks data/splits/krama_archeology12.jsonl \\
      --extractor openrouter:openai/gpt-5 \\
      --out results/krama_smoke/specs

  python3 scripts/extract_specs_krama.py \\
      --tasks data/splits/krama_archeology12.jsonl \\
      --extractor anthropic:claude-opus-4-6 \\
      --out results/krama_smoke/specs
"""
import argparse
import json
import os
import sys
import traceback
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "scripts"))

from spec_extraction_tools import (  # noqa: E402
    make_read_file_tool,
    make_list_files_tool,
    make_read_data_file_tool,
    make_krama_dispatcher,
    run_anthropic_spec_loop,
    run_openai_spec_loop,
)

# Fail fast on missing samplers. Without these, the LLM extracts specs without
# seeing the data (it sees "(unable to sample)") and the resulting specs are
# guesswork. Better to crash here than to silently produce uninformed specs.
try:
    import openpyxl  # noqa: F401  -- needed for pd.read_excel
except ImportError:
    raise SystemExit(
        "openpyxl is required for KramaBench spec extraction (xlsx sampling). "
        "Run: pip install -r requirements.txt"
    )


# ---------------------------------------------------------------------------
# Spec schema: KramaBench-flavored
# ---------------------------------------------------------------------------

SAVE_SPEC_TOOL = {
    "name": "save_spec",
    "description": (
        "Save the data-pipeline spec for this Krama task. This is the single output "
        "of the planning step. After calling this tool, do not call anything else."
    ),
    "input_schema": {
        "type": "object",
        "required": [
            "question_summary", "answer_type",
            "interpretations", "chosen_interpretation",
            "data_sources_to_use", "key_functionalities",
            "computation_plan", "expected_output_format",
        ],
        "properties": {
            "question_summary": {"type": "string"},
            "answer_type": {
                "type": "string",
                "enum": ["numeric_exact", "numeric_approximate",
                         "string_exact", "string_approximate",
                         "list_exact", "list_approximate",
                         "boolean", "other"],
            },
            "interpretations": {
                "type": "array",
                "minItems": 2,
                "maxItems": 4,
                "items": {
                    "type": "object",
                    "required": ["id", "reading", "rationale"],
                    "properties": {
                        "id": {"type": "string", "description": "Short slug, e.g. 'literal', 'calibrated', 'domain'."},
                        "reading": {"type": "string", "description": "Plain-English restatement of how this interpretation reads the question."},
                        "rationale": {"type": "string", "description": "Why a reasonable annotator might pick this — docs evidence, domain convention, etc."},
                    },
                },
                "description": (
                    "I-1: Question-restating gate. Surface 2-4 plausible "
                    "interpretations of the task question BEFORE committing. "
                    "Required even for unambiguous-looking questions — write "
                    "down the alternative readings you considered and rejected."
                ),
            },
            "chosen_interpretation": {
                "type": "object",
                "required": ["id", "reason"],
                "properties": {
                    "id": {"type": "string", "description": "Must match one of `interpretations[].id`."},
                    "reason": {"type": "string", "description": "Why this interpretation is best-supported by the docs + samples you verified."},
                },
                "description": "I-1: Which interpretation the computation_plan implements, with justification.",
            },
            "data_sources_to_use": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Files (by name) the pipeline will read. Subset of the data lake.",
            },
            "key_functionalities": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "High-level steps any correct pipeline must contain. Used "
                    "as the rubric for design-quality scoring; keep these "
                    "abstract enough to be implementation-agnostic."
                ),
            },
            "computation_plan": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Step-by-step pandas pseudocode the executor will follow.",
            },
            "expected_output_format": {"type": "string"},
            "notes_for_executor": {"type": "string"},
        },
    },
}


SYSTEM_PROMPT = """\
You are the SPEC AGENT for a data-science pipeline task. You read raw data
files (CSV, XLSX, JSON, ...) and produce ONE structured specification that an
executor agent will then implement as a pandas pipeline.

This is a MULTI-SHOT extraction. You may call helper tools to verify facts
before committing the spec. You have up to 5 tool turns total; use them
deliberately. A separate PLANNER AGENT handles any later review or revision
if the executor escalates.

# Tools available to you

- read_file(filename): read a small text file from this task's context_dir
  (csv/txt/md/json head). Use for inspecting documentation or small data files.
- list_files(): list every file in the context_dir. Call this if you're
  unsure what's available.
- read_data_file(path, n_rows=15): sample a data file. Supports CSV, XLSX,
  JSON, parquet, txt. Returns shape, columns, dtypes, and head. Use this to
  verify column names and value distributions BEFORE committing a
  computation_plan.
- save_spec(...): emit your final pipeline spec. Terminates extraction.

Required tool-use discipline: BEFORE calling save_spec, you SHOULD verify at
least one key fact via a helper tool. Typical patterns:
- Call read_data_file on every file you plan to use to CONFIRM column names
  and value distributions. The user message includes initial samples but
  re-sampling with more rows or against a non-default sheet often reveals
  the gotchas (compound keys, sentinel "M" missing markers, header rows).
- If a sample shows a multi-row header, re-sample with more rows to find
  the real header.

Calling save_spec on turn 1 without any helper-tool verification is a sign you
didn't actually check the data; do that only when the user message above
already contains everything you need.

# Question-restating gate (I-1)

BEFORE committing to a single computation_plan you MUST surface 2-4 plausible
INTERPRETATIONS of the question in the `interpretations` array. Then pick one
in `chosen_interpretation`, with reasoning grounded in the docs/samples.

This is the FIRST thing your spec must show after question_summary. The
interpretations are not optional — even for questions that look unambiguous,
write down the alternative reading you considered and rejected.

Examples of interpretive axes that produce divergent answers in this benchmark:
- Date convention: raw radiocarbon BP vs calibrated BC vs calendar year
- Direction of time: sort by Age_ky asc (= going BACKWARD in time) vs sort by
  calendar time asc (= going FORWARD in time)
- Rank semantic: low Barrington rank = high importance, so correlation with a
  positive quantity (like population) reads opposite from raw-numeric rank
- "Most northern" / "most southern" tie-breakers
- Dedup granularity: by full key tuple vs by name only vs by name+overlapping-range
- "Strictly greater than" vs "at least" for thresholds
- Inclusive vs exclusive range endpoints
- "Last" / "first" tie-breakers — file order vs date order vs spatial order

You do not have to enumerate ALL of these; pick the 2-4 most relevant for
THIS task and write each as `{id, reading, rationale}`. Then commit to one
via `chosen_interpretation = {id, reason}` and write the computation_plan
to implement THAT interpretation.

The planner_agent has visibility into your alternatives — if the executor's
answer looks wrong, the planner can re-spec against an alternative reading
without re-discovering the ambiguity from scratch.

# Helper functions available to the executor

The executor's Python REPL preamble pre-imports a small set of paradigm-level
helpers from `data/context/krama_helper.py`. When your computation_plan needs
any of these patterns, REFERENCE THE HELPER BY NAME so the executor uses it
instead of re-implementing fragile logic:

- read_multi_header_excel(path, sheet, header_keywords)
    Robust read of xlsx files whose real header row is not row 0
    (use when sampling shows the first 1-3 rows are titles/units/dashes).
- parse_missing_marker(df, cols, markers=("M","NA","-",""))
    Convert sentinel-string missingness (e.g., "M" means missing per the
    KramaBench paper) to NaN BEFORE numeric coercion. Always call this when
    sample dtypes show object on a column you expect to be numeric.
- safe_dedupe(df, keys, agg="first")
    Conflict-aware dedup that surfaces near-duplicate-key collisions instead
    of silently double-counting (use whenever multiple rows share a join key).
- linear_interp_by_key(df, key_col, value_col)
    Linear interpolation of `value_col` against a sorted numeric `key_col`
    (use for chronology/year interpolation tasks; pads gaps without
    extrapolating outside the observed range).
- bp_to_calendar_year(years_bp, reference_year=1950)
    Convert "years before present" (geology/archeology convention) to a
    calendar year. Reference is 1950 CE by archeological convention.
- canonicalize_msa_name(name, suffix="Metropolitan Statistical Area",
                        drop_comma_before_state=True)
    Normalize an FTC MSA string to the canonical "<core>, <STATE>
    Metropolitan Statistical Area" form. Use whenever joining
    State MSA *.csv files or emitting an MSA-typed answer.
- cross_state_msa(name) -> bool
    True iff the MSA's state-token block lists 2+ codes (e.g., "MA-NH").
    Use for any "cross-state MSA" filter.
- sum_subcategory_counts(df, total_col, category_cols, percent_col=None)
    For FTC totals where sub-percentages sum > 100% (a single report
    classified into multiple sub-types), returns the sum-of-counts
    instead of the headline total.
- pct_of_population_for_age_bucket(report_count_2024, share_2024_by_age,
                                   target_age_groups, base_total)
    Back-project a 2024 share onto a 2007 base. CRITICAL: base_total
    must describe the SAME population as share_2024 (do NOT mix
    all-fraud denominator with identity-theft-only share).
- treat_missing_as(df, cols, policy)
    Named NaN policy: policy in {"as_safe","as_unsafe","preserve","drop"}.
    Use when the question says "if no data, assume safe" or similar.
- per_unit_mean_vs_total(df, unit_col, value_col, condition)
    Returns dict {'conditional','baseline','delta'}, all means in the
    same per-unit unit. Use whenever the question asks "how many MORE
    X on days when Y" - do NOT mix a per-unit mean with a sum.
- top_k_pct_threshold(df, value_col, target_share=0.9)
    Returns the smallest fraction (in [0,1], NOT percent) of top-sorted
    rows whose value_col covers target_share of the total. Pareto sweep.
- lag_correlation(series_a, series_b, max_lag,
                  sign_convention="b_leads_a")
    Returns (best_lag, best_r2). Convention "b_leads_a" tests
    series_b.shift(+L) against series_a (canonical for "what lag of
    B best predicts A").
- geopotential_per_mass(r_km, mu_km3_s2=398600.4418, r_earth_km=6371.0)
    Newtonian geopotential per unit mass anchored to Earth's surface.
    Do NOT use g*h for satellite altitudes (linear approximation is
    off by ~15x at 450 km).
- count_two_actor_conflicts(df, conflict_col, second_actor_col=None)
    Brecke-style two-actor mask: hyphen-only is too narrow; accepts
    " vs ", " - " (space-padded), ", ", or a non-null second_actor_col.
- find_column_by_keywords(df, keywords, case_insensitive=True)
    Returns ALL columns whose name contains every keyword. Use when
    a sheet has multiple Age_ky / wet-dry / Al series and the spec
    must pick deliberately (do not auto-select the first match).

When a helper applies, include in `computation_plan` a step like:
"Read `<file>` with read_multi_header_excel(sheet='Sheet1',
header_keywords=['Site','Year'])". Do NOT inline the helper's
implementation in the spec; reference it by name. The executor knows
these symbols and will import them automatically.

# Meta-rules for high-quality data-pipeline specs

1. NAME ONLY FILES IN THE DATA LAKE.
   The user message lists every file available in this task's context_dir plus
   a sample of each. Only reference files that actually exist. If the question
   could be answered from multiple files, pick the ones whose schema matches
   the question's named entities most cleanly.

2. SURFACE GOTCHAS YOU CAN SEE IN THE SAMPLE.
   If a sample reveals non-default semantics — e.g., "M" meaning missing,
   compound encoded keys, multi-row headers, partial subtotals, near-duplicate
   files — name the gotcha in `notes_for_executor` and translate the
   defensive handling into a concrete pandas step in `computation_plan`.

3. KEY FUNCTIONALITIES ARE IMPLEMENTATION-AGNOSTIC.
   `key_functionalities` is the rubric for whether ANY correct pipeline did
   the right transformations (e.g., "join climate to chronology by interpolated
   year"). Keep these abstract — they should be true regardless of whether the
   executor uses pandas, polars, or raw SQL. Avoid library names here.

4. COMPUTATION PLAN IS CONCRETE PANDAS.
   `computation_plan` is the executor's recipe — use pandas function names,
   actual column names from the samples, dtype assumptions when relevant.

5. EXPECTED OUTPUT FORMAT IS AUTHORITATIVE.
   State the answer type AND the literal formatting rule (e.g., "single float
   rounded to 4 decimals", "comma-separated list of beach names, alphabetical").

6. EDGE CASES.
   State what the executor should do when: no rows match, the schema differs
   from the sample, an expected column is missing, the answer would be NaN.

# Output

Use the `save_spec` tool to emit the structured spec. Output ONLY the spec;
do not execute code.
"""


# ---------------------------------------------------------------------------
# Data-lake sampling: produce a text bundle the spec_agent sees in the user msg
# ---------------------------------------------------------------------------

def sample_csv(path: Path, n_rows: int = 15) -> str:
    try:
        import pandas as pd
        df = pd.read_csv(path, nrows=n_rows, low_memory=False)
        return (
            f"shape (head): {df.shape}; columns: {list(df.columns)}\n"
            f"dtypes:\n{df.dtypes.to_string()}\n"
            f"head:\n{df.to_string(index=False)}\n"
        )
    except Exception as e:
        return f"(unable to sample CSV: {e})"


def sample_xlsx(path: Path, sheets: int = 3, rows: int = 10) -> str:
    try:
        import pandas as pd
        xls = pd.ExcelFile(path)
        out = [f"sheets: {xls.sheet_names}"]
        for sn in xls.sheet_names[:sheets]:
            try:
                df = pd.read_excel(path, sheet_name=sn, nrows=rows)
                out.append(f"--- sheet '{sn}' ---")
                out.append(f"shape (head): {df.shape}; columns: {list(df.columns)[:20]}")
                out.append(f"head:\n{df.head(rows).to_string(index=False)}")
            except Exception as e:
                out.append(f"--- sheet '{sn}' (error: {e}) ---")
        return "\n".join(out)
    except Exception as e:
        return f"(unable to sample XLSX: {e})"


def sample_json(path: Path, max_chars: int = 4000) -> str:
    try:
        raw = path.read_text()[:max_chars]
        return f"head ({max_chars} chars):\n{raw}"
    except Exception as e:
        return f"(unable to sample JSON: {e})"


def sample_text(path: Path, max_chars: int = 2000) -> str:
    try:
        return f"head ({max_chars} chars):\n{path.read_text()[:max_chars]}"
    except Exception as e:
        return f"(unable to read: {e})"


def sample_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".csv":
        return sample_csv(path)
    if ext in (".xlsx", ".xls"):
        return sample_xlsx(path)
    if ext == ".json":
        return sample_json(path)
    if ext in (".txt", ".md", ".tsv"):
        return sample_text(path)
    return f"(no sampler for {ext} — file size {path.stat().st_size} bytes)"


def list_data_lake(context_dir: Path, limit: int = 50) -> list[Path]:
    if not context_dir.exists():
        return []
    files = sorted([p for p in context_dir.iterdir() if p.is_file()])
    return files[:limit]


def build_user_prompt(task: dict, context_dir: Path) -> str:
    """Assemble the user message: question + per-file samples for every file in
    task.data_sources, plus a listing of the wider data lake (with size only)."""
    data_sources: list[str] = task.get("data_sources") or []
    # Sample every named data source. If data_sources is empty, sample every
    # file in the directory (capped).
    files_to_sample: list[Path] = []
    if data_sources:
        for name in data_sources:
            p = context_dir / name
            if p.exists():
                files_to_sample.append(p)
            else:
                files_to_sample.append(p)  # missing — sampler will note
    else:
        files_to_sample = list_data_lake(context_dir)

    all_files = list_data_lake(context_dir)
    lake_listing = "\n".join(
        f"- {p.name}  ({p.stat().st_size if p.exists() else '?'} bytes)"
        for p in all_files
    ) or "(empty data lake)"

    sample_blocks: list[str] = []
    samples_attempted = 0
    samples_failed = 0
    for p in files_to_sample:
        block = [f"## {p.name}"]
        if p.exists():
            samples_attempted += 1
            sample_text = sample_file(p)
            block.append(sample_text)
            # Heuristic: "unable to sample" / "error" / "no sampler" ⇒ failed.
            lower = sample_text.lower()
            if ("unable to sample" in lower
                    or "no sampler for" in lower
                    or (sample_text.startswith("(") and "error" in lower)):
                samples_failed += 1
        else:
            samples_attempted += 1
            samples_failed += 1
            block.append(f"(file missing: {p})")
        sample_blocks.append("\n".join(block))

    # Loud banner if too many sample attempts failed. The LLM should KNOW it's
    # working blind so it doesn't over-commit to a speculative computation_plan
    # built from filename alone — bug 7 in the integration audit.
    banner = ""
    if samples_attempted and samples_failed == samples_attempted:
        banner = (
            "# WARNING — ALL FILE SAMPLES FAILED\n"
            "You have NO concrete schema/sample for any flagged file. Your spec will "
            "be speculative unless you mark every assumption about column names, "
            "dtypes, and values as [UNVERIFIED] in notes_for_executor AND add a "
            "first computation_plan step `Inspect files via df.head() / df.dtypes / "
            "df.shape BEFORE proceeding`. The executor will run that step first."
        )
    elif samples_attempted and samples_failed > 0:
        banner = (
            f"# NOTE — {samples_failed}/{samples_attempted} file samples failed\n"
            "Some samples below are error strings. Treat assumptions about those "
            "files as unverified in `notes_for_executor`."
        )

    parts = []
    if banner:
        parts.append(banner)
    parts += [
        "# Data lake (all files in this task's context_dir)",
        lake_listing,
        "",
        f"# Sampled files (every file flagged as relevant for this task)",
        "\n\n".join(sample_blocks) if sample_blocks else "(none flagged)",
        "",
        "# Task",
        f"task_id: {task.get('task_id','')}",
        f"question: {task.get('question','')}",
        f"guidelines: {task.get('guidelines','')}",
        f"answer_type: {task.get('answer_type','')}",
        "",
        "Analyze the task and the sampled files. Produce a structured Krama spec "
        "with key_functionalities (abstract steps for the rubric) and a concrete "
        "pandas computation_plan the executor will implement.",
    ]
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# API calls — same provider switching as DABStep extract_specs.py
# ---------------------------------------------------------------------------

def _krama_helper_tools(context_dir: Path) -> list[dict]:
    return [
        make_read_file_tool(context_dir, suggest_for_sqlite=False),
        make_list_files_tool(context_dir),
        make_read_data_file_tool(),
    ]


def call_anthropic(model: str, user: str, context_dir: Path, max_tokens: int = 8000):
    """Multi-shot extraction via Anthropic native tool_use."""
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not in .env")
    client = anthropic.Anthropic()
    spec, usage, session, telem = run_anthropic_spec_loop(
        client=client,
        model=model,
        system=SYSTEM_PROMPT,
        user_prompt=user,
        helper_tools=_krama_helper_tools(context_dir),
        save_spec_tool=SAVE_SPEC_TOOL,
        dispatch=make_krama_dispatcher(context_dir),
        max_tokens=max_tokens,
    )
    if spec is None:
        raise RuntimeError(
            f"spec_agent never called save_spec (hit_cap={telem['hit_cap']}, "
            f"tool_calls_before_save={telem['tool_calls_before_save']})"
        )
    return spec, usage, session


def call_openrouter(model: str, user: str, context_dir: Path, max_tokens: int = 16000):
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
        helper_tools=_krama_helper_tools(context_dir),
        save_spec_tool=SAVE_SPEC_TOOL,
        dispatch=make_krama_dispatcher(context_dir),
        provider_label="openrouter",
        max_tokens=max_tokens,
    )
    if spec is None:
        raise RuntimeError(
            f"spec_agent never called save_spec (hit_cap={telem['hit_cap']}, "
            f"tool_calls_before_save={telem['tool_calls_before_save']})"
        )
    return spec, usage, session


def call_fireworks(model: str, user: str, context_dir: Path, max_tokens: int = 16000,
                   key_var: str = "FIREWORKS_API_KEY2"):
    """Multi-shot extraction via Fireworks (OpenAI-compatible tool-calling).

    ~5x faster than OpenRouter on GLM-5.1 (smoke test: 0.97s vs 4.46s/call).
    `key_var` lets the caller pick FIREWORKS_API_KEY vs FIREWORKS_API_KEY2 for
    sharding."""
    from openai import OpenAI
    key = os.environ.get(key_var)
    if not key:
        raise SystemExit(f"{key_var} not in .env")
    client = OpenAI(api_key=key, base_url="https://api.fireworks.ai/inference/v1",
                    timeout=180.0, max_retries=0)
    spec, usage, session, telem = run_openai_spec_loop(
        client=client,
        model=model,
        system=SYSTEM_PROMPT,
        user_prompt=user,
        helper_tools=_krama_helper_tools(context_dir),
        save_spec_tool=SAVE_SPEC_TOOL,
        dispatch=make_krama_dispatcher(context_dir),
        provider_label="fireworks",
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
    p.add_argument("--tasks", required=True, help="Krama tasks JSONL from kramabench_adapter.py")
    p.add_argument("--extractor", required=True,
                   help="Format: <provider>:<model_id>. Provider: anthropic | openrouter")
    p.add_argument("--out", required=True, help="Output directory for spec JSON files")
    args = p.parse_args()

    if ":" not in args.extractor:
        raise SystemExit("--extractor must be <provider>:<model_id>")
    provider, model = args.extractor.split(":", 1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = [json.loads(l) for l in Path(args.tasks).read_text().splitlines() if l.strip()]
    print(f"Extractor: {provider}:{model}")
    print(f"Tasks:     {args.tasks} ({len(tasks)} rows)")
    print(f"Out:       {out_dir}")

    for t in tasks:
        tid = str(t.get("task_id", t.get("id", "")))
        out_path = out_dir / f"{tid}.json"
        original_path = out_dir / f"{tid}.original.json"
        session_path = out_dir / f"{tid}.spec_session.json"
        ctx = Path(t.get("context_dir", ""))
        print(f"\n  extracting spec for {tid} (context_dir={ctx}) ...", flush=True)
        try:
            user = build_user_prompt(t, ctx)
            if provider == "anthropic":
                spec, usage, session = call_anthropic(model, user, ctx)
            elif provider == "openrouter":
                spec, usage, session = call_openrouter(model, user, ctx)
            elif provider == "fireworks":
                spec, usage, session = call_fireworks(model, user, ctx, key_var="FIREWORKS_API_KEY")
            elif provider == "fireworks2":
                spec, usage, session = call_fireworks(model, user, ctx, key_var="FIREWORKS_API_KEY2")
            else:
                raise SystemExit(f"Unknown provider: {provider}")

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
            n_tools = meta.get("tool_calls_before_save", 0)
            print(f"    OK — {n_kf} key_functionalities, {n_steps} plan steps, {n_tools} tool calls. "
                  f"in={usage['input_tokens']} out={usage['output_tokens']} tokens.")
        except Exception as e:
            print(f"    ERROR: {e}")
            traceback.print_exc()
            out_path.write_text(json.dumps({"_error": str(e)}, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
