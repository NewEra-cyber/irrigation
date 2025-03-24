from flask import Flask, jsonify, send_from_directory, request, session
import os
import json
import time
import threading
import sys
import shutil
from datetime import datetime
from docx import Document
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "your_secret_key"  # Change this to a secure secret key

# Define paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECORDS_DIR = os.path.join(BASE_DIR, 'records')
DATA_FILE = os.path.join(BASE_DIR, 'irrigation_data.json')
USER_DATA_FILE = os.path.join(BASE_DIR, 'users.json')

# Ensure the records directory exists
if not os.path.exists(RECORDS_DIR):
    os.makedirs(RECORDS_DIR)
else:
    # Delete all existing records in the records directory at startup
    print("Deleting existing records...")
    for filename in os.listdir(RECORDS_DIR):
        file_path = os.path.join(RECORDS_DIR, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")
    print("Existing records deleted.")

# Ensure the users file exists
if not os.path.exists(USER_DATA_FILE):
    with open(USER_DATA_FILE, "w") as f:
        json.dump({}, f)

# -------------------- Multi-user Authentication -------------------- #
def load_users():
    with open(USER_DATA_FILE, "r") as f:
        return json.load(f)

def save_users(users):
    with open(USER_DATA_FILE, "w") as f:
        json.dump(users, f, indent=4)

@app.route("/api/register", methods=["POST"])
def register():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    if not username or not password:
        return jsonify({"message": "Username and password required"}), 400
    users = load_users()
    if username in users:
        return jsonify({"message": "Username already exists"}), 400
    users[username] = {"password": generate_password_hash(password)}
    save_users(users)
    return jsonify({"message": "User registered successfully"}), 201

@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    users = load_users()
    if username not in users or not check_password_hash(users[username]["password"], password):
        return jsonify({"message": "Invalid credentials"}), 401
    session["user"] = username
    return jsonify({"message": "Login successful", "user": username})

@app.route("/api/logout", methods=["POST"])
def logout():
    session.pop("user", None)
    return jsonify({"message": "Logged out successfully"})

@app.route("/api/user", methods=["GET"])
def get_user():
    if "user" in session:
        return jsonify({"user": session["user"]})
    return jsonify({"message": "Not logged in"}), 401

# -------------------- Original Functionality -------------------- #
def load_irrigation_data():
    try:
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading irrigation data: {e}")
        return {
            "temperature": 25.0,
            "humidity": 60.0,
            "soilMoisture": 30.0,
            "soilPH": 6.5,
            "lightIntensity": 500.0,
            "anomaly": False
        }

def save_record(data):
    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    filename = f"record_{timestamp}.docx"
    filepath = os.path.join(RECORDS_DIR, filename)
    doc = Document()
    doc.add_heading('Irrigation Record', 0)
    doc.add_paragraph(f"Timestamp: {timestamp}")
    doc.add_paragraph(f"Temperature: {data['temperature']} °C")
    doc.add_paragraph(f"Humidity: {data['humidity']} %")
    doc.add_paragraph(f"Soil Moisture: {data['soilMoisture']} %")
    doc.add_paragraph(f"Soil pH: {data['soilPH']}")
    doc.add_paragraph(f"Light Intensity: {data['lightIntensity']} lux")
    doc.add_paragraph(f"Anomaly: {data['anomaly']}")
    doc.save(filepath)
    print(f"Saved record: {filename}")

def save_records_periodically():
    while True:
        data = load_irrigation_data()
        save_record(data)
        time.sleep(20 * 60)  # Sleep for 20 minutes

# Start the background task to save records
threading.Thread(target=save_records_periodically, daemon=True).start()

# Function to terminate the script after 50 minutes
def terminate_script():
    print("50 minutes elapsed. Terminating script...")
    os._exit(0)  # Forcefully exit the script

# Schedule script termination after 50 minutes (3000 seconds)
threading.Timer(3000, terminate_script).start()
print("Script will terminate automatically after 50 minutes.")

@app.route('/api/irrigation-data')
def get_irrigation_data():
    data = load_irrigation_data()
    return jsonify(data)

@app.route('/api/records')
def list_records():
    records = [f for f in os.listdir(RECORDS_DIR) if f.endswith('.docx')]
    return jsonify(records)

@app.route('/', defaults={'path': 'index.html'})
@app.route('/<path:path>')
def serve_static(path):
    return send_from_directory(BASE_DIR, path)

@app.route('/records/<filename>')
def serve_record(filename):
    return send_from_directory(RECORDS_DIR, filename)

if __name__ == '__main__':
    try:
        app.run(host='0.0.0.0', port=8000, debug=False)
    except KeyboardInterrupt:
        print("Server terminated manually.")
        sys.exit(0)
