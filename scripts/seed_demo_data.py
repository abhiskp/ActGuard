from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
import warnings
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SERVER_URL = "http://127.0.0.1:8000"


def build_payload(
    *,
    agent_id: str,
    session_id: str,
    tool_name: str,
    action: str,
    resource: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    return {
        "agent_id": agent_id,
        "session_id": session_id,
        "tool_name": tool_name,
        "action": action,
        "resource": resource,
        "parameters": parameters,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def build_seed_payloads(batch_id: str | None = None) -> list[tuple[str, dict[str, Any]]]:
    batch_id = batch_id or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return [
        (
            "Allowed CRM lookup for Acme",
            build_payload(
                agent_id="seed-sales-agent",
                session_id=f"seed-{batch_id}-crm-safe",
                tool_name="crm",
                action="read",
                resource="customers/acme-corp",
                parameters={"customer_id": "acme-corp", "fields": ["name", "tier"]},
            ),
        ),
        (
            "Allowed CRM lookup for Globex",
            build_payload(
                agent_id="seed-sales-agent",
                session_id=f"seed-{batch_id}-crm-safe",
                tool_name="crm",
                action="read",
                resource="customers/globex",
                parameters={
                    "customer_id": "globex",
                    "fields": ["name", "tier", "region"],
                },
            ),
        ),
        (
            "Approval required for cross-border finance export",
            build_payload(
                agent_id="seed-finance-agent",
                session_id=f"seed-{batch_id}-finance-export",
                tool_name="finance",
                action="export",
                resource="reports/q3-cross-border",
                parameters={"report_type": "financial", "cross_border": True},
            ),
        ),
        (
            "Blocked mass file delete",
            build_payload(
                agent_id="seed-ops-agent",
                session_id=f"seed-{batch_id}-mass-delete",
                tool_name="file_store",
                action="delete",
                resource="drive/folder/customer-exports",
                parameters={"count": 10, "path": "/mock/customer-exports"},
            ),
        ),
        (
            "Blocked external transfer",
            build_payload(
                agent_id="seed-sync-agent",
                session_id=f"seed-{batch_id}-external-transfer",
                tool_name="mock_drive",
                action="transfer",
                resource="drive/files/customer-list.csv",
                parameters={
                    "destination_type": "external",
                    "destination_domain": "unknown.example",
                },
            ),
        ),
        (
            "Blocked dangerous admin action",
            build_payload(
                agent_id="seed-admin-agent",
                session_id=f"seed-{batch_id}-admin-risk",
                tool_name="admin",
                action="disable_mfa",
                resource="workspace/security/mfa",
                parameters={"target_group": "finance-admins"},
            ),
        ),
        (
            "Blocked sensitive CRM field lookup",
            build_payload(
                agent_id="seed-support-agent",
                session_id=f"seed-{batch_id}-sensitive-crm",
                tool_name="crm",
                action="read",
                resource="customers/initech",
                parameters={
                    "customer_id": "initech",
                    "fields": ["name", "email", "ssn"],
                },
            ),
        ),
        (
            "Approval required for risky partner transfer",
            build_payload(
                agent_id="seed-sync-agent",
                session_id=f"seed-{batch_id}-partner-transfer",
                tool_name="mock_drive",
                action="transfer",
                resource="drive/files/revenue-summary.csv",
                parameters={
                    "destination_type": "partner",
                    "destination_domain": "exports.external.example",
                },
            ),
        ),
        (
            "Allowed low-volume mock delete",
            build_payload(
                agent_id="seed-ops-agent",
                session_id=f"seed-{batch_id}-small-delete",
                tool_name="file_store",
                action="delete",
                resource="drive/folder/tmp-cleanup",
                parameters={"count": 1, "path": "/mock/tmp-cleanup"},
            ),
        ),
        (
            "Suspicious sequence: CRM read",
            build_payload(
                agent_id="seed-risk-agent",
                session_id=f"seed-{batch_id}-suspicious-sequence",
                tool_name="crm",
                action="read",
                resource="customers/umbrella",
                parameters={
                    "customer_id": "umbrella",
                    "fields": ["name", "tier", "region"],
                },
            ),
        ),
        (
            "Suspicious sequence: finance export",
            build_payload(
                agent_id="seed-risk-agent",
                session_id=f"seed-{batch_id}-suspicious-sequence",
                tool_name="finance",
                action="export",
                resource="reports/umbrella-cross-border",
                parameters={"report_type": "financial", "cross_border": True},
            ),
        ),
        (
            "Suspicious sequence: file delete",
            build_payload(
                agent_id="seed-risk-agent",
                session_id=f"seed-{batch_id}-suspicious-sequence",
                tool_name="file_store",
                action="delete",
                resource="drive/folder/umbrella-export",
                parameters={"count": 1, "path": "/mock/umbrella-export"},
            ),
        ),
    ]


def reset_local_demo_data() -> None:
    from app.database import get_connection, get_database_path, initialize_database
    from app.main import get_sequence_detector

    database_path = get_database_path()
    initialize_database(database_path)
    with get_connection(database_path) as connection:
        connection.execute("DELETE FROM approvals")
        connection.execute("DELETE FROM audit_logs")
        connection.commit()
    get_sequence_detector().clear()


def post_to_running_server(
    payload: dict[str, Any],
    *,
    server_url: str,
) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{server_url}/v1/tool-call",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.loads(response.read().decode("utf-8"))


def run_with_in_process_app(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    warnings.filterwarnings(
        "ignore",
        message="Using `httpx` with `starlette.testclient` is deprecated.*",
    )
    from fastapi.testclient import TestClient

    from app.main import app, get_sequence_detector

    get_sequence_detector().clear()
    with TestClient(app) as client:
        return [
            client.post("/v1/tool-call", json=payload).json()
            for payload in payloads
        ]


def seed_demo_data(
    *,
    reset: bool,
    server_url: str = DEFAULT_SERVER_URL,
) -> list[tuple[str, dict[str, Any]]]:
    if reset:
        reset_local_demo_data()

    seed_steps = build_seed_payloads()
    payloads = [payload for _, payload in seed_steps]
    try:
        responses = [
            post_to_running_server(payload, server_url=server_url)
            for payload in payloads
        ]
        print(f"Seeded ActGuard demo data using running server at {server_url}")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        responses = run_with_in_process_app(payloads)
        print("Seeded ActGuard demo data using in-process FastAPI app")

    return list(zip([label for label, _ in seed_steps], responses))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed local ActGuard demo data.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear local audit logs and approvals before seeding.",
    )
    parser.add_argument(
        "--server-url",
        default=DEFAULT_SERVER_URL,
        help=f"ActGuard server URL. Defaults to {DEFAULT_SERVER_URL}.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    seeded_results = seed_demo_data(reset=args.reset, server_url=args.server_url)
    counts = Counter(response["decision"] for _, response in seeded_results)

    print()
    for label, response in seeded_results:
        print(f"{label}")
        print(f"  decision: {response['decision']}")
        print(f"  matched_policy_id: {response['matched_policy_id']}")
        print(f"  risk_score: {response['risk_score']}")
        print(f"  trace_id: {response['trace_id']}")
        print()

    print("Summary")
    print(f"  allow: {counts['allow']}")
    print(f"  require_approval: {counts['require_approval']}")
    print(f"  block: {counts['block']}")


if __name__ == "__main__":
    main()
