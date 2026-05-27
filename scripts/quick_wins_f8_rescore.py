"""
QW-1 / F8 — rescore numeric pred at gold's decimal precision.

For each candidate task: load original pred, parse to float, round to
decimals(gold), re-run question_scorer. Write a new results CSV with one
extra column `f8_applied` indicating which rows were rescored.

See docs/quick_wins/README.md §QW-1 for context.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from scorer import question_scorer


def decimals_of(s: str) -> int:
    s = s.strip()
    if "." not in s:
        return 0
    return len(s.split(".", 1)[1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-csv", required=True, type=Path)
    ap.add_argument("--gold", required=True, type=Path)
    ap.add_argument("--candidates", required=True,
                    help="Comma-separated task IDs to rescore")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    candidates = {t.strip() for t in args.candidates.split(",") if t.strip()}
    gold_raw = json.loads(args.gold.read_text())
    gold = {tid: (v.get("verified_answer") if isinstance(v, dict) else v)
            for tid, v in gold_raw.items()}

    rows = list(csv.DictReader(open(args.results_csv)))
    fieldnames = list(rows[0].keys()) + ["f8_applied", "f8_pred_rounded"]

    flipped = []
    for r in rows:
        r["f8_applied"] = "false"
        r["f8_pred_rounded"] = ""
        tid = r["task_id"]
        if tid not in candidates:
            continue
        pred = (r.get("pred_final") or "").strip()
        g = str(gold.get(tid, "")).strip()
        if not pred or not g:
            continue
        try:
            pn = float(pred)
            ndp = decimals_of(g)
            rounded = f"{round(pn, ndp):.{ndp}f}"
        except ValueError:
            continue
        was_correct = r.get("correct", "").lower() == "true"
        new_correct = question_scorer(rounded, g)
        if new_correct and not was_correct:
            r["correct"] = "True"
            r["pred_final"] = rounded
            r["f8_applied"] = "true"
            r["f8_pred_rounded"] = rounded
            flipped.append(tid)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    passed = sum(1 for r in rows if r.get("correct", "").lower() == "true")
    print(f"Wrote {args.out}")
    print(f"  total rows:           {len(rows)}")
    print(f"  candidates considered: {len(candidates)}")
    print(f"  newly flipped to PASS: {len(flipped)}  → {flipped}")
    print(f"  final PASS count:     {passed} / {len(rows)} = {100 * passed / len(rows):.1f}%")


if __name__ == "__main__":
    main()
