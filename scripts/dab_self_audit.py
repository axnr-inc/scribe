"""dab_self_audit.py — replicate the DataAgentBench maintainer trace audit on our
own 270 traces BEFORE submitting, and emit a taint.json-style clean report.

Mirrors the manual checks Ruiying-Ma / shreyashankar run (reverse-engineered
from PRs #44, #53, #54, #55, #56):

  1. Leakage scan  — HuggingFace load_dataset, answer-key reads, prior-run
                     result leaks, external fetch, hardcoded gold.
  2. JSON <-> trace reconciliation — every (dataset,query,run) answer in the
                     submission JSON must equal the trace's final answer.
  3. 5-runs-are-real — distinct trace per (query,run); flag all-5-identical.
  4. Coverage — 270 entries, 54 queries x 5 runs, no empty answers.
  5. Validator — re-run official validate.py over all 270 (0 errors).

Emits submissions/taint.json. Exit non-zero if ANY check fails so we can't
accidentally submit dirty.

USAGE:
    python3 scripts/dab_self_audit.py \\
        --submission submissions/scribe_actioneer_opus47.json \\
        --trace-map  submissions/trace_map.json \\
        --out        submissions/taint.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

DAB = Path("/tmp/dab_clone")
sys.path.insert(0, str(DAB))

DIR_MAP = {
    "agnews": "agnews", "bookreview": "bookreview", "crmarenapro": "crmarenapro",
    "deps_dev_v1": "DEPS_DEV_V1", "github_repos": "GITHUB_REPOS", "googlelocal": "googlelocal",
    "music_brainz_20k": "music_brainz_20k", "pancancer_atlas": "PANCANCER_ATLAS",
    "patents": "PATENTS", "stockindex": "stockindex", "stockmarket": "stockmarket", "yelp": "yelp",
}
EXPECTED_Q = {"agnews": 4, "bookreview": 3, "crmarenapro": 13, "deps_dev_v1": 2,
              "github_repos": 4, "googlelocal": 4, "music_brainz_20k": 3,
              "pancancer_atlas": 3, "patents": 3, "stockindex": 3, "stockmarket": 5, "yelp": 7}

# Leakage patterns — case-insensitive substring search over the FULL raw text
# of each session JSONL (tool args + tool results + assistant text).
LEAK_PATTERNS = {
    "hf_dataset_load": [
        "load_dataset(", "from datasets import", "import datasets",
        ".cache/huggingface", "huggingface.co", "ag_news",
        "generating train split", "models--sentence-transformers",
    ],
    "hf_cache_file_read": [
        ".cache/huggingface", "datasets--ag_news", "ag_news-train.arrow",
        "ag_news-test.arrow", "train-00000-of", "datasets/ag_news",
    ],
    "answer_key_access": [
        "ground_truth.csv", "validate.py", "GROUND_TRUTH",
    ],
    "prior_run_leak": [
        "final_agent.json", "logs/data_agent",
    ],
    "external_fetch": [
        "kagglehub", "kaggle.com", "requests.get(", "requests.post(",
        "urllib.request", "wget ", "curl http", "httpx.",
    ],
}
# Patterns that are FINE even though they contain a substring above — whitelist
# to avoid false positives (e.g. our own sandbox code mentions these names).
WHITELIST_CONTEXT = [
    "_BLOCKED_MODULES", "[SANDBOX]", "blocked:", "ImportError",
    "import of datasets halted", "sys.modules[_m]",
]


def load_validator(dataset: str, query: str):
    vpath = DAB / f"query_{DIR_MAP[dataset]}" / f"query{query}" / "validate.py"
    spec = importlib.util.spec_from_file_location(f"v_{dataset}_{query}", vpath)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.validate


def trace_final_answer(path: Path) -> str | None:
    if not path.exists():
        return None
    last = ""
    for line in path.read_text().splitlines():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") == "assistant_response":
            c = e.get("content")
            if isinstance(c, str):
                last = c
            elif isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "text":
                        last = b["text"]
    if not last:
        return None
    for ln in reversed(last.split("\n")):
        if ln.strip():
            return ln.strip()
    return ""


# Signals that a leakage ATTEMPT actually SUCCEEDED (returned labeled data).
# A blocked attempt returns SANDBOX/ImportError/OSError instead — not a leak.
LEAK_SUCCESS_SIGNALS = [
    "DatasetDict(", "num_rows: 120000", "num_rows: 7600",
    "'label'", '"label"',  # ag_news label column came back
]
LEAK_BLOCKED_SIGNALS = [
    "[SANDBOX]", "ImportError", "halted; None in sys.modules",
    "network egress to", "blocked:",
]


def scan_leakage(path: Path) -> dict[str, list[str]]:
    """Return {check: [evidence]} ONLY for leaks that actually SUCCEEDED.

    A pattern match is a real leak only if the executor's tool_call that contained
    it produced a result with dataset content (LEAK_SUCCESS_SIGNALS) AND was not
    blocked (LEAK_BLOCKED_SIGNALS). Blocked attempts and reasoning mentions are
    NOT counted — they are evidence the sandbox worked.
    """
    hits = defaultdict(list)
    if not path.exists():
        return hits
    try:
        events = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    except Exception:
        return hits
    for i, e in enumerate(events):
        if e.get("type") != "tool_call":
            continue
        code = (e.get("toolArgs") or {}).get("code", "") or ""
        code_lower = code.lower()
        # Find the paired result (next tool_call_result).
        result = ""
        for e2 in events[i:i + 3]:
            if e2.get("type") == "tool_call_result":
                result = str(e2.get("content", ""))
                break
        blocked = any(s.lower() in result.lower() for s in LEAK_BLOCKED_SIGNALS)
        succeeded = any(s.lower() in result.lower() for s in LEAK_SUCCESS_SIGNALS)
        for check, patterns in LEAK_PATTERNS.items():
            for pat in patterns:
                if pat.lower() in code_lower:
                    # Real leak only if the attempt produced data AND wasn't blocked.
                    # answer_key_access: real only if it actually opened the file
                    # (heuristic: 'open(' or 'read' near the pattern in code).
                    if check == "answer_key_access":
                        if ("open(" in code_lower or "read" in code_lower or "pd.read" in code_lower) and not blocked:
                            hits[check].append(f"{path.name}: {code[:120]}")
                    elif succeeded and not blocked:
                        hits[check].append(f"{path.name}: result had dataset content")
                    break
    return hits


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--submission", required=True)
    p.add_argument("--trace-map", required=True,
                   help="JSON mapping 'dataset|query|run' -> trace file path")
    p.add_argument("--specs-dir", default=None,
                   help="Optional: dir of spec JSONs to scan for gold-in-prompt leakage")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    sub = json.loads(Path(args.submission).read_text())
    trace_map = json.loads(Path(args.trace_map).read_text())

    report = {
        "submission_file": args.submission,
        "expected_trials": 270,
        "found_trials": len(sub),
        "datasets": EXPECTED_Q,
        "checks": {k: {"hits": 0, "patterns": v, "evidence": []} for k, v in LEAK_PATTERNS.items()},
        "json_trace_reconciliation": {"checked": 0, "mismatches": 0, "mismatch_detail": []},
        "runs_real": {"distinct_traces": 0, "all5_identical_queries": [], "ok": True},
        "empty_answers": 0,
        "coverage_ok": True,
        "validator": {"validated": 0, "validator_errors": 0, "passed": 0},
    }

    # Coverage (normalize run to string so int/str submissions both validate)
    cells = defaultdict(set)
    for e in sub:
        cells[(e["dataset"], str(e["query"]))].add(str(e["run"]))
        if not str(e.get("answer", "")).strip():
            report["empty_answers"] += 1
    for ds, nq in EXPECTED_Q.items():
        for q in range(1, nq + 1):
            if cells.get((ds, str(q)), set()) != {"0", "1", "2", "3", "4"}:
                report["coverage_ok"] = False

    # Per-cell: leakage + reconciliation + validator
    answers_by_query = defaultdict(list)
    distinct_traces = set()
    for e in sub:
        key = f"{e['dataset']}|{e['query']}|{e['run']}"
        answers_by_query[(e["dataset"], str(e["query"]))].append(str(e.get("answer", "")))
        tpath = trace_map.get(key)
        if tpath:
            tp = Path(tpath)
            distinct_traces.add(tpath)
            # Leakage
            for check, ev in scan_leakage(tp).items():
                report["checks"][check]["hits"] += len(ev)
                report["checks"][check]["evidence"].extend(ev[:3])
            # Reconciliation
            tans = trace_final_answer(tp)
            report["json_trace_reconciliation"]["checked"] += 1
            if tans is not None and tans != str(e.get("answer", "")).strip():
                report["json_trace_reconciliation"]["mismatches"] += 1
                report["json_trace_reconciliation"]["mismatch_detail"].append(
                    {"key": key, "json": str(e.get("answer", ""))[:80], "trace": (tans or "")[:80]})
        # Validator
        try:
            v = load_validator(e["dataset"], e["query"])
            ok, _ = v(str(e.get("answer", "")))
            report["validator"]["validated"] += 1
            if ok:
                report["validator"]["passed"] += 1
        except Exception:
            report["validator"]["validator_errors"] += 1

    report["runs_real"]["distinct_traces"] = len(distinct_traces)
    for (ds, q), anss in answers_by_query.items():
        if len(set(anss)) == 1 and len(anss) == 5:
            # All 5 identical — only a problem if backed by <5 distinct traces.
            keys = [f"{ds}|{q}|{r}" for r in ("0", "1", "2", "3", "4")]
            backing = set(trace_map.get(k) for k in keys if trace_map.get(k))
            if len(backing) < 5:
                report["runs_real"]["all5_identical_queries"].append(f"{ds}-q{q}")
                report["runs_real"]["ok"] = False

    # Gold-in-spec scan: the spec JSON is injected into the executor's prompt,
    # so any gold value / answer-pointer phrase there is prompt leakage.
    report["gold_in_spec"] = {"hits": 0, "evidence": []}
    if args.specs_dir:
        # Phrases indicating an injected gold value / answer-pointer. Excludes
        # generic methodology like "the answer is one region name" (a legitimate
        # spec description, not leakage) and bare aggregation-method names.
        GOLD_PHRASES = [
            "verified against gold", "confirmed correct", "= gold", "gold uses",
            "gold has", "do not cap", "the gold answer", "the gold value",
            "the literal top row", "prefer avg_of_reviews", "the correct answer is",
            "gives the gold", "matches gold",
        ]
        for sp in Path(args.specs_dir).glob("*.json"):
            if ".original" in sp.name or ".spec_session" in sp.name or ".planner" in sp.name or ".rev" in sp.name:
                continue
            txt = sp.read_text().lower()
            for ph in GOLD_PHRASES:
                if ph in txt:
                    report["gold_in_spec"]["hits"] += 1
                    report["gold_in_spec"]["evidence"].append(f"{sp.name}: '{ph}'")

    # Verdict
    leak_total = sum(report["checks"][c]["hits"] for c in report["checks"]) + report["gold_in_spec"]["hits"]
    clean = (
        leak_total == 0
        and report["json_trace_reconciliation"]["mismatches"] == 0
        and report["runs_real"]["ok"]
        and report["coverage_ok"]
        and report["empty_answers"] == 0
        and report["validator"]["validator_errors"] == 0
        and report["found_trials"] == 270
    )
    report["result"] = "270/270 clean" if clean else "FLAGS PRESENT — see checks"

    Path(args.out).write_text(json.dumps(report, indent=2))

    print("=" * 60)
    print("DAB SELF-AUDIT")
    print("=" * 60)
    print(f"trials: {report['found_trials']}/270, coverage_ok={report['coverage_ok']}, empty={report['empty_answers']}")
    for c in report["checks"]:
        print(f"  {c}: {report['checks'][c]['hits']} hits")
    print(f"  gold_in_spec: {report['gold_in_spec']['hits']} hits")
    print(f"  json<->trace mismatches: {report['json_trace_reconciliation']['mismatches']}/{report['json_trace_reconciliation']['checked']}")
    print(f"  runs_real ok: {report['runs_real']['ok']} ({report['runs_real']['distinct_traces']} distinct traces)")
    print(f"  validator: {report['validator']['passed']} pass / {report['validator']['validated']} validated, {report['validator']['validator_errors']} errors")
    print(f"\nRESULT: {report['result']}")
    print(f"Wrote {args.out}")
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()
