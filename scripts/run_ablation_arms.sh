#!/usr/bin/env bash
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
SPLIT=data/splits/dab_all54.jsonl
SPECS=results/dab_final_specs

echo "===== ARM B: Kimi-K2.6 executor + Opus-4.7 planner/reviewer (54x1) ====="
npx tsx src/run.ts -c configs/dab_scribe_kimi_opus.yaml -d "$SPLIT" \
  -o results/abl_kimi_opus --specs "$SPECS" -w 3 --run-index 0
echo "===== ARM B DONE ====="

echo "===== ARM A: Opus-4.7 all roles (54x1, baseline w/ per-model cost) ====="
npx tsx src/run.ts -c configs/dab_scribe.yaml -d "$SPLIT" \
  -o results/abl_opus_all --specs "$SPECS" -w 3 --run-index 0
echo "===== ARM A DONE ====="
echo "ALL ABLATION ARMS COMPLETE"
