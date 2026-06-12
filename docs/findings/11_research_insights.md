# Critical research insights — paper-worthy claims

This document captures the most surprising and well-supported claims that have emerged across the SCRIBE development cycle. These are the candidate contributions for a paper.

## Insight 1: The "executor + planner consensus on wrong" failure mode (F-E) is dominant

**Claim**: When a docs-grounded executor and a docs-grounded planner cascade are both reading the same source artifacts, they reach the same interpretation of the question. If that interpretation differs from the gold's intended interpretation, BOTH agents converge on the same wrong answer with high confidence.

**Evidence**:
- Krama pilot 12: 6 of 7 failures are F-E (executor + planner ANSWER on wrong)
- LiveSQL pilot 10: 7+ of 9 failures are F-E
- DABStep 1712: planner used `query_fees` deterministically, quoted manual.md §5, verified executor's arithmetic, and approved the wrong answer with `[Verdict: ANSWER]`

**Implication**: Cascade-style review architectures (Reflexion, our planner_agent) have a structural ceiling set by the shared source-document interpretation. The cascade catches **structural** spec bugs (duplicate columns, missing wildcards) but not **interpretive** ones (what the question asker actually meant when they wrote "first time").

**Novelty**: Reflexion and CRITIC reported "execution feedback helps; verbal critique doesn't generalize." Our finding refines this: **execution + LLM critique helps when the critic has independent ground truth (unit tests, external verifier) but bounds at the joint-interpretation ceiling when both agents read the same docs.**

## Insight 2: The harness ceiling is set by spec-extraction quality, not by execution or verification

**Claim**: A correctly-implemented harness with a 5-verdict cascade, EC5 context reminders, P1 verifiers, mandatory pre-commit gates, and spec versioning still bottoms out at spec quality. Every layer downstream of `<task_id>.json` works correctly; failures concentrate at the spec layer.

**Evidence**:
- All 3 benchmarks show ZERO harness-implementation errors at pilot scale (0 Python errors, 0 cascade mis-firings, 0 spec-versioning bugs)
- Krama 42% pass rate matches the harness's ability to faithfully execute its specs
- 6 SPEC_WRONG verdicts fired across LiveSQL pilot 10 → 0 of those 3 tasks passed → the planner can revise specs but the revision doesn't always identify the actual gap

**Implication**: Subsequent harness optimizations (better tools, more verifiers, deeper cascades) yield diminishing returns until spec quality improves. **P2b (stronger spec extraction) is the highest-leverage open intervention.**

## Insight 3: EC5 (context-decay reminder) breaks the compute-success-commit-failure pattern

**Claim**: Inserting a short, conditional, recurring "you can escalate via ask_planner_agent" footer into every `tool_call_result` past iter 10 — silent if already escalated — empirically breaks the "compute-success, commit-failure" failure mode where the executor computes a valid answer but iter-caps without committing.

**Evidence**: DABStep 1712 across 4 runs:
- repro_pilot (no EC5): 31 tool calls, 3 escalations, committed "Not Applicable" (wrong)
- P2 v2 (no EC5): 19 tool calls, 0 escalations, blank commit (no answer)
- v1 smoke (no EC5): **40 tool calls, iter cap, blank commit**
- v2 smoke (with EC5): **16 tool calls, 1 escalation, committed `9.48` cleanly**

**Mechanism**: User-stated hypothesis that proved correct: "Kimi forgot to escalate because after many tool calls the rule was buried under stdout content." EC5 keeps the option in recent context where attention is strongest.

**Novelty**: Context-decay is documented in lost-in-the-middle literature. EC5 is the first (to our knowledge) **conditional reminder** that goes silent once the executor has complied — addressing the false-positive cost of always-on reminders.

## Insight 4: SCRIBE matches strong-model agentic systems with weaker base models

**Claim**: SCRIBE with Kimi-K2.6 + GPT-5 (cost ~$0.20/task) achieves 42% on KramaBench archeology — matching smolagents-DR with Claude-3.7 (44.44%, cost ~$0.60/task) and within reach of the 58% human baseline.

**Evidence**:
- KramaBench archeology pilot 12: 5/12 = 42%
- Cost per task: ~$0.20 (Kimi-K2.6 Fireworks + GPT-5 OpenRouter)
- Comparison: smolagents-DR Claude-3.7 on archeology = 44.44% per KramaBench paper Table 5

**Implication**: The harness mechanism (specifically: spec→executor→cascade with persistent revision) substitutes for raw model capability. This validates the **"capability budget should go to the task-solving agent, not the orchestrator"** finding from "Harness Updating Is Not Harness Benefit" (arxiv 2605.30621).

**Limitations**: LiveSQL pilot was 1/10 (poor); DABStep 1712 alone is not representative. Full ablations needed before publishing.

## Insight 5: SPEC_WRONG fires but doesn't always converge

**Claim**: The planner's ability to identify spec gaps is real but bounded. Multiple SPEC_WRONG verdicts on the same task can find DIFFERENT gaps each round without ever finding the actual underlying issue.

**Evidence**:
- LiveSQL virtual_10: 3 consecutive SPEC_WRONG verdicts (hit revision cap of 3); task still failed
- Krama hard-2: 1 SPEC_WRONG verdict identified duplicate-column handling (real gap, valid revision) but the underlying answer (49.75 vs gold 38.42) was driven by a different unidentified gap

**Mechanism**: The planner's R1-R5 verification re-reads source docs. It catches inconsistencies between spec and docs. But when the spec is consistent with docs AND wrong vs gold, R1-R5 has no signal.

**Implication**: Bumping the revision cap beyond 3 likely yields diminishing returns. The real lever is giving the planner **external ground truth** (sub-task golds, executable tests) — see Insight 1.

## Insight 6: Pandas paradigm has a structural advantage in cascade-style harnesses

**Claim**: A cascade-style harness with pandas-flavored tools (HELPER_MANIFEST, verify_step, AUTO-INSPECT, groupby/merge pattern triggers) lifts pandas-paradigm benchmarks (DABStep, Krama) more than it lifts SQL-paradigm benchmarks (LiveSQL).

**Evidence**: 
- After identical normalization, Krama gets 42%, DABStep gets ?(see below — pending), LiveSQL gets 10%
- LiveSQL needs paradigm-specific compensation: MANDATORY pre-commit gate (only LiveSQL has it); sqlglot pre-flight (only LiveSQL); but verify_step + Tier A/B are PYTHON-ONLY

**Implication**: Future text-to-SQL harness designs need symmetric tools (SQL helpers, schema-aware assertions). See `09_pandas_bias_in_architecture.md` for the catalog.

**Honest caveat**: This may also reflect benchmark difficulty — LiveSQLBench is harder per the paper. More controlled experiments needed to disentangle paradigm-bias from inherent task difficulty.

## Insight 7: The "alreadyPrintsShape" suppression is correct but reduces P1 coverage

**Claim**: P1 Tier A `[AUTO-INSPECT]` correctly suppresses when the executor's code already prints `.shape`/`.dtypes`/`.head()`. Kimi-K2.6's default coding style does this on every cell. Result: 0 of 95+ run_python calls across pilots showed AUTO-INSPECT output.

**Evidence**: Krama pilot 12: 0 AUTO-INSPECT fires across 86 run_python calls. DABStep pilot still running. All cells end `print(df.head(...))`.

**Implication**: Tier A delivers value to MODELS WHOSE STYLE DIFFERS FROM KIMI. For Kimi specifically, Tier A is dormant. Either (a) loosen the suppression to provide complementary info (dtypes when only shape was printed) or (b) accept that Tier A is model-style-dependent and focus on Tier B/C.

## Insight 8: Verify_step is opt-in and gets used rarely

**Claim**: Despite being available, verify_step was called on only 1 of 12 Krama tasks (8% opt-in rate). When called, all assertions returned PASS — meaning the executor used it only when it was already confident.

**Evidence**: Krama hard-9: 3 verify_step calls (row_count, non_null, column_exists) — all PASS. Executor still committed the wrong answer (opposite sign).

**Implication**: Opt-in verification is sociologically biased toward overconfident users. To get coverage, we need either (a) mandatory verify_step calls (analogous to mandatory pre-commit gate) or (b) auto-triggered verify_step on specific patterns (extension of Tier B).

## Insight 9: 100% benchmark-agnosticism is achievable through dispatch, not removal

**Claim**: Across 4+ audit rounds, the harness moved from "DABStep-only assumptions hardcoded in shared code" to "every shared interface dispatches per benchmark via a small set of detection functions." The 6 dispatchers (renderSpecForPrompt, requiredFieldsForSpec, makeFileManifest, hasFeesJson, tool selection by db_path, docsDir priority) cleanly handle all 3 benchmarks.

**Evidence**: Type A/B/C audit (P4 round 2) verified all dispatchers are exhaustive and correct. Zero hidden benchmark-specific code in shared TS modules.

**Implication**: Architecture can be made paradigm-agnostic without sacrificing paradigm-specific quality. The dispatcher pattern preserves both.

## Insight 10: Iterative R1-R5 from LiveSQL generalizes to all paradigms

**Claim**: The "5-step pre-reply verification" originally embedded in LiveSQL's spec_agent prompt (R1 re-read; R2 verify named concepts; R3 verify structural plan; R4 verify result dimensionality; R5 verify executor's intermediate evidence) was moved to the planner_agent system prompt in P4 cleanup. It now applies across DABStep + LiveSQL + Krama.

**Evidence**: Krama pilot 12 + LiveSQL pilot 10 traces show planner replies using R3 substitution language ("computation_plan / cte_plan / pipeline plan / matching logic"), executing R1 (read_file calls) before flagging SPEC_WRONG.

**Implication**: Some review-checklists are paradigm-portable when written abstractly. Worth carrying forward to other harness research.

## What's NOT yet a research insight

- "P1 verifiers improve accuracy" — pilot data so far shows 0 fires for Tier A and Tier B, low usage for Tier C. Need bigger pilots before claiming lift.
- "SCRIBE generalizes to a 4th benchmark" — not tested.
- "Specific verifier assertions catch specific bug families" — failure analysis suggestive but not measured.

## Open empirical questions

These would be follow-up papers:

1. What's the SPEC ↔ gold-interpretation gap distribution? Is it dominated by 1-2 categories (e.g., aggregation level, tie-break rule)?
2. Does multi-shot spec extraction (P2b.3) actually close the F-E gap, or just produces more confident-wrong specs?
3. Does sub-task gold verification (P2b.5) carry signal across benchmarks?
4. Is there a "spec quality measure" that predicts pilot accuracy without running the executor?

## Methodology for any paper

When reporting cross-benchmark numbers, **disclose**:
- Same executor model (Kimi-K2.6 on Fireworks) across all 3
- Same planner model (GPT-5 on OpenRouter) across all 3
- Same EC5 + cascade + pre-commit gate + verify_step (where applicable) across all 3
- HELPER_MANIFEST is DABStep-only (Asymmetry 1)
- Tier C is pandas-paradigm-only (no SQL assertions in v1)
- MANDATORY pre-commit gate fires on all 3 (post-P4 fix)
- Spec extraction was single-shot GPT-5 with save_spec only

Anything beyond this stack (e.g., P2b results, if implemented) should be reported as separate ablations.

## Related docs

- `01_harness_vs_model_failure_modes.md` — full taxonomy F-A through F-E
- `02_cross_benchmark_fairness.md` — what asymmetries remain
- `03_smoke_results_3bench.md` — pre-P1 smoke results
- `04_ec5_context_decay_mitigation.md` — Insight 3 deeper dive
- `05_p1_verifiers_design.md` + `05_verifier_lit_review.md` — Insight 7-8 grounding
- `06_krama_failure_analysis.md` + `07_livesql_failure_analysis.md` — Insight 1-2-5 empirical basis
- `08_architecture_component_tool_inventory.md` — Insight 9 catalog
- `09_pandas_bias_in_architecture.md` — Insight 6 deeper dive
- `10_stronger_spec_extraction_proposal.md` — what to do about Insight 2
