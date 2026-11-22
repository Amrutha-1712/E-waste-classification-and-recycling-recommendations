from __future__ import annotations

import base64
from io import BytesIO
import sqlite3
import threading
from urllib.parse import parse_qs, urlsplit

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


def _configure_smtp(monkeypatch):
    monkeypatch.setenv("SMTP_SERVER", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.test")
    monkeypatch.setenv("SMTP_PASSWORD", "test-app-password")
    monkeypatch.setenv("SMTP_FROM", "sender@example.test")


def _run_background_threads_synchronously(monkeypatch):
    class ImmediateThread:
        def __init__(self, target, args, daemon):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(backend_app, "Thread", ImmediateThread)


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


def test_email_password_reset_link_is_single_use_and_updates_password(monkeypatch):
    _configure_smtp(monkeypatch)
    _run_background_threads_synchronously(monkeypatch)
    email = "reset@example.test"
    users = {
        email: {
            "username": "reset-user",
            "email": email,
            "password_hash": backend_app.hash_password("old-password"),
            "items_recycled": 0,
            "points": 0,
        }
    }
    delivered = []
    monkeypatch.setattr(backend_app, "load_users", lambda: users)
    monkeypatch.setattr(backend_app, "save_users", lambda changed: users.update(changed))
    monkeypatch.setattr(
        backend_app, "send_password_reset_email",
        lambda recipient, reset_url: delivered.append((recipient, reset_url)),
    )
    monkeypatch.setattr(backend_app, "password_reset_tokens", {})
    monkeypatch.setattr(backend_app, "password_reset_requests", {})

    client = _client()
    assert client.get("/forgot-password").status_code == 200
    response = client.post(
        "/api/password-reset/request-link",
        json={"email": email},
    )
    assert response.status_code == 200
    assert response.json["success"] is True
    assert email not in response.get_data(as_text=True)
    assert len(delivered) == 1
    recipient, reset_url = delivered[0]
    assert recipient == email
    token = parse_qs(urlsplit(reset_url).query)["token"][0]
    assert token not in response.get_data(as_text=True)
    digest = backend_app.password_reset_token_digest(token)
    assert 0 < backend_app.password_reset_tokens[digest]["expires_at"] - backend_app.time.time() <= 900

    reset_page = client.get(urlsplit(reset_url).path + "?" + urlsplit(reset_url).query)
    assert reset_page.status_code == 200
    assert reset_page.headers["Cache-Control"] == "no-store"
    assert reset_page.headers["Referrer-Policy"] == "no-referrer"
    assert client.get("/reset-password?token=invalid").status_code == 302
    assert client.post(
        "/api/password-reset/complete",
        json={"token": "invalid", "password": "new-password"},
    ).status_code == 400
    response = client.post(
        "/api/password-reset/complete",
        json={"token": token, "password": "new-password"},
    )
    assert response.status_code == 200
    assert backend_app.verify_password(users[email], "new-password") == (True, False)
    assert "password" not in users[email]
    assert client.post(
        "/api/password-reset/complete",
        json={"token": token, "password": "another-password"},
    ).status_code == 400


def test_password_reset_token_expires_and_resend_is_throttled(monkeypatch):
    _configure_smtp(monkeypatch)
    _run_background_threads_synchronously(monkeypatch)
    email = "expiry@example.test"
    users = {email: {"email": email}}
    sent = []
    monkeypatch.setattr(backend_app, "load_users", lambda: users)
    monkeypatch.setattr(
        backend_app, "send_password_reset_email",
        lambda recipient, link: sent.append((recipient, link)),
    )
    monkeypatch.setattr(backend_app, "password_reset_tokens", {})
    monkeypatch.setattr(backend_app, "password_reset_requests", {})

    client = _client()
    assert client.post(
        "/api/password-reset/request-link", json={"email": email}
    ).status_code == 200
    response = client.post(
        "/api/password-reset/request-link", json={"email": email}
    )
    assert response.status_code == 429
    assert response.json["retry_after"] > 0

    token = parse_qs(urlsplit(sent[0][1]).query)["token"][0]
    digest = backend_app.password_reset_token_digest(token)
    backend_app.password_reset_tokens[digest]["expires_at"] = 0
    response = client.get(f"/reset-password?token={token}")
    assert response.status_code == 302
    response = client.post("/api/password-reset/complete", json={
        "token": token, "password": "new-password"
    })
    assert response.status_code == 400
    assert "expired" in response.json["message"].lower()


def test_password_reset_email_configuration_failure_is_reported(monkeypatch):
    email = "smtp-error@example.test"
    monkeypatch.setattr(backend_app, "load_users", lambda: {email: {"email": email}})

    def fail_configuration():
        raise backend_app.SMTPConfigurationError("SMTP settings are missing")

    monkeypatch.setattr(backend_app, "get_smtp_settings", fail_configuration)
    monkeypatch.setattr(backend_app, "password_reset_tokens", {})
    monkeypatch.setattr(backend_app, "password_reset_requests", {})

    response = _client().post(
        "/api/password-reset/request-link",
        json={"email": email},
    )
    assert response.status_code == 503
    assert "not configured" in response.json["message"].lower()
    assert email not in backend_app.password_reset_tokens


def test_password_reset_email_uses_configured_starttls_smtp(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, server, port, timeout):
            sent["connection"] = (server, port, timeout)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def ehlo(self):
            sent["ehlo"] = True

        def starttls(self, context):
            sent["starttls"] = context is not None

        def login(self, username, password):
            sent["credentials"] = (username, password)

        def send_message(self, message):
            sent["message"] = message

    monkeypatch.setenv("SMTP_SERVER", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.test")
    monkeypatch.setenv("SMTP_PASSWORD", "test-app-password")
    monkeypatch.setenv("SMTP_FROM", "sender@example.test")
    monkeypatch.setattr(backend_app.smtplib, "SMTP", FakeSMTP)

    backend_app.send_password_reset_email(
        "recipient@example.test",
        "http://localhost:5000/reset-password?token=test-token",
    )

    assert sent["connection"] == ("smtp.gmail.com", 587, 15)
    assert sent["starttls"] is True
    assert sent["credentials"] == ("sender@example.test", "test-app-password")
    assert sent["message"]["To"] == "recipient@example.test"
    assert "test-token" in sent["message"].get_body(preferencelist=("plain",)).get_content()


def test_password_reset_request_returns_before_email_finishes(monkeypatch):
    email = "background@example.test"
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    monkeypatch.setattr(backend_app, "load_users", lambda: {email: {"email": email}})
    monkeypatch.setattr(
        backend_app, "get_smtp_settings",
        lambda: ("smtp.gmail.com", 587, "sender@example.test", "secret", "sender@example.test"),
    )

    def delayed_send(_recipient, _reset_url):
        started.set()
        release.wait(5)
        finished.set()

    monkeypatch.setattr(backend_app, "send_password_reset_email", delayed_send)
    monkeypatch.setattr(backend_app, "password_reset_tokens", {})
    monkeypatch.setattr(backend_app, "password_reset_requests", {})

    try:
        response = _client().post(
            "/api/password-reset/request-link",
            json={"email": email},
        )
        assert response.status_code == 200
        assert started.wait(1)
        assert not finished.is_set()
    finally:
        release.set()
    assert finished.wait(2)


def test_smtp_authentication_failure_is_logged_and_reset_can_be_retried(monkeypatch, caplog):
    _configure_smtp(monkeypatch)
    _run_background_threads_synchronously(monkeypatch)
    email = "smtp-auth@example.test"
    monkeypatch.setattr(backend_app, "load_users", lambda: {email: {"email": email}})

    def fail_auth(*_args):
        raise backend_app.smtplib.SMTPAuthenticationError(535, b"Authentication failed")

    monkeypatch.setattr(backend_app, "send_password_reset_email", fail_auth)
    monkeypatch.setattr(backend_app, "password_reset_tokens", {})
    monkeypatch.setattr(backend_app, "password_reset_requests", {})

    response = _client().post(
        "/api/password-reset/request-link",
        json={"email": email},
    )
    assert response.status_code == 200
    assert "SMTP authentication failed" in caplog.text
    assert not backend_app.password_reset_tokens
    assert not backend_app.password_reset_requests


def test_smtp_connection_failure_is_logged_and_reset_can_be_retried(monkeypatch, caplog):
    _configure_smtp(monkeypatch)
    _run_background_threads_synchronously(monkeypatch)
    email = "smtp-connect@example.test"
    monkeypatch.setattr(backend_app, "load_users", lambda: {email: {"email": email}})

    def fail_connection(*_args):
        raise backend_app.smtplib.SMTPServerDisconnected("connection lost")

    monkeypatch.setattr(backend_app, "send_password_reset_email", fail_connection)
    monkeypatch.setattr(backend_app, "password_reset_tokens", {})
    monkeypatch.setattr(backend_app, "password_reset_requests", {})

    response = _client().post(
        "/api/password-reset/request-link",
        json={"email": email},
    )
    assert response.status_code == 200
    assert "Could not connect to the SMTP server" in caplog.text
    assert not backend_app.password_reset_tokens
    assert not backend_app.password_reset_requests


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
