from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.models import Decision, ToolCallRequest
from app.policy_engine import PolicyEngine
from app.sequence_detector import SequenceDetector, ToolCallEvent


def event(tool_name: str, action: str) -> ToolCallEvent:
    return ToolCallEvent(
        agent_id="agent-test",
        session_id="session-sequence",
        tool_name=tool_name,
        action=action,
        resource="mock-resource",
        parameters={},
        timestamp=datetime.now(timezone.utc),
    )


def request(tool_name: str, action: str) -> ToolCallRequest:
    return ToolCallRequest(
        agent_id="agent-test",
        session_id="session-sequence",
        tool_name=tool_name,
        action=action,
        resource="mock-resource",
        parameters={"count": 1},
        timestamp=datetime.now(timezone.utc),
    )


def test_sequence_detector_returns_recent_calls_by_session() -> None:
    detector = SequenceDetector(max_events_per_session=2)
    detector.add_call(event("crm", "read"))
    detector.add_call(event("finance", "export"))
    detector.add_call(event("file_store", "delete"))

    recent_calls = detector.recent_calls("session-sequence")

    assert [(call.tool_name, call.action) for call in recent_calls] == [
        ("finance", "export"),
        ("file_store", "delete"),
    ]


def test_suspicious_sequence_policy_blocks_delete() -> None:
    engine = PolicyEngine.from_yaml(Path("config/policies.yaml"))
    detector = SequenceDetector()
    detector.add_call(event("crm", "read"))
    detector.add_call(event("finance", "export"))

    match = engine.evaluate(
        request("file_store", "delete"),
        detector.recent_calls("session-sequence"),
    )

    assert match.decision == Decision.BLOCK
    assert match.matched_policy_id == "suspicious_crm_finance_delete_sequence"
