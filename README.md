# LoneMonitor: Two-Tiered Self-Healing AI System

A zero-maintenance, two-tiered self-healing infrastructure framework designed to maximize uptime while minimizing resource consumption.

---

## 🏗 Architecture Overview

```
┌────────────────────────────────────────────────────────┐
│                   UNMANAGED SYSTEM                     │
│                                                        │
│   ┌──────────────────┐        ┌──────────────────┐     │
│   │  Target Application│ ◄────► │  Tier 1 Watchdog │     │
│   │ (Minimal Overhead)│        │ (Dumb, Light, Fast)│     │
│   └──────────────────┘        ─────────┬────────┘     │
└─────────────────────────────────────────┼──────────────┘
                                          │ Incident Detected
                                          ▼ (Async Dispatch)
                                ┌──────────────────┐
                                │ Tier 2 AI Engine │
                                │ (Slow, Deep, Smart)
                                └──────────────────┘
```

- **Tier 1 (Fast Watchdog)**: Process supervisor daemon (<20MB RAM, <500ms latency). Monitors heartbeats, RAM limits (85%), crash exit codes, and performs instant process restarts & lock file cleanups.
- **Tier 2 (AI Cybersecurity & Ops Engineer)**: Asynchronous AI agent (using `ai.py`). Receives JSON diagnostic payloads, generates unified git diff patches ($\le 50$ lines), verifies them in isolated temp sandboxes, and merges them into production.

---

## 📁 System Components

| File | Purpose |
| :--- | :--- |
| [`target_app.py`](file:///C:/Users/sidhp/Documents/GitHub/LoneMonitor/target_app.py) | Target application containing endpoints & chaos triggers |
| [`watchdog.py`](file:///C:/Users/sidhp/Documents/GitHub/LoneMonitor/watchdog.py) | Tier 1 supervisor daemon (monitors, contains, restarts, dispatches) |
| [`payload_builder.py`](file:///C:/Users/sidhp/Documents/GitHub/LoneMonitor/payload_builder.py) | Assembles JSON diagnostic snapshot |
| [`tier2_engine.py`](file:///C:/Users/sidhp/Documents/GitHub/LoneMonitor/tier2_engine.py) | Tier 2 AI engine interface (uses `ai.py`, enforces diff size & circuit breakers) |
| [`sandbox_runner.py`](file:///C:/Users/sidhp/Documents/GitHub/LoneMonitor/sandbox_runner.py) | Runs git patch verification inside an isolated temp environment |
| [`chaos_test.py`](file:///C:/Users/sidhp/Documents/GitHub/LoneMonitor/chaos_test.py) | Controlled failure verification script |
| [`ai.py`](file:///C:/Users/sidhp/Documents/GitHub/LoneMonitor/ai.py) | Model interface (OpenAI / Local LLM client endpoint) |

---

## 🛡 Guardrails & Fail-Safes

1. **Diff Size Cap**: Modifications strictly capped at $\le 50$ lines.
2. **Circuit Breaker**: Capped at maximum 2 repair attempts per module before freezing auto-remediation.
3. **Sandbox Verification**: Patches must compile and pass syntax checks in a clean temporary clone before hitting main.

---

## 🚀 Running the System

### 1. Start Tier 1 Watchdog
```bash
python watchdog.py
```

### 2. Run Controlled Chaos Tests
In a separate terminal:

- **Test KeyError Crash**:
  ```bash
  python chaos_test.py keyerror
  ```
- **Test Stale Lock Cleanup**:
  ```bash
  python chaos_test.py lock
  ```
- **Test Memory Leak Saturation**:
  ```bash
  python chaos_test.py leak
  ```
