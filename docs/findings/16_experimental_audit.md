# Experimental audit — 2026-06-06

Pre-paper review of the 3-bench pilot setup. Author is acting as an independent reviewer checking for issues that would invalidate or mislead results.

## Audit scope

The 3-bench pilot (`docs/findings/12_3bench_pilot_synthesis.md`) reports 9/32 = 28% pass:
- DABStep: 3/10 (30%)
- LiveSQL: 1/10 (10%)
- Krama (archeology): 5/12 (42%)

This audit checks: data leakage, sample bias, reproducibility, prompt-version consistency, fairness, iter-cap accounting, memorization, and metadata integrity.

## CRITICAL flags

### FLAG 1 — Krama 42% is archeology-only, not Krama-wide

KramaBench has 104 tasks across 6 domains. Our pilot ran the FULL archeology subset (12 tasks), NOT a sample of the 104-task benchmark.

Per KramaBench paper Table 5 (smolagents-DR Claude-3.7 per-domain):

| Domain | smolagents-DR | Human |
|---|---|---|
| archeology | 44.44% | 58.33% |
| astronomy | 50.00% | 70.00% |
| biomedical | 38.89% | 100.00% |
| environment | 60.56% | 76.90% |
| legal | 61.23% | 86.67% |
| wildfire | 60.16% | 66.20% |
| **overall** | **55.83%** | **76.75%** |

**Implication:** Reporting "SCRIBE got 42% on KramaBench" without qualification is misleading. Honest framing: "42% on KramaBench archeology" — matches the 44% archeology-specific baseline. The "matches smolagents-DR" claim is ONLY valid for archeology, NOT Krama-wide.

**Severity:** Critical. Paper-claim implications.

**Recovery:** Always qualify as "archeology-only" until other domains are pulled (Krama has astronomy, biomedical, environment, legal, wildfire data lakes that need downloading).

### FLAG 2 — Memorization untested

KramaBench paper §4.1 reports an obscured-input experiment: real identifiers (city names, dates, places) replaced with synthetic ones. Claude-3.7 Reflexion drops **62.81% → 12.77%** on this variant. The drop measures memorization vs actual pipeline-building.

We did NOT run the obscured-input variant for Krama. Our 42% archeology result MAY include memorization lift — GPT-5 (used for both spec_agent AND planner_agent) has likely seen world-cities, archaeological site names, KB articles, in its training set.

**Implication:** Cannot make a leakage-free claim without obscured-input testing.

**Severity:** Critical for academic claims.

**Recovery:** Pull KramaBench's obscured variants and re-run. The Krama dataset's `data/kramabench/` likely needs an `obscured/` variant download.

## HIGH flags

### FLAG 3 — Sample bias on all 3 pilots

| Benchmark | Task selection |
|---|---|
| DABStep | First 10 hard tasks from `hard_all378.jsonl` after `pilot5` skip — NOT random |
| LiveSQL | First 10 from `livesql_harness_tasks.jsonl` after `virtual_3` skip — NOT random |
| Krama | All 12 archeology tasks — NOT a sample (full small domain) |

For DABStep + LiveSQL: convenience sampling. The first 10 in the file may be systematically easier or harder than average. Pass rates do not generalize to the full benchmark.

**Implication:** "DABStep 30% on 10 tasks" doesn't predict "DABStep ~30% on 378 hard tasks." Need a random sample (or full run) to extrapolate.

**Recovery:** Replace `first 10` with `random.seed(42); random.sample(tasks, 10)`. Re-run pilots.

### FLAG 4 — LiveSQL spec `_meta.extractor` field missing

DABStep + Krama specs persist `_meta: {extractor: 'openrouter:openai/gpt-5', input_tokens: ..., output_tokens: ...}`. LiveSQL specs persist `_meta: {}` (empty).

The pilot DID use OpenRouter GPT-5 (per `run_manifest.json`), but the file-level metadata is missing. Recordkeeping/reproducibility issue.

**Severity:** High for reproducibility, doesn't invalidate result.

**Recovery:** `extract_specs_livesql.py` needs to add the `_meta` field assignment that DABStep + Krama have. ~5 LOC fix.

### FLAG 5 — Spec extractors modified after pilot ran

- Pilot specs created: 17:20–17:22 (Jun 6)
- P2b agent modified all 3 extractors: 18:31–18:32

The pilot 9/32 = 28% result reflects the **pre-P2b spec_agent** (one-shot, save_spec-only). The post-P2b spec_agent will produce different (likely better) specs.

**Implication:** Not invalidating, but means the pilot result must be reported as a *baseline* — paired with a post-P2b re-run as an *ablation*.

**Severity:** Medium-high.

**Recovery:** Treat 9/32 as the baseline. Re-run after P2b helpers wiring + Fireworks2. Report both numbers explicitly as separate columns: `(baseline, post-P2b)`.

## MEDIUM flags

### FLAG 6 — DABStep iter-cap accounting depends on threshold choice

3 of 10 DABStep tasks hit iter cap of 40:
- 1738: 39 successful run_python + 1 error → genuinely couldn't commit
- 2564: same shape
- 2761: same shape

All counted as failures. But pass rate is sensitive to iter cap. If we'd set max_iter=60, some might have committed (per the EC5 win pattern on 1712).

**Severity:** Medium. Not wrong but a confounded hyperparameter.

**Recovery:** Report max_iter alongside pass rate. Consider ablation: same pilot at max_iter ∈ {20, 40, 60}.

### FLAG 7 — Cost / latency may differ between Fireworks keys

Just switched primary configs to fireworks2 (better latency per user). Pilot was on fireworks (key 1). Throughput characteristics may differ.

**Severity:** Low. Doesn't affect correctness.

**Recovery:** Document which key was used per pilot.

## CLEAN — verified non-issues

- ✓ No gold leakage in spec_agent prompts (verified on task 1234)
- ✓ Planner code stable across pilots (last mod 16:54, pilots at 17:22+)
- ✓ All 3 pilot configs identical at the model/iter/planner level
- ✓ DABStep HELPER_MANIFEST did NOT leak into LiveSQL/Krama specs
- ✓ No planner_session pollution from prior runs
- ✓ Pilot dirs created fresh before extraction
- ✓ No Python REPL errors caused by harness bugs in the pilot itself (the v3 false-bug was caught before pilot ran)

## Recommended corrections (priority order)

1. **Fix Krama framing**: always qualify as "archeology-only". Update docs 06, 11, 12 to use that phrasing. Documentation discipline; no code change.
2. **Fix LiveSQL `_meta` bug** (FLAG 4). 5-line fix in `extract_specs_livesql.py`.
3. **Switch to random-sampled pilots** (FLAG 3). Update split-prep scripts to use seeded random sampling. Re-run.
4. **Wire HELPER_MANIFEST for Krama** + re-run with P2b extractors + Fireworks2 to get the upgraded baseline (FLAG 5).
5. **Pull KramaBench obscured-input variant** + re-run for leakage check (FLAG 2). Could establish a memorization-stripped lower bound.
6. **Add iter cap to methodology section** of any paper (FLAG 6).
7. **Document Fireworks key usage** per pilot in `run_manifest.json` going forward (FLAG 7).

## What this audit doesn't cover

- Did the grader implementation actually match published benchmark scoring? Vendored DABStep scorer assumed correct (it's their official one). LiveSQL/Krama graders are our own implementations — would need separate verification.
- Did pilot tasks have annotation noise? KramaBench paper notes some ambiguity in their gold answers; cannot audit per-task.
- Does Kimi-K2.6 have memorization advantage on DABStep fee-rule patterns (which are Adyen-flavored)? Not tested.
- Are there hidden state-carry bugs between EC5 / Tier C / cascade that the smoke tests didn't surface?

## Methodology stance for the paper

If we want to publish numbers from this pilot:

- **Krama archeology 42%**: can publish as "matches smolagents-DR-on-archeology with weaker base models," with these caveats explicit:
  - Archeology-only (not Krama-wide)
  - Full archeology (not a sample)
  - Memorization not yet stripped — need obscured-input ablation
- **DABStep 30%**: cannot publish without random-sample re-run. "First 10 hard tasks" is not a defensible methodology.
- **LiveSQL 10%**: dropping LiveSQL per Decision 1 (`docs/findings/15_decisions_2026-06-06.md`). No publication implication.

The **strongest defensible claim** right now is:
> *"On KramaBench's archeology domain (12 tasks, full subset), SCRIBE with Kimi-K2.6 + GPT-5 achieves 5/12 = 41.67% — matching the smolagents-DR Claude-3.7 baseline (44.44%) per KramaBench paper Table 5, at substantially lower per-task cost. Memorization not yet stripped; obscured-input ablation pending."*

## Related docs

- `06_krama_failure_analysis.md` — needs "archeology-only" qualification
- `11_research_insights.md` — Insight 4 needs same qualification + memorization caveat
- `12_3bench_pilot_synthesis.md` — same
- `15_decisions_2026-06-06.md` — LiveSQL deferred, helpers planned
