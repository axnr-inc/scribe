#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
for run in 0 1 2 3 4; do
  OUT="results/dab_clean_rerun_2fix/run${run}"
  mkdir -p "$OUT"
  echo "===== 2FIX RUN ${run} ====="
  npx tsx src/run.ts -c configs/dab_scribe.yaml -d data/splits/dab_rerun_2fix.jsonl -o "$OUT" --specs results/dab_clean_specs -w 2
done
echo "2FIX COMPLETE"
