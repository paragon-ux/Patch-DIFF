"""Postgres integration tests for typed submit, idempotency, stage validity, replay, and read tools."""

from __future__ import annotations

import uuid

from sqlalchemy import select, update

from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.validity import NOT_EVALUATED
from app.core.versions import LEGACY_RUNTIME_VERSION, RUNTIME_VERSION
from app.mcp import tools
from app.pdcp.models import SUPPORTED_PROTOCOL_VERSION
from app.pdcp.typed import ALLOWED_TYPED_EDIT_FIELDS, REQUIRED_TYPED_EDIT_FIELDS, TYPED_PROTOCOL_VERSION
from app.services.pdcp_service import submit_edits, submit_pdcp
from app.services.regeneration_service import request_regeneration
from app.services.replay_service import replay_target
from app.storage.db import SessionLocal
from app.storage.models import (
    AppendOnlyManifestLedger,
    AppendOnlyPdcpLogs,
    CloudTargetFiles,
    TargetSnapshots,
)
from backend.tests.integration.helpers import create_target, pdcp_for


def _edit(match: str, replace: str, **extra) -> dict:
    return {"match": match, "replace": replace, **extra}


def test_typed_accept_logs_typed_record_and_derived_ledger_row() -> None:
    target_id = create_target("old text")
    with SessionLocal() as session:
        result = submit_edits(
            session,
            target_file_id=target_id,
            intent="Swap word.",
            edits=[_edit("old", "new", rationale="why")],
            expected_target_version=0,
        )
        assert result.status == "accepted"
        log = session.get(AppendOnlyPdcpLogs, result.pdcp_log_id)
        assert log.protocol_version == TYPED_PROTOCOL_VERSION
        assert log.runtime_version == RUNTIME_VERSION
        assert log.pdcp_content_hash == canonical_sha256(log.pdcp_content)
        row = session.scalars(
            select(AppendOnlyManifestLedger).where(AppendOnlyManifestLedger.pdcp_log_id == log.pdcp_log_id)
        ).one()
        assert row.origin == "typed"
        assert row.intent == "why"
        assert row.input_state is None and row.output_state is None and row.risk is None
        assert row.derived_json["span_start"] == 0
        assert session.get(CloudTargetFiles, target_id).current_content == "new text"


def test_pdcp_and_typed_ledger_rows_both_carry_derived_facts_and_origin() -> None:
    target_id = create_target("alpha beta")
    with SessionLocal() as session:
        p_res = submit_pdcp(
            session,
            target_file_id=target_id,
            pdcp_content=pdcp_for(target_id, ("alpha", "ALPHA")),
            expected_target_version=0,
        )
        assert p_res.status == "accepted"
        t_res = submit_edits(
            session,
            target_file_id=target_id,
            intent="Uppercase beta.",
            edits=[_edit("beta", "BETA", risk="low")],
            expected_target_version=1,
        )
        assert t_res.status == "accepted"

        rows = session.scalars(
            select(AppendOnlyManifestLedger)
            .where(AppendOnlyManifestLedger.target_file_id == target_id)
            .order_by(AppendOnlyManifestLedger.ledger_sequence)
        ).all()
        assert len(rows) == 2

        pdcp_row, typed_row = rows
        assert pdcp_row.origin == "pdcp_manifest"
        assert pdcp_row.input_state is not None
        assert pdcp_row.output_state is not None
        assert pdcp_row.derived_json["span_start"] == 0
        assert pdcp_row.derived_json["span_end"] == 5

        assert typed_row.origin == "typed"
        assert typed_row.intent == "Uppercase beta."
        assert typed_row.risk == "low"
        assert typed_row.input_state is None
        assert typed_row.derived_json["span_start"] == 6
        assert typed_row.derived_json["span_end"] == 10


def test_typed_submit_without_any_guard_is_rejected_and_logged_without_mutation() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        result = submit_edits(session, target_file_id=target_id, intent="x", edits=[_edit("old", "new")])
        assert result.status == "rejected"
        assert result.failure_reason is FailureReason.CONTEXT_MISSING
        assert session.get(CloudTargetFiles, target_id).current_content == "old"
        log = session.get(AppendOnlyPdcpLogs, result.pdcp_log_id)
        assert log.status == "rejected" and log.protocol_version == TYPED_PROTOCOL_VERSION


def test_format_specific_vs_format_neutral_diagnostics_and_no_pdcp_leakage_on_typed_rejection() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        typed_rej = submit_edits(
            session,
            target_file_id=target_id,
            intent="x",
            edits=[_edit("old", "new", region_hint="forbidden")],
            expected_target_version=0,
        )
        assert typed_rej.status == "rejected"
        assert typed_rej.failure_reason is FailureReason.MANIFEST_INVALID
        diag = typed_rej.diagnostic
        assert diag["format"] == TYPED_PROTOCOL_VERSION
        assert diag["requires_new_submission"] is True
        assert set(diag["allowed_edit_fields"]) == set(ALLOWED_TYPED_EDIT_FIELDS)
        assert set(diag["required_edit_fields"]) == set(REQUIRED_TYPED_EDIT_FIELDS)
        # No PDCP-specific manifest diagnostics may leak onto typed rejections:
        for forbidden_key in ("missing_fields", "invalid_fields", "unknown_fields", "requires_new_pdcp"):
            assert forbidden_key not in diag

        # Applicability rejection on typed path also must not leak requires_new_pdcp:
        typed_absent = submit_edits(
            session,
            target_file_id=target_id,
            intent="x",
            edits=[_edit("nonexistent", "new")],
            expected_target_version=0,
        )
        assert typed_absent.failure_reason is FailureReason.MATCH_ABSENT
        assert typed_absent.diagnostic["format"] == TYPED_PROTOCOL_VERSION
        assert typed_absent.diagnostic["requires_new_submission"] is True
        assert "requires_new_pdcp" not in typed_absent.diagnostic

        # Legacy PDCP rejection retains its PDCP-specific diagnostic fields:
        pdcp_rej = submit_pdcp(
            session,
            target_file_id=target_id,
            pdcp_content=pdcp_for(target_id, ("nonexistent", "new")),
            expected_target_version=0,
        )
        assert pdcp_rej.failure_reason is FailureReason.MATCH_ABSENT
        assert pdcp_rej.diagnostic["format"] == SUPPORTED_PROTOCOL_VERSION
        assert pdcp_rej.diagnostic["requires_new_pdcp"] is True
        assert pdcp_rej.diagnostic["requires_new_submission"] is True


def test_validity_stages_across_typed_and_pdcp_paths_via_mcp_tools() -> None:
    target_id = str(create_target("hello world"))

    # 1. Pre-parse guard failure (expected_current_hash mismatch) -> protocol_valid: None, transaction_valid: None
    pre_hash = tools.patchdiff_submit_edits(
        target_file_id=target_id,
        intent="x",
        edits=[_edit("hello", "hi")],
        expected_current_hash="0" * 64,
    )
    assert pre_hash["failure_reason"] == "target_hash_mismatch"
    assert pre_hash["validity"] == {
        "protocol_valid": None,
        "transaction_valid": None,
        "task_correct": NOT_EVALUATED,
        "semantic": NOT_EVALUATED,
    }

    # 2. In-core PDCP header target_hash mismatch (no pre-parse guard) -> protocol_valid: True, transaction_valid: False
    bad_header_pdcp = pdcp_for(uuid.UUID(target_id), ("hello", "hi"), header_hash="0" * 64)
    in_core_hash = tools.patchdiff_submit_pdcp(
        target_file_id=target_id,
        pdcp_content=bad_header_pdcp,
    )
    assert in_core_hash["failure_reason"] == "target_hash_mismatch"
    assert in_core_hash["validity"] == {
        "protocol_valid": True,
        "transaction_valid": False,
        "task_correct": NOT_EVALUATED,
        "semantic": NOT_EVALUATED,
    }

    # 3. Protocol validation failure -> protocol_valid: False, transaction_valid: None
    proto_fail = tools.patchdiff_submit_edits(
        target_file_id=target_id,
        intent="   ",
        edits=[_edit("hello", "hi")],
        expected_target_version=0,
    )
    assert proto_fail["failure_reason"] == "manifest_missing"
    assert proto_fail["validity"] == {
        "protocol_valid": False,
        "transaction_valid": None,
        "task_correct": NOT_EVALUATED,
        "semantic": NOT_EVALUATED,
    }

    # 4. Transaction applicability failure -> protocol_valid: True, transaction_valid: False
    tx_fail = tools.patchdiff_submit_edits(
        target_file_id=target_id,
        intent="x",
        edits=[_edit("absent", "hi")],
        expected_target_version=0,
    )
    assert tx_fail["failure_reason"] == "match_absent"
    assert tx_fail["validity"] == {
        "protocol_valid": True,
        "transaction_valid": False,
        "task_correct": NOT_EVALUATED,
        "semantic": NOT_EVALUATED,
    }

    # 5. Post-simulation commit guard failure (TARGET_DIVERGED) -> protocol_valid: True, transaction_valid: True
    with SessionLocal() as session:
        def _corrupt_during_simulation(target):
            target.version = 99

        diverged = submit_edits(
            session,
            target_file_id=target_id,
            intent="x",
            edits=[_edit("hello", "hi")],
            expected_target_version=0,
            _before_final_guard=_corrupt_during_simulation,
        )
        assert diverged.failure_reason is FailureReason.TARGET_DIVERGED
        payload = tools._submit_result_to_payload(diverged)
        assert payload["validity"] == {
            "protocol_valid": True,
            "transaction_valid": True,
            "task_correct": NOT_EVALUATED,
            "semantic": NOT_EVALUATED,
        }


def test_malformed_uuid_and_invalid_parent_lineage_handling() -> None:
    # Malformed target_file_id returns CONTEXT_INVALID without crashing
    bad_target = tools.patchdiff_submit_edits(
        target_file_id="not-a-uuid",
        intent="x",
        edits=[_edit("a", "b")],
        expected_target_version=0,
    )
    assert bad_target["status"] == "rejected"
    assert bad_target["failure_reason"] == "context_invalid"
    assert bad_target["validity"]["protocol_valid"] is None

    # Nonexistent valid UUID returns TARGET_NOT_FOUND
    missing_target = tools.patchdiff_submit_edits(
        target_file_id=str(uuid.uuid4()),
        intent="x",
        edits=[_edit("a", "b")],
        expected_target_version=0,
    )
    assert missing_target["status"] == "rejected"
    assert missing_target["failure_reason"] == "target_not_found"
    assert missing_target["validity"]["protocol_valid"] is None

    target_a = str(create_target("hello"))
    target_b = str(create_target("world"))

    # Nonexistent parent_pdcp_log_id -> rejected with CONTEXT_INVALID and logged with parent_pdcp_log_id=None
    missing_parent = tools.patchdiff_submit_edits(
        target_file_id=target_a,
        intent="x",
        edits=[_edit("hello", "hi")],
        expected_target_version=0,
        parent_pdcp_log_id=str(uuid.uuid4()),
    )
    assert missing_parent["status"] == "rejected"
    assert missing_parent["failure_reason"] == "context_invalid"
    assert missing_parent["pdcp_log_id"] is not None

    # Malformed parent_pdcp_log_id -> rejected with CONTEXT_INVALID
    malformed_parent = tools.patchdiff_submit_edits(
        target_file_id=target_a,
        intent="x",
        edits=[_edit("hello", "hi")],
        expected_target_version=0,
        parent_pdcp_log_id="not-a-uuid",
    )
    assert malformed_parent["status"] == "rejected"
    assert malformed_parent["failure_reason"] == "context_invalid"

    # Cross-target parent_pdcp_log_id -> rejected with CONTEXT_INVALID
    other_attempt = tools.patchdiff_submit_edits(
        target_file_id=target_b,
        intent="x",
        edits=[_edit("world", "earth")],
        expected_target_version=0,
    )
    cross_parent = tools.patchdiff_submit_edits(
        target_file_id=target_a,
        intent="x",
        edits=[_edit("hello", "hi")],
        expected_target_version=0,
        parent_pdcp_log_id=other_attempt["pdcp_log_id"],
    )
    assert cross_parent["status"] == "rejected"
    assert cross_parent["failure_reason"] == "context_invalid"


def test_stale_guard_rejects_and_lost_response_retry_cannot_apply_twice() -> None:
    target_id = create_target("old")
    with SessionLocal() as session:
        first = submit_edits(
            session, target_file_id=target_id, intent="x", edits=[_edit("old", "new")], expected_target_version=0
        )
        assert first.status == "accepted"
        retry = submit_edits(
            session, target_file_id=target_id, intent="x", edits=[_edit("old", "new")], expected_target_version=0
        )
        assert retry.status == "rejected"
        assert retry.failure_reason is FailureReason.TARGET_VERSION_MISMATCH
        hashes = session.scalars(
            select(AppendOnlyPdcpLogs.pdcp_content_hash).where(AppendOnlyPdcpLogs.target_file_id == target_id)
        ).all()
        assert len(hashes) == 2 and hashes[0] == hashes[1]


def test_client_request_id_idempotency_lost_response_recovery_and_conflict_rejection() -> None:
    target_id = str(create_target("alpha"))

    # 1. First submission with client_request_id="req-001"
    first = tools.patchdiff_submit_edits(
        target_file_id=target_id,
        intent="Alpha to Beta.",
        edits=[_edit("alpha", "beta")],
        expected_target_version=0,
        client_request_id="req-001",
    )
    assert first["status"] == "accepted"
    assert first["deduplicated"] is False
    assert first["client_request_id"] == "req-001"
    assert first["version"] == 1

    # 2. Target advances through an ABA sequence ("beta" -> "alpha") and a no-op edit ("alpha" -> "alpha")
    second = tools.patchdiff_submit_edits(
        target_file_id=target_id,
        intent="Beta back to Alpha.",
        edits=[_edit("beta", "alpha")],
        expected_target_version=1,
    )
    assert second["status"] == "accepted" and second["version"] == 2

    noop = tools.patchdiff_submit_edits(
        target_file_id=target_id,
        intent="No-op hash preserving edit.",
        edits=[_edit("alpha", "alpha")],
        expected_current_hash=second["after_hash"],
        client_request_id="req-noop",
    )
    assert noop["status"] == "accepted" and noop["version"] == 3
    assert noop["before_hash"] == noop["after_hash"]

    # 3. Retry of "req-001" (even though target is now v3 and content is "alpha" again!):
    # Because client_request_id="req-001" was already recorded, it returns the original
    # terminal outcome without re-applying the edit or creating a new log row!
    recovered_first = tools.patchdiff_submit_edits(
        target_file_id=target_id,
        intent="Alpha to Beta.",
        edits=[_edit("alpha", "beta")],
        expected_target_version=0,
        client_request_id="req-001",
    )
    assert recovered_first["status"] == "accepted"
    assert recovered_first["deduplicated"] is True
    assert recovered_first["pdcp_log_id"] == first["pdcp_log_id"]
    assert recovered_first["version"] == 1
    assert recovered_first["after_hash"] == first["after_hash"]
    # Target remains at v3 with content "alpha" (not mutated to "beta" a second time!)
    current = tools.patchdiff_get_target(target_file_id=target_id)
    assert current["version"] == 3
    assert current["current_content"] == "alpha"

    # 4. Retry of no-op hash-guarded edit with same client_request_id also deduplicates cleanly
    recovered_noop = tools.patchdiff_submit_edits(
        target_file_id=target_id,
        intent="No-op hash preserving edit.",
        edits=[_edit("alpha", "alpha")],
        expected_current_hash=second["after_hash"],
        client_request_id="req-noop",
    )
    assert recovered_noop["status"] == "accepted"
    assert recovered_noop["deduplicated"] is True
    assert recovered_noop["pdcp_log_id"] == noop["pdcp_log_id"]
    assert tools.patchdiff_get_target(target_file_id=target_id)["version"] == 3

    # 5. Rejected submission with client_request_id="req-rej" also recovers its terminal rejection
    rej = tools.patchdiff_submit_edits(
        target_file_id=target_id,
        intent="Missing match.",
        edits=[_edit("nonexistent", "x")],
        expected_target_version=3,
        client_request_id="req-rej",
    )
    assert rej["status"] == "rejected"
    assert rej["deduplicated"] is False
    recovered_rej = tools.patchdiff_submit_edits(
        target_file_id=target_id,
        intent="Missing match.",
        edits=[_edit("nonexistent", "x")],
        expected_target_version=3,
        client_request_id="req-rej",
    )
    assert recovered_rej["status"] == "rejected"
    assert recovered_rej["deduplicated"] is True
    assert recovered_rej["pdcp_log_id"] == rej["pdcp_log_id"]

    # 6. Conflicting reuse of client_request_id="req-001" with different payload is rejected
    conflict = tools.patchdiff_submit_edits(
        target_file_id=target_id,
        intent="Different intent with reused id.",
        edits=[_edit("alpha", "gamma")],
        expected_target_version=3,
        client_request_id="req-001",
    )
    assert conflict["status"] == "rejected"
    assert conflict["failure_reason"] == "context_invalid"
    assert conflict["deduplicated"] is False
    assert conflict["diagnostic"]["existing_pdcp_log_id"] == first["pdcp_log_id"]

    # 7. patchdiff_get_pdcp_log filters by client_request_id
    by_req_id = tools.patchdiff_get_pdcp_log(target_file_id=target_id, client_request_id="req-001")
    assert len(by_req_id["entries"]) == 1
    assert by_req_id["entries"][0]["pdcp_log_id"] == first["pdcp_log_id"]
    assert by_req_id["entries"][0]["client_request_id"] == "req-001"


def test_host_loop_reject_reread_revise_keeps_lineage_without_regeneration_tools() -> None:
    target_id = create_target("name: A\nname: B\n")
    with SessionLocal() as session:
        rejected = submit_edits(
            session, target_file_id=target_id, intent="x", edits=[_edit("name:", "title:")], expected_target_version=0
        )
        assert rejected.failure_reason is FailureReason.MATCH_AMBIGUOUS
        assert rejected.diagnostic["occurrence_count"] == 2
        accepted = submit_edits(
            session,
            target_file_id=target_id,
            intent="x",
            edits=[_edit("name:", "title:", occurrence_index=2)],
            expected_target_version=0,
            parent_pdcp_log_id=rejected.pdcp_log_id,
            attempt=2,
        )
        assert accepted.status == "accepted"
        child = session.get(AppendOnlyPdcpLogs, accepted.pdcp_log_id)
        assert child.parent_pdcp_log_id == rejected.pdcp_log_id and child.regeneration_attempt == 2
        assert session.get(AppendOnlyPdcpLogs, rejected.pdcp_log_id).status == "rejected"


def test_mixed_pdcp_and_typed_history_replays_and_matches_materialized_state() -> None:
    target_id = create_target("one two")
    with SessionLocal() as session:
        assert submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("one", "1"))).status == "accepted"
        assert (
            submit_edits(session, target_file_id=target_id, intent="x", edits=[_edit("two", "2")], expected_target_version=1).status
            == "accepted"
        )
        replayed = replay_target(session, target_file_id=target_id)
        assert replayed.status == "success"
        assert replayed.reconstructed_content == "1 2"
        assert replayed.materialized_state_matches is True
        assert replayed.materialized_state_checks == {
            "content_matches": True,
            "stored_hash_matches": True,
            "recomputed_hash_matches": True,
            "version_matches": True,
        }


def test_replay_success_is_distinct_from_materialized_state_health_and_reports_component_checks() -> None:
    target_id = create_target("a")
    with SessionLocal() as session:
        submit_edits(session, target_file_id=target_id, intent="x", edits=[_edit("a", "b")], expected_target_version=0)
        session.execute(
            update(CloudTargetFiles).where(CloudTargetFiles.target_file_id == target_id).values(current_hash="0" * 64)
        )
        session.commit()
        replayed = replay_target(session, target_file_id=target_id)
        assert replayed.status == "success"
        assert replayed.materialized_state_matches is False
        assert replayed.materialized_state_checks == {
            "content_matches": True,
            "stored_hash_matches": False,
            "recomputed_hash_matches": True,
            "version_matches": True,
        }


def test_replay_detects_tampered_before_hash_broken_version_chain_and_unknown_profiles() -> None:
    target_id = create_target("a")
    with SessionLocal() as session:
        submit_edits(session, target_file_id=target_id, intent="x", edits=[_edit("a", "b")], expected_target_version=0)
        log = session.scalars(
            select(AppendOnlyPdcpLogs).where(
                AppendOnlyPdcpLogs.target_file_id == target_id,
                AppendOnlyPdcpLogs.status == "accepted",
            )
        ).one()
        original_hash = log.before_hash
        log.before_hash = "f" * 64
        session.flush()
        assert replay_target(session, target_file_id=target_id).failure_reason is FailureReason.REPLAY_HASH_MISMATCH

        log.before_hash = original_hash
        log.before_version = 5
        session.flush()
        assert replay_target(session, target_file_id=target_id).failure_reason is FailureReason.REPLAY_PROTOCOL_INVALID

        log.before_version = 0
        log.runtime_version = "patchdiff-mvp-9.9.9"
        session.flush()
        assert replay_target(session, target_file_id=target_id).failure_reason is FailureReason.REPLAY_PROTOCOL_INVALID

        log.runtime_version = RUNTIME_VERSION
        log.protocol_version = "patchdiff-tx/99"
        session.flush()
        assert replay_target(session, target_file_id=target_id).failure_reason is FailureReason.REPLAY_PROTOCOL_INVALID

        log.protocol_version = TYPED_PROTOCOL_VERSION
        log.pdcp_content_hash = "0" * 64
        session.flush()
        assert replay_target(session, target_file_id=target_id).failure_reason is FailureReason.REPLAY_HASH_MISMATCH

        session.rollback()

    # Corrupted initial snapshot hash is also caught by replay
    with SessionLocal() as session:
        target = session.get(CloudTargetFiles, target_id)
        snap = session.get(TargetSnapshots, target.initial_snapshot_id)
        snap.content_hash = "0" * 64
        session.flush()
        assert replay_target(session, target_file_id=target_id).failure_reason is FailureReason.REPLAY_HASH_MISMATCH
        session.rollback()


def test_legacy_runtime_log_with_overlap_acceptance_still_replays() -> None:
    target_id = create_target("aaa")
    with SessionLocal() as session:
        result = submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("aa", "b")))
        assert result.failure_reason is FailureReason.MATCH_AMBIGUOUS
    legacy_id = create_target("aaa")
    with SessionLocal() as session:
        session.add(
            AppendOnlyPdcpLogs(
                target_file_id=legacy_id,
                editing_cycle_id=session.get(CloudTargetFiles, legacy_id).active_editing_cycle_id,
                submission_source="model_response",
                protocol_version="0.2.3",
                runtime_version=LEGACY_RUNTIME_VERSION,
                pdcp_content=pdcp_for(legacy_id, ("aa", "b")),
                pdcp_content_hash=canonical_sha256(pdcp_for(legacy_id, ("aa", "b"))),
                status="accepted",
                before_version=0,
                after_version=1,
                before_hash=canonical_sha256("aaa"),
                after_hash=canonical_sha256("ba"),
                change_count=1,
            )
        )
        session.flush()
        replayed = replay_target(session, target_file_id=legacy_id)
        assert replayed.status == "success" and replayed.reconstructed_content == "ba"
        session.rollback()


def test_read_target_and_find_occurrences_pagination_and_argument_validation() -> None:
    target_id = str(create_target("item=1\nitem=1\nitem=1\n"))

    # Read pagination via next_start
    page1 = tools.patchdiff_read_target(target_file_id=target_id, start=0, length=7)
    assert page1["status"] == "ok"
    assert page1["text"] == "item=1\n"
    assert page1["truncated"] is True
    assert page1["next_start"] == 7

    page2 = tools.patchdiff_read_target(target_file_id=target_id, start=page1["next_start"], length=100)
    assert page2["status"] == "ok"
    assert page2["text"] == "item=1\nitem=1\n"
    assert page2["truncated"] is False
    assert page2["next_start"] is None

    # Occurrence pagination via start_occurrence / next_occurrence_index
    occ1 = tools.patchdiff_find_occurrences(
        target_file_id=target_id, text="item=1", context_chars=4, start_occurrence=1, max_results=2
    )
    assert occ1["status"] == "ok"
    assert occ1["occurrence_count"] == 3
    assert occ1["returned_count"] == 2
    assert occ1["truncated"] is True
    assert occ1["next_occurrence_index"] == 3
    assert [o["occurrence_index"] for o in occ1["occurrences"]] == [1, 2]

    occ2 = tools.patchdiff_find_occurrences(
        target_file_id=target_id,
        text="item=1",
        context_chars=4,
        start_occurrence=occ1["next_occurrence_index"],
        max_results=2,
    )
    assert occ2["status"] == "ok"
    assert [o["occurrence_index"] for o in occ2["occurrences"]] == [3]
    assert occ2["truncated"] is False
    assert occ2["next_occurrence_index"] is None

    # Invalid argument checks
    assert tools.patchdiff_read_target(target_file_id=target_id, start=-1)["status"] == "invalid_argument"
    assert tools.patchdiff_read_target(target_file_id=target_id, start=0, length=0)["status"] == "invalid_argument"
    assert tools.patchdiff_read_target(target_file_id="bad-uuid")["status"] == "invalid_argument"
    assert tools.patchdiff_find_occurrences(target_file_id=target_id, text="")["status"] == "invalid_argument"
    assert (
        tools.patchdiff_find_occurrences(target_file_id=target_id, text="item=1", start_occurrence=0)["status"]
        == "invalid_argument"
    )
    assert tools.patchdiff_get_pdcp_log(target_file_id=target_id, before_sequence=0)["status"] == "invalid_argument"


def test_regeneration_wrapper_passes_guards_and_handles_missing_parent() -> None:
    missing = request_regeneration(SessionLocal(), pdcp_log_id=uuid.uuid4(), regenerated_pdcp_content="x")
    assert missing["status"] == "not_found"

    target_id = create_target("old")
    with SessionLocal() as session:
        rejected = submit_pdcp(session, target_file_id=target_id, pdcp_content=pdcp_for(target_id, ("zzz", "q")))
        out = request_regeneration(
            session,
            pdcp_log_id=rejected.pdcp_log_id,
            regenerated_pdcp_content=pdcp_for(target_id, ("old", "new")),
            expected_target_version=99,
        )
        assert out["status"] == "rejected"
        assert out["result"].failure_reason is FailureReason.TARGET_VERSION_MISMATCH


def test_run_003_sanitize_guard_metadata_before_persistence() -> None:
    target_id = create_target("content to edit")
    with SessionLocal() as session:
        # 1. 65-character oversized hash
        res_hash = submit_edits(
            session,
            target_file_id=target_id,
            intent="oversized hash test",
            edits=[_edit("content", "new_content")],
            expected_current_hash="a" * 65,
        )
        assert res_hash.status == "rejected"
        assert res_hash.failure_reason is FailureReason.CONTEXT_INVALID
        log_hash = session.get(AppendOnlyPdcpLogs, res_hash.pdcp_log_id)
        assert log_hash is not None
        assert log_hash.expected_current_hash is None
        assert log_hash.diagnostic_json.get("raw_expected_current_hash") == "a" * 65

        # 2. Negative expected_target_version
        res_ver = submit_edits(
            session,
            target_file_id=target_id,
            intent="negative version test",
            edits=[_edit("content", "new_content")],
            expected_target_version=-1,
        )
        assert res_ver.status == "rejected"
        assert res_ver.failure_reason is FailureReason.CONTEXT_INVALID
        log_ver = session.get(AppendOnlyPdcpLogs, res_ver.pdcp_log_id)
        assert log_ver is not None
        assert log_ver.expected_target_version is None
        assert log_ver.diagnostic_json.get("raw_expected_target_version") == -1

        # 3. Non-integer attempt
        res_att = submit_edits(
            session,
            target_file_id=target_id,
            intent="bad attempt test",
            edits=[_edit("content", "new_content")],
            expected_target_version=0,
            attempt="not-an-int",
        )
        assert res_att.status == "rejected"
        assert res_att.failure_reason is FailureReason.CONTEXT_INVALID
        log_att = session.get(AppendOnlyPdcpLogs, res_att.pdcp_log_id)
        assert log_att is not None
        assert log_att.regeneration_attempt is None
        assert log_att.diagnostic_json.get("raw_attempt") == "not-an-int"


def test_svc_001_parent_pdcp_log_id_must_reference_rejected_attempt() -> None:
    target_id = create_target("initial text")
    with SessionLocal() as session:
        # First submission succeeds (accepted)
        res_acc = submit_edits(
            session,
            target_file_id=target_id,
            intent="valid edit",
            edits=[_edit("initial", "updated")],
            expected_target_version=0,
        )
        assert res_acc.status == "accepted"
        acc_log_id = res_acc.pdcp_log_id

        # Attempt to reference an accepted log must be rejected
        res_bad_parent = submit_edits(
            session,
            target_file_id=target_id,
            intent="retry pointing to accepted log",
            edits=[_edit("updated", "new")],
            expected_target_version=1,
            parent_pdcp_log_id=acc_log_id,
        )
        assert res_bad_parent.status == "rejected"
        assert res_bad_parent.failure_reason is FailureReason.CONTEXT_INVALID
        assert "parent_pdcp_log_id must reference a rejected attempt." in res_bad_parent.failure_detail

        # Create an actual rejected attempt (e.g. non-matching target content)
        res_rej = submit_edits(
            session,
            target_file_id=target_id,
            intent="edit that fails to match",
            edits=[_edit("nonexistent", "whatever")],
            expected_target_version=1,
        )
        assert res_rej.status == "rejected"
        rej_log_id = res_rej.pdcp_log_id

        # Referencing the rejected attempt succeeds and records lineage
        res_retry = submit_edits(
            session,
            target_file_id=target_id,
            intent="proper retry pointing to rejected log",
            edits=[_edit("updated", "final")],
            expected_target_version=1,
            parent_pdcp_log_id=rej_log_id,
            attempt=2,
        )
        assert res_retry.status == "accepted"
        log_retry = session.get(AppendOnlyPdcpLogs, res_retry.pdcp_log_id)
        assert log_retry is not None
        assert log_retry.parent_pdcp_log_id == rej_log_id
        assert log_retry.regeneration_attempt == 2


def test_svc_002_attempt_argument_validation() -> None:
    target_id = create_target("some text")
    with SessionLocal() as session:
        for bad_attempt in [0, -1, True, "1", 2**31]:
            res = submit_edits(
                session,
                target_file_id=target_id,
                intent="testing invalid attempt",
                edits=[_edit("some", "other")],
                expected_target_version=0,
                attempt=bad_attempt,
            )
            assert res.status == "rejected"
            assert res.failure_reason is FailureReason.CONTEXT_INVALID
            assert "attempt must be an integer between 1 and 2147483647." in res.failure_detail

        # Valid attempts persist properly
        res_ok = submit_edits(
            session,
            target_file_id=target_id,
            intent="valid attempt",
            edits=[_edit("some", "other")],
            expected_target_version=0,
            attempt=1,
        )
        assert res_ok.status == "accepted"
        log = session.get(AppendOnlyPdcpLogs, res_ok.pdcp_log_id)
        assert log is not None
        assert log.regeneration_attempt == 1

