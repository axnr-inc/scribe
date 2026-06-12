#!/usr/bin/env bash
# Canonical DAB 5-trial runner with per-trial interpretation rotation.
#
# Usage:
#   bash scripts/run_dab_5trials.sh <split.jsonl> <specs_dir> <out_base> [config] [workers]
#
# Each trial passes --run-index $run, so specs that declare
# interpretation_confidence: "split" commit a DIFFERENT reading per trial
# (Pass@1 diversity); specs marked "committed" behave exactly as before.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
export PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH"

SPLIT="${1:?split.jsonl}"
SPECS="${2:?specs dir}"
OUTBASE="${3:?out base dir}"
CONFIG="${4:-configs/dab_scribe.yaml}"
WORKERS="${5:-4}"

for run in 0 1 2 3 4; do
  OUT="$OUTBASE/run${run}"; mkdir -p "$OUT"
  echo "===== TRIAL ${run} -> ${OUT} ====="
  npx tsx src/run.ts -c "$CONFIG" -d "$SPLIT" -o "$OUT" --specs "$SPECS" -w "$WORKERS" --run-index "$run"
done
echo "ALL 5 TRIALS COMPLETE"
