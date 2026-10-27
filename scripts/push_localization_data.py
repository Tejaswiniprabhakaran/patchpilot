"""Upload the built localization dataset and its card to the Hugging Face Hub.

The Kaggle notebook (notebooks/01_fault_localization.ipynb) downloads it from there.
Authentication uses your own Hugging Face login (run `huggingface-cli login` once, or set
HF_TOKEN in your shell); this script never asks for or stores a token.

Usage:
    python scripts/push_localization_data.py --repo <hf-username>/patchpilot-localization
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

DATA = Path("data/processed/localization")
CARD = Path("docs/dataset_cards/localization.md")
FILES = ["train.jsonl.gz", "val.jsonl.gz", "test.jsonl.gz"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="<hf-username>/patchpilot-localization")
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()

    missing = [f for f in FILES if not (DATA / f).exists()]
    if missing:
        raise SystemExit(f"build the dataset first; missing {missing} in {DATA}")

    from huggingface_hub import HfApi

    api = HfApi()
    api.create_repo(args.repo, repo_type="dataset", private=args.private, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name in FILES:
            shutil.copy(DATA / name, Path(tmp) / name)
        shutil.copy(CARD, Path(tmp) / "README.md")
        shutil.copy("results/localization/dataset_stats.json", Path(tmp) / "dataset_stats.json")
        shutil.copy("results/leakage_check.json", Path(tmp) / "leakage_check.json")
        api.upload_folder(
            folder_path=tmp,
            repo_id=args.repo,
            repo_type="dataset",
            commit_message="PatchPilot fault-localization dataset",
        )
    print(f"uploaded to https://huggingface.co/datasets/{args.repo}")


if __name__ == "__main__":
    main()
