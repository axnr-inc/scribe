# Iter-cap failures in agentic data analysis: a research memo

**Subject**: 97 of 228 Kimi K2.6 failures on the DABStep benchmark (450 tasks) are
"iter_capped" — the agent never produces a final text answer within a 25–30 tool-call
budget. This memo characterises the phenomenon empirically, situates it in the
agentic-LLM literature, develops falsifiable hypotheses, and proposes experiments.

**Author**: failure analysis on top of the Kimi K2.6 + DABStep run.
**Status**: draft v0.1.

---

## 1. The phenomenon, re-formulated

The default reading of "iter_capped" is *"the model spiralled — kept running similar
code until we cut it off."* The data refutes this for Kimi K2.6 base on DABStep:

| Trace feature on 97 iter_capped sessions | mean | median | what it tells us |
|---|---:|---:|---|
| `code_repetition_score` (shingle-Jaccard of consecutive code blocks) | 0.05 | 0.024 | 92 of 97 < 0.1 — the model writes **diverse** code each iter, NOT stuck-in-a-loop |
| `files_opened` (of 7 context files) | 5.21 | 5 | the model is **fully exploring** the corpus, not under-reading |
| `fee_conditions_applied` (of 9 fee fields) | 8.82 | 9 | the model is **applying the rules correctly**; no Bug #1 leakage |
| `python_errors` per session | 1.02 | 1 | error rate is real but low; 33% of sessions have zero errors |
| `intermediate_values_printed` (capped at 40 in extractor) | 40 | 40 | the model emits **massive** intermediate output — lots of verification |
| `thinking_blocks` | 0 | 0 | confirmed: Kimi K2.6 base run, no reasoning emitted |
| `claim_vs_action_gaps` | 0 | 0 | the model isn't promising-and-failing; it just keeps working |

The portrait is not a model thrashing. It's a model **doing thorough analysis but never
deciding the analysis is finished**. Each iteration adds a new view of the data — a
new filter, a new aggregation, a new sanity-check — none of which the model treats as
the terminal one.

I propose renaming this failure mode in our own analysis:

> **`iter_capped` is the "infinite verification" failure mode: the model has the
> capacity to produce an answer but lacks the meta-prior that says *"I am done.
> Commit."* It substitutes "compute more" for "commit and stop".**

This re-framing matters because the typical fixes for spirals (deduplicate code,
detect loops, force divergence) won't help here. The fixes for *non-commitment* are
different: explicit budget hints, forced-finalize prompts, output-format priming.

## 2. Topic distribution of iter_capped failures

| topic | iter_capped count | total in topic | iter_capped rate within topic |
|---|---:|---:|---:|
| fee_rule | 37 | 90 | 41% |
| date_specific | 23 | 83 | 28% |
| delta_what_if | 19 | 120 | 16% |
| aci_format | 16 | 71 | 23% |
| merchant_lookup | 1 | 9 | 11% |
| reference_lookup | 1 | 12 | 8% |

iter_capped concentrates on tasks that require **multi-table joins + per-row rule
application** (fee_rule, date_specific). On `transaction_count` / `other` /
`fraud_metric` it doesn't appear at all — those tasks have a clear "stop" signal
(one number or one category).

This is consistent with the "infinite verification" framing: tasks where the answer is
a single derived value have clear termination ("got the number → done"). Tasks
involving rule-by-rule application don't — there's always one more rule to double-
check, one more transaction to verify.

## 3. Cross-model evidence (from our prior runs)

Same DABStep tasks, different models, different iter counts:

| Task | Kimi-2.6 off | Kimi-2.6 reasoning | Opus-4.6 reasoning | Deepseek-v3.2 reasoning |
|---|---:|---:|---:|---:|
| 2715 | 24 (answered) | 13 (answered) | 16 (answered) | 30 (cap) → 49 (cap=60) |
| 2740 | 24 (answered) | 17 (answered) | 9 (answered) | 26 (answered) |
| 2703 | 17 (answered) | 30 (cap) | 10 (answered) | n/a |
| 1681 (dev) | 17 | n/a | n/a | 17 |

Three model-class behaviours emerge:

1. **Opus 4.6 (closed-source frontier)** converges in 9–16 tool calls across all tasks
   tested. Tight reasoning, clear stop.
2. **Kimi K2.6 base, no reasoning** uses 17–24 tool calls and *does* commit (rarely
   hits the cap on these). Quick commitments, often wrong, but never iter-capped on
   the small sample.
3. **Reasoning models** are bimodal: on tasks they "get", they're tight (Opus 9–16).
   On tasks they're uncertain about, they over-explore (deepseek hit 30-cap on 2715,
   needed 49 iters; Kimi-reasoning hit 30-cap on 2703).

**Provisional cross-model observation:** *reasoning ability does not monotonically
shorten the tool-use chain.* It tightens convergence when the model is confident, but
elongates it when the model is uncertain. So a reasoning model can either fix
iter_capped or make it worse, depending on how the model handles its own uncertainty.

## 4. Literature context

The "non-convergence" failure mode is **under-studied** in the agentic-LLM literature.
Most evaluations focus on whether the final answer is right, not on the distribution
of trace lengths or the share of runs that don't terminate.

Pieces that are adjacent:

- **ReAct** (Yao et al., 2022). Frames the thought-action-observation loop. Treats
  termination implicitly ("model emits no more actions").
- **Reflexion** (Shinn et al., 2023). Adds self-reflection between attempts. Shows
  reflection can fix errors. *But also implicitly assumes the model knows when to
  stop and reflect.* No analysis of cases where the model keeps reflecting forever.
- **Toolformer** (Schick et al., 2023). Self-supervised tool learning. Doesn't address
  multi-tool agentic chains or termination.
- **Scaling test-time compute** (Snell et al., 2024). Shows test-time compute scaling
  helps. But there's a sweet spot — beyond it, returns diminish. Implies a hidden
  optimum-compute that the model should learn to target.
- **GAIA** (Mialon et al., 2023) and **AgentBench** (Liu et al., 2023). Both treat
  agentic tasks but report only final correctness, not termination behaviour.
- **DABStep** (Adyen, 2025) — our benchmark. Reports task scores; doesn't break down
  by failure mechanism.

The gap: **no published study (to my knowledge) characterises non-convergence as a
distinct failure mode in agentic data-analysis benchmarks, nor measures the cost
distribution of premature-stop vs over-verification.**

That gap is the research direction. Concretely:

> *"Termination calibration in tool-using LLM agents on structured data tasks"* —
> a study of when models stop, why they don't, and how to teach them.

This is a publishable angle. The work would sit at the intersection of agentic
benchmarks (DABStep / GAIA / AgentBench), test-time compute scaling (Snell 2024),
and instruction-tuning for tool-use (Reflexion / ToolBench).

## 5. Hypotheses

Five candidates, ordered by my prior on explanatory power:

### H1: **Weak terminate-and-commit prior** (most likely)
Kimi K2.6 base is trained on conversational + instruction data but has no
specific signal for "you have enough; commit now". The model's emission distribution
puts almost-zero mass on producing a clean final text answer in a tool-using context.
Each iter it tends to either (a) emit another tool_call, or (b) emit minimal text
that doesn't satisfy our "is this a final answer?" check.

Falsifiable: if H1 is right, models with explicit tool-use post-training (Anthropic
Opus, OpenAI's tool-calling models) will have stronger termination priors and lower
iter_capped rates on the same tasks. The Opus observation supports H1.

### H2: **Self-verification anxiety on partial-coverage data**
On tasks where some transactions / rules don't match cleanly (Bug #2 territory), the
model interprets the discrepancy as a signal to verify more rather than commit. The
absence of a clean closed-form check makes the model keep poking.

Falsifiable: iter_capped rate should correlate with **rule-coverage discontinuity** in
the data — tasks where some merchant/ACI/date combinations have no matching fee rule
should have higher iter_capped rates than tasks with full rule coverage.

### H3: **Format anxiety bleeds compute**
DABStep guideline format strings have known issues (the `{card_scheme}:{fee}`
placeholder typo on ACI tasks). Reasoning models spend iterations debating format
ambiguity. On Kimi-reasoning runs we observed this explicitly in the trace.

Falsifiable: prompts that explicitly disambiguate output format should reduce iter
counts on the affected task families.

### H4: **Multi-table-join task hardness**
Tasks requiring per-row join + per-row rule application (fee_rule, date_specific) are
inherently more verification-prone than scalar lookup tasks. The iter_capped
distribution heavily favours these topics — consistent with H4.

Falsifiable: control for task structure. Tasks of equal computational complexity but
different "verification surface area" should have different iter_capped rates.

### H5: **Open-source vs frontier model convergence asymmetry**
Beyond "weak terminate prior" (H1), open-source models may have a systematically
*lower training signal density on agentic tool-use*. They generate more
exploratory-looking code per iter because they've seen less data on "produce a
concise tool-using chain". Their iter counts are higher even when they're working
correctly.

Falsifiable: on tasks where both Opus and Kimi succeed, count iters. If Kimi
consistently uses 2× as many tool calls as Opus to reach the same right answer, H5
is supported (independent of iter_capped failures).

These hypotheses are not mutually exclusive. H1 is likely the dominant primary
mechanism with H2-H4 acting as modulators.

## 6. Experiments — designed to discriminate hypotheses

### Experiment A — Budget-scaling on a fixed iter_capped sample
**Goal**: characterise convergence as a function of budget. Tests H1 (does Kimi
*ever* converge if given enough rope?) and quantifies the bottom-of-the-curve gain.

**Method**: pick 10 iter_capped Kimi tasks stratified by topic. Re-run each at
budgets {25, 50, 100, 200}. Measure (a) does the model produce an answer, (b) iter
count at first commit, (c) per-budget cost.

**Expected outcomes**:
- If Kimi converges by 50 → H1 is the cap setting, not a deep model limitation.
- If Kimi keeps running to 100, 200 without converging → H1 is a fundamental model
  trait. Strong evidence for "missing termination prior".

**Cost**: 40 sessions × ~$0.30–1.00 each (higher budget = higher cost on cap'd ones)
= roughly $20–40.

### Experiment B — Cross-model panel on iter_capped tasks
**Goal**: quantify cross-model convergence asymmetry (H1, H5).

**Method**: same 10 iter_capped Kimi tasks, run on:
- Kimi K2.6 base
- Kimi K2.6 + reasoning
- Opus 4.6 + reasoning
- Deepseek v3.2 + reasoning
- GLM-5.1 base
- Qwen3-coder

Budget = 50 (generous to absorb expected over-shooting). Measure iter count
distribution per model.

**Expected outcomes**:
- Opus iter count stays low (~10–15). Open-source models scatter higher (20–50+).
  If so, H5 (open-source convergence asymmetry) is supported.

**Cost**: 6 models × 10 tasks ≈ 60 sessions × variable cost ≈ $80–150.

### Experiment C — Convergence-hint prompt intervention
**Goal**: test whether explicit budget hints in the prompt induce earlier termination
without harming accuracy (H1, H3).

**Method**: rerun the same 10 iter_capped tasks with Kimi K2.6 base + the new
prompt addendum:

> "You have at most 12 tool calls in this session. Each call should make
> measurable progress toward the answer. Once you have computed the requested
> value, immediately print() it AND emit a single-line final text answer matching
> the Guidelines format. Do NOT re-verify already-computed values."

Measure: iter count, success rate, vs unmodified baseline.

**Expected outcomes**:
- Best case: most tasks now produce an answer in ≤12 iters with accuracy similar
  to / better than the unmodified baseline. Supports H1 — the model just needed
  the convergence signal in the prompt.
- Worst case: model still hits cap; or commits too early to a wrong answer.

**Cost**: 10 sessions ≈ $5.

### Experiment D — Rule-coverage probe (tests H2)
**Goal**: does iter_capped correlate with rule-coverage discontinuity?

**Method**: for each of the 450 tasks, pre-compute whether the canonical solution
involves an "uncovered" rule case (some merchant/date/ACI combination has no
matching fee rule). Bucket tasks by coverage-discontinuity-present vs not.

Statistical test: chi-square iter_capped × coverage-discontinuity. If iter_capped
concentrates on discontinuity tasks → H2 supported.

**Cost**: pure analysis on existing data, no API spend.

### Experiment E — Trace surgery: Kimi prefix → Opus completion
**Goal**: distinguish "Kimi can't find the answer" from "Kimi can't decide to stop".

**Method**: pick an iter_capped Kimi session at iter N. Replay iters 1..N as
Opus's input (give Opus Kimi's tool_calls + their results as conversation history),
let Opus continue. Measure additional iters Opus needs to terminate.

**Expected outcomes**:
- If Opus terminates in 1-3 additional iters from Kimi's prefix → Kimi was AT the
  answer but couldn't see it. Strong evidence for H1 (termination prior gap).
- If Opus also needs 10+ iters → the analysis genuinely wasn't complete in Kimi's
  prefix.

**Cost**: 10 prefix-completion runs ≈ $10–20. Trace-surgery infra is new; needs a
small harness modification.

### Experiment F — Self-consistency probe
**Goal**: did Kimi already compute the right answer somewhere in its trace?

**Method**: for each iter_capped session, parse intermediate prints. Compute whether
the leaderboard-correct answer appears as a substring in any tool_result. If yes,
the model "had" the answer but didn't recognise it.

We already have hints from our `no_assistant_response` analysis that ~26 of 35 NAR
sessions didn't have the answer computed in the trace at all. For iter_capped the
median intermediate_values count is 40 — substantially more printed work. Worth
measuring.

**Cost**: pure analysis on existing data.

### Experiment G — Format-disambiguation intervention (tests H3)
**Goal**: do output-format hints reduce iter counts?

**Method**: rerun the 10 iter_capped tasks with the prompt addendum:

> "For ACI questions, the leaderboard expects the ACI LETTER ONLY (e.g. `D`), not
> `{card_scheme}:{fee}` (the guideline placeholder is misleading). For numeric
> questions, round to the decimal places shown in any example given."

Measure iter counts vs unmodified baseline.

**Cost**: 10 sessions ≈ $5.

## 7. Concrete near-term plan

A natural sequencing of the experiments above by cost / information value:

1. **F** (self-consistency probe) and **D** (rule-coverage probe) — zero API cost,
   pure analysis. Run today.
2. **C** (convergence-hint prompt) — $5, fast feedback on H1.
3. **A** (budget scaling) — $20–40, definitive on H1.
4. **B** (cross-model panel) — $80–150, addresses H5 and is publishable.
5. **E** (trace surgery) — needs harness mod. Highest information-per-dollar if it
   shows Opus closing in 1-3 iters from Kimi's prefix.

## 8. Where this fits in the bigger picture

Two paper angles I'd consider:

### Paper 1: "Premature stop and infinite verification: dual failure modes in
tool-using LLM agents on structured data tasks"
A characterisation paper. Take DABStep (or a similar agentic benchmark), break
failures into termination-behaviour buckets (premature stop / over-verify / wrong
content / format), measure across 4-6 model classes (open vs closed, reasoning vs
not), and propose **termination calibration** as a new evaluation dimension.

Strength: this is empirically novel — no one has measured this systematically.
Weakness: descriptive papers are harder to land than methods papers.

### Paper 2: "Termination-aware prompting for cost-efficient tool-using agents"
A methods paper. Show that simple prompt-level termination signals (budget hints,
verification-cap rules, format disambiguators) reduce iter_capped rates by X% while
maintaining or improving accuracy across models. Frame as cost-efficiency: "we
recover ~30% of failures with no extra compute by changing the prompt".

Strength: actionable, evaluable, hard to dispute if numbers hold.
Weakness: prompt-engineering papers risk being seen as fragile; need to show
robustness across model classes and benchmarks.

### Most ambitious: a fine-tuning angle
If H1 is supported and the open-source vs frontier asymmetry is real, the next move
is a **small fine-tuning study**: take an open-source model (Qwen-coder), fine-tune
on termination-labeled traces (where to stop, what to print as final answer), and
show that small targeted fine-tuning closes the iter_capped gap with frontier models.
That's a bigger project but a real PhD-thesis-shaped contribution.

## 9. Open questions for further work

- Does iter_capped behaviour vary with prompt length? (Long system prompts may eat
  budget the model doesn't account for.)
- Is iter_capped a feature of agentic SCAFFOLDING design, or of the model itself?
  Replacing the harness's loop logic with a different protocol (e.g. AutoGen-style
  multi-agent verifier) could change the answer.
- Can we predict iter_capped ex ante from task structure? A small classifier that
  predicts "this task will iter_cap on Kimi" could route only those tasks to Opus,
  enabling cheap-with-fallback inference.

---

End memo.
