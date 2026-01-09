
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
    # Using python -m uvicorn to ensure we use the same python environment
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        preexec_fn=os.setsid  # Create a new process group for easier cleanup
    )
    time.sleep(5)  # Wait for server to start
    return process

def stop_server(process):
    """Stop the server."""
    print("Stopping server...")
    os.killpg(os.getpgid(process.pid), signal.SIGTERM)

def test_registration_flow():
    # 1. Send SMS Code
    phone = "+15550001"
    print(f"\n[Step 1] Sending code to {phone}...")
    try:
        resp = requests.post(f"{BASE_URL}/send_code", json={"phone": phone})
        if resp.status_code == 200:
            print("Success:", resp.json())
        else:
            print("Failed:", resp.text)
            return
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    # 2. Get the code from the server logs or by cheating (since we are local)
    # Since we can't easily read the server stdout in real-time effectively without blocking,
    # let's modify main.py temporarily OR just rely on the fact that for testing 
    # we might need to peek into the memory/print. 
    # Actually, main.py prints "DEBUG: SMS Code for ...".
    # But for this test script, I can't easily read that stdout.
    # ALTERNATIVE: I can inspect the SMS_CODES dict if I could import main, 
    # but main runs in a separate process.
    # HACK: Let's use a fixed code for testing or just read the code logic.
    # main.py uses random.randint(100000, 999999).
    # I can't guess it.
    
    # REVISED STRATEGY: 
    # I will rely on the fact that I can't automate the code retrieval easily without modifying the code.
    # However, I can Modify main.py to print the code to a file, or return it in the response for DEBUG mode.
    pass

if __name__ == "__main__":
    # verification is hard without the code.
    print("This script is a placeholder. I need to run the server and test manually or modify code to expose the OTP.")
