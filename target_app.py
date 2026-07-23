import time
import os
import sys
from flask import Flask, jsonify, request

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
    user_id = data["user_id"]
    return jsonify({"user_id": user_id, "name": f"User_{user_id}"})

@app.route("/chaos/leak", methods=["GET"])
def cause_memory_leak():
    global LEAK_BUFFER
    LEAK_BUFFER.append(b"X" * (50 * 1024 * 1024))
    return jsonify({"status": "leak_injected", "buffer_count": len(LEAK_BUFFER)})

@app.route("/chaos/lock-crash", methods=["GET"])
def cause_lock_crash():
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    os._exit(1)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
