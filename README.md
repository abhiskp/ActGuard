# ActGuard

ActGuard is a runtime control plane for AI-agent tool calls. It sits between an AI agent and mock external tools, evaluates each requested action against policy-as-code rules, records the decision, and creates human approval work items when needed.

This MVP does not connect to Gmail, Slack, Drive, CRM, databases, or any real third-party system. All tool names and resources are mock identifiers.

## Architecture

- `app/main.py` exposes the FastAPI API.
- `app/models.py` defines typed request and response schemas with Pydantic.
- `app/policy_engine.py` loads YAML policies and evaluates scalar, parameter, and sequence conditions.
- `app/sequence_detector.py` keeps recent tool-call history per session.
- `app/audit_log.py` writes every decision to SQLite.
- `app/approvals.py` stores and updates human approval queue items.
- `config/policies.yaml` contains the default policy-as-code rules.
- `scripts/demo_agent.py` runs a mock agent scenario.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run The API

```bash
export ACTGUARD_ADMIN_TOKEN="change-me-local-dev"
uvicorn app.main:app --reload
```

The server listens on `http://127.0.0.1:8000` by default.

- Dashboard: `http://127.0.0.1:8000/`
- API docs: `http://127.0.0.1:8000/docs`

## Dashboard

The dashboard is served by FastAPI from `static/index.html`. It includes:

- a mock tool-call tester
- a pending approval queue with approve and reject actions
- decision counters
- an audit log table

No frontend build step is required.

The dashboard has an Admin Token field. Use the same value as `ACTGUARD_ADMIN_TOKEN` when approving or rejecting items.

## Tool-Call API

`POST /v1/tool-call`

```json
{
  "agent_id": "agent-1",
  "session_id": "session-1",
  "tool_name": "finance",
  "action": "export",
  "resource": "reports/q2-cross-border",
  "parameters": {
    "report_type": "financial",
    "cross_border": true
  },
  "timestamp": "2026-07-07T12:00:00Z"
}
```

Response:

```json
{
  "decision": "require_approval",
  "reason": "Cross-border financial exports require human approval.",
  "matched_policy_id": "require_approval_financial_export",
  "risk_score": 75,
  "trace_id": "..."
}
```

## Approval API

```bash
curl http://127.0.0.1:8000/v1/approvals
curl -X POST http://127.0.0.1:8000/v1/approvals/{approval_id}/approve \
  -H "X-ActGuard-Admin-Token: change-me-local-dev"
curl -X POST http://127.0.0.1:8000/v1/approvals/{approval_id}/reject \
  -H "X-ActGuard-Admin-Token: change-me-local-dev"
```

## Audit API

```bash
curl http://127.0.0.1:8000/v1/audit-logs
curl "http://127.0.0.1:8000/v1/audit-logs?decision=block&limit=25&offset=0"
curl "http://127.0.0.1:8000/v1/audit-logs?agent_id=agent-api&session_id=session-api"
```

Supported audit log query parameters:

- `limit`: page size from `1` to `200`, default `50`
- `offset`: page offset, default `0`
- `agent_id`
- `session_id`
- `decision`: `allow`, `block`, or `require_approval`
- `tool_name`
- `action`

## Policy Format

Policies live in `config/policies.yaml`.

Each policy has:

- `id`: stable policy identifier.
- `priority`: higher priority policies are evaluated first.
- `effect`: one of `allow`, `block`, or `require_approval`.
- `risk_score`: integer from `0` to `100`.
- `reason`: human-readable decision reason.
- `conditions`: matching rules.

Supported conditions:

- `tool_name.equals`
- `action.equals`
- `resource.equals`
- parameter `equals`
- parameter `greater_than`
- parameter `less_than`
- parameter `contains`
- parameter `regex`
- scalar or parameter `in`
- ordered `sequence` rules based on previous tool calls in the same session plus the current call

Example:

```yaml
- id: require_approval_financial_export
  priority: 70
  effect: require_approval
  risk_score: 75
  reason: Cross-border financial exports require human approval.
  conditions:
    tool_name:
      equals: finance
    action:
      equals: export
    parameters:
      - path: report_type
        equals: financial
      - path: cross_border
        equals: true
```

Policies are validated when ActGuard starts and whenever they are reloaded. Validation errors include the exact policy path, such as `policies[0].conditions.parameters[0]`.

Reload policies without restarting the server:

```bash
curl -X POST http://127.0.0.1:8000/v1/policies/reload \
  -H "X-ActGuard-Admin-Token: change-me-local-dev"
```

## Admin Protection

ActGuard protects administrative actions with an API token:

- approval decisions
- policy reloads

Set `ACTGUARD_ADMIN_TOKEN` before starting the server. Send the same value in the `X-ActGuard-Admin-Token` header for protected endpoints.

If `ACTGUARD_ADMIN_TOKEN` is not configured, admin endpoints fail closed with `503 Service Unavailable`. If a request omits the token or sends the wrong token, ActGuard returns `401 Unauthorized`.

## Demo

```bash
python scripts/demo_agent.py
```

The demo sends three mock actions:

1. Read CRM customer data: allowed.
2. Export a cross-border financial report: requires approval.
3. Delete 10 files: blocked.

The script uses a running local server when one is available. If not, it falls back to the in-process FastAPI app.

## Tests

```bash
pytest
```

GitHub Actions runs the test suite on pushes and pull requests to `main` using Python 3.11 and 3.12.

## Docker

```bash
export ACTGUARD_ADMIN_TOKEN="change-me-local-dev"
docker compose up --build
```

SQLite data is stored in a Docker volume mounted at `/app/data`.
