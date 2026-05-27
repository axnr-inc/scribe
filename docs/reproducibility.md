# Reproducibility

Every headline number in the SCRIBE paper has a one-line reproduction recipe below. Smaller targets (≤5 tasks) fit comfortably on a laptop in <10 min; the full hard-378 run requires GPU-backed Kimi-K2.6 hosting (Fireworks/Baseten/OpenRouter) and costs ~$40 in API calls.

## Prerequisites

```bash
git clone <repo> && cd scribe
npm install && python3 -m pip install -r requirements.txt
node scripts/patch_pi_ai_env.cjs       # patches pi-ai client for fireworks/baseten
cp .env.example .env && $EDITOR .env   # OPENROUTER_API_KEY, FIREWORKS_API_KEY, BASETEN_API_KEY
python3 scripts/fetch_dabstep_data.py  # manual.md, fees.json, payments.csv, ...
```

## Smoke test (5 tasks, ~5 min, <$1)

```bash
bash scripts/repro.sh
```

Writes `results/repro_pilot/summary.json` and per-task session JSONL under `results/repro_pilot/<task_id>/sessions/`.

## Headline numbers

| # | Number | Recipe | Expected output |
|---|---|---|---|
| 1 | Easy-72 = 95.8% | `npx tsx src/run.ts --config configs/scribe_main.yaml --split data/splits/easy_all72.jsonl --out results/easy72` | 69/72 PASS |
| 2 | Hard-378 = 52.9% (before quick-wins) | `npx tsx src/run.ts --config configs/scribe_main.yaml --split data/splits/hard_all378.jsonl --out results/hard378` | 192–200/378 PASS depending on provider-side variance |
| 3 | Hard-378 final (after F8 rescore) | `python3 scripts/quick_wins_f8_rescore.py results/v23_gpt5_hard_all378_FINAL.csv > results/hard_all378_FINAL_qw_f8.csv` | 200/378 PASS |
| 4 | 44-regression recovery (Path B) | `npx tsx src/run.ts --config configs/scribe_main.yaml --tasks <44 ids from supplement> --escalate --out results/reg44` | ~9/44 rescued |
| 5 | Task-17 cross-planner | `for p in gpt-5 gpt-5.5 claude-opus-4; do npx tsx src/run.ts --config configs/scribe_main.yaml --planner $p --tasks 17 --out results/t17_$p; done` | gpt-5/gpt-5.5 PASS with 1 retry; opus PASS with 2 retries |
| 6 | GPT-5 solo (falsifier) | `npx tsx src/run.ts --config configs/gpt5_solo_baseline.yaml --tasks 17,36,1275,1453,1739 --out results/gpt5_solo5` | 2–3/5 PASS (worse than SCRIBE at higher cost) |

## Ablations

| Ablation | Recipe | Reports in supplement |
|---|---|---|
| Variant-B (planner injects domain knowledge directly into prompts) | `configs/scribe_main.yaml` → swap to `experiments/configs/kimi_grafted_iterative_baseten_dk.yaml` | Section 5.3 — fails relative to spec-only baseline |
| Meta-rules pilot | `experiments/configs/kimi_grafted_iterative.yaml` with `--meta-rules` flag, 5-task pilot | Section 5.4 |
| Spec-only (no escalation) | `configs/kimi_grafted_iterative.yaml` with `ask_spec_agent` tool removed | Section 5.5 |
| Opus×10 sampling on task 17 | `for i in $(seq 1 10); do npx tsx src/run.ts --planner opus --tasks 17 --seed $i --out results/opus10_$i; done` | Section 5.6 (variance) |

## Provider-routing notes

Kimi-K2.6 is served via three backends (Fireworks, Baseten, OpenRouter); routing was chosen per-task based on which provider was healthy at the time. The `results_union.csv` files preserve the `shards` column documenting which provider produced each result. Re-runs may land on different shards and may produce slightly different traces; pass-rates are stable to ±2 tasks across reruns in our experience.

## Grading

```bash
python3 scripts/grade.py --pred results/<run>/results.csv --gold data/verified_answers.json
```

Uses the vendored DABStep official scorer (`vendor/dabstep_scorer/scorer.py`) with the documented `min(dec_places)` rounding and `rel_tol=1e-4` tolerance. (Note: predictions like `8.894813` against gold `8.91` do NOT pass — see `docs/notes/` for tolerance details.)
