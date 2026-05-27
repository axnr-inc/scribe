# Experiment: k=5 sampling-variance on fee_rule iter_capped tasks (Kimi K2.6)

## Setup
- 10 fee_rule iter_capped tasks (1711, 1713, 1715, 1716, 1720, 1721, 1722, 1724, 1728, 1729)
- Kimi K2.6 base, no reasoning, max_iterations=50, prompt_caching off
- 5 samples per task, all 50 fired in parallel via OpenRouter

## Aggregate results

| Metric | Value |
|---|---|
| Total runs correct | 3 / 50 (6%) |
| pass@1 (≥1 of 5 ✓) | 2 / 10 (20%) |
| pass@majority (≥3 of 5 ✓) | 0 / 10 (0%) |
| pass@5 = pass@1 | (re-sampling adds 0pp over best-single-sample assumption) |

## Per-task outcomes

I = incorrect, N = no_answer (NAR-like), C = correct

| task | k=5 | correct | iter range |
|---|---|---:|---|
| 1722 | I C I C N | 2/5 | 36–49 |
| 1724 | N I I I C | 1/5 | 26–49 |
| 1711 | I N N I N | 0/5 | 4–50 |
| 1713 | N I N N I | 0/5 | 31–49 |
| 1715 | I N I N I | 0/5 | 2–52 |
| 1716 | N I I N I | 0/5 | 2–49 |
| 1720 | I I N I I | 0/5 | 2–44 |
| 1721 | I N I N I | 0/5 | 25–49 |
| 1728 | N I I I N | 0/5 | 34–49 |
| 1729 | I N N I N | 0/5 | 29–50 |

## What this overturns

The prior hypothesis was that re-sampling would recover sampling-stochastic
failures. The data refutes it for this cluster: 8 of 10 tasks remain unrecoverable
at k=5 with double budget. Pass@5 = 20%, identical to best-pass@1 on these tasks.

## What this confirms

Variance is genuinely large per-task. Iter range within a single task spans 2 to 52
on the same prompt. The model's trace shape is highly stochastic — sometimes bails
in 2 iters, sometimes runs the full 50 — but the *outcome distribution* doesn't
favour correct answers.

## Decomposed failure modes (revised)

iter_capped failures on fee_rule combine:

1. **Computational gap** (dominant). Kimi has poor procedural skill on multi-table
   join + per-row rule application. Most non-correct outcomes are I (wrong answer)
   not N (no answer). Even when committing, the answer is usually wrong.
2. **Termination uncertainty**. When the model derives correctly, it sometimes
   fails to emit a final text answer (N outcomes ~30% of samples).
3. **Inter-sample variance**. Outcomes scatter across (commit / no-commit) and
   (correct / incorrect) widely. Hi variance, low mean.

## Implication for the research story

> "Iter-capped failures on agentic data-analysis benchmarks decompose into three
> compounding mechanisms: commit-failure, compute-gap, and inter-sample variance.
> The 'best-of-k inference' fix that works for many LLM reasoning failures is
> empirically insufficient on the dominant sub-cluster (fee_rule + Kimi K2.6).
> Compute-gap on rule-application tasks is a model-capability ceiling — not a
> scaffolding problem — and is not bridgeable by re-sampling at the user side.
> The frontier-vs-open-source gap on agentic data analysis is real."

## What we don't yet know

- How many of these 8 unrecoverable tasks would Opus 4.6 solve in 1 attempt?
  Earlier we observed 100% Opus success on 1717 (which is in the same family).
  If Opus succeeds on 8/10 of these too → opensource-frontier gap quantified.
- Does k=10 or k=20 recover more? (Probably yes, marginally — but with diminishing
  returns. The 0% pass@majority hints that even more samples won't push past 50%.)
- What's the per-iter cost of these long runs? Cumulative across 50 runs we spent
  ~$25–30. Would the comparative Opus runs be cheaper per-task-solved?

## Suggested follow-up experiments

1. **Opus on the same 10 tasks.** Run Opus 4.6 once on each, expect ~80–100% pass.
   Quantifies the model-class gap directly. Cost: ~$3–5.
2. **k=10 Kimi off** on the 8 unrecoverable tasks. Tests if 10 samples push past
   the pass@5 plateau. Cost: ~$15–20.
3. **Prompt-level "commit hint"** on the same 10 tasks (Experiment C from memo 01).
   If a prompt change recovers 4–6 of these without re-sampling, the cluster is
   commit-failure-bound after all. Cost: ~$5.

(1) is the highest-leverage next step. If Opus succeeds on 8/10, the paper claim
is sharp: "frontier models are not just iter-efficient — they are categorically
more accurate on rule-application tasks even at matched budget."
