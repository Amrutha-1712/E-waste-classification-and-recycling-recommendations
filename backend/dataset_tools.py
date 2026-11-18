from __future__ import annotations

import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_ROOT = (
    PROJECT_ROOT
    / "dataset"
    / "Laptop Components Image Dataset to Classify Different Components"
)
INDEPENDENT_TEST_ROOT = PROJECT_ROOT / "dataset" / "independent_test"
ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


class DatasetError(RuntimeError):
    pass


def _project_relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path.resolve())


def _class_sort_key(path: Path) -> tuple[int, str]:
    match = re.match(r"(\d+)\.\s*(.*)", path.name)
    if match:
        return int(match.group(1)), match.group(2).casefold()
    return 9999, path.name.casefold()


def resolve_split_root(dataset_root: Path, split_name: str) -> Path:
    outer = dataset_root / split_name
    nested = outer / split_name
    root = nested if nested.is_dir() else outer
    if not root.is_dir():
        raise DatasetError(f"Dataset split directory was not found: {outer}")
    return root


def class_name_from_folder(folder: Path) -> str:
    match = re.match(r"\d+\.\s*(.+)", folder.name)
    return match.group(1).strip() if match else folder.name.strip()


def _image_files(class_dir: Path) -> list[Path]:
    return sorted(
        path for path in class_dir.iterdir()
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def inspect_dataset(dataset_root: Path = DATASET_ROOT) -> dict[str, Any]:
    raw_root = resolve_split_root(dataset_root, "Raw Data")
    augmented_root = resolve_split_root(dataset_root, "Augmented Data")
    class_dirs = sorted(
        (path for path in raw_root.iterdir() if path.is_dir()), key=_class_sort_key
    )
    augmented_class_names = {
        path.name for path in augmented_root.iterdir() if path.is_dir()
    }
    raw_class_names = {path.name for path in class_dirs}
    if not class_dirs:
        raise DatasetError(f"No component class folders were found in {raw_root}")

    report: dict[str, Any] = {
        "dataset_root": str(dataset_root),
        "classes": [],
        "split_totals": {"raw": 0, "augmented": 0},
        "dimensions": {},
        "corrupt_images": [],
        "exact_duplicates": [],
        "raw_classes_missing_from_augmented": sorted(
            raw_class_names - augmented_class_names
        ),
        "augmented_classes_missing_from_raw": sorted(
            augmented_class_names - raw_class_names
        ),
    }
    digest_paths: dict[str, list[str]] = defaultdict(list)

    for class_dir in class_dirs:
        display_name = class_name_from_folder(class_dir)
        class_report: dict[str, Any] = {"name": display_name}
        for split, root in (("raw", raw_root), ("augmented", augmented_root)):
            split_class_dir = root / class_dir.name
            files = _image_files(split_class_dir) if split_class_dir.is_dir() else []
            class_report[split] = len(files)
            report["split_totals"][split] += len(files)
            for path in files:
                try:
                    with Image.open(path) as image:
                        image_format = image.format or "unknown"
                        dimensions = f"{image.width}x{image.height}"
                        image.verify()
                    report["dimensions"].setdefault(
                        f"{split}:{image_format}:{dimensions}", 0
                    )
                    report["dimensions"][f"{split}:{image_format}:{dimensions}"] += 1
                    digest = _sha256(path)
                    digest_paths[digest].append(_project_relative_path(path))
                except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
                    report["corrupt_images"].append(
                        {
                            "path": _project_relative_path(path),
                            "error": type(error).__name__,
                        }
                    )
        report["classes"].append(class_report)

    report["class_count"] = len(class_dirs)
    report["image_total"] = sum(report["split_totals"].values())
    report["exact_duplicates"] = [
        paths for paths in digest_paths.values() if len(paths) > 1
    ]
    return report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_split_manifest(
    dataset_root: Path = DATASET_ROOT,
    validation_fraction: float = 0.2,
    seed: int = 42,
) -> dict[str, Any]:
    if not 0.0 < validation_fraction < 1.0:
        raise ValueError("validation_fraction must be between 0 and 1.")

    raw_root = resolve_split_root(dataset_root, "Raw Data")
    class_dirs = sorted(
        (path for path in raw_root.iterdir() if path.is_dir()), key=_class_sort_key
    )
    if not class_dirs:
        raise DatasetError(f"No component class folders were found in {raw_root}")

    classes = [class_name_from_folder(folder) for folder in class_dirs]
    train: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    rng = random.Random(seed)
    digest_labels: dict[str, str] = {}

    for label, class_dir in enumerate(class_dirs):
        files = _image_files(class_dir)
        if len(files) < 2:
            raise DatasetError(
                f"Class {class_name_from_folder(class_dir)} needs at least two raw images."
            )

        groups: dict[str, list[Path]] = defaultdict(list)
        for path in files:
            try:
                with Image.open(path) as image:
                    image.verify()
            except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
                raise DatasetError(f"Invalid source image {path}: {error}") from error
            digest = _sha256(path)
            prior_label = digest_labels.setdefault(digest, classes[label])
            if prior_label != classes[label]:
                raise DatasetError(
                    f"An identical image is labeled as both {prior_label} and "
                    f"{classes[label]}; review {path} before training."
                )
            groups[digest].append(path)

        rng.shuffle(groups_list := list(groups.values()))
        validation_group_count = max(
            1, min(len(groups_list) - 1, round(len(groups_list) * validation_fraction))
        )
        validation_groups = groups_list[:validation_group_count]
        train_groups = groups_list[validation_group_count:]
        for target, selected_groups in (
            (validation, validation_groups),
            (train, train_groups),
        ):
            for group in selected_groups:
                target.extend(
                    {
                        "path": _project_relative_path(path),
                        "label": label,
                        "class_name": classes[label],
                    }
                    for path in group
                )

    rng.shuffle(train)
    rng.shuffle(validation)
    return {
        "seed": seed,
        "validation_fraction": validation_fraction,
        "class_names": classes,
        "train": train,
        "validation": validation,
        "counts": {
            "train": Counter(item["class_name"] for item in train),
            "validation": Counter(item["class_name"] for item in validation),
        },
        "independent_test_root": str(INDEPENDENT_TEST_ROOT),
        "independent_test_status": "pending_not_present",
        "augmented_data_policy": "excluded; train-only online augmentation is used",
    }


def save_split_manifest(manifest: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serializable = dict(manifest)
    serializable["counts"] = {
        split: dict(counts) for split, counts in manifest["counts"].items()
    }
    output_path.write_text(
        json.dumps(serializable, indent=2), encoding="utf-8"
    )
