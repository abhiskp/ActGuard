from __future__ import annotations

import os
import sqlite3
from pathlib import Path


DEFAULT_DATABASE_PATH = Path("data/actguard.db")


def get_database_path() -> Path:
    return Path(os.getenv("ACTGUARD_DB_PATH", str(DEFAULT_DATABASE_PATH)))


def get_connection(database_path: Path | str | None = None) -> sqlite3.Connection:
    db_path = Path(database_path) if database_path is not None else get_database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(database_path: Path | str | None = None) -> None:
    with get_connection(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                trace_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                action TEXT NOT NULL,
                decision TEXT NOT NULL,
                reason TEXT NOT NULL,
                matched_policy_id TEXT,
                risk_score INTEGER NOT NULL,
                raw_request_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS approvals (
                approval_id TEXT PRIMARY KEY,
                trace_id TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                decided_at TEXT,
                agent_id TEXT NOT NULL,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                action TEXT NOT NULL,
                resource TEXT NOT NULL,
                reason TEXT NOT NULL,
                risk_score INTEGER NOT NULL,
                raw_request_json TEXT NOT NULL,
                FOREIGN KEY(trace_id) REFERENCES audit_logs(trace_id)
            )
            """
        )
        connection.commit()
