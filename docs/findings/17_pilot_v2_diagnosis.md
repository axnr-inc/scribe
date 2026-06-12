# Pilot v2 (Krama-failed-5) diagnosis — 2026-06-06

Re-ran the 5 Krama-archeology-hard tasks that failed in P1 (hard-1, 2, 5, 9, 12) with the P2b multi-shot spec_agent + the new Krama HELPER_MANIFEST + iter_cap 60. Sharded across both Fireworks keys for parallelism.

**Headline result: 0 / 5 PASS.** Same verdict as P1 on these 5 tasks, different wrong numbers.

## What was different in v2

| Lever | P1 (baseline) | v2 (this run) |
|---|---|---|
| spec_agent | one-shot, save_spec-only (1 tool) | P2b multi-shot, MAX_TOOL_TURNS=5, read_file + read_data_file + list_files + save_spec (4 tools) |
| spec quality | blind extraction (openpyxl was missing) | data-verified extraction (samples + multi-header detection) |
| executor REPL preamble | pandas/numpy/sqlite base | + 5 Krama helpers pre-imported (read_multi_header_excel, parse_missing_marker, safe_dedupe, linear_interp_by_key, bp_to_calendar_year) |
| iter_cap | 40 | 40 (Krama; DABStep got 60) |
| Models | GPT-5 spec+planner, Kimi-K2.6 exec | unchanged |

## Per-task result

| Task | Gold | v2 answer | Δ | helper used | iter / tool_calls | wall / cost |
|---|---|---|---|---|---|---|
| hard-1 | 8577.5298 | 8347.1887 | -2.7% | read_multi_header_excel | 10 / 9 | 95s / $0.14 |
| hard-2 | 38.42 | 49.75 | +29% | read_multi_header_excel | 10 / 9 | 76s / $0.12 |
| hard-5 | 66158.3691 | 36815.2633 | -44% | read_multi_header_excel + bp_to_calendar_year | 17 / 16 | 126s / $0.26 |
| hard-9 | 0.015648 | -0.210104 | sign flip + 13× | none (CSV-only task) | 10 / 9 | 123s / $0.14 |
| hard-12 | 409 | 1146 | +180% | safe_dedupe | 17 / 16 | 120s / $0.16 |

**Total cost:** $0.82. **Avg iter:** 12.8 / 40 — far from the cap. **No iter-caps.**

## Per-task root-cause diagnosis

### hard-1 (-2.7%) — date-convention mismatch

- Spec: oldest_BP = max raw `date` column, youngest_BP = min — divide by 1000 → ky.
- Reality: gold likely uses calibrated dates from `Cal. BC 1 sigma` / `Cal. BC 2 sigma` columns, not raw `date` (14C years BP). The spec_agent saw the `date` column in the sample and committed to raw BP/1000 without checking whether the calibrated columns were the intended source.
- Planner verified within this frame. SPEC_WRONG didn't fire because nothing in the docs *contradicts* using `date`; it's just not the convention the task author intended.

### hard-2 (+29%) — time-direction ambiguity

- Question: "percent of years the wet-dry index was increasing".
- Spec interpretation: sort by Age_ky ascending → index "increases" as Age_ky increases (= going backward in time).
- Likely gold interpretation: sort by *calendar time* ascending → index increases as Age_ky *decreases*.
- Both interpretations are defensible. Spec picked one; planner verified within it.

### hard-5 (-44%) — wrong Age_ky column

- The climate file has 4 columns named "Age_ky" (one per panel: elemental, PC, Dust, wet-dry).
- Spec instructed: "use the first Age_ky column paired with the elemental Al/K/etc panel".
- Executor used the helpers correctly, but may have paired against the wrong Age_ky (the column-disambiguation logic in the spec was opaque).
- Could also be the tie-break for "most northern Neolithic" — "ties broken by later year" requires picking the correct year convention (calibrated vs raw BP).

### hard-9 (sign flip, 13×) — semantic inversion of rank

- Pipeline: 39 distance<0.1° matches → 30 after "keep last roman_idx" → Pearson(rank, population).
- Result: -0.21 (gold: +0.016).
- Likely cause: **Barrington Atlas rank semantics inverted**. Low rank = high importance. Spec didn't note this. The negative correlation is *correct* for raw rank values but the question implicitly assumes "importance" axis, which inverts the sign.
- Secondary possibility: "keep last" tie-break direction inverted — gold may use "first" or the closest by distance.

### hard-12 (+180%) — dedup granularity too loose

- Spec: dedup by (Conflict, StartYear, EndYear) tuple.
- Gold (409 vs our 1146 — ratio 2.8×): gold probably dedupes by `Conflict` name only (so "Bohemia-Germany 1390-1402" and "Bohemia-Germany 1389-1395" count as one).
- The "lasting at least a year" interpretation is also under-specified — spec used `EndYear - StartYear + 1 >= 1` which is almost always true.

## The dominant failure mode is **F-E (executor + planner consensus on wrong)**

In all 5 failures the pattern is identical:

1. **spec_agent** commits to a plausible-but-arguable question interpretation
2. **executor** faithfully implements the spec; produces a number
3. **executor** calls `ask_planner_agent` with a structured summary
4. **planner_agent** verifies *within the spec's frame*; returns `[Verdict: ANSWER]`
5. Executor commits the wrong answer

None of the cascade's 5 verdicts catches this:
- **SPEC_WRONG** requires concrete doc-contradiction; here the spec is *defensible*, not contradicted
- **BLIND_SPOT** requires the executor asking the wrong question; here the executor asked the right one (per the spec)
- **EXECUTOR_WRONG** requires misimplementation; the executor implemented correctly
- **NA_CONFIRMED** is for NA cases
- **ANSWER** is what fires — the planner sees nothing wrong because the spec frames the question

**The cascade has no authority to second-guess the spec's question-interpretation.**

This is the same F-E pattern observed in P1 (`12_3bench_pilot_synthesis.md`, `06_krama_failure_analysis.md`). P2b + HELPER_MANIFEST raised the spec's mechanical floor (right columns, right dtypes, right helpers) but did NOT address the semantic ambiguity at question→spec translation. They're necessary but not sufficient.

## Three interventions (planned for v3)

### I-1 — Question-restating gate (smallest, do first)

Force spec_agent to surface 2-3 plausible question interpretations in an `_interpretations` field BEFORE committing to one. The chosen interpretation is justified in the spec; alternatives stay visible to the planner.

Expected lever: gives the planner a way to dissent ("you picked interpretation A; alternative B better matches the docs"). Adds ~5% spec-extraction time.

### I-2 — Multi-spec sampling (biggest leverage)

Generate N=3 specs per task, each with a different ambiguity-resolution stance ("strict literal", "domain-conventional", "permissive"). Run each → N candidate answers. Pick by:
- Majority vote (when 2 of 3 agree), OR
- Spec-adjudicator call that examines the disagreement and picks

Expected lever: ambiguity-driven failures (hard-1, hard-2, hard-9, hard-12 — 4 of 5) become *resolvable* if any of N specs aligns with gold. Cost is N× spec+exec, so ~3× the per-task cost. Worth it on hard subsets.

### I-3 — SPEC_DOUBT (6th verdict)

Add `SPEC_DOUBT` to the cascade. Fires when planner believes the answer LOOKS plausible but the spec's framing has interpretive ambiguity that could matter. Triggers a re-spec with an alternative interpretation.

Risk: the planner is the SAME model that committed the spec; it may not catch itself. Mitigation: re-spec uses the *other* model (e.g., executor as second opinion).

Expected lever: moderate. Catches F-E only when the planner has metacognitive doubt — won't help when the planner is confident-but-wrong.

## Model swap for v3 — fully open-source stack

Per user direction, removing GPT-5 (closed) AND swapping Kimi-K2.6 → a different open-source executor. New topology:

| Role | Model (was) | Model (v3) | Provider |
|---|---|---|---|
| spec_agent | openai/gpt-5 | **deepseek/deepseek-chat-v3.1** | OpenRouter |
| planner_agent | openai/gpt-5 | **deepseek/deepseek-chat-v3.1** | OpenRouter |
| executor | accounts/fireworks/models/kimi-k2p6 | **accounts/fireworks/models/qwen3-coder-30b-a3b-instruct** | Fireworks / Fireworks2 |

**Why DeepSeek-V3.1 for planner+spec_agent:**
- Open-source (MIT-style license).
- Strongest non-R1 reasoning available on common providers; competitive with GPT-5 on reasoning benchmarks.
- Available via OpenRouter (where our extract_specs scripts already work) — no harness code changes needed beyond the model string.
- Faster than R1 (no chain-of-thought tax) → reasonable spec_agent latency.

**Why Qwen3-Coder-30B-A3B-Instruct for executor:**
- Open-source (Apache 2.0).
- Code-specialized — pre-trained heavily on code + tool-calling traces; designed for the executor role.
- Smaller than Kimi-K2.6 (30B-A3B MoE active vs 1.6T total params) → faster per-iteration latency on Fireworks.
- DIFFERENT model family than the planner (DeepSeek) — this means when the executor calls `ask_planner_agent`, there's genuine cross-model dissent capability (a same-model planner/executor pair tends to agree on shared errors).
- User's original architecture pick (from earlier in this conversation) — switching back deliberately after Kimi-K2.6's F-E results.

**Why NOT Kimi-K2.6 anymore for executor:**
- Validated but produced F-E (executor+planner consensus on wrong) on all 5 Krama-hard failures in v2.
- Same-model cascade (Kimi + GPT-5 are both "frontier-class generalist") collapsed to confident-wrong on ambiguous tasks.
- Switching to a smaller code-specialized model + larger reasoning planner creates the asymmetry needed for cascade dissent.

## What this finding does NOT say

- It does not say P2b is useless. P2b is necessary infrastructure; the helpers + verifier tool surface raised the *floor* of spec quality. F-E is a *ceiling* problem.
- It does not say the 5-verdict cascade is wrong. The cascade works for the failure modes it was designed for (executor errors, missed docs, spec contradictions). F-E is a new failure mode.
- It does not generalize to easy tasks. P1 archeology-easy was 4/8 pass; we haven't re-run v2 on easies. Possible v2 regresses some easies due to spec rigidity, but more likely it doesn't matter (easies are easy by definition).

## Related docs

- `06_krama_failure_analysis.md` — original F-E pattern observation
- `12_3bench_pilot_synthesis.md` — P1 pilot synthesis
- `15_decisions_2026-06-06.md` — LiveSQL deferred, HELPER_MANIFEST added, Fireworks2 sharding
- `16_experimental_audit.md` — flagged Krama-42% framing + memorization gaps
- (forthcoming) `18_v3_interventions.md` — implementation notes for I-1/I-2/I-3
