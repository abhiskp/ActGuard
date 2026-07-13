from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.approvals import ApprovalRepository
from app.audit_log import AuditLogRepository
from app.database import get_database_path, initialize_database
from app.models import (
    AuditLogEntry,
    ApprovalDecisionResponse,
    ApprovalItem,
    Decision,
    ToolCallDecision,
    ToolCallRequest,
)
from app.policy_engine import PolicyEngine
from app.sequence_detector import SequenceDetector, ToolCallEvent

POLICY_PATH = Path("config/policies.yaml")
DASHBOARD_PATH = Path("static/index.html")

sequence_detector = SequenceDetector()
policy_engine = PolicyEngine.from_yaml(POLICY_PATH)


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
    return sequence_detector


@app.get("/", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(DASHBOARD_PATH)


@app.post("/v1/tool-call", response_model=ToolCallDecision)
def evaluate_tool_call(
    request: ToolCallRequest,
    db_path: Path = Depends(get_db_path),
    engine: PolicyEngine = Depends(get_policy_engine),
    detector: SequenceDetector = Depends(get_sequence_detector),
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


@app.get("/v1/audit-logs", response_model=list[AuditLogEntry])
def list_audit_logs(db_path: Path = Depends(get_db_path)) -> list[AuditLogEntry]:
    return AuditLogRepository(db_path).list_entries()


@app.post(
    "/v1/approvals/{approval_id}/approve",
    response_model=ApprovalDecisionResponse,
)
def approve_item(
    approval_id: str,
    db_path: Path = Depends(get_db_path),
) -> ApprovalDecisionResponse:
    return ApprovalRepository(db_path).approve(approval_id)


@app.post(
    "/v1/approvals/{approval_id}/reject",
    response_model=ApprovalDecisionResponse,
)
def reject_item(
    approval_id: str,
    db_path: Path = Depends(get_db_path),
) -> ApprovalDecisionResponse:
    return ApprovalRepository(db_path).reject(approval_id)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
