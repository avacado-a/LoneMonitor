import os
import sys
import time
import subprocess
import requests
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False
import threading
from payload_builder import build_payload
import tier2_engine
import sandbox_runner

TARGET_SCRIPT = os.path.join("TestProject", "app.py")
HEALTH_URL = None
PROCESS_MEM_LIMIT_MB = 200.0  # Trigger containment if target process exceeds 200MB RSS
SYSTEM_RAM_THRESHOLD_PERCENT = 80.0
STALE_LOCKS = [".daemon.lock", ".app.lock", "app_state.lock", "app.pid"]

CRITICAL_LOG_PATTERNS = ["MemoryError", "OutOfMemory", "Traceback (most recent call last)"]

class Watchdog:
    def __init__(self):
        self.process = None
        self.recent_logs = []
        self.is_running = True
        self.remedying = False
        self.detected_critical_log = None

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
        self.detected_critical_log = None
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
                
                # Instant log pattern detection for memory errors / unhandled crashes
                if prefix == "STDERR":
                    for pat in CRITICAL_LOG_PATTERNS:
                        if pat in line and not self.detected_critical_log:
                            self.detected_critical_log = f"Critical error pattern '{pat}' detected in stderr logs."

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
            time.sleep(0.5)
            
            # Check 1: Process Exit
            if self.process.poll() is not None:
                exit_code = self.process.returncode
                self.log(f"Target process died unexpectedly with exit code {exit_code}!")
                stderr_logs = "\n".join([l for l in self.recent_logs if "[STDERR]" in l])
                self.hard_restart()
                self.trigger_tier2_remediation(
                    error_type=f"Unexpected Process Exit (Code {exit_code})",
                    stack_trace=stderr_logs or "Process terminated without explicit exception stack trace."
                )
                continue

            # Check 2: Instant Critical Log Trigger (e.g. MemoryError in stderr)
            if self.detected_critical_log:
                err_msg = self.detected_critical_log
                self.detected_critical_log = None
                self.log(f"CRITICAL LOG TRIGGER: {err_msg}")
                stderr_logs = "\n".join([l for l in self.recent_logs if "[STDERR]" in l][-50:])
                self.hard_restart()
                self.trigger_tier2_remediation(
                    error_type="Critical Log Error / Memory Error",
                    stack_trace=stderr_logs or err_msg
                )
                continue

            # Check 3: Process & System Memory Limits
            if HAS_PSUTIL and self.process and psutil.pid_exists(self.process.pid):
                try:
                    proc = psutil.Process(self.process.pid)
                    proc_mem_mb = proc.memory_info().rss / (1024 * 1024)
                    sys_ram_pct = psutil.virtual_memory().percent

                    if proc_mem_mb > PROCESS_MEM_LIMIT_MB:
                        self.log(f"ALERT: Target process RSS memory cap breached ({proc_mem_mb:.1f}MB > {PROCESS_MEM_LIMIT_MB}MB)!")
                        self.hard_restart()
                        self.trigger_tier2_remediation(
                            error_type="Target Process Memory Cap Exceeded",
                            stack_trace=f"Process {self.process.pid} reached {proc_mem_mb:.1f}MB RSS memory usage."
                        )
                        continue

                    if sys_ram_pct > SYSTEM_RAM_THRESHOLD_PERCENT:
                        self.log(f"ALERT: Total system RAM saturation ({sys_ram_pct}% > {SYSTEM_RAM_THRESHOLD_PERCENT}%)!")
                        self.hard_restart()
                        self.trigger_tier2_remediation(
                            error_type="High System Memory Saturation",
                            stack_trace=f"System RAM threshold exceeded: {sys_ram_pct}% total usage."
                        )
                        continue
                except Exception:
                    pass

            # Check 4: Health Endpoint Heartbeat
            if HEALTH_URL:
                try:
                    r = requests.get(HEALTH_URL, timeout=1.0)
                    if r.status_code != 200:
                        self.log(f"Healthz returned status code {r.status_code}!")
                        self.hard_restart()
                except Exception:
                    pass

if __name__ == "__main__":
    wd = Watchdog()
    wd.monitor()
