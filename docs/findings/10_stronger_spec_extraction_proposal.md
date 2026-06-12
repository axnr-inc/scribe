# Stronger spec extraction — proposal (P2b+)

The `06_krama_failure_analysis.md` and `07_livesql_failure_analysis.md` failure analyses converge on one finding: **the harness ceiling is set by spec-extraction quality.** Every layer downstream of `<task_id>.json` works correctly. The bottleneck is the spec_agent producing a spec that's logically consistent with docs but missing the gold's intended interpretation (F-E).

This document proposes a roadmap for fixing this.

## Where we are

### spec_agent's current capabilities
- **One LLM call** (no iteration)
- **One tool**: `save_spec` (forced via Anthropic `tool_choice`, or via OpenRouter `response_format=json_object`)
- **No other tools**: no `read_file`, no data sampling, no `query_fees`, no verification, no `verify_step`
- **Input context**: full source docs in user message (manual.md + fees.json + ... for DABStep; data file samples for Krama; schema + KB JSONL + column meanings for LiveSQL)
- **Output**: one structured spec via `save_spec`

### What it cannot do
- Re-read specific doc sections during reasoning
- Sample actual data values
- Run sample queries against the DB
- Test JSON path extraction
- Verify formula interpretations against example rows
- Iterate ("hmm, my first plan is wrong; let me revise")
- Self-consistency check (one answer, no ensemble)

## The proposal — 5 incremental enhancements

Ordered from least to most invasive.

### P2b.1 — Give spec_agent `read_file`

**Effort**: ~50 LOC per extractor (3 of them) — pattern already exists in `ask_planner.ts`.

**Why**: When the spec_agent is about to commit a key interpretation choice (e.g., "I'll use Euclidean distance ≤ 0.1 degrees for ancient-modern city matching"), it should be able to re-read the relevant section of docs to verify. Today, it has the docs in its initial message but no way to deliberately re-consult during its reasoning chain.

**Estimated lift**: +3-5% on average across benchmarks. Bigger lift on tasks where docs have a critical disambiguating detail.

### P2b.2 — Give spec_agent `query_fees` (DABStep) / `sample_table(name, n)` (LiveSQL) / `read_data_file(path)` (Krama)

**Effort**: ~200 LOC total. Adapt existing planner-side `query_fees` for spec_agent's call path; add new lightweight sampling tools.

**Why**: F-E failures often trace to spec_agent making interpretation choices it cannot verify. Examples:
- Krama hard-9 (Pearson sign wrong): spec_agent should have sampled `worldcities.csv` to see population distribution at the city-matching threshold
- LiveSQL credit_5 (LTV wrong): spec_agent should have sampled `expenses_and_assets.propfinancialdata` to verify the `$.propvalue` JSON path actually exists
- LiveSQL virtual_10 (hit revision cap): spec_agent never saw actual `engagement` or `interactions` tables — couldn't catch the FEI formula interpretation gap

**Estimated lift**: +5-10% average. Bigger on JSON-heavy LiveSQL tasks (probably +10-15% there).

### P2b.3 — Multi-shot reasoning loop

**Effort**: ~150 LOC of orchestration. Modify extractor `main()` to run a 2-3 turn loop:
1. **Round 1**: read docs + initial spec draft
2. **Round 2**: read targeted sections + sample data + verify assumptions → revise spec
3. **Round 3** (optional): final commit

**Why**: Today's spec extraction is a "draft once, ship" pattern. Replacing it with "draft, verify, refine" mirrors what a human analyst would do. Most production data-quality tooling (Great Expectations, pandera) embeds this iteration.

**Estimated lift**: +5-10%. Probably saturates at 3 rounds (Self-Debug finding).

**Cost**: 2-3x token spend per spec extraction. For 450 DABStep tasks: ~$150 extra. Acceptable.

### P2b.4 — Self-consistency sampling

**Effort**: ~80 LOC orchestration + spec merger.

**Why**: Extract N=3-5 specs with different temperatures or with different `system` framing. Compare. If they all agree → high confidence. If they diverge → that signals the question is ambiguous and the spec_agent should escalate (a NEW state — "spec_agent uncertain").

**Estimated lift**: +3-5%. Higher false-positive rate (some divergences are real ambiguity in the task).

**Cost**: N× spec extraction. For N=3: 3x token cost. ~$450 extra for full DABStep run.

### P2b.5 — External-verifier guided extraction

**Effort**: ~250 LOC. Most invasive.

**Why**: For benchmarks with sub-task golds (Krama provides this), the spec_agent could RUN its proposed pipeline against the sub-task verifiers before committing. If sub-tasks fail, refine spec. This bridges the gap between "logically consistent with docs" and "logically consistent with gold's intent."

**Estimated lift**: +10-20% on Krama (where sub-task golds exist). 0% lift on DABStep (no sub-task golds publicly).

**Cost**: Per-extraction execution cost. Material engineering.

## Recommended priority sequence

1. **P2b.1 + P2b.2 together** (~250 LOC, ~3 days work) — biggest bang for buck. Catches most F-E failures where spec_agent needed to verify a single fact.
2. **P2b.3 multi-shot** (~150 LOC, ~2 days) — implement after P2b.1+.2 since the loop needs the tools.
3. **P2b.5 external verifier** (~250 LOC, ~5 days) — only for Krama (where sub-task golds exist). High lift, narrow applicability.
4. **P2b.4 self-consistency** — optional. Only worth it if P2b.1-3 don't close enough of the gap.

Total for P2b.1-3 (the core proposal): ~400 LOC, ~5 days, $1-2 in extra inference cost per pilot run.

## Per-benchmark expected lift

After full P2b.1-3:

| Benchmark | Current pilot | After P2b.1-3 | After +P2b.5 |
|---|---|---|---|
| DABStep | 0/10 (0%) — confused first task already 1712 | +10-15% | +10-15% (no sub-task gold) |
| Krama | 5/12 (42%) | +5-10% | +15-25% (sub-task gold available) |
| LiveSQL | 1/10 (10%) | **+10-15%** (biggest lever for SQL — sample DB during extraction) | +10-15% |

These are educated guesses based on the lit review (`05_verifier_lit_review.md` set the +5-12% Self-Debug envelope) and the failure-mode analysis.

## Implementation gotchas

1. **Anthropic forced tool_choice**: If we add `read_file` etc., we cannot also force `tool_choice="save_spec"`. Spec_agent now has to choose when to call `save_spec`. Acceptable behavior change.
2. **Token budget**: Tools that re-read full files re-cost the input context. Use targeted reads (line ranges or section names).
3. **Loop budget**: cap at 3 rounds + 5 tool calls per round to prevent runaway.
4. **Concurrent extraction**: LiveSQL extractor already uses 5 workers; multi-shot may conflict. Reduce workers if spec_agent gets expensive.

## What this won't fix

- Pure model-capability gaps (Kimi vs better-future-model)
- Tasks where the gold answer is one of multiple reasonable interpretations (annotation noise)
- F-A (compute-success-commit-failure) — that's executor behavior, handled by EC5 + pre-commit gate
- Pure execution bugs (the executor's pandas code is buggy) — Tier A/B/C still catches these

## Related docs

- `06_krama_failure_analysis.md` + `07_livesql_failure_analysis.md` — the empirical motivation
- `08_architecture_component_tool_inventory.md` — what spec_agent has today
- `09_pandas_bias_in_architecture.md` — why LiveSQL needs the most help
- `11_research_insights.md` — why this is paper-worthy
