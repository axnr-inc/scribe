# Cross-model panel on a single iter_capped task

## Task
1717 — "For the 10th of the year 2023, what is the total fees that Crossfit_Hanna
should pay?" Expected: 148.61.

## Setup
All 4 model conditions, same prompt, cap=50 (doubled from original).

## Results
| Model | Iters | Cost | Tokens | Answer | Δ vs Opus |
|---|---:|---:|---:|---|---:|
| Opus 4.6 reasoning | 20 | $0.60 | 263K | ✓ 148.61 | — |
| Kimi K2.6 off | 23 | $0.54 | 363K | ✓ 148.61 | +3 iters |
| Kimi K2.6 reasoning | 38 | $1.25 | 1.0M | ✓ 148.61 | +18 iters |
| Deepseek-v3.2 reasoning | 50 (cap) | $0.99 | 780K | ✗ (none) | n/a |

## Findings

### 1. Kimi-off solves the same fee_rule task Opus does, in 23 vs 20 iters
The original full-batch run iter-capped this task at 25 iters. With cap=50 and a
different sampling roll, Kimi-off converged in 23. This implicates **sampling
variance + tight budget** as the dominant explanation for many iter_capped failures
in fee_rule.

H5 (open vs frontier convergence asymmetry) is weaker than originally hypothesized.
The gap on this task is 3 iters, not the 2× I'd expected.

### 2. Reasoning is actively harmful for Kimi K2.6 on this task
- Kimi-off: 23 iters, $0.54, correct
- Kimi-reasoning: 38 iters, $1.25 (2.3× cost), correct

Reasoning added 15 iters of overhead with zero accuracy benefit. This is opposite
to the conventional "reasoning helps" wisdom. Hypothesis: reasoning amplifies
exploration; on a base model without strong termination priors, exploration becomes
wandering. Reasoning helps when convergence priors are strong (Opus); it hurts
when they're weak (Kimi).

### 3. Deepseek-v3.2 reasoning is structurally over-exploring
50 iters, $0.99, no answer. Same pattern observed on 2715 (cap 30 → 60).
**Deepseek-v3.2 with reasoning doesn't converge even at 2x budget.** This is a
model-class issue, not a budget issue.

## Three-mechanism reframe of iter_capped

Combined with Experiment F (self-consistency probe):

| Sub-mode | Definition | Recovers under |
|---|---|---|
| Stochastic non-convergence | Same model converges sometimes; sampling-variance dominates | k≥3 re-sampling OR higher cap |
| Compute-budget bound | Model genuinely needs > 25 iters (typical for fee_rule) | Higher cap (50+) |
| Over-exploration in reasoning models | Reasoning amplifies search, model never commits | None — model-class issue; needs better training or different model |

The clean publishable claim:

> "Non-convergence in agentic LLMs is not a single phenomenon. It decomposes into
> three mechanisms — sampling-stochastic, compute-budget bound, and reasoning-
> amplified over-exploration — each with a distinct recovery path. The literature
> on test-time compute scaling (Snell 2024, ReAct 2022) does not distinguish these,
> conflating fixable budget bounds with structural over-exploration."

## Implications for our Kimi K2.6 analysis

Of the 97 iter_capped failures:
- ~42 are likely *terminate-prior gap* (had answer in print but didn't commit) → recoverable by prompt-level termination hint
- ~55 are likely *compute-budget bound* (didn't reach answer in 25 iters) → recoverable by k-sampling and/or cap=50
- A small subset may be *unrecoverable structural over-exploration* (more likely on tasks where Kimi specifically over-thinks)

The next high-information experiment: **measure sampling variance**.
Run Kimi K2.6 off on 10 iter_capped tasks, k=5 attempts each.
- If k=5 recovers >50% of tasks → stochastic dominant
- If k=5 recovers <20% → compute-budget or structural

Cost: ~10 tasks × 5 runs × ~$0.30 avg = $15. Highest information-per-dollar of any
experiment now.
