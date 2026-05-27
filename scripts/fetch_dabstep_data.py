"""
SCRIBE — fetch DABStep context files + verified_answers from Hugging Face.

DABStep (Apache 2.0) is hosted at https://huggingface.co/datasets/adyen/DABstep.
We don't redistribute the raw data files in this repo; instead we download them
on demand into data/context/ and data/verified_answers.json.

Required by the executor:
  data/context/manual.md
  data/context/fees.json
  data/context/payments.csv             (~50 MB)
  data/context/merchant_data.json
  data/context/merchant_category_codes.csv
  data/context/acquirer_countries.csv
  data/context/payments-readme.md
  data/verified_answers.json
"""
import shutil
import sys
from pathlib import Path

try:
    from huggingface_hub import snapshot_download
except ImportError:
    print("Missing dependency: pip install huggingface_hub", file=sys.stderr)
    sys.exit(1)

REPO_ROOT = Path(__file__).resolve().parent.parent
DST_CONTEXT = REPO_ROOT / "data" / "context"
DST_GOLD = REPO_ROOT / "data" / "verified_answers.json"


def main():
    DST_CONTEXT.mkdir(parents=True, exist_ok=True)
    print(f"Downloading DABStep context files into {DST_CONTEXT}...")

    cache_dir = snapshot_download(
        repo_id="adyen/DABstep",
        repo_type="dataset",
        allow_patterns=[
            "data/context/*",
            "verified_answers.json",
        ],
    )

    src_context = Path(cache_dir) / "data" / "context"
    if src_context.exists():
        for src in src_context.iterdir():
            if src.is_file():
                shutil.copy(src, DST_CONTEXT / src.name)
                print(f"  + {src.name} ({src.stat().st_size:,} bytes)")
    else:
        print(f"  WARN: expected {src_context} not found in HF cache", file=sys.stderr)

    src_gold = Path(cache_dir) / "verified_answers.json"
    if src_gold.exists():
        shutil.copy(src_gold, DST_GOLD)
        print(f"  + verified_answers.json -> {DST_GOLD}")

    listed = sorted(p.name for p in DST_CONTEXT.iterdir() if p.is_file())
    print(f"\nDone. Context files now in {DST_CONTEXT}:")
    for name in listed:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
