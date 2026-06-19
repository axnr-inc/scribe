#!/usr/bin/env bash
# Quick 2-question Sentinel smoke (~$1–2, ~10–15 min).
export SENTINEL_OUT=results/sentinel_smoke2
export SENTINEL_GROUP=smoke
export SENTINEL_LIMIT=2
exec bash "$(dirname "$0")/repro_sentinel.sh"
