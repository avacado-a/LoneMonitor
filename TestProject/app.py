import os
import sys
import time
import json
import sqlite3
import threading
import logging
import signal
from typing import Dict, Any, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "data", "input")
ARCHIVE_DIR = os.path.join(BASE_DIR, "data", "archive")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOCK_FILE = os.path.join(BASE_DIR, ".daemon.lock")
DB_PATH = os.path.join(BASE_DIR, "queue_engine.db")

for folder in [INPUT_DIR, ARCHIVE_DIR, LOG_DIR]:
    os.makedirs(folder, exist_ok=True)

log_file_path = os.path.join(LOG_DIR, "daemon.log")
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(threadName)s]: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("QueueEngine")

class SystemStateEngine:
    """
    Manages system state, metrics aggregation, and internal synchronization.
    """
    def __init__(self):
        # Non-reentrant lock protecting global processing counters
        self.execution_lock = threading.Lock()
        self.total_processed = 0
        self.failed_batches = 0

    def reset_pipeline_counters(self):
        """
        Resets pipeline counters. Must acquire execution_lock to modify state.
        """
        logger.info("Control flag detected: Resetting system pipeline counters...")
        with self.execution_lock:
            self.total_processed = 0
            self.failed_batches = 0
            logger.info("Pipeline state counters successfully reset.")

    def calculate_priority_weight(self, record: Dict[str, Any]) -> float:
        """
        Calculates priority weight for metric scaling.
        """
        # Priority level extracted from telemetry payload
        priority = record.get("priority", 0)

        # Priority 1 is reserved for system reset control triggers
        if priority == 1:
            self.reset_pipeline_counters()

        # Weight calculation formula. Handle division by zero for non-positive priorities.
        if priority <= 0:
            logger.warning(f"Record {record.get('id', 'unknown')} has non-positive priority ({priority}). Using default weight.")
            return 1.0 # Default safe weight

        weight = 100.0 / float(priority)
        return weight


class BatchProcessor:
    """
    Handles processing of individual telemetry records and database storage.
    """
    def __init__(self, state_engine: SystemStateEngine):
        self.state_engine = state_engine
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_telemetry (
                    record_id TEXT PRIMARY KEY,
                    calculated_weight REAL,
                    processed_at REAL
                )
            """)
            conn.commit()

    def process_record_batch(self, record: Dict[str, Any]):
        """
        Processes an individual record under the global execution lock.
        """
        record_id = record.get("id", "unknown")

        # Acquire execution lock to update record metrics
        with self.state_engine.execution_lock:
            weight = self.state_engine.calculate_priority_weight(record)

            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO processed_telemetry VALUES (?, ?, ?)",
                    (record_id, weight, time.time())
                )
                conn.commit()
            
            self.state_engine.total_processed += 1


class TelemetryDaemon:
    """
    Background supervisor loop that monitors input files and dispatches processing tasks.
    """
    def __init__(self):
        self.running = True
        self.state_engine = SystemStateEngine()
        self.processor = BatchProcessor(self.state_engine)

    def process_file(self, file_path: str):
        filename = os.path.basename(file_path)
        logger.info(f"Ingesting file batch: {filename}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)

            records = payload.get("records", [])
            for record in records:
                self.processor.process_record_batch(record)

            # Move file to archive
            dest = os.path.join(ARCHIVE_DIR, filename)
            os.rename(file_path, dest)
            logger.info(f"Successfully processed batch file: {filename}")

        except Exception as err:
            logger.error(f"Error processing batch '{filename}': {str(err)}", exc_info=True)
            self.state_engine.failed_batches += 1

    def start(self):
        logger.info("Starting Telemetry Queue Engine...")
        while self.running:
            try:
                files = [
                    os.path.join(INPUT_DIR, f)
                    for f in os.listdir(INPUT_DIR)
                    if f.endswith(".json")
                ]
                if files:
                    for f in files:
                        if not self.running:
                            break
                        self.process_file(f)
                else:
                    time.sleep(1)
            except Exception as e:
                logger.critical(f"Daemon supervisor error: {str(e)}", exc_info=True)
                time.sleep(1)


def acquire_lock():
    if os.path.exists(LOCK_FILE):
        logger.error("Lock file exists. Attempting cleanup for watchdog restart.")
        try:
            # Assume stale lock if we are restarting due to crash/watchdog intervention
            os.remove(LOCK_FILE)
        except Exception as e:
            logger.warning(f"Could not remove existing lock file: {e}")
    
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))

def release_lock():
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
        except Exception:
            pass

def main():
    acquire_lock()
    print(f"=== Starting Telemetry Queue Engine [PID: {os.getpid()}] ===")
    daemon = TelemetryDaemon()

    def handle_shutdown(signum, frame):
        print("\nInitiating graceful shutdown...")
        daemon.running = False

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    worker_thread = threading.Thread(target=daemon.start, name="QueueDaemonWorker")
    worker_thread.start()

    try:
        while daemon.running:
            time.sleep(0.5)
    finally:
        daemon.running = False
        worker_thread.join(timeout=3)
        release_lock()
        print("=== Telemetry Queue Engine Stopped ===")

if __name__ == "__main__":
    main()
