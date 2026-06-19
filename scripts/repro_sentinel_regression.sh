#!/usr/bin/env bash
# Full Sentinel regression set (44 questions). Long run — hours, $$ cost.
export SENTINEL_OUT=results/sentinel_regression
export SENTINEL_GROUP=regression
unset SENTINEL_LIMIT
unset SENTINEL_TASK_IDS
exec bash "$(dirname "$0")/repro_sentinel.sh"
