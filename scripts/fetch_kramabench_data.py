"""Fetch KramaBench workload + data lake into data/kramabench/.

Uses a sparse git clone of mitdbg/Kramabench so we only pull the domains we
ask for (data lake is 1.7 GB total; archaeology alone is 7.5 MB).

Examples:
  # Just the workload JSON for all 6 domains (~7 MB):
  python3 scripts/fetch_kramabench_data.py --workload-only

  # Workload + archeology data lake (7.5 MB lake):
  python3 scripts/fetch_kramabench_data.py --domains archeology

  # Multiple domains:
  python3 scripts/fetch_kramabench_data.py --domains archeology legal

  # Everything (1.7 GB):
  python3 scripts/fetch_kramabench_data.py --all

Layout after fetch (relative to repo root):
  data/kramabench/
    workload/
      archeology.json       # all 12 archaeology tasks
      astronomy.json
      biomedical.json
      environment.json
      legal.json
      wildfire.json
    data/
      archeology/           # data lake for archaeology
        *.csv, *.xlsx, ...
      legal/
        *.csv, ...
      ...                   # only the domains you asked for
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KRAMA_ROOT = ROOT / "data" / "kramabench"
REPO_URL = "https://github.com/mitdbg/Kramabench.git"
DOMAINS = ("archeology", "astronomy", "biomedical", "environment", "legal", "wildfire")


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def sparse_checkout(target: Path, paths: list[str]) -> None:
    """git sparse-checkout into `target`, pulling only the given path prefixes."""
    target.mkdir(parents=True, exist_ok=True)
    if not (target / ".git").exists():
        run(["git", "init"], cwd=target)
        run(["git", "remote", "add", "origin", REPO_URL], cwd=target)
        run(["git", "config", "core.sparseCheckout", "true"], cwd=target)

    sparse_file = target / ".git" / "info" / "sparse-checkout"
    sparse_file.parent.mkdir(parents=True, exist_ok=True)
    sparse_file.write_text("\n".join(paths) + "\n")

    # Pull main, depth=1 to keep size small.
    run(["git", "fetch", "--depth", "1", "origin", "main"], cwd=target)
    run(["git", "checkout", "main"], cwd=target)


def install(target_workload: Path, target_data: Path, domains: list[str], workload_only: bool) -> None:
    # Clone into a temp dir adjacent to KRAMA_ROOT so we can move pieces in.
    work = KRAMA_ROOT / ".clone"
    if work.exists():
        shutil.rmtree(work)

    paths = ["workload/"]
    if not workload_only:
        for d in domains:
            paths.append(f"data/{d}/")

    sparse_checkout(work, paths)

    # Copy workload JSONs over.
    target_workload.mkdir(parents=True, exist_ok=True)
    src_workload = work / "workload"
    if src_workload.exists():
        for f in src_workload.iterdir():
            if f.suffix == ".json":
                shutil.copy(f, target_workload / f.name)

    if not workload_only:
        target_data.mkdir(parents=True, exist_ok=True)
        src_data = work / "data"
        for d in domains:
            src = src_data / d
            if src.exists() and src.is_dir():
                dst = target_data / d
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)

    # Don't keep the .clone — saves disk and avoids accidental nested git.
    shutil.rmtree(work)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--domains", nargs="+", default=[],
                   help=f"Domains to fetch data lakes for. Choices: {', '.join(DOMAINS)}")
    p.add_argument("--all", action="store_true", help="Fetch all 6 domains (~1.7 GB).")
    p.add_argument("--workload-only", action="store_true",
                   help="Fetch only the workload JSON files; skip data lakes.")
    p.add_argument("--out", default=str(KRAMA_ROOT),
                   help=f"Output root directory (default: {KRAMA_ROOT})")
    args = p.parse_args()

    out_root = Path(args.out)
    workload_dir = out_root / "workload"
    data_dir = out_root / "data"

    if args.all:
        domains = list(DOMAINS)
    else:
        domains = args.domains
    for d in domains:
        if d not in DOMAINS:
            print(f"ERROR: unknown domain '{d}'. Choices: {', '.join(DOMAINS)}", file=sys.stderr)
            return 2

    if not args.workload_only and not domains:
        print("Neither --workload-only nor --domains/--all given. Defaulting to --workload-only.")
        args.workload_only = True

    print(f"Out:      {out_root}")
    print(f"Workload: {workload_dir}")
    if not args.workload_only:
        print(f"Lakes:    {data_dir} (domains: {', '.join(domains)})")
    else:
        print(f"Lakes:    skipped")

    install(workload_dir, data_dir, domains, args.workload_only)

    # Summary
    n_workload = len(list(workload_dir.glob("*.json"))) if workload_dir.exists() else 0
    print(f"\nDone. {n_workload} workload JSON(s) in {workload_dir}.")
    if not args.workload_only:
        for d in domains:
            ddir = data_dir / d
            if ddir.exists():
                n_files = sum(1 for _ in ddir.rglob("*") if _.is_file())
                size_mb = sum(p.stat().st_size for p in ddir.rglob("*") if p.is_file()) / 1e6
                print(f"  {d}: {n_files} files, {size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
