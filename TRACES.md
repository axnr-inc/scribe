# Trace inventory

This file maps every experiment reported in the SCRIBE paper (and supplement) to the artifact(s) preserved in this repository. The goal is **full transparency**: every headline number and every ablation has either an in-repo summary or a documented path to the raw session logs.

## Convention

- **summary CSV / JSON**: small (<1 MB), committed in-repo under `results/`.
- **sample session JSONL**: representative full traces (≤100 KB each), committed under `results/samples/`.
- **full session corpus**: the entire ~1.8 GB session-log archive from the development run lives in the source project (`grafting_v2/results/`) and will be released as a separate Zenodo / GitHub release artifact (see "Full corpus" below). It is **not** in this repo for size reasons.

## Inventory

| Experiment | What it shows | In-repo summary | In-repo sample(s) | Full traces |
|---|---|---|---|---|
| GPT-5 + Kimi-K2.6, hard-378 (FINAL) | Headline hard-split result | `results/v23_gpt5_hard_all378_FINAL.csv` (378 rows), `results/hard_all378_FINAL_qw_f8.csv` (rescore) | `results/samples/sample_1012.jsonl`, `sample_2366.jsonl`, `sample_fireworks.jsonl` | full corpus, archive `v23_gpt5_hard_all378_FINAL/` (~17 MB) |
| GPT-5 + Kimi-K2.6, easy-72 | Headline easy-split result | `results/v23_gpt5_easy_all72.csv` (72 rows), `results/v23_gpt5_easy_all72_summary.json` | covered by hard-split samples | full corpus, archive `v23_gpt5_easy_all72/` (~45 MB) |
| GPT-5 + Kimi-K2.6, easy-18 (early subset) | Early dev iteration | `results/v23_gpt5_easy18.csv` (18 rows) | — | full corpus |
| Pilot-5 (canonical smoke test) | Reproducibility check, repro.sh target | `results/v23_pilot5.csv`, `results/repro_pilot/summary.json` | `results/repro_pilot/<task>/sessions/` (5 full traces, committed) | n/a |
| GPT-5-solo, 5-task falsifier | Solo-frontier ablation | `results/v23_gpt5_solo5_summary.json`, `results/v23_gpt5_solo5_manifest.json` | — | full corpus, archive `v23_gpt5_solo5/` (~272 KB) |
| Task-17 cross-planner study (gpt-5, gpt-5.5, opus, multiple seeds) | Planner-sensitivity ablation (T-D1..T-D3) | `results/samples/task17_cross_planner/results.csv` (aggregated) | `results/samples/task17_cross_planner/{gpt5,gpt5_retry,gpt55,opus,opus_retry,opus_retry2}.jsonl` (6 traces) | covered by samples |
| Opus×10 sampling on task 17 | Variance / best-of-N study | `results/v23_opus_x10_task17_extract.log` | — | full corpus, archive `v23_opus_x10_task17/` (~6.1 MB) |
| 44-regression recovery (Path B) | Escalation rescue demo | `results/hard_regressions44_rerun_union.csv` (45 rows) | `results/samples/regressions44_rescued/task2489_escalation_rescue.jsonl` (esc_total=1, rescued), `task1507_rescued.jsonl`, `task1676_rescued.jsonl` | full corpus, archive `v23_hard_regressions44_rerun/` (~30 MB) |
| Quick-wins F8 (rescore) | Tooling-correction sweep | `results/hard_all378_FINAL_qw_f8.csv`, script: `scripts/quick_wins_f8_rescore.py` | — | n/a (rescore is deterministic given full CSV) |
| Quick-wins F10 (rerun) | Tooling-correction sweep | `results/v23_hard_quickwin_f10_summary.json` | — | full corpus, archive `v23_hard_quickwin_f10/` (~608 KB) |
| Quick-wins F12 | Tooling-correction sweep | `results/v23_hard_quickwin_f12_summary.json` | — | full corpus |
| Variant-B (DK injection) | Failed ablation, reported in supplement | (Variant-B reproduction recipe in `docs/reproducibility.md`; raw corpus 276 MB lives in full-corpus archive only) | — | full corpus, archive `v23_variantb_184/` (~276 MB) |
| Meta-rules pilot (5-task) | Spec-format ablation | `results/v23_metarules_pilot5_summary.json` | — | full corpus, archive `v23_metarules_pilot5/` (~3.5 MB) |
| Kimi-K2.6 solo failure analyses (95 incorrect tasks) | Failure taxonomy in supplement | `docs/failure_analysis/incorrect_summary.csv`, `incorrect_categorized.csv`, `verified_failures*.json`, plus per-pattern markdowns (`deep_root_cause_per_pattern.md`, `root_cause_and_planner_fix.md`, `verified_per_task_diagnosis.md`, etc.) | covered by markdowns | full traces archive: `harness/analysis/kimi-k2.6/incorrect_traces/` and `tasks.zip` (~23 MB) |

## Full corpus

The complete development corpus (1.8 GB) includes every session log for every task across every shard. It will be released as a single tarball alongside the paper:

```
scribe-full-corpus.tar.gz  (planned ~600 MB compressed)
  results/v23_gpt5_hard_all378_FINAL/    # 378 task dirs, each with sessions/normal_agent.jsonl
  results/v23_gpt5_easy_all72/
  results/v23_hard_regressions44_rerun/  # baseten/, fireworks/, fireworks_2/, openrouter/, quickwin_*/ shards
  results/v23_variantb_184/              # baseten/, fireworks/, fireworks2/, openrouter_kimi/, specs/
  results/v23_opus_x10_task17/           # 10 sampling runs on task 17
  results/v23_task17_*/                  # 6 cross-planner runs on task 17
  results/v23_gpt5_solo5/, v23_metarules_pilot5/, v23_hard_quickwin_f{10,12}/
  results/v23_gpt5_easy18/               # early dev subset
  analysis/kimi-k2.6/                    # 95 Kimi-solo failure traces + analysis markdowns
```

Release target: Zenodo DOI, attached as supplementary material to the camera-ready submission. Until then the corpus is available on request from the authors.

## What's omitted and why

- **API request/response bodies** for the frontier-model calls (GPT-5, Opus). The session JSONL captures the executor side fully; the spec-agent side is recorded as a single `ask_spec_agent` tool call with the planner's textual reply. We do not log the raw OpenAI/Anthropic HTTP traffic — this matches DABStep convention and avoids leaking provider-side metadata that may be subject to ToS.
- **`.env` files** and credentials are excluded by `.gitignore`.
- **Provider routing decisions** (which shard a given task landed on across baseten/fireworks/openrouter shards) are preserved in the `shards` column of `results_union.csv` files.

## Reproduction

Each experiment in the table above has a one-line recipe in `docs/reproducibility.md`. The canonical smoke-test (5 tasks, ~5 min, <$1) is `bash scripts/repro.sh` and writes to `results/repro_pilot/`.
