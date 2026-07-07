from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SERVER_URL = "http://127.0.0.1:8000"


def build_payload(
    *,
    session_id: str,
    tool_name: str,
    action: str,
    resource: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    return {
        "agent_id": "demo-agent",
        "session_id": session_id,
        "tool_name": tool_name,
        "action": action,
        "resource": resource,
        "parameters": parameters,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def post_to_running_server(payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{DEFAULT_SERVER_URL}/v1/tool-call",
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


def run_demo() -> None:
    session_id = "demo-session"
    steps = [
        (
            "Read CRM customer data",
            build_payload(
                session_id=session_id,
                tool_name="crm",
                action="read",
                resource="customers/acme-corp",
                parameters={"customer_id": "acme-corp", "fields": ["name", "tier"]},
            ),
        ),
        (
            "Export cross-border financial report",
            build_payload(
                session_id=session_id,
                tool_name="finance",
                action="export",
                resource="reports/q2-cross-border",
                parameters={"report_type": "financial", "cross_border": True},
            ),
        ),
        (
            "Delete 10 files",
            build_payload(
                session_id=session_id,
                tool_name="file_store",
                action="delete",
                resource="drive/folder/customer-exports",
                parameters={"count": 10, "path": "/mock/customer-exports"},
            ),
        ),
    ]
    payloads = [payload for _, payload in steps]

    try:
        responses = [post_to_running_server(payload) for payload in payloads]
        print(f"ActGuard demo using running server at {DEFAULT_SERVER_URL}")
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        responses = run_with_in_process_app(payloads)
        print("ActGuard demo using in-process FastAPI app")

    print()
    for (label, _), response in zip(steps, responses):
        print(f"{label}")
        print(f"  decision: {response['decision']}")
        print(f"  reason: {response['reason']}")
        print(f"  matched_policy_id: {response['matched_policy_id']}")
        print(f"  risk_score: {response['risk_score']}")
        print(f"  trace_id: {response['trace_id']}")
        print()


if __name__ == "__main__":
    run_demo()
