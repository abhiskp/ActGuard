from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database import get_connection
from app.models import (
    Decision,
    ExecutionStatus,
    ToolCallRequest,
    ToolExecutionResult,
)


class MockToolExecutor:
    """Executes deterministic local stand-ins for agent tools."""

    def execute(self, request: ToolCallRequest) -> ToolExecutionResult:
        output = self._build_output(request)
        return ToolExecutionResult(
            status=ExecutionStatus.EXECUTED,
            updated_at=datetime.now(timezone.utc),
            message=f"Mock {request.tool_name}.{request.action} executed.",
            output=output,
        )

    def _build_output(self, request: ToolCallRequest) -> dict[str, Any]:
        if request.tool_name == "crm" and request.action == "read":
            return {
                "customer_id": request.parameters.get("customer_id", request.resource),
                "fields": request.parameters.get("fields", []),
                "source": "mock_crm",
            }
        if request.tool_name == "finance" and request.action == "export":
            return {
                "report": request.resource,
                "format": request.parameters.get("format", "csv"),
                "source": "mock_finance",
            }
        if request.tool_name == "file_store" and request.action == "delete":
            return {
                "deleted_count": request.parameters.get("count", 0),
                "path": request.parameters.get("path", request.resource),
                "source": "mock_file_store",
            }
        return {
            "resource": request.resource,
            "parameters": request.parameters,
            "source": f"mock_{request.tool_name}",
        }


class ExecutionRepository:
    def __init__(self, database_path: Path | str) -> None:
        self.database_path = database_path

    def record(self, trace_id: str, result: ToolExecutionResult) -> None:
        output_json = json.dumps(result.output) if result.output is not None else None
        with get_connection(self.database_path) as connection:
            connection.execute(
                """
                INSERT INTO tool_executions (
                    trace_id, status, updated_at, message, output_json
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(trace_id) DO UPDATE SET
                    status = excluded.status,
                    updated_at = excluded.updated_at,
                    message = excluded.message,
                    output_json = excluded.output_json
                """,
                (
                    trace_id,
                    result.status.value,
                    result.updated_at.isoformat(),
                    result.message,
                    output_json,
                ),
            )
            connection.commit()


def execute_tool(
    request: ToolCallRequest,
    executor: MockToolExecutor,
) -> ToolExecutionResult:
    try:
        return executor.execute(request)
    except Exception as exc:
        return ToolExecutionResult(
            status=ExecutionStatus.FAILED,
            updated_at=datetime.now(timezone.utc),
            message=f"Mock tool execution failed: {exc}",
        )


def initial_execution(
    request: ToolCallRequest,
    decision: Decision,
    executor: MockToolExecutor,
) -> ToolExecutionResult:
    if decision == Decision.ALLOW:
        return execute_tool(request, executor)

    now = datetime.now(timezone.utc)
    if decision == Decision.REQUIRE_APPROVAL:
        return ToolExecutionResult(
            status=ExecutionStatus.PENDING_APPROVAL,
            updated_at=now,
            message="Tool call is held until a human approves it.",
        )
    return ToolExecutionResult(
        status=ExecutionStatus.BLOCKED,
        updated_at=now,
        message="Tool call was blocked and was not executed.",
    )


def rejected_execution() -> ToolExecutionResult:
    return ToolExecutionResult(
        status=ExecutionStatus.REJECTED,
        updated_at=datetime.now(timezone.utc),
        message="Tool call was rejected and was not executed.",
    )
