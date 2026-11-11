"""Live workspace ownership, guarded recovery and publication races."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import hashlib
import json
from queue import Queue
from threading import Barrier, Event
import time
import uuid

import pytest
from alembic import command
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import workspace_root_context
from app.mcp import tools
from app.services import target_service
from app.services.coordinated_transaction_service import submit_coordinated_transactions
from app.services.pdcp_service import submit_edits
from app.services.save_service import save_target
from app.services.target_service import WorkspaceRecovery, initialize_target, initialize_target_from_workspace
from app.services.workspace_sync_service import WorkspaceSyncError
from app.storage.db import SessionLocal
from app.storage.models import (
    AppendOnlyPdcpLogs, CloudTargetFiles, CurrentPdcpFiles, EditingCycles, Projects, TargetSnapshots, WorkspaceBindingMember,
)
from backend.tests.integration.test_batch_stdio_profiles import peer
from backend.tests.integration.test_migrations_reachable import isolated_migrations, snapshot


def open_path(root, filename="target.txt", **arguments):
    with workspace_root_context(root):
        return tools.patchdiff_initialize_target(filename=filename, from_workspace=True, **arguments)


def recovery(target, disk, *, action="reimport", key="recover-1", **overrides):
    return {
        "action": action,
        "target_file_id": str(target["target_file_id"]),
        "expected_target_version": target["version"],
        "expected_current_hash": target["current_hash"],
        "expected_disk_sha256": hashlib.sha256(disk).hexdigest(),
        "client_request_id": key,
        **overrides,
    }


def submit(target, match, replacement, *, key=None):
    return tools.patchdiff_submit_edits(
        target_file_id=str(target["target_file_id"]), expected_target_version=target["version"],
        expected_current_hash=target["current_hash"], intent=f"Change {match} to {replacement}",
        edits=[{"match": match, "replace": replacement}], client_request_id=key,
    )


def rpc_call(rpc, name, **arguments):
    return json.loads(rpc("tools/call", {"name": name, "arguments": arguments})["content"][0]["text"])


def test_four_stdio_processes_reuse_one_history_and_publish_both_edits(tmp_path):
    file = tmp_path / "target.txt"
    file.write_bytes(b"a b\r\n")
    arguments = {"filename": file.name, "from_workspace": True}
    with ExitStack() as stack, ThreadPoolExecutor(max_workers=4) as workers:
        clients = [stack.enter_context(peer(profile, workspace_root=tmp_path))[1]
                   for profile in ("workspace", "workspace", "observed_workspace", "observed_workspace")]
        barrier = Barrier(4, timeout=10)

        def first_open(rpc):
            barrier.wait()
            return rpc_call(rpc, "patchdiff_initialize_target", **arguments)

        replies = list(workers.map(first_open, clients))
        assert sum(reply.get("created") is True for reply in replies) == 1
        opened = next(reply for reply in replies if reply.get("created") is True)
        for client, reply in zip(clients, replies):
            if reply["status"] != "ok":
                assert reply["code"] == "workspace_busy"
                reply = rpc_call(client, "patchdiff_initialize_target", **arguments)
            assert reply["target_file_id"] == opened["target_file_id"]

        target_id = opened["target_file_id"]
        first = rpc_call(clients[0], "patchdiff_submit_edits", target_file_id=target_id,
                         intent="Apply X", expected_target_version=0, edits=[{"match": "a", "replace": "X"}])
        assert first["status"] == "accepted"
        reopened = rpc_call(clients[0], "patchdiff_initialize_target", **arguments)
        assert reopened["target_file_id"] == target_id and reopened["version"] == 1 and reopened["created"] is False
        assert file.read_bytes() == b"a b\r\n"
        read = rpc_call(clients[2], "patchdiff_read_target", target_file_id=target_id)
        assert read["text"] == "X b\n"
        stale = rpc_call(clients[1], "patchdiff_submit_edits", target_file_id=target_id,
                         intent="Apply stale Y", expected_target_version=opened["version"],
                         edits=[{"match": "b", "replace": "stale"}])
        assert stale["failure_reason"] == "target_version_mismatch"
        second = rpc_call(clients[0], "patchdiff_submit_edits", target_file_id=target_id,
                          intent="Apply Y", expected_target_version=reopened["version"],
                          edits=[{"match": "b", "replace": "Y"}])
        assert second["status"] == "accepted"
        saved = rpc_call(clients[1], "patchdiff_save", target_file_id=target_id, expected_target_version=2,
                         sync_workspace=True)
        assert saved["status"] == "saved"
        assert file.read_bytes() == b"X Y\r\n"

    with peer("workspace", workspace_root=tmp_path) as (_, rpc):
        after_restart = rpc_call(rpc, "patchdiff_initialize_target", **arguments)
        assert after_restart["target_file_id"] == target_id and after_restart["version"] == 2
        assert after_restart["active_editing_cycle_id"] == saved["new_editing_cycle_id"]
    with SessionLocal() as session:
        tid = uuid.UUID(target_id)
        target = session.get(CloudTargetFiles, tid)
        assert session.scalar(select(func.count()).select_from(CloudTargetFiles).where(
            CloudTargetFiles.project_id == target.project_id)) == 1
        assert session.scalar(select(func.count()).select_from(EditingCycles).where(EditingCycles.target_file_id == tid)) == 2
        assert session.scalar(select(func.count()).select_from(TargetSnapshots).where(TargetSnapshots.target_file_id == tid)) == 2


def test_root_path_aliases_and_explicit_metadata_conflicts(tmp_path):
    nested = tmp_path / "pkg"
    nested.mkdir()
    (nested / "target.txt").write_bytes(b"initial")
    independent = tmp_path / "elsewhere"
    independent.mkdir()
    (independent / "target.txt").write_bytes(b"initial")
    with SessionLocal.begin() as session:
        project = Projects(name="test project")
        session.add(project)
        session.flush()
        project_id = str(project.project_id)
    opened = open_path(tmp_path, r"pkg\target.txt", project_id=project_id, content_type="text/example")
    assert opened["created"] is True and opened["filename"] == "pkg/target.txt"
    assert open_path(tmp_path, "pkg/target.txt", content_type=None)["target_type"] == "text/example"
    assert open_path(tmp_path, "pkg/target.txt", project_id=project_id)["target_file_id"] == opened["target_file_id"]
    assert open_path(tmp_path, "pkg/target.txt", project_id=str(uuid.uuid4()))["code"] == "workspace_project_conflict"
    assert open_path(tmp_path, "pkg/target.txt", content_type="text/plain")["code"] == "workspace_content_type_conflict"
    alias = open_path(nested)
    assert alias["code"] == "workspace_binding_mismatch" and alias["active_target_file_id"] == opened["target_file_id"]
    inline = tools.patchdiff_initialize_target(filename="target.txt", content="initial")
    with workspace_root_context(nested):
        publication = tools.patchdiff_save(target_file_id=inline["target_file_id"], sync_workspace=True)
    assert publication["code"] == "workspace_binding_mismatch"
    assert publication["active_target_file_id"] == opened["target_file_id"]
    assert open_path(independent)["target_file_id"] != opened["target_file_id"]


def test_guarded_reimport_drift_outcomes_and_fences(tmp_path):
    file = tmp_path / "target.txt"
    file.write_bytes(b"initial\r\n")
    target = open_path(tmp_path)
    accepted = submit(target, "initial", "working", key="original-edit")
    assert accepted["status"] == "accepted"
    version_one = open_path(tmp_path)
    disk = b"external\r\n"
    file.write_bytes(disk)
    drift = open_path(tmp_path)
    assert drift["code"] == "external_disk_drift" and drift["target_file_id"] == target["target_file_id"]
    assert drift["version"] == 1 and drift["current_hash"] == version_one["current_hash"]
    assert drift["disk_sha256"] == hashlib.sha256(disk).hexdigest()

    stale = recovery(target, disk, key="stale")
    rejected = open_path(tmp_path, workspace_recovery=stale)
    assert rejected["code"] == "target_version_mismatch" and rejected["deduplicated"] is False
    wrong_eol = recovery(version_one, b"external\n", key="wrong-eol")
    assert open_path(tmp_path, workspace_recovery=wrong_eol)["code"] == "workspace_disk_hash_mismatch"

    request = recovery(version_one, disk)
    successor = open_path(tmp_path, workspace_recovery=request)
    assert successor["created"] is True and successor["target_file_id"] != target["target_file_id"]
    assert successor["version"] == 0 and successor["deduplicated"] is False
    assert open_path(tmp_path)["target_file_id"] == successor["target_file_id"]
    assert file.read_bytes() == disk

    rejected_again = open_path(tmp_path, workspace_recovery=stale)
    assert rejected_again["code"] == "target_version_mismatch" and rejected_again["deduplicated"] is True
    assert rejected_again["target_file_id"] == target["target_file_id"]
    assert rejected_again["active_target_file_id"] == successor["target_file_id"]
    conflict = open_path(tmp_path, workspace_recovery={**request, "expected_target_version": 2})
    assert conflict["code"] == "request_key_conflict"

    old_id = target["target_file_id"]
    with SessionLocal() as session:
        tid = uuid.UUID(old_id)
        log_count = select(func.count()).select_from(AppendOnlyPdcpLogs).where(AppendOnlyPdcpLogs.target_file_id == tid)
        current_attempt = select(CurrentPdcpFiles.pdcp_content_hash).where(CurrentPdcpFiles.target_file_id == tid)
        state = session.scalar(log_count), session.scalar(current_attempt)
        oversized = tools.patchdiff_submit_replacement(
            target_file_id=old_id, intent="Oversized obsolete replacement", expected_target_version=1,
            replacement="é" * 524_289,
        )
        assert oversized["status"] == "invalid_argument" and oversized["code"] == "replacement_too_large"
        assert (session.scalar(log_count), session.scalar(current_attempt)) == state
    prior = submit(target, "initial", "working", key="original-edit")
    assert prior["deduplicated"] is True and prior["pdcp_log_id"] == accepted["pdcp_log_id"]
    assert submit(version_one, "working", "obsolete")["code"] == "workspace_target_superseded"
    assert tools.patchdiff_submit_operations(target_file_id=old_id, intent="obsolete",
        expected_target_version=1, operations=[{"op": "match", "match": "working", "replace": "obsolete"}]
    )["code"] == "workspace_target_superseded"
    assert tools.patchdiff_submit_replacement(target_file_id=old_id, intent="obsolete",
        expected_target_version=1, replacement="obsolete")["code"] == "workspace_target_superseded"
    assert tools.patchdiff_submit_observed_operations(target_file_id=old_id, intent="obsolete",
        expected_target_version=1, observation_id=str(uuid.uuid4()),
        operations=[{"op": "match", "match": "working", "replace": "obsolete"}]
    )["code"] == "workspace_target_superseded"
    for sync in (False, True):
        with workspace_root_context(tmp_path):
            save = tools.patchdiff_save(target_file_id=old_id, sync_workspace=sync)
        assert save["code"] == "workspace_target_superseded" and save["snapshot_id"] is None
    replay = tools.patchdiff_replay(target_file_id=old_id)
    assert replay["status"] == "success" and replay["materialized_state_matches"]

    newer_disk = b"later\n"
    file.write_bytes(newer_disk)
    later = open_path(tmp_path, workspace_recovery=recovery(successor, newer_disk, key="later"))
    recovered = open_path(tmp_path, workspace_recovery=request)
    assert recovered["deduplicated"] is True
    assert recovered["target_file_id"] == successor["target_file_id"]
    assert recovered["active_target_file_id"] == later["target_file_id"]
    assert recovered["active_editing_cycle_id"] == successor["active_editing_cycle_id"]
    assert recovered["disk_sha256"] == successor["disk_sha256"]


@pytest.mark.parametrize("fail_checkpoint", [False, True])
def test_inline_save_holds_destination_through_checkpoint_and_handles_partial(tmp_path, fail_checkpoint):
    file = tmp_path / "target.txt"
    file.write_bytes(b"initial")
    inline = tools.patchdiff_initialize_target(filename=file.name, content="initial")
    other = tools.patchdiff_initialize_target(filename=file.name, content="initial")
    assert inline["target_file_id"] != other["target_file_id"]
    assert submit(inline, "initial", "published")["status"] == "accepted"
    installed = Event()
    continue_checkpoint = Event()

    def pause_checkpoint():
        installed.set()
        assert continue_checkpoint.wait(10)
        if fail_checkpoint:
            raise RuntimeError("simulated checkpoint failure")

    def save():
        with SessionLocal() as session:
            return save_target(session, target_file_id=inline["target_file_id"], sync_workspace=True,
                               workspace_root=tmp_path, _after_snapshot=pause_checkpoint)

    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(save)
        try:
            assert installed.wait(10)
            assert file.read_bytes() == b"published"
            assert open_path(tmp_path)["code"] == "workspace_busy"
        finally:
            continue_checkpoint.set()
        result = pending.result(timeout=10)
    if fail_checkpoint:
        assert result.status == "partial" and result.snapshot_id is None
        opened = open_path(tmp_path)
        assert opened["created"] is True and opened["target_file_id"] != inline["target_file_id"]
    else:
        assert result.status == "saved"
        assert open_path(tmp_path)["target_file_id"] == inline["target_file_id"]
    with workspace_root_context(tmp_path):
        competing = tools.patchdiff_save(target_file_id=other["target_file_id"], sync_workspace=True)
    assert competing["code"] == "workspace_binding_mismatch"
    owner = opened["target_file_id"] if fail_checkpoint else inline["target_file_id"]
    assert competing["active_target_file_id"] == owner


def test_reimport_fences_waiting_single_and_coordinated_submissions(tmp_path, monkeypatch):
    file = tmp_path / "target.txt"
    file.write_bytes(b"initial")
    target = open_path(tmp_path)
    companion = tools.patchdiff_initialize_target(filename="companion.txt", content="companion")
    disk = b"external"
    file.write_bytes(disk)
    locked = Event()
    finish_reimport = Event()
    real_import = target_service._import_workspace_target

    def pause_import(*args):
        locked.set()
        assert finish_reimport.wait(10)
        return real_import(*args)

    pids = Queue()

    def in_transaction(operation, **kwargs):
        with SessionLocal.begin() as session:
            pids.put(session.scalar(select(func.pg_backend_pid())))
            return operation(session, **kwargs)

    monkeypatch.setattr(target_service, "_import_workspace_target", pause_import)
    with ThreadPoolExecutor(max_workers=4) as workers:
        pending_reimport = workers.submit(open_path, tmp_path, workspace_recovery=recovery(target, disk))
        try:
            assert locked.wait(10)
            competing_request = recovery(target, disk, key="competing")
            assert open_path(tmp_path, workspace_recovery=competing_request)["code"] == "workspace_busy"
            pending_edit = workers.submit(in_transaction, submit_edits,
                target_file_id=target["target_file_id"], expected_target_version=0,
                intent="Edit stale target", edits=[{"match": "initial", "replace": "obsolete"}])
            pending_coordinated = workers.submit(in_transaction, submit_coordinated_transactions,
                intent="Edit both", targets=[
                    {"target_file_id": companion["target_file_id"], "expected_target_version": 0,
                     "edits": [{"match": "companion", "replace": "changed"}]},
                    {"target_file_id": target["target_file_id"], "expected_target_version": 0,
                     "edits": [{"match": "initial", "replace": "obsolete"}]},
                ])
            pending_save = workers.submit(in_transaction, save_target,
                target_file_id=target["target_file_id"], sync_workspace=False)
            waiting_pids = [pids.get(timeout=5) for _ in range(3)]
            statement = text("""
                SELECT count(*) FROM unnest(CAST(:pids AS integer[])) AS backend(pid)
                WHERE cardinality(pg_blocking_pids(backend.pid)) > 0
            """)
            with SessionLocal() as session:
                deadline = time.monotonic() + 5
                while session.scalar(statement, {"pids": waiting_pids}) < 3:
                    assert time.monotonic() < deadline, "Expected all three writers to wait for row locks"
                    time.sleep(0.01)
        finally:
            finish_reimport.set()
        assert pending_reimport.result(timeout=10)["created"] is True
        assert pending_edit.result(timeout=10).code == "workspace_target_superseded"
        assert pending_coordinated.result(timeout=10)["code"] == "workspace_target_superseded"
        assert pending_save.result(timeout=10).code == "workspace_target_superseded"
    competing = open_path(tmp_path, workspace_recovery=competing_request)
    assert competing["code"] == "workspace_recovery_target_conflict" and not competing["deduplicated"]
    assert tools.patchdiff_read_target(target_file_id=companion["target_file_id"])["version"] == 0
    assert file.read_bytes() == disk


def test_migration_preserves_legacy_histories_and_selects_duplicate_explicitly(tmp_path, isolated_migrations, monkeypatch):
    config, connection = isolated_migrations
    command.upgrade(config, "20261105_0006")
    connection.commit()
    directory = tmp_path / "pkg"
    directory.mkdir()
    file = directory / "target.txt"
    raw = b"legacy\r\n"
    file.write_bytes(raw)
    (tmp_path / "singleton.txt").write_bytes(raw)
    changed = b"changed legacy disk"
    (directory / "drifted.txt").write_bytes(changed)
    (directory / "reimport.txt").write_bytes(changed)
    stat = tmp_path.stat()
    identity = f"{stat.st_dev}:{stat.st_ino}"
    with Session(bind=connection) as session:
        first = initialize_target(session, filename=r"pkg\target.txt", content=raw, target_type="text/plain",
                                  workspace_tracked=True, workspace_root_identity=identity)
        second = initialize_target(session, filename="pkg/target.txt", content=raw, target_type="text/plain",
                                   workspace_tracked=True, workspace_root_identity=identity)
        duplicates = [
            initialize_target(session, filename="pkg/target.txt", content=raw, target_type="text/plain",
                              workspace_tracked=True, workspace_root_identity=identity)
            for _ in range(19)
        ]
        singleton = initialize_target(session, filename="singleton.txt", content=raw, target_type="text/plain",
                                      workspace_tracked=True, workspace_root_identity=identity)
        drifted = initialize_target(session, filename="pkg/drifted.txt", content=raw, target_type="text/plain",
                                    workspace_tracked=True, workspace_root_identity=identity)
        reimport_members = [
            initialize_target(session, filename="pkg/reimport.txt", content=raw, target_type="text/plain",
                              workspace_tracked=True, workspace_root_identity=identity)
            for _ in range(2)
        ]
        malformed = initialize_target(session, filename="pkg/target.txt", content=raw, target_type="text/plain",
                                      workspace_tracked=True, workspace_root_identity="malformed:identity")
    before = snapshot(connection)
    connection.commit()
    command.upgrade(config, "head")
    assert snapshot(connection) == before
    assert connection.scalar(select(func.count()).select_from(WorkspaceBindingMember)) == 25
    connection.commit()
    monkeypatch.setattr(tools, "SessionLocal", lambda: Session(bind=connection, expire_on_commit=False))

    assert open_path(tmp_path, "singleton.txt")["target_file_id"] == str(singleton.target_file_id)
    drift = open_path(tmp_path, "pkg/drifted.txt")
    assert drift["code"] == "external_disk_drift" and drift["target_file_id"] == str(drifted.target_file_id)
    alias = open_path(directory, "drifted.txt")
    assert alias["code"] == "workspace_binding_mismatch" and alias["active_target_file_id"] == str(drifted.target_file_id)
    ambiguous = open_path(tmp_path, "pkg/target.txt")
    assert ambiguous["code"] == "workspace_binding_ambiguous" and ambiguous["candidate_count"] == 21
    candidates = sorted(str(item.target_file_id) for item in [first, second, *duplicates])
    assert ambiguous["candidate_target_file_ids"] == candidates[:20] and ambiguous["candidates_truncated"]
    assert open_path(directory)["code"] == "workspace_binding_mismatch"
    assert str(malformed.target_file_id) not in ambiguous["candidate_target_file_ids"]
    malformed_state = {"target_file_id": malformed.target_file_id, "version": 0, "current_hash": malformed.current_hash}
    assert submit(malformed_state, "legacy", "unsafe")["code"] == "workspace_binding_metadata_invalid"
    coordinated = tools.patchdiff_commit_multi_target(intent="Invalid legacy binding", targets=[{
        "target_file_id": str(malformed.target_file_id), "expected_target_version": 0,
        "edits": [{"match": "legacy", "replace": "unsafe"}],
    }])
    assert coordinated["code"] == "workspace_binding_metadata_invalid"
    for sync in (False, True):
        with workspace_root_context(tmp_path):
            refused = tools.patchdiff_save(target_file_id=str(malformed.target_file_id), sync_workspace=sync)
        assert refused["code"] == "workspace_binding_metadata_invalid"
    assert file.read_bytes() == raw
    first_state = {"target_file_id": first.target_file_id, "version": first.version, "current_hash": first.current_hash}
    assert submit(first_state, "legacy", "early")["code"] == "workspace_binding_ambiguous"
    assert tools.patchdiff_save(target_file_id=str(second.target_file_id))["code"] == "workspace_binding_ambiguous"
    selection = recovery(first_state, raw, action="select_existing")
    picked = open_path(tmp_path, "pkg/target.txt", workspace_recovery=selection)
    assert picked["created"] is False and picked["target_file_id"] == str(first.target_file_id)
    assert open_path(tmp_path, "pkg/target.txt", workspace_recovery=selection)["deduplicated"] is True
    assert open_path(tmp_path, "pkg/target.txt")["target_file_id"] == str(first.target_file_id)
    assert tools.patchdiff_save(target_file_id=str(second.target_file_id))["code"] == "workspace_target_superseded"
    assert tools.patchdiff_replay(target_file_id=str(second.target_file_id))["materialized_state_matches"]

    member = reimport_members[0]
    member_state = {"target_file_id": member.target_file_id, "version": 0, "current_hash": member.current_hash}
    refused = open_path(tmp_path, "pkg/reimport.txt", workspace_recovery=recovery(
        member_state, changed, action="select_existing", key="drifted-selection",
    ))
    assert refused["code"] == "external_disk_drift"
    successor = open_path(tmp_path, "pkg/reimport.txt", workspace_recovery=recovery(member_state, changed))
    assert successor["created"] and successor["target_file_id"] != str(member.target_file_id)
    for old in reimport_members:
        assert tools.patchdiff_save(target_file_id=str(old.target_file_id))["code"] == "workspace_target_superseded"

    with pytest.raises(Exception, match="Cannot downgrade 20261111_0007: workspace binding evidence exists"):
        command.downgrade(config, "20261105_0006")
    connection.rollback()
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "20261111_0007"


def test_failed_reimport_rolls_back_successor_and_leaves_request_key_available(tmp_path, monkeypatch):
    file = tmp_path / "target.txt"
    file.write_bytes(b"initial")
    target = open_path(tmp_path)
    disk = b"external"
    file.write_bytes(disk)
    request = recovery(target, disk)
    real_import = target_service._import_workspace_target

    def fail_after_import(*args):
        real_import(*args)
        raise RuntimeError("interrupted successor creation")

    with monkeypatch.context() as interrupted:
        interrupted.setattr(target_service, "_import_workspace_target", fail_after_import)
        with pytest.raises(RuntimeError, match="interrupted successor creation"):
            open_path(tmp_path, workspace_recovery=request)
    assert open_path(tmp_path)["target_file_id"] == target["target_file_id"]
    with SessionLocal() as session:
        original = session.get(CloudTargetFiles, uuid.UUID(target["target_file_id"]))
        assert session.scalar(select(func.count()).select_from(CloudTargetFiles).where(
            CloudTargetFiles.project_id == original.project_id)) == 1
    retry = open_path(tmp_path, workspace_recovery=request)
    assert retry["status"] == "ok" and retry["created"] and not retry["deduplicated"]


def test_lost_stdio_open_and_recovery_responses_resume_recorded_history(tmp_path):
    file = tmp_path / "target.txt"
    file.write_bytes(b"initial")
    arguments = {"filename": file.name, "from_workspace": True}

    def drop_response(rpc, **fields):
        rpc("tools/call", {"name": "patchdiff_initialize_target", "arguments": {**arguments, **fields}}, read=False)

    with peer("workspace", workspace_root=tmp_path) as (process, rpc):
        drop_response(rpc)
    assert process.returncode == 0
    with peer("workspace", workspace_root=tmp_path) as (_, rpc):
        opened = rpc_call(rpc, "patchdiff_initialize_target", **arguments)
        assert opened["created"] is False and opened["version"] == 0

    disk = b"external"
    file.write_bytes(disk)
    request = recovery(opened, disk)
    with peer("workspace", workspace_root=tmp_path) as (process, rpc):
        drop_response(rpc, workspace_recovery=request)
    assert process.returncode == 0
    successor = open_path(tmp_path)
    assert successor["target_file_id"] != opened["target_file_id"]
    assert submit(successor, "external", "updated")["status"] == "accepted"
    with peer("workspace", workspace_root=tmp_path) as (_, rpc):
        replayed = rpc_call(rpc, "patchdiff_initialize_target", **arguments, workspace_recovery=request)
    assert replayed["deduplicated"] and replayed["target_file_id"] == successor["target_file_id"]
    assert replayed["version"] == 0 and replayed["current_hash"] == successor["current_hash"]
    assert open_path(tmp_path)["version"] == 1


def test_recorded_recovery_precedes_missing_or_unsafe_destination(tmp_path):
    directory = tmp_path / "sub"
    directory.mkdir()
    file = directory / "target.txt"
    name = "sub/target.txt"
    file.write_bytes(b"initial")
    opened = open_path(tmp_path, name)
    disk = b"external"
    file.write_bytes(disk)
    request = recovery(opened, disk)
    successor = open_path(tmp_path, name, workspace_recovery=request)
    assert successor["created"] is True

    file.unlink()
    directory.rmdir()
    drift = open_path(tmp_path, name)
    assert drift["code"] == "external_disk_drift" and drift["disk_sha256"] is None
    assert (drift["target_file_id"], drift["version"], drift["current_hash"]) == (
        successor["target_file_id"], successor["version"], successor["current_hash"])
    recovered = open_path(tmp_path, name, workspace_recovery=request)
    assert recovered["deduplicated"] and recovered["target_file_id"] == successor["target_file_id"]
    with workspace_root_context(tmp_path):
        assert tools.patchdiff_save(target_file_id=successor["target_file_id"], sync_workspace=True)["code"] == "external_disk_drift"

    directory.mkdir()
    other = tmp_path / "other.txt"
    other.write_bytes(b"unrelated")
    file.symlink_to(other)
    assert open_path(tmp_path, name)["code"] == "workspace_symlink_escape"
    assert open_path(tmp_path, name, workspace_recovery=request)["deduplicated"]
    assert open_path(tmp_path, name, workspace_recovery={
        **request, "expected_target_version": 1,
    })["code"] == "request_key_conflict"


@pytest.mark.parametrize("autoflush", [True, False])
@pytest.mark.parametrize("explicit_recovery", [True, False])
def test_workspace_open_preserves_pending_local_orm_changes(tmp_path, autoflush, explicit_recovery):
    file = tmp_path / "target.txt"
    file.write_bytes(b"initial")
    opened = open_path(tmp_path)
    request = WorkspaceRecovery.parse(recovery(opened, b"initial")) if explicit_recovery else None
    with SessionLocal(autoflush=autoflush) as session:
        target = session.get(CloudTargetFiles, uuid.UUID(opened["target_file_id"]))
        target.current_content = "pending local write"
        with pytest.raises(WorkspaceSyncError) as rejected:
            initialize_target_from_workspace(session, filename=file.name, workspace_root=tmp_path, recovery=request)
        assert rejected.value.code == "workspace_pending_target_changes"
        assert target in session.dirty and target.current_content == "pending local write"
        session.rollback()
    assert tools.patchdiff_read_target(target_file_id=opened["target_file_id"])["text"] == "initial"
    if request is not None:
        valid = open_path(tmp_path, workspace_recovery=recovery(opened, b"initial"))
        assert valid["created"] and not valid["deduplicated"]


def test_bound_invalid_disk_encoding_and_malformed_baseline_preserve_target(tmp_path):
    file = tmp_path / "target.txt"
    file.write_bytes(b"initial")
    opened = open_path(tmp_path)
    disk = b"\xff\x00"
    file.write_bytes(disk)
    assert open_path(tmp_path)["code"] == "external_disk_drift"
    invalid = open_path(tmp_path, workspace_recovery=recovery(opened, disk))
    assert invalid["code"] == "target_encoding_invalid"
    assert open_path(tmp_path, workspace_recovery=recovery(opened, disk))["deduplicated"]

    file.write_bytes(b"initial")
    with SessionLocal.begin() as session:
        target = session.get(CloudTargetFiles, uuid.UUID(opened["target_file_id"]))
        target.source_line_endings = {**target.source_line_endings, "last_synced_disk_sha256": ["bad"]}
    assert open_path(tmp_path)["code"] == "workspace_binding_metadata_invalid"
    assert submit(opened, "initial", "updated")["code"] == "workspace_binding_metadata_invalid"
    repaired = open_path(tmp_path, workspace_recovery=recovery(opened, b"initial", key="repair-baseline"))
    assert repaired["created"] and repaired["target_file_id"] != opened["target_file_id"]


def test_publication_keeps_recovery_out_until_checkpoint(tmp_path):
    file = tmp_path / "target.txt"
    file.write_bytes(b"initial")
    target = open_path(tmp_path)
    assert submit(target, "initial", "published")["status"] == "accepted"
    working = open_path(tmp_path)
    request = recovery(working, b"published")
    installed = Event()
    finish_checkpoint = Event()

    def pause_checkpoint():
        installed.set()
        assert finish_checkpoint.wait(10)

    def save():
        with SessionLocal() as session:
            return save_target(session, target_file_id=target["target_file_id"], expected_target_version=1,
                               sync_workspace=True, workspace_root=tmp_path, _after_snapshot=pause_checkpoint)

    with ThreadPoolExecutor(max_workers=1) as workers:
        pending_save = workers.submit(save)
        try:
            assert installed.wait(10)
            assert file.read_bytes() == b"published"
            assert open_path(tmp_path, workspace_recovery=request)["code"] == "workspace_busy"
        finally:
            finish_checkpoint.set()
        assert pending_save.result(timeout=10).status == "saved"

    reimported = open_path(tmp_path, workspace_recovery=request)
    assert reimported["created"] and not reimported["deduplicated"]
    assert file.read_bytes() == b"published"
