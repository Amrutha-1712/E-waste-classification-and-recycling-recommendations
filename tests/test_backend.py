from __future__ import annotations

import base64
from io import BytesIO
import sqlite3

import backend.app as backend_app
from backend.feedback_store import save_feedback
from backend.evaluate_independent import evaluate
from backend.model_service import ModelUnavailableError
from backend.dataset_tools import build_split_manifest, inspect_dataset
from PIL import Image


def _image_bytes(image_format: str = "JPEG") -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 48), (35, 90, 145)).save(output, format=image_format)
    return output.getvalue()


def _client():
    backend_app.app.config.update(TESTING=True)
    return backend_app.app.test_client()


def test_classification_requires_a_file():
    response = _client().post("/api/classify", data={})

    assert response.status_code == 400
    assert response.json["success"] is False


def test_existing_pages_are_served_with_case_sensitive_template_names():
    client = _client()

    assert client.get("/").status_code == 200
    assert client.get("/register").status_code == 200
    assert client.get("/login").status_code == 200
    assert client.get("/classify").status_code == 200


def test_corrupt_image_is_rejected_before_model_loading(monkeypatch):
    def fail_if_called():
        raise AssertionError("The classifier should not load for corrupt input.")

    monkeypatch.setattr(backend_app, "get_classifier", fail_if_called)
    response = _client().post(
        "/api/classify",
        data={"image": (BytesIO(b"not an image"), "photo.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert response.json["message"] == "The image is invalid or corrupted."


def test_classifier_returns_specific_recommendation(monkeypatch):
    class FakeClassifier:
        def predict(self, image):
            assert image.mode == "RGB"
            return {
                "component": "Battery",
                "predicted_component": "Battery",
                "confidence": 0.985,
                "classification_status": "classified",
            }

    monkeypatch.setattr(backend_app, "get_classifier", FakeClassifier)
    response = _client().post(
        "/api/classify",
        data={"image": (BytesIO(_image_bytes()), "battery.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert response.json["component"] == "Battery"
    assert response.json["confidence"] == 98.5
    assert response.json["component_info"] == (
        "Component: Battery\nRecyclable: Yes\nHazardous: Yes"
    )
    assert response.json["recommendation"]["reuse"].startswith("Reuse only")


def test_classifier_accepts_base64_data_uri(monkeypatch):
    class FakeClassifier:
        def predict(self, image):
            assert image.mode == "RGB"
            return {
                "component": "Battery",
                "predicted_component": "Battery",
                "confidence": 0.75,
                "classification_status": "classified",
            }

    monkeypatch.setattr(backend_app, "get_classifier", FakeClassifier)
    data_uri = "data:image/jpeg;base64," + base64.b64encode(_image_bytes()).decode("ascii")
    response = _client().post("/api/classify", json={"image": data_uri})

    assert response.status_code == 200
    assert response.json["component"] == "Battery"


def test_missing_model_is_reported_as_unavailable(monkeypatch):
    def unavailable():
        raise ModelUnavailableError("No trained model is available.")

    monkeypatch.setattr(backend_app, "get_classifier", unavailable)
    response = _client().post(
        "/api/classify",
        data={"image": (BytesIO(_image_bytes()), "battery.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 503
    assert "No trained model" in response.json["message"]


def test_feedback_is_validated_and_persisted(monkeypatch):
    stored = {}

    def save(payload):
        stored.update(payload)
        return 12

    monkeypatch.setattr(backend_app, "save_feedback", save)
    response = _client().post(
        "/api/feedback",
        json={
            "classification_correct": True,
            "recommendation_useful": False,
            "overall_rating": 4,
            "comments": "Useful safety guidance",
            "component": "Battery",
        },
    )

    assert response.status_code == 201
    assert response.json["feedback_id"] == 12
    assert stored["classification_correct"] is True
    assert stored["recommendation_useful"] is False


def test_feedback_store_writes_to_sqlite(tmp_path):
    database = tmp_path / "feedback.sqlite3"
    feedback_id = save_feedback(
        {
            "classification_correct": True,
            "recommendation_useful": True,
            "overall_rating": 5,
            "component": "RAM",
            "comments": "Clear instructions",
        },
        database,
    )

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT classification_correct, recommendation_useful, overall_rating, component, comments "
            "FROM feedback WHERE id = ?",
            (feedback_id,),
        ).fetchone()

    assert row == (1, 1, 5, "RAM", "Clear instructions")


def test_invalid_feedback_is_not_saved(monkeypatch):
    def fail_if_called(_payload):
        raise AssertionError("Invalid feedback must not be persisted.")

    monkeypatch.setattr(backend_app, "save_feedback", fail_if_called)
    response = _client().post(
        "/api/feedback",
        json={
            "classification_correct": "yes",
            "recommendation_useful": True,
            "overall_rating": 8,
        },
    )

    assert response.status_code == 400


def test_legacy_password_is_upgraded_after_successful_login(monkeypatch):
    users = {
        "legacy@example.test": {
            "username": "legacy-user",
            "email": "legacy@example.test",
            "password": "old-password",
            "items_recycled": 0,
            "points": 0,
        }
    }
    monkeypatch.setattr(backend_app, "load_users", lambda: users)
    monkeypatch.setattr(backend_app, "save_users", lambda changed: users.update(changed))

    response = _client().post(
        "/api/login",
        json={"username": "legacy-user", "password": "old-password"},
    )

    assert response.status_code == 200
    assert "password" not in users["legacy@example.test"]
    assert backend_app.verify_password(
        users["legacy@example.test"], "old-password"
    ) == (True, False)


def test_new_registrations_hash_password(monkeypatch):
    users = {}
    monkeypatch.setattr(backend_app, "load_users", lambda: users)
    monkeypatch.setattr(backend_app, "save_users", lambda changed: users.update(changed))

    response = _client().post(
        "/api/register",
        json={
            "username": "new-user",
            "email": "new@example.test",
            "password": "a-strong-password",
        },
    )

    assert response.status_code == 200
    user = users["new@example.test"]
    assert "password" not in user
    assert user["password_hash"].startswith("pbkdf2_sha256$")
    assert backend_app.verify_password(user, "a-strong-password") == (True, False)


def test_split_is_deterministic_and_stratified(tmp_path):
    raw_root = tmp_path / "Raw Data"
    for folder in ("1. Battery", "2. RAM"):
        class_dir = raw_root / folder
        class_dir.mkdir(parents=True)
        class_offset = 0 if folder == "1. Battery" else 120
        for index in range(10):
            image = Image.new("RGB", (30, 40), (index * 10 + class_offset, 30, 90))
            image.save(class_dir / f"image-{index}.jpg", format="JPEG")

    first = build_split_manifest(tmp_path, seed=7)
    second = build_split_manifest(tmp_path, seed=7)
    assert first["train"] == second["train"]
    assert first["validation"] == second["validation"]
    assert first["counts"]["train"] == {"Battery": 8, "RAM": 8}
    assert first["counts"]["validation"] == {"Battery": 2, "RAM": 2}


def test_exact_duplicate_images_stay_in_one_split(tmp_path):
    raw_root = tmp_path / "Raw Data"
    class_dir = raw_root / "1. Battery"
    class_dir.mkdir(parents=True)
    shared = _image_bytes()
    (class_dir / "copy-a.jpg").write_bytes(shared)
    (class_dir / "copy-b.jpg").write_bytes(shared)
    Image.new("RGB", (30, 40), (220, 20, 50)).save(class_dir / "other.jpg")
    Image.new("RGB", (30, 40), (15, 220, 50)).save(class_dir / "last.jpg")

    manifest = build_split_manifest(tmp_path, seed=3)
    split_by_path = {
        item["path"]: split
        for split in ("train", "validation")
        for item in manifest[split]
    }

    assert split_by_path[str(class_dir / "copy-a.jpg")] == split_by_path[
        str(class_dir / "copy-b.jpg")
    ]


def test_dataset_audit_reports_cross_split_exact_duplicates(tmp_path):
    raw_root = tmp_path / "Raw Data" / "Raw Data" / "1. Battery"
    augmented_root = tmp_path / "Augmented Data" / "Augmented Data" / "1. Battery"
    raw_root.mkdir(parents=True)
    augmented_root.mkdir(parents=True)
    image = _image_bytes()
    (raw_root / "raw.jpg").write_bytes(image)
    (augmented_root / "copy.jpg").write_bytes(image)

    report = inspect_dataset(tmp_path)

    assert report["class_count"] == 1
    assert report["split_totals"] == {"raw": 1, "augmented": 1}
    assert len(report["exact_duplicates"]) == 1
    assert report["corrupt_images"] == []


def test_independent_evaluation_stays_pending_when_dataset_is_missing(tmp_path):
    missing_test_root = tmp_path / "independent_test"

    try:
        evaluate(missing_test_root)
    except FileNotFoundError as error:
        assert "evaluation remains pending" in str(error)
    else:
        raise AssertionError("Independent evaluation should not proceed without test data.")
