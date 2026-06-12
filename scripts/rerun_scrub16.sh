#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
for run in 0 1 2 3 4; do
  OUT="results/dab_clean_rerun_scrub16/run${run}"; mkdir -p "$OUT"
  echo "===== SCRUB16 RUN ${run} ====="
  npx tsx src/run.ts -c configs/dab_scribe.yaml -d data/splits/dab_promptscrub16.jsonl -o "$OUT" --specs results/dab_clean_specs -w 4
done
echo "SCRUB16 COMPLETE"
