#!/usr/bin/env python3
"""Invalid-data SQLite database for tracking QC failures."""

import os
import sqlite3
import json
import requests
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from contextlib import contextmanager
import shutil

from astribot_dq.logger import g_logger
from astribot_dq.file_path import FilePath

MAX_INVALID_RECORDS_PER_TASK = 10
MAX_ALERT_COUNT = 100

# Feishu webhook URL from environment variable; falls back to empty string
FEISHU_WEBHOOK_URL = os.environ.get("ASTRIBOT_FEISHU_WEBHOOK_URL", "")


class InvalidDataDB:
    """Manages a SQLite database tracking invalid HDF5 files."""

    DB_VERSION = 1

    def __init__(self, db_dir: str):
        self.db_dir = db_dir
        self.db_path = os.path.join(db_dir, "invalid_data.db")
        os.makedirs(db_dir, exist_ok=True)
        self._init_database()
        self._migrate_database()
        g_logger.info(f"InvalidDataDB initialized at: {self.db_path}")

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            g_logger.error(f"Database operation failed: {e}")
            raise
        finally:
            conn.close()

    def _init_database(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS invalid_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_path TEXT NOT NULL,
                    invalid_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_size INTEGER,
                    detected_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    error_type TEXT DEFAULT 'timestamp_duplicate',
                    error_summary TEXT,
                    error_details TEXT,
                    status TEXT DEFAULT 'active',
                    rollback_time TIMESTAMP,
                    rollback_target TEXT,
                    notes TEXT,
                    task_name TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_detected_time ON invalid_records(detected_time)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_status ON invalid_records(status)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_file_name ON invalid_records(file_name)"
            )
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alert_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_name TEXT NOT NULL,
                    alert_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS report_retry_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL,
                    request_body TEXT NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    last_retry_time TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    error_message TEXT
                )
            """)
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_report_retry_queue_created_at ON report_retry_queue(created_at)"
            )
            cursor.execute("""
                INSERT OR REPLACE INTO metadata (key, value, updated_at)
                VALUES ('db_version', ?, CURRENT_TIMESTAMP)
            """, (str(self.DB_VERSION),))
            g_logger.info("Database tables initialized")

    def _migrate_database(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            self._add_column_if_not_exists(cursor, "invalid_records", "task_name", 'TEXT DEFAULT ""')

    def _add_column_if_not_exists(self, cursor, table_name, column_name, column_definition):
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = [col[1] for col in cursor.fetchall()]
        if column_name not in columns:
            cursor.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
            )
            g_logger.info(f"Added column '{column_name}' to '{table_name}'")

    def add_invalid_record(
        self, original_path: str, invalid_path: str, error_summary: str,
        error_details_list: List[Dict], file_size: Optional[int] = None,
        error_type: str = None, task_name: str = ""
    ) -> int:
        file_name = os.path.basename(original_path)
        if file_size is None and os.path.exists(invalid_path):
            file_size = os.path.getsize(invalid_path)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO invalid_records
                (original_path, invalid_path, file_name, file_size,
                 error_summary, error_details, error_type, task_name, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active')
            """, (
                original_path, invalid_path, file_name, file_size,
                error_summary, json.dumps(error_details_list, ensure_ascii=False),
                error_type, task_name,
            ))
            record_id = cursor.lastrowid
            cursor.execute(
                "SELECT COUNT(*) as count FROM invalid_records WHERE task_name = ?",
                (task_name,),
            )
            task_count = cursor.fetchone()["count"]
            g_logger.info(
                f"Added invalid record: {file_name} (ID: {record_id}), "
                f"task: {task_name}, count: {task_count}"
            )
            if task_count > MAX_INVALID_RECORDS_PER_TASK:
                cursor.execute(
                    "SELECT COUNT(*) as count FROM alert_records WHERE task_name = ?",
                    (task_name,),
                )
                if cursor.fetchone()["count"] == 0:
                    cursor.execute(
                        "SELECT file_name, error_type FROM invalid_records WHERE task_name = ? ORDER BY detected_time DESC",
                        (task_name,),
                    )
                    records_details = [
                        (row["file_name"], row["error_type"]) for row in cursor.fetchall()
                    ]
                    self._feishu_alert(task_name, records_details)
                    self._add_alert_record(cursor, task_name)
            return record_id

    def _feishu_alert(self, task_name: str, records_details: List[Tuple[str, str]]):
        try:
            file_details = []
            for file_name, error_type in records_details:
                file_details.append([
                    {"tag": "text", "text": f"  • {file_name}: {error_type or 'unknown'}"}
                ])
            content = [
                [{"tag": "text", "text": f"QC anomalies exceed {MAX_INVALID_RECORDS_PER_TASK}"}]
            ]
            content.extend(file_details)
            if not FEISHU_WEBHOOK_URL:
                g_logger.warning(f"Skipping Feishu alert for '{task_name}': ASTRIBOT_FEISHU_WEBHOOK_URL not set")
                return
            response = requests.post(
                FEISHU_WEBHOOK_URL,
                json={
                    "msg_type": "post",
                    "content": {
                        "post": {
                            "zh_cn": {
                                "title": f"QC anomaly: {task_name}",
                                "content": content,
                            }
                        }
                    },
                },
                timeout=2,
            )
            g_logger.info(f"Sent alert for task '{task_name}', response: {response.json()}")
        except Exception as e:
            g_logger.error(f"Failed to send alert for '{task_name}': {e}")

    def _add_alert_record(self, cursor, task_name: str):
        cursor.execute(
            "INSERT INTO alert_records (task_name, alert_time) VALUES (?, CURRENT_TIMESTAMP)",
            (task_name,),
        )
        g_logger.info(f"Added alert record for task '{task_name}'")
        cursor.execute("SELECT COUNT(*) as count FROM alert_records")
        total = cursor.fetchone()["count"]
        if total > MAX_ALERT_COUNT:
            delete_count = total - MAX_ALERT_COUNT
            cursor.execute(
                "DELETE FROM alert_records WHERE id IN (SELECT id FROM alert_records ORDER BY alert_time ASC LIMIT ?)",
                (delete_count,),
            )
            g_logger.info(f"Cleaned {delete_count} old alert records")

    def rollback_record(self, record_id: int, target_path: str, notes: Optional[str] = None) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT invalid_path, file_name, status FROM invalid_records WHERE id = ?",
                (record_id,),
            )
            row = cursor.fetchone()
            if not row:
                g_logger.error(f"Record not found: {record_id}")
                return False
            if row["status"] == "rolled_back":
                g_logger.warning(f"Record {record_id} already rolled back")
                return False
            if not os.path.exists(row["invalid_path"]):
                g_logger.error(f"Invalid file not found: {row['invalid_path']}")
                return False
            try:
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                shutil.move(row["invalid_path"], target_path)
                g_logger.info(f"Rolled back: {row['invalid_path']} -> {target_path}")
                cursor.execute("""
                    UPDATE invalid_records
                    SET status='rolled_back', rollback_time=CURRENT_TIMESTAMP,
                        rollback_target=?, notes=?, updated_at=CURRENT_TIMESTAMP
                    WHERE id=?
                """, (target_path, notes, record_id))
                return True
            except Exception as e:
                g_logger.error(f"Rollback failed: {e}")
                return False

    def get_record_by_id(self, record_id: int) -> Optional[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM invalid_records WHERE id = ?", (record_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def query_records(
        self, status: Optional[str] = None, days: Optional[int] = None, limit: int = 100
    ) -> List[Dict]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            query = "SELECT * FROM invalid_records WHERE 1=1"
            params = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if days:
                cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
                query += " AND detected_time >= ?"
                params.append(cutoff)
            query += " ORDER BY detected_time DESC LIMIT ?"
            params.append(limit)
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def get_statistics(self, days: Optional[int] = None) -> Dict:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            date_filter = ""
            params = []
            if days:
                cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
                date_filter = "WHERE detected_time >= ?"
                params.append(cutoff)
            cursor.execute(f"SELECT COUNT(*) as count FROM invalid_records {date_filter}", params)
            total = cursor.fetchone()["count"]
            cursor.execute(
                f"SELECT status, COUNT(*) as count FROM invalid_records {date_filter} GROUP BY status",
                params,
            )
            status_stats = {row["status"]: row["count"] for row in cursor.fetchall()}
            cursor.execute(
                f"SELECT SUM(file_size) as total_size FROM invalid_records {date_filter}", params
            )
            total_size = cursor.fetchone()["total_size"] or 0
            cursor.execute(
                f"SELECT detected_time FROM invalid_records {date_filter} ORDER BY detected_time DESC LIMIT 1",
                params,
            )
            row = cursor.fetchone()
            return {
                "total_count": total,
                "status_stats": status_stats,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
                "latest_detected_time": row["detected_time"] if row else None,
                "query_days": days,
            }

    def cleanup_old_records(self, days: int = 30, delete_files: bool = True) -> int:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, invalid_path FROM invalid_records WHERE detected_time < ?",
                (cutoff,),
            )
            records = cursor.fetchall()
            cleaned = 0
            for row in records:
                if delete_files and os.path.exists(row["invalid_path"]):
                    try:
                        os.remove(row["invalid_path"])
                        folder = os.path.dirname(row["invalid_path"])
                        FilePath.remove_empty_dirs(folder, self.db_dir)
                    except Exception as e:
                        g_logger.error(f"Failed to delete {row['invalid_path']}: {e}")
                        continue
                cleaned += 1
            cursor.execute("DELETE FROM invalid_records WHERE detected_time < ?", (cutoff,))
            cursor.execute("DELETE FROM report_retry_queue WHERE created_at < ?", (cutoff,))
            g_logger.info(f"Cleaned {cleaned} old records (>{days} days)")
            return cleaned

    def export_records_to_json(self, output_path: str, days: Optional[int] = None):
        records = self.query_records(days=days, limit=10000)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        g_logger.info(f"Exported {len(records)} records to {output_path}")
