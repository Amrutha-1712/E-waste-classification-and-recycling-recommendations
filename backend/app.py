from flask import Flask, request, jsonify, render_template, redirect, url_for, render_template_string, session, make_response # type: ignore[import-not-found]
from flask_cors import CORS  # type: ignore[import-not-found]
from pathlib import Path
from io import BytesIO
import base64
import binascii
import hashlib
import hmac
import html
import json
import os
import secrets
import smtplib
import sqlite3
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from email.message import EmailMessage
from threading import Thread
from PIL import Image, UnidentifiedImageError
from dotenv import load_dotenv

from .feedback_store import save_feedback
from .component_info import get_component_info
from .model_service import ModelUnavailableError, get_classifier
from .recommendations import RECOMMENDATIONS, get_recommendation

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ENV_FILE = (Path(__file__).resolve().parent / ".env").resolve()
load_dotenv(dotenv_path=BACKEND_ENV_FILE)
APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5000").rstrip("/")

app = Flask(__name__, template_folder=str(PROJECT_ROOT / "frontend"))
CORS(app)

app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
if not os.environ.get("FLASK_SECRET_KEY"):
    app.logger.warning(
        "FLASK_SECRET_KEY is not set; sessions will not survive server restarts."
    )
app.config.update(
    MAX_CONTENT_LENGTH=12 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_COOKIE_SECURE") == "1",
)
app.logger.warning(
    "Backend .env path: %s (exists=%s); SMTP variable presence: %s",
    BACKEND_ENV_FILE,
    BACKEND_ENV_FILE.is_file(),
    ", ".join(
        f"{name}={'set' if os.environ.get(name) else 'missing'}"
        for name in (
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "SMTP_FROM",
            "SMTP_SERVER",
            "SMTP_PORT",
        )
    ),
)

# Forces the browser session cookie to remain active for 7 days across close/refresh events
app.permanent_session_lifetime = timedelta(days=7)

DATA_FILE = PROJECT_ROOT / "users.json"
MAX_PROFILE_PHOTO_SIZE = 2 * 1024 * 1024
MAX_CLASSIFICATION_IMAGE_SIZE = 10 * 1024 * 1024
PASSWORD_HASH_ITERATIONS = 310_000
PASSWORD_RESET_TOKEN_TTL_SECONDS = 15 * 60
PASSWORD_RESET_COOLDOWN_SECONDS = 60
password_reset_tokens = {}
password_reset_requests = {}
password_reset_lock = threading.Lock()


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    salt_text = base64.urlsafe_b64encode(salt).decode("ascii")
    digest_text = base64.urlsafe_b64encode(digest).decode("ascii")
    return f"pbkdf2_sha256${PASSWORD_HASH_ITERATIONS}${salt_text}${digest_text}"


def verify_password(user_data, password):
    stored_hash = user_data.get("password_hash")
    if isinstance(stored_hash, str):
        try:
            algorithm, iterations, salt_text, expected_text = stored_hash.split("$", 3)
            if algorithm != "pbkdf2_sha256":
                return False, False
            salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
            expected = base64.urlsafe_b64decode(expected_text.encode("ascii"))
            actual = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), salt, int(iterations)
            )
        except (ValueError, TypeError, binascii.Error):
            return False, False
        return hmac.compare_digest(actual, expected), False

    legacy_password = user_data.get("password")
    if isinstance(legacy_password, str) and hmac.compare_digest(
        legacy_password, password
    ):
        return True, True
    return False, False


def load_users():
    if not DATA_FILE.exists():
        return {}
    with DATA_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)

def save_users(users):
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(users, f, indent=4)

def get_session_user(users):
    account_id = session.get('user_email')
    if not account_id:
        return None, None

    if account_id in users:
        return account_id, users[account_id]

    for user_id, user_data in users.items():
        if user_data.get('email') == account_id or user_data.get('username') == account_id:
            return user_id, user_data

    return None, None

# ==========================================
#      DYNAMIC RESPONSIVE ERROR TEMPLATE
# ==========================================
ERROR_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }}</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', system-ui, sans-serif; }
        body { background-color: #e8f5e9; display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
        .error-container { background: white; padding: 40px 30px; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); text-align: center; max-width: 460px; width: 100%; }
        .warning-icon { font-size: 56px; color: #d32f2f; margin-bottom: 15px; }
        h2 { color: #1b5e20; margin-bottom: 12px; font-size: 24px; font-weight: 700; }
        p { color: #4b5563; margin-bottom: 28px; line-height: 1.6; font-size: 16px; }
        .back-button { display: inline-block; background-color: #2e7d32; color: white; padding: 14px 28px; text-decoration: none; border-radius: 8px; font-weight: 600; font-size: 15px; width: 100%; transition: background-color 0.2s; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }
        .back-button:hover { background-color: #1b5e20; }
    </style>
</head>
<body>
    <div class="error-container">
        <div class="warning-icon">⚠️</div>
        <h2>{{ title }}</h2>
        <p>{{ message }}</p>
        <a href="{{ back_url }}" class="back-button">Return to Page</a>
    </div>
</body>
</html>
"""

# ==========================================
#    DYNAMIC INJECTOR PATTERN HOOKS (GET)
# ==========================================

@app.route('/')
@app.route('/index.html')
def root_page():
    """First landing home portal template."""
    if 'user_email' in session:
        return redirect(url_for('home_page'))
    return render_template('index.html')

@app.route('/register', methods=['GET'])
@app.route('/register.html', methods=['GET'])
def register_page():
    if 'user_email' in session:
        return redirect(url_for('home_page'))
    return render_template('Register.html')

@app.route('/login', methods=['GET'])
@app.route('/login.html', methods=['GET'])
def login_page():
    if 'user_email' in session:
        return redirect(url_for('home_page'))
    return render_template('login.html')

@app.route('/forgot-password')
@app.route('/forgot-password.html')
def forgot_password_page():
    return render_template('forgot-password.html')

@app.route('/reset-password')
def reset_password_page():
    token = request.args.get('token', '')
    if get_password_reset_token(token) is None:
        return redirect(url_for('forgot_password_page', reset='invalid_token'))

    response = make_response(render_template('reset-password.html', reset_token=token))
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

@app.route('/classify')
@app.route('/classify.html')
def classify_page():
    return render_template('classify.html')

@app.route('/components')
@app.route('/components.html')
def components_page():
    return render_template('components.html')


def find_user_by_email(users, email):
    normalized_email = email.strip().lower()
    for user_id, user_data in users.items():
        if (user_id.lower() == normalized_email or
                user_data.get('email', '').strip().lower() == normalized_email):
            return user_id, user_data
    return None, None


class SMTPConfigurationError(RuntimeError):
    pass


def clear_failed_password_reset_email(email, digest, requested_at):
    with password_reset_lock:
        password_reset_tokens.pop(digest, None)
        if password_reset_requests.get(email) == requested_at:
            password_reset_requests.pop(email, None)


def deliver_password_reset_email(recipient, reset_url, digest, email, requested_at):
    try:
        send_password_reset_email(recipient, reset_url)
    except SMTPConfigurationError as error:
        clear_failed_password_reset_email(email, digest, requested_at)
        app.logger.error("Password reset email configuration error: %s", error)
    except smtplib.SMTPAuthenticationError:
        clear_failed_password_reset_email(email, digest, requested_at)
        app.logger.exception("SMTP authentication failed while sending a reset link.")
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, TimeoutError, OSError):
        clear_failed_password_reset_email(email, digest, requested_at)
        app.logger.exception("Could not connect to the SMTP server.")
    except smtplib.SMTPException:
        clear_failed_password_reset_email(email, digest, requested_at)
        app.logger.exception("The SMTP server rejected the password reset email.")
    except ValueError:
        clear_failed_password_reset_email(email, digest, requested_at)
        app.logger.exception("The password reset email could not be formatted.")


def get_smtp_settings():
    server = os.environ.get('SMTP_SERVER') or os.environ.get('SMTP_HOST') or 'smtp.gmail.com'
    username = os.environ.get('SMTP_USERNAME')
    password = os.environ.get('SMTP_PASSWORD')
    sender = os.environ.get('SMTP_FROM')
    missing = [
        name for name, value in (
            ('SMTP_SERVER', server),
            ('SMTP_USERNAME', username),
            ('SMTP_PASSWORD', password),
            ('SMTP_FROM', sender),
        ) if not value
    ]
    if missing:
        raise SMTPConfigurationError(
            "Missing required email settings: " + ", ".join(missing)
        )

    try:
        port = int(os.environ.get('SMTP_PORT', '587'))
    except ValueError as error:
        raise SMTPConfigurationError("SMTP_PORT must be a number.") from error
    if not 1 <= port <= 65535:
        raise SMTPConfigurationError("SMTP_PORT must be between 1 and 65535.")

    return server, port, username, password, sender


def send_password_reset_email(email, reset_url):
    server, port, username, password, sender = get_smtp_settings()
    message = EmailMessage()
    message['Subject'] = 'Reset your CircuitCycle password'
    message['From'] = sender
    message['To'] = email
    message.set_content(
        "We received a request to reset your CircuitCycle password.\n\n"
        f"Reset it using this link (valid for 15 minutes):\n{reset_url}\n\n"
        "If you did not request this, you can ignore this email."
    )
    message.add_alternative(
        "<p>We received a request to reset your CircuitCycle password.</p>"
        f'<p><a href="{html.escape(reset_url, quote=True)}">Reset your password</a></p>'
        "<p>This link expires in 15 minutes. If you did not request this, "
        "you can ignore this email.</p>",
        subtype='html',
    )

    with smtplib.SMTP(server, port, timeout=15) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(username, password)
        smtp.send_message(message)


def password_reset_token_digest(token):
    key = str(app.secret_key).encode("utf-8")
    return hmac.new(key, token.encode("utf-8"), hashlib.sha256).hexdigest()


def get_password_reset_token(token):
    if not isinstance(token, str) or not token or len(token) > 256:
        return None

    digest = password_reset_token_digest(token)
    with password_reset_lock:
        reset = password_reset_tokens.get(digest)
        if reset is None:
            return None
        if reset['expires_at'] <= time.time():
            password_reset_tokens.pop(digest, None)
            return None
        return digest, reset


@app.route('/api/password-reset/request', methods=['POST'])
@app.route('/api/password-reset/request-code', methods=['POST'])
@app.route('/api/password-reset/request-link', methods=['POST'])
def request_password_reset():
    payload = request.get_json(silent=True)
    email = payload.get('email', '') if isinstance(payload, dict) else ''
    if not isinstance(email, str) or not email.strip():
        return jsonify({"success": False, "message": "Enter your registered email address."}), 400

    email = email.strip().lower()
    if "@" not in email:
        return jsonify({"success": False, "message": "Enter a valid email address."}), 400

    user_id, user_data = find_user_by_email(load_users(), email)
    if user_data is None:
        return jsonify({
            "success": True,
            "message": "If an account exists for that email, a reset link will be sent."
        }), 200

    recipient = user_data.get('email') or user_id
    normalized_email = str(recipient).strip().lower()
    try:
        get_smtp_settings()
    except SMTPConfigurationError as error:
        app.logger.error("Password reset email configuration error: %s", error)
        return jsonify({
            "success": False,
            "message": "Email sending is not configured. Set SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM, SMTP_SERVER, and SMTP_PORT in backend/.env, then restart the server."
        }), 503

    now = time.time()
    token = secrets.token_urlsafe(32)
    digest = password_reset_token_digest(token)
    reset_url = f"{APP_BASE_URL}{url_for('reset_password_page', token=token)}"
    with password_reset_lock:
        last_request = password_reset_requests.get(normalized_email)
        if last_request is not None:
            retry_after = PASSWORD_RESET_COOLDOWN_SECONDS - int(now - last_request)
            if retry_after > 0:
                return jsonify({
                    "success": False,
                    "message": "Please wait before requesting another reset link.",
                    "retry_after": retry_after
                }), 429

        password_reset_tokens[digest] = {
            "email": normalized_email,
            "expires_at": now + PASSWORD_RESET_TOKEN_TTL_SECONDS,
        }
        password_reset_requests[normalized_email] = now

    try:
        Thread(
            target=deliver_password_reset_email,
            args=(recipient, reset_url, digest, normalized_email, now),
            daemon=False,
        ).start()
    except RuntimeError:
        clear_failed_password_reset_email(normalized_email, digest, now)
        app.logger.exception("Could not queue the password reset email.")
        return jsonify({
            "success": False,
            "message": "The reset email could not be queued. Please try again."
        }), 503

    return jsonify({
        "success": True,
        "message": "If an account exists for that email, a reset link will be sent.",
        "resend_after": PASSWORD_RESET_COOLDOWN_SECONDS
    }), 200


@app.route('/api/password-reset/complete', methods=['POST'])
def complete_password_reset():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"success": False, "message": "Invalid password reset request."}), 400

    token = payload.get('token', '')
    new_password = payload.get('password', '')
    if not isinstance(token, str) or not token:
        return jsonify({"success": False, "message": "Use the reset link from your email."}), 400
    if not isinstance(new_password, str) or len(new_password) < 6:
        return jsonify({"success": False, "message": "Your password must be at least 6 characters."}), 400

    token_result = get_password_reset_token(token)
    if token_result is None:
        return jsonify({
            "success": False,
            "message": "This reset link is invalid or expired. Request a new one."
        }), 400

    digest, reset = token_result
    with password_reset_lock:
        current_reset = password_reset_tokens.get(digest)
        if current_reset is not reset or current_reset['expires_at'] <= time.time():
            password_reset_tokens.pop(digest, None)
            return jsonify({
                "success": False,
                "message": "This reset link is invalid or expired. Request a new one."
            }), 400

        users = load_users()
        user_id, user_data = find_user_by_email(users, reset['email'])
        if user_data is None:
            password_reset_tokens.pop(digest, None)
            return jsonify({"success": False, "message": "This reset link is no longer valid."}), 400

        user_data["password_hash"] = hash_password(new_password)
        user_data.pop("password", None)
        users[user_id] = user_data
        save_users(users)
        password_reset_tokens.pop(digest, None)
        password_reset_requests.pop(reset['email'], None)

    return jsonify({"success": True, "message": "Your password has been reset. You can now log in."}), 200


@app.route('/auth/google')
def google_login():
    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    if not client_id or not os.environ.get('GOOGLE_CLIENT_SECRET'):
        return redirect(url_for('login_page', error='google_not_configured'))

    state = secrets.token_urlsafe(32)
    session['google_oauth_state'] = state
    redirect_uri = os.environ.get('GOOGLE_REDIRECT_URI') or url_for(
        'google_callback', _external=True
    )
    query = urllib.parse.urlencode({
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'prompt': 'select_account'
    })
    return redirect(f"https://accounts.google.com/o/oauth2/v2/auth?{query}")


@app.route('/auth/google/callback')
def google_callback():
    expected_state = session.pop('google_oauth_state', '')
    received_state = request.args.get('state', '')
    if not expected_state or not hmac.compare_digest(expected_state, received_state):
        return redirect(url_for('login_page', error='google_failed'))
    if request.args.get('error') or not request.args.get('code'):
        return redirect(url_for('login_page', error='google_failed'))

    client_id = os.environ.get('GOOGLE_CLIENT_ID')
    client_secret = os.environ.get('GOOGLE_CLIENT_SECRET')
    if not client_id or not client_secret:
        return redirect(url_for('login_page', error='google_not_configured'))

    redirect_uri = os.environ.get('GOOGLE_REDIRECT_URI') or url_for(
        'google_callback', _external=True
    )
    token_request = urllib.request.Request(
        'https://oauth2.googleapis.com/token',
        data=urllib.parse.urlencode({
            'code': request.args['code'],
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code'
        }).encode(),
        headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    try:
        with urllib.request.urlopen(token_request, timeout=10) as response:
            token_data = json.loads(response.read())
        id_token = token_data.get('id_token')
        if not id_token:
            raise ValueError("Google did not return an ID token.")

        with urllib.request.urlopen(
                'https://oauth2.googleapis.com/tokeninfo?' +
                urllib.parse.urlencode({'id_token': id_token}),
                timeout=10) as response:
            identity = json.loads(response.read())

        if (identity.get('aud') != client_id or
                identity.get('iss') not in ('accounts.google.com', 'https://accounts.google.com') or
                identity.get('email_verified') not in (True, 'true') or
                int(identity.get('exp', 0)) <= time.time()):
            raise ValueError("Google identity token validation failed.")
    except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError,
            json.JSONDecodeError):
        app.logger.exception("Google sign-in could not be completed.")
        return redirect(url_for('login_page', error='google_failed'))

    email = identity.get('email', '').strip()
    if not email:
        return redirect(url_for('login_page', error='google_failed'))

    users = load_users()
    user_id, user_data = find_user_by_email(users, email)
    if user_data is None:
        base_username = (identity.get('name') or email.split('@', 1)[0]).strip()
        username = base_username
        existing_names = {user.get('username', '').lower() for user in users.values()}
        suffix = 1
        while username.lower() in existing_names:
            suffix += 1
            username = f"{base_username}{suffix}"
        user_id = email
        user_data = {
            "username": username,
            "email": email,
            "items_recycled": 0,
            "points": 0
        }
        users[user_id] = user_data
        save_users(users)

    session.clear()
    session.permanent = True
    session['user_email'] = user_data.get('email', email)
    session['user_username'] = user_data.get('username', email.split('@', 1)[0])
    return redirect(url_for('home_page'))

@app.route('/home', methods=['GET'])
def home_page():
    """Dashboard view panel. The session tracker keeps the user authorized."""
    if 'user_email' not in session:
        return redirect(url_for('login_page'))
        
    try:
        page = render_template('index.html', logged_in=True, username=session.get('user_username', 'User'))
        page = page.replace(
            '<a class="button button-primary" id="viewProfileLink" href="/profile">View Profile</a>',
            ''
        ).replace("document.getElementById('viewProfileLink').href = '/profile';", '')
        page = page.replace('<small>Full name</small>', '<small>Username</small>')
        photo_controls = """
        <input id="profilePhotoInput" type="file" accept="image/png,image/jpeg,image/webp" hidden>
        <button class="button button-primary" id="profilePhotoSelect" type="button">Add profile picture</button>
        <button class="button button-secondary" id="profilePhotoRemove" type="button" hidden>Remove picture</button>
        <span id="profilePhotoStatus" role="status" aria-live="polite"></span>
        """
        page = page.replace(
            '<a class="button button-secondary" id="logoutLink" href="/logout">Log out</a>',
            photo_controls + '<a class="button button-secondary" id="logoutLink" href="/logout">Log out</a>',
            1
        )
        page = page.replace(
            "document.getElementById('profileEmail').textContent = email;",
            """document.getElementById('profileEmail').textContent = email;
                    const photo = document.getElementById('profilePhoto');
                    if (user.profile_photo) photo.src = user.profile_photo;
                    else photo.removeAttribute('src');"""
        )
        responsive_styles = """
        <style>
            .navbar, .profile-menu { box-sizing: border-box; }
            .profile-menu {
                max-width: calc(100vw - 24px);
                max-height: calc(100vh - 100px);
                overflow-y: auto;
            }
            @media (max-width: 900px) {
                .navbar { width: calc(100% - 24px); gap: 12px; }
                .nav-links { gap: clamp(8px, 1.5vw, 16px); }
            }
            @media (max-width: 700px) {
                .navbar { left: 8px; width: calc(100% - 16px); top: 8px; gap: 8px; transform: none; backdrop-filter: none; }
                .nav-links { gap: 8px; }
                .profile-menu {
                    position: fixed;
                    top: 76px;
                    right: 8px;
                    z-index: 1001;
                    width: min(340px, calc(100vw - 32px));
                    max-height: calc(100vh - 82px);
                }
                .profile-menu .profile-actions {
                    display: grid;
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }
                .profile-menu .profile-actions .button {
                    min-width: 0;
                    padding: 10px 8px;
                    text-align: center;
                    font-size: 12px;
                }
                .profile-menu #profilePhotoStatus {
                    grid-column: 1 / -1;
                    overflow-wrap: anywhere;
                }
            }
        </style>
        """
        page = page.replace('</head>', responsive_styles + '</head>', 1)
        photo_script = """
        <script>
            (function () {
                const input = document.getElementById('profilePhotoInput');
                const selectButton = document.getElementById('profilePhotoSelect');
                const removeButton = document.getElementById('profilePhotoRemove');
                const photo = document.getElementById('profilePhoto');
                const status = document.getElementById('profilePhotoStatus');
                if (!input || !selectButton || !removeButton || !photo || !status) return;

                function syncPhotoControls() {
                    const hasPhoto = Boolean(photo.getAttribute('src'));
                    selectButton.textContent = hasPhoto ? 'Update profile picture' : 'Add profile picture';
                    removeButton.hidden = !hasPhoto;
                }

                selectButton.addEventListener('click', function () {
                    input.click();
                });

                input.addEventListener('change', async function () {
                    const file = input.files && input.files[0];
                    if (!file) return;
                    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
                        status.textContent = 'Choose a PNG, JPG, or WebP image.';
                        input.value = '';
                        return;
                    }
                    if (file.size > 2 * 1024 * 1024) {
                        status.textContent = 'The image must be 2 MB or smaller.';
                        input.value = '';
                        return;
                    }

                    status.textContent = 'Uploading picture…';
                    try {
                        const imageData = await new Promise(function (resolve, reject) {
                            const reader = new FileReader();
                            reader.onload = function () { resolve(reader.result); };
                            reader.onerror = function () { reject(new Error('Unable to read image')); };
                            reader.readAsDataURL(file);
                        });
                        const response = await fetch('/api/profile/photo', {
                            method: 'POST',
                            credentials: 'same-origin',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ photo: imageData })
                        });
                        const result = await response.json();
                        if (!response.ok) throw new Error(result.message || 'Unable to save picture.');
                        photo.src = result.profile_photo;
                        syncPhotoControls();
                        status.textContent = 'Profile picture saved.';
                    } catch (error) {
                        console.error('Unable to save profile picture:', error);
                        status.textContent = error.message || 'Unable to save picture.';
                    } finally {
                        input.value = '';
                    }
                });

                removeButton.addEventListener('click', async function () {
                    status.textContent = 'Removing picture…';
                    try {
                        const response = await fetch('/api/profile/photo', {
                            method: 'DELETE',
                            credentials: 'same-origin'
                        });
                        const result = await response.json();
                        if (!response.ok) throw new Error(result.message || 'Unable to remove picture.');
                        photo.removeAttribute('src');
                        syncPhotoControls();
                        status.textContent = 'Profile picture removed.';
                    } catch (error) {
                        console.error('Unable to remove profile picture:', error);
                        status.textContent = error.message || 'Unable to remove picture.';
                    }
                });

                syncPhotoControls();
            }());
        </script>
        """
        page = page.replace('</body>', photo_script + '</body>', 1)
        return page
    except Exception:
        return f"""
        <html>
        <body style="font-family:sans-serif; background:#e8f5e9; text-align:center; padding-top:100px;">
            <h2>Logged In! Welcome to E-Waste Care Dashboard</h2>
            <p>User account session: <b>{session.get('user_username', 'Active User')}</b></p>
            <br>
            <a href="/logout" style="background:#d32f2f; color:white; padding:10px 20px; text-decoration:none; border-radius:5px;">Logout Securely</a>
        </body>
        </html>
        """

@app.route('/api/profile', methods=['GET'])
def get_profile():
    users = load_users()
    _, user_data = get_session_user(users)
    if user_data is None:
        return jsonify({"logged_in": False, "user": None}), 200

    return jsonify({
        "logged_in": True,
        "user": {
            "username": user_data.get('username') or session.get('user_username', 'User'),
            "email": user_data.get('email', ''),
            "profile_photo": user_data.get('profile_photo')
        }
    }), 200

@app.route('/api/profile/photo', methods=['POST', 'DELETE'])
def update_profile_photo():
    users = load_users()
    user_id, user_data = get_session_user(users)
    if user_data is None:
        return jsonify({"success": False, "message": "You must be logged in to manage your profile picture."}), 401

    if request.method == 'DELETE':
        user_data.pop('profile_photo', None)
        users[user_id] = user_data
        save_users(users)
        return jsonify({"success": True, "profile_photo": None}), 200

    max_request_size = ((MAX_PROFILE_PHOTO_SIZE + 2) // 3) * 4 + 256
    if request.content_length is not None and request.content_length > max_request_size:
        return jsonify({"success": False, "message": "The image must be 2 MB or smaller."}), 413

    payload = request.get_json(silent=True)
    photo_data = payload.get('photo') if isinstance(payload, dict) else None
    if not isinstance(photo_data, str) or ',' not in photo_data:
        return jsonify({"success": False, "message": "A valid image is required."}), 400

    header, encoded_image = photo_data.split(',', 1)
    mime_types = {
        'data:image/png;base64': ('image/png', lambda data: data.startswith(b'\x89PNG\r\n\x1a\n')),
        'data:image/jpeg;base64': ('image/jpeg', lambda data: data.startswith(b'\xff\xd8\xff')),
        'data:image/webp;base64': (
            'image/webp',
            lambda data: len(data) >= 12 and data[:4] == b'RIFF' and data[8:12] == b'WEBP'
        )
    }
    image_type = mime_types.get(header.lower())
    if image_type is None:
        return jsonify({"success": False, "message": "Use a PNG, JPG, or WebP image."}), 400
    if len(encoded_image) > ((MAX_PROFILE_PHOTO_SIZE + 2) // 3) * 4:
        return jsonify({"success": False, "message": "The image must be 2 MB or smaller."}), 413

    try:
        image_bytes = base64.b64decode(encoded_image, validate=True)
    except (binascii.Error, ValueError):
        return jsonify({"success": False, "message": "The image data is invalid."}), 400

    mime_type, matches_signature = image_type
    if len(image_bytes) > MAX_PROFILE_PHOTO_SIZE:
        return jsonify({"success": False, "message": "The image must be 2 MB or smaller."}), 413
    if not matches_signature(image_bytes):
        return jsonify({"success": False, "message": "The image contents do not match the selected format."}), 400

    user_data['profile_photo'] = f"data:{mime_type};base64,{encoded_image}"
    users[user_id] = user_data
    save_users(users)
    return jsonify({"success": True, "profile_photo": user_data['profile_photo']}), 200

# ==========================================
#       ROBUST BACKEND PROCESSING LOGIC
# ==========================================

@app.route('/api/register', methods=['POST'])
@app.route('/register', methods=['POST'])
def handle_register():
    json_data = request.get_json(silent=True) or {}
    if not isinstance(json_data, dict):
        return jsonify({"success": False, "message": "All fields are required."}), 400
    
    username = json_data.get('username') or request.values.get('username')
    email = json_data.get('email') or request.values.get('email') or username
    password = json_data.get('password') or request.values.get('password')

    if not username or not password or not email:
        if request.form or not request.is_json:
            return render_template_string(ERROR_TEMPLATE, title="Registration Incomplete", message="All validation fields are required.", back_url="/register")
        return jsonify({"success": False, "status": "error", "message": "All fields are required"}), 400

    users = load_users()
    
    email_exists = False
    if email in users:
        email_exists = True
    else:
        for stored_email, u_info in users.items():
            if u_info.get('email') == email or u_info.get('username') == username:
                email_exists = True
                break

    if email_exists:
        if request.form or not request.is_json:
            return render_template_string(ERROR_TEMPLATE, title="Registration Conflict", message="Email/Username already registered.", back_url="/register")
        return jsonify({"success": False, "status": "error", "message": "Email already registered"}), 400

    users[email] = {
        "username": username,
        "password_hash": hash_password(password),
        "email": email,
        "items_recycled": 0, 
        "points": 0
    }
    save_users(users)
    
    if request.form or not request.is_json:
        return redirect(url_for('login_page'))
        
    return jsonify({"success": True, "status": "success", "message": "Registration successful!"}), 200

@app.route('/api/login', methods=['POST'])
@app.route('/login', methods=['POST'])
def handle_login():
    users = load_users()
    json_data = request.get_json(silent=True) or {}
    if not isinstance(json_data, dict):
        return jsonify({"success": False, "message": "Enter your username/email and password."}), 400
    input_user = (json_data.get('username') or request.values.get('username') or
                  json_data.get('email') or request.values.get('email') or
                  json_data.get('loginUser') or request.values.get('loginUser'))
    password = json_data.get('password') or request.values.get('password')
    if not isinstance(input_user, str) or not isinstance(password, str):
        if request.form or not request.is_json:
            return redirect(url_for('login_page', error='invalid_credentials'))
        return jsonify({"success": False, "message": "Enter your username/email and password."}), 400

    user_id, user_data = None, None
    for candidate_id, candidate in users.items():
        if (candidate_id.lower() == input_user.strip().lower() or
                candidate.get('email', '').lower() == input_user.strip().lower() or
                candidate.get('username', '').lower() == input_user.strip().lower()):
            user_id, user_data = candidate_id, candidate
            break
    if user_data is None:
        password_matches, upgrade_legacy_password = False, False
    else:
        password_matches, upgrade_legacy_password = verify_password(
            user_data, password
        )
    if not password_matches:
        if request.form or not request.is_json:
            return redirect(url_for('login_page', error='invalid_credentials'))
        return jsonify({
            "success": False,
            "message": "Invalid username/email or password."
        }), 401
    if upgrade_legacy_password:
        user_data["password_hash"] = hash_password(password)
        user_data.pop("password", None)
        save_users(users)

    username_val = user_data.get('username', input_user)
    email_val = user_data.get('email', user_id)
    points_val = user_data.get('points', 0)
    recycled_val = user_data.get('items_recycled', 0)
    session.permanent = True
    session['user_email'] = email_val
    session['user_username'] = username_val

    if request.form or not request.is_json:
        return redirect(url_for('home_page'))

    return jsonify({
        "success": True,
        "success_status": True,
        "status": "success",
        "error": False,
        "redirect": "/home",
        "url": "/home",
        "message": "Welcome back!",
        "user": {
            "username": username_val,
            "email": email_val,
            "points": points_val,
            "items_recycled": recycled_val
        }
    }), 200

@app.route('/logout')
def handle_logout():
    """Clears user session storage entirely and resets application track state."""
    session.clear()
    return redirect(url_for('root_page'))


@app.route("/api/classify", methods=["POST"])
def classify_image():
    uploaded_file = request.files.get("image")
    if uploaded_file is not None:
        if not uploaded_file.filename:
            return jsonify({"success": False, "message": "Select an image to classify."}), 400
        image_bytes = uploaded_file.read(MAX_CLASSIFICATION_IMAGE_SIZE + 1)
    else:
        payload = request.get_json(silent=True)
        image_data = payload.get("image") if isinstance(payload, dict) else None
        if not isinstance(image_data, str) or not image_data:
            return jsonify({"success": False, "message": "Select an image to classify."}), 400
        if image_data[:5].lower() == "data:":
            header, separator, image_data = image_data.partition(",")
            if not separator or header.lower() not in {
                "data:image/jpeg;base64",
                "data:image/png;base64",
                "data:image/webp;base64",
            }:
                return jsonify({
                    "success": False,
                    "message": "Use a JPEG, PNG, or WebP image.",
                }), 415
        if len(image_data) > ((MAX_CLASSIFICATION_IMAGE_SIZE + 2) // 3) * 4:
            return jsonify({"success": False, "message": "The image must be 10 MB or smaller."}), 413
        try:
            image_bytes = base64.b64decode(image_data, validate=True)
        except (binascii.Error, ValueError):
            return jsonify({"success": False, "message": "The image data is invalid."}), 400

    if len(image_bytes) > MAX_CLASSIFICATION_IMAGE_SIZE:
        return jsonify({"success": False, "message": "The image must be 10 MB or smaller."}), 413
    if not image_bytes:
        return jsonify({"success": False, "message": "The uploaded image is empty."}), 400

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                return jsonify({
                    "success": False,
                    "message": "Use a JPEG, PNG, or WebP image.",
                }), 415
            if image.width * image.height > 40_000_000:
                return jsonify({
                    "success": False,
                    "message": "The image dimensions exceed the supported limit.",
                }), 413
            image.verify()
        with Image.open(BytesIO(image_bytes)) as image:
            image = image.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        return jsonify({"success": False, "message": "The image is invalid or corrupted."}), 400

    try:
        prediction = get_classifier().predict(image)
    except ModelUnavailableError as error:
        app.logger.error("Classification model is unavailable: %s", error)
        return jsonify({"success": False, "message": str(error)}), 503

    recommendation = None
    if prediction["classification_status"] == "classified":
        recommendation = get_recommendation(prediction["component"])
        if recommendation is None:
            app.logger.error(
                "No recycling recommendation exists for model class %r.",
                prediction["component"],
            )
            return jsonify({
                "success": False,
                "message": "A recommendation is not configured for this model class.",
            }), 503

    return jsonify({
        "success": True,
        "component": prediction["component"],
        "predicted_component": prediction["predicted_component"],
        "component_info": get_component_info(prediction["component"]),
        "confidence": round(prediction["confidence"] * 100, 1),
        "classification_status": prediction["classification_status"],
        "status_message": (
            "Successfully Classified"
            if prediction["classification_status"] == "classified"
            else "Unknown or Unrecognized Component"
        ),
        "recommendation": recommendation,
    }), 200


@app.route("/api/feedback", methods=["POST"])
def submit_feedback():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"success": False, "message": "Submit feedback as JSON."}), 400

    classification_correct = payload.get("classification_correct")
    recommendation_useful = payload.get("recommendation_useful")
    overall_rating = payload.get("overall_rating")
    component = payload.get("component")
    comments = payload.get("comments", "")
    if type(classification_correct) is not bool or type(recommendation_useful) is not bool:
        return jsonify({
            "success": False,
            "message": "Answer both classification and recommendation questions.",
        }), 400
    if (
        not isinstance(overall_rating, int)
        or isinstance(overall_rating, bool)
        or not 1 <= overall_rating <= 5
    ):
        return jsonify({"success": False, "message": "Choose a rating from 1 to 5."}), 400
    if component is not None and (
        not isinstance(component, str) or len(component) > 80
    ):
        return jsonify({"success": False, "message": "The component value is invalid."}), 400
    if not isinstance(comments, str) or len(comments) > 1000:
        return jsonify({
            "success": False,
            "message": "Feedback comments must be 1,000 characters or fewer.",
        }), 400

    try:
        feedback_id = save_feedback({
            "classification_correct": classification_correct,
            "recommendation_useful": recommendation_useful,
            "overall_rating": overall_rating,
            "component": component,
            "comments": comments.strip(),
        })
    except sqlite3.Error:
        app.logger.exception("Unable to persist feedback.")
        return jsonify({
            "success": False,
            "message": "Feedback could not be saved right now.",
        }), 503

    return jsonify({"success": True, "feedback_id": feedback_id}), 201


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"success": False, "message": "The request exceeds the 12 MB limit."}), 413


if __name__ == '__main__':
    try:
        get_classifier()
    except ModelUnavailableError as error:
        app.logger.error("Classification model is unavailable at startup: %s", error)
    app.run(
        host="0.0.0.0",
        debug=os.environ.get("FLASK_DEBUG") == "1",
        port=int(os.environ.get("PORT", "5000")),
    )