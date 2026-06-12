# Harness-fixable vs model-bound failure modes

Synthesized from: 3-bench smoke (1 task each), prior P2 pilot, audit traces, KramaBench paper findings, lit-review (Self-Refine / Reflexion / CRITIC / KramaBench / Harness-Update-Is-Not-Benefit).

## Observed failures (this codebase, this experiment)

### F-A: Compute-success, commit-failure (Kimi over-verification)

**Pattern:** Executor produces a candidate answer in its thinking block (e.g., `"The result is 9.477138. Should we round to 2 decimals: 9.48."` at iter ~30 of DABStep 1712) but does NOT emit it as `assistant_response`. Instead, fires another `run_python` to "double-check" and runs out of budget.

**Concretely seen in:**
- DABStep 1712 — 40 tool calls, 0 assistant_response (this smoke)
- DABStep 2528 — same pattern in P2 v1 smoke (40 iters, no commit)

**Root cause (hypothesis, well-supported):** Context decay. The mandatory iter-15 escalation rule is in the system prompt at position 0, but at iter 30 it's buried under ~50K tokens of tool_call_result content. Kimi's recent-context attention is dominated by data values, not the escalation guidance.

**Harness-fixable?** YES. EC5 (this commit) re-injects the escalation reminder into every tool_call_result footer past iter 10. The reminder is silent once the executor has actually escalated at least once.

### F-B: Wrong answer committed without escalation

**Pattern:** Executor commits a numerically-wrong answer with conviction (Krama `archeology-hard-1` committed `8347.19`, gold `8577.53`). No escalation. Trace shows the executor never paused to consider its uncertainty.

**Root cause:** Self-uncertainty miscalibration — a known and widely-documented RLHF failure mode. The model is confidently wrong because it never learned to flag uncertainty.

**Harness-fixable?** PARTIALLY. EC5 (recurring reminder) addresses cases where the executor is QUIETLY uncertain. It does NOT address cases where the executor is confidently wrong — those need either (a) per-step verifiers (P1 in our roadmap) that catch the wrongness mechanically, or (b) a fundamentally different model with better calibration.

### F-C: Planner unreachable graceful degradation

**Pattern:** LiveSQL smoke fired `ask_planner_agent` (executor obeyed the MANDATORY pre-commit gate) but the planner API returned 401 (dead Anthropic key). Tool returned `"Planner error: Anthropic 401. Proceed with your best judgment."` Executor committed SQL without verification.

**Root cause:** Config-level asymmetry (`livesql_scribe.yaml` used Anthropic Sonnet planner while DABStep+Krama use OpenRouter GPT-5).

**Harness-fixable?** YES — the harness DID gracefully degrade (no crash). The fix is to NORMALIZE the config (now applied; LiveSQL uses OpenRouter GPT-5 like the other two).

### F-D: Mandatory iter-15 rule ignored

**Pattern:** Both DABStep and Krama executors ignored the iter-15 mandatory escalation rule in their prompt YAML. 0 escalations across both tasks despite both being hard tasks with visible uncertainty in the executor's thinking.

**Root cause:** Same as F-A (context decay).

**Harness-fixable?** YES (EC5). **Confirmed by v2 smoke** — DABStep 1712 went from 40 iter-cap-no-commit (v1) to 16 tool calls with 1 escalation and a committed answer (v2). See `04_ec5_context_decay_mitigation.md`.

### F-E: Executor + planner consensus on a wrong answer

**Pattern:** DABStep 1712 v2 — executor computed `9.48`, escalated, planner verified using `query_fees` and `read_file`, quoted manual.md correctly, emitted `[Verdict: ANSWER]`. Gold answer is `12.91`. Both agents agreed on the wrong number because the spec doesn't disambiguate the question's intent.

**Root cause:** Spec extraction missed a critical interpretation. Both executor and planner are working off the same spec and reach the same wrong conclusion.

**Harness-fixable?** PARTIALLY:
- Better spec extraction (more thorough doc reading, R1-R5 verification, query_fees during extraction) could reduce this
- Per-step verification against KNOWN sub-task answers (P1) catches it when sub-task gold exists (KramaBench-style)
- For DABStep specifically, sub-task gold doesn't exist publicly, so detection is harder
- Pre-commit verifier that checks against quick aggregates ("does the answer's magnitude look right?") is a candidate

## Lit-review consensus on harness-durable vs harness-crutch

From `docs/findings/` synthesis (and the gap analysis):

**Durable harness work** (will pay even as models improve):
- Deterministic verification at each step (P1 — sqlglot, row-count assertions, dtype checks). KramaBench's smolagents-DR's tight retrieve-revise-repeat is empirically the strongest single intervention.
- Definition registries (where applicable; Omni semantic-layer concept)
- Permissions / access boundaries (not in scope for benchmark eval)

**Crutch harness work** (will dissolve as models improve):
- Schema linking (Distyl: "the death of schema linking" — better models attend over full schemas)
- Spec extraction in trivial-schema settings (where the schema fits in context)
- Heavy iterative refinement (Huang et al.: GPT-4 GSM8K 95% → 89% over 2 self-correction rounds)

**Neutral / depends:**
- 5-verdict cascade structure (durable as long as escalation is sometimes useful)
- EC5 context-decay reminder (durable IF context decay remains a thing; may dissolve with bigger context windows + better attention)

## What this smoke proved + what it didn't

### Proved (smoke validates harness correctness)
- All 3 benchmarks execute end-to-end without crashes
- Per-benchmark spec rendering, validation, tool registration work
- LiveSQL pre-commit gate fires; planner-401 degrades gracefully
- New EC5 hook is correctly wired (verified post-implementation; rerun pending)
- Cross-benchmark code paths use the same shared TS/Python infrastructure

### Did NOT prove (need bigger N)
- Whether EC5 actually fixes F-A and F-D at any meaningful rate (need 10-20 task smoke)
- Whether the planner cascade catches real spec mistakes (need tasks where the spec IS wrong)
- Whether cross-benchmark accuracy comparison is fair given the documented asymmetries (need normalized configs across all 3 + pilot of 20+ each)

## Methodology stance for paper

When reporting cross-benchmark numbers, document:
1. **Harness identity** — same code, same hooks, same EC1-EC5 mitigations across all 3
2. **Config asymmetries** — same planner model (GPT-5), same iter cap (40), same thinking setting (now uniform after the smoke-followup fix)
3. **Per-benchmark intrinsic differences** — different paradigm (Python vs SQL vs data-lake), different spec schemas. These are dependent variables, not confounds.
4. **The HELPER_MANIFEST asymmetry** (DABStep only) — disclose as a known limitation; consider per-benchmark helpers as future work but DO NOT silently include them in headline numbers.
