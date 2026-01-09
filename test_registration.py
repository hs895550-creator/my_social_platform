
import requests
import sqlite3
import time
import subprocess
import sys
import os
import signal

# Configuration
BASE_URL = "http://127.0.0.1:8000"
DB_PATH = "social.db"

def start_server():
    """Start the FastAPI server in a subprocess."""
    print("Starting server...")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid
    )
    time.sleep(5)  # Wait for server to start
    return process

def stop_server(process):
    """Stop the server."""
    print("Stopping server...")
    os.killpg(os.getpgid(process.pid), signal.SIGTERM)

def check_db_user(phone):
    """Check if user exists in DB."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id, phone, status FROM users WHERE phone = ?", (phone,))
    user = cursor.fetchone()
    conn.close()
    return user

def test_registration_flow():
    server_process = start_server()
    try:
        # 1. Send SMS Code
        phone = "+15550001"
        print(f"\n[Step 1] Sending code to {phone}...")
        try:
            resp = requests.post(f"{BASE_URL}/send_code", json={"phone": phone})
            if resp.status_code == 200:
                data = resp.json()
                print("Success:", data)
                code = data.get("debug_code")
            else:
                print("Failed:", resp.text)
                return
        except Exception as e:
            print(f"Connection failed: {e}")
            return

        if not code:
            print("Could not get debug code.")
            return

        # 2. Register
        print(f"\n[Step 2] Registering with code {code}...")
        # Note: /register expects form data
        form_data = {
            "phone": phone,
            "code": code,
            "password": "testpassword123",
            "gender": "male",
            "age_range": "30-35",
            "country": "United States (+1)",
            "agreement": "on" # Checkbox value
        }
        
        # We need to handle cookies for session
        session = requests.Session()
        resp = session.post(f"{BASE_URL}/register", data=form_data, allow_redirects=False)
        
        print(f"Registration Status: {resp.status_code}")
        if resp.status_code == 303:
            print(f"Redirected to: {resp.headers.get('Location')}")
            if "/verify" in resp.headers.get('Location'):
                print("✅ Registration Successful (Redirected to verification page)")
            else:
                print("❌ Registration Redirect Unexpected")
        else:
            print("❌ Registration Failed")
            print(resp.text)

        # 3. Verify Database
        print("\n[Step 3] Checking Database...")
        user = check_db_user(phone)
        if user:
            print(f"✅ User found in DB: ID={user[0]}, Phone={user[1]}, Status={user[2]}")
        else:
            print("❌ User NOT found in DB")

    finally:
        stop_server(server_process)

if __name__ == "__main__":
    test_registration_flow()
