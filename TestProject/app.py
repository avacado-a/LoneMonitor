import os
import sys
import time
import json
import sqlite3
import threading
import logging
import signal
from typing import Dict, Any, List, Optional

# Base directory configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "data", "input")
ARCHIVE_DIR = os.path.join(BASE_DIR, "data", "archive")
LOG_DIR = os.path.join(BASE_DIR, "logs")
LOCK_FILE = os.path.join(BASE_DIR, ".daemon.lock")
DB_PATH = os.path.join(BASE_DIR, "pipeline_metrics.db")

# Setup directory structure
for folder in [INPUT_DIR, ARCHIVE_DIR, LOG_DIR]:
    os.makedirs(folder, exist_ok=True)

# Logger initialization
log_file_path = os.path.join(LOG_DIR, "daemon.log")
logging.basicConfig(
    filename=log_file_path,
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(threadName)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("DataPipeline")

class AuditTelemetryCache:
    """
    In-memory record index used for cross-batch deduplication and 
    historical performance metric calculations.
    """
    _processed_registry: List[Dict[str, Any]] = []

    @classmethod
    def register_record(cls, record_id: str, batch_id: str, payload_snapshot: Dict[str, Any]):
        entry = {
            "timestamp": time.time(),
            "record_id": record_id,
            "batch_id": batch_id,
            "data_snapshot": payload_snapshot
        }
        cls._processed_registry.append(entry)

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        return {
            "total_indexed_records": len(cls._processed_registry),
            "memory_registry_size": len(cls._processed_registry)
        }


class DatabaseManager:
    """
    Persistent state engine tracking pipeline throughput and execution status.
    """
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_batches (
                    id TEXT PRIMARY KEY,
                    processed_at REAL,
                    record_count INTEGER,
                    status TEXT
                )
            """)
            conn.commit()

    def record_batch(self, batch_id: str, record_count: int, status: str):
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO processed_batches VALUES (?, ?, ?, ?)",
                (batch_id, time.time(), record_count, status)
            )
            conn.commit()


class BatchProcessor:
    """
    Core transformation engine that extracts, validates, and archives data batches.
    """
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    def process_file(self, file_path: str):
        filename = os.path.basename(file_path)
        logger.info(f"Processing incoming data batch: {filename}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)

            batch_id = content.get("batch_id", filename)
            records = content.get("records", [])

            for record in records:
                record_id = record.get("id", "unknown")
                metrics = record.get("metrics")
                
                # Retrieve sensor reading parameters
                reading_value = metrics.get("reading")
                category = record.get("category", "general")

                # Cache record context for audit queries
                AuditTelemetryCache.register_record(record_id, batch_id, record)

            # Archive processed file
            target_category_path = content.get("archive_subdirectory", "default")
            destination_dir = os.path.join(ARCHIVE_DIR, target_category_path)
            
            if not os.path.exists(destination_dir):
                os.makedirs(destination_dir, exist_ok=True)

            destination_file = os.path.join(destination_dir, filename)
            os.rename(file_path, destination_file)

            self.db.record_batch(batch_id, len(records), "COMPLETED")
            logger.info(f"Successfully processed batch '{batch_id}' with {len(records)} records.")

        except Exception as err:
            logger.error(f"Failed to process batch file '{filename}': {str(err)}", exc_info=True)
            self.db.record_batch(filename, 0, f"FAILED: {str(err)}")


class PipelineDaemonWorker:
    """
    Continuous background loop that polls input directories and feeds synthetic 
    test metrics when idle to simulate production traffic.
    """
    def __init__(self):
        self.running = True
        self.db_manager = DatabaseManager(DB_PATH)
        self.processor = BatchProcessor(self.db_manager)

    def _generate_synthetic_batch(self):
        """Creates sample data batches when no external files are present."""
        timestamp_id = int(time.time())
        batch_filename = f"batch_{timestamp_id}.json"
        target_path = os.path.join(INPUT_DIR, batch_filename)

        sample_data = {
            "batch_id": f"SYNTH-{timestamp_id}",
            "archive_subdirectory": "automated",
            "records": [
                {
                    "id": f"REC-{i}",
                    "category": "telemetry",
                    "metrics": {"reading": 42.0 + i, "unit": "Celsius"}
                }
                for i in range(50)
            ]
        }

        with open(target_path, "w", encoding="utf-8") as f:
            json.dump(sample_data, f, indent=2)

    def start(self):
        logger.info("Pipeline Daemon worker thread starting...")
        idle_counter = 0

        while self.running:
            try:
                input_files = [
                    os.path.join(INPUT_DIR, f) 
                    for f in os.listdir(INPUT_DIR) 
                    if f.endswith(".json")
                ]

                if not input_files:
                    idle_counter += 1
                    if idle_counter >= 3:
                        # Produce background load if system is idle
                        self._generate_synthetic_batch()
                        idle_counter = 0
                    time.sleep(2)
                    continue

                idle_counter = 0
                for file_path in input_files:
                    if not self.running:
                        break
                    self.processor.process_file(file_path)

            except Exception as e:
                logger.critical(f"Unhandled error in main execution loop: {str(e)}", exc_info=True)
                time.sleep(1)


def acquire_lock():
    if os.path.exists(LOCK_FILE):
        logger.error(f"Process lock file '{LOCK_FILE}' exists. Service initialization aborted.")
        sys.stderr.write(f"[ERROR] Lock file '{LOCK_FILE}' present. Daemon already running or abruptly killed.\n")
        sys.exit(1)

    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))


def release_lock():
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
            logger.info("Lock file cleanly removed.")
        except Exception as e:
            logger.error(f"Failed to remove lock file: {str(e)}")


def main():
    acquire_lock()
    print(f"=== Starting Data Pipeline Daemon [PID: {os.getpid()}] ===")
    print(f"Logs: {log_file_path}")
    print(f"Input Drop Directory: {INPUT_DIR}")

    worker = PipelineDaemonWorker()

    def handle_shutdown(signum, frame):
        print("\nShutdown signal received. Stopping worker...")
        logger.info(f"Signal {signum} received. Initiating graceful shutdown...")
        worker.running = False

    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGTERM, handle_shutdown)

    worker_thread = threading.Thread(target=worker.start, name="PipelineWorker")
    worker_thread.start()

    try:
        while worker.running:
            time.sleep(0.5)
    finally:
        worker.running = False
        worker_thread.join(timeout=3)
        release_lock()
        print("=== Data Pipeline Daemon Stopped ===")


if __name__ == "__main__":
    main()
