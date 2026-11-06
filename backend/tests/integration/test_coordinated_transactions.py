import concurrent.futures
import uuid
import pytest
from sqlalchemy import text

import app.mcp.tools
from app.mcp.server import registry
from app.services.coordinated_transaction_service import submit_coordinated_transactions
from app.services.target_service import initialize_target
from app.storage.db import SessionLocal
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles


@pytest.fixture
def sample_targets():
    """Create three distinct targets in a clean database session."""
    with SessionLocal() as session:
        t1 = initialize_target(
            session,
            filename="math_kernel.py",
            content="def compute_factor(a: int, b: int) -> int:\n    return a + b\n",
            target_type="text/x-python",
        )
        t2 = initialize_target(
            session,
            filename="client_alpha.py",
            content="from math_kernel import compute_factor\nval = compute_factor(1, 2)\n",
            target_type="text/x-python",
        )
        t3 = initialize_target(
            session,
            filename="client_beta.py",
            content="from math_kernel import compute_factor\nprint(compute_factor(3, 4))\n",
            target_type="text/x-python",
        )
        session.commit()
        return {
            "t1": {"id": str(t1.target_file_id), "version": t1.version, "hash": t1.current_hash},
            "t2": {"id": str(t2.target_file_id), "version": t2.version, "hash": t2.current_hash},
            "t3": {"id": str(t3.target_file_id), "version": t3.version, "hash": t3.current_hash},
        }


def test_coordinated_transaction_atomic_success_across_three_targets(sample_targets):
    t1 = sample_targets["t1"]
    t2 = sample_targets["t2"]
    t3 = sample_targets["t3"]

    payload = {
        "intent": "Rename compute_factor to compute_product across kernel and clients",
        "targets": [
            {
                "target_file_id": t1["id"],
                "expected_target_version": t1["version"],
                "expected_current_hash": t1["hash"],
                "operations": [
                    {"op": "match", "match": "def compute_factor(", "replace": "def compute_product("},
                    {"op": "match", "match": "return a + b", "replace": "return a * b"},
                ],
            },
            {
                "target_file_id": t2["id"],
                "expected_target_version": t2["version"],
                "expected_current_hash": t2["hash"],
                "operations": [
                    {"op": "match", "match": "import compute_factor", "replace": "import compute_product"},
                    {"op": "match", "match": "val = compute_factor(1, 2)", "replace": "val = compute_product(1, 2)"},
                ],
            },
            {
                "target_file_id": t3["id"],
                "expected_target_version": t3["version"],
                "expected_current_hash": t3["hash"],
                "operations": [
                    {"op": "match", "match": "import compute_factor", "replace": "import compute_product"},
                    {"op": "match", "match": "print(compute_factor(3, 4))", "replace": "print(compute_product(3, 4))"},
                ],
            },
        ],
    }

    result = registry.call("patchdiff_commit_multi_target", **payload)
    assert result["status"] == "accepted"
    coord_id = result["coordinated_transaction_id"]
    assert coord_id is not None
    assert len(result["targets"]) == 3

    # Verify database state
    with SessionLocal() as session:
        for item in result["targets"]:
            tid = uuid.UUID(item["target_file_id"])
            target = session.get(CloudTargetFiles, tid)
            assert target.version == 1
            assert target.current_hash == item["current_hash"]
            assert "compute_product" in target.current_content
            assert "compute_factor" not in target.current_content

        # Verify audit logs share coordinated_transaction_id
        logs = session.query(AppendOnlyPdcpLogs).filter(
            AppendOnlyPdcpLogs.target_file_id.in_([uuid.UUID(t["target_file_id"]) for t in result["targets"]])
        ).all()
        assert len(logs) == 3
        for log in logs:
            assert log.status == "accepted"
            assert log.diagnostic_json["coordinated_transaction_id"] == coord_id
            assert log.diagnostic_json["target_count"] == 3

        # Verify ledgers created
        ledgers = session.query(AppendOnlyManifestLedger).filter(
            AppendOnlyManifestLedger.target_file_id.in_([uuid.UUID(t["target_file_id"]) for t in result["targets"]])
        ).all()
        assert len(ledgers) == 6  # 2 edits per target * 3 targets


def test_coordinated_transaction_all_or_nothing_rollback_on_guard_mismatch(sample_targets):
    t1 = sample_targets["t1"]
    t2 = sample_targets["t2"]
    t3 = sample_targets["t3"]

    payload = {
        "intent": "Partial failure test: target 3 has stale version guard",
        "targets": [
            {
                "target_file_id": t1["id"],
                "expected_target_version": t1["version"],
                "expected_current_hash": t1["hash"],
                "operations": [{"op": "match", "match": "def compute_factor", "replace": "def broken"}],
            },
            {
                "target_file_id": t2["id"],
                "expected_target_version": t2["version"],
                "expected_current_hash": t2["hash"],
                "operations": [{"op": "match", "match": "import compute_factor", "replace": "import broken"}],
            },
            {
                "target_file_id": t3["id"],
                "expected_target_version": 9999,  # Stale version guard!
                "expected_current_hash": t3["hash"],
                "operations": [{"op": "match", "match": "import compute_factor", "replace": "import broken"}],
            },
        ],
    }

    result = registry.call("patchdiff_commit_multi_target", **payload)
    assert result["status"] == "rejected"
    assert result["code"] == "target_version_mismatch"
    assert result["failed_target_file_id"] == t3["id"]

    # Verify zero targets were mutated in PostgreSQL
    with SessionLocal() as session:
        for t in (t1, t2, t3):
            target = session.get(CloudTargetFiles, uuid.UUID(t["id"]))
            assert target.version == t["version"]
            assert target.current_hash == t["hash"]
            assert "broken" not in target.current_content


def test_coordinated_transaction_all_or_nothing_rollback_on_match_absent(sample_targets):
    t1 = sample_targets["t1"]
    t2 = sample_targets["t2"]

    payload = {
        "intent": "Operation failure test: target 2 match absent",
        "targets": [
            {
                "target_file_id": t1["id"],
                "expected_target_version": t1["version"],
                "expected_current_hash": t1["hash"],
                "operations": [{"op": "match", "match": "def compute_factor", "replace": "def modified"}],
            },
            {
                "target_file_id": t2["id"],
                "expected_target_version": t2["version"],
                "expected_current_hash": t2["hash"],
                "operations": [{"op": "match", "match": "NONEXISTENT_TEXT_XYZ", "replace": "modified"}],
            },
        ],
    }

    result = registry.call("patchdiff_commit_multi_target", **payload)
    assert result["status"] == "rejected"
    assert result["code"] == "match_absent"
    assert result["failed_target_file_id"] == t2["id"]

    # Verify target 1 was NOT mutated
    with SessionLocal() as session:
        target1 = session.get(CloudTargetFiles, uuid.UUID(t1["id"]))
        assert target1.version == t1["version"]
        assert "def modified" not in target1.current_content


def test_coordinated_transaction_rejects_duplicate_target_ids(sample_targets):
    t1 = sample_targets["t1"]

    payload = {
        "intent": "Duplicate target check",
        "targets": [
            {
                "target_file_id": t1["id"],
                "operations": [{"op": "match", "match": "a", "replace": "b"}],
            },
            {
                "target_file_id": t1["id"],
                "operations": [{"op": "match", "match": "b", "replace": "c"}],
            },
        ],
    }

    result = registry.call("patchdiff_commit_multi_target", **payload)
    assert result["status"] == "rejected"
    assert result["code"] == "duplicate_target_in_coordinated_transaction"


def test_deadlock_free_concurrency_under_reversed_target_order(sample_targets):
    """Verify that concurrent transactions requesting targets in opposite orders do not deadlock."""
    t1 = sample_targets["t1"]
    t2 = sample_targets["t2"]

    def run_tx_forward():
        return registry.call(
            "patchdiff_commit_multi_target",
            intent="Forward order transaction [t1, t2]",
            targets=[
                {
                    "target_file_id": t1["id"],
                    "expected_target_version": t1["version"],
                    "operations": [{"op": "match", "match": "def compute_factor", "replace": "def fn1"}],
                },
                {
                    "target_file_id": t2["id"],
                    "expected_target_version": t2["version"],
                    "operations": [{"op": "match", "match": "import compute_factor", "replace": "import fn1"}],
                },
            ],
        )

    def run_tx_reversed():
        return registry.call(
            "patchdiff_commit_multi_target",
            intent="Reversed order transaction [t2, t1]",
            targets=[
                {
                    "target_file_id": t2["id"],
                    "expected_target_version": t2["version"],
                    "operations": [{"op": "match", "match": "import compute_factor", "replace": "import fn2"}],
                },
                {
                    "target_file_id": t1["id"],
                    "expected_target_version": t1["version"],
                    "operations": [{"op": "match", "match": "def compute_factor", "replace": "def fn2"}],
                },
            ],
        )

    # Run both simultaneously
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_tx_forward)
        f2 = executor.submit(run_tx_reversed)
        r1 = f1.result(timeout=10)
        r2 = f2.result(timeout=10)

    # One transaction must succeed and the other must fail with version mismatch (or both succeed if non-conflicting)
    statuses = {r1["status"], r2["status"]}
    assert "accepted" in statuses
    # Crucially: neither threw psycopg.errors.DeadlockDetected
