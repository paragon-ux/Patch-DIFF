"""Adversarial stress and challenge harness for Milestone M2 (SCRIPT-001..005).

Agent: Challenger M2-1 (critic, specialist)
Objective:
1. Symlink & Path Escape Challenge: Attempt to bypass directory containment (SCRIPT-001)
2. Cooperative Concurrency / Lost-Update Challenge: Multi-process and multi-threaded race conditions (SCRIPT-003)
3. Pre-Write Digest Tampering Challenge: Payload corruption and hash mismatch defense (SCRIPT-002)
4. Truthful Deferred Delivery Integrity Challenge: Corrupted paginated exports (SCRIPT-004)
5. Mandatory Preimage Enforcement Challenge: Existing target clobbering defense (SCRIPT-005)
"""

from __future__ import annotations

import base64
import errno
import fcntl
import hashlib
import multiprocessing as mp
import os
from pathlib import Path
import stat
import threading
import time
import uuid

import pytest

from examples import host_finalize as finalizer


# ==============================================================================
# Suite 1: Symlink & Path Escape Containment Challenge (SCRIPT-001)
# ==============================================================================

def test_symlink_dir_pointing_outside_jail_rejected(tmp_path: Path):
    """Challenge 1.1: Directory component symlink pointing outside authorized root is rejected."""
    auth_root = tmp_path / "authorized_root"
    auth_root.mkdir()
    outside_jail = tmp_path / "outside_jail"
    outside_jail.mkdir()

    canary_file = outside_jail / "canary_target.txt"
    canary_content = b"CANARY_INITIAL_SAFE\n"
    canary_file.write_bytes(canary_content)

    # Symlink inside auth_root pointing to outside_jail
    escape_link = auth_root / "link_to_jail"
    escape_link.symlink_to(outside_jail)

    hostile_payload = b"HOSTILE_PAYLOAD_PWNED\n"
    hostile_hash = hashlib.sha256(hostile_payload).hexdigest()

    # Target path traverses through the symlink
    target_path = escape_link / "canary_target.txt"

    with pytest.raises(finalizer.PathEscapeError) as exc_info:
        finalizer.safe_write_back_file(
            target_path,
            hostile_payload,
            expected_sha256=hostile_hash,
            authorized_root=auth_root,
            allow_unconditional_overwrite=True,
        )

    assert "is a symlink" in str(exc_info.value) or "is not a directory" in str(exc_info.value)
    # Canary MUST NOT be overwritten
    assert canary_file.read_bytes() == canary_content


def test_symlink_leaf_pointing_outside_jail_rejected(tmp_path: Path):
    """Challenge 1.2: Leaf target symlink pointing outside authorized root is rejected."""
    auth_root = tmp_path / "authorized_root"
    auth_root.mkdir()
    outside_jail = tmp_path / "outside_jail"
    outside_jail.mkdir()

    secret_file = outside_jail / "etc_shadow_mock.txt"
    secret_bytes = b"root:$6$mocksecretpasswordhash\n"
    secret_file.write_bytes(secret_bytes)

    # Target is a symlink pointing to the external sensitive file
    symlink_leaf = auth_root / "compromised_leaf.txt"
    symlink_leaf.symlink_to(secret_file)

    payload = b"OVERWRITTEN_CORRUPTED\n"
    payload_hash = hashlib.sha256(payload).hexdigest()

    with pytest.raises(finalizer.PathEscapeError) as exc_info:
        finalizer.safe_write_back_file(
            symlink_leaf,
            payload,
            expected_sha256=payload_hash,
            authorized_root=auth_root,
            allow_unconditional_overwrite=True,
        )

    assert "is a symlink" in str(exc_info.value)
    # Target outside MUST be untouched
    assert secret_file.read_bytes() == secret_bytes


def test_symlink_leaf_pointing_inside_root_rejected(tmp_path: Path):
    """Challenge 1.3: Leaf target symlink pointing to another file inside authorized root is rejected."""
    auth_root = tmp_path / "authorized_root"
    auth_root.mkdir()

    internal_secret = auth_root / "internal_secret.txt"
    internal_bytes = b"secret_internal_data\n"
    internal_secret.write_bytes(internal_bytes)

    symlink_leaf = auth_root / "alias_link.txt"
    symlink_leaf.symlink_to(internal_secret)

    payload = b"overwrite_data\n"
    payload_hash = hashlib.sha256(payload).hexdigest()

    with pytest.raises(finalizer.PathEscapeError) as exc_info:
        finalizer.safe_write_back_file(
            symlink_leaf,
            payload,
            expected_sha256=payload_hash,
            authorized_root=auth_root,
            allow_unconditional_overwrite=True,
        )

    assert "is a symlink" in str(exc_info.value)
    assert internal_secret.read_bytes() == internal_bytes


def test_symlink_intermediate_dir_pointing_inside_root_rejected(tmp_path: Path):
    """Challenge 1.4: Even internal symlinked directory components must be rejected via O_NOFOLLOW."""
    auth_root = tmp_path / "authorized_root"
    auth_root.mkdir()

    real_sub = auth_root / "real_sub"
    real_sub.mkdir()
    (real_sub / "original.txt").write_bytes(b"original\n")

    alias_dir_link = auth_root / "alias_sub"
    alias_dir_link.symlink_to(real_sub)

    payload = b"new_content\n"
    payload_hash = hashlib.sha256(payload).hexdigest()

    target_path = alias_dir_link / "new_file.txt"

    with pytest.raises(finalizer.PathEscapeError) as exc_info:
        finalizer.safe_write_back_file(
            target_path,
            payload,
            expected_sha256=payload_hash,
            authorized_root=auth_root,
        )

    assert "is a symlink" in str(exc_info.value)
    assert not (real_sub / "new_file.txt").exists()


def test_nested_symlink_chain_escape_rejected(tmp_path: Path):
    """Challenge 1.5: Deeply nested directory containing symlink in chain is rejected."""
    auth_root = tmp_path / "authorized_root"
    auth_root.mkdir()
    d1 = auth_root / "d1"
    d1.mkdir()

    external_dir = tmp_path / "external"
    external_dir.mkdir()
    canary = external_dir / "canary.txt"
    canary.write_bytes(b"safe\n")

    d2_link = d1 / "d2"
    d2_link.symlink_to(external_dir)

    payload = b"attack\n"
    h = hashlib.sha256(payload).hexdigest()

    with pytest.raises(finalizer.PathEscapeError):
        finalizer.safe_write_back_file(
            auth_root / "d1" / "d2" / "canary.txt",
            payload,
            expected_sha256=h,
            authorized_root=auth_root,
            allow_unconditional_overwrite=True,
        )

    assert canary.read_bytes() == b"safe\n"


@pytest.mark.parametrize(
    "bad_rel_path",
    [
        "../outside.txt",
        "../../outside.txt",
        "sub/../../outside.txt",
        "sub/nested/../../../outside.txt",
        "sub/./../../outside.txt",
        "..",
        "sub/..",
    ],
)
def test_parent_traversal_dotdot_variations_rejected(tmp_path: Path, bad_rel_path: str):
    """Challenge 1.6: Dot-dot path traversal attempts must raise PathEscapeError."""
    auth_root = tmp_path / "authorized_root"
    auth_root.mkdir()
    sub = auth_root / "sub"
    sub.mkdir()
    nested = sub / "nested"
    nested.mkdir()

    data = b"traversal_payload\n"
    h = hashlib.sha256(data).hexdigest()

    with pytest.raises(finalizer.PathEscapeError):
        finalizer.safe_write_back_file(
            auth_root / bad_rel_path,
            data,
            expected_sha256=h,
            authorized_root=auth_root,
        )


def test_absolute_paths_outside_root_rejected(tmp_path: Path):
    """Challenge 1.7: Absolute path not relative to authorized_root raises PathEscapeError."""
    auth_root = tmp_path / "authorized_root"
    auth_root.mkdir()
    outside_file = tmp_path / "outside_file.txt"
    outside_file.write_bytes(b"initial\n")

    data = b"escape\n"
    h = hashlib.sha256(data).hexdigest()

    with pytest.raises(finalizer.PathEscapeError):
        finalizer.safe_write_back_file(
            outside_file,
            data,
            expected_sha256=h,
            authorized_root=auth_root,
            allow_unconditional_overwrite=True,
        )

    assert outside_file.read_bytes() == b"initial\n"


def test_root_directory_as_target_rejected(tmp_path: Path):
    """Challenge 1.8: Attempting to write directly to authorized_root as a file is rejected."""
    auth_root = tmp_path / "authorized_root"
    auth_root.mkdir()

    data = b"content\n"
    h = hashlib.sha256(data).hexdigest()

    with pytest.raises(finalizer.PathEscapeError) as exc_info:
        finalizer.safe_write_back_file(
            auth_root,
            data,
            expected_sha256=h,
            authorized_root=auth_root,
        )
    assert "specifies root directory" in str(exc_info.value)


def test_destination_is_existing_directory_rejected(tmp_path: Path):
    """Challenge 1.9: Destination that is an existing sub-directory raises HostWriteBackError."""
    auth_root = tmp_path / "authorized_root"
    auth_root.mkdir()
    existing_dir = auth_root / "existing_dir"
    existing_dir.mkdir()

    data = b"content\n"
    h = hashlib.sha256(data).hexdigest()

    with pytest.raises(finalizer.HostWriteBackError) as exc_info:
        finalizer.safe_write_back_file(
            existing_dir,
            data,
            expected_sha256=h,
            authorized_root=auth_root,
        )
    assert "is a directory" in str(exc_info.value)
    assert existing_dir.is_dir()


# ==============================================================================
# Suite 2: Cooperative Concurrency, Lost-Update & Dead-Inode Races (SCRIPT-003)
# ==============================================================================

def test_multithreaded_high_contention_race_preserves_single_update(tmp_path: Path):
    """Challenge 2.1: 20 concurrent threads racing on same file with stale preimage.

    Guarantees:
    - Zero lost updates
    - Exactly 1 thread succeeds
    - Exactly 19 threads fail closed with PreimageMismatchError
    - Disk contains winner's exact bytes
    """
    auth_root = tmp_path / "project"
    auth_root.mkdir()
    target_file = auth_root / "concurrent_shared.txt"

    initial_bytes = b"version 0: initial baseline\n"
    target_file.write_bytes(initial_bytes)
    initial_hash = hashlib.sha256(initial_bytes).hexdigest()

    num_threads = 20
    barrier = threading.Barrier(num_threads)
    results: list[dict] = []
    results_lock = threading.Lock()

    def worker_thread(thread_id: int):
        thread_payload = f"version 1: updated by thread-{thread_id}\n".encode("utf-8")
        thread_hash = hashlib.sha256(thread_payload).hexdigest()
        barrier.wait()  # Synchronize release for maximum race contention
        try:
            res_path = finalizer.safe_write_back_file(
                target_file,
                thread_payload,
                expected_sha256=thread_hash,
                preimage_sha256=initial_hash,
                authorized_root=auth_root,
            )
            with results_lock:
                results.append({"thread_id": thread_id, "status": "success", "payload": thread_payload})
        except Exception as exc:
            with results_lock:
                results.append({"thread_id": thread_id, "status": "error", "error": exc})

    threads = [threading.Thread(target=worker_thread, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [r for r in results if r["status"] == "success"]
    failures = [r for r in results if r["status"] == "error"]

    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(failures) == num_threads - 1, f"Expected {num_threads - 1} failures, got {len(failures)}"

    # All failures must strictly be PreimageMismatchError
    for fail in failures:
        assert isinstance(fail["error"], finalizer.PreimageMismatchError)

    # Disk must match winning thread's exact payload
    winner_payload = successes[0]["payload"]
    assert target_file.read_bytes() == winner_payload


def _mp_worker(
    worker_id: int,
    target_file_str: str,
    auth_root_str: str,
    initial_hash: str,
    out_queue: mp.Queue,
    start_event: mp.Event,
):
    """Process worker function for multi-process concurrency test."""
    try:
        start_event.wait()  # Release simultaneously
        payload = f"version 1: written by process {worker_id}\n".encode("utf-8")
        p_hash = hashlib.sha256(payload).hexdigest()
        finalizer.safe_write_back_file(
            Path(target_file_str),
            payload,
            expected_sha256=p_hash,
            preimage_sha256=initial_hash,
            authorized_root=Path(auth_root_str),
        )
        out_queue.put({"worker_id": worker_id, "status": "success", "payload": payload})
    except finalizer.PreimageMismatchError as exc:
        out_queue.put({"worker_id": worker_id, "status": "preimage_mismatch", "error": str(exc)})
    except Exception as exc:
        out_queue.put({"worker_id": worker_id, "status": "other_error", "error": str(exc)})


def test_multiprocess_high_contention_race_preserves_single_update(tmp_path: Path):
    """Challenge 2.2: 8 separate OS processes racing under fcntl.flock on same file.

    Guarantees cross-process flock exclusivity across distinct process descriptors.
    """
    auth_root = tmp_path / "mp_project"
    auth_root.mkdir()
    target_file = auth_root / "mp_target.txt"

    initial_bytes = b"process baseline version 0\n"
    target_file.write_bytes(initial_bytes)
    initial_hash = hashlib.sha256(initial_bytes).hexdigest()

    num_workers = 8
    out_queue: mp.Queue = mp.Queue()
    start_event: mp.Event = mp.Event()

    processes = [
        mp.Process(
            target=_mp_worker,
            args=(
                i,
                str(target_file),
                str(auth_root),
                initial_hash,
                out_queue,
                start_event,
            ),
        )
        for i in range(num_workers)
    ]

    for p in processes:
        p.start()

    # Trigger synchronized launch
    start_event.set()

    for p in processes:
        p.join(timeout=10)
        assert not p.is_alive(), "Process did not terminate within timeout (possible deadlock)"

    results = []
    while not out_queue.empty():
        results.append(out_queue.get())

    assert len(results) == num_workers
    successes = [r for r in results if r["status"] == "success"]
    mismatches = [r for r in results if r["status"] == "preimage_mismatch"]
    others = [r for r in results if r["status"] == "other_error"]

    assert len(others) == 0, f"Unexpected errors: {others}"
    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(mismatches) == num_workers - 1

    winner_payload = successes[0]["payload"]
    assert target_file.read_bytes() == winner_payload


def test_dead_inode_replacement_race_stress(tmp_path: Path):
    """Challenge 2.3: Verify that os.replace inode mutation does not decouple waiting lock holders.

    Worker A acquires lock, safe_write_back_file calls os.replace (changing target file's inode).
    Worker B is queued waiting for .lock-{leaf}.
    When Worker A exits, Worker B must acquire the SAME .lock-{leaf} file (stable inode),
    inspect the NEW target inode, and fail with PreimageMismatchError rather than writing
    to a dead/detached inode or corrupting the new inode.
    """
    auth_root = tmp_path / "inode_test"
    auth_root.mkdir()
    target_file = auth_root / "inode_race.txt"

    v1_bytes = b"v1: original inode\n"
    target_file.write_bytes(v1_bytes)
    v1_hash = hashlib.sha256(v1_bytes).hexdigest()
    initial_inode = target_file.stat().st_ino

    lock_file = auth_root / f".lock-{target_file.name}"
    # Prime lock file to capture lock inode
    lock_fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o600)
    lock_inode_initial = os.fstat(lock_fd).st_ino
    os.close(lock_fd)

    v2_bytes = b"v2: replaced inode by Worker A\n"
    v2_hash = hashlib.sha256(v2_bytes).hexdigest()

    # Step 1: Worker A replaces target file
    finalizer.safe_write_back_file(
        target_file,
        v2_bytes,
        expected_sha256=v2_hash,
        preimage_sha256=v1_hash,
        authorized_root=auth_root,
    )

    new_inode = target_file.stat().st_ino
    assert new_inode != initial_inode, "os.replace should have created a new inode"

    # Verify lock file inode did NOT change
    lock_inode_current = lock_file.stat().st_ino
    assert lock_inode_current == lock_inode_initial, "Lock file inode must remain constant"

    # Step 2: Worker B attempts write back with stale v1_hash
    v3_bytes = b"v3: stale proposal by Worker B\n"
    v3_hash = hashlib.sha256(v3_bytes).hexdigest()

    with pytest.raises(finalizer.PreimageMismatchError):
        finalizer.safe_write_back_file(
            target_file,
            v3_bytes,
            expected_sha256=v3_hash,
            preimage_sha256=v1_hash,  # Stale!
            authorized_root=auth_root,
        )

    # v2 must remain completely intact
    assert target_file.read_bytes() == v2_bytes
    assert target_file.stat().st_ino == new_inode


def test_concurrent_creation_of_nonexistent_destination(tmp_path: Path):
    """Challenge 2.4: 10 threads trying to initialize the same nonexistent file simultaneously.

    Thread 1 creates it.
    Threads 2..10 acquire the lock, discover the file now exists, and fail closed
    with PreimageMismatchError (since preimage_sha256 is None and allow_unconditional_overwrite is False).
    """
    auth_root = tmp_path / "create_race"
    auth_root.mkdir()
    target_file = auth_root / "brand_new_file.txt"

    num_threads = 10
    barrier = threading.Barrier(num_threads)
    results = []
    lock = threading.Lock()

    def creator_thread(tid: int):
        data = f"first-init from thread {tid}\n".encode("utf-8")
        h = hashlib.sha256(data).hexdigest()
        barrier.wait()
        try:
            finalizer.safe_write_back_file(
                target_file,
                data,
                expected_sha256=h,
                preimage_sha256=None,
                authorized_root=auth_root,
                allow_unconditional_overwrite=False,
            )
            with lock:
                results.append({"tid": tid, "status": "success", "data": data})
        except Exception as exc:
            with lock:
                results.append({"tid": tid, "status": "error", "error": exc})

    threads = [threading.Thread(target=creator_thread, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    successes = [r for r in results if r["status"] == "success"]
    failures = [r for r in results if r["status"] == "error"]

    assert len(successes) == 1
    assert len(failures) == num_threads - 1

    for fail in failures:
        assert isinstance(fail["error"], finalizer.PreimageMismatchError)
        assert "already exists; preimage_sha256 is required" in str(fail["error"])


def test_uncoordinated_external_clobber_detected_by_cooperative_writer(tmp_path: Path):
    """Challenge 2.5: Uncoordinated writer alters target file without acquiring lock.

    The next cooperative writer must detect the altered disk hash under lock
    and fail closed with PreimageMismatchError before replacing anything.
    """
    auth_root = tmp_path / "clobber_test"
    auth_root.mkdir()
    target_file = auth_root / "guarded.txt"

    v1_bytes = b"v1: legitimate baseline\n"
    target_file.write_bytes(v1_bytes)
    v1_hash = hashlib.sha256(v1_bytes).hexdigest()

    # External uncoordinated rogue write directly modifies disk
    rogue_bytes = b"ROGUE_INJECTION_CORRUPTED\n"
    target_file.write_bytes(rogue_bytes)

    # Cooperative writer attempts guarded write expecting v1
    v2_bytes = b"v2: planned update\n"
    v2_hash = hashlib.sha256(v2_bytes).hexdigest()

    with pytest.raises(finalizer.PreimageMismatchError) as exc_info:
        finalizer.safe_write_back_file(
            target_file,
            v2_bytes,
            expected_sha256=v2_hash,
            preimage_sha256=v1_hash,
            authorized_root=auth_root,
        )

    assert "does not match" in str(exc_info.value) or "has hash" in str(exc_info.value)
    # The rogue content was not replaced by v2
    assert target_file.read_bytes() == rogue_bytes


# ==============================================================================
# Suite 3: Pre-Write Digest Tampering Challenge (SCRIPT-002)
# ==============================================================================

def test_prewrite_tampered_single_bit_flip_aborts_before_disk(tmp_path: Path):
    """Challenge 3.1: 1-bit corrupted payload fails before any disk interaction.

    Assert:
    - HostWriteBackError raised immediately
    - Destination file untouched (exact content, inode, mtime)
    - Zero temporary files (.tmp-*) created
    - Zero lock files (.lock-*) created
    """
    auth_root = tmp_path / "tamper_test"
    auth_root.mkdir()
    target_file = auth_root / "prewrite_target.txt"

    original_bytes = b"ORIGINAL_PERSISTENT_DATA\n"
    target_file.write_bytes(original_bytes)
    orig_stat = target_file.stat()

    valid_payload = b"PROPOSED_NEW_CONTENT\n"
    expected_hash = hashlib.sha256(valid_payload).hexdigest()

    # Tamper payload by flipping one bit
    corrupted_payload = bytearray(valid_payload)
    corrupted_payload[0] ^= 0x01
    corrupted_bytes = bytes(corrupted_payload)

    # Initial directory inventory
    dir_files_before = set(os.listdir(auth_root))

    with pytest.raises(finalizer.HostWriteBackError) as exc_info:
        finalizer.safe_write_back_file(
            target_file,
            corrupted_bytes,
            expected_sha256=expected_hash,
            preimage_sha256=hashlib.sha256(original_bytes).hexdigest(),
            authorized_root=auth_root,
        )

    assert "Pre-write digest verification failed" in str(exc_info.value)

    # Verify destination file is completely untouched
    assert target_file.read_bytes() == original_bytes
    new_stat = target_file.stat()
    assert new_stat.st_ino == orig_stat.st_ino
    assert new_stat.st_mtime_ns == orig_stat.st_mtime_ns
    assert new_stat.st_size == orig_stat.st_size

    # Verify ZERO new files (.tmp or .lock) were created
    dir_files_after = set(os.listdir(auth_root))
    assert dir_files_after == dir_files_before


@pytest.mark.parametrize(
    "corrupt_idx",
    [0, 10, 500, 1024, -1],
)
def test_prewrite_tampered_large_payload_locations(tmp_path: Path, corrupt_idx: int):
    """Challenge 3.2: 1 MiB payload with bit corruption at various offsets."""
    auth_root = tmp_path / "large_tamper"
    auth_root.mkdir()
    target_file = auth_root / "large_file.bin"

    # 1 MiB payload
    large_payload = b"A" * (1024 * 1024)
    expected_hash = hashlib.sha256(large_payload).hexdigest()

    # Corrupt at specific index
    corrupted = bytearray(large_payload)
    corrupted[corrupt_idx] = ord("B")
    corrupted_bytes = bytes(corrupted)

    with pytest.raises(finalizer.HostWriteBackError) as exc_info:
        finalizer.safe_write_back_file(
            target_file,
            corrupted_bytes,
            expected_sha256=expected_hash,
            authorized_root=auth_root,
        )

    assert "Pre-write digest verification failed" in str(exc_info.value)
    assert not target_file.exists()
    assert len(list(auth_root.glob(".tmp-*"))) == 0
    assert len(list(auth_root.glob(".lock-*"))) == 0


@pytest.mark.parametrize(
    "bad_expected_hash",
    [
        None,
        123456789,
        "not_a_valid_hash",
        "a" * 63,  # 63 chars (too short)
        "a" * 65,  # 65 chars (too long)
        "g" * 64,  # invalid hex character 'g'
        " " + "a" * 64,
        "a" * 63 + "\n",
    ],
)
def test_prewrite_invalid_expected_sha_formats(tmp_path: Path, bad_expected_hash):
    """Challenge 3.3: Invalid expected_sha256 formats fail before touching disk."""
    auth_root = tmp_path / "format_test"
    auth_root.mkdir()
    target_file = auth_root / "format.txt"

    data = b"some data"
    with pytest.raises(finalizer.HostWriteBackError) as exc_info:
        finalizer.safe_write_back_file(
            target_file,
            data,
            expected_sha256=bad_expected_hash,
            authorized_root=auth_root,
        )
    assert "Invalid expected_sha256 format" in str(exc_info.value)
    assert not target_file.exists()


@pytest.mark.parametrize(
    "bad_data",
    [
        "this is a string, not bytes",
        ["list", "of", "items"],
        {"dict": "data"},
        12345,
        None,
    ],
)
def test_prewrite_non_bytes_data_rejected(tmp_path: Path, bad_data):
    """Challenge 3.4: Passing non-bytes data fails immediately."""
    auth_root = tmp_path / "type_test"
    auth_root.mkdir()
    target_file = auth_root / "types.txt"

    with pytest.raises(finalizer.HostWriteBackError) as exc_info:
        finalizer.safe_write_back_file(
            target_file,
            bad_data,  # type: ignore
            expected_sha256="a" * 64,
            authorized_root=auth_root,
        )
    assert "data must be bytes" in str(exc_info.value)
    assert not target_file.exists()


# ==============================================================================
# Suite 4: Truthful Deferred Delivery Integrity Challenge (SCRIPT-004)
# ==============================================================================

def test_finalize_deferred_corrupted_base64_fails_closed(tmp_path: Path):
    """Challenge 4.1: Corrupted base64 payload during pagination fails closed with disk_status='error'."""
    tid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    dest_file = tmp_path / "deferred_b64_fail.bin"

    def mock_call(name, **args):
        if name == "patchdiff_finalize_target":
            return {
                "status": "ok",
                "target_file_id": tid,
                "finalization_id": fid,
                "version": 1,
                "exported_content": None,
                "content_delivery": "deferred",
                "content_sha256": "a" * 64,
                "content_bytes": 100,
            }
        if name == "patchdiff_read_finalized_export":
            return {
                "status": "ok",
                "finalization_id": fid,
                "target_file_id": tid,
                "content_base64": "!!!NOT_VALID_BASE64_PADDING@@@",
                "offset": 0,
                "bytes_read": 50,
                "total_bytes": 100,
                "has_more": True,
                "next_offset": 50,
            }
        raise ValueError(name)

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="b64-fail",
        destination_path=dest_file,
        raise_on_disk_error=False,
    )

    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert "Invalid base64 payload" in receipt["disk_error"]
    assert not dest_file.exists()


def test_finalize_deferred_assembled_sha256_mismatch_fails_closed(tmp_path: Path):
    """Challenge 4.2: Assembled deferred stream hash mismatch fails closed."""
    tid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    dest_file = tmp_path / "deferred_hash_mismatch.bin"
    actual_data = b"assembled chunk data"

    def mock_call(name, **args):
        if name == "patchdiff_finalize_target":
            return {
                "status": "ok",
                "target_file_id": tid,
                "finalization_id": fid,
                "version": 1,
                "exported_content": None,
                "content_delivery": "deferred",
                "content_sha256": "0" * 64,  # Expected hash does not match actual
                "content_bytes": len(actual_data),
            }
        if name == "patchdiff_read_finalized_export":
            return {
                "status": "ok",
                "finalization_id": fid,
                "target_file_id": tid,
                "content_base64": base64.b64encode(actual_data).decode("ascii"),
                "offset": 0,
                "bytes_read": len(actual_data),
                "total_bytes": len(actual_data),
                "has_more": False,
                "next_offset": None,
            }
        raise ValueError(name)

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="sha-mismatch",
        destination_path=dest_file,
        raise_on_disk_error=False,
    )

    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert "Deferred assembled bytes SHA-256" in receipt["disk_error"]
    assert not dest_file.exists()


def test_finalize_deferred_assembled_length_mismatch_fails_closed(tmp_path: Path):
    """Challenge 4.3: Assembled deferred stream length mismatch fails closed."""
    tid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    dest_file = tmp_path / "deferred_len_mismatch.bin"
    actual_data = b"short"
    actual_hash = hashlib.sha256(actual_data).hexdigest()

    def mock_call(name, **args):
        if name == "patchdiff_finalize_target":
            return {
                "status": "ok",
                "target_file_id": tid,
                "finalization_id": fid,
                "version": 1,
                "exported_content": None,
                "content_delivery": "deferred",
                "content_sha256": actual_hash,
                "content_bytes": 999999,  # Mismatched expected length
            }
        if name == "patchdiff_read_finalized_export":
            return {
                "status": "ok",
                "finalization_id": fid,
                "target_file_id": tid,
                "content_base64": base64.b64encode(actual_data).decode("ascii"),
                "offset": 0,
                "bytes_read": len(actual_data),
                "total_bytes": 999999,
                "has_more": False,
                "next_offset": None,
            }
        raise ValueError(name)

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="len-mismatch",
        destination_path=dest_file,
        raise_on_disk_error=False,
    )

    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert "Deferred assembled bytes length" in receipt["disk_error"]
    assert not dest_file.exists()


def test_finalize_deferred_stalled_pagination_offset_fails_closed(tmp_path: Path):
    """Challenge 4.4: Loop stall attack where next_offset <= current offset."""
    tid = str(uuid.uuid4())
    fid = str(uuid.uuid4())
    dest_file = tmp_path / "deferred_stall.bin"

    def mock_call(name, **args):
        if name == "patchdiff_finalize_target":
            return {
                "status": "ok",
                "target_file_id": tid,
                "finalization_id": fid,
                "version": 1,
                "exported_content": None,
                "content_delivery": "deferred",
                "content_sha256": "a" * 64,
                "content_bytes": 1000,
            }
        if name == "patchdiff_read_finalized_export":
            return {
                "status": "ok",
                "finalization_id": fid,
                "target_file_id": tid,
                "content_base64": base64.b64encode(b"chunk").decode("ascii"),
                "offset": 0,
                "bytes_read": 5,
                "total_bytes": 1000,
                "has_more": True,
                "next_offset": 0,  # Invalid: next_offset <= offset (infinite loop attempt)
            }
        raise ValueError(name)

    receipt = finalizer.finalize_single_target(
        mock_call,
        target_file_id=tid,
        client_request_id="stall-test",
        destination_path=dest_file,
        raise_on_disk_error=False,
    )

    assert receipt["status"] == "error"
    assert receipt["db_status"] == "ok"
    assert receipt["disk_status"] == "error"
    assert "Invalid pagination response" in receipt["disk_error"]
    assert not dest_file.exists()


# ==============================================================================
# Suite 5: Invariant & Resource Defense (Descriptor Leaks & Pipeline Stress)
# ==============================================================================

def test_descriptor_leak_invariance_across_all_paths(tmp_path: Path):
    """Challenge 5.1: Assert ZERO file descriptor leaks across success and all error paths."""
    proc_fd_dir = Path("/proc/self/fd")
    if not proc_fd_dir.exists():
        pytest.skip("/proc/self/fd not supported on this platform")

    auth_root = tmp_path / "fd_test_root"
    auth_root.mkdir()
    target_file = auth_root / "fd_target.txt"

    data = b"valid data\n"
    h = hashlib.sha256(data).hexdigest()

    def get_open_fds() -> set[int]:
        # Filter out the directory listing fd itself
        return {int(p.name) for p in proc_fd_dir.iterdir() if p.name.isdigit()}

    # Warmup Python runtime / imports
    finalizer.safe_write_back_file(target_file, data, expected_sha256=h, authorized_root=auth_root)

    baseline_fds = get_open_fds()

    for i in range(10):
        # 1. Success path
        new_data = f"iteration {i}\n".encode("utf-8")
        new_h = hashlib.sha256(new_data).hexdigest()
        curr_h = hashlib.sha256(target_file.read_bytes()).hexdigest()
        finalizer.safe_write_back_file(
            target_file, new_data, expected_sha256=new_h, preimage_sha256=curr_h, authorized_root=auth_root
        )

        # 2. Path escape error
        with pytest.raises(finalizer.PathEscapeError):
            finalizer.safe_write_back_file(
                auth_root / "../outside.txt", new_data, expected_sha256=new_h, authorized_root=auth_root
            )

        # 3. Digest tampering error
        with pytest.raises(finalizer.HostWriteBackError):
            finalizer.safe_write_back_file(
                target_file, b"corrupted", expected_sha256=new_h, authorized_root=auth_root
            )

        # 4. Preimage mismatch error
        with pytest.raises(finalizer.PreimageMismatchError):
            finalizer.safe_write_back_file(
                target_file, new_data, expected_sha256=new_h, preimage_sha256="bad" * 16, authorized_root=auth_root
            )

    post_fds = get_open_fds()
    leaked_fds = post_fds - baseline_fds
    assert not leaked_fds, f"Leaked file descriptors detected: {leaked_fds}"


def _pipeline_worker(
    worker_id: int,
    target_str: str,
    auth_root_str: str,
    revisions_target: int,
    out_queue: mp.Queue,
):
    """Worker that repeatedly reads current state, generates next revision, and writes back."""
    target = Path(target_str)
    auth_root = Path(auth_root_str)
    committed = 0

    while True:
        try:
            curr_bytes = target.read_bytes()
        except OSError:
            time.sleep(0.01)
            continue

        try:
            curr_rev = int(curr_bytes.decode("utf-8").strip().split()[-1])
        except Exception:
            curr_rev = 0

        if curr_rev >= revisions_target:
            break

        next_rev = curr_rev + 1
        payload = f"revision {next_rev}\n".encode("utf-8")
        p_hash = hashlib.sha256(payload).hexdigest()
        pre_hash = hashlib.sha256(curr_bytes).hexdigest()

        try:
            finalizer.safe_write_back_file(
                target,
                payload,
                expected_sha256=p_hash,
                preimage_sha256=pre_hash,
                authorized_root=auth_root,
            )
            committed += 1
        except finalizer.PreimageMismatchError:
            # Expected under competition: another worker committed ahead; loop and retry
            time.sleep(0.005)
        except Exception as exc:
            out_queue.put({"worker_id": worker_id, "status": "error", "error": str(exc)})
            return

    out_queue.put({"worker_id": worker_id, "status": "done", "committed": committed})


def test_multiprocess_serialized_pipeline_with_backoff_and_retry(tmp_path: Path):
    """Challenge 5.2: Multi-process pipeline completing 10 serialized revisions under high contention."""
    auth_root = tmp_path / "pipeline_root"
    auth_root.mkdir()
    target_file = auth_root / "pipeline_file.txt"

    target_file.write_bytes(b"revision 0\n")

    num_workers = 4
    total_revisions = 10
    out_queue = mp.Queue()

    workers = [
        mp.Process(
            target=_pipeline_worker,
            args=(i, str(target_file), str(auth_root), total_revisions, out_queue),
        )
        for i in range(num_workers)
    ]

    for w in workers:
        w.start()

    for w in workers:
        w.join(timeout=15)
        assert not w.is_alive(), "Worker hung during pipeline test (possible deadlock)"

    results = []
    while not out_queue.empty():
        results.append(out_queue.get())

    assert len(results) == num_workers
    for r in results:
        assert r["status"] == "done", f"Worker failed: {r}"

    # Verify that exactly revision 10 was reached cleanly
    final_content = target_file.read_bytes().decode("utf-8").strip()
    assert final_content == f"revision {total_revisions}"
