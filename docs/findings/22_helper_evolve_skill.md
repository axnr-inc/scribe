# 22 — helper-evolve: automated helper-mining loop

## What this is

`scripts/helper_evolve.py` + `.claude/skills/helper-evolve/SKILL.md`
codify the manual workflow we ran across this session: take a scored
KramaBench run, classify failures, propose paradigm-level helpers,
gate-check them, wire them into the three load-bearing files, and
(optionally) re-extract+re-run+score the delta.

It is the productized form of the workflow described in
`14a_paradigm_fit_and_helper_strategy.md` (the inclusion bar) and
`21_helper_manifest_expansion.md` (the proposal template).

## Where it sits

```
results/<run>/final_results.json      ← step 1 (existing run script)
results/<run>/official_scores/        ← step 2 (existing scorer)
            ↓
scripts/helper_evolve.py              ← steps 3-9 (this skill)
            ↓
data/context/krama_helper.py          (edited)
src/run.ts                            (edited, preamble import block)
scripts/extract_specs_krama.py        (edited, spec_agent menu)
results/<run>/specs_v2/               (re-extracted specs)
results/<run>/_rerun/                 (executor re-run)
results/<run>/_delta_report.json      (net Δ pass-mass + invocation audit)
```

## How to use

Dry-run first (no source edits, no rerun, ~$1-3 in API calls):

```bash
python3 scripts/helper_evolve.py \
  --run-dir results/krama_opus_104_v3 \
  --tasks   data/splits/krama_all104.jsonl \
  --config  configs/kramabench_scribe_opus.yaml \
  --skip-wiring
```

Inspect `<run-dir>/_proposals.json`, `_rejections.json`, and
`_approved_helpers.json`. If the approved set looks right, drop
`--skip-wiring` to apply the edits:

```bash
python3 scripts/helper_evolve.py \
  --run-dir results/krama_opus_104_v3 \
  --tasks   data/splits/krama_all104.jsonl \
  --config  configs/kramabench_scribe_opus.yaml
```

Then `git diff` the three target files. If they look right, run the
full verification loop:

```bash
python3 scripts/helper_evolve.py \
  --run-dir results/krama_opus_104_v3 \
  --tasks   data/splits/krama_all104.jsonl \
  --config  configs/kramabench_scribe_opus.yaml \
  --execute --workers 4
```

## The gates (auto-enforced, no bypass)

Each `ProposedHelper` must clear:

1. **Name uniqueness** — must not shadow an existing helper. (Catches
   the proposer trying to "improve" an existing one — that's a manual
   patch, not a new helper.)
2. **`recovers_documented_failure`** — `recovers_task_ids` is a non-empty
   subset of the failing tasks the orchestrator just indexed.
3. **`paradigm_level`** — recovers >=2 real failing tasks OR self-attests
   paradigm-level (with a name that doesn't look like a task-solver).
   The self-attestation is downstream-checkable by reviewing
   `_proposals.json`.
4. **`pure_python`** — the implementation must not import `requests`,
   `httpx`, `openai`, `anthropic`, `langchain`, `aiohttp`, `socket`,
   `paramiko`, or `urllib`. (We grep the implementation text.)
5. **`trigger_phrase_in_docstring`** — the docstring contains "use when",
   "use for", or "use whenever" so the spec_agent's grep-style menu
   walk finds it.

Failures are written to `_rejections.json` with reasons.

## What the orchestrator is NOT

- It does not generate **unit tests** for proposed helpers. The test
  is the rerun-delta in step 9 — if the helper has zero invocations
  across `specs_v2/` or the per-task delta is zero, the helper is dead
  weight and you should revert the wiring.
- It does not **patch** existing helpers. If the right fix is a better
  parser inside `canonicalize_msa_name` rather than a new helper, the
  proposer is instructed to note this in `rejected_drafts` and leave
  the wiring untouched.
- It does not **rerun the full split** — only the failed-task subset.
  If a new helper accidentally breaks a previously-passing task, you
  won't see it in this delta. (Mitigation: occasionally re-run the
  full split out-of-band; helpers shouldn't regress passes because
  they're additive in the preamble, but the spec_agent's prompt also
  changes and could in principle nudge a passing spec to pass less
  cleanly.)
- It does not **revert on negative delta**. If `_delta_report.json`
  shows `net_delta` < 0, you must `git checkout data/context/krama_helper.py
  src/run.ts scripts/extract_specs_krama.py` to roll back.

## Gotchas

- **Anchor drift in `src/run.ts`.** The wire-step inserts new
  `lines.push(...)` calls between two anchor lines (open: the last
  existing `lines.push(\`        <helper>,\`)`; close: the next
  `lines.push(\`    )\`)`). If that block is restructured, the
  orchestrator raises a clear error pointing at `RUN_TS_OPEN_ANCHOR`
  in `helper_evolve.py`.
- **Sentinel drift in `extract_specs_krama.py`.** The wire-step splices
  spec_agent menu blocks immediately before the sentinel line "When a
  helper applies, include in `computation_plan`". If that sentence is
  paraphrased, splice fails with a clear error.
- **Helper sections in `krama_helper.py`** are appended verbatim with a
  banner comment. The orchestrator does not try to alphabetize or
  group by domain. Refactoring is manual.
- **The classifier+proposer use Claude Opus by default** because the
  manual workflow that this automates used Opus 4.7 inline. Override
  with `--model claude-sonnet-4-7` for cheaper iteration.

## Cost notes

- Steps 3-5 cost ~$1-3 per invocation (Opus, ~50 failed tasks,
  classifier+proposer each ~10K tokens in/out).
- Step 7 (re-extract specs) cost depends on the number of failed
  tasks × per-task spec cost (~$0.05-0.10 with Opus). For a 50-task
  rerun that's ~$3.
- Step 8 (re-run executor) is the dominant cost — same as the original
  executor run on the failed subset. For 50 Krama tasks with Opus 4.7,
  budget ~$5-8.

Total per evolution cycle: ~$10-15. Worth it if you expect to recover
>3 failures.

## Testing the orchestrator

`python3 scripts/helper_evolve.py --help` runs cleanly. The internal
checks done during development:

- Failure-index build on `results/krama_all104/` returns 49 records
  (matches the manual count).
- Helper parsing returns the 16 helpers currently in
  `data/context/krama_helper.py`.
- All three anchor strings resolve.
- Wiring functions are idempotent (verified via a write-restore test
  with a synthetic `__test_helper_xyz`).
- All four gates fire on synthetic bad inputs (duplicate name,
  missing trigger phrase, network import, paradigm-level miss).

## When to retire this skill

If the helper manifest stabilizes (no new proposals pass gates across
3+ runs), retire the skill — the manifest has reached its ceiling for
the current model class. The right next move at that point is a
different lever (better executor, better verifier, more interpretations
in spec extraction), not more helpers.
