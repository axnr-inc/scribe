#!/usr/bin/env bash
# Re-run executor + planner + grade only (reuse existing specs; skip re-extraction).
# Apply pi-ai patch first if you haven't since npm install:
#   node scripts/patch_pi_ai_env.cjs
#
# Usage:
#   bash scripts/repro_sentinel_executor_only.sh
#   SENTINEL_OUT=results/sentinel_smoke2_opus bash scripts/repro_sentinel_executor_only.sh

export SENTINEL_SKIP_SPECS=1
export SENTINEL_OUT="${SENTINEL_OUT:-results/sentinel_smoke2_opus}"
export SENTINEL_GROUP=smoke
export SENTINEL_LIMIT=2
export SENTINEL_CONFIG="${SENTINEL_CONFIG:-configs/sentinel_scribe_opus.yaml}"
exec bash "$(dirname "$0")/repro_sentinel.sh"
