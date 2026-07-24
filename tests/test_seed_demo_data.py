from __future__ import annotations

from collections import Counter
from pathlib import Path

from app.approvals import ApprovalRepository
from app.audit_log import AuditLogRepository
from scripts.seed_demo_data import build_seed_payloads, seed_demo_data


def test_seed_payloads_cover_demo_decisions() -> None:
    payloads = build_seed_payloads(batch_id="test")

    assert len(payloads) == 12
    assert payloads[0][1]["session_id"] == "seed-test-crm-safe"
    assert payloads[-1][1]["session_id"] == "seed-test-suspicious-sequence"


def test_seed_demo_data_writes_audit_logs_and_pending_approvals(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "seed-demo.db"
    monkeypatch.setenv("ACTGUARD_DB_PATH", str(database_path))
    monkeypatch.setenv("ACTGUARD_ADMIN_TOKEN", "test-admin-token")

    seeded_results = seed_demo_data(
        reset=True,
        server_url="http://127.0.0.1:9",
    )

    counts = Counter(response["decision"] for _, response in seeded_results)
    assert counts == {
        "allow": 4,
        "require_approval": 3,
        "block": 5,
    }

    audit_page = AuditLogRepository(database_path).list_entries(limit=50)
    approvals = ApprovalRepository(database_path).list_pending()

    assert audit_page.total == 12
    assert len(audit_page.items) == 12
    assert len(approvals) == 3
