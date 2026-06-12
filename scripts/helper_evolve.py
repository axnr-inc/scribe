"""helper_evolve.py — orchestrator for the SCRIBE helper-evolution loop.

Automates steps 3-9 of the manual KramaBench helper-mining workflow described
in `docs/findings/21_helper_manifest_expansion.md` and the helper-evolve skill
(`.claude/skills/helper-evolve/SKILL.md`). Step 1 (executor run) and step 2
(scoring) stay with the user's existing scripts; this orchestrator picks up
from the scored run directory.

Stages:
  step 3: build failure index from final_results.json + official_scores/
  step 4: LLM classifier → groups failures by type
  step 5: LLM proposer → emits ProposedHelper records (Pydantic-validated)
  step 6: wire approved helpers into 3 files (idempotent)
  step 7: re-extract specs for failed tasks
  step 8: re-run executor on failed tasks
  step 9: merge + re-score + delta report

Usage:
    python3 scripts/helper_evolve.py \
        --run-dir results/krama_opus_104_v3 \
        --tasks   data/splits/krama_all104.jsonl \
        --config  configs/kramabench_scribe_opus.yaml

Stages 7-9 are gated behind --execute (default: dry-run; only steps 3-6 run).
This keeps the orchestrator cheap to iterate on locally.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


# ===========================================================================
# Pydantic schema (load-bearing)
# ===========================================================================


class ProposedHelper(BaseModel):
    """Schema the LLM proposer must emit for each new helper."""

    name: str = Field(description="snake_case Python identifier; e.g. canonicalize_msa_name")
    signature: str = Field(
        description="full signature line including param defaults; e.g. 'foo(x: int, y: str = \"a\") -> str'"
    )
    purpose: str = Field(description="1-2 sentence rationale")
    recovers_task_ids: list[str] = Field(
        description="task_ids from _failures.json this helper would fix; non-empty"
    )
    docstring: str = Field(
        description="drop-in PEP-257 docstring text WITHOUT the surrounding triple quotes"
    )
    implementation: str = Field(
        description="plain-text Python function body (without the def line); will be wrapped"
    )
    spec_agent_description: str = Field(
        description=(
            "2-4 line block to splice into extract_specs_krama.py's helper menu. "
            "Must include a 'use when'/'use for'/'use whenever' trigger phrase."
        )
    )
    inclusion_criteria_passed: dict[str, bool] = Field(
        description=(
            "Self-attested gates: recovers_documented_failure, paradigm_level, "
            "pure_python, trigger_phrase_in_docstring."
        )
    )


class ProposerOutput(BaseModel):
    helpers: list[ProposedHelper]
    rejected_drafts: list[str] = Field(
        default_factory=list,
        description="Free-text notes on candidates the proposer itself decided NOT to emit.",
    )


class FailureCluster(BaseModel):
    label: str = Field(description="short kebab-case label, e.g. 'msa-canonicalization'")
    task_ids: list[str]
    root_cause: str = Field(description="1-2 sentence diagnosis of the shared mode")
    suggests_helper: bool


class ClassifierOutput(BaseModel):
    clusters: list[FailureCluster]
    notes: str = ""


# ===========================================================================
# Step 3: failure index
# ===========================================================================


@dataclass
class FailureRecord:
    task_id: str
    domain: str
    level: str
    answer_type: str
    question: str
    gold: str
    got: str
    pass_score: float  # per_task_pass (may be fractional for partial scores)
    error: str | None = None
    spec_path: str | None = None


def _load_json(p: Path) -> Any:
    with p.open() as f:
        return json.load(f)


def _iter_jsonl(p: Path) -> list[dict]:
    out: list[dict] = []
    with p.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def build_failure_index(run_dir: Path, tasks_jsonl: Path) -> list[FailureRecord]:
    """Step 3: cross-reference final_results.json with official_scores/overall.json
    and the source dataset to emit a structured failure index."""
    final_results_path = run_dir / "final_results.json"
    overall_path = run_dir / "official_scores" / "overall.json"
    if not final_results_path.exists():
        raise FileNotFoundError(f"missing {final_results_path}")
    if not overall_path.exists():
        raise FileNotFoundError(f"missing {overall_path}")

    finals = _load_json(final_results_path)
    overall = _load_json(overall_path)
    tasks_by_id = {row["task_id"]: row for row in _iter_jsonl(tasks_jsonl)}

    per_task_pass: dict[str, float] = {}
    for domain_block in overall.values():
        per_task_pass.update(domain_block.get("per_task_pass", {}))

    records: list[FailureRecord] = []
    for entry in finals:
        task_id = entry["task_id"]
        score = per_task_pass.get(task_id, 0.0 if not entry.get("pass") else 1.0)
        if score >= 1.0:
            continue  # only failed/partial tasks
        meta = tasks_by_id.get(task_id, {})
        spec_path = run_dir / "specs" / f"{task_id}.json"
        records.append(
            FailureRecord(
                task_id=task_id,
                domain=entry.get("domain", meta.get("domain", "")),
                level=entry.get("level", meta.get("level", "")),
                answer_type=meta.get("answer_type", ""),
                question=meta.get("question", ""),
                gold=str(entry.get("gold", meta.get("answer", ""))),
                got=str(entry.get("final_answer", "")),
                pass_score=float(score),
                error=entry.get("error"),
                spec_path=str(spec_path) if spec_path.exists() else None,
            )
        )
    return records


def write_failures_json(records: list[FailureRecord], out_path: Path) -> None:
    payload = [
        {
            "task_id": r.task_id,
            "domain": r.domain,
            "level": r.level,
            "answer_type": r.answer_type,
            "question": r.question,
            "gold": r.gold,
            "got": r.got,
            "pass_score": r.pass_score,
            "error": r.error,
            "spec_path": r.spec_path,
        }
        for r in records
    ]
    out_path.write_text(json.dumps(payload, indent=2))


# ===========================================================================
# Step 4-5: LLM-driven classification + proposal
# ===========================================================================


def _anthropic_client():
    from anthropic import Anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set (load .env)")
    return Anthropic(api_key=api_key)


CLASSIFIER_SYSTEM = """\
You are a failure-mode analyst for the SCRIBE benchmark harness. The user will
give you a JSON list of failed KramaBench tasks (gold vs got). Group them into
clusters that share a single root cause.

A useful cluster:
- has 2+ task_ids OR is clearly a paradigm-level recurring data primitive
  (so a future helper recovers more than one task).
- has a one- or two-sentence root cause that names the operation needed
  (e.g., "MSA name canonicalization", "BP-to-calendar conversion").
- sets suggests_helper=true ONLY if a SMALL paradigm-level Python primitive
  would have prevented the failure.

Do NOT propose helpers in this step; just cluster. The next agent will
generate proposals from your clusters.
"""

PROPOSER_SYSTEM = """\
You are the HELPER MINER for the SCRIBE harness. The user gives you:
  (a) the failure list (gold vs got),
  (b) clusters from the classifier,
  (c) the set of helpers already present (names + signatures).

You emit ProposedHelper records that meet ALL inclusion gates:
- recovers_documented_failure: each helper.recovers_task_ids must be a non-empty
  subset of the supplied failing task_ids.
- paradigm_level: applies to >=2 tasks, OR is a recurring scientific/regulatory
  primitive (e.g., physics constant transform, percentile aggregator).
- pure_python: no network / LLM / external-API imports in implementation.
- trigger_phrase_in_docstring: docstring contains "use when" or "use for" or
  "use whenever" so the spec_agent can find it.

CRITICAL: do not duplicate or shadow any helper name in the "already present"
list. If the failure is solved by an existing helper that just wasn't used,
emit nothing and note this in rejected_drafts.

Style — match the existing helpers in `data/context/krama_helper.py`:
- Implementation accepts pd.DataFrame / np.ndarray / Series uniformly.
- Docstrings list "Recovers: <task_id>, ..." in the last paragraph.
- Implementations are pure functions, no I/O side-effects unless the helper IS
  an I/O helper (like read_multi_header_excel).
- Keep each implementation <40 lines.

Return up to 6 helpers. Quality > quantity.
"""


def llm_classify(client, failures: list[FailureRecord], model: str) -> ClassifierOutput:
    user = json.dumps(
        [
            {
                "task_id": f.task_id,
                "domain": f.domain,
                "level": f.level,
                "question": f.question,
                "gold": f.gold,
                "got": f.got,
                "answer_type": f.answer_type,
            }
            for f in failures
        ],
        indent=2,
    )
    msg = client.messages.parse(
        model=model,
        max_tokens=8000,
        system=CLASSIFIER_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=ClassifierOutput,
    )
    out = msg.output_parsed
    assert out is not None, "classifier returned no parsed output"
    return out


def llm_propose(
    client,
    failures: list[FailureRecord],
    clusters: ClassifierOutput,
    existing_helpers: list[tuple[str, str]],
    model: str,
) -> ProposerOutput:
    existing_block = "\n".join(f"- {name}{sig}" for name, sig in existing_helpers)
    user = (
        "FAILURES:\n"
        + json.dumps(
            [
                {
                    "task_id": f.task_id,
                    "domain": f.domain,
                    "question": f.question,
                    "gold": f.gold,
                    "got": f.got,
                }
                for f in failures
            ],
            indent=2,
        )
        + "\n\nCLUSTERS:\n"
        + clusters.model_dump_json(indent=2)
        + "\n\nALREADY-PRESENT HELPERS:\n"
        + existing_block
    )
    msg = client.messages.parse(
        model=model,
        max_tokens=16000,
        system=PROPOSER_SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_format=ProposerOutput,
    )
    out = msg.output_parsed
    assert out is not None, "proposer returned no parsed output"
    return out


# ===========================================================================
# Gate enforcement
# ===========================================================================


_FORBIDDEN_IMPORTS = re.compile(
    r"\bimport\s+(requests|urllib|httpx|openai|anthropic|langchain|aiohttp|socket|paramiko)\b"
    r"|\bfrom\s+(requests|urllib|httpx|openai|anthropic|langchain|aiohttp|socket|paramiko)\b"
)

_TRIGGER_RE = re.compile(r"\b(use when|use for|use whenever)\b", re.IGNORECASE)


def enforce_gates(
    proposal: ProposedHelper,
    failing_task_ids: set[str],
    existing_names: set[str],
) -> tuple[bool, list[str]]:
    """Return (passed, reasons_failed). Re-derives gates from the proposal
    content rather than trusting the LLM's self-attestation."""
    reasons: list[str] = []

    # name uniqueness
    if proposal.name in existing_names:
        reasons.append(f"name '{proposal.name}' duplicates existing helper")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", proposal.name):
        reasons.append(f"name '{proposal.name}' is not a valid snake_case identifier")

    # recovers_documented_failure
    recovered = set(proposal.recovers_task_ids)
    if not recovered:
        reasons.append("recovers_task_ids is empty")
    bogus = recovered - failing_task_ids
    if bogus:
        reasons.append(f"recovers_task_ids references non-failing tasks: {sorted(bogus)}")

    # paradigm_level — accept if either >=2 real failing tasks recovered,
    # or the proposer self-attested AND name suggests a primitive (not task-specific).
    real_hits = recovered & failing_task_ids
    if len(real_hits) < 2 and not proposal.inclusion_criteria_passed.get("paradigm_level", False):
        reasons.append(
            f"paradigm_level: only {len(real_hits)} real failing tasks recovered and "
            "self-attestation absent"
        )

    # pure_python
    if _FORBIDDEN_IMPORTS.search(proposal.implementation):
        reasons.append("pure_python: implementation imports a network/LLM library")

    # trigger phrase
    if not _TRIGGER_RE.search(proposal.docstring):
        reasons.append("trigger_phrase_in_docstring: missing 'use when/for/whenever'")

    return (not reasons), reasons


# ===========================================================================
# Step 6: idempotent wiring into 3 files
# ===========================================================================


HELPER_PY = ROOT / "data" / "context" / "krama_helper.py"
RUN_TS = ROOT / "src" / "run.ts"
EXTRACT_PY = ROOT / "scripts" / "extract_specs_krama.py"


# Anchor strings — must match the current contents EXACTLY.
RUN_TS_OPEN_ANCHOR = "    lines.push(`        find_column_by_keywords,`);"
RUN_TS_CLOSE_ANCHOR = "    lines.push(`    )`);"

EXTRACT_PY_SENTINEL = "When a helper applies, include in `computation_plan`"


def existing_helper_names() -> list[str]:
    """Parse `def NAME(` lines from data/context/krama_helper.py."""
    text = HELPER_PY.read_text()
    return re.findall(r"^def\s+([a-zA-Z_]\w*)\s*\(", text, flags=re.MULTILINE)


def existing_helpers_with_sigs() -> list[tuple[str, str]]:
    text = HELPER_PY.read_text()
    out: list[tuple[str, str]] = []
    # capture name + signature paren block (may span lines)
    for m in re.finditer(
        r"^def\s+([a-zA-Z_]\w*)\s*(\([\s\S]*?\)\s*(?:->\s*[^:]+)?):",
        text,
        flags=re.MULTILINE,
    ):
        out.append((m.group(1), m.group(2)))
    return out


def _format_helper_block(p: ProposedHelper) -> str:
    """Render a fully-formed Python helper section, matching the existing style."""
    body = textwrap.indent(p.implementation.rstrip() + "\n", "    ")
    doc = p.docstring.strip().replace('"""', '\\"\\"\\"')
    return (
        f"\n# ---------------------------------------------------------------------------\n"
        f"# {p.name}  (added by helper_evolve.py)\n"
        f"# ---------------------------------------------------------------------------\n\n"
        f"def {p.signature.strip()}:\n"
        f'    """{doc}\n    """\n'
        f"{body}\n"
    )


def wire_helper_py(approved: list[ProposedHelper]) -> list[str]:
    """Append helpers to data/context/krama_helper.py.  Idempotent."""
    text = HELPER_PY.read_text()
    added: list[str] = []
    for p in approved:
        if re.search(rf"^def\s+{re.escape(p.name)}\s*\(", text, flags=re.MULTILINE):
            print(f"  [wire helper.py] skip {p.name} (already defined)")
            continue
        text = text.rstrip() + "\n" + _format_helper_block(p)
        added.append(p.name)
    HELPER_PY.write_text(text)
    return added


def wire_run_ts(approved: list[ProposedHelper]) -> list[str]:
    """Insert names into the `from krama_helper import (...)` push block in src/run.ts."""
    text = RUN_TS.read_text()
    added: list[str] = []
    # Find the open anchor index — the close anchor is the FIRST occurrence of
    # `    lines.push(\`    )\`);` AFTER it.
    open_idx = text.find(RUN_TS_OPEN_ANCHOR)
    if open_idx == -1:
        raise RuntimeError(
            f"src/run.ts open anchor not found: {RUN_TS_OPEN_ANCHOR!r}. "
            "The preamble block may have changed; update RUN_TS_OPEN_ANCHOR."
        )
    close_idx = text.find(RUN_TS_CLOSE_ANCHOR, open_idx)
    if close_idx == -1:
        raise RuntimeError("src/run.ts close anchor not found after open anchor")

    block = text[open_idx:close_idx]
    insertion_lines: list[str] = []
    for p in approved:
        marker = f"        {p.name},"
        if marker in block:
            print(f"  [wire run.ts] skip {p.name} (already imported)")
            continue
        insertion_lines.append(f"    lines.push(`        {p.name},`);\n")
        added.append(p.name)

    if not insertion_lines:
        return added

    end_of_open_line = text.find("\n", open_idx) + 1
    new_text = text[:end_of_open_line] + "".join(insertion_lines) + text[end_of_open_line:]
    RUN_TS.write_text(new_text)
    return added


_EVOLVE_BLOCK_BEGIN = "# --- helper_evolve auto-additions BEGIN ---"
_EVOLVE_BLOCK_END = "# --- helper_evolve auto-additions END ---"


def wire_extract_specs(approved: list[ProposedHelper]) -> list[str]:
    """Splice spec_agent_description blocks into extract_specs_krama.py
    immediately BEFORE the sentinel line. Idempotent — re-uses a marked block."""
    text = EXTRACT_PY.read_text()
    if EXTRACT_PY_SENTINEL not in text:
        raise RuntimeError(
            f"extract_specs_krama.py sentinel not found: {EXTRACT_PY_SENTINEL!r}"
        )

    # Determine the prose-string concat region (a triple-quoted or implicit-concat
    # block of plain text). We assume the sentinel sits as a line of plain text
    # in the SYSTEM_PROMPT block; we just prepend our additions as a comment-free
    # text section delimited by sentinels we own.
    if _EVOLVE_BLOCK_BEGIN in text and _EVOLVE_BLOCK_END in text:
        # Already have a managed block — splice into it.
        pre, rest = text.split(_EVOLVE_BLOCK_BEGIN, 1)
        managed, post = rest.split(_EVOLVE_BLOCK_END, 1)
        existing_block = managed
    else:
        idx = text.find(EXTRACT_PY_SENTINEL)
        # Walk back to the start of the line containing the sentinel.
        line_start = text.rfind("\n", 0, idx) + 1
        pre = text[:line_start]
        post = text[line_start:]
        existing_block = f"\n{_EVOLVE_BLOCK_BEGIN}\n{_EVOLVE_BLOCK_END}\n"
        # Now we'll work in pre + existing_block + post; the splice point is between
        # the BEGIN/END markers.
        text = pre + existing_block + post
        pre, rest = text.split(_EVOLVE_BLOCK_BEGIN, 1)
        managed, post = rest.split(_EVOLVE_BLOCK_END, 1)
        existing_block = managed

    added: list[str] = []
    new_block = existing_block
    for p in approved:
        marker = f"- {p.name}("
        if marker in new_block or marker in pre:
            print(f"  [wire extract] skip {p.name} (description already present)")
            continue
        desc = p.spec_agent_description.strip()
        if not desc.lstrip().startswith("- "):
            # Ensure dash-prefixed bullet matching surrounding style.
            desc = f"- {desc}" if not desc.startswith(p.name) else f"- {desc}"
        new_block = new_block.rstrip() + "\n" + desc + "\n"
        added.append(p.name)

    new_text = pre + _EVOLVE_BLOCK_BEGIN + new_block + _EVOLVE_BLOCK_END + post
    EXTRACT_PY.write_text(new_text)
    return added


# ===========================================================================
# Steps 7-9: re-extract, re-run, score delta (shell-out only; gated by --execute)
# ===========================================================================


def write_failed_tasks_jsonl(records: list[FailureRecord], tasks_jsonl: Path, out: Path) -> int:
    """Subset the source dataset to only the failing task_ids; preserves order."""
    failing = {r.task_id for r in records}
    by_id = {row["task_id"]: row for row in _iter_jsonl(tasks_jsonl)}
    lines = []
    for tid in failing:
        if tid in by_id:
            lines.append(json.dumps(by_id[tid]))
    out.write_text("\n".join(lines) + "\n")
    return len(lines)


def run_cmd(cmd: list[str], cwd: Path | None = None) -> int:
    print(f"  $ {' '.join(shlex.quote(c) for c in cmd)}")
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None)
    return proc.returncode


def step7_reextract_specs(failed_jsonl: Path, out_dir: Path) -> int:
    return run_cmd(
        [
            sys.executable,
            "scripts/extract_specs_krama.py",
            "--extractor",
            "anthropic:claude-opus-4-7",
            "--tasks",
            str(failed_jsonl),
            "--out",
            str(out_dir),
        ],
        cwd=ROOT,
    )


def step8_rerun_executor(
    config: Path, failed_jsonl: Path, specs_dir: Path, rerun_dir: Path, workers: int
) -> int:
    return run_cmd(
        [
            "npm",
            "run",
            "run",
            "--",
            "--config",
            str(config),
            "--dataset",
            str(failed_jsonl),
            "--specs",
            str(specs_dir),
            "--out-dir",
            str(rerun_dir),
            "--workers",
            str(workers),
        ],
        cwd=ROOT,
    )


def step9_merge_and_delta(
    original_run_dir: Path,
    rerun_dir: Path,
    failures_before: list[FailureRecord],
    approved: list[ProposedHelper],
    out_path: Path,
) -> dict:
    """Merge original passing tasks + rerun results, re-score, write delta report."""
    orig_finals = _load_json(original_run_dir / "final_results.json")
    rerun_finals_path = rerun_dir / "final_results.json"
    if not rerun_finals_path.exists():
        raise FileNotFoundError(f"missing {rerun_finals_path}")
    rerun_finals = _load_json(rerun_finals_path)

    rerun_by_id = {r["task_id"]: r for r in rerun_finals}
    merged = []
    for entry in orig_finals:
        tid = entry["task_id"]
        merged.append(rerun_by_id.get(tid, entry))
    merged_path = rerun_dir / "final_results_merged.json"
    merged_path.write_text(json.dumps(merged, indent=2))

    # Run the scorer.
    score_dir = rerun_dir / "official_scores_merged"
    score_dir.mkdir(parents=True, exist_ok=True)
    rc = run_cmd(
        [
            sys.executable,
            "scripts/score_krama104_official.py",
            "--results",
            str(merged_path),
            "--out",
            str(score_dir),
        ],
        cwd=ROOT,
    )
    if rc != 0:
        print(f"  [step 9] scorer exited {rc}; delta report may be partial.")

    # Diff per-task pass.
    after_overall = _load_json(score_dir / "overall.json")
    after_pass: dict[str, float] = {}
    for blk in after_overall.values():
        after_pass.update(blk.get("per_task_pass", {}))
    before_pass = {f.task_id: f.pass_score for f in failures_before}

    deltas = []
    for tid, before in before_pass.items():
        after = after_pass.get(tid, before)
        deltas.append({"task_id": tid, "before": before, "after": after, "delta": after - before})

    # Helper invocation audit: grep specs_v2 for each name.
    invocations = {p.name: [] for p in approved}
    specs_v2 = rerun_dir.parent / "specs_v2" if (rerun_dir.parent / "specs_v2").exists() else None
    if specs_v2 is None:
        # default to <original_run_dir>/specs_v2 conventionally
        specs_v2 = original_run_dir / "specs_v2"
    if specs_v2.exists():
        for spec_file in specs_v2.glob("*.json"):
            spec_text = spec_file.read_text()
            for p in approved:
                if p.name in spec_text:
                    invocations[p.name].append(spec_file.stem)

    report = {
        "approved_helpers": [p.name for p in approved],
        "per_task_delta": deltas,
        "net_delta": sum(d["delta"] for d in deltas),
        "helper_invocations": invocations,
        "unused_helpers": [n for n, v in invocations.items() if not v],
    }
    out_path.write_text(json.dumps(report, indent=2))
    return report


# ===========================================================================
# CLI
# ===========================================================================


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Helper-evolution orchestrator for the SCRIBE harness.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("--run-dir", type=Path, required=True, help="results/<run> dir")
    ap.add_argument("--tasks", type=Path, required=True, help="source dataset jsonl")
    ap.add_argument("--config", type=Path, required=True, help="executor config yaml")
    ap.add_argument(
        "--model",
        default="claude-opus-4-7",
        help="Anthropic model id for classifier+proposer (default claude-opus-4-7)",
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        help="run steps 7-9 (re-extract, re-run, delta). default: dry-run (steps 3-6 only).",
    )
    ap.add_argument(
        "--workers", type=int, default=4, help="executor worker count for step 8"
    )
    ap.add_argument(
        "--skip-wiring",
        action="store_true",
        help="run steps 3-5 and write proposals but do not edit source files",
    )
    args = ap.parse_args(argv)

    run_dir: Path = args.run_dir.resolve()
    tasks_jsonl: Path = args.tasks.resolve()
    config: Path = args.config.resolve()

    if not run_dir.exists():
        print(f"[fatal] run dir does not exist: {run_dir}", file=sys.stderr)
        return 2
    if not tasks_jsonl.exists():
        print(f"[fatal] tasks file does not exist: {tasks_jsonl}", file=sys.stderr)
        return 2

    # ---- Step 3 ----
    print("[step 3] building failure index")
    failures = build_failure_index(run_dir, tasks_jsonl)
    failures_path = run_dir / "_failures.json"
    write_failures_json(failures, failures_path)
    print(f"  -> {failures_path} ({len(failures)} failures)")

    if not failures:
        print("[done] no failures to mine; exiting.")
        return 0

    # ---- Step 4-5 ----
    print(f"[step 4] classifying failures with {args.model}")
    client = _anthropic_client()
    clusters = llm_classify(client, failures, args.model)
    clusters_path = run_dir / "_clusters.json"
    clusters_path.write_text(clusters.model_dump_json(indent=2))
    print(f"  -> {clusters_path} ({len(clusters.clusters)} clusters)")

    print(f"[step 5] proposing helpers with {args.model}")
    existing = existing_helpers_with_sigs()
    existing_names = {n for n, _ in existing}
    proposals = llm_propose(client, failures, clusters, existing, args.model)
    proposals_path = run_dir / "_proposals.json"
    proposals_path.write_text(proposals.model_dump_json(indent=2))
    print(f"  -> {proposals_path} ({len(proposals.helpers)} draft helpers)")

    # ---- Gate enforcement ----
    print("[step 5.5] enforcing inclusion gates")
    failing_ids = {f.task_id for f in failures}
    approved: list[ProposedHelper] = []
    rejected: list[dict[str, Any]] = []
    for p in proposals.helpers:
        ok, reasons = enforce_gates(p, failing_ids, existing_names)
        if ok:
            approved.append(p)
            print(f"  [approve] {p.name}  (recovers {p.recovers_task_ids})")
        else:
            rejected.append({"name": p.name, "reasons": reasons})
            print(f"  [reject ] {p.name}: {reasons}")
    rejections_path = run_dir / "_rejections.json"
    rejections_path.write_text(json.dumps(rejected, indent=2))
    approved_path = run_dir / "_approved_helpers.json"
    approved_path.write_text(json.dumps([p.model_dump() for p in approved], indent=2))
    print(f"  -> {approved_path} ({len(approved)} approved, {len(rejected)} rejected)")

    if not approved:
        print("[done] no helpers passed gates; nothing to wire.")
        return 0

    # ---- Step 6 ----
    if args.skip_wiring:
        print("[step 6] SKIPPED (--skip-wiring)")
    else:
        print("[step 6] wiring approved helpers into source files (idempotent)")
        added_helper_py = wire_helper_py(approved)
        added_run_ts = wire_run_ts(approved)
        added_extract = wire_extract_specs(approved)
        print(f"  -> {HELPER_PY.relative_to(ROOT)}: added {added_helper_py}")
        print(f"  -> {RUN_TS.relative_to(ROOT)}: added {added_run_ts}")
        print(f"  -> {EXTRACT_PY.relative_to(ROOT)}: added {added_extract}")

    if not args.execute:
        print(
            "[done] dry-run complete. Re-invoke with --execute to run steps 7-9 "
            "(re-extract specs, re-run executor, score delta)."
        )
        return 0

    # ---- Step 7 ----
    print("[step 7] re-extracting specs for failed tasks")
    failed_jsonl = run_dir / "_failed.jsonl"
    n = write_failed_tasks_jsonl(failures, tasks_jsonl, failed_jsonl)
    print(f"  -> {failed_jsonl} ({n} tasks)")
    specs_v2 = run_dir / "specs_v2"
    specs_v2.mkdir(exist_ok=True)
    rc = step7_reextract_specs(failed_jsonl, specs_v2)
    if rc != 0:
        print(f"[step 7] re-extract returned {rc}; aborting before re-run.")
        return rc

    # ---- Step 8 ----
    print("[step 8] re-running executor on failed tasks")
    rerun_dir = run_dir / "_rerun"
    rc = step8_rerun_executor(config, failed_jsonl, specs_v2, rerun_dir, args.workers)
    if rc != 0:
        print(f"[step 8] executor returned {rc}; aborting before delta.")
        return rc

    # ---- Step 9 ----
    print("[step 9] merging rerun with originals and computing delta")
    delta_path = run_dir / "_delta_report.json"
    report = step9_merge_and_delta(run_dir, rerun_dir, failures, approved, delta_path)
    print(f"  -> {delta_path}")
    print(
        f"  net Δ pass-mass: {report['net_delta']:+.3f}; "
        f"unused helpers: {report['unused_helpers']}"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValidationError as e:
        print(f"[fatal] schema validation failed: {e}", file=sys.stderr)
        sys.exit(3)
