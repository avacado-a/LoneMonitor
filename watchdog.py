import os
import sys
import time
import glob
import subprocess
import threading
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

import tier2_engine

TARGET_SCRIPT = os.environ.get("TARGET_SCRIPT", "target_app.py")
LOG_DIR = os.environ.get("LOG_DIR", "logs")
HEALTH_URL = os.environ.get("HEALTH_URL", None)

PROCESS_MEM_LIMIT_MB = 200.0  # RSS limit
SYSTEM_RAM_THRESHOLD_PERCENT = 85.0
STALE_LOCKS = [".daemon.lock", ".app.lock", "app_state.lock", "app.pid"]
CRITICAL_LOG_PATTERNS = ["MemoryError", "OutOfMemory", "Traceback (most recent call last)"]

class Watchdog:
    """
    Tier 1 Fast Supervisor:
    Process lifecycle monitoring, PID tracking, RSS memory caps, real-time stderr/log matching,
    stale lock cleanup, and instant process containment (<500ms).
    """
    def __init__(self):
        self.process = None
        self.recent_logs = []
        self.is_running = True
        self.remedying = False
        self.detected_critical_log = None
        self.log_file_offsets = {}

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
        
        threading.Thread(target=self._stream_output, args=(self.process.stdout, "STDOUT"), daemon=True).start()
        threading.Thread(target=self._stream_output, args=(self.process.stderr, "STDERR"), daemon=True).start()

    def _stream_output(self, stream, prefix):
        for line in iter(stream.readline, ''):
            if line:
                formatted = f"[{prefix}] {line.strip()}"
                self.recent_logs.append(formatted)
                print(formatted)
                
                if prefix == "STDERR":
                    for pat in CRITICAL_LOG_PATTERNS:
                        if pat in line and not self.detected_critical_log:
                            self.detected_critical_log = f"Critical error pattern '{pat}' detected in stderr logs."

    def _check_app_log_files(self):
        if not os.path.exists(LOG_DIR):
            return
        
        log_files = glob.glob(os.path.join(LOG_DIR, "*.log"))
        for log_path in log_files:
            try:
                current_size = os.path.getsize(log_path)
                last_offset = self.log_file_offsets.get(log_path, 0)
                
                # Prevent loading giant >10MB log files into RAM
                if current_size > 10 * 1024 * 1024:
                    last_offset = current_size - 50 * 1024
                
                if current_size > last_offset:
                    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                        f.seek(last_offset)
                        new_content = f.read()
                        self.log_file_offsets[log_path] = current_size

                        if "Traceback (most recent call last)" in new_content or "[ERROR]" in new_content or "AttributeError" in new_content or "TypeError" in new_content or "KeyError" in new_content or "ZeroDivisionError" in new_content:
                            if not self.detected_critical_log and not self.remedying:
                                self.detected_critical_log = f"Exception detected in log file '{log_path}':\n{new_content[-1000:]}"
                else:
                    self.log_file_offsets[log_path] = current_size
            except Exception:
                pass

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
        payload = tier2_engine.build_payload(
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
                    success = tier2_engine.test_and_apply_patch(diff)
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
        time.sleep(2)

        while self.is_running:
            time.sleep(0.5)
            self._check_app_log_files()

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

            if self.detected_critical_log:
                err_msg = self.detected_critical_log
                self.detected_critical_log = None
                self.log("CRITICAL LOG TRIGGER DETECTED!")
                self.hard_restart()
                self.trigger_tier2_remediation(
                    error_type="Application Log Exception Trigger",
                    stack_trace=err_msg
                )
                continue

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
                        self.log(f"ALERT: System RAM saturation ({sys_ram_pct}% > {SYSTEM_RAM_THRESHOLD_PERCENT}%)!")
                        self.hard_restart()
                        self.trigger_tier2_remediation(
                            error_type="High System Memory Saturation",
                            stack_trace=f"System RAM threshold exceeded: {sys_ram_pct}% total usage."
                        )
                        continue
                except Exception:
                    pass

if __name__ == "__main__":
    wd = Watchdog()
    wd.monitor()
