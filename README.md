# SCRIBE

**S**pec-**C**onditioned **R**eAct with **I**nline **B**ackreview **E**scalation — a three-role agent architecture for data-analysis benchmarks.

## What

SCRIBE decomposes the work of a data-analysis agent into three roles, each played by a model chosen for that role:

1. **Spec Agent** (frontier model, e.g. GPT-5) — reads the task + the source documents (manual, schemas, rule catalog) and emits a structured `computation_plan`. The plan is *frozen* — the executor cannot rewrite it.
2. **ReAct Executor** (smaller open-weights model, e.g. Kimi-K2.6) — reads the spec and runs a standard ReAct loop with a Python REPL. Can call back to the spec agent via an `ask_spec_agent` tool when it detects ambiguity.
3. **Review Agent** (same frontier model as Spec) — when the executor escalates, the review path re-reads source documents and either confirms the executor's interpretation or emits a revised spec.

The asymmetry — frontier model only on the *thinking* roles, smaller model on the heavy *acting* role — is the key cost lever.

## Headline results

SCRIBE has been evaluated on three data-analysis benchmarks:

### DataAgentBench — 71.99% stratified Pass@1 (leaderboard submission)

54 queries × 5 trials across 12 datasets and 4 DBMS (SQLite, DuckDB, PostgreSQL, MongoDB),
scored with the official per-query validators and DAB's stratified formula.
Submitted as [ucbepic/DataAgentBench PR #57](https://github.com/ucbepic/DataAgentBench/pull/57);
the current leaderboard #1 (Spacedock) is 65.55%.

| Dataset | Pass@1 | Dataset | Pass@1 |
|---|---|---|---|
| bookreview | 1.00 | pancancer_atlas | 0.67 |
| googlelocal | 1.00 | deps_dev_v1 | 0.50 |
| stockindex | 1.00 | github_repos | 0.50 |
| stockmarket | 1.00 | agnews | 0.25 |
| yelp | 0.94 | patents | 0.00 |
| music_brainz_20k | 0.93 | | |
| crmarenapro | 0.85 | **Stratified** | **0.7199** |

This is the *corrected* number after a leakage review (see "Integrity pipeline" below):
our first submission scored 83.87%, the maintainers identified prompt-leakage paths,
and we re-ran every affected query under a hardened sandbox with regenerated gold-free
specs — plus several additional issues our own audit surfaced that the reviewers had
not flagged. The honest number is lower and we report it as-is.

### KramaBench — 55.8% (lenient) / 52.9% (strict)

104 tasks across all 6 domains, official scorer (vendored with 4 bugs patched, see
`vendor/kramabench_eval/`). Statistically tied with the best published agentic system
(smolagents-DR Claude-3.7 at 55.83%) while using smaller open-weights executor models.

| Domain | Tasks | Strict (≥0.999) | Lenient (≥0.5 partial-credit) |
|---|---|---|---|
| biomedical | 9 | 7 (77.8%) | 7 (77.8%) |
| environment | 20 | 14 (70.0%) | 15 (75.0%) |
| wildfire | 21 | 11 (52.4%) | 13 (61.9%) |
| legal | 30 | 15 (50.0%) | 15 (50.0%) |
| archeology | 12 | 4 (33.3%) | 4 (33.3%) |
| astronomy | 12 | 4 (33.3%) | 4 (33.3%) |
| **OVERALL** | **104** | **55/104 = 52.9%** | **58/104 = 55.8%** |

Full breakdown and failure analysis in `docs/findings/18_krama104_results.md`.

### DABStep — 59.8% combined (dev set)

| Split | SCRIBE | DS-STAR (Gemini-2.5-Pro) | DS-STAR (GPT-5) |
|---|---|---|---|
| Easy-72 | **95.8% (69/72)** | 87.5% | 88.9% |
| Hard-378 | **52.9% (200/378)** | 45.24% | 43.12% |
| Combined-450 | **59.8% (269/450)** | ~52.0% | ~50.4% |

SCRIBE figures are *best-of-N + recovery* over the dev set with consensus gold. DS-STAR figures are from the public DABStep leaderboard (hidden test set). Direct comparison requires a leaderboard submission — listed in our Limitations.

## Integrity pipeline (DataAgentBench)

Leaderboard submissions ship with a verifiable anti-leakage record:

- **Hardened executor sandbox** (enforced in the REPL preamble, `src/run.ts`):
  import block for `datasets`/`huggingface_hub`/`kaggle`/etc., network egress block
  (only localhost project DBs reachable), and a local-cache read block (no
  `~/.cache/huggingface` or external `.arrow`/`.parquet` reads).
- **Spec hygiene** (`scripts/extract_specs_dab.py`, RULE 0): specs may never contain
  answer values, record IDs, gold cardinality, or validator internals.
- **Self-audit** (`scripts/dab_self_audit.py`): replicates the maintainers' trace
  checks — HF/cache loads, answer-key access, external fetches, gold tokens in any
  prompt, JSON↔trace reconciliation, distinct-trace verification — and emits a
  taint ledger shipped with the submission (270/270 clean).
- **Honest re-runs, not patches**: every flagged query was re-executed end-to-end.
  Two instructive cases: github_repos/q2's spec used the eventual answer as a format
  example — removing it changed nothing (the executor re-derives the answer 5/5);
  github_repos/q1's spec pre-stated a computed value — removing it flipped the query
  to a 5/5 *fail*, so we kept the failing honest answers and reported the lower score.

## Model-stack experiments

- **Claude Opus 4.7** on all three roles is the submitted DAB configuration.
- **Claude Fable 5** (same pipeline, fresh specs) beats Opus on the hardest 15-query
  DAB subset (0.600 vs 0.493) but **refuses cancer-genomics tasks** (PanCancer Atlas
  BRCA/CDH1 queries return empty in both the spec and executor roles), projecting it
  ~3 points below Opus on the full benchmark — so Opus ships.
- **Open-stack variants** (GLM planner + Kimi executor; DeepSeek-V3.1) are evaluated
  on KramaBench/DABStep — see `docs/findings/` and the paper.

## Transparency

We aim for **end-to-end reproducibility** of every number in the paper and supplement.

- **Summary CSVs** for every experiment (hard-378, easy-72, easy-18, pilot-5, 44-regression rerun, task-17 cross-planner, quick-wins F8/F10/F12, GPT-5-solo falsifier, meta-rules pilot) are committed under `results/`. See `TRACES.md` for the full inventory.
- **Sample session traces** (≤176 KB each, plaintext JSONL) live in `results/samples/`:
  - `task17_cross_planner/` — six full traces showing how planner choice (GPT-5 / GPT-5.5 / Opus, with retries) flips the same task between PASS and FAIL.
  - `regressions44_rescued/` — three full traces including `task2489_escalation_rescue.jsonl`, our canonical demonstration of Path-B escalation rescuing a failed run.
  - `sample_1012.jsonl`, `sample_2366.jsonl`, `sample_fireworks.jsonl` — representative hard-378 executions.
  - `../repro_pilot/<task>/sessions/` — five full traces from the smoke-test (also re-generated by `scripts/repro.sh`).
- **Kimi-K2.6 solo failure analysis** (95 incorrect tasks, root-cause taxonomy, per-pattern markdowns) is committed under `docs/failure_analysis/`.
- **Reproduction recipes** for all six headline numbers and all major ablations are in `docs/reproducibility.md`. The smallest target (`bash scripts/repro.sh`) runs 5 tasks in ~5 min for <$1.
- **Full session corpus** (~1.8 GB, every task × every shard × every reroute) is too large to commit; we will release it as a Zenodo tarball with the camera-ready paper. See `TRACES.md` for the file list and request instructions.
- **Failed ablations** (Variant-B DK injection, meta-rules pilot) are documented in the supplement and have summary JSONs committed; the failed configs are preserved under `experiments/configs/` for inspection.

## Quickstart

```bash
git clone <repo> && cd scribe
npm install && python3 -m pip install -r requirements.txt
node scripts/patch_pi_ai_env.js          # patches pi-ai for fireworks/baseten
cp .env.example .env && $EDITOR .env     # fill OPENROUTER_API_KEY + FIREWORKS_API_KEY
python3 scripts/fetch_dabstep_data.py    # downloads manual.md, fees.json, payments.csv...
bash scripts/repro.sh                    # 5-task sanity check (~5 min, <$1)
```

## Layout

```
src/                       TypeScript harness (Agent loop, run_python tool, ask_spec_agent tool,
                           hardened sandbox preamble, multi-row gate)
src/prompts/               YAML prompt templates per executor variant
scripts/                   Python + bash: spec extractors (DABStep/Krama/DAB), scorers,
                           dab_self_audit, validate_submission, streaming orchestrators, repro
configs/                   YAML run configs (scribe_main = DABStep; dab_scribe = DataAgentBench;
                           kramabench_scribe* = KramaBench; *_fable / *_glm_kimi = model stacks)
vendor/dabstep_scorer/     DABStep official scorer.py (vendored, Apache 2.0)
vendor/kramabench_eval/    KramaBench official evaluator (vendored, 4 bugs patched)
data/                      Tasks + splits + helper manifests (dab_helper, patent_helper,
                           krama_helper); benchmark data lakes are fetched, not committed
submissions/               DataAgentBench leaderboard artifacts: 270-cell answers JSON,
                           trace bundle (270 sessions), self-audit taint ledger, PR description
results/                   Summary CSVs + sample session traces (see TRACES.md)
TRACES.md                  Inventory mapping every experiment to its artifact(s)
docs/                      Architecture, failure analysis, findings, reproducibility
paper/                     LaTeX sources + figures + IEEE template
experiments/               Archived non-canonical configs (for transparency, not for repro)
```

## Reproduction recipes

See `docs/reproducibility.md` for the full set of commands. Six headline numbers can each be reproduced from a single recipe; the smallest pilot finishes in ~5 min for under $1.

## Citation

```bibtex
@inproceedings{scribe2026,
  title = {SCRIBE: Spec-Conditioned ReAct for Data-Analysis Agents},
  author = {TBD},
  booktitle = {IEEE International Conference on Data Mining (ICDM)},
  year = {2026},
}
```

## License

Apache 2.0 — see `LICENSE`. Includes the DABStep official scorer (also Apache 2.0) under `vendor/dabstep_scorer/`. See `NOTICE` for the full attribution list.
