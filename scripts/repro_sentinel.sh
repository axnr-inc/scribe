#!/usr/bin/env bash
# Sentinel eval — configurable repro driver.
#
# Env overrides:
#   SENTINEL_OUT=results/sentinel_smoke2     output directory
#   SENTINEL_GROUP=smoke|regression|all      question bucket (default: smoke)
#   SENTINEL_LIMIT=2                         first N tasks after group filter
#   SENTINEL_TASK_IDS=polar_6,cybermarket_7  explicit question ids
#   SENTINEL_EXTRACTOR=anthropic:claude-sonnet-4-6
#   SENTINEL_CONFIG=configs/sentinel_scribe_anthropic.yaml
#   SENTINEL_CONFIG=configs/sentinel_scribe_opus.yaml           # Opus executor + planner (Anthropic)
#   SENTINEL_CONFIG=configs/sentinel_scribe_mercury2.yaml       # Mercury 2 executor + planner (OpenRouter)
#   SENTINEL_CONTEXT_MODE=rag|full            spec-context loading mode (default: rag)
#   SENTINEL_RAG_TOP_K=12                     chunks retrieved per task (rag mode)
#   SENTINEL_RAG_MAX_CONTEXT_CHARS=45000      retrieved char budget (rag mode)
#   SENTINEL_RUN_SQL_MAX_ROWS=50000           max rows fetched by run_sql in executor
#   RUN_SQL_TOOL_OUTPUT_CAP=0                 0 = no tool-output row truncation
#
# Examples:
#   bash scripts/repro_sentinel.sh                                    # 6 smoke tasks
#   SENTINEL_LIMIT=2 SENTINEL_OUT=results/sentinel_smoke2 bash ...  # 2 tasks
#   SENTINEL_GROUP=regression SENTINEL_OUT=results/sentinel_reg bash ...
set -uo pipefail
cd "$(dirname "$0")/.."

SENTINEL_ROOT="${SENTINEL_SDK_PATH:-../sentinel-eval-sdk}"
SENTINEL_ROOT="$(cd "$SENTINEL_ROOT" 2>/dev/null && pwd || true)"
if [ -z "$SENTINEL_ROOT" ] || [ ! -d "$SENTINEL_ROOT" ]; then
  echo "ERROR: sentinel-eval-sdk not found. Set SENTINEL_SDK_PATH in .env"
  exit 1
fi

export SENTINEL_SDK_PATH="$SENTINEL_ROOT"

SENTINEL_EXTRACTOR="${SENTINEL_EXTRACTOR:-anthropic:claude-sonnet-4-6}"
SENTINEL_CONFIG="${SENTINEL_CONFIG:-configs/sentinel_scribe_anthropic.yaml}"
SENTINEL_GROUP="${SENTINEL_GROUP:-smoke}"
SENTINEL_OUT="${SENTINEL_OUT:-results/sentinel_smoke}"
SENTINEL_LIMIT="${SENTINEL_LIMIT:-}"
SENTINEL_TASK_IDS="${SENTINEL_TASK_IDS:-}"
SENTINEL_CONTEXT_MODE="${SENTINEL_CONTEXT_MODE:-rag}"
SENTINEL_RAG_TOP_K="${SENTINEL_RAG_TOP_K:-12}"
SENTINEL_RAG_CHUNK_CHARS="${SENTINEL_RAG_CHUNK_CHARS:-1800}"
SENTINEL_RAG_OVERLAP_CHARS="${SENTINEL_RAG_OVERLAP_CHARS:-250}"
SENTINEL_RAG_MAX_CONTEXT_CHARS="${SENTINEL_RAG_MAX_CONTEXT_CHARS:-45000}"
SENTINEL_RAG_INCLUDE_FULL_FILE_UNDER="${SENTINEL_RAG_INCLUDE_FULL_FILE_UNDER:-7000}"
SENTINEL_RUN_SQL_MAX_ROWS="${SENTINEL_RUN_SQL_MAX_ROWS:-50000}"
RUN_SQL_TOOL_OUTPUT_CAP="${RUN_SQL_TOOL_OUTPUT_CAP:-0}"
export SENTINEL_RUN_SQL_MAX_ROWS RUN_SQL_TOOL_OUTPUT_CAP

command -v node >/dev/null 2>&1 || { echo "ERROR: node 20+ required"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3 required"; exit 1; }
[ -f .env ] || { echo "ERROR: copy .env.example to .env"; exit 1; }

set -a
source .env
set +a

if grep -qE 'provider:\s*fireworks2?' "$SENTINEL_CONFIG"; then
  : "${FIREWORKS_API_KEY2:?FIREWORKS_API_KEY2 required for $SENTINEL_CONFIG}"
fi
if grep -qE 'provider:\s*anthropic' "$SENTINEL_CONFIG" || [[ "$SENTINEL_EXTRACTOR" == anthropic:* ]]; then
  : "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY required for $SENTINEL_CONFIG / $SENTINEL_EXTRACTOR}"
fi
if grep -qE 'provider:\s*openrouter' "$SENTINEL_CONFIG"; then
  : "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY required for $SENTINEL_CONFIG}"
fi
if [ "${LANGFUSE_ENABLED:-}" = "1" ]; then
  : "${LANGFUSE_PUBLIC_KEY:?LANGFUSE_PUBLIC_KEY required when LANGFUSE_ENABLED=1}"
  : "${LANGFUSE_SECRET_KEY:?LANGFUSE_SECRET_KEY required when LANGFUSE_ENABLED=1}"
  python3 -c "import langfuse" 2>/dev/null || {
    echo "ERROR: LANGFUSE_ENABLED=1 but langfuse Python package missing. Run: pip install 'langfuse>=3.0.0'"
    exit 1
  }
fi

case "$SENTINEL_EXTRACTOR" in
  openrouter:*)
    : "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY required for SENTINEL_EXTRACTOR=$SENTINEL_EXTRACTOR}"
    ;;
  fireworks:*)
    : "${FIREWORKS_API_KEY:?FIREWORKS_API_KEY required for SENTINEL_EXTRACTOR=$SENTINEL_EXTRACTOR}"
    ;;
  fireworks2:*)
    : "${FIREWORKS_API_KEY2:?FIREWORKS_API_KEY2 required for SENTINEL_EXTRACTOR=$SENTINEL_EXTRACTOR}"
    ;;
esac

if [ ! -d "$SENTINEL_ROOT/context_downloads/eval_alien" ]; then
  echo "Context missing; run: cd $SENTINEL_ROOT && python download_context.py"
  exit 1
fi

if [ -f "$SENTINEL_ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$SENTINEL_ROOT/.env"
  set +a
fi

echo "=== Sentinel repro: group=$SENTINEL_GROUP out=$SENTINEL_OUT limit=${SENTINEL_LIMIT:-all} ==="

echo
echo "=== 0/4: connectivity check ==="
if ! python3 scripts/check_sentinel_connectivity.py; then
  echo "Fix network access first (VPN / staging .env)."
  exit 1
fi

OUT="$SENTINEL_OUT"
mkdir -p "$OUT/specs"

ADAPTER_ARGS=(--group "$SENTINEL_GROUP" --sentinel-root "$SENTINEL_ROOT" --out "$OUT/tasks.jsonl")
if [ -n "$SENTINEL_LIMIT" ]; then
  ADAPTER_ARGS+=(--limit "$SENTINEL_LIMIT")
fi
if [ -n "$SENTINEL_TASK_IDS" ]; then
  ADAPTER_ARGS+=(--task-ids "$SENTINEL_TASK_IDS")
fi

echo
echo "=== 1/4: convert Sentinel questions → tasks.jsonl ==="
python3 scripts/sentinel_adapter.py "${ADAPTER_ARGS[@]}"

echo
echo "=== 2/4: extract specs ($SENTINEL_EXTRACTOR) ==="
if [ "${SENTINEL_SKIP_SPECS:-}" = "1" ]; then
  echo "  Skipping spec extraction (SENTINEL_SKIP_SPECS=1); reusing $OUT/specs"
else
python3 scripts/extract_specs_sentinel.py \
  --tasks "$OUT/tasks.jsonl" \
  --sentinel-root "$SENTINEL_ROOT" \
  --extractor "$SENTINEL_EXTRACTOR" \
  --out "$OUT/specs" \
  --run-out "$OUT" \
  --context-mode "$SENTINEL_CONTEXT_MODE" \
  --rag-top-k "$SENTINEL_RAG_TOP_K" \
  --rag-chunk-chars "$SENTINEL_RAG_CHUNK_CHARS" \
  --rag-overlap-chars "$SENTINEL_RAG_OVERLAP_CHARS" \
  --rag-max-context-chars "$SENTINEL_RAG_MAX_CONTEXT_CHARS" \
  --rag-include-full-file-under "$SENTINEL_RAG_INCLUDE_FULL_FILE_UNDER" \
  --workers 2
fi

if ! python3 -c "
import json, sys
from pathlib import Path
bad = []
for p in Path('$OUT/specs').glob('*.json'):
    if p.name.endswith('.original.json') or '.spec_session' in p.name: continue
    try:
        o = json.load(open(p))
        if isinstance(o, dict) and '_error' in o:
            bad.append(p.stem)
    except Exception: pass
if bad:
    print('Spec extraction failed for:', ', '.join(bad), file=sys.stderr)
    sys.exit(1)
"; then
  echo "ERROR: fix spec extraction (API keys / credits) before running executor."
  exit 1
fi

echo
echo "=== 3/4: run SCRIBE executor ($SENTINEL_CONFIG) ==="
npx tsx src/run.ts \
  -d "$OUT/tasks.jsonl" \
  -c "$SENTINEL_CONFIG" \
  -o "$OUT" \
  --specs "$OUT/specs" \
  -n "sentinel_${SENTINEL_GROUP}"

echo
echo "=== 4/4: grade against Sentinel gold CSVs ==="
python3 scripts/grade_sentinel.py \
  --out "$OUT" \
  --tasks "$OUT/tasks.jsonl" \
  --sentinel-root "$SENTINEL_ROOT"

if [ "${LANGFUSE_ENABLED:-}" = "1" ]; then
  echo
  echo "=== 4b/4: refresh Langfuse trace metrics ==="
  python3 scripts/sentinel_refresh_langfuse_traces.py --out "$OUT"
fi

PASS=$(python3 -c "import json; print(sum(1 for r in json.load(open('$OUT/results.json')) if r.get('status')=='pass'))" 2>/dev/null || echo 0)
TOTAL=$(python3 -c "import json; print(len(json.load(open('$OUT/results.json'))))" 2>/dev/null || echo 0)
echo
echo "==============================="
echo "PASS=$PASS/$TOTAL  (group=$SENTINEL_GROUP, out=$OUT)"
echo "==============================="

echo
python3 scripts/sentinel_usage_report.py --out "$OUT"
