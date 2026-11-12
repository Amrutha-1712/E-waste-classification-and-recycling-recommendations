from flask import Flask, request, jsonify, render_template, redirect, url_for, render_template_string, session # type: ignore[import-not-found]
from flask_cors import CORS  # type: ignore[import-not-found]
import base64
import binascii
import hashlib
import hmac
import json
import os
import secrets
import smtplib
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta
from email.message import EmailMessage

app = Flask(__name__, template_folder='../frontend')
CORS(app)  

# Hardcoded secret key guarantees consistency across server hot-reloads
app.secret_key = "e_waste_care_secure_session_key_2026" 

# Forces the browser session cookie to remain active for 7 days across close/refresh events
app.permanent_session_lifetime = timedelta(days=7)

DATA_FILE = "users.json"
MAX_PROFILE_PHOTO_SIZE = 2 * 1024 * 1024
PASSWORD_RESET_TTL_SECONDS = 10 * 60
PASSWORD_RESET_COOLDOWN_SECONDS = 60
PASSWORD_RESET_MAX_ATTEMPTS = 5
password_reset_codes = {}
password_reset_requests = {}

def load_users():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_users(users):
    with open(DATA_FILE, "w") as f:
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
    return render_template('register.html')

@app.route('/login', methods=['GET'])
@app.route('/login.html', methods=['GET'])
def login_page():
    if 'user_email' in session:
        return redirect(url_for('home_page'))
    return render_template('login.html')


def find_user_by_email(users, email):
    normalized_email = email.strip().lower()
    for user_id, user_data in users.items():
        if (user_id.lower() == normalized_email or
                user_data.get('email', '').strip().lower() == normalized_email):
            return user_id, user_data
    return None, None


def send_password_reset_email(email, code):
    host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    port = int(os.environ.get('SMTP_PORT', '587'))
    username = os.environ.get('SMTP_USERNAME')
    password = os.environ.get('SMTP_PASSWORD')
    sender = os.environ.get('SMTP_FROM', username or '')
    if not username or not password or not sender:
        raise RuntimeError("SMTP_USERNAME, SMTP_PASSWORD, and SMTP_FROM must be configured.")

    message = EmailMessage()
    message['Subject'] = 'Your CircuitCycle password reset code'
    message['From'] = sender
    message['To'] = email
    message.set_content(
        f"Your CircuitCycle password reset code is {code}. "
        "It expires in 10 minutes. If you did not request this, ignore this email."
    )

    with smtplib.SMTP(host, port, timeout=15) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(username, password)
        smtp.send_message(message)


@app.route('/api/password-reset/request', methods=['POST'])
def request_password_reset():
    payload = request.get_json(silent=True)
    email = payload.get('email', '') if isinstance(payload, dict) else ''
    if not isinstance(email, str) or not email.strip():
        return jsonify({"success": False, "message": "Enter your registered email address."}), 400

    user_id, user_data = find_user_by_email(load_users(), email)
    if user_data is None:
        return jsonify({"success": False, "message": "No account is registered with that email address."}), 404

    email = user_data.get('email') or user_id
    now = time.time()
    if now - password_reset_requests.get(email.lower(), 0) < PASSWORD_RESET_COOLDOWN_SECONDS:
        return jsonify({"success": False, "message": "Please wait a minute before requesting another code."}), 429

    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        send_password_reset_email(email, code)
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError):
        app.logger.exception("Unable to send password reset email.")
        return jsonify({
            "success": False,
            "message": "We couldn't send the code right now. Please try again later."
        }), 503

    password_reset_codes[email.lower()] = {
        "digest": hashlib.sha256(f"{email.lower()}:{code}".encode()).hexdigest(),
        "expires_at": now + PASSWORD_RESET_TTL_SECONDS,
        "attempts": 0
    }
    password_reset_requests[email.lower()] = now
    return jsonify({"success": True, "message": "A 6-digit reset code was sent to your email."}), 200


@app.route('/api/password-reset/complete', methods=['POST'])
def complete_password_reset():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"success": False, "message": "Invalid password reset request."}), 400

    email = payload.get('email', '')
    code = payload.get('code', '')
    new_password = payload.get('password', '')
    if not all(isinstance(value, str) for value in (email, code, new_password)):
        return jsonify({"success": False, "message": "Enter your email, code, and new password."}), 400
    email = email.strip().lower()
    if not email or not code.isdigit() or len(code) != 6:
        return jsonify({"success": False, "message": "Enter the 6-digit code sent to your email."}), 400
    if len(new_password) < 6:
        return jsonify({"success": False, "message": "Your password must be at least 6 characters."}), 400

    reset = password_reset_codes.get(email)
    if reset is None or reset['expires_at'] < time.time():
        password_reset_codes.pop(email, None)
        return jsonify({"success": False, "message": "That code has expired. Request a new one."}), 400
    if reset['attempts'] >= PASSWORD_RESET_MAX_ATTEMPTS:
        password_reset_codes.pop(email, None)
        return jsonify({"success": False, "message": "Too many incorrect attempts. Request a new code."}), 429

    submitted_digest = hashlib.sha256(f"{email}:{code}".encode()).hexdigest()
    if not hmac.compare_digest(reset['digest'], submitted_digest):
        reset['attempts'] += 1
        return jsonify({"success": False, "message": "That code is incorrect. Please try again."}), 400

    user_id, user_data = find_user_by_email(load_users(), email)
    if user_data is None:
        password_reset_codes.pop(email, None)
        return jsonify({"success": False, "message": "No account is registered with that email address."}), 404

    users = load_users()
    user_data['password'] = new_password
    users[user_id] = user_data
    save_users(users)
    password_reset_codes.pop(email, None)
    password_reset_requests.pop(email, None)
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
                .navbar { width: calc(100% - 16px); top: 8px; gap: 8px; }
                .nav-links { gap: 8px; }
                .profile-menu {
                    right: 0;
                    width: min(340px, calc(100vw - 16px));
                    max-height: calc(100vh - 82px);
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
        "password": password, 
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
        return jsonify({"success": False, "message": "Enter your username/email and password."}), 400

    user_id, user_data = None, None
    for candidate_id, candidate in users.items():
        if (candidate_id.lower() == input_user.strip().lower() or
                candidate.get('email', '').lower() == input_user.strip().lower() or
                candidate.get('username', '').lower() == input_user.strip().lower()):
            user_id, user_data = candidate_id, candidate
            break
    if user_data is None or user_data.get('password') != password:
        return jsonify({
            "success": False,
            "message": "Invalid username/email or password."
        }), 401

    username_val = user_data.get('username', input_user)
    email_val = user_data.get('email', user_id)
    points_val = user_data.get('points', 0)
    recycled_val = user_data.get('items_recycled', 0)
    session.permanent = True
    session['user_email'] = email_val
    session['user_username'] = username_val

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

if __name__ == '__main__':
    app.run(debug=True, port=5000)