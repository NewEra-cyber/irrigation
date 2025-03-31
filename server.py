import os
import json
import secrets
from datetime import datetime
from flask import Flask, request, jsonify, session, redirect, url_for, send_from_directory
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity
from flask_mail import Mail, Message
from flask_dance.contrib.google import make_google_blueprint, google
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import requests
from docx import Document

# Load environment variables from .env
load_dotenv()

app = Flask(__name__, static_folder='.')
app.secret_key = os.getenv('FLASK_SECRET_KEY')
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY')
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['ENVIRONMENT'] = os.getenv('ENVIRONMENT', 'local')

jwt = JWTManager(app)
mail = Mail(app)

# Google OAuth setup
google_bp = make_google_blueprint(
    client_id=os.getenv('GOOGLE_CLIENT_ID_LOCAL') if app.config['ENVIRONMENT'] == 'local' else os.getenv('GOOGLE_CLIENT_ID_PROD'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET_LOCAL') if app.config['ENVIRONMENT'] == 'local' else os.getenv('GOOGLE_CLIENT_SECRET_PROD'),
    redirect_to='google_login',
    scope=["profile", "email"]
)
app.register_blueprint(google_bp, url_prefix="/api")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(BASE_DIR, 'users.json')
IRRIGATION_DATA_FILE = os.path.join(BASE_DIR, 'irrigation_data.json')
RECORDS_DIR = os.path.join(BASE_DIR, 'records')

# Ensure directories and files exist
os.makedirs(RECORDS_DIR, exist_ok=True)
if not os.path.exists(USERS_FILE):
    with open(USERS_FILE, 'w') as f:
        json.dump({}, f)
if not os.path.exists(IRRIGATION_DATA_FILE):
    with open(IRRIGATION_DATA_FILE, 'w') as f:
        json.dump({}, f)

# Helper functions
def load_users():
    with open(USERS_FILE, 'r') as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=4)

def load_irrigation_data():
    with open(IRRIGATION_DATA_FILE, 'r') as f:
        data = json.load(f)
    if not data:
        data = fetch_weather_data()
        save_irrigation_data(data)
    return data

def save_irrigation_data(data):
    with open(IRRIGATION_DATA_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def fetch_weather_data():
    api_key = os.getenv('OPENWEATHER_API_KEY')
    url = f"http://api.openweathermap.org/data/2.5/weather?q=London&appid={api_key}&units=metric"
    response = requests.get(url)
    if response.status_code == 200:
        weather = response.json()
        return {
            "temperature": weather["main"]["temp"],
            "humidity": weather["main"]["humidity"],
            "soil_moisture": 50.0,  # Simulated
            "soil_ph": 6.5,         # Simulated
            "light_intensity": 1000.0,  # Simulated
            "anomaly": False,
            "timestamp": datetime.utcnow().isoformat()
        }
    return {
        "temperature": 25.0, "humidity": 60.0, "soil_moisture": 50.0,
        "soil_ph": 6.5, "light_intensity": 1000.0, "anomaly": False,
        "timestamp": datetime.utcnow().isoformat()
    }

def send_verification_email(email, token):
    msg = Message("Verify Your Email", sender=app.config['MAIL_USERNAME'], recipients=[email])
    link = url_for('verify_email', token=token, _external=True)
    msg.body = f"Please click the link to verify your email: {link}"
    mail.send(msg)
    return link

# Routes
@app.route('/')
def serve_index():
    return send_from_directory(BASE_DIR, 'index.html')

@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory(BASE_DIR, path)

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    role = data.get('role', 'user')
    secret_key = data.get('secret_key', '')

    users = load_users()
    if username in users:
        return jsonify({"message": "Username already exists"}), 400
    if any(u['email'] == email for u in users.values()):
        return jsonify({"message": "Email already exists"}), 400
    if role == 'admin' and secret_key != 'your_admin_secret':  # Replace with a secure secret
        return jsonify({"message": "Invalid secret key for admin"}), 403

    verification_token = secrets.token_urlsafe(32)
    users[username] = {
        "email": email,
        "password": generate_password_hash(password),
        "role": role,
        "is_verified": False,
        "verification_token": verification_token
    }
    save_users(users)

    verification_link = send_verification_email(email, verification_token)
    return jsonify({"message": "Registration successful, please verify your email", "verification_link": verification_link}), 201

@app.route('/api/verify/<token>')
def verify_email(token):
    users = load_users()
    for username, user in users.items():
        if user.get('verification_token') == token:
            user['is_verified'] = True
            user.pop('verification_token')
            save_users(users)
            return jsonify({"message": "Email verified successfully"}), 200
    return jsonify({"message": "Invalid or expired token"}), 400

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    users = load_users()
    user = users.get(username)
    if not user or not check_password_hash(user['password'], password):
        return jsonify({"message": "Invalid credentials"}), 401
    if not user.get('is_verified', False):
        return jsonify({"message": "Please verify your email first"}), 403

    session['user'] = username
    access_token = create_access_token(identity=username)
    return jsonify({
        "message": "Login successful",
        "token": access_token,
        "user": {"username": username, "email": user["email"], "role": user["role"], "is_verified": True}
    }), 200

@app.route('/api/google')
def google_login():
    if not google.authorized:
        return redirect(url_for('google.login'))
    resp = google.get("/plus/v1/people/me")
    assert resp.ok, resp.text
    google_info = resp.json()
    email = google_info["emails"][0]["value"]
    username = email.split('@')[0]

    users = load_users()
    if username not in users:
        users[username] = {
            "email": email,
            "password": generate_password_hash(secrets.token_urlsafe(16)),
            "role": "user",
            "is_verified": True
        }
        save_users(users)

    session['user'] = username
    access_token = create_access_token(identity=username)
    return redirect(url_for('serve_index'))

@app.route('/api/irrigation-data', methods=['GET'])
@jwt_required()
def get_irrigation_data():
    data = load_irrigation_data()
    return jsonify(data), 200

@app.route('/api/records', methods=['GET'])
@jwt_required()
def get_records():
    records = [f for f in os.listdir(RECORDS_DIR) if f.endswith('.docx')]
    return jsonify(records), 200

@app.route('/records/<filename>')
@jwt_required()
def download_record(filename):
    return send_from_directory(RECORDS_DIR, filename)

@app.route('/api/updateuser', methods=['POST'])
@jwt_required()
def update_user():
    username = get_jwt_identity()
    data = request.get_json()
    new_username = data.get('username')
    new_email = data.get('email')

    users = load_users()
    user = users.get(username)
    if not user:
        return jsonify({"message": "User not found"}), 404

    if new_username and new_username != username:
        if new_username in users:
            return jsonify({"message": "Username already taken"}), 400
        users[new_username] = users.pop(username)
        username = new_username

    if new_email and new_email != user['email']:
        if any(u['email'] == new_email for u in users.values()):
            return jsonify({"message": "Email already in use"}), 400
        user['email'] = new_email

    save_users(users)
    return jsonify({
        "message": "User updated successfully",
        "user": {"username": username, "email": user["email"], "role": user["role"], "is_verified": user["is_verified"]}
    }), 200

@app.route('/api/deleteaccount', methods=['POST'])
@jwt_required()
def delete_account():
    username = get_jwt_identity()
    data = request.get_json()
    password = data.get('password')

    users = load_users()
    user = users.get(username)
    if not user or not check_password_hash(user['password'], password):
        return jsonify({"message": "Invalid password"}), 401

    del users[username]
    save_users(users)
    session.pop('user', None)
    return jsonify({"message": "Account deleted successfully"}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000)
