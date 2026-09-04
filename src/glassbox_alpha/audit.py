from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import CycleReport, to_primitive


class AuditStore:
    """SQLite decision ledger with a SHA-256 hash chain."""

    def __init__(self, path: Path, kill_switch_path: Path):
        self.path = path
        self.kill_switch_path = kill_switch_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.kill_switch_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS decisions (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL UNIQUE,
                    proposal_id TEXT,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    execution_mode TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    record_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_decisions_created ON decisions(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_decisions_proposal ON decisions(proposal_id);
                CREATE TABLE IF NOT EXISTS runtime_state (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def append(self, report: CycleReport) -> str:
        payload = json.dumps(to_primitive(report), sort_keys=True, separators=(",", ":"))
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT record_hash FROM decisions ORDER BY sequence DESC LIMIT 1"
            ).fetchone()
            previous_hash = row["record_hash"] if row else "GENESIS"
            record_hash = hashlib.sha256((previous_hash + payload).encode("utf-8")).hexdigest()
            connection.execute(
                """
                INSERT INTO decisions (
                    run_id, proposal_id, created_at, status, symbol, execution_mode,
                    payload_json, previous_hash, record_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.run_id,
                    report.proposal.proposal_id if report.proposal else None,
                    report.created_at.isoformat(),
                    report.status,
                    report.symbol,
                    report.execution_mode,
                    payload,
                    previous_hash,
                    record_hash,
                ),
            )
        return record_hash

    def recent(self, limit: int = 20) -> list[dict[str, object]]:
        safe_limit = max(1, min(limit, 200))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, payload_json, record_hash, previous_hash
                FROM decisions ORDER BY sequence DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return self._decode_rows(rows)

    def recent_meaningful(self, limit: int = 20) -> list[dict[str, object]]:
        """Hide repetitive off-hours freshness records without deleting audit evidence."""
        safe_limit = max(1, min(limit, 200))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, payload_json, record_hash, previous_hash
                FROM decisions
                WHERE status != 'abstained_stale_data'
                ORDER BY sequence DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return self._decode_rows(rows)

    def submitted_entries(self, limit: int = 200) -> list[dict[str, object]]:
        """Load entry Passports by status so audit noise cannot hide an open position."""
        safe_limit = max(1, min(limit, 1000))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT sequence, payload_json, record_hash, previous_hash
                FROM decisions
                WHERE status = 'submitted_paper'
                ORDER BY sequence DESC LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return self._decode_rows(rows)

    @staticmethod
    def _decode_rows(rows: list[sqlite3.Row]) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            payload["audit"] = {
                "sequence": row["sequence"],
                "record_hash": row["record_hash"],
                "previous_hash": row["previous_hash"],
            }
            result.append(payload)
        return result

    def get(self, run_id: str) -> dict[str, object] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT sequence, payload_json, record_hash, previous_hash FROM decisions WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["payload_json"])
        payload["audit"] = {
            "sequence": row["sequence"],
            "record_hash": row["record_hash"],
            "previous_hash": row["previous_hash"],
        }
        return payload

    def was_submitted(self, proposal_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM decisions
                WHERE proposal_id = ? AND status IN ('submitted_paper', 'error_execution_unknown')
                LIMIT 1
                """,
                (proposal_id,),
            ).fetchone()
        return row is not None

    def has_status(self, proposal_id: str, status: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM decisions WHERE proposal_id = ? AND status = ? LIMIT 1",
                (proposal_id, status),
            ).fetchone()
        return row is not None

    def submissions_today(self, day: date | None = None) -> int:
        target = (day or datetime.now(timezone.utc).date()).isoformat()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total FROM decisions
                WHERE status = 'submitted_paper' AND substr(created_at, 1, 10) = ?
                """,
                (target,),
            ).fetchone()
        return int(row["total"])

    def update_high_watermark(self, equity: float, key: str = "high_watermark") -> float:
        current = self.get_runtime_float(key, equity)
        high = max(current, equity)
        self.set_runtime(key, str(high))
        return high

    def get_runtime_float(self, key: str, default: float) -> float:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM runtime_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return float(row["value"])
        except (TypeError, ValueError):
            return default

    def get_runtime(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM runtime_state WHERE key = ?", (key,)).fetchone()
        return default if row is None else str(row["value"])

    def get_runtime_bool(self, key: str, default: bool = False) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT value FROM runtime_state WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return str(row["value"]).strip().lower() in {"1", "true", "yes", "on"}

    def set_runtime(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runtime_state(key, value, updated_at) VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, now),
            )

    @property
    def kill_switch_engaged(self) -> bool:
        return self.kill_switch_path.exists()

    def set_kill_switch(self, engaged: bool) -> None:
        if engaged:
            self.kill_switch_path.touch(exist_ok=True)
        elif self.kill_switch_path.exists():
            self.kill_switch_path.unlink()

    def verify_chain(self) -> tuple[bool, int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload_json, previous_hash, record_hash FROM decisions ORDER BY sequence"
            ).fetchall()
        previous = "GENESIS"
        for index, row in enumerate(rows, start=1):
            expected = hashlib.sha256((previous + row["payload_json"]).encode("utf-8")).hexdigest()
            if row["previous_hash"] != previous or row["record_hash"] != expected:
                return False, index
            previous = row["record_hash"]
        return True, len(rows)

    def stats(self) -> dict[str, object]:
        with self._connect() as connection:
            rows = connection.execute("SELECT status, COUNT(*) AS total FROM decisions GROUP BY status").fetchall()
            total = connection.execute("SELECT COUNT(*) AS total FROM decisions").fetchone()["total"]
        counts = {row["status"]: row["total"] for row in rows}
        valid, records = self.verify_chain()
        return {
            "total_cycles": total,
            "by_status": counts,
            "audit_chain_valid": valid,
            "audit_records": records,
        }
