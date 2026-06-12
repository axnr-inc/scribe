# Krama pilot 12 — failure analysis

**Date:** 2026-06-06
**Setup:** Kimi-K2.6 executor (Fireworks) + GPT-5 spec_agent + GPT-5 planner_agent (OpenRouter) + EC5 + P1 verifiers active.
**Task set:** 12 archeology tasks from `data/splits/krama_archeology12.jsonl`.

## Headline

**5/12 PASS (42%).** Easy: 4/6 (67%). Hard: 1/6 (17%).

For comparison (KramaBench paper):
- Human baseline on archeology: 58%
- smolagents-DR Claude-3.7 on archeology: 44.44%
- Best agentic system overall: 55.83%

**SCRIBE is competitive with weaker base models** (Kimi-K2.6 + GPT-5 vs Claude-3.7).

## What the harness layer did

- 11/12 escalations (mandatory pre-commit gate fires reliably)
- 1 `[Verdict: SPEC_WRONG]` (archeology-hard-2) — first time the cascade revised a spec mid-task
- 3 `verify_step` calls (only archeology-hard-9 used Tier C; all 3 returned PASS)
- 0 `[AUTO-INSPECT]` fires (Kimi's `print(df.head())` style triggers `alreadyPrintsShape` suppression — by design)
- 0 pattern-triggered VERIFY tags (no `.groupby()` or `.merge()` in any task)
- 0 Python errors

## Failure taxonomy (the 7 failures)

| Task | Predicted | Gold | Mode | Planner verdict | Diagnosis |
|---|---|---|---|---|---|
| easy-6 | (blank) | São Paulo | **F-A** | (no escalation) | Single tool call, then stopped — no `assistant_response` emitted |
| easy-8 | 55 | 52 | **F-E** | ANSWER | Bibliography tokenization missed 3 duplicates; spec was imprecise |
| hard-1 | 8347.19 | 8577.53 | **F-E** | ANSWER | Spec's earliest/latest interpolation method differs from gold's intended method |
| hard-12 | 1146 | 409 | **F-E** | ANSWER | Conflict dedupe key was wrong; spec doesn't specify "by name AND year" |
| **hard-2** | **49.75** | **38.42** | **F-E with SPEC_WRONG** | SPEC_WRONG → ANSWER | Planner caught duplicate-column bug → revised → executor re-ran → same answer. **Planner caught wrong issue.** |
| hard-5 | 34748 | 66158 | **F-E** | ANSWER | "Most northern Neolithic" tie-break or year-BP conversion wrong |
| hard-9 | −0.21 | 0.0156 | **F-E** (used verify_step!) | ANSWER | Pearson correlation OPPOSITE SIGN — matching threshold or rank parsing wrong |

## The dominant pattern: F-E (executor + planner consensus on wrong)

**6 of 7 failures are F-E.** Both `spec_agent` (GPT-5) and `planner_agent` (GPT-5) read the SAME source documents and reached the SAME interpretation. Neither has access to gold answer. So they can't catch "you computed something logically valid but not what the question asker meant."

### The clearest example: hard-9

1. Executor opted into `verify_step` 3 times: row_count (PASS), non_null (PASS), column_exists (PASS) — confirmed the data was loaded correctly
2. Escalated to planner with structured summary
3. Planner spent 57s reviewing
4. Planner quoted docs verbatim with `[Source: docs]` tags
5. Planner emitted `[Verdict: ANSWER]` with detailed reasoning
6. Both agents converged on −0.21
7. **Gold is +0.0156. Opposite sign.**

The harness is doing exactly what it's supposed to. The bottleneck is upstream of the harness.

### The clearest demonstration of the limit: hard-2

1. Executor computed 49.75 using `iloc` to handle duplicate columns
2. Escalated for pre-commit verification
3. Planner correctly identified that the SPEC didn't explicitly mention duplicate column handling → emitted `[Verdict: SPEC_WRONG]` + revised spec
4. Executor: "the rest of the computation is essentially what we already did (using iloc). Our computed answer is 49.75. The revised spec matches..."
5. Re-ran with same logic → 49.75 → committed
6. Gold: 38.42

**The cascade fired correctly but caught the wrong bug.** The real issue (whatever distinguishes 49.75 from 38.42 in the wet-dry index calculation) was never identified by either agent.

## What this confirms about the harness

**Every layer of delivery works**:
- ✓ Spec extracted by spec_agent → written to `<task_id>.json`
- ✓ Spec rendered by `renderKramaSpec` → injected into executor's user message
- ✓ Executor processes spec, runs ReAct loop
- ✓ Mandatory pre-commit gate fires reliably (11/12)
- ✓ Executor's structured 5-header summary reaches planner
- ✓ Planner reads current spec from disk, calls `read_file`, emits verdicts
- ✓ When SPEC_WRONG fires, revised JSON is persisted and delivered to executor inline
- ✓ Tier-C `verify_step` works when called

**The bottleneck is at the SPEC LAYER, not delivery.** This motivates P2b (stronger spec extraction).

## Per-component lift attribution

- **EC5 (context-decay reminder)**: Not directly tested here — pre-commit gate forces escalation before EC5 thresholds matter. Likely under-attributed; bigger pilots with longer-iteration tasks would surface its effect.
- **Pre-commit gate (P4 audit fix)**: Strong effect. 11/12 escalations is unprecedented across all prior smokes.
- **`SPEC_WRONG` revision mechanism**: Fired once, mechanism worked, but the chosen revision didn't fix the actual problem.
- **P1 Tier A/B**: 0 fires in this pilot. Kimi's coding style + lack of groupby/merge in archeology = nothing to detect.
- **P1 Tier C (`verify_step`)**: 1 task (8%) opted in. Used for shape/null/column checks — confirmed data loaded correctly but couldn't catch the semantic error.

## Implications

1. The harness ARCHITECTURE is sound — every layer works.
2. The harness CEILING is set by spec-extraction quality.
3. To break through 42% on Krama archeology, the levers are:
   - Stronger spec extraction (more tools / multi-shot / self-consistency)
   - Sub-task gold verification (Krama provides sub-task golds — currently unused)
   - More iterations of SPEC_WRONG → reformulation (currently capped at 3)
4. EC5, pre-commit gate, and the cascade together have made the harness behave consistently across benchmark paradigms — even with this poor accuracy, ZERO crashes, ZERO Python errors, EVERY task committed (except easy-6's F-A no-commit).

## Related docs

- `01_harness_vs_model_failure_modes.md` — failure mode taxonomy (F-A through F-E)
- `02_cross_benchmark_fairness.md` — what asymmetries exist
- `04_ec5_context_decay_mitigation.md` — EC5 design
- `05_p1_verifiers_design.md` — P1 verifier design
- `05_verifier_lit_review.md` — assertion vocabulary lit review
- `07_livesql_failure_analysis.md` — companion analysis for LiveSQL
- `10_stronger_spec_extraction_proposal.md` — the proposed next intervention
