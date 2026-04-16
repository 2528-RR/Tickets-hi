from flask import Flask, render_template, request, redirect, session, jsonify
import psycopg2
from datetime import datetime, timedelta
import jwt
import requests
import random
import os

app = Flask(__name__)
app.secret_key = "super_secret_key_change_this"
JWT_SECRET = "jwt_secret_change_this"

# ✅ USE ENV VARIABLE (IMPORTANT)
DATABASE_URL = os.environ.get("postgresql://...@dpg-d7ghrjrbc2fs73bpu760-a.internal:5432/database_url_2bwr")

# -------- DATABASE -------- #
def get_db():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    try:
        conn = get_db()
        cur = conn.cursor()

        # USERS TABLE
        cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            email TEXT PRIMARY KEY,
            role TEXT
        );
        """)

        # 🔥 SCANS TABLE (PREVENT DUPLICATES)
        cur.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id SERIAL PRIMARY KEY,
            email TEXT,
            event TEXT,
            scanned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(email, event)
        );
        """)

        # Sample users
        cur.execute("""
        INSERT INTO users (email, role)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """, ('brothersreddy2009@gmail.com', 'student'))

        cur.execute("""
        INSERT INTO users (email, role)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
        """, ('mandasriramachandraraghavaredd@gmail.com', 'manager'))

        conn.commit()
        cur.close()
        conn.close()

    except Exception as e:
        print("DB INIT ERROR:", e)

# ✅ SAFE INIT
init_db()

# -------- EMAIL CONFIG -------- #
EMAILJS_SERVICE_ID = "service_rgxfs9o"
EMAILJS_TEMPLATE_ID = "template_7m5vyuj"
EMAILJS_USER_ID = "QTYpAJGfLL6Wx5GRt"
EMAILJS_PRIVATE_KEY = "S8ZCy-j38GyIAqvBSFjPU"

otp_store = {}

# -------- OTP -------- #
def generate_otp():
    return str(random.randint(1000, 9999))

def send_otp_email(email, otp):
    try:
        payload = {
            "service_id": EMAILJS_SERVICE_ID,
            "template_id": EMAILJS_TEMPLATE_ID,
            "user_id": EMAILJS_USER_ID,
            "accessToken": EMAILJS_PRIVATE_KEY,
            "template_params": {"to_email": email, "otp": otp}
        }
        response = requests.post("https://api.emailjs.com/api/v1.0/email/send", json=payload)
        return response.status_code == 200
    except:
        return False

# -------- AUTH -------- #
def login_user(email, role):
    session['email'] = email
    session['role'] = role

def is_student():
    return session.get('role') == 'student'

def is_manager():
    return session.get('role') == 'manager'

# -------- ROUTES -------- #
@app.route('/')
def index():
    return render_template('index.html')

# -------- LOGIN -------- #
@app.route('/login/<role>', methods=['GET', 'POST'])
def login(role):
    if request.method == 'POST':
        email = request.form['email']

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email=%s AND role=%s", (email, role))
        user = cur.fetchone()
        cur.close()
        conn.close()

        if not user:
            return render_template('login.html', step="enter", role=role, error="User not found")

        otp = generate_otp()
        otp_store[email] = otp

        if send_otp_email(email, otp):
            return render_template('login.html', step="verify", email=email, role=role)
        else:
            return render_template('login.html', step="enter", role=role, error="OTP failed")

    return render_template('login.html', step="enter", role=role)

# -------- VERIFY OTP -------- #
@app.route('/verify', methods=['POST'])
def verify():
    email = request.form['email']
    otp = request.form['otp']
    role = request.form['role']

    if otp_store.get(email) == otp:
        login_user(email, role)
        return redirect('/dashboard' if role == 'student' else '/scanner')

    return render_template('login.html', step="verify", email=email, role=role, error="Invalid OTP")

# -------- DASHBOARD -------- #
@app.route('/dashboard')
def dashboard():
    if not is_student():
        return redirect('/')
    return render_template('dashboard.html', email=session['email'])

# -------- GENERATE QR -------- #
@app.route('/generate-qr/<event>')
def generate_qr(event):
    if not is_student():
        return jsonify({"error": "Unauthorized"}), 401

    email = session['email']
    current_hour = datetime.now().hour

    if event == 'food' and current_hour >= 18:
        return jsonify({"error": "Lunch closed"}), 403

    if event == 'dj' and not (17 <= current_hour < 18):
        return jsonify({"error": "DJ only 5–6 PM"}), 403

    payload = {
        "email": email,
        "event": event,
        "exp": datetime.utcnow() + timedelta(seconds=30),
        "iat": datetime.utcnow()
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={token}"

    return jsonify({"qr": qr_url})

# -------- VALIDATE QR -------- #
@app.route('/validate', methods=['POST'])
def validate():
    if not is_manager():
        return jsonify({"error": "Unauthorized"}), 401

    token = request.json.get('token')

    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        email = decoded['email']
        event = decoded['event']
    except jwt.ExpiredSignatureError:
        return jsonify({"status": "Expired QR"})
    except jwt.InvalidTokenError:
        return jsonify({"status": "Invalid QR"})

    conn = get_db()
    cur = conn.cursor()

    # 🔥 PREVENT DUPLICATE ENTRY
    cur.execute("SELECT * FROM scans WHERE email=%s AND event=%s", (email, event))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({"status": "Already Used", "email": email})

    cur.execute("INSERT INTO scans (email, event) VALUES (%s, %s)", (email, event))
    conn.commit()

    cur.close()
    conn.close()

    return jsonify({
        "status": "Accepted",
        "email": email,
        "event": event,
        "time": str(datetime.now())
    })

# -------- LOGOUT -------- #
@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# -------- RUN -------- #
if __name__ == '__main__':
    app.run(debug=True)
