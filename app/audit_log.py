from __future__ import annotations

import json
from pathlib import Path

from app.database import get_connection
from app.models import (
    AuditLogEntry,
    AuditLogPage,
    Decision,
    ToolCallDecision,
    ToolCallRequest,
)


class AuditLogRepository:
    def __init__(self, database_path: Path | str) -> None:
        self.database_path = database_path

    def record_decision(
        self, request: ToolCallRequest, decision: ToolCallDecision
    ) -> AuditLogEntry:
        raw_request_json = request.model_dump_json()
        entry = AuditLogEntry(
            trace_id=decision.trace_id,
            timestamp=request.timestamp,
            agent_id=request.agent_id,
            session_id=request.session_id,
            tool_name=request.tool_name,
            action=request.action,
            decision=decision.decision,
            reason=decision.reason,
            matched_policy_id=decision.matched_policy_id,
            risk_score=decision.risk_score,
            raw_request_json=raw_request_json,
        )
        with get_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO audit_logs (
                    trace_id,
                    timestamp,
                    agent_id,
                    session_id,
                    tool_name,
                    action,
                    decision,
                    reason,
                    matched_policy_id,
                    risk_score,
                    raw_request_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.trace_id,
                    entry.timestamp.isoformat(),
                    entry.agent_id,
                    entry.session_id,
                    entry.tool_name,
                    entry.action,
                    entry.decision.value,
                    entry.reason,
                    entry.matched_policy_id,
                    entry.risk_score,
                    entry.raw_request_json,
                ),
            )
            connection.commit()
        return entry

    def list_entries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        agent_id: str | None = None,
        session_id: str | None = None,
        decision: Decision | None = None,
        tool_name: str | None = None,
        action: str | None = None,
    ) -> AuditLogPage:
        where_clauses: list[str] = []
        values: list[object] = []
        filters = {
            "agent_id": agent_id,
            "session_id": session_id,
            "decision": decision.value if decision else None,
            "tool_name": tool_name,
            "action": action,
        }
        for column, value in filters.items():
            if value is None:
                continue
            where_clauses.append(f"{column} = ?")
            values.append(value)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        with get_connection(self.database_path) as connection:
            total = connection.execute(
                f"SELECT COUNT(*) AS total FROM audit_logs {where_sql}",
                values,
            ).fetchone()["total"]
            rows = connection.execute(
                f"""
                SELECT * FROM audit_logs
                {where_sql}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
                """,
                [*values, limit, offset],
            ).fetchall()
        return AuditLogPage(
            items=[
                AuditLogEntry(
                    trace_id=row["trace_id"],
                    timestamp=row["timestamp"],
                    agent_id=row["agent_id"],
                    session_id=row["session_id"],
                    tool_name=row["tool_name"],
                    action=row["action"],
                    decision=row["decision"],
                    reason=row["reason"],
                    matched_policy_id=row["matched_policy_id"],
                    risk_score=row["risk_score"],
                    raw_request_json=json.dumps(json.loads(row["raw_request_json"])),
                )
                for row in rows
            ],
            total=total,
            limit=limit,
            offset=offset,
        )
