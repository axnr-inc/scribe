#!/usr/bin/env bash
# Re-run the 15 contaminated DAB tasks x5 under the HARDENED sandbox with clean,
# gold-free specs. Output: results/dab_clean_rerun/run{0..4}/summary.json
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"

SPLIT="data/splits/dab_rerun_clean15.jsonl"
SPECS="results/dab_clean_specs"
CONFIG="configs/dab_scribe.yaml"
OUTBASE="results/dab_clean_rerun"

for run in 0 1 2 3 4; do
  OUT="$OUTBASE/run${run}"
  mkdir -p "$OUT"
  echo "===== RUN ${run} -> ${OUT} ====="
  npx tsx src/run.ts -c "$CONFIG" -d "$SPLIT" -o "$OUT" --specs "$SPECS" -w 4
  echo "===== RUN ${run} done ====="
done
echo "ALL 5 TRIALS COMPLETE"
