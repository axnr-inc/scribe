"""Spec extractor — Stage 1 of grafting.

Reads manual.md + fees.json + merchant_data.json + payments-readme.md plus a task question,
and emits a structured rule-extraction spec via tool_use (Anthropic models) or
JSON response (OpenRouter models). One spec per task. Saved to results/<arm>/specs/<task_id>.json.

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

CONTEXT_DIR = ROOT / "data/context"


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
You are a spec agent. You read source documents (a manual, schemas, rule catalogs, and similar reference material in the user message) and produce a structured specification an executor agent will use to compute the answer to a user task. You also REVIEW the executor's work when it later calls back to you with a structured summary.

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

# Output (initial extraction)

Use the `save_spec` tool to emit the structured spec. Output ONLY the spec; do not execute code.

# When called for review (follow-up turn)

If you receive a follow-up user message containing the executor's STRUCTURED SUMMARY (with headers `# Step` / `# Computed so far` / `# Pseudo-code` / `# Assumptions` / `# Question`), follow this protocol:

1. Read the executor's structured summary carefully.

2. Use the `read_file` tool to re-read the relevant source documents. You MUST call read_file at least once before replying — verify the executor's assumptions against what the docs actually say.

3. Compare each of the executor's stated assumptions against the docs:
   - If any assumption is INCONSISTENT with the docs, flag it.
   - If the executor missed a rule, definition, or constraint that the docs state, flag it.

4. Reply format:
   - If you found a mistake:
       [Flag: mistake detected]
       <quote the relevant doc passage>
       <revised understanding>
       [Revised spec]
       <FULL revised spec, same schema as the initial save_spec output, with the fix applied>
       The executor will replace its working spec with this revised version.
   - If you found no mistake:
       [No flag]
       <answer the executor's specific question, grounded in doc quotes>
       If the docs are silent on the question, say so explicitly and suggest a defensible default with rationale.

5. What you must NOT do:
   - Do not flag a mistake based on intuition. Flag only when you can quote the doc passage that contradicts the executor's assumption.
   - Do not return a revised spec unless you have flagged a real, doc-grounded mistake.
   - Do not change the spec just because the executor seemed unsure — answer the question instead.

6. NEVER return an empty or "(no content)" response.
   Every review reply MUST include:
   - The header `[Flag: mistake detected]` or `[No flag]` (exactly one of the two)
   - At least one direct quote from a source document (you MUST have called read_file before replying)
   - A concrete diagnostic line stating what you found, e.g. "Found 47 matching rules after re-reading fees.json" or "Confirmed: zero rules match after checking account_type, MCC, and card_scheme constraints"

   When the executor's question is about whether to commit "Not Applicable":
   - You MUST attempt the data lookup yourself before signing off on NA.
   - Format your reply as: "Attempted lookup → found X matching rules. Therefore [NA is correct / NA is wrong; correct rule IDs are Y, Z...]."
   - Do NOT confirm NA based on the executor's report alone; verify by re-reading the relevant files.

   An empty or sentinel-only response is an unacceptable failure mode; if you cannot help, you must at minimum state WHY (e.g., "Unable to access fees.json; cannot verify executor's claim").
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


def call_anthropic(model: str, user: str, max_tokens: int = 8000) -> tuple[dict, dict, dict]:
    """Returns (spec, usage, session) where session is the seed conversation history
    (system + user + assistant) that ask_planner will resume in subsequent turns."""
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not in .env")
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        tools=[SAVE_SPEC_TOOL],
        tool_choice={"type": "tool", "name": "save_spec"},
        messages=[{"role": "user", "content": user}],
    )
    spec = None
    for block in resp.content:
        if block.type == "tool_use" and block.name == "save_spec":
            spec = block.input
            break
    if spec is None:
        raise RuntimeError(f"No tool_use block returned. Stop reason: {resp.stop_reason}")
    usage = {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}
    # Build the session seed. Anthropic's API requires that every tool_use block in an
    # assistant message be followed IMMEDIATELY by a user message containing a tool_result
    # block with the matching tool_use_id. The extraction call ended with a tool_use
    # (save_spec) and never received a tool_result, so we synthesise one — the conversation
    # is now well-formed and ask_planner can simply append another user message.
    assistant_content = [b.model_dump() for b in resp.content]
    tool_use_blocks = [b for b in assistant_content if b.get("type") == "tool_use"]
    synthetic_tool_results = [
        {
            "type": "tool_result",
            "tool_use_id": b["id"],
            "content": "Spec saved. The conversation may continue if the executor escalates a question.",
        }
        for b in tool_use_blocks
    ]
    session = {
        "provider": "anthropic",
        "model": model,
        "system": SYSTEM_PROMPT,
        "tools": [SAVE_SPEC_TOOL],
        "messages": [
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant_content},
            # synthetic tool_result so the conversation is API-valid for follow-ups
            {"role": "user", "content": synthetic_tool_results} if synthetic_tool_results else {"role": "user", "content": ""},
        ],
    }
    return spec, usage, session


def call_openrouter(model: str, user: str, max_tokens: int = 16000) -> tuple[dict, dict, dict]:
    """OpenRouter via OpenAI-compatible endpoint, json_object response format.
    Returns (spec, usage, session) — session is the OpenAI-style messages history
    that ask_planner can resume."""
    from openai import OpenAI
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY not in .env")
    # Tight timeout to fail fast on rare unresponsive requests; no retries — we want to skip & continue.
    client = OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1", timeout=180.0, max_retries=0)

    # Embed the schema in the system prompt for OpenRouter (no tool_use on all providers).
    system_with_schema = SYSTEM_PROMPT + (
        "\n\nOutput requirement: respond with ONE valid JSON object matching this schema. "
        "No markdown, no preamble. Use \\n for any newlines inside string values.\n\n"
        f"Schema:\n{json.dumps(SAVE_SPEC_TOOL['input_schema'], indent=2)}"
    )
    resp = client.chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_with_schema},
            {"role": "user", "content": user},
        ],
    )
    content = resp.choices[0].message.content or ""
    # strip fences if present
    content = content.strip()
    if content.startswith("```"):
        content = content[content.find("\n")+1:]
        if content.rstrip().endswith("```"):
            content = content.rstrip().rstrip("`").rstrip()
    spec = json.loads(content)
    usage = {
        "input_tokens": getattr(resp.usage, "prompt_tokens", 0),
        "output_tokens": getattr(resp.usage, "completion_tokens", 0),
    }
    session = {
        "provider": "openrouter",
        "model": model,
        "system": system_with_schema,
        "messages": [
            {"role": "user", "content": user},
            {"role": "assistant", "content": resp.choices[0].message.content or ""},
        ],
    }
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
        session_path = out_dir / f"{tid}.session.json"
        print(f"\n  extracting spec for {tid} ...", flush=True)
        try:
            user = build_user_prompt(t, context)
            if provider == "anthropic":
                spec, usage, session = call_anthropic(model, user)
            elif provider == "openrouter":
                spec, usage, session = call_openrouter(model, user)
            else:
                raise SystemExit(f"Unknown provider: {provider}")

            spec["_meta"] = {"extractor": f"{provider}:{model}", **usage}
            out_path.write_text(json.dumps(spec, indent=2))
            # Persist the conversation seed so ask_planner can resume in the same
            # "session" (continuity of context — manual.md, fees.json, the assistant's
            # own spec-writing reasoning — all carry forward into escalation calls).
            session_path.write_text(json.dumps(session, indent=2))
            steps = len(spec.get("computation_plan") or [])
            print(f"    OK — {steps} plan steps. in={usage['input_tokens']} out={usage['output_tokens']} tokens.")
            print(f"    session seed → {session_path.name}")
        except Exception as e:
            print(f"    ERROR: {e}")
            out_path.write_text(json.dumps({"_error": str(e)}, indent=2))


if __name__ == "__main__":
    main()
