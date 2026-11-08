from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.approvals import ApprovalRepository
from app.audit_log import AuditLogRepository
from app.database import get_database_path, initialize_database
from app.execution import (
    ExecutionRepository,
    MockToolExecutor,
    execute_tool,
    initial_execution,
    rejected_execution,
)
from app.models import (
    AuditLogPage,
    ApprovalDecisionResponse,
    ApprovalItem,
    Decision,
    PolicyReloadResponse,
    ToolCallDecision,
    ToolCallRequest,
)
from app.policy_engine import PolicyEngine, PolicyValidationError
from app.security import require_admin_token
from app.sequence_detector import SequenceDetector, ToolCallEvent

POLICY_PATH = Path("config/policies.yaml")
DASHBOARD_PATH = Path("static/index.html")

policy_engine = PolicyEngine.from_yaml(POLICY_PATH)
tool_executor = MockToolExecutor()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    initialize_database(get_database_path())
    yield


app = FastAPI(
    title="ActGuard",
    summary="Runtime control plane for AI-agent tool calls.",
    version="0.1.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory="static"), name="static")


def get_db_path() -> Path:
    return get_database_path()


def get_policy_engine() -> PolicyEngine:
    return policy_engine


def get_sequence_detector() -> SequenceDetector:
    return SequenceDetector(database_path=get_database_path())


def get_tool_executor() -> MockToolExecutor:
    return tool_executor


def reload_policy_engine_from_disk() -> PolicyEngine:
    return PolicyEngine.from_yaml(POLICY_PATH)


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(DASHBOARD_PATH)


@app.post("/v1/tool-call", response_model=ToolCallDecision)
def evaluate_tool_call(
    request: ToolCallRequest,
    db_path: Path = Depends(get_db_path),
    engine: PolicyEngine = Depends(get_policy_engine),
    detector: SequenceDetector = Depends(get_sequence_detector),
    executor: MockToolExecutor = Depends(get_tool_executor),
) -> ToolCallDecision:
    previous_calls = detector.recent_calls(request.session_id)
    policy_match = engine.evaluate(request, previous_calls)
    response = ToolCallDecision(
        decision=policy_match.decision,
        reason=policy_match.reason,
        matched_policy_id=policy_match.matched_policy_id,
        risk_score=policy_match.risk_score,
        trace_id=str(uuid4()),
    )

    AuditLogRepository(db_path).record_decision(request, response)
    if response.decision == Decision.REQUIRE_APPROVAL:
        ApprovalRepository(db_path).create_item(request, response)

    execution = initial_execution(request, response.decision, executor)
    ExecutionRepository(db_path).record(response.trace_id, execution)
    response.execution = execution

    detector.add_call(
        ToolCallEvent(
            agent_id=request.agent_id,
            session_id=request.session_id,
            tool_name=request.tool_name,
            action=request.action,
            resource=request.resource,
            parameters=request.parameters,
            timestamp=request.timestamp,
        )
    )
    return response


@app.get("/v1/approvals", response_model=list[ApprovalItem])
def list_approvals(db_path: Path = Depends(get_db_path)) -> list[ApprovalItem]:
    return ApprovalRepository(db_path).list_pending()


@app.get("/v1/audit-logs", response_model=AuditLogPage)
def list_audit_logs(
    db_path: Path = Depends(get_db_path),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    agent_id: str | None = None,
    session_id: str | None = None,
    decision: Decision | None = None,
    tool_name: str | None = None,
    action: str | None = None,
) -> AuditLogPage:
    return AuditLogRepository(db_path).list_entries(
        limit=limit,
        offset=offset,
        agent_id=agent_id,
        session_id=session_id,
        decision=decision,
        tool_name=tool_name,
        action=action,
    )


@app.post(
    "/v1/policies/reload",
    response_model=PolicyReloadResponse,
    dependencies=[Depends(require_admin_token)],
)
def reload_policies() -> PolicyReloadResponse:
    global policy_engine
    try:
        next_engine = reload_policy_engine_from_disk()
    except PolicyValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"message": "Policy validation failed.", "errors": exc.errors},
        ) from exc

    policy_engine = next_engine
    return PolicyReloadResponse(
        status="reloaded",
        policy_count=len(policy_engine.policies),
        message="Policies reloaded successfully.",
    )


@app.post(
    "/v1/approvals/{approval_id}/approve",
    response_model=ApprovalDecisionResponse,
    dependencies=[Depends(require_admin_token)],
)
def approve_item(
    approval_id: str,
    db_path: Path = Depends(get_db_path),
    executor: MockToolExecutor = Depends(get_tool_executor),
) -> ApprovalDecisionResponse:
    approvals = ApprovalRepository(db_path)
    item = approvals.get_pending(approval_id)
    response = approvals.approve(approval_id)
    execution = execute_tool(
        ToolCallRequest.model_validate_json(item.raw_request_json), executor
    )
    ExecutionRepository(db_path).record(item.trace_id, execution)
    response.execution = execution
    return response


@app.post(
    "/v1/approvals/{approval_id}/reject",
    response_model=ApprovalDecisionResponse,
    dependencies=[Depends(require_admin_token)],
)
def reject_item(
    approval_id: str,
    db_path: Path = Depends(get_db_path),
) -> ApprovalDecisionResponse:
    approvals = ApprovalRepository(db_path)
    item = approvals.get_pending(approval_id)
    response = approvals.reject(approval_id)
    execution = rejected_execution()
    ExecutionRepository(db_path).record(item.trace_id, execution)
    response.execution = execution
    return response


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
