from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np
from PIL import Image


ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_PATH = ARTIFACTS_DIR / "model.keras"
CLASS_NAMES_PATH = ARTIFACTS_DIR / "class_names.json"
THRESHOLD_PATH = ARTIFACTS_DIR / "rejection_threshold.json"
UNKNOWN_LABEL = "Unknown or Unrecognized Component"

_lock = Lock()
_classifier: "Classifier | None" = None


class ModelUnavailableError(RuntimeError):
    pass


class Classifier:
    def __init__(
        self, model: Any, class_names: list[str], rejection_threshold: float
    ) -> None:
        self.model = model
        self.class_names = class_names
        self.rejection_threshold = rejection_threshold

    def predict(self, image: Image.Image) -> dict[str, Any]:
        import tensorflow as tf

        resized = tf.image.resize_with_pad(
            np.asarray(image.convert("RGB"), dtype=np.float32), 224, 224
        ).numpy()
        scores = np.asarray(self.model.predict(resized[None, ...], verbose=0))[0]
        if scores.ndim != 1 or len(scores) != len(self.class_names):
            raise ModelUnavailableError("The model output does not match its class mapping.")

        index = int(np.argmax(scores))
        confidence = float(scores[index])
        is_known = confidence >= self.rejection_threshold
        return {
            "component": self.class_names[index] if is_known else UNKNOWN_LABEL,
            "predicted_component": self.class_names[index],
            "confidence": confidence,
            "classification_status": "classified" if is_known else "unknown",
            "recommendation": None,
        }


def get_classifier() -> Classifier:
    global _classifier
    if _classifier is not None:
        return _classifier

    with _lock:
        if _classifier is not None:
            return _classifier

        missing = [
            path.name for path in (MODEL_PATH, CLASS_NAMES_PATH, THRESHOLD_PATH)
            if not path.is_file()
        ]
        if missing:
            raise ModelUnavailableError(
                "A trained model is not available. Missing artifacts: "
                + ", ".join(missing)
                + ". Run the documented training command first."
            )

        try:
            import tensorflow as tf

            model = tf.keras.models.load_model(MODEL_PATH, compile=False)
            class_names = json.loads(CLASS_NAMES_PATH.read_text(encoding="utf-8"))
            threshold_data = json.loads(THRESHOLD_PATH.read_text(encoding="utf-8"))
            threshold = float(threshold_data["threshold"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ModelUnavailableError(
                "The saved model artifacts could not be loaded."
            ) from error

        if (
            not isinstance(class_names, list)
            or not class_names
            or not all(isinstance(name, str) for name in class_names)
            or not 0.0 <= threshold <= 1.0
        ):
            raise ModelUnavailableError("The saved class mapping or threshold is invalid.")

        _classifier = Classifier(model, class_names, threshold)
        return _classifier
