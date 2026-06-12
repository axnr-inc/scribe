**Agent name:** SCRIBE (Actioneer)
**Backbone LLM:** Claude Opus 4.7 (Anthropic)
**Hints:** Yes
**Trials:** 5 per query
**Stratified Pass@1:** 71.99%

> **Note (correction):** This is the corrected submission following the maintainers' leakage review of our earlier 83.87% entry. All flagged queries (and several additional ones we found in our own audit) were re-run under a hardened sandbox with regenerated, gold-free specs. The honest number is lower, and we report it as-is. Full remediation details below.

### Architecture — design principles

SCRIBE (Spec-Conditioned ReAct with Inline Backreview Escalation) is a three-role harness. Each role mitigates a specific, well-known LLM failure mode on data-analysis tasks.

1. **Action bias -> planning agent.** A dedicated *spec agent* commits a structured plan (JSON contract) before the executor sees a Python REPL; the executor is conditioned on that plan.
2. **"One definitive answer" bias -> multi-interpretation surfacing.** The spec agent enumerates 2-4 explicit interpretations (filter strictness, metric definition, single- vs multi-row, code-vs-name granularity) and records the alternatives for the reviewer. Where the benchmark leaves a decisive interpretation unspecified, the spec now presents the options open, with no committed choice.
3. **Premature commitment -> backreview over the recent window.** The reviewer receives the last N steps as structured context, so it can target the step where a wrong decision was made.
4. **Five-verdict cascade -> root-cause-aware recovery.** The reviewer emits exactly one of `[SPEC_WRONG | BLIND_SPOT | EXECUTOR_WRONG | NA_CONFIRMED | ANSWER]`.

### Remediation of the flagged leakage (and what else we found)

Every issue from the review is fixed, and the affected queries re-run end-to-end:

1. **Local HF cache reads (agnews/query4).** Added a filesystem guard to the executor preamble that blocks reads of any HuggingFace/Kaggle cache path and any `.arrow`/`.parquet` shard outside the task's own context directory. agnews was re-run with the guard active; all agnews answers now come from honest classification of the article text in MongoDB. (agnews/query4's honest answer does not match gold, and we report the failure.)
2. **Gold-derived values in the prompt** (crmarenapro/q2, q12; deps_dev_v1/q1; googlelocal/q2; pancancer/q1). The hand-tuning pass that introduced these was removed entirely. Specs were regenerated from schema/data only, and the spec-extraction prompt now contains an explicit hygiene rule forbidding answer values, record IDs, gold cardinality, or validator references in any spec.
3. **Decisive unspecified interpretation injected up front** (yelp/q1, q5). Regenerated specs surface the aggregation choice as an open interpretation with no steer. Notably, the executor still selects the review-weighted reading on its own from the data, and both queries pass honestly.
4. **Additional issues we found in our own audit and fixed the same way** (re-run, not patched):
   - crmarenapro/q10's spec contained a literal record-ID prediction; all 13 crmarenapro queries were re-run with scrubbed specs.
   - github_repos/q2's spec used the eventual answer as a format example. After removing it, the executor still derives the same repo from the data in 5/5 runs — the example was redundant, but we re-ran anyway so the shipped traces are example-free.
   - github_repos/q1's spec pre-stated a computed value ("the answer is 1/3 ≈ 0.3333"). After removing it, the executor computes a different (failing) value in 5/5 runs — i.e. the hint was load-bearing. We kept the honest failing answers and report the lower github_repos score.
   - All specs were additionally scrubbed of validator-internals language (matcher behavior, row-count gates) and of sampled record-ID literals.

### Integrity / anti-leakage

All trials in this submission ran under a hardened Python sandbox enforced in the executor's REPL preamble:

- **Import block**: `datasets`, `huggingface_hub`, `kaggle(hub)`, `tensorflow_datasets`, `torchvision.datasets` raise ImportError; offline env vars set.
- **Network egress block**: sockets to any non-localhost host raise OSError; only the project DBs on 127.0.0.1 are reachable.
- **Local-cache block**: reads of HuggingFace/Kaggle cache paths or external `.arrow`/`.parquet` shards raise OSError.

Self-audit (`scribe_actioneer_opus47_taint.json`, committed): **270/270 clean** — 0 HF dataset loads, 0 cache file reads, 0 answer-key/validator reads, 0 external fetches, 0 gold values or answer-pointers in any spec that reaches a prompt, 0 JSON-vs-trace mismatches, 270 distinct real traces. We additionally scanned every trace prompt for gold tokens, record IDs, validator references, and format-examples equal to the answer (0 hits), and verified every passing answer is computed in its trace from the project data.

One disclosure: in a single deps_dev_v1/q1 trace (a query that fails 0/5), the executor writes "the planner's expected answer listed X" while overriding the planner's internal proposal against the data. This refers to our own planner's data-derived suggestion, not the benchmark gold; we left the trace untouched rather than edit it.

### Results Summary

| Dataset | Pass@1 |
|---|---|
| bookreview | 1.00 |
| googlelocal | 1.00 |
| stockindex | 1.00 |
| stockmarket | 1.00 |
| yelp | 0.94 |
| music_brainz_20k | 0.93 |
| crmarenapro | 0.85 |
| PANCANCER_ATLAS | 0.67 |
| deps_dev_v1 | 0.50 |
| GITHUB_REPOS | 0.50 |
| agnews | 0.25 |
| PATENTS | 0.00 |
| **Stratified Pass@1** | **0.7199** |

### Notes

- Pass@1 computed with DAB's stratified formula `(1/D) x sum_J [(1/Q_J) x sum_i (c_i,j / n)]`; every trial validated with the official `query_<ds>/query<N>/validate.py` (270 records, 0 validator errors).
- Submission file: `submissions/scribe_actioneer_opus47.json` — 270 entries (54 queries x 5 trials).
- Full per-trial trace bundle (`submissions/scribe_actioneer_opus47_traces.zip`, 270 session logs with prompts + tool I/O) and the self-audit ledger (`submissions/scribe_actioneer_opus47_taint.json`) are committed in this PR for verification.
