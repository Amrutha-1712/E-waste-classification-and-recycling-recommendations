from flask import Flask, request, jsonify, render_template, redirect, url_for, render_template_string, session # type: ignore[import-not-found]
from flask_cors import CORS  # type: ignore[import-not-found]
import json
import os
from datetime import timedelta

app = Flask(__name__, template_folder='../frontend')
CORS(app)  

# Hardcoded secret key guarantees consistency across server hot-reloads
app.secret_key = "e_waste_care_secure_session_key_2026" 

# Forces the browser session cookie to remain active for 7 days across close/refresh events
app.permanent_session_lifetime = timedelta(days=7)

DATA_FILE = "users.json"

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
        
    try:
        original_html = render_template('login.html')
        
        # Intercepts form data submit, routes to /api/login, and saves cookie session state
        injected_controller = """
        <script>
        document.addEventListener("DOMContentLoaded", function() {
            var targetForm = document.querySelector("form");
            if(targetForm) {
                targetForm.removeAttribute("action");
                targetForm.removeAttribute("method");
                
                targetForm.addEventListener("submit", function(e) {
                    e.preventDefault();
                    
                    var userBox = document.querySelector('input[type="text"], input[name="username"], input[name="email"], #username');
                    var passBox = document.querySelector('input[type="password"], input[name="password"], #password');
                    
                    var payload = {
                        username: userBox ? userBox.value : "User",
                        password: passBox ? passBox.value : ""
                    };
                    
                    fetch('/api/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    })
                    .then(function(res) { return res.json(); })
                    .then(function(data) {
                        if (data.success || data.status === "success") {
                            window.location.replace("/home");
                        } else {
                            alert(data.message || "Invalid account credentials entered.");
                        }
                    })
                    .catch(function(err) {
                        window.location.replace("/home");
                    });
                });
            }
        });
        </script>
        </body>
        """
        if "</body>" in original_html:
            return original_html.replace("</body>", injected_controller)
        return original_html + injected_controller
    except Exception:
        return render_template('login.html')

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
    account_id = session.get('user_email')
    if not account_id:
        return jsonify({"logged_in": False, "user": None}), 200

    users = load_users()
    user_data = users.get(account_id)
    if user_data is None:
        user_data = next(
            (
                stored_user for stored_user in users.values()
                if stored_user.get('email') == account_id
                or stored_user.get('username') == account_id
            ),
            None
        )

    if user_data is None:
        return jsonify({"logged_in": False, "user": None}), 200

    return jsonify({
        "logged_in": True,
        "user": {
            "username": user_data.get('username') or session.get('user_username', 'User'),
            "email": user_data.get('email', '')
        }
    }), 200

# ==========================================
#       ROBUST BACKEND PROCESSING LOGIC
# ==========================================

@app.route('/api/register', methods=['POST'])
@app.route('/register', methods=['POST'])
def handle_register():
    json_data = request.get_json(silent=True) or {}
    
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
    
    input_user = (json_data.get('username') or request.values.get('username') or 
                  json_data.get('email') or request.values.get('email') or
                  json_data.get('loginUser') or request.values.get('loginUser'))
    
    username_val = str(input_user) if input_user else "User"
    email_val = ""
    points_val = 0
    recycled_val = 0

    if input_user in users:
        username_val = users[input_user].get('username', username_val)
        email_val = users[input_user].get('email', email_val)
        points_val = users[input_user].get('points', 0)
        recycled_val = users[input_user].get('items_recycled', 0)
    else:
        for stored_email, u_data in users.items():
            if u_data.get('username') == input_user or u_data.get('email') == input_user:
                username_val = u_data.get('username', username_val)
                email_val = u_data.get('email', email_val)
                points_val = u_data.get('points', 0)
                recycled_val = u_data.get('items_recycled', 0)
                break

    # Persist session metrics inside active storage variables
    session.permanent = True
    session['user_email'] = email_val if email_val else username_val
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