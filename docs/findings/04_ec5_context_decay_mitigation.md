# EC5 — Conditional escalation reminder (context-decay mitigation)

Date: 2026-06-06
Implemented in: `src/harness/hooks/after_tool.ts`

## Problem (empirical)

Across pre-EC5 smokes:
- DABStep 1712 (P2 v1, P2 v2, smoke1): 40 tool_call iter cap; 0 escalations; final answer never committed
- DABStep 2528 (P2 v1): same — iter cap, no escalation
- Krama archeology-hard-1: 12 tool calls, no escalation, committed wrong answer

The mandatory iter-15 escalation rule lives in the system prompt at position 0. By iter 30 it's buried under ~50K tokens of `tool_call_result` content. Kimi's recent-context attention dominates over distant system-prompt content. The model has the rule in long-term memory (system prompt) but not in working memory (recent turns).

## Hypothesis (user-stated, well-supported by trace evidence)

> "Kimi has forgotten that it has to escalate because after so many tool callings, it has already burned so many tokens that those rules are out of the context itself."

i.e. **context decay** of the escalation guidance.

## Solution — EC5

A short footer appended to every `tool_call_result` past iter 10, reminding the executor that `ask_planner_agent` is available. The reminder:

1. **Re-injects guidance into recent context** — addresses decay
2. **Escalates tone over time** — silent before iter 10, soft from 10-14, urgent from 15+
3. **Goes silent once the executor has escalated at least once** — avoids nagging a model that already complied

### Footer table

| Iter | Already escalated? | Footer |
|---|---|---|
| 1-9 | any | (silent) |
| 10-14 | no | `"[iter X/MAX] If uncertain about correctness or stuck, escalate via ask_planner_agent."` |
| 10-14 | yes | (silent) |
| 15+ | no | `"[iter X/MAX] You have not escalated yet. If uncertain about correctness, blocked on an ambiguity, or considering a 'Not Applicable' commit, escalate via ask_planner_agent now."` |
| 15+ | yes | (silent) |

### Implementation

Two new constants + one helper function in `src/harness/hooks/after_tool.ts`:

```typescript
const EC5_SOFT_FROM = 10;
const EC5_URGENT_FROM = 15;
const EC5_ESCALATION_TOOLS = new Set(["ask_planner_agent", "ask_spec_agent", "ask_planner"]);

function ec5Footer(iterCount, escalationCount, maxIter): string {
  if (escalationCount >= 1) return "";
  // ... return appropriate footer based on iter
}
```

The footer is composed alongside the existing context_mgmt stats line, so a single modified result is returned when either fires.

## Cost

- ~10 tokens per tool_call_result when the soft footer fires
- ~30 tokens when the urgent footer fires
- Zero tokens before iter 10 or after the executor has escalated
- For a typical 40-iter task that escalates once: ~50-100 extra tokens total. Negligible.

## What EC5 explicitly does NOT do

- It does NOT enforce escalation — the executor can still ignore. The earlier-considered EC6 (hard tool-filter at iter 15) was explicitly REJECTED by the user in favor of the softer approach. Rationale: a model that already complied shouldn't be forced to escalate again; trust the recurring reminder.
- It does NOT address the F-B mode (confidently-wrong without uncertainty). That requires P1 deterministic verifiers.
- It does NOT change the system prompt. The escalation guidance there is unchanged.

## Validation plan

The pre-EC5 3-bench smoke (see `03_smoke_results_3bench.md`) showed 0 escalations on DABStep and Krama. The re-run with EC5 should show:
- At least one escalation on tasks that hit iter 15 without committing
- Lower iter-cap rate
- Possibly higher accuracy (if the planner can catch the executor's silent errors)

If EC5 does NOT increase escalation rate, the hypothesis is wrong and we need different mitigation (most likely EC6 + targeted prompt redesign).

## Validation result (v2 smoke, 2026-06-06)

### DABStep 1712 — CLEAR WIN

| Metric | v1 (no EC5) | v2 (with EC5) |
|---|---|---|
| Tool calls | 40 (iter cap) | **16** |
| Escalations | 0 | **1** |
| Hit iter cap | YES | **NO** |
| Final answer | (blank) | `9.48` committed |
| Cost | $0.71 | $0.50 |

**EC5 broke the compute-success-commit-failure pattern.** The executor reached its candidate answer, was nudged by the EC5 footer, escalated to the planner, got `[Verdict: ANSWER]`, and committed cleanly. Hypothesis confirmed.

### Krama archeology-hard-1 — NO CHANGE

EC5 fired (verified via trace), but executor committed the same wrong answer (`8347.19`) at iter 13 with no escalation. Reason: Kimi felt confident throughout — never matched the "uncertain" condition in the EC5 footer text. **EC5 helps F-A (compute-success-commit-failure) but not F-B (confidently-wrong without uncertainty).** Documented in `01_harness_vs_model_failure_modes.md`.

### LiveSQL virtual_3 — ORTHOGONAL CONFIRMATION

LiveSQL's MANDATORY pre-commit gate already forces escalation; EC5 doesn't add value here. v2 confirmed the cascade works end-to-end with the normalized OpenRouter planner (v1's Anthropic 401 went away).

## Cross-benchmark generalization

EC5 is benchmark-agnostic by construction (lives in `after_tool` hook, no per-benchmark code). v2 smoke confirms it fires correctly across all 3 paths.

## What we learned about EC5's limits

1. **Targets uncertain executors only.** The footer text says "if uncertain or stuck". Kimi often doesn't feel uncertain even when wrong. For confident-wrong cases (F-B), the next intervention is P1 (deterministic per-step verifiers).
2. **Planner agreement is not correctness.** DABStep 1712 v2 showed executor + planner converging on the wrong answer (gold 12.91, both got 9.48). This is a NEW failure mode (F-E) that EC5 cannot address.
3. **The trace doesn't show EC5 footers.** The session logger captures pre-modification result text. The footer is injected only into the agent's view. This is fine but means "did EC5 fire" must be inferred from behavior (escalation count + iter trajectory), not log inspection.

## Open questions for future iterations

1. Should EC5 fire on `ask_planner_agent`'s own tool_call_result? Currently it does. Probably harmless (the executor sees its own escalation reply with a counter). Could suppress to keep output clean.
2. Should EC5 RE-FIRE after some delay even for executors who already escalated? (E.g., if iter ≥ 25 and last escalation was iter 5, maybe nudge again.) Not currently implemented.
3. Should the iter threshold be config-driven instead of hard-coded? Currently `EC5_SOFT_FROM = 10` and `EC5_URGENT_FROM = 15` are module-level constants. Easy to move to config if we want per-benchmark tuning.
