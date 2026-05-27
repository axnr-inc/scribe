#!/usr/bin/env bash
# SCRIBE — 5-task sanity pilot. ~5 min wall, <$1 cost.
# Expected: 4/5 PASS (±1). On clean clone runs end-to-end from a fresh .env.

set -uo pipefail
cd "$(dirname "$0")/.."

# --- preflight ---
command -v node >/dev/null 2>&1 || { echo "ERROR: node 20+ required"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "ERROR: python3.10+ required"; exit 1; }
[ -f .env ] || { echo "ERROR: copy .env.example to .env and fill keys"; exit 1; }

set -a
source .env
set +a

: "${OPENROUTER_API_KEY:?OPENROUTER_API_KEY not set in .env}"
: "${FIREWORKS_API_KEY:?FIREWORKS_API_KEY not set in .env}"

# --- ensure DABStep data is present ---
if [ ! -f data/context/payments.csv ]; then
  echo "DABStep context not found; running fetch_dabstep_data.py..."
  python3 scripts/fetch_dabstep_data.py
fi

# --- pilot task file ---
PILOT="data/splits/pilot5.jsonl"
if [ ! -f "$PILOT" ]; then
  mkdir -p data/splits
  python3 - <<'PY'
import json
keep = {"1712", "1574", "1444", "1508", "2528"}
rows = []
for src in ("data/target_tasks.jsonl", "data/splits/hard_all378.jsonl"):
    try:
        for l in open(src):
            r = json.loads(l)
            if str(r.get("task_id")) in keep: rows.append(r)
    except FileNotFoundError:
        pass
    if len(rows) >= 5: break
with open("data/splits/pilot5.jsonl", "w") as f:
    for r in rows: f.write(json.dumps(r) + "\n")
print(f"wrote pilot5: {len(rows)} tasks")
PY
fi

OUT=results/repro_pilot
mkdir -p "$OUT/specs"

echo
echo "=== 1/4: extracting specs (GPT-5 via OpenRouter) ==="
python3 scripts/extract_specs.py \
  --tasks "$PILOT" \
  --extractor openrouter:openai/gpt-5 \
  --out "$OUT/specs"

echo
echo "=== 2/4: building grafted dataset ==="
python3 scripts/build_dataset.py \
  --tasks "$PILOT" \
  --mode grafted \
  --specs "$OUT/specs" \
  --out "$OUT/tasks.jsonl"

echo
echo "=== 3/4: running executor (Kimi-K2.6 via Fireworks) ==="
npx tsx src/run.ts \
  -d "$OUT/tasks.jsonl" \
  -c configs/scribe_main.yaml \
  -o "$OUT" \
  --specs "$OUT/specs" \
  -n "repro_pilot"

echo
echo "=== 4/4: grading ==="
python3 scripts/grade.py \
  --out "$OUT" \
  --gold data/verified_answers.json

PASS=$(python3 -c "import csv; print(sum(1 for r in csv.DictReader(open('$OUT/results.csv')) if r.get('correct','').lower()=='true'))" 2>/dev/null || echo 0)
echo
echo "==============================="
echo "Pilot PASS=$PASS/5 (expected 4/5 +/-1)"
echo "==============================="
if [ "$PASS" -lt 3 ]; then
  echo "FAIL: <3 PASS. Check docs/reproducibility.md troubleshooting."
  exit 1
fi
echo "OK."
