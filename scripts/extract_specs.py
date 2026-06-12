"""Spec extractor — Stage 1 of grafting.

Reads manual.md + fees.json + merchant_data.json + payments-readme.md plus a task question,
and emits a structured rule-extraction spec via tool_use. One spec per task.

P2b upgrades (this version):
  - P2b.1: spec_agent now has a `read_file` tool (manifest scoped to data/context/).
  - P2b.2: spec_agent now has `query_fees` and `list_files` for programmatic lookup.
  - P2b.3: multi-shot reasoning loop (cap 5 tool turns). The model may call any
    helper tool before save_spec; loop terminates when save_spec is called.

Examples:
  # Sonnet as planner:
  python scripts/extract_specs.py \\
      --tasks data/target_tasks.jsonl \\
      --extractor anthropic:claude-sonnet-4-6 \\
      --out results/sonnet_kimi/specs

  # Kimi as planner (self-graft):
  python scripts/extract_specs.py \\
      --tasks data/target_tasks.jsonl \\
      --extractor openrouter:moonshotai/kimi-k2.6 \\
      --out results/kimi_kimi/specs

  # Haiku as planner:
  python scripts/extract_specs.py \\
      --tasks data/target_tasks.jsonl \\
      --extractor anthropic:claude-haiku-4-5 \\
      --out results/haiku_kimi/specs
"""
import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "scripts"))

CONTEXT_DIR = ROOT / "data/context"

from spec_extraction_tools import (  # noqa: E402
    make_read_file_tool,
    make_list_files_tool,
    make_query_fees_tool,
    make_dabstep_dispatcher,
    run_anthropic_spec_loop,
    run_openai_spec_loop,
)


SAVE_SPEC_TOOL = {
    "name": "save_spec",
    "description": (
        "Save the rule-extraction spec for this task. This is the single output of the rule-extraction step. "
        "After calling this tool, do not call anything else."
    ),
    "input_schema": {
        "type": "object",
        "required": [
            "question_summary", "answer_type",
            "merchant", "date_filter",
            "applicable_card_schemes", "matching_logic",
            "computation_plan", "expected_output_format",
        ],
        "properties": {
            "question_summary": {"type": "string"},
            "answer_type": {"type": "string", "enum": ["list_of_fee_ids", "total_eur", "single_number", "boolean", "other"]},
            "merchant": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "account_type": {"type": ["string", "null"]},
                    "merchant_category_code": {"type": ["integer", "null"]},
                    "capture_delay": {"type": ["string", "null"]},
                    "acquirers": {"type": "array", "items": {"type": "string"}},
                    "notes": {"type": "string"},
                },
            },
            "date_filter": {
                "type": "object",
                "required": ["kind", "year"],
                "properties": {
                    "kind": {"type": "string", "enum": ["specific_day", "month", "year", "range"]},
                    "year": {"type": "integer"},
                    "month": {"type": ["integer", "null"]},
                    "day_of_year": {"type": ["integer", "null"]},
                    "month_name": {"type": ["string", "null"]},
                    "iso_date": {"type": ["string", "null"]},
                },
            },
            "applicable_card_schemes": {"type": "array", "items": {"type": "string"}},
            "matching_logic": {
                "type": "object",
                "required": ["convention", "fields_to_match"],
                "properties": {
                    "convention": {"type": "string"},
                    "fields_to_match": {"type": "array", "items": {"type": "string"}},
                    "derived_fields": {"type": "array", "items": {"type": "string"}},
                },
            },
            "computation_plan": {"type": "array", "items": {"type": "string"}},
            "expected_output_format": {"type": "string"},
            "notes_for_executor": {"type": "string"},
        },
    },
}


SYSTEM_PROMPT = """\
You are the SPEC AGENT. You read source documents (a manual, schemas, rule catalogs, and similar reference material in the user message) and produce ONE structured specification an executor agent will then use to compute the answer to a user task.

This is a MULTI-SHOT extraction. You may call helper tools to verify facts before committing to the spec. You have up to 5 tool turns total; use them deliberately. A separate PLANNER AGENT (with its own prompt and tools) handles any later review or revision when the executor escalates.

# Tools available to you

- read_file(filename): re-read a source artifact from data/context/ (see the
  manifest in the tool description). Use this to re-check a definition or
  formula before committing your spec.
- list_files(): list every file in data/context/. Call this if you're unsure
  what's available.
- query_fees(filters, limit=50): programmatic lookup over fees.json with
  correct wildcard semantics (null OR empty-list = matches any value). Prefer
  this over scanning fees.json by eye when enumerating rules.
- save_spec(...): emit your final structured spec. This terminates extraction.

Required tool-use discipline: BEFORE calling save_spec, you SHOULD verify at
least one key fact via a helper tool. Typical patterns:
- If the question names a merchant, call query_fees with merchant attributes
  (look them up via read_file('merchant_data.json') first) to enumerate the
  actual applicable fee rules.
- If the question references a named metric or formula, call read_file('manual.md')
  to re-anchor on the exact definition before drafting the computation_plan.
- If you're unsure about a column or field, call read_file('payments-readme.md').

Calling save_spec on turn 1 without any helper-tool verification is a sign you
didn't actually check the docs; do that only when the user message above
already contains everything you need.

# Meta-rules for high-quality specs

1. CONNECT DOCS-DEFINED RULES TO CODE.
   When the source documents define a rule, formula, or filter predicate explicitly, translate the abstract description into the concrete pandas code pattern the executor should use. Do not leave a doc-stated rule in English when the docs gave you enough specificity to translate.

2. SURFACE DOCS-DEFINED FORMULAS WHEN THE QUESTION USES THE METRIC NAME.
   If the user task references a named metric, concept, or rule, and the source documents DEFINE that named entity, surface the docs-defined formula verbatim in the spec — even if the user task does not explicitly invoke the docs section that defines it.

3. TRANSLATE NON-DEFAULT SEMANTICS INTO CODE PATTERNS.
   When the source documents define non-default behaviour for a concept that diverges from typical SQL/pandas defaults, translate the abstract rule into the concrete code pattern. Spell out the filter predicate explicitly rather than describing the behaviour in English.

4. IDENTIFY EDGE CASES.
   Explicitly state what the executor should do for: empty result set, no matching rule, concepts the question references that are NOT defined in the docs. State these as named branches in the computation_plan.

5. FILTER EXPLICITNESS.
   Spell out filter predicates in pandas notation, not English alone. Include all relevant fields with their wildcard/null handling.

# Output

Call the `save_spec` tool ONCE with the final structured spec. Do not call other tools after save_spec.
"""


def load_context() -> dict:
    return {
        "manual.md":              (CONTEXT_DIR / "manual.md").read_text(),
        "fees.json":              (CONTEXT_DIR / "fees.json").read_text(),
        "merchant_data.json":     (CONTEXT_DIR / "merchant_data.json").read_text(),
        "payments-readme.md":     (CONTEXT_DIR / "payments-readme.md").read_text(),
    }


HELPER_MANIFEST = """\
# Executor environment — helpers available to call by name

The executor's Python REPL imports the following canonical helpers from
`data/context/dabstep_helper.py` at startup. Reference them by name in your
`computation_plan` (per meta-rule #10) rather than inlining their definitions
or rewriting their logic:

- `list_match(rule_val, txn_val)` — list-field wildcard match. True iff
  `rule_val` is None, is an empty list `[]`, or contains `txn_val`. Use for
  rule fields `account_type`, `merchant_category_code`, `aci`.

- `scal_match(rule_val, txn_val)` — scalar-field wildcard match. True iff
  `rule_val` is None / NaN, or equals `txn_val`. Use for rule fields
  `card_scheme`, `is_credit`, `capture_delay`, `monthly_volume`,
  `monthly_fraud_level` (and `intracountry` after bool cast).

- `attr_matches_wildcard(rule_attr, query_val)` — same semantics as
  `list_match` but framed for attribute-filter questions (e.g. "average fee
  that NexPay charges for account_type=D").

- `rule_applies(rule, txn, merchant=None)` — full per-txn rule-applicability
  predicate over all eight rule fields (uses `scal_match` + `list_match`
  internally, casts `is_credit` to bool, handles `intracountry`). Pass the
  rule dict, a txn dict-like with the needed fields, and an optional merchant
  dict (for `capture_delay_bucket`, `account_type`, `mcc`).

- `fee_for_rule(rule, eur_amount)` — Manual §5 fee formula
  `fixed_amount + rate * eur_amount / 10000`.

Using these helpers shrinks the computation_plan from ~25 inline-pandas
steps to ~8 high-level steps; the executor follows shorter plans more
reliably. When the question shape matches what `rule_applies` /
`attr_matches_wildcard` handle, you should typically write the plan as:

  1. Build `merchant_ctx` and per-txn fields.
  2. Filter `fees[fees['card_scheme'] == txn.card_scheme]`.
  3. Pick applicable rules via `rule_applies(rule, txn, merchant_ctx)`.
  4. Pick winner by max specificity (then min ID).
  5. Compute fee via `fee_for_rule(winner, eur_amount)`.
  6. Aggregate + format.
"""


def build_user_prompt(task: dict, context: dict) -> str:
    parts = [
        "# Context files\n",
        "## manual.md", "```", context["manual.md"], "```\n",
        "## fees.json (complete — all ~1000 rules)",
        "```json", context["fees.json"], "```\n",
        "## merchant_data.json", "```json", context["merchant_data.json"], "```\n",
        "## payments-readme.md", "```", context["payments-readme.md"], "```\n",
        HELPER_MANIFEST,
        "# Task",
        f"task_id: {task.get('task_id', task.get('id',''))}",
        f"question: {task.get('question', '')}",
        f"guidelines: {task.get('guidelines', '')}",
        "",
        "Analyze the task and produce the structured rule-extraction spec. "
        "Focus on the FACTS the executor needs (merchant attrs, date filter, fields to match) and the PLAN, "
        "not on listing every fee rule.",
    ]
    return "\n\n".join(parts)


def _dabstep_helper_tools() -> list[dict]:
    return [
        make_read_file_tool(CONTEXT_DIR, suggest_for_sqlite=False),
        make_list_files_tool(CONTEXT_DIR),
        make_query_fees_tool(),
    ]


def call_anthropic(model: str, user: str, max_tokens: int = 8000) -> tuple[dict, dict, dict]:
    """Multi-shot extraction via Anthropic native tool_use. Returns (spec, usage, session)."""
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not in .env")
    client = anthropic.Anthropic()
    spec, usage, session, telem = run_anthropic_spec_loop(
        client=client,
        model=model,
        system=SYSTEM_PROMPT,
        user_prompt=user,
        helper_tools=_dabstep_helper_tools(),
        save_spec_tool=SAVE_SPEC_TOOL,
        dispatch=make_dabstep_dispatcher(CONTEXT_DIR),
        max_tokens=max_tokens,
    )
    if spec is None:
        raise RuntimeError(
            f"spec_agent never called save_spec (hit_cap={telem['hit_cap']}, "
            f"forced_save={telem['forced_save']}, tool_calls_before_save={telem['tool_calls_before_save']})"
        )
    return spec, usage, session


def call_openrouter(model: str, user: str, max_tokens: int = 16000) -> tuple[dict, dict, dict]:
    """Multi-shot extraction via OpenRouter (OpenAI tool-calling). Returns (spec, usage, session)."""
    from openai import OpenAI
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY not in .env")
    client = OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1", timeout=180.0, max_retries=0)
    spec, usage, session, telem = run_openai_spec_loop(
        client=client,
        model=model,
        system=SYSTEM_PROMPT,
        user_prompt=user,
        helper_tools=_dabstep_helper_tools(),
        save_spec_tool=SAVE_SPEC_TOOL,
        dispatch=make_dabstep_dispatcher(CONTEXT_DIR),
        provider_label="openrouter",
        max_tokens=max_tokens,
    )
    if spec is None:
        raise RuntimeError(
            f"spec_agent never called save_spec (hit_cap={telem['hit_cap']}, "
            f"forced_save={telem['forced_save']}, tool_calls_before_save={telem['tool_calls_before_save']})"
        )
    return spec, usage, session


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", required=True, help="Path to tasks JSONL (e.g. data/target_tasks.jsonl)")
    p.add_argument("--extractor", required=True, help="Format: <provider>:<model_id>. Provider: anthropic | openrouter")
    p.add_argument("--out", required=True, help="Output directory for spec JSON files")
    args = p.parse_args()

    if ":" not in args.extractor:
        raise SystemExit("--extractor must be <provider>:<model_id>")
    provider, model = args.extractor.split(":", 1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = [json.loads(l) for l in Path(args.tasks).read_text().splitlines() if l.strip()]
    context = load_context()
    print(f"Extractor: {provider}:{model}")
    print(f"Tasks:     {args.tasks} ({len(tasks)} rows)")
    print(f"Out:       {out_dir}")

    for t in tasks:
        tid = str(t.get("task_id", t.get("id", "")))
        out_path = out_dir / f"{tid}.json"
        original_path = out_dir / f"{tid}.original.json"
        session_path = out_dir / f"{tid}.spec_session.json"
        print(f"\n  extracting spec for {tid} ...", flush=True)
        try:
            user = build_user_prompt(t, context)
            if provider == "anthropic":
                spec, usage, session = call_anthropic(model, user)
            elif provider == "openrouter":
                spec, usage, session = call_openrouter(model, user)
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
            # <tid>.json is the CURRENT spec; planner overwrites it on SPEC_WRONG revisions.
            out_path.write_text(spec_text)
            # <tid>.original.json is the immutable initial extraction (for audit / ablation).
            original_path.write_text(spec_text)
            # <tid>.spec_session.json is the spec_agent's extraction conversation, kept for
            # audit only. The planner_agent does NOT resume this session; it starts its own.
            session_path.write_text(json.dumps(session, indent=2))
            steps = len(spec.get("computation_plan") or [])
            n_tools = meta.get("tool_calls_before_save", 0)
            print(f"    OK — {steps} plan steps, {n_tools} tool calls before save. "
                  f"in={usage['input_tokens']} out={usage['output_tokens']} tokens.")
            print(f"    spec → {out_path.name} + {original_path.name} (audit: {session_path.name})")
        except Exception as e:
            print(f"    ERROR: {e}")
            out_path.write_text(json.dumps({"_error": str(e)}, indent=2))


if __name__ == "__main__":
    main()
