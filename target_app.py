import os
import sys
import time
import logging
from flask import Flask, jsonify, request

# Ensure logs directory exists
LOG_DIR = os.environ.get("LOG_DIR", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Set up logger for app
log_file = os.path.join(LOG_DIR, "app.log")
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s"
)

app = Flask(__name__)
LEAK_BUFFER = []
LOCK_FILE = "app_state.lock"

@app.route("/")
def index():
    return jsonify({"status": "running", "service": "target_app", "version": "1.0.0"})

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "uptime": time.time()})

@app.route("/user", methods=["POST"])
def get_user_profile():
    data = request.get_json(force=True) or {}
    # Edge case bug: missing 'user_id' throws KeyError if null
    user_id = data["user_id"]
    return jsonify({"user_id": user_id, "name": f"User_{user_id}"})

@app.route("/chaos/leak", methods=["GET"])
def cause_memory_leak():
    global LEAK_BUFFER
    # Allocate 50MB per request
    LEAK_BUFFER.append(b"X" * (50 * 1024 * 1024))
    logging.warning(f"Memory leak injected. Current buffer blocks: {len(LEAK_BUFFER)}")
    return jsonify({"status": "leak_injected", "buffer_count": len(LEAK_BUFFER)})

@app.route("/chaos/lock-crash", methods=["GET"])
def cause_lock_crash():
    logging.critical("Lock crash chaos endpoint triggered!")
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    os._exit(1)

if __name__ == "__main__":
    print(f"=== Starting Target Application on http://127.0.0.1:5000 [PID: {os.getpid()}] ===")
    app.run(host="127.0.0.1", port=5000)
