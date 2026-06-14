"""Build a cost-vs-accuracy table for the executor-swap ablation.

Reads each arm's summary.json (which now carries per-model token/cost fields),
validates answers against the official DAB validators (stratified Pass@1),
adds the shared one-time Opus spec-extraction cost, and prints a comparison.

Usage:
  python3 scripts/ablation_cost_accuracy.py \
      --arm "Opus-all:results/abl_opus_all/summary.json" \
      --arm "Kimi-exec+Opus-planner:results/abl_kimi_opus/summary.json" \
      --specs results/dab_final_specs
"""
from __future__ import annotations
import argparse, glob, importlib.util, json, sys
from collections import defaultdict
from pathlib import Path

DAB = Path("/Users/suraj/dab_clone")
_vc: dict = {}
def validator(ds, q):
    if (ds, q) in _vc: return _vc[(ds, q)]
    sys.path.insert(0, str(DAB))
    vp = DAB / f"query_{ds}" / f"query{q}" / "validate.py"
    spec = importlib.util.spec_from_file_location(f"v_{ds}_{q}", vp)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    _vc[(ds, q)] = m.validate; return m.validate

def stratified(rows):
    qstat = defaultdict(lambda: [0, 0])
    for r in rows:
        tid = r["task_id"]; ds, q = tid.rsplit("-q", 1)
        ans = (r.get("final_answer") or "").strip()
        try: ok = bool(validator(ds, q)(ans)[0])
        except Exception: ok = False
        qstat[(ds, q)][0] += int(ok); qstat[(ds, q)][1] += 1
    ds_rates = defaultdict(list)
    for (ds, q), (p, n) in qstat.items():
        ds_rates[ds].append(p / n if n else 0)
    per_ds = {d: sum(v)/len(v) for d, v in ds_rates.items()}
    strat = sum(per_ds.values())/len(per_ds) if per_ds else 0.0
    npass = sum(p for p, n in qstat.values()); ntot = sum(n for p, n in qstat.values())
    return strat, per_ds, npass, ntot

def spec_cost(specs_dir):
    ti = to = 0
    for f in glob.glob(f"{specs_dir}/*.json"):
        if any(x in f for x in ["session", "original", ".rev"]): continue
        m = json.load(open(f)).get("_meta", {})
        ti += m.get("input_tokens", 0); to += m.get("output_tokens", 0)
    return ti/1e6*5 + to/1e6*25, ti, to  # Opus $5/$25

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", action="append", required=True, help="label:path/to/summary.json")
    ap.add_argument("--specs", required=True)
    args = ap.parse_args()

    sc, sti, sto = spec_cost(args.specs)
    print(f"\nShared spec-extraction (Opus 4.7): {sti:,} in / {sto:,} out  =  ${sc:.2f}\n")

    rows_out = []
    for arm in args.arm:
        label, path = arm.split(":", 1)
        rows = json.load(open(path))
        strat, per_ds, npass, ntot = stratified(rows)
        exec_cost = sum(r.get("executor_cost_usd", 0) for r in rows)
        plan_cost = sum(r.get("planner_cost_usd", 0) for r in rows)
        exec_in = sum(r.get("executor_input_tokens", 0) for r in rows)
        exec_out = sum(r.get("executor_output_tokens", 0) for r in rows)
        plan_in = sum(r.get("planner_input_tokens", 0) for r in rows)
        plan_out = sum(r.get("planner_output_tokens", 0) for r in rows)
        wall = sum(r.get("wall_seconds", 0) for r in rows)
        run_cost = exec_cost + plan_cost
        total = run_cost + sc
        rows_out.append(dict(label=label, strat=strat, exec_cost=exec_cost, plan_cost=plan_cost,
                             run_cost=run_cost, total=total, wall=wall, per_ds=per_ds,
                             npass=npass, ntot=ntot, exec_in=exec_in, exec_out=exec_out,
                             plan_in=plan_in, plan_out=plan_out, n=len(rows)))

    print(f"{'Config':32s} {'Pass@1':>8s} {'exec$':>8s} {'review$':>8s} {'run$':>8s} {'+spec$':>8s} {'total$':>8s} {'$/task':>7s} {'min':>6s}")
    print("-"*110)
    for r in rows_out:
        print(f"{r['label']:32s} {r['strat']:>8.4f} {r['exec_cost']:>8.2f} {r['plan_cost']:>8.2f} "
              f"{r['run_cost']:>8.2f} {r['total']:>8.2f} {r['total']:>8.2f} "
              f"{r['total']/max(1,r['n']):>7.3f} {r['wall']/60:>6.1f}")
    print("-"*110)
    # accuracy per $ (run cost)
    for r in rows_out:
        eff = r['strat']/r['run_cost'] if r['run_cost'] else 0
        print(f"  {r['label']:30s}  Pass@1={r['strat']:.4f} ({r['npass']}/{r['ntot']} trials)  "
              f"exec {r['exec_in']:,}/{r['exec_out']:,}tok  review {r['plan_in']:,}/{r['plan_out']:,}tok  "
              f"acc/run$={eff:.4f}")
    # per-dataset deltas if exactly 2 arms
    if len(rows_out) == 2:
        a, b = rows_out
        print(f"\nPer-dataset Pass@1 ({a['label']} vs {b['label']}):")
        for ds in sorted(set(a['per_ds']) | set(b['per_ds'])):
            va = a['per_ds'].get(ds, 0); vb = b['per_ds'].get(ds, 0)
            flag = "" if abs(va-vb) < 1e-9 else ("  <-- "+(a['label'] if va>vb else b['label']))
            print(f"  {ds:18s} {va:.3f}   {vb:.3f}{flag}")

if __name__ == "__main__":
    main()
