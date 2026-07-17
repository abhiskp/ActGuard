from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Decision(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_APPROVAL = "require_approval"


class ToolCallRequest(BaseModel):
    agent_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    tool_name: str = Field(..., min_length=1)
    action: str = Field(..., min_length=1)
    resource: str = Field(..., min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ToolCallDecision(BaseModel):
    decision: Decision
    reason: str
    matched_policy_id: str | None
    risk_score: int = Field(..., ge=0, le=100)
    trace_id: str


class AuditLogEntry(BaseModel):
    trace_id: str
    timestamp: datetime
    agent_id: str
    session_id: str
    tool_name: str
    action: str
    decision: Decision
    reason: str
    matched_policy_id: str | None
    risk_score: int
    raw_request_json: str


class AuditLogPage(BaseModel):
    items: list[AuditLogEntry]
    total: int = Field(..., ge=0)
    limit: int = Field(..., ge=1)
    offset: int = Field(..., ge=0)


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalItem(BaseModel):
    approval_id: str
    trace_id: str
    status: ApprovalStatus
    created_at: datetime
    decided_at: datetime | None = None
    agent_id: str
    session_id: str
    tool_name: str
    action: str
    resource: str
    reason: str
    risk_score: int
    raw_request_json: str


class ApprovalDecisionResponse(BaseModel):
    approval_id: str
    status: ApprovalStatus


class PolicyReloadResponse(BaseModel):
    status: str
    policy_count: int
    message: str
