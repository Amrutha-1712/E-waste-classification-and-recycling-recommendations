from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from .dataset_tools import (
    ARTIFACTS_DIR,
    INDEPENDENT_TEST_ROOT,
    PROJECT_ROOT,
    class_name_from_folder,
)
from .model_service import ModelUnavailableError, get_classifier

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as image_file:
        for chunk in iter(lambda: image_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluate(test_root: Path, output_dir: Path = ARTIFACTS_DIR / "independent_test") -> dict[str, Any]:
    from sklearn.metrics import classification_report, confusion_matrix
    import tensorflow as tf

    if not test_root.is_dir():
        raise FileNotFoundError(
            f"Independent test data is not present at {test_root}; evaluation remains pending."
        )

    class_dirs = sorted(path for path in test_root.iterdir() if path.is_dir())
    if not class_dirs:
        raise ValueError(f"No class folders found in independent dataset: {test_root}")

    classifier = get_classifier()
    class_to_index = {name: index for index, name in enumerate(classifier.class_names)}
    manifest_path = ARTIFACTS_DIR / "split_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            "The training split manifest is missing; overlap with training data cannot be checked."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    training_digests = {
        _sha256(PROJECT_ROOT / record["path"])
        for split in ("train", "validation")
        for record in manifest[split]
    }

    y_true: list[int] = []
    y_pred: list[int] = []
    confidences: list[float] = []
    class_counts: Counter[str] = Counter()
    overlaps: list[str] = []
    duplicate_test_images: list[tuple[str, str]] = []
    errors: list[str] = []
    seen_classes: set[str] = set()
    seen_test_digests: dict[str, str] = {}

    for class_dir in class_dirs:
        component = class_name_from_folder(class_dir)
        if component not in class_to_index:
            errors.append(f"Unmapped test class folder: {class_dir.name}")
            continue
        seen_classes.add(component)
        files = sorted(
            path for path in class_dir.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        )
        for path in files:
            try:
                digest = _sha256(path)
                if digest in training_digests:
                    overlaps.append(str(path))
                    continue
                previous_path = seen_test_digests.setdefault(digest, str(path))
                if previous_path != str(path):
                    duplicate_test_images.append((previous_path, str(path)))
                    continue
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    input_image = tf.image.resize_with_pad(
                        np.asarray(image.convert("RGB"), dtype=np.float32), 224, 224
                    ).numpy()
            except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
                errors.append(f"Invalid image {path}: {type(error).__name__}")
                continue
            scores = np.asarray(
                classifier.model.predict(input_image[None, ...], verbose=0)
            )[0]
            y_true.append(class_to_index[component])
            y_pred.append(int(np.argmax(scores)))
            confidences.append(float(np.max(scores)))
            class_counts[component] += 1

    if errors:
        raise ValueError("Independent dataset validation failed:\n" + "\n".join(errors))
    if overlaps:
        raise ValueError(
            "Independent test images overlap training/validation data by exact content:\n"
            + "\n".join(overlaps[:20])
        )
    if duplicate_test_images:
        raise ValueError(
            "Independent test data contains exact duplicate files:\n"
            + "\n".join(f"{first} == {second}" for first, second in duplicate_test_images[:20])
        )
    if not y_true:
        raise ValueError("No valid independent test images were evaluated.")

    labels = list(range(len(classifier.class_names)))
    report = classification_report(
        y_true,
        y_pred,
        labels=labels,
        target_names=classifier.class_names,
        output_dict=True,
        zero_division=0,
    )
    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    rejected = sum(
        confidence < classifier.rejection_threshold for confidence in confidences
    )
    result = {
        "status": "evaluated_independent_test",
        "images_tested": len(y_true),
        "correct": int(np.sum(np.asarray(y_true) == np.asarray(y_pred))),
        "incorrect": int(np.sum(np.asarray(y_true) != np.asarray(y_pred))),
        "top1_accuracy": float(np.mean(np.asarray(y_true) == np.asarray(y_pred))),
        "rejected_by_validation_threshold": rejected,
        "class_counts": dict(class_counts),
        "classes_missing_from_test_set": sorted(
            set(classifier.class_names) - seen_classes
        ),
        "per_class": {name: report[name] for name in classifier.class_names},
        "classification_report": report,
        "confusion_matrix": matrix.tolist(),
        "independent_test_root": str(test_root),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "independent_test_report.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    with (output_dir / "independent_test_confusion_matrix.csv").open(
        "w", newline="", encoding="utf-8"
    ) as output_file:
        writer = csv.writer(output_file)
        writer.writerow(["actual/predicted", *classifier.class_names])
        for name, row in zip(classifier.class_names, matrix):
            writer.writerow([name, *row.tolist()])
    import matplotlib.pyplot as plt

    figure, axis = plt.subplots(figsize=(13, 11))
    image = axis.imshow(matrix, cmap="Greens")
    figure.colorbar(image, ax=axis)
    axis.set(
        xticks=labels,
        yticks=labels,
        xticklabels=classifier.class_names,
        yticklabels=classifier.class_names,
        xlabel="Predicted",
        ylabel="Actual",
        title="Independent test confusion matrix",
    )
    plt.setp(axis.get_xticklabels(), rotation=90, ha="right")
    figure.tight_layout()
    figure.savefig(output_dir / "independent_test_confusion_matrix.png", dpi=150)
    plt.close(figure)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate the finalized model on a separate independent dataset."
    )
    parser.add_argument("--test-dir", type=Path, default=INDEPENDENT_TEST_ROOT)
    parser.add_argument(
        "--output-dir", type=Path, default=ARTIFACTS_DIR / "independent_test"
    )
    args = parser.parse_args()
    try:
        result = evaluate(args.test_dir, args.output_dir)
    except (FileNotFoundError, ValueError, ModelUnavailableError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
