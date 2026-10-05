from flask import Flask, request, jsonify, render_template  # type: ignore[import-not-found]
from flask_cors import CORS  # type: ignore[import-not-found]
import json
import os

# Crucial setup: Tells Flask to look for HTML templates inside the frontend folder
app = Flask(__name__, template_folder='../frontend')
CORS(app)  

DATA_FILE = "users.json"

def load_users():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(DATA_FILE, "w") as f:
        json.dump(users, f, indent=4)

# Routes to display the team's HTML pages
@app.route('/register')
def register_page():
    return render_template('register.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/home')
def home_page():
    return render_template('home.html')

# API Logic: Account Registration
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({"success": False, "message": "All fields are required"}), 400

    users = load_users()
    if username in users:
        return jsonify({"success": False, "message": "Username already taken!"}), 400

    users[username] = {"password": password, "items_recycled": 0, "points": 0}
    save_users(users)
    return jsonify({"success": True, "message": "Registration successful!"})

# API Logic: User Verification
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json
    username = data.get('username')
    password = data.get('password')

    users = load_users()
    if username in users and users[username]['password'] == password:
        return jsonify({
            "success": True, 
            "message": "Welcome back!", 
            "username": username,
            "points": users[username]['points'],
            "items_recycled": users[username]['items_recycled']
        })
    
    return jsonify({"success": False, "message": "Incorrect username or password"}), 401

if __name__ == '__main__':
    print("🚀 E-Waste server launching on http://127.0.0")
    app.run(debug=True, port=5000)
