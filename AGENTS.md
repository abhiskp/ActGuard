# ActGuard Coding Instructions

ActGuard is a runtime control plane for AI-agent tool calls.

## Product principle

Do not build a generic security toy. Build a clean developer-facing middleware product that demonstrates policy-as-code, agent trace monitoring, approval workflows, and auditability.

## Coding rules

- Use Python 3.11+.
- Use FastAPI, Pydantic, SQLite, pytest, and PyYAML.
- Keep modules small and readable.
- Prefer explicit types.
- Add tests for every core behavior.
- Do not use real Gmail, Slack, Drive, CRM, or database integrations in the MVP.
- Use mock tools and mock agent behavior.
- Never execute destructive real-world actions.
- Store audit logs locally in SQLite.
- Keep the project runnable with simple local commands.

## MVP priority order

1. API schemas
2. Policy engine
3. Sequence detector
4. Audit logging
5. Approval queue
6. Demo agent
7. Tests
8. README
9. Optional dashboard

## Definition of done

The project is complete when `pytest` passes and `scripts/demo_agent.py` shows allow, require_approval, and block decisions.
