# Experiment F results: self-consistency probe on iter_capped sessions

## Method
For each of the 97 Kimi K2.6 iter_capped sessions, scanned ALL `tool_call_result`
content for whether the leaderboard-correct expected answer appeared:
1. As a direct substring (literal text match)
2. Via the official DABStep grader on any single line (handles numeric tolerance)

## Result
| status | count | % |
|---|---:|---:|
| direct substring match | 32 | 33% |
| grader-passes some printed line | 10 | 10% |
| **Kimi HAD the answer in trace** | **42** | **43%** |
| Kimi never reached the answer | 55 | 57% |

## Topic breakdown
| topic | had-answer-in-trace |
|---|---:|
| aci_format | 100% (16/16) |
| reference_lookup | 100% (1/1) |
| date_specific | 56.5% |
| delta_what_if | 36.8% |
| **fee_rule** | **13.5%** (4/37) |
| merchant_lookup | 0% (1/1) |

## Reshapes the hypothesis

iter_capped is **two distinct failure modes** mixed:
- `terminate_failure`: 42 tasks. Model computed the answer but couldn't commit.
  Pure H1 (terminate-prior gap). Prompt-level fix should recover all.
- `compute_failure`: 55 tasks. Model never reached the answer within 25 iters.
  Different problem — needs higher budget OR better tool use.

### Topic-conditioned interventions
- aci_format + reference_lookup: prompt-level terminate hint → ~100% recovery
- fee_rule: budget + better rule-matching → likely needs >50 iters or a better model
- date_specific + delta_what_if: ~50% / 37% recovery from terminate hint

## What this means for the research direction

The publishable claim becomes more nuanced than "terminate-prior gap":

> "Iter-cap failures in open-source agentic LLMs on data-analysis tasks
> decompose into a *terminate-prior gap* (model has the answer but cannot
> commit) and a *compute-budget gap* (model cannot reach the answer in time).
> The split is topic-conditional: rule-application tasks are budget-bound,
> while format / interpretation tasks are commitment-bound. Prompt-level
> termination hints can plausibly recover all commitment-bound failures
> without extra compute. Compute-bound failures require either budget
> increases or model-quality improvements."

This is a sharper, more actionable framing than "non-convergence is a thing".
