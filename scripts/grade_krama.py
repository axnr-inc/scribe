"""Grade a KramaBench run.

Walks results/<run>/<task_id>/sessions/normal_agent.jsonl, extracts the final
assistant_response, scores against the task's gold answer using the answer_type
the adapter persisted, and writes results.csv + results.json.

Supported answer_types (E2E scoring only — 3-capability scoring is deferred):
  numeric_exact / numeric_approximate
  string_exact / string_approximate
  list_exact / list_approximate
  boolean

The gold lives in the original Krama tasks JSONL (data/splits/krama_*.jsonl);
we re-read it to get gold + answer_type per task_id.

Example:
  python3 scripts/grade_krama.py \\
      --out results/krama_smoke \\
      --tasks data/splits/krama_archeology12.jsonl
"""
import argparse
import csv
import json
import math
import re
from pathlib import Path


def load_tasks(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        t = json.loads(line)
        out[str(t["task_id"])] = t
    return out


def extract_pred_text(task_dir: Path) -> str:
    """Get the LAST line of the LAST assistant_response in the session log.
    Mirrors the DABStep convention: final answer is on its own line at the end."""
    log = task_dir / "sessions" / "normal_agent.jsonl"
    if not log.exists():
        return ""
    last_resp = ""
    for line in log.read_text().splitlines():
        if not line.strip():
            continue
        try:
            evt = json.loads(line)
        except Exception:
            continue
        if evt.get("type") == "assistant_response":
            last_resp = str(evt.get("content", ""))
    # Final-answer convention: last non-blank line of the last response.
    for ln in reversed([l.rstrip() for l in last_resp.splitlines()]):
        if ln.strip():
            return ln.strip()
    return ""


# ---------------------------------------------------------------------------
# Per-answer-type scorers
# ---------------------------------------------------------------------------

def _to_number(s: str) -> float | None:
    if s is None:
        return None
    s = str(s).strip().replace(",", "").rstrip(".")
    if s.lower() in ("not applicable", "n/a", "na", ""):
        return None
    try:
        return float(s)
    except ValueError:
        # Pull first floaty token if mixed in prose.
        m = re.search(r"-?\d+(\.\d+)?", s)
        if m:
            try:
                return float(m.group(0))
            except ValueError:
                return None
        return None


def score_numeric_exact(pred: str, gold: str, tol_rel: float = 1e-3) -> bool:
    p = _to_number(pred)
    g = _to_number(gold)
    if p is None or g is None:
        return False
    if math.isnan(p) or math.isnan(g):
        return False
    if g == 0:
        return abs(p) < 1e-9
    return abs(p - g) / abs(g) <= tol_rel


def score_numeric_approximate(pred: str, gold: str, tol_rel: float = 0.05) -> bool:
    return score_numeric_exact(pred, gold, tol_rel=tol_rel)


def _norm_string(s: str) -> str:
    s = (s or "").strip().strip("\"'").strip()
    return re.sub(r"\s+", " ", s).lower()


def score_string_exact(pred: str, gold: str) -> bool:
    return _norm_string(pred) == _norm_string(gold)


def score_string_approximate(pred: str, gold: str) -> bool:
    p, g = _norm_string(pred), _norm_string(gold)
    if not p or not g:
        return False
    return p == g or p in g or g in p


def _parse_list(s: str) -> list[str]:
    s = (s or "").strip()
    if not s:
        return []
    # Try JSON
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed]
        except Exception:
            pass
    # Comma-separated fallback
    return [x.strip().strip("\"'") for x in s.split(",") if x.strip()]


def score_list_exact(pred: str, gold: str) -> bool:
    pl = _parse_list(pred)
    gl = _parse_list(gold)
    if len(pl) != len(gl):
        return False
    return all(_norm_string(p) == _norm_string(g) for p, g in zip(pl, gl))


def score_list_approximate(pred: str, gold: str) -> bool:
    pl = set(_norm_string(x) for x in _parse_list(pred))
    gl = set(_norm_string(x) for x in _parse_list(gold))
    if not gl:
        return False
    # F1 >= 0.9 — mirrors KramaBench's list_approximate threshold (paper §2.2)
    tp = len(pl & gl)
    if tp == 0:
        return False
    precision = tp / len(pl) if pl else 0.0
    recall = tp / len(gl)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return f1 >= 0.9


def score_boolean(pred: str, gold: str) -> bool:
    p = _norm_string(pred)
    g = _norm_string(gold)
    truthy = {"true", "yes", "y", "1"}
    falsy = {"false", "no", "n", "0"}
    pp = True if p in truthy else (False if p in falsy else None)
    gg = True if g in truthy else (False if g in falsy else None)
    if pp is None or gg is None:
        return False
    return pp == gg


SCORERS = {
    "numeric_exact": score_numeric_exact,
    "numeric_approximate": score_numeric_approximate,
    "string_exact": score_string_exact,
    "string_approximate": score_string_approximate,
    "list_exact": score_list_exact,
    "list_approximate": score_list_approximate,
    "boolean": score_boolean,
}


def grade(pred: str, gold: str, answer_type: str) -> bool:
    fn = SCORERS.get((answer_type or "").lower())
    if fn is None:
        # Unknown answer_type: fall back to string_approximate.
        return score_string_approximate(pred, gold)
    return fn(pred, gold)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True, help="Run output dir (results/<run>)")
    p.add_argument("--tasks", required=True, help="Original Krama tasks JSONL (with answer + answer_type)")
    args = p.parse_args()

    run_dir = Path(args.out)
    tasks = load_tasks(Path(args.tasks))
    rows: list[dict] = []

    for task_dir in sorted([d for d in run_dir.iterdir() if d.is_dir() and (d / "sessions").exists()]):
        tid = task_dir.name
        if tid not in tasks:
            continue
        t = tasks[tid]
        gold = str(t.get("answer", ""))
        atype = t.get("answer_type", "")
        pred = extract_pred_text(task_dir)
        ok = grade(pred, gold, atype)
        rows.append({
            "task_id": tid,
            "level": t.get("level", ""),
            "domain": t.get("domain", ""),
            "answer_type": atype,
            "gold": gold,
            "pred": pred,
            "correct": ok,
        })

    # Write CSV + JSON
    csv_path = run_dir / "results.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else ["task_id"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    (run_dir / "results.json").write_text(json.dumps(rows, indent=2))

    n_pass = sum(1 for r in rows if r["correct"])
    n = len(rows) or 1
    print(f"=== Results for {run_dir.name} ===")
    print(f"  pass rate: {n_pass}/{len(rows)}  ({100*n_pass/n:.0f}%)\n")
    print(f"{'task':<28} {'level':<4} {'gold':<28} {'pred':<28} ✓/✗")
    print("-" * 100)
    for r in rows:
        gold = (r["gold"][:24] + "...") if len(r["gold"]) > 27 else r["gold"]
        pred = (r["pred"][:24] + "...") if len(r["pred"]) > 27 else r["pred"]
        mark = "✓" if r["correct"] else "✗"
        print(f"{r['task_id']:<28} {r['level']:<4} {gold:<28} {pred:<28} {mark}")
    print(f"\nWrote {csv_path} and results.json")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
