# 🛡 LoneMonitor: Two-Tier Self-Healing AI Engine

LoneMonitor is a lightweight, high-performance **Two-Tier Self-Healing System** for long-running Python daemons and background services. 

It combines **Tier 1 (Fast Deterministic Process Containment)** with **Tier 2 (Sandboxed AI Hot-Fix Patching)** to achieve automatic incident detection, sandbox patch validation, and live service restoration without manual intervention.

---

## 📐 Architecture Overview

```
                          ┌───────────────────────────┐
                          │   Target Application      │
                          │     (target_app.py)       │
                          └─────────────┬─────────────┘
                                        │ (stderr / logs / RSS mem)
                                        ▼
                          ┌───────────────────────────┐
                          │  Tier 1 Fast Watchdog     │  <-- <500ms Containment & Hard Restart
                          │       (watchdog.py)       │
                          └─────────────┬─────────────┘
                                        │ (Diagnostic Payload)
                                        ▼
                          ┌───────────────────────────┐
                          │   Tier 2 AI Engine        │  <-- Generates Unified Git Diff via ai.py
                          │     (tier2_engine.py)     │
                          └─────────────┬─────────────┘
                                        │
                                        ▼
                          ┌───────────────────────────┐
                          │   Isolated Sandbox        │  <-- Verifies Git Apply & Syntax Compilation
                          └─────────────┬─────────────┘
                                        │ (Merge & Hot-Reload)
                                        ▼
                          ┌───────────────────────────┐
                          │  Production Code Restored │
                          └───────────────────────────┘
```

---

## ⚡ Key Features

- **Tier 1 Fast Containment (<500ms)**:
  - Tracks child process PID, RSS memory caps (200MB limit), and system RAM thresholds.
  - Monitors `sys.stderr` and application `.log` files for critical exception patterns (`MemoryError`, `Traceback`, `AttributeError`, `ZeroDivisionError`, etc.).
  - Auto-cleans stale lock files (`.daemon.lock`, `.app.lock`, `app.pid`) upon process termination.
- **Tier 2 AI Hot-Fix Engine**:
  - Packages JSON diagnostic snapshots (stack traces, memory metrics, recent logs, git commits).
  - Enforces strict Unified Git Diff constraints ($\le 50$ lines changed, no full rewrites).
  - **Circuit Breaker**: Prevents infinite repair loops by capping patch attempts per module.
- **Isolated Sandbox Verification**:
  - Copies production code to an isolated temporary sandbox (`tempfile.mkdtemp`).
  - Auto-calculates unified diff hunk chunk headers (`@@ -old,count +new,count @@`).
  - Verifies patch compilation via `py_compile` before merging into production.

---

## 📂 Streamlined Repository Structure

| File | Description |
| :--- | :--- |
| `watchdog.py` | Tier 1 Fast Process Supervisor & Memory Cap Monitor |
| `tier2_engine.py` | Tier 2 AI Engine, Diagnostic Payload Builder & Sandbox Verification |
| `ai.py` | External AI Interface (`ai.request(messages, temperature)`) |
| `target_app.py` | Sample Target Application Template |

---

## 🚀 Quick Start

### 1. Run the Watchdog Supervisor

```bash
python watchdog.py
```

### 2. Configure Environment Options (Optional)

```bash
export TARGET_SCRIPT="target_app.py"
export LOG_DIR="logs"
export HEALTH_URL="http://localhost:8000/healthz"
```

---

## 📜 License

MIT License. Designed for high-reliability background infrastructure.
