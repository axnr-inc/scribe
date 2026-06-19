#!/usr/bin/env bash
# 2-question smoke with Inception Mercury 2 executor + planner (reuses specs if present).
export SENTINEL_OUT="${SENTINEL_OUT:-results/sentinel_smoke2_mercury2}"
export SENTINEL_GROUP=smoke
export SENTINEL_LIMIT=2
export SENTINEL_CONFIG=configs/sentinel_scribe_mercury2.yaml
# Keep Sonnet for spec extraction (cheaper); override for Mercury specs:
# export SENTINEL_EXTRACTOR=openrouter:inception/mercury-2
exec bash "$(dirname "$0")/repro_sentinel.sh"
