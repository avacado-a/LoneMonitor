import os
import sys
import time
import subprocess
import requests

# Add parent directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from payload_builder import build_payload
import tier2_engine
import sandbox_runner

TEST_APP_PATH = os.path.join(os.path.dirname(__file__), "target_app.py")
TARGET_URL = "http://127.0.0.1:5001"

def run_test():
    print("==================================================")
    print("    TESTING SELF-HEALING FRAMEWORK ON TestProject")
    print("==================================================")

    # Step 1: Launch target application
    print("\n[Step 1] Launching TestProject/target_app.py...")
    proc = subprocess.Popen(
        [sys.executable, TEST_APP_PATH],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    time.sleep(2)

    try:
        # Check health
        r = requests.get(f"{TARGET_URL}/healthz", timeout=2)
        print(f"Health check: {r.json()}")

        # Step 2: Trigger KeyError
        print("\n[Step 2] Sending malformed payload to trigger unhandled KeyError...")
        try:
            res = requests.post(f"{TARGET_URL}/api/process", json={"wrong_key": 123}, timeout=3)
            print(f"Response code: {res.status_code}")
        except Exception as e:
            print(f"Request exception: {e}")

        # Simulate Tier 1 log capture & diagnostic snapshot
        stack_trace = """
Traceback (most recent call last):
  File "flask/app.py", line 1477, in __call__
  File "TestProject/target_app.py", line 22, in process_data
    items = data["items"]
KeyError: 'items'
"""
        recent_logs = [
            "[INFO] Starting server on port 5001",
            "[POST /api/process] Received payload: {'wrong_key': 123}",
            "[ERROR] KeyError: 'items' in TestProject/target_app.py at line 22"
        ]

        print("\n[Step 3] Building Tier 1 Diagnostic Snapshot...")
        payload = build_payload(
            error_type="Unhandled KeyError Exception",
            stack_trace=stack_trace,
            recent_logs=recent_logs,
            affected_files=["TestProject/target_app.py"],
            pid=proc.pid
        )

        # Step 4: Dispatch to Tier 2 AI Engine (via ai.py)
        print("\n[Step 4] Invoking Tier 2 AI Repair Engine (via ai.py)...")
        repair_res = tier2_engine.analyze_and_patch(payload)
        print(f"Repair Result Status: {repair_res.get('status')}")

        if repair_res.get("status") == "patch_generated":
            diff = repair_res["diff"]
            print("\n--- Generated Git Patch ---")
            print(diff)
            print("---------------------------")

            # Step 5: Test & Apply in Sandbox
            print("\n[Step 5] Validating & applying patch in isolated sandbox...")
            success = sandbox_runner.test_and_apply_patch(diff, target_repo_dir=".")
            print(f"Sandbox Verification Success: {success}")

            if success:
                print("\n[Step 6] Patch applied! Restarting target app to verify fix...")
                proc.kill()
                time.sleep(1)
                proc = subprocess.Popen(
                    [sys.executable, TEST_APP_PATH],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                time.sleep(2)

                print("Re-testing /api/process endpoint with malformed payload...")
                retry_res = requests.post(f"{TARGET_URL}/api/process", json={"wrong_key": 123}, timeout=3)
                print(f"New Response Code: {retry_res.status_code}")
                print(f"New Response Body: {retry_res.text}")
                
                if retry_res.status_code in [200, 400]:
                    print("\nSUCCESS: Target application self-healed and handles missing parameters gracefully!")
        else:
            print(f"Repair failed: {repair_res}")

    finally:
        if proc:
            proc.kill()

if __name__ == "__main__":
    run_test()
