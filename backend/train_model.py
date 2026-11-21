from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

import numpy as np

from .dataset_tools import (
    ARTIFACTS_DIR,
    DATASET_ROOT,
    PROJECT_ROOT,
    build_split_manifest,
    save_split_manifest,
)

IMAGE_SIZE = 224
ARCHITECTURES = ("MobileNetV2", "EfficientNetB0")


def _tensorflow():
    try:
        import tensorflow as tf
    except ImportError as error:
        raise RuntimeError(
            "TensorFlow is required. Install project requirements before training."
        ) from error
    return tf


def build_classifier(architecture: str, class_count: int, learning_rate: float = 1e-3):
    tf = _tensorflow()
    if architecture == "MobileNetV2":
        backbone = tf.keras.applications.MobileNetV2(
            include_top=False,
            weights="imagenet",
            input_shape=(IMAGE_SIZE, IMAGE_SIZE, 3),
        )
    elif architecture == "EfficientNetB0":
        backbone = tf.keras.applications.EfficientNetB0(
            include_top=False,
            weights="imagenet",
            input_shape=(IMAGE_SIZE, IMAGE_SIZE, 3),
        )
    else:
        raise ValueError(f"Unsupported architecture: {architecture}")

    backbone.trainable = False
    inputs = tf.keras.Input(shape=(IMAGE_SIZE, IMAGE_SIZE, 3))
    augmented = tf.keras.Sequential(
        [
            tf.keras.layers.RandomFlip("horizontal"),
            tf.keras.layers.RandomRotation(0.06),
            tf.keras.layers.RandomZoom(0.1),
            tf.keras.layers.RandomContrast(0.1),
        ],
        name="train_only_augmentation",
    )(inputs)
    if architecture == "MobileNetV2":
        prepared = tf.keras.applications.mobilenet_v2.preprocess_input(augmented)
    else:
        prepared = tf.keras.applications.efficientnet.preprocess_input(augmented)

    features = backbone(prepared, training=False)
    features = tf.keras.layers.GlobalAveragePooling2D()(features)
    features = tf.keras.layers.Dropout(0.3)(features)
    outputs = tf.keras.layers.Dense(
        class_count,
        activation="softmax",
        kernel_regularizer=tf.keras.regularizers.l2(1e-4),
    )(features)
    model = tf.keras.Model(inputs, outputs, name=f"{architecture}_ewaste")
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=learning_rate),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    return model, backbone


def _dataset_from_records(records: list[dict[str, Any]], batch_size: int, training: bool):
    tf = _tensorflow()
    paths = []
    for record in records:
        path = Path(record["path"])
        paths.append(str(path if path.is_absolute() else PROJECT_ROOT / path))
    labels = [record["label"] for record in records]
    dataset = tf.data.Dataset.from_tensor_slices((paths, labels))

    def load_image(path, label):
        image_bytes = tf.io.read_file(path)
        image = tf.io.decode_image(
            image_bytes, channels=3, expand_animations=False
        )
        image.set_shape((None, None, 3))
        image = tf.image.resize_with_pad(image, IMAGE_SIZE, IMAGE_SIZE)
        return tf.cast(image, tf.float32), label

    dataset = dataset.map(load_image, num_parallel_calls=tf.data.AUTOTUNE)
    if training:
        dataset = dataset.shuffle(
            min(len(records), 4096), reshuffle_each_iteration=True
        )
    return dataset.batch(batch_size).prefetch(tf.data.AUTOTUNE)


def _evaluate(
    model: Any,
    training_data,
    validation_data,
    class_names: list[str],
    output_dir: Path,
    architecture: str,
) -> dict[str, Any]:
    from sklearn.metrics import classification_report, confusion_matrix

    y_true: list[int] = []
    probabilities: list[np.ndarray] = []
    for images, labels in validation_data:
        probabilities.extend(np.asarray(model.predict(images, verbose=0)))
        y_true.extend(np.asarray(labels, dtype=int).tolist())

    scores = np.asarray(probabilities)
    predicted = scores.argmax(axis=1)
    report = classification_report(
        y_true,
        predicted,
        labels=list(range(len(class_names))),
        target_names=class_names,
        output_dict=True,
        zero_division=0,
    )
    training_metrics = model.evaluate(training_data, verbose=0, return_dict=True)

    threshold = 0.50

    output_dir.mkdir(parents=True, exist_ok=True)
    matrix = confusion_matrix(
        y_true, predicted, labels=list(range(len(class_names)))
    )
    np.savetxt(output_dir / f"{architecture}_confusion_matrix.csv", matrix, fmt="%d", delimiter=",")
    metrics = {
        "architecture": architecture,
        "training_accuracy": float(training_metrics["accuracy"]),
        "validation_accuracy": float(np.mean(predicted == np.asarray(y_true))),
        "validation_macro_f1": float(report["macro avg"]["f1-score"]),
        "per_class": {
            name: report[name] for name in class_names
        },
        "classification_report": report,
        "confusion_matrix": matrix.tolist(),
        "rejection_threshold": threshold,
        "threshold_selection": (
            "Fixed confidence threshold of 0.50 to reduce rejection of valid components; "
            "this is not an out-of-distribution validation."
        ),
        "independent_test_status": "pending_not_present",
    }
    (output_dir / f"{architecture}_validation_report.json").write_text(
        json.dumps(metrics, indent=2), encoding="utf-8"
    )
    (output_dir / "rejection_threshold.json").write_text(
        json.dumps({"threshold": threshold, "selection": metrics["threshold_selection"]}, indent=2),
        encoding="utf-8",
    )
    try:
        import matplotlib.pyplot as plt

        figure, axis = plt.subplots(figsize=(13, 11))
        image = axis.imshow(matrix, cmap="Greens")
        figure.colorbar(image, ax=axis)
        axis.set(
            xticks=range(len(class_names)),
            yticks=range(len(class_names)),
            xticklabels=class_names,
            yticklabels=class_names,
            xlabel="Predicted",
            ylabel="Actual",
            title=f"{architecture} validation confusion matrix",
        )
        plt.setp(axis.get_xticklabels(), rotation=90, ha="right")
        figure.tight_layout()
        figure.savefig(output_dir / f"{architecture}_confusion_matrix.png", dpi=150)
        plt.close(figure)
    except ImportError as error:
        raise RuntimeError("Matplotlib is required to save the confusion-matrix plot.") from error
    return metrics


def run_benchmark(
    architecture: str, batch_size: int = 8, steps: int = 3
) -> dict[str, Any]:
    tf = _tensorflow()
    model, _ = build_classifier(architecture, class_count=26)
    images = tf.random.uniform(
        (batch_size, IMAGE_SIZE, IMAGE_SIZE, 3), minval=0, maxval=255
    )
    labels = tf.random.uniform(
        (batch_size,), minval=0, maxval=26, dtype=tf.int32
    )
    model.train_on_batch(images, labels)
    model.predict(images, verbose=0)
    started = time.perf_counter()
    for _ in range(steps):
        model.train_on_batch(images, labels)
    elapsed = time.perf_counter() - started
    seconds_per_batch = elapsed / steps
    inference_started = time.perf_counter()
    for _ in range(steps):
        model.predict(images, verbose=0)
    inference_seconds = (time.perf_counter() - inference_started) / steps
    train_images = 26 * 112
    estimated_epoch_seconds = seconds_per_batch * math.ceil(train_images / batch_size)
    return {
        "architecture": architecture,
        "tensorflow_version": tf.__version__,
        "devices": [device.name for device in tf.config.list_physical_devices()],
        "batch_size": batch_size,
        "measured_steps": steps,
        "seconds_per_batch": seconds_per_batch,
        "images_per_second": batch_size / seconds_per_batch,
        "inference_seconds_per_image": inference_seconds / batch_size,
        "inference_images_per_second": batch_size / inference_seconds,
        "estimated_seconds_per_epoch": estimated_epoch_seconds,
        "estimate_scope": "model-only synthetic batches; excludes image loading and validation",
    }


def train_architecture(
    architecture: str,
    manifest: dict[str, Any],
    output_dir: Path,
    batch_size: int,
    head_epochs: int,
    fine_tune_epochs: int,
) -> dict[str, Any]:
    tf = _tensorflow()
    train_data = _dataset_from_records(manifest["train"], batch_size, True)
    validation_data = _dataset_from_records(manifest["validation"], batch_size, False)
    model, backbone = build_classifier(architecture, len(manifest["class_names"]))
    model_path = output_dir / f"{architecture}.keras"
    checkpoint = tf.keras.callbacks.ModelCheckpoint(
        model_path,
        monitor="val_accuracy",
        save_best_only=True,
        mode="max",
    )
    early_stop = tf.keras.callbacks.EarlyStopping(
        monitor="val_loss", patience=4, restore_best_weights=True
    )
    reduce_lr = tf.keras.callbacks.ReduceLROnPlateau(
        monitor="val_loss", factor=0.25, patience=2, min_lr=1e-6
    )
    head_history = model.fit(
        train_data,
        validation_data=validation_data,
        epochs=head_epochs,
        callbacks=[checkpoint, early_stop, reduce_lr],
    )
    initial_best = float(max(head_history.history.get("val_accuracy", [0.0])))

    backbone.trainable = True
    for layer in backbone.layers[:-30]:
        layer.trainable = False
    for layer in backbone.layers:
        if isinstance(layer, tf.keras.layers.BatchNormalization):
            layer.trainable = False
    fine_tune_checkpoint = tf.keras.callbacks.ModelCheckpoint(
        model_path,
        monitor="val_accuracy",
        save_best_only=True,
        mode="max",
        initial_value_threshold=initial_best,
    )
    model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-5),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    fine_tune_early_stop = tf.keras.callbacks.EarlyStopping(
        monitor="val_loss", patience=4, restore_best_weights=True
    )
    fine_tune_reduce_lr = tf.keras.callbacks.ReduceLROnPlateau(
        monitor="val_loss", factor=0.25, patience=2, min_lr=1e-7
    )
    model.fit(
        train_data,
        validation_data=validation_data,
        epochs=fine_tune_epochs,
        callbacks=[
            fine_tune_checkpoint,
            fine_tune_early_stop,
            fine_tune_reduce_lr,
        ],
    )

    best_model = tf.keras.models.load_model(model_path, compile=False)
    best_model.compile(
        optimizer=tf.keras.optimizers.Adam(learning_rate=1e-5),
        loss="sparse_categorical_crossentropy",
        metrics=["accuracy"],
    )
    metrics = _evaluate(
        best_model,
        train_data,
        validation_data,
        manifest["class_names"],
        output_dir,
        architecture,
    )
    return {"model_path": str(model_path), "metrics": metrics}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and compare transfer-learning models.")
    parser.add_argument(
        "--architecture", choices=(*ARCHITECTURES, "compare"), default="compare"
    )
    parser.add_argument("--benchmark", action="store_true")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--benchmark-steps", type=int, default=3)
    parser.add_argument("--head-epochs", type=int, default=10)
    parser.add_argument("--fine-tune-epochs", type=int, default=12)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--dataset-root", type=Path, default=DATASET_ROOT)
    parser.add_argument("--output-dir", type=Path, default=ARTIFACTS_DIR)
    args = parser.parse_args()

    tf = _tensorflow()
    tf.keras.utils.set_random_seed(args.seed)
    architectures = ARCHITECTURES if args.architecture == "compare" else (args.architecture,)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.benchmark:
        results = [
            run_benchmark(architecture, args.batch_size, args.benchmark_steps)
            for architecture in architectures
        ]
        (args.output_dir / "cpu_benchmark.json").write_text(
            json.dumps(results, indent=2), encoding="utf-8"
        )
        print(json.dumps(results, indent=2))
        return

    manifest = build_split_manifest(dataset_root=args.dataset_root, seed=args.seed)
    save_split_manifest(manifest, args.output_dir / "split_manifest.json")
    (args.output_dir / "class_names.json").write_text(
        json.dumps(manifest["class_names"], indent=2), encoding="utf-8"
    )
    class_indices = {
        str(label): class_name
        for label, class_name in enumerate(manifest["class_names"])
    }
    (args.output_dir / "class_indices.json").write_text(
        json.dumps(class_indices, indent=2), encoding="utf-8"
    )
    results = [
        train_architecture(
            architecture,
            manifest,
            args.output_dir,
            args.batch_size,
            args.head_epochs,
            args.fine_tune_epochs,
        )
        for architecture in architectures
    ]
    best = max(
        results,
        key=lambda item: item["metrics"]["validation_macro_f1"],
    )
    best_path = Path(best["model_path"])
    destination = args.output_dir / "best_ewaste_model.keras"
    if best_path != destination:
        import shutil

        shutil.copyfile(best_path, destination)
    (args.output_dir / "rejection_threshold.json").write_text(
        json.dumps(
            {
                "threshold": best["metrics"]["rejection_threshold"],
                "selection": best["metrics"]["threshold_selection"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
