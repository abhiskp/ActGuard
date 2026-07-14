from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.models import Decision, ToolCallRequest
from app.policy_engine import PolicyEngine, PolicyValidationError


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


def test_scalar_in_operator_blocks_dangerous_admin_action() -> None:
    engine = PolicyEngine.from_yaml(POLICY_PATH)

    match = engine.evaluate(make_request(tool_name="admin", action="disable_mfa"))

    assert match.decision == Decision.BLOCK
    assert match.matched_policy_id == "block_dangerous_admin_actions"


def test_contains_operator_blocks_sensitive_crm_fields() -> None:
    engine = PolicyEngine.from_yaml(POLICY_PATH)

    match = engine.evaluate(
        make_request(
            tool_name="crm",
            action="read",
            parameters={"fields": ["name", "ssn"]},
        )
    )

    assert match.decision == Decision.BLOCK
    assert match.matched_policy_id == "block_sensitive_crm_field_lookup"


def test_regex_operator_requires_approval_for_risky_partner_domain() -> None:
    engine = PolicyEngine.from_yaml(POLICY_PATH)

    match = engine.evaluate(
        make_request(
            tool_name="mock_drive",
            action="transfer",
            parameters={
                "destination_type": "partner",
                "destination_domain": "exports.external.example",
            },
        )
    )

    assert match.decision == Decision.REQUIRE_APPROVAL
    assert match.matched_policy_id == "require_approval_partner_domain_transfer"


def test_less_than_operator_allows_small_file_delete() -> None:
    engine = PolicyEngine.from_yaml(POLICY_PATH)

    match = engine.evaluate(
        make_request(
            tool_name="file_store",
            action="delete",
            parameters={"count": 1},
        )
    )

    assert match.decision == Decision.ALLOW
    assert match.matched_policy_id == "allow_small_file_delete"


def test_policy_validation_reports_clear_errors(tmp_path: Path) -> None:
    policy_path = tmp_path / "invalid-policies.yaml"
    policy_path.write_text(
        """
policies:
  - id: broken_policy
    effect: maybe
    risk_score: 110
    conditions:
      tool_name:
        starts_with: crm
      parameters:
        - path: destination
          regex: "["
""",
        encoding="utf-8",
    )

    with pytest.raises(PolicyValidationError) as exc_info:
        PolicyEngine.from_yaml(policy_path)

    assert exc_info.value.errors == [
        "policies[0].effect must be one of: allow, block, require_approval.",
        "policies[0].risk_score must be at most 100.",
        "policies[0].conditions.tool_name has unsupported operator(s): starts_with.",
        "policies[0].conditions.parameters[0].regex is invalid: unterminated character set at position 0.",
    ]
