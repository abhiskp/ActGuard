from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.database import initialize_database
from app.main import app, get_sequence_detector
from app.policy_engine import PolicyEngine
from app.sequence_detector import SequenceDetector

ADMIN_TOKEN = "test-admin-token"
ADMIN_HEADERS = {"X-ActGuard-Admin-Token": ADMIN_TOKEN}


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    database_path = tmp_path / "actguard-test.db"
    monkeypatch.setenv("ACTGUARD_DB_PATH", str(database_path))
    monkeypatch.setenv("ACTGUARD_ADMIN_TOKEN", ADMIN_TOKEN)
    initialize_database(database_path)
    detector = SequenceDetector()
    main_module.policy_engine = PolicyEngine.from_yaml(Path("config/policies.yaml"))
    app.dependency_overrides[get_sequence_detector] = lambda: detector
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def payload(
    *,
    tool_name: str,
    action: str,
    parameters: dict[str, Any] | None = None,
    session_id: str = "session-api",
) -> dict[str, Any]:
    return {
        "agent_id": "agent-api",
        "session_id": session_id,
        "tool_name": tool_name,
        "action": action,
        "resource": "mock-resource",
        "parameters": parameters or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def test_tool_call_allows_read_only_crm_lookup(client: TestClient) -> None:
    response = client.post(
        "/v1/tool-call",
        json=payload(tool_name="crm", action="read"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "allow"
    assert body["matched_policy_id"] == "allow_read_only_crm_lookup"
    assert body["trace_id"]


def test_tool_call_blocks_mass_delete(client: TestClient) -> None:
    response = client.post(
        "/v1/tool-call",
        json=payload(
            tool_name="file_store",
            action="delete",
            parameters={"count": 10},
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "block"
    assert body["matched_policy_id"] == "block_mass_delete"


def test_tool_call_financial_export_creates_approval(client: TestClient) -> None:
    response = client.post(
        "/v1/tool-call",
        json=payload(
            tool_name="finance",
            action="export",
            parameters={"report_type": "financial", "cross_border": True},
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "require_approval"
    assert body["matched_policy_id"] == "require_approval_financial_export"

    approvals_response = client.get("/v1/approvals")
    assert approvals_response.status_code == 200
    approvals = approvals_response.json()
    assert len(approvals) == 1
    assert approvals[0]["trace_id"] == body["trace_id"]
    assert approvals[0]["status"] == "pending"


def test_audit_logs_include_every_tool_call_decision(client: TestClient) -> None:
    first = client.post(
        "/v1/tool-call",
        json=payload(tool_name="crm", action="read"),
    ).json()
    second = client.post(
        "/v1/tool-call",
        json=payload(
            tool_name="file_store",
            action="delete",
            parameters={"count": 10},
        ),
    ).json()

    response = client.get("/v1/audit-logs")

    assert response.status_code == 200
    logs = response.json()
    assert [entry["trace_id"] for entry in logs] == [
        second["trace_id"],
        first["trace_id"],
    ]
    assert logs[0]["decision"] == "block"
    assert logs[1]["decision"] == "allow"


def test_approval_flow_approve_and_reject(client: TestClient) -> None:
    client.post(
        "/v1/tool-call",
        json=payload(
            tool_name="finance",
            action="export",
            parameters={"report_type": "financial", "cross_border": True},
        ),
    )
    approval_id = client.get("/v1/approvals").json()[0]["approval_id"]

    approve_response = client.post(
        f"/v1/approvals/{approval_id}/approve",
        headers=ADMIN_HEADERS,
    )

    assert approve_response.status_code == 200
    assert approve_response.json() == {
        "approval_id": approval_id,
        "status": "approved",
    }
    assert client.get("/v1/approvals").json() == []

    reject_response = client.post(
        f"/v1/approvals/{approval_id}/reject",
        headers=ADMIN_HEADERS,
    )
    assert reject_response.status_code == 404


def test_api_detects_suspicious_sequence(client: TestClient) -> None:
    session_id = "session-sequence-api"
    client.post(
        "/v1/tool-call",
        json=payload(tool_name="crm", action="read", session_id=session_id),
    )
    client.post(
        "/v1/tool-call",
        json=payload(
            tool_name="finance",
            action="export",
            parameters={"report_type": "financial", "cross_border": True},
            session_id=session_id,
        ),
    )
    response = client.post(
        "/v1/tool-call",
        json=payload(
            tool_name="file_store",
            action="delete",
            parameters={"count": 1},
            session_id=session_id,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "block"
    assert body["matched_policy_id"] == "suspicious_crm_finance_delete_sequence"


def test_dashboard_route_serves_html(client: TestClient) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "ActGuard Control Plane" in response.text


def test_policy_reload_reports_success(client: TestClient) -> None:
    response = client.post("/v1/policies/reload", headers=ADMIN_HEADERS)

    assert response.status_code == 200
    assert response.json() == {
        "status": "reloaded",
        "policy_count": 9,
        "message": "Policies reloaded successfully.",
    }


def test_policy_reload_returns_validation_errors(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_policy_path = tmp_path / "invalid-policies.yaml"
    invalid_policy_path.write_text(
        """
policies:
  - id: invalid_reload_policy
    effect: block
    conditions:
      parameters:
        - path: count
          not_an_operator: 5
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_module, "POLICY_PATH", invalid_policy_path)

    response = client.post("/v1/policies/reload", headers=ADMIN_HEADERS)

    assert response.status_code == 400
    assert response.json() == {
        "detail": {
            "message": "Policy validation failed.",
            "errors": [
                "policies[0].conditions.parameters[0] has unsupported operator(s): not_an_operator."
            ],
        }
    }


def test_admin_endpoints_reject_missing_token(client: TestClient) -> None:
    response = client.post("/v1/policies/reload")

    assert response.status_code == 401
    assert response.json() == {"detail": "Valid ActGuard admin token required."}


def test_admin_endpoints_reject_invalid_token(client: TestClient) -> None:
    response = client.post(
        "/v1/policies/reload",
        headers={"X-ActGuard-Admin-Token": "wrong-token"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Valid ActGuard admin token required."}


def test_admin_endpoints_fail_closed_when_token_is_not_configured(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ACTGUARD_ADMIN_TOKEN", raising=False)

    response = client.post("/v1/policies/reload", headers=ADMIN_HEADERS)

    assert response.status_code == 503
    assert response.json() == {"detail": "ACTGUARD_ADMIN_TOKEN is not configured."}


def test_admin_endpoints_fail_closed_for_whitespace_only_server_token(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ACTGUARD_ADMIN_TOKEN", "   ")

    response = client.post(
        "/v1/policies/reload",
        headers={"X-ActGuard-Admin-Token": "   "},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "ACTGUARD_ADMIN_TOKEN is not configured."}
