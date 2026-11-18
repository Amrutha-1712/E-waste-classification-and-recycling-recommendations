from __future__ import annotations

import argparse
import json
from pathlib import Path

from .dataset_tools import ARTIFACTS_DIR, DATASET_ROOT, inspect_dataset


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect dataset classes, image formats, dimensions, corruption, and exact duplicates."
    )
    parser.add_argument("--dataset-root", type=Path, default=DATASET_ROOT)
    parser.add_argument(
        "--report",
        type=Path,
        default=ARTIFACTS_DIR / "dataset_audit.json",
    )
    args = parser.parse_args()

    report = inspect_dataset(args.dataset_root)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
