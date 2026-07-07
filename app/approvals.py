from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, status

from app.database import get_connection
from app.models import (
    ApprovalDecisionResponse,
    ApprovalItem,
    ApprovalStatus,
    ToolCallDecision,
    ToolCallRequest,
)


class ApprovalRepository:
    def __init__(self, database_path: Path | str) -> None:
        self.database_path = database_path

    def create_item(
        self, request: ToolCallRequest, decision: ToolCallDecision
    ) -> ApprovalItem:
        item = ApprovalItem(
            approval_id=str(uuid4()),
            trace_id=decision.trace_id,
            status=ApprovalStatus.PENDING,
            created_at=datetime.now(timezone.utc),
            decided_at=None,
            agent_id=request.agent_id,
            session_id=request.session_id,
            tool_name=request.tool_name,
            action=request.action,
            resource=request.resource,
            reason=decision.reason,
            risk_score=decision.risk_score,
            raw_request_json=request.model_dump_json(),
        )
        with get_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO approvals (
                    approval_id,
                    trace_id,
                    status,
                    created_at,
                    decided_at,
                    agent_id,
                    session_id,
                    tool_name,
                    action,
                    resource,
                    reason,
                    risk_score,
                    raw_request_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.approval_id,
                    item.trace_id,
                    item.status.value,
                    item.created_at.isoformat(),
                    item.decided_at,
                    item.agent_id,
                    item.session_id,
                    item.tool_name,
                    item.action,
                    item.resource,
                    item.reason,
                    item.risk_score,
                    item.raw_request_json,
                ),
            )
            connection.commit()
        return item

    def list_pending(self) -> list[ApprovalItem]:
        with get_connection(self.database_path) as connection:
            rows = connection.execute(
                """
                SELECT * FROM approvals
                WHERE status = ?
                ORDER BY created_at ASC
                """,
                (ApprovalStatus.PENDING.value,),
            ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def approve(self, approval_id: str) -> ApprovalDecisionResponse:
        return self._set_status(approval_id, ApprovalStatus.APPROVED)

    def reject(self, approval_id: str) -> ApprovalDecisionResponse:
        return self._set_status(approval_id, ApprovalStatus.REJECTED)

    def _set_status(
        self, approval_id: str, approval_status: ApprovalStatus
    ) -> ApprovalDecisionResponse:
        decided_at = datetime.now(timezone.utc).isoformat()
        with get_connection(self.database_path) as connection:
            cursor = connection.execute(
                """
                UPDATE approvals
                SET status = ?, decided_at = ?
                WHERE approval_id = ? AND status = ?
                """,
                (
                    approval_status.value,
                    decided_at,
                    approval_id,
                    ApprovalStatus.PENDING.value,
                ),
            )
            connection.commit()

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Pending approval item not found.",
            )
        return ApprovalDecisionResponse(
            approval_id=approval_id,
            status=approval_status,
        )

    def _row_to_item(self, row: object) -> ApprovalItem:
        return ApprovalItem(
            approval_id=row["approval_id"],
            trace_id=row["trace_id"],
            status=row["status"],
            created_at=row["created_at"],
            decided_at=row["decided_at"],
            agent_id=row["agent_id"],
            session_id=row["session_id"],
            tool_name=row["tool_name"],
            action=row["action"],
            resource=row["resource"],
            reason=row["reason"],
            risk_score=row["risk_score"],
            raw_request_json=row["raw_request_json"],
        )
