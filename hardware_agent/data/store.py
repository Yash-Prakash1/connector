"""Local data store — SQLite at ~/.hardware-agent/data.db."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from hardware_agent.core.models import Iteration, SessionResult


_DEFAULT_DB_PATH = os.path.join(
    str(Path.home()), ".hardware-agent", "data.db"
)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT,
    device_type TEXT NOT NULL,
    device_name TEXT,
    os TEXT NOT NULL,
    os_version TEXT,
    python_version TEXT,
    env_type TEXT,
    initial_state_fingerprint TEXT,
    initial_packages TEXT,
    outcome TEXT,
    iteration_count INTEGER DEFAULT 0,
    duration_seconds REAL,
    final_code TEXT,
    error_message TEXT,
    pattern_uploaded INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS iterations (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    iteration_number INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    tool_params TEXT,
    success INTEGER NOT NULL,
    stdout TEXT,
    stderr TEXT,
    exit_code INTEGER,
    duration_ms INTEGER,
    error_fingerprint TEXT,
    error_category TEXT,
    resolves_iteration_id TEXT
);

CREATE TABLE IF NOT EXISTS community_patterns (
    id TEXT PRIMARY KEY,
    device_type TEXT NOT NULL,
    os TEXT NOT NULL,
    initial_state_fingerprint TEXT,
    steps TEXT NOT NULL,
    success_count INTEGER,
    success_rate REAL,
    confidence_score REAL,
    last_synced TEXT
);

CREATE TABLE IF NOT EXISTS community_errors (
    id TEXT PRIMARY KEY,
    device_type TEXT,
    os TEXT,
    error_fingerprint TEXT NOT NULL,
    error_category TEXT,
    explanation TEXT,
    resolution_action TEXT,
    resolution_detail TEXT,
    success_count INTEGER,
    success_rate REAL,
    next_error_fingerprint TEXT,
    last_synced TEXT
);

CREATE TABLE IF NOT EXISTS upload_queue (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    attempts INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT OR IGNORE INTO config (key, value) VALUES ('telemetry', 'true');
INSERT OR IGNORE INTO config (key, value) VALUES ('model', 'claude-sonnet-4-20250514');
"""


class DataStore:
    """Local SQLite data store."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or _DEFAULT_DB_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript(_SCHEMA)
        conn.commit()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    # ── Config ───────────────────────────────────────────────────────

    def get_config(self, key: str) -> Optional[str]:
        conn = self._get_conn()
        row = conn.execute(
            "SELECT value FROM config WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    def set_config(self, key: str, value: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value),
        )
        conn.commit()

    # ── Sessions ─────────────────────────────────────────────────────

    def create_session(
        self,
        session_id: str,
        device_type: str,
        device_name: str,
        os_name: str,
        os_version: str,
        python_version: str,
        env_type: str,
        fingerprint: str,
    ) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO sessions
               (id, created_at, device_type, device_name, os, os_version,
                python_version, env_type, initial_state_fingerprint)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                datetime.now().isoformat(),
                device_type,
                device_name,
                os_name,
                os_version,
                python_version,
                env_type,
                fingerprint,
            ),
        )
        conn.commit()

    def complete_session(self, session_id: str, result: SessionResult) -> None:
        conn = self._get_conn()
        conn.execute(
            """UPDATE sessions SET
               updated_at = ?,
               outcome = ?,
               iteration_count = ?,
               duration_seconds = ?,
               final_code = ?,
               error_message = ?
               WHERE id = ?""",
            (
                datetime.now().isoformat(),
                "success" if result.success else "failed",
                result.iterations,
                result.duration_seconds,
                result.final_code,
                result.error_message,
                session_id,
            ),
        )
        conn.commit()

    def mark_session_shared(self, session_id: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE sessions SET pattern_uploaded = 1 WHERE id = ?",
            (session_id,),
        )
        conn.commit()

    # ── Iterations ───────────────────────────────────────────────────

    def log_iteration(self, session_id: str, iteration: Iteration) -> None:
        conn = self._get_conn()
        conn.execute(
            """INSERT INTO iterations
               (id, session_id, iteration_number, timestamp, tool_name,
                tool_params, success, stdout, stderr, exit_code, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(uuid.uuid4()),
                session_id,
                iteration.number,
                iteration.timestamp.isoformat(),
                iteration.tool_call.name,
                json.dumps(iteration.tool_call.parameters),
                1 if iteration.result.success else 0,
                iteration.result.stdout,
                iteration.result.stderr,
                iteration.result.exit_code,
                iteration.duration_ms,
            ),
        )
        conn.commit()

    # ── Community Patterns (cache) ───────────────────────────────────

    def cache_patterns(self, patterns: list[dict]) -> None:
        conn = self._get_conn()
        now = datetime.now().isoformat()
        for p in patterns:
            conn.execute(
                """INSERT OR REPLACE INTO community_patterns
                   (id, device_type, os, initial_state_fingerprint, steps,
                    success_count, success_rate, confidence_score, last_synced)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p.get("id", str(uuid.uuid4())),
                    p["device_type"],
                    p["os"],
                    p.get("initial_state_fingerprint"),
                    json.dumps(p["steps"]) if isinstance(p["steps"], list) else p["steps"],
                    p.get("success_count", 0),
                    p.get("success_rate", 0.0),
                    p.get("confidence_score", 0.0),
                    now,
                ),
            )
        conn.commit()

    def get_cached_patterns(
        self, device_type: str, os_name: str
    ) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM community_patterns
               WHERE device_type = ? AND os = ?
               ORDER BY confidence_score DESC""",
            (device_type, os_name),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if isinstance(d.get("steps"), str):
                d["steps"] = json.loads(d["steps"])
            result.append(d)
        return result

    # ── Community Errors (cache) ─────────────────────────────────────

    def cache_errors(self, errors: list[dict]) -> None:
        conn = self._get_conn()
        now = datetime.now().isoformat()
        for e in errors:
            conn.execute(
                """INSERT OR REPLACE INTO community_errors
                   (id, device_type, os, error_fingerprint, error_category,
                    explanation, resolution_action, resolution_detail,
                    success_count, success_rate, next_error_fingerprint, last_synced)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    e.get("id", str(uuid.uuid4())),
                    e.get("device_type"),
                    e.get("os"),
                    e["error_fingerprint"],
                    e.get("error_category"),
                    e.get("explanation"),
                    e.get("resolution_action"),
                    json.dumps(e.get("resolution_detail", {})),
                    e.get("success_count", 0),
                    e.get("success_rate", 0.0),
                    e.get("next_error_fingerprint"),
                    now,
                ),
            )
        conn.commit()

    def get_cached_errors(
        self, device_type: str, os_name: str
    ) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT * FROM community_errors
               WHERE (device_type = ? OR device_type IS NULL)
               AND (os = ? OR os IS NULL)
               ORDER BY success_rate DESC""",
            (device_type, os_name),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            if isinstance(d.get("resolution_detail"), str):
                d["resolution_detail"] = json.loads(d["resolution_detail"])
            result.append(d)
        return result

    # ── Upload Queue ─────────────────────────────────────────────────

    def queue_upload(self, payload: dict) -> None:
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO upload_queue (id, payload, created_at) VALUES (?, ?, ?)",
            (str(uuid.uuid4()), json.dumps(payload), datetime.now().isoformat()),
        )
        conn.commit()

    def get_pending_uploads(self) -> list[dict]:
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM upload_queue ORDER BY created_at"
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["payload"] = json.loads(d["payload"])
            result.append(d)
        return result

    def remove_upload(self, upload_id: str) -> None:
        conn = self._get_conn()
        conn.execute("DELETE FROM upload_queue WHERE id = ?", (upload_id,))
        conn.commit()

    def increment_upload_attempts(self, upload_id: str) -> None:
        conn = self._get_conn()
        conn.execute(
            "UPDATE upload_queue SET attempts = attempts + 1 WHERE id = ?",
            (upload_id,),
        )
        conn.commit()

    # ── Analysis ─────────────────────────────────────────────────────

    def save_analysis(self, session_id: str, analysis: Any) -> None:
        """Save analysis results to local SQLite for learning.

        Upserts resolution patterns into community_patterns and error
        resolutions into community_errors so the replay engine can find them.
        """
        from hardware_agent.data.models import SessionAnalysis

        if not isinstance(analysis, SessionAnalysis):
            return

        conn = self._get_conn()
        now = datetime.now().isoformat()

        # ── Save resolution pattern ──────────────────────────────────
        if analysis.pattern is not None:
            steps_dicts = [
                {"action": s.action, **s.detail}
                for s in analysis.pattern.steps
            ]
            steps_json = json.dumps(steps_dicts, sort_keys=True)
            is_success = analysis.pattern.outcome == "success"

            # Deterministic ID from device_type + os + steps
            pattern_key = json.dumps({
                "device_type": analysis.pattern.device_type,
                "os": analysis.pattern.os,
                "steps": steps_dicts,
            }, sort_keys=True)
            pattern_id = "local_" + hashlib.sha256(
                pattern_key.encode()
            ).hexdigest()[:16]

            existing = conn.execute(
                "SELECT success_count, confidence_score "
                "FROM community_patterns WHERE id = ?",
                (pattern_id,),
            ).fetchone()

            if existing:
                old_success = existing["success_count"] or 0
                # confidence_score stores total attempt count for local patterns
                old_total = int(existing["confidence_score"] or 0)
                new_total = old_total + 1
                new_success = old_success + (1 if is_success else 0)
                new_rate = new_success / new_total
                conn.execute(
                    """UPDATE community_patterns
                       SET success_count = ?, success_rate = ?,
                           confidence_score = ?, last_synced = ?
                       WHERE id = ?""",
                    (new_success, new_rate, new_total, now, pattern_id),
                )
            else:
                conn.execute(
                    """INSERT INTO community_patterns
                       (id, device_type, os, initial_state_fingerprint, steps,
                        success_count, success_rate, confidence_score, last_synced)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        pattern_id,
                        analysis.pattern.device_type,
                        analysis.pattern.os,
                        analysis.pattern.initial_state_fingerprint,
                        steps_json,
                        1 if is_success else 0,
                        1.0 if is_success else 0.0,
                        1,  # total_count = 1
                        now,
                    ),
                )
            conn.commit()

        # ── Save error resolutions ───────────────────────────────────
        for er in analysis.error_resolutions:
            er_key = f"{er.error_fingerprint}:{er.resolution_action}"
            er_id = "local_" + hashlib.sha256(
                er_key.encode()
            ).hexdigest()[:16]

            existing = conn.execute(
                "SELECT success_count FROM community_errors WHERE id = ?",
                (er_id,),
            ).fetchone()

            if existing:
                new_count = (existing["success_count"] or 0) + 1
                conn.execute(
                    """UPDATE community_errors
                       SET success_count = ?, success_rate = 1.0,
                           last_synced = ?
                       WHERE id = ?""",
                    (new_count, now, er_id),
                )
            else:
                conn.execute(
                    """INSERT INTO community_errors
                       (id, device_type, os, error_fingerprint, error_category,
                        explanation, resolution_action, resolution_detail,
                        success_count, success_rate, last_synced)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        er_id,
                        er.device_type,
                        er.os,
                        er.error_fingerprint,
                        er.error_category,
                        er.explanation,
                        er.resolution_action,
                        json.dumps(er.resolution_detail),
                        1,
                        1.0,
                        now,
                    ),
                )
            conn.commit()
