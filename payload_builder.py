import datetime
import os
import subprocess
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

def get_git_commit():
    try:
        res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception:
        return "unknown"

def build_payload(error_type: str, stack_trace: str, recent_logs: list, affected_files: list = None, pid: int = None):
    system_metrics = {}
    if HAS_PSUTIL and pid and psutil.pid_exists(pid):
        try:
            proc = psutil.Process(pid)
            system_metrics["cpu_percent"] = proc.cpu_percent(interval=0.1)
            system_metrics["memory_mb"] = proc.memory_info().rss / (1024 * 1024)
            system_metrics["total_ram_percent"] = psutil.virtual_memory().percent
        except Exception:
            pass
    else:
        system_metrics["total_ram_percent"] = 50.0  # Fallback estimate

    return {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "error_type": error_type,
        "stack_trace": stack_trace,
        "recent_logs": recent_logs[-200:],
        "git_commit": get_git_commit(),
        "affected_files": affected_files or ["target_app.py"],
        "system_metrics": system_metrics
    }
