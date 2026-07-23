import os
import sys
import time
import subprocess
import requests
import psutil
import threading
from payload_builder import build_payload
import tier2_engine
import sandbox_runner

TARGET_SCRIPT = "target_app.py"
HEALTH_URL = "http://127.0.0.1:5000/healthz"
RAM_THRESHOLD_PERCENT = 85.0
STALE_LOCKS = ["app_state.lock", "app.pid"]

class Watchdog:
    def __init__(self):
        self.process = None
        self.recent_logs = []
        self.is_running = True
        self.remedying = False

    def log(self, msg: str):
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] [Tier 1 Watchdog] {msg}"
        print(entry)
        self.recent_logs.append(entry)

    def cleanup_stale_locks(self):
        for lock in STALE_LOCKS:
            if os.path.exists(lock):
                try:
                    os.remove(lock)
                    self.log(f"Cleaned up stale lock file: {lock}")
                except Exception as e:
                    self.log(f"Failed to remove stale lock {lock}: {e}")

    def start_target_app(self):
        self.cleanup_stale_locks()
        self.log(f"Starting target application '{TARGET_SCRIPT}'...")
        self.process = subprocess.Popen(
            [sys.executable, TARGET_SCRIPT],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )
        
        # Threads to record logs asynchronously
        threading.Thread(target=self._stream_output, args=(self.process.stdout, "STDOUT"), daemon=True).start()
        threading.Thread(target=self._stream_output, args=(self.process.stderr, "STDERR"), daemon=True).start()

    def _stream_output(self, stream, prefix):
        for line in iter(stream.readline, ''):
            if line:
                formatted = f"[{prefix}] {line.strip()}"
                self.recent_logs.append(formatted)
                print(formatted)

    def hard_restart(self):
        self.log("Performing immediate process containment & hard-restart...")
        if self.process:
            try:
                self.process.kill()
            except Exception:
                pass
        self.cleanup_stale_locks()
        time.sleep(1)
        self.start_target_app()

    def trigger_tier2_remediation(self, error_type: str, stack_trace: str):
        if self.remedying:
            return
        self.remedying = True
        
        self.log("Dispatching diagnostic payload to Tier 2 AI Engineer...")
        payload = build_payload(
            error_type=error_type,
            stack_trace=stack_trace,
            recent_logs=self.recent_logs,
            affected_files=[TARGET_SCRIPT],
            pid=self.process.pid if self.process else None
        )

        def _async_worker():
            try:
                res = tier2_engine.analyze_and_patch(payload)
                if res.get("status") == "patch_generated":
                    diff = res["diff"]
                    self.log("Patch received from Tier 2. Testing in isolated sandbox...")
                    success = sandbox_runner.test_and_apply_patch(diff)
                    if success:
                        self.log("Patch successfully verified and merged! Reloading target application...")
                        self.hard_restart()
                    else:
                        self.log("Patch verification failed in sandbox.")
                else:
                    self.log(f"Tier 2 remediation skipped or failed: {res}")
            finally:
                self.remedying = False

        threading.Thread(target=_async_worker, daemon=True).start()

    def monitor(self):
        self.start_target_app()
        time.sleep(2)  # Give app time to spin up

        while self.is_running:
            time.sleep(1)
            
            # Check 1: Process Exit
            if self.process.poll() is not None:
                exit_code = self.process.returncode
                self.log(f"Target process died unexpectedly with exit code {exit_code}!")
                
                # Snapshot stack trace from logs
                stderr_logs = "\n".join([l for l in self.recent_logs if "[STDERR]" in l])
                
                # Immediate Tier 1 Containment & Restart
                self.hard_restart()
                
                # Async Tier 2 dispatch
                self.trigger_tier2_remediation(
                    error_type=f"Unexpected Process Exit (Code {exit_code})",
                    stack_trace=stderr_logs or "Process terminated without explicit exception stack trace."
                )
                continue

            # Check 2: System Memory Threshold
            mem_pct = psutil.virtual_memory().percent
            if mem_pct > RAM_THRESHOLD_PERCENT:
                self.log(f"ALERT: Memory usage saturation ({mem_pct}% > {RAM_THRESHOLD_PERCENT}%)!")
                self.hard_restart()
                self.trigger_tier2_remediation(
                    error_type="High Memory Saturation / Potential Memory Leak",
                    stack_trace=f"RAM threshold exceeded: {mem_pct}% total system usage."
                )
                continue

            # Check 3: Health Endpoint Heartbeat
            try:
                r = requests.get(HEALTH_URL, timeout=1.5)
                if r.status_code != 200:
                    self.log(f"Healthz returned status code {r.status_code}!")
                    self.hard_restart()
            except Exception as e:
                # App unresponsive
                pass

if __name__ == "__main__":
    wd = Watchdog()
    wd.monitor()
