"""Validate a DAB submission JSON end-to-end and compute the official stratified
Pass@1: (1/D) * sum_datasets [ (1/Q_d) * sum_queries (passes / n_trials) ].

Each cell {dataset, query, run, answer} is validated against the official
query_<dataset>/query<query>/validate.py from the DAB clone.
"""
from __future__ import annotations
import argparse, importlib.util, json, sys
from collections import defaultdict
from pathlib import Path

DAB_ROOT = Path("/private/tmp/dab_clone")

_cache: dict = {}
def load_validator(dataset: str, query: str):
    key = (dataset, query)
    if key in _cache:
        return _cache[key]
    vpath = DAB_ROOT / f"query_{dataset}" / f"query{query}" / "validate.py"
    if not vpath.exists():
        raise FileNotFoundError(f"validate.py not found: {vpath}")
    if str(DAB_ROOT) not in sys.path:
        sys.path.insert(0, str(DAB_ROOT))
    spec = importlib.util.spec_from_file_location(f"dab_val_{dataset}_{query}", vpath)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _cache[key] = mod.validate
    return mod.validate


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--submission", required=True)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    cells = json.load(open(args.submission))
    # group passes per (dataset, query)
    qstats = defaultdict(lambda: {"pass": 0, "n": 0})
    failures = []
    for c in cells:
        ds, q = c["dataset"], str(c["query"])
        ans = (c.get("answer") or "").strip()
        try:
            ok, reason = load_validator(ds, q)(ans)
        except Exception as e:
            ok, reason = False, f"validator raised: {e}"
        qstats[(ds, q)]["n"] += 1
        qstats[(ds, q)]["pass"] += int(bool(ok))
        if not ok:
            failures.append((ds, q, c["run"], reason[:80]))

    # stratify: per-query rate -> per-dataset mean -> dataset mean
    ds_to_qrates = defaultdict(list)
    for (ds, q), s in qstats.items():
        ds_to_qrates[ds].append(s["pass"] / s["n"] if s["n"] else 0.0)
    per_ds = {ds: sum(rs) / len(rs) for ds, rs in ds_to_qrates.items()}
    stratified = sum(per_ds.values()) / len(per_ds) if per_ds else 0.0

    print(f"\n=== Per-dataset Pass@1 ({len(per_ds)} datasets) ===")
    for ds in sorted(per_ds):
        print(f"  {ds:18s} {per_ds[ds]:.4f}")
    print(f"\n  STRATIFIED Pass@1 = {stratified:.4f}")
    print(f"  cells validated   = {len(cells)}, failing cells = {len(failures)}")

    out = {"stratified_pass_at_1": stratified, "per_dataset": per_ds,
           "n_cells": len(cells), "n_fail_cells": len(failures),
           "qstats": {f"{d}|{q}": s for (d, q), s in qstats.items()}}
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2))
        print(f"  wrote {args.out}")


if __name__ == "__main__":
    main()
