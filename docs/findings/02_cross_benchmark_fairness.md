# Cross-benchmark fairness — asymmetries that affect comparison

This document catalogs what is SHARED, what is INTENTIONALLY DIFFERENT, and what is currently asymmetric in ways that confound cross-benchmark numbers. Updated after the P4 audit + P4 cleanup + 3-bench smoke + config normalization.

## Shared (good — comparable)

| Component | Status |
|---|---|
| Executor model | Kimi-K2.6 on Fireworks across all 3 |
| Agent loop | pi-agent-core ReAct |
| Spec escalation tool | `ask_planner_agent` |
| Spec refresh tool | `read_current_spec` |
| Spec versioning files | `.original.json` / `.rev{N}.json` / `.revisions.jsonl` |
| 5-verdict cascade | yes |
| Planner system prompt | benchmark-agnostic (post Agent 4 generic-language rewrite + R1-R5 pre-reply verification baked in) |
| Spec injection mechanism | `renderSpecFromPath` with per-schema dispatch |
| Required-fields validation | `requiredFieldsForSpec` per-schema dispatch |
| Session lifecycle | per-task `planner_session.json` |
| EC1-EC4 mitigations | shared code path |
| EC5 (recurring escalation reminder) | shared code path in `after_tool` hook |
| Planner model | GPT-5 on OpenRouter across all 3 (post-normalization) |
| Max iterations | 40 across all 3 (post-normalization) |
| `thinking` setting | `null` across all 3 (post-normalization) |
| Graders write `results.csv` + `results.json` | yes (post P4 cleanup fix #5) |

## Intentionally different (by design — fine)

| Component | DABStep | LiveSQL | Krama |
|---|---|---|---|
| Compute tool | `run_python` | `run_sql` | `run_python` |
| Spec schema fields | merchant / date_filter / matching_logic | tables_needed / cte_plan / kb_formulas | data_sources / key_functionalities |
| Spec renderer | `renderDabstepSpec` | `renderLivesqlSpec` | `renderKramaSpec` |
| Data layout | flat `data/context/` | per-task sqlite | per-domain `input/` |
| Structured-summary header | `# Pseudo-code` | `# SQL` | `# Pseudo-code` |
| File manifest in planner | hand-written DABStep manifest (gated on `manual.md` presence) | auto-listed | auto-listed |
| Helper tools | `query_fees` (gated on `fees.json` presence) | none | none |

## Asymmetries that STILL confound (open)

### A1 — `HELPER_MANIFEST` (DABStep-only)

**What:** DABStep's `extract_specs.py` injects a ~40-line "canonical Python helpers" manifest (`list_match`, `scal_match`, `rule_applies`, `fee_for_rule`) into the spec_agent's user prompt. The spec_agent is encouraged to reference helpers by name, producing shorter computation_plans (~8 steps vs ~25 inline pandas).

**Impact:** DABStep specs are pre-compressed. Executor follows shorter plans more reliably. Cross-benchmark accuracy comparison conflates "Kimi follows DABStep specs better" with "DABStep specs are easier to follow."

**Status:** Documented; defer per user decision (case-by-case). Per Type B audit, building LiveSQL helpers (latest-record-per-entity is the canonical case) is high-signal future work.

### A2 — LiveSQL MANDATORY pre-commit gate

**What:** `src/prompts/livesql_grafted.yaml` has a hard rule: executor MUST call `ask_planner_agent` before emitting `FINAL SQL`. DABStep and Krama only have the soft iter-15 rule (now reinforced by EC5).

**Impact:** LiveSQL gets MUCH stronger escalation enforcement than the other two. A direct cross-benchmark comparison of "escalation rate" or "planner-saved tasks" is biased upward for LiveSQL.

**Status:** Intentional — the pre-commit gate was responsible for v3's 15/15. Cannot port to DABStep/Krama as-is (they don't have a single SQL emission point). Worth documenting as benchmark-paradigm-specific (the SQL paradigm allows a hard pre-commit gate; the pandas paradigm doesn't).

### A3 — Spec extractor `HELPER_MANIFEST` vs R1-R5 vs neither

After Fix #4 (R1-R5 moved to planner prompt), the spec_agent system prompts now look like:

| Benchmark | Spec_agent prompt has | Implication |
|---|---|---|
| DABStep | 5 meta-rules + HELPER_MANIFEST | Specs reference helpers by name |
| LiveSQL | 5 meta-rules (no helpers; no R1-R5 anymore — those moved to planner) | Standard rule-extraction |
| Krama | 5 meta-rules (no helpers) | Standard rule-extraction |

**Impact:** Lower than before P4 cleanup. The R1-R5 verification rigor is now applied uniformly via the planner (which runs across all 3 benchmarks). Only HELPER_MANIFEST remains asymmetric (see A1).

### A4 — Spec extractor provider portability

**What:** Pre-cleanup, `extract_specs_livesql.py` only supported Anthropic. Post-cleanup, it supports `anthropic / openrouter / fireworks / fireworks2`. DABStep's `extract_specs.py` supports `anthropic / openrouter`. Krama's supports `anthropic / openrouter`.

**Impact:** Affects operational portability, not headline accuracy. To run "DeepSeek-R1 as spec_agent" across all 3, we'd need to add Fireworks to DABStep and Krama extractors.

**Status:** Open, ~30 LOC each.

### A5 — No DABStep adapter

**What:** LiveSQL has `livesqlbench_adapter.py`, Krama has `kramabench_adapter.py`. DABStep tasks are pre-formatted in `data/target_tasks.jsonl` — no adapter, conceptually inconsistent.

**Impact:** Onboarding / documentation only. Doesn't affect numbers.

**Status:** Defer.

## Methodology stance

Headline numbers should be reported with these conditions explicit in the paper:
- Same executor model (Kimi-K2.6) and provider (Fireworks) across all 3
- Same planner model (GPT-5) and provider (OpenRouter) across all 3
- Same iter cap (40), same `thinking` (null)
- Same EC1-EC5 mitigations
- DIFFERENT helper manifest (A1) — disclosed
- DIFFERENT pre-commit gate semantics (A2) — disclosed; document as paradigm-intrinsic

For any claim like "the harness lifts accuracy by X% across benchmarks", control for A1 and A2 — i.e., remove the HELPER_MANIFEST when reporting the DABStep number for that specific claim, or normalize the gate semantics.
