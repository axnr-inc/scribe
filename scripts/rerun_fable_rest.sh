#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"
SPLIT="data/splits/dab_fable_rest39.jsonl"
SPECS="results/dab_clean_specs_fable_rest"
CONFIG="configs/dab_scribe_fable.yaml"
OUTBASE="results/dab_clean_rerun_fable_rest"
for run in 0 1 2 3 4; do
  OUT="$OUTBASE/run${run}"; mkdir -p "$OUT"
  echo "===== FABLE-REST RUN ${run} ====="
  npx tsx src/run.ts -c "$CONFIG" -d "$SPLIT" -o "$OUT" --specs "$SPECS" -w 4
done
echo "ALL 5 FABLE-REST TRIALS COMPLETE"
