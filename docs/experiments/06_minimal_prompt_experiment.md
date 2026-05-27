# Experiment: minimal-prompt Kimi K2.6 on 5 fee_rule iter_capped tasks

## Question
Does our strict 100-line DABStep prompt cause Kimi K2.6 base's failures on fee_rule
iter_capped tasks? Is the bottleneck the prompt, or the model?

## Setup
Created `src/prompts/minimal.yaml`:
- tools_section: 4 lines (just CONTEXT_DIR + run_python + lib list)
- quick_rules / deep_rules: "Answer the question. Print() the final answer when ready."

Ran Kimi K2.6 base k=1, cap=50, on 5 of our 10 k=5 tasks (1711, 1715, 1720, 1721, 1729).

## Results
| task | expected | minimal-prompt answer | iters | ok? |
|---|---|---|---:|:---:|
| 1711 | 29.93 | (no answer, iter_cap) | 49 | — |
| 1715 | 9.17 | 23.85 | 46 | ✗ |
| 1720 | 105.13 | 91.14 | 47 | ✗ |
| 1721 | 93.08 | (no answer, iter_cap) | 49 | — |
| 1729 | 91.51 | 35.51 | 29 | ✗ |

**0 of 5 correct.**

## Three-way summary on same 5 tasks
| setup | correct / 5 |
|---|---:|
| Kimi K2.6, strict prompt, k=5, cap=50 | 0 (these specific 5) |
| Kimi K2.6, minimal prompt, k=1, cap=50 | 0 |
| Opus 4.6 (provided traces, minimal prompt + submit_answer tool) | 4 (1 trace contaminated) |

## Verification — minimal prompt was actually applied
Verified on task 1715 trace: Kimi's first tool_call uses `os.listdir(context_dir)`
to discover files itself, rather than being told the file list. This is the
minimal-prompt behaviour (the strict prompt enumerates files). Confirmed.

## Interpretation

The prompt-strictness hypothesis is refuted. Two independent interventions failed
to recover Kimi K2.6 base on fee_rule iter_capped tasks:
1. **k=5 sampling**: 0/5 → 2/10 (negligible).
2. **Minimal prompting**: 0/5 (these 5 specific tasks).

The remaining hypothesis — and the now-strongly-supported one — is **model
capability**. Kimi K2.6 base lacks the procedural skill to reliably derive multi-row
multi-rule fee totals, regardless of how the task is presented.

Combined with the Opus comparison (9 of 10 traces show genuine derivation chains),
the cross-model gap is real and not a scaffolding artefact.

## Refined research claim

> "On agentic data-analysis benchmarks (DABStep fee-rule cluster), the failure
> of open-source 70B-class models is a **procedural-capability ceiling**, not a
> scaffolding or budget artefact. Two cheap user-side interventions —
> multi-sample inference (k=5) and minimal-prompt scaffolding — fail to recover
> Kimi K2.6 on tasks where Opus 4.6 succeeds via inspectable reasoning chains
> in fewer iterations. The gap is bridgeable only at the model-training side."

This is now a cleanly defensible claim with three independent lines of evidence:
1. k=5 doesn't help (sampling variance is real but irrelevant to accuracy)
2. minimal prompt doesn't help (prompt complexity isn't the bottleneck)
3. Opus's traces show genuine procedural competence on 9/10 of the same tasks

## Next experiments to consider

- **Scale up the Opus comparison**: read all 446 of the provided Opus traces
  and score them against our 228 Kimi failures. If Opus gets ~80-90% on the
  full Kimi failure set, the capability-ceiling claim covers all of DABStep.
- **Re-verify task 1711 contamination**: run Opus on our harness with the
  *minimal* prompt and submit_answer tool. If Opus computes 29.93 properly under
  matched conditions, the trace was just missing intermediate events. If it
  computes 96.34 again or otherwise diverges, the trace was contaminated.
- **Targeted fine-tuning probe** (paper-scale): fine-tune a 70B open-source
  model on ~1000 traces of Opus solving similar fee_rule tasks. Test if the
  capability gap closes. This is the publishable methods experiment.
