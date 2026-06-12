"""extract_specs_krama_multi.py — I-2 multi-stance spec sampling.

For each task, generate N=3 specs under different ambiguity-resolution stances:
- stance_literal: take the question's wording as strictly literal; default to
  raw / uncalibrated / inclusive interpretations.
- stance_domain: apply domain conventions (calibrated dates, calendar-time
  direction, importance-axis ranks, dedup by natural key, etc.).
- stance_strict: apply the MOST restrictive interpretation of every threshold,
  filter, and dedup rule.

Each spec is saved as `<tid>.stance_<X>.json` alongside the standard `<tid>.json`
(which still gets the default extraction so the existing pilot pipeline keeps
working). A separate adjudicator step (TODO: scripts/select_winning_spec.py)
will read the 3 candidate specs + their executor answers and pick a winner.

This script is part of the I-2 intervention from docs/findings/17_pilot_v2_diagnosis.md.
For v3 pilot we ship the extractor but do NOT yet run the 3× executor pass —
v3 relies on I-1 (interpretations field in single spec) + I-3 (SPEC_DOUBT
verdict for runtime dissent). I-2 is the v4 fallback if v3 still shows F-E.

USAGE:
    python3 scripts/extract_specs_krama_multi.py \\
        --tasks data/splits/krama_failed5_v2.jsonl \\
        --extractor openrouter:deepseek/deepseek-chat-v3.1 \\
        --out results/pilot_v3/krama5/specs_multi \\
        --stances literal,domain,strict
"""

from __future__ import annotations
import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Reuse the single-shot Krama extractor's machinery by importing it directly.
KRAMA_MOD_PATH = ROOT / "scripts" / "extract_specs_krama.py"
spec = importlib.util.spec_from_file_location("extract_specs_krama", KRAMA_MOD_PATH)
krama_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(krama_mod)


STANCE_ADDENDA = {
    "literal": (
        "\n# Stance for this extraction: LITERAL\n"
        "Interpret the question's wording as strictly literal. Prefer raw "
        "(uncalibrated) values when the question doesn't specify, default to "
        "inclusive range endpoints when ambiguous, and treat 'last' / 'first' "
        "tie-breakers as file-order. Your `chosen_interpretation` should be "
        "the most literal of the alternatives you surface."
    ),
    "domain": (
        "\n# Stance for this extraction: DOMAIN-CONVENTIONAL\n"
        "Apply field-specific conventions even when the question doesn't "
        "spell them out. For archaeology: prefer CALIBRATED BC dates over raw "
        "14C BP, calendar-time direction for trend questions, Barrington-rank "
        "as inverse-importance. For climate: select Age_ky column that pairs "
        "with the elemental panel by sample-row spacing. Your "
        "`chosen_interpretation` should be the domain-conventional one."
    ),
    "strict": (
        "\n# Stance for this extraction: STRICT\n"
        "Apply the MOST restrictive interpretation of every threshold and "
        "filter: 'greater than X' means STRICTLY greater (not >=), date "
        "ranges are EXCLUSIVE at endpoints when ambiguous, dedup is by the "
        "NARROWEST natural key (e.g. by name only, not by name+year-range). "
        "Your `chosen_interpretation` should be the strictest one."
    ),
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", required=True)
    p.add_argument("--extractor", required=True,
                   help="Format: <provider>:<model_id>. Same as extract_specs_krama.py.")
    p.add_argument("--out", required=True)
    p.add_argument("--stances", default="literal,domain,strict",
                   help="Comma-separated stance names to extract. "
                        "Available: literal, domain, strict.")
    args = p.parse_args()

    stances = [s.strip() for s in args.stances.split(",") if s.strip()]
    unknown = [s for s in stances if s not in STANCE_ADDENDA]
    if unknown:
        raise SystemExit(f"Unknown stances: {unknown}. Available: {list(STANCE_ADDENDA)}")

    if ":" not in args.extractor:
        raise SystemExit("--extractor must be <provider>:<model_id>")
    provider, model = args.extractor.split(":", 1)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    tasks = [json.loads(l) for l in Path(args.tasks).read_text().splitlines() if l.strip()]
    print(f"Extractor: {provider}:{model}")
    print(f"Stances:   {stances}")
    print(f"Tasks:     {args.tasks} ({len(tasks)} rows)")
    print(f"Out:       {out_dir}")

    # Patch the system prompt for each stance, call the existing extractor.
    base_system_prompt = krama_mod.SYSTEM_PROMPT
    for t in tasks:
        tid = str(t.get("task_id", t.get("id", "")))
        for stance in stances:
            print(f"\n  [{tid} / {stance}] extracting ...", flush=True)
            krama_mod.SYSTEM_PROMPT = base_system_prompt + STANCE_ADDENDA[stance]
            try:
                # Reuse extract_specs_krama's internal extraction routine.
                # The single-task path is implemented inline in its main(); we
                # bypass that by calling the underlying tool-loop directly.
                # Signatures from extract_specs_krama.py:345 / :444 / :468:
                #   build_user_prompt(task, context_dir)
                #   call_openrouter(model, user, context_dir, max_tokens=...)
                from pathlib import Path as _Path
                ctx = _Path(t["context_dir"]) if t.get("context_dir") else _Path(".")
                user = krama_mod.build_user_prompt(t, ctx)
                if provider == "openrouter":
                    result_spec, usage, session = krama_mod.call_openrouter(model, user, ctx)
                elif provider == "anthropic":
                    result_spec, usage, session = krama_mod.call_anthropic(model, user, ctx)
                else:
                    raise SystemExit(f"Unknown provider: {provider}")

                meta = (session.get("metadata") or {})
                result_spec.setdefault("_meta", {})
                result_spec["_meta"].update({
                    "extractor": f"{provider}:{model}",
                    "stance": stance,
                    **usage,
                    "tool_calls_before_save": meta.get("tool_calls_before_save", 0),
                })
                out_path = out_dir / f"{tid}.stance_{stance}.json"
                out_path.write_text(json.dumps(result_spec, indent=2))
                (out_dir / f"{tid}.stance_{stance}.spec_session.json").write_text(
                    json.dumps(session, indent=2))
                print(f"    OK — {len(result_spec.get('computation_plan',[]))} steps, "
                      f"{meta.get('tool_calls_before_save',0)} tool calls. "
                      f"in={usage['input_tokens']} out={usage['output_tokens']}.")
            except Exception as e:
                print(f"    ERROR: {e}")
                (out_dir / f"{tid}.stance_{stance}.json").write_text(
                    json.dumps({"_error": str(e), "_meta": {"stance": stance}}, indent=2))
            finally:
                krama_mod.SYSTEM_PROMPT = base_system_prompt


if __name__ == "__main__":
    main()
