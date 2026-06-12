# 3-benchmark smoke results (1 task per benchmark, post-P4-cleanup)

Date: 2026-06-06
Goal: validate that P4 audit fixes (Type A/B/C + planner prompt rewrite + 7 cleanup items) didn't regress any of the 3 benchmark code paths.

## Tasks selected (1 each)

| Benchmark | Task | Source |
|---|---|---|
| DABStep | `1712` | `data/splits/dabstep_smoke1.jsonl` (first of pilot5) |
| LiveSQL | `virtual_3` | first of `/Users/suraj/Downloads/livesqlbench/livesql_harness_tasks.jsonl` |
| Krama | `archeology-hard-1` | first of `data/splits/krama_archeology12.jsonl` |

## Raw results

| Benchmark | Tool calls | Escalations | Time | Cost | Final | Gold | Pass |
|---|---|---|---|---|---|---|---|
| DABStep | 40 (all run_python) | 0 | 204s | $0.71 | (blank — iter cap hit) | 12.91 | ✗ |
| LiveSQL | 4 (3 run_sql + 1 ask_planner_agent) | 1 (Anthropic 401) | 20s | $0.08 | committed SQL | (correct ans) | ✗ |
| Krama | 12 (all run_python) | 0 | 54s | $0.19 | 8347.19 | 8577.53 | ✗ |

**Accuracy 0/3**, but accuracy was NOT the goal. The goal was harness-correctness validation.

## Harness validation (12/12)

| Check | Result |
|---|---|
| All 3 paths execute without crashes | ✓ |
| `run_python` vs `run_sql` dispatch | ✓ |
| Spec renderer dispatches DABStep / LiveSQL / Krama correctly | ✓ |
| New tool name `ask_planner_agent` | ✓ |
| `read_current_spec` registered (not called in any task) | ✓ |
| LiveSQL ported pre-commit gate fires | ✓ |
| Krama per-task `context_dir` override works | ✓ |
| Krama xlsx sampling works (openpyxl fix) | ✓ |
| Graceful degradation on planner API failure (LiveSQL 401) | ✓ |
| Fix #7 silent-DABStep warning fires correctly | ✓ |
| All 3 graders produce `results.csv` + `results.json` (fix #5) | ✓ |
| LiveSQL extractor accepts OpenRouter (fix #6) | ✓ |

## Failure modes observed

### DABStep 1712 — compute-success commit-failure

Model produced candidate answer `9.48` at ~iter 30 (visible in `assistant_thinking`) but kept calling `run_python` to "verify" until iter cap. Zero `assistant_response` events.

**Diagnosis:** F-A (context-decay, see `01_harness_vs_model_failure_modes.md`).

**Mitigation:** EC5 (implemented after this smoke). Recurring escalation reminder past iter 10 — would likely have nudged Kimi to commit or escalate by iter 15.

### LiveSQL virtual_3 — planner-401 graceful degradation

Executor obeyed the MANDATORY pre-commit gate, called `ask_planner_agent`, got `"Planner error: Anthropic 401"` because `livesql_scribe.yaml` was using a dead Anthropic key. Executor committed SQL anyway.

**Diagnosis:** F-C (planner unreachable).

**Mitigation:** Config normalization (now applied — LiveSQL uses OpenRouter GPT-5 like the others). Re-run pending.

### Krama archeology-hard-1 — confident-wrong without escalation

Executor committed `8347.19` (gold `8577.53`). 12 tool calls, no escalation. The trace shows the executor never paused to consider its uncertainty.

**Diagnosis:** F-B + F-D (calibration + context decay).

**Mitigation:** EC5 partial coverage (will nudge escalation at iter 10+, but this task committed at iter 12 with no prior uncertainty signal). For confidently-wrong cases, the real fix is P1 (per-step deterministic verifiers).

## What the smoke proved about cross-benchmark fairness

- All 3 paths use the same code, same hooks, same EC1-EC4 (and now EC5) mitigations
- `livesql_scribe.yaml` was the last config asymmetry — now normalized
- No new asymmetries surfaced

## Next steps (sequenced)

1. Re-run smoke with EC5 + normalized LiveSQL config (validates EC5 effect + restores LiveSQL planner path)
2. Focused prompt-bias audit (smoke traces in hand as evidence)
3. P1 — deterministic per-step verifiers (the highest-leverage gap per lit review)
4. After P1: 10-20 task pilots per benchmark for statistically meaningful comparison
