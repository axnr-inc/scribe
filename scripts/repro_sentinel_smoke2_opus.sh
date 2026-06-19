#!/usr/bin/env bash
# 2-question smoke with Opus 4.7 executor (reuses Kimi-run specs if present).
export SENTINEL_OUT="${SENTINEL_OUT:-results/sentinel_smoke2_opus}"
export SENTINEL_GROUP=smoke
export SENTINEL_LIMIT=2
export SENTINEL_CONFIG=configs/sentinel_scribe_opus.yaml
# Keep Sonnet for spec extraction (cheaper); override for Opus specs:
# export SENTINEL_EXTRACTOR=anthropic:claude-opus-4-7
exec bash "$(dirname "$0")/repro_sentinel.sh"
