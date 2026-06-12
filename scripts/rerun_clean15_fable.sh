#!/usr/bin/env bash
# Clean Fable-5 re-run of the 15 contaminated DAB tasks x5 under the HARDENED
# sandbox with scrubbed, gold-free Fable specs. Apples-to-apples vs the Opus run.
# Output: results/dab_clean_rerun_fable/run{0..4}/summary.json
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"

SPLIT="data/splits/dab_rerun_clean15.jsonl"
SPECS="results/dab_clean_specs_fable"
CONFIG="configs/dab_scribe_fable.yaml"
OUTBASE="results/dab_clean_rerun_fable"

for run in 0 1 2 3 4; do
  OUT="$OUTBASE/run${run}"
  mkdir -p "$OUT"
  echo "===== FABLE RUN ${run} -> ${OUT} ====="
  npx tsx src/run.ts -c "$CONFIG" -d "$SPLIT" -o "$OUT" --specs "$SPECS" -w 3
  echo "===== FABLE RUN ${run} done ====="
done
echo "ALL 5 FABLE TRIALS COMPLETE"
