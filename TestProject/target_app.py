import time
import os
import sys
from flask import Flask, jsonify, request

app = Flask(__name__)

LOCK_FILE = "app_state.lock"

@app.route("/")
def index():
    return jsonify({"status": "running", "app": "TestProject App", "version": "1.0.0"})

@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok", "time": time.time()})

@app.route("/api/process", methods=["POST"])
def process_data():
    data = request.get_json(force=True) or {}
    items = data.get("items", [])
    total = sum(items)
    return jsonify({"total": total, "count": len(items)})

@app.route("/chaos/crash-lock", methods=["GET"])
def crash_with_lock():
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    os._exit(1)

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001)
