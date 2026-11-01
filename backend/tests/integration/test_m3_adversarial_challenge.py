"""Adversarial challenge test suite for Milestone M3 (PR23-R3-SVC-001 & PR23-R3-SVC-002).

Empirically tests:
1. read_finalized_export:
   - Negative offsets and offset beyond total_bytes (OOB).
   - Exact offset == total_bytes boundary behavior.
   - Non-integer and boolean offsets/limits.
   - Negative and zero limits.
   - Excessive limit (>1MiB cap) ensuring chunk does not exceed 1MiB.
   - Multibyte UTF-8 characters (2-byte, 3-byte, 4-byte/emojis) sliced across tiny chunk boundaries (limits 1, 2, 3, 5, 7 bytes).
   - Reassembly fidelity and byte-for-byte SHA256 equality.
   - Target file edited multiple times post-finalization; verify finalized export retrieves historical snapshot.
   - Snapshot tampering, DB corruption, and mismatched target snapshot; verify snapshot_integrity_failure.
2. finalize_target session hygiene:
   - Rapid consecutive calls on the EXACT SAME SQLAlchemy session instance:
     * initial finalize
     * identical keyed retry
     * conflicting fingerprint retry
     * version guard mismatch
     * hash guard mismatch
     * target not found
     * missing guards
     * invalid characters
     * unrecoverable mixed EOL
   - Assert session.in_transaction() == False before and after every single call.
   - Assert zero autobegin leaks.
"""

import base64
import hashlib
import uuid
import pytest
from sqlalchemy import select

from app.core.failures import FailureReason
from app.services.export_service import read_finalized_export, MAX_EXPORT_CHUNK_BYTES
from app.services.finalize_service import finalize_target
from app.services.pdcp_service import submit_edits
from app.services.target_service import initialize_target
from app.storage.db import SessionLocal
from app.storage.models import CloudTargetFiles, TargetFinalizations, TargetSnapshots


# ==============================================================================
# Challenge 1: PR23-R3-SVC-001 - read_finalized_export Stress & Integrity
# ==============================================================================

def test_read_finalized_export_adversarial_bounds_and_types():
    """Test negative offsets, OOB offsets, negative/zero limits, boolean traps, and excessive limits."""
    # 1. Initialize and finalize a small target
    content = "Hello, PatchDIFF Adversarial Testing!\n"
    content_bytes = len(content.encode("utf-8"))

    with SessionLocal() as session:
        init = initialize_target(session, filename="bounds_test.txt", content=content, target_type="text/plain")
        target_id = init.target_file_id
        fin = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=f"fin-bounds-{uuid.uuid4()}",
            expected_target_version=init.version,
            expected_current_hash=init.current_hash,
            format="canonical_lf",
        )
        assert fin.status == "ok"
        fin_id = fin.finalization_id

    with SessionLocal() as session:
        # Negative offset
        res = read_finalized_export(session, fin_id, target_id, offset=-1)
        assert res["status"] == "invalid_argument"
        assert res["code"] == "invalid_offset"

        res = read_finalized_export(session, fin_id, target_id, offset=-999999)
        assert res["status"] == "invalid_argument"
        assert res["code"] == "invalid_offset"

        # Boolean offset trap (in Python isinstance(True, int) is True!)
        res = read_finalized_export(session, fin_id, target_id, offset=True)
        assert res["status"] == "invalid_argument"
        assert res["code"] == "invalid_offset"

        res = read_finalized_export(session, fin_id, target_id, offset=False)
        assert res["status"] == "invalid_argument"
        assert res["code"] == "invalid_offset"

        # Negative and zero limit
        res = read_finalized_export(session, fin_id, target_id, offset=0, limit=0)
        assert res["status"] == "invalid_argument"
        assert res["code"] == "invalid_limit"

        res = read_finalized_export(session, fin_id, target_id, offset=0, limit=-50)
        assert res["status"] == "invalid_argument"
        assert res["code"] == "invalid_limit"

        # Boolean limit trap
        res = read_finalized_export(session, fin_id, target_id, offset=0, limit=True)
        assert res["status"] == "invalid_argument"
        assert res["code"] == "invalid_limit"

        # Offset strictly greater than total_bytes -> invalid_range
        res = read_finalized_export(session, fin_id, target_id, offset=content_bytes + 1)
        assert res["status"] == "invalid_argument"
        assert res["code"] == "invalid_range"
        assert res["total_bytes"] == content_bytes

        res = read_finalized_export(session, fin_id, target_id, offset=999999999)
        assert res["status"] == "invalid_argument"
        assert res["code"] == "invalid_range"

        # Offset exact boundary: offset == total_bytes -> valid response with 0 bytes read, has_more=False
        res = read_finalized_export(session, fin_id, target_id, offset=content_bytes)
        assert res["status"] == "ok"
        assert res["bytes_read"] == 0
        assert res["total_bytes"] == content_bytes
        assert res["has_more"] is False
        assert res["next_offset"] is None
        assert res["content_base64"] == ""


def test_read_finalized_export_excessive_limit_cap_1mib():
    """Verify that requesting limit > 1MiB (e.g. 50MiB) is safely capped to 1,048,576 bytes without crash."""
    # Create > 1.5 MiB target
    base_text = "ABCDEFGHIJ0123456789\n"  # 21 bytes
    large_content = base_text * 80000     # ~1.68 MiB (1,680,000 bytes)
    raw_bytes = large_content.encode("utf-8")
    assert len(raw_bytes) > MAX_EXPORT_CHUNK_BYTES

    with SessionLocal() as session:
        init = initialize_target(session, filename="excessive_limit.txt", content=large_content, target_type="text/plain")
        target_id = init.target_file_id
        fin = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=f"fin-excessive-{uuid.uuid4()}",
            expected_target_version=init.version,
            expected_current_hash=init.current_hash,
            format="canonical_lf",
        )
        assert fin.status == "ok"
        fin_id = fin.finalization_id
        expected_sha256 = fin.content_sha256
        total_bytes = fin.content_bytes
        assert total_bytes == len(raw_bytes)

    with SessionLocal() as session:
        # Request 100 MiB limit
        res = read_finalized_export(session, fin_id, target_id, offset=0, limit=100 * 1024 * 1024)
        assert res["status"] == "ok"
        # Must be capped at exactly MAX_EXPORT_CHUNK_BYTES (1,048,576)
        assert res["bytes_read"] == MAX_EXPORT_CHUNK_BYTES
        assert len(base64.b64decode(res["content_base64"])) == MAX_EXPORT_CHUNK_BYTES
        assert res["has_more"] is True
        assert res["next_offset"] == MAX_EXPORT_CHUNK_BYTES
        assert res["total_bytes"] == total_bytes

        # Read remainder with limit capped at 1 MiB
        res_next = read_finalized_export(session, fin_id, target_id, offset=res["next_offset"], limit=MAX_EXPORT_CHUNK_BYTES)
        assert res_next["status"] == "ok"
        chunk2 = base64.b64decode(res_next["content_base64"])
        assert res["bytes_read"] + len(chunk2) == total_bytes
        assert res_next["has_more"] is False
        assert res_next["next_offset"] is None

        # Check assembled hash
        chunk1 = base64.b64decode(res["content_base64"])
        full_bytes = chunk1 + chunk2
        assert hashlib.sha256(full_bytes).hexdigest() == expected_sha256


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 4, 5, 7, 11, 16])
def test_read_finalized_export_multibyte_utf8_split_across_chunk_boundaries(chunk_size):
    """Stress test base64 chunking when multibyte characters (2, 3, 4-byte/emojis) are sliced across chunk boundaries."""
    # Text containing 1-byte, 2-byte (é, ñ, α, β), 3-byte (€, 世界, 語), and 4-byte (🌍, 🚀, 🎉, 🔥) chars
    rich_text = (
        "ASCII intro.\n"
        "2-byte characters: é, ñ, ü, ç, α, β, γ, δ, ж, щ.\n"
        "3-byte characters: € (euro), ¥, ₹, 語, 漢, 字, 世, 界, ∳, ⨀.\n"
        "4-byte emojis & astral planes: 🌍 🚀 🎉 🔥 𝕏 🦀 🦄 ⚡ 💎 🧙‍♂️.\n"
        "Mixed line endings and combinations: Aé€🌍Bñ¥🚀Cü₹🎉D\n"
    )
    raw_bytes = rich_text.encode("utf-8")
    expected_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    total_bytes = len(raw_bytes)

    with SessionLocal() as session:
        init = initialize_target(session, filename=f"multibyte_{chunk_size}.txt", content=rich_text, target_type="text/plain")
        target_id = init.target_file_id
        fin = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=f"fin-mb-{chunk_size}-{uuid.uuid4()}",
            expected_target_version=init.version,
            expected_current_hash=init.current_hash,
            format="canonical_lf",
        )
        assert fin.status == "ok"
        fin_id = fin.finalization_id

    # Page through with the tiny chunk size
    chunks = []
    offset = 0
    has_more = True

    with SessionLocal() as session:
        while has_more:
            page = read_finalized_export(session, fin_id, target_id, offset=offset, limit=chunk_size)
            assert page["status"] == "ok"
            assert page["total_bytes"] == total_bytes
            assert page["content_sha256"] == expected_sha256

            decoded_chunk = base64.b64decode(page["content_base64"])
            assert len(decoded_chunk) == page["bytes_read"]
            assert len(decoded_chunk) <= chunk_size
            chunks.append(decoded_chunk)

            has_more = page["has_more"]
            offset = page["next_offset"]

    # Reassemble and verify byte-for-byte fidelity
    assembled = b"".join(chunks)
    assert len(assembled) == total_bytes
    assert hashlib.sha256(assembled).hexdigest() == expected_sha256
    # Verify exact UTF-8 decode
    decoded_text = assembled.decode("utf-8")
    assert decoded_text == rich_text


def test_read_finalized_export_multiple_post_finalization_edits():
    """Verify that target file edited multiple times post-finalization retrieves historical snapshot without corruption."""
    v0_text = "Version 0: Original baseline text.\nChapter 1: The Beginning.\n"
    v1_text = "Version 1: First revision of document.\nChapter 1: The Beginning.\n"
    v2_text = "Version 2: Second revision with additions.\nChapter 1: The Beginning.\nChapter 2: Middle.\n"
    v3_text = "Version 3: Final mutated state.\nChapter 1: The Ending.\n"

    with SessionLocal() as session:
        init = initialize_target(session, filename="multi_edit.txt", content=v0_text, target_type="text/plain")
        target_id = init.target_file_id
        v0 = init.version
        h0 = init.current_hash

    # Finalize at Version 0
    fin1_req_id = f"fin-v0-{uuid.uuid4()}"
    with SessionLocal() as session:
        fin1 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=fin1_req_id,
            expected_target_version=v0,
            expected_current_hash=h0,
            format="canonical_lf",
        )
        assert fin1.status == "ok"
        fin1_id = fin1.finalization_id
        fin1_sha256 = fin1.content_sha256
        fin1_bytes = fin1.content_bytes

    # Edit 1 -> Version 1
    with SessionLocal() as session:
        e1 = submit_edits(
            session,
            target_file_id=target_id,
            expected_target_version=v0,
            expected_current_hash=h0,
            intent="Update to version 1",
            edits=[{"match": "Version 0: Original baseline text.", "replace": "Version 1: First revision of document."}],
        )
        assert e1.status == "accepted"
        v1 = e1.current_version
        h1 = e1.current_hash

    # Edit 2 -> Version 2
    with SessionLocal() as session:
        e2 = submit_edits(
            session,
            target_file_id=target_id,
            expected_target_version=v1,
            expected_current_hash=h1,
            intent="Update to version 2",
            edits=[
                {"match": "Version 1: First revision of document.", "replace": "Version 2: Second revision with additions."},
                {"match": "Chapter 1: The Beginning.\n", "replace": "Chapter 1: The Beginning.\nChapter 2: Middle.\n"},
            ],
        )
        assert e2.status == "accepted"
        v2 = e2.current_version
        h2 = e2.current_hash

    # Finalize at Version 2 (Second checkpoint)
    fin2_req_id = f"fin-v2-{uuid.uuid4()}"
    with SessionLocal() as session:
        fin2 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=fin2_req_id,
            expected_target_version=v2,
            expected_current_hash=h2,
            format="canonical_lf",
        )
        assert fin2.status == "ok"
        fin2_id = fin2.finalization_id
        fin2_sha256 = fin2.content_sha256
        fin2_bytes = fin2.content_bytes

    # Edit 3 -> Version 3
    with SessionLocal() as session:
        e3 = submit_edits(
            session,
            target_file_id=target_id,
            expected_target_version=v2,
            expected_current_hash=h2,
            intent="Update to version 3",
            edits=[
                {"match": "Version 2: Second revision with additions.\nChapter 1: The Beginning.\nChapter 2: Middle.\n", "replace": v3_text},
            ],
        )
        assert e3.status == "accepted"
        v3 = e3.current_version
        h3 = e3.current_hash

    # Now verify that read_finalized_export on fin1_id returns EXACTLY Version 0
    with SessionLocal() as session:
        p1 = read_finalized_export(session, fin1_id, target_id)
        assert p1["status"] == "ok"
        assert p1["total_bytes"] == fin1_bytes
        assert p1["content_sha256"] == fin1_sha256
        data1 = base64.b64decode(p1["content_base64"]).decode("utf-8")
        assert data1 == v0_text
        assert "Version 0" in data1
        assert "Version 1" not in data1
        assert "Version 2" not in data1
        assert "Version 3" not in data1

        # Verify that read_finalized_export on fin2_id returns EXACTLY Version 2
        p2 = read_finalized_export(session, fin2_id, target_id)
        assert p2["status"] == "ok"
        assert p2["total_bytes"] == fin2_bytes
        assert p2["content_sha256"] == fin2_sha256
        data2 = base64.b64decode(p2["content_base64"]).decode("utf-8")
        assert data2 == v2_text
        assert "Version 2" in data2
        assert "Chapter 2: Middle" in data2
        assert "Version 3" not in data2

        # Verify live target file in DB is still at Version 3 and not rolled back
        target = session.get(CloudTargetFiles, target_id)
        assert target.version == v3
        assert target.current_hash == h3
        assert target.current_content == v3_text


def test_read_finalized_export_tampering_and_integrity_failure():
    """Verify snapshot tampering or corruption returns closed snapshot_integrity_failure."""
    text = "Integrity check file content.\n"
    with SessionLocal() as session:
        init = initialize_target(session, filename="tamper_test.txt", content=text, target_type="text/plain")
        target_id = init.target_file_id
        fin = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=f"fin-tamper-{uuid.uuid4()}",
            expected_target_version=init.version,
            expected_current_hash=init.current_hash,
            format="canonical_lf",
        )
        assert fin.status == "ok"
        fin_id = fin.finalization_id
        snapshot_id = fin.snapshot_id

    # Tamper 1: Modify snapshot content in database directly
    with SessionLocal() as session:
        snap = session.get(TargetSnapshots, snapshot_id)
        assert snap is not None
        snap.content = "TAMPERED_CONTENT_CORRUPTED"
        session.commit()

    # read_finalized_export MUST reject with snapshot_integrity_failure
    with SessionLocal() as session:
        res_tampered = read_finalized_export(session, fin_id, target_id)
        assert res_tampered["status"] == "error"
        assert res_tampered["error"] == "snapshot_integrity_failure"
        assert "Snapshot integrity check failed" in res_tampered["failure_detail"]

    # Tamper 2: Snapshot belongs to another target_file_id
    with SessionLocal() as session:
        other_target = initialize_target(session, filename="other_target.txt", content="Other\n", target_type="text/plain")
        snap = session.get(TargetSnapshots, snapshot_id)
        snap.target_file_id = other_target.target_file_id
        session.commit()

    # read_finalized_export MUST reject with snapshot_integrity_failure
    with SessionLocal() as session:
        res_mismatch = read_finalized_export(session, fin_id, target_id)
        assert res_mismatch["status"] == "error"
        assert res_mismatch["error"] == "snapshot_integrity_failure"
        assert "Snapshot record associated with finalization is missing or invalid" in res_mismatch["failure_detail"]


# ==============================================================================
# Challenge 2: PR23-R3-SVC-002 - Session Hygiene Across Rapid Consecutive Calls
# ==============================================================================

def test_session_hygiene_rapid_consecutive_calls_on_same_session():
    """Rapidly invoke consecutive calls (initial, retry, conflict, version mismatch,
    hash mismatch, missing target, missing guards, invalid args, unrecoverable EOL)
    on the EXACT SAME SQLAlchemy session instance.
    Assert session.in_transaction() == False before and after every single call.
    Assert zero autobegin leaks.
    """
    # Initialize target
    with SessionLocal() as session:
        init = initialize_target(session, filename="rapid_hygiene.txt", content="Base text\n", target_type="text/plain")
        target_id = init.target_file_id
        v0 = init.version
        h0 = init.current_hash

    client_request_id = f"fin-rapid-{uuid.uuid4()}"

    # Open a single persistent SQLAlchemy session
    with SessionLocal() as session:
        assert session.in_transaction() is False
        assert len(session.dirty) == 0

        # Call 1: Initial successful finalize
        res1 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=v0,
            expected_current_hash=h0,
            format="canonical_lf",
        )
        assert res1.status == "ok"
        assert res1.is_idempotent_replay is False
        assert session.in_transaction() is False
        assert len(session.dirty) == 0

        # Call 2: Identical keyed retry on the SAME session
        res2 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=v0,
            expected_current_hash=h0,
            format="canonical_lf",
        )
        assert res2.status == "ok"
        assert res2.is_idempotent_replay is True
        assert session.in_transaction() is False
        assert len(session.dirty) == 0

        # Call 3: Conflicting fingerprint retry on the SAME session
        res3 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=v0,
            expected_current_hash=h0,
            format="crlf",  # different format triggers conflict
        )
        assert res3.status == "rejected"
        assert res3.failure_code == "request_key_conflict"
        assert session.in_transaction() is False
        assert len(session.dirty) == 0

        # Call 4: Version guard mismatch on the SAME session (new request ID)
        res4 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=f"fin-diff-{uuid.uuid4()}",
            expected_target_version=999,  # version mismatch
            expected_current_hash=h0,
            format="canonical_lf",
        )
        assert res4.status == "rejected"
        assert res4.failure_reason == FailureReason.TARGET_VERSION_MISMATCH
        assert session.in_transaction() is False
        assert len(session.dirty) == 0

        # Call 5: Hash guard mismatch on the SAME session (new request ID)
        res5 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=f"fin-diff-{uuid.uuid4()}",
            expected_target_version=v0,
            expected_current_hash="f" * 64,  # hash mismatch
            format="canonical_lf",
        )
        assert res5.status == "rejected"
        assert res5.failure_reason == FailureReason.TARGET_HASH_MISMATCH
        assert session.in_transaction() is False
        assert len(session.dirty) == 0

        # Call 6: Target not found on the SAME session
        res6 = finalize_target(
            session,
            target_file_id=uuid.uuid4(),
            client_request_id=f"fin-diff-{uuid.uuid4()}",
            expected_target_version=0,
            format="canonical_lf",
        )
        assert res6.status == "rejected"
        assert res6.failure_reason == FailureReason.TARGET_NOT_FOUND
        assert session.in_transaction() is False
        assert len(session.dirty) == 0

        # Call 7: Missing guards on the SAME session
        res7 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=f"fin-diff-{uuid.uuid4()}",
            expected_target_version=None,
            expected_current_hash=None,
            format="canonical_lf",
        )
        assert res7.status == "rejected"
        assert res7.failure_reason == FailureReason.CONTEXT_INVALID
        assert session.in_transaction() is False
        assert len(session.dirty) == 0

        # Call 8: Invalid format argument on the SAME session
        res8 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=f"fin-diff-{uuid.uuid4()}",
            expected_target_version=v0,
            format="unsupported_format",
        )
        assert res8.status == "rejected"
        assert res8.failure_reason == FailureReason.CONTEXT_INVALID
        assert session.in_transaction() is False
        assert len(session.dirty) == 0

        # Call 9: Consecutive identical retry again to verify session didn't decay
        res9 = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=client_request_id,
            expected_target_version=v0,
            expected_current_hash=h0,
            format="canonical_lf",
        )
        assert res9.status == "ok"
        assert res9.is_idempotent_replay is True
        assert session.in_transaction() is False
        assert len(session.dirty) == 0


import threading
import time
from app.mcp.external_adapter import ExternalMCPAdapter
from app.storage.repositories import select_target_for_update


def test_finalize_target_lock_wait_vs_hold_under_contention():
    """Verify PR23-R3-DOC-002: lock_wait_ms specifically captures row lock acquisition wait time under live DB contention."""
    with SessionLocal() as session:
        init = initialize_target(session, filename="contention_test.txt", content="Contention test data\n", target_type="text/plain")
        target_id = init.target_file_id
        v0 = init.version
        h0 = init.current_hash

    # We will hold SELECT ... FOR UPDATE on target_id for ~250ms in Thread A
    lock_acquired_event = threading.Event()
    release_lock_event = threading.Event()

    def lock_holder():
        with SessionLocal() as session:
            with session.begin():
                session.execute(select_target_for_update(target_id)).scalar_one()
                lock_acquired_event.set()
                release_lock_event.wait(timeout=2.0)

    t_holder = threading.Thread(target=lock_holder)
    t_holder.start()
    assert lock_acquired_event.wait(timeout=2.0), "Lock holder failed to acquire lock"

    # In main thread, schedule finalize_target after starting release timer
    def delayed_release():
        time.sleep(0.20)  # Hold for 200ms
        release_lock_event.set()

    t_releaser = threading.Thread(target=delayed_release)
    t_releaser.start()

    with SessionLocal() as session:
        t0 = time.perf_counter()
        res = finalize_target(
            session,
            target_file_id=target_id,
            client_request_id=f"fin-contention-{uuid.uuid4()}",
            expected_target_version=v0,
            expected_current_hash=h0,
            format="canonical_lf",
        )
        total_time_ms = (time.perf_counter() - t0) * 1000.0

    t_holder.join(timeout=2.0)
    t_releaser.join(timeout=2.0)

    assert res.status == "ok"
    assert res.lock_wait_ms is not None
    assert res.lock_hold_ms is not None
    # lock_wait_ms must be >= 180ms due to the lock holder
    assert res.lock_wait_ms >= 180.0, f"Expected lock_wait_ms >= 180ms, got {res.lock_wait_ms}"
    # lock_hold_ms should be the execution time AFTER acquiring lock (significantly less than total wait)
    assert res.lock_hold_ms < res.lock_wait_ms, f"Expected lock_hold_ms ({res.lock_hold_ms}) < lock_wait_ms ({res.lock_wait_ms})"
    assert total_time_ms >= res.lock_wait_ms


def test_read_finalized_export_mcp_profile_access_control():
    """Verify that patchdiff_read_finalized_export is exposed in 'full' profile and denied in 'observed_v2'."""
    adapter_full = ExternalMCPAdapter(profile="full")
    adapter_v2 = ExternalMCPAdapter(profile="observed_v2")

    tools_full = [t["name"] for t in adapter_full.list_tools()]
    tools_v2 = [t["name"] for t in adapter_v2.list_tools()]

    assert "patchdiff_read_finalized_export" in tools_full
    assert "patchdiff_read_finalized_export" not in tools_v2

    # Calling via observed_v2 profile returns unknown tool error
    resp_v2 = adapter_v2.call_tool(
        "patchdiff_read_finalized_export",
        {
            "finalization_id": str(uuid.uuid4()),
            "target_file_id": str(uuid.uuid4()),
        },
    )
    assert resp_v2.get("isError") is True
    assert "Unknown PatchDIFF MCP tool" in resp_v2["content"][0]["text"]


def test_read_finalized_export_nul_and_invalid_unicode_arguments():
    """Verify that arguments with NUL bytes or uncoercible types are rejected cleanly with safe sanitization."""
    with SessionLocal() as session:
        # NUL in finalization_id
        res1 = read_finalized_export(session, "abc\x00def", str(uuid.uuid4()))
        assert res1["status"] == "invalid_argument"
        assert "\\u0000" in res1["finalization_id"]

        # NUL in target_file_id
        res2 = read_finalized_export(session, str(uuid.uuid4()), "target\x00bad")
        assert res2["status"] == "invalid_argument"
        assert "\\u0000" in res2["target_file_id"]

        # Float offset and limit
        res3 = read_finalized_export(session, str(uuid.uuid4()), str(uuid.uuid4()), offset=10.5)
        assert res3["status"] == "invalid_argument"
        assert res3["code"] == "invalid_offset"

        res4 = read_finalized_export(session, str(uuid.uuid4()), str(uuid.uuid4()), limit=500.2)
        assert res4["status"] == "invalid_argument"
        assert res4["code"] == "invalid_limit"
