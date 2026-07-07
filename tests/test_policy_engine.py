from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.models import Decision, ToolCallRequest
from app.policy_engine import PolicyEngine


POLICY_PATH = Path("config/policies.yaml")


def make_request(
    *,
    tool_name: str,
    action: str,
    parameters: dict[str, object] | None = None,
) -> ToolCallRequest:
    return ToolCallRequest(
        agent_id="agent-test",
        session_id="session-test",
        tool_name=tool_name,
        action=action,
        resource="mock-resource",
        parameters=parameters or {},
        timestamp=datetime.now(timezone.utc),
    )


def test_read_only_crm_lookup_is_allowed() -> None:
    engine = PolicyEngine.from_yaml(POLICY_PATH)

    match = engine.evaluate(make_request(tool_name="crm", action="read"))

    assert match.decision == Decision.ALLOW
    assert match.matched_policy_id == "allow_read_only_crm_lookup"
    assert match.risk_score == 10


def test_financial_export_requires_approval() -> None:
    engine = PolicyEngine.from_yaml(POLICY_PATH)

    match = engine.evaluate(
        make_request(
            tool_name="finance",
            action="export",
            parameters={"report_type": "financial", "cross_border": True},
        )
    )

    assert match.decision == Decision.REQUIRE_APPROVAL
    assert match.matched_policy_id == "require_approval_financial_export"


def test_mass_delete_is_blocked() -> None:
    engine = PolicyEngine.from_yaml(POLICY_PATH)

    match = engine.evaluate(
        make_request(
            tool_name="file_store",
            action="delete",
            parameters={"count": 10},
        )
    )

    assert match.decision == Decision.BLOCK
    assert match.matched_policy_id == "block_mass_delete"


def test_external_transfer_is_blocked() -> None:
    engine = PolicyEngine.from_yaml(POLICY_PATH)

    match = engine.evaluate(
        make_request(
            tool_name="mock_drive",
            action="transfer",
            parameters={"destination_type": "external"},
        )
    )

    assert match.decision == Decision.BLOCK
    assert match.matched_policy_id == "block_external_data_transfer"
