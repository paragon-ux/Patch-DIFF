import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.result import RejectedCoreResult
from app.core.versions import RUNTIME_VERSION as TYPED_RUNTIME_VERSION
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.operations import (
    OPERATIONS_PROTOCOL_VERSION,
    build_operations_record,
    operations_runtime_version,
    parse_operations_record,
    to_parsed_operations,
)
from app.pdcp.typed import (
    TYPED_PROTOCOL_VERSION,
    build_record as build_typed_record,
    canonical_record_json,
    parse_typed_record,
    to_parsed_transaction as to_parsed_typed,
)
from app.services.workspace_binding_service import workspace_write_fence
from app.storage.models import AppendOnlyManifestLedger, AppendOnlyPdcpLogs, CloudTargetFiles
from app.storage.repositories import select_targets_for_update_ordered


def _coerce_uuid(val: Any) -> uuid.UUID | None:
    if isinstance(val, uuid.UUID):
        return val
    try:
        return uuid.UUID(str(val))
    except (ValueError, TypeError, AttributeError):
        return None


def submit_coordinated_transactions(
    session: Session,
    *,
    intent: str,
    targets: list[dict[str, Any]],
    client_request_id: str | None = None,
) -> dict[str, Any]:
    """Execute an all-or-nothing multi-target coordinated transaction.

    Acquires row locks on all target rows in strict canonical ascending UUID order
    to mathematically eliminate circular waits and deadlock risks.
    """
    if not targets:
        return {
            "status": "rejected",
            "code": "empty_targets",
            "failure_detail": "Coordinated transaction requires at least one target specification.",
            "failed_target_file_id": None,
            "coordinated_transaction_id": None,
            "targets": [],
        }

    # 1. Parse and validate target identifiers
    target_uuids: list[uuid.UUID] = []
    for entry in targets:
        raw_id = entry.get("target_file_id")
        parsed_uuid = _coerce_uuid(raw_id)
        if parsed_uuid is None:
            return {
                "status": "rejected",
                "code": "invalid_target_file_id",
                "failure_detail": f"Invalid target_file_id: {raw_id}.",
                "failed_target_file_id": str(raw_id) if raw_id is not None else None,
                "coordinated_transaction_id": None,
                "targets": [],
            }
        if parsed_uuid in target_uuids:
            return {
                "status": "rejected",
                "code": "duplicate_target_in_coordinated_transaction",
                "failure_detail": f"Target {parsed_uuid} appears more than once in the coordinated transaction.",
                "failed_target_file_id": str(parsed_uuid),
                "coordinated_transaction_id": None,
                "targets": [],
            }
        target_uuids.append(parsed_uuid)

    # 2. Acquire locks in canonical UUID order
    sorted_uuids = sorted(target_uuids, key=str)
    stmt = select_targets_for_update_ordered(sorted_uuids)
    locked_rows = session.execute(stmt).scalars().all()
    locked_by_id = {row.target_file_id: row for row in locked_rows}

    # Verify all targets exist
    for tid in target_uuids:
        if tid not in locked_by_id:
            return {
                "status": "rejected",
                "code": "target_not_found",
                "failure_detail": f"Target {tid} was not found.",
                "failed_target_file_id": str(tid),
                "coordinated_transaction_id": None,
                "targets": [],
            }

    # 3. Evaluate preconditions across all targets first
    for entry in targets:
        tid = _coerce_uuid(entry["target_file_id"])
        target = locked_by_id[tid]

        fence = workspace_write_fence(session, target)
        if fence is not None:
            return {
                "status": "rejected",
                "code": fence.code,
                "failure_detail": fence.detail,
                "failed_target_file_id": str(tid),
                "coordinated_transaction_id": None,
                "targets": [],
                **fence.evidence,
            }

        exp_version = entry.get("expected_target_version")
        if exp_version is not None and target.version != exp_version:
            return {
                "status": "rejected",
                "code": "target_version_mismatch",
                "failure_detail": f"Target {tid} version mismatch: expected {exp_version}, found {target.version}.",
                "failed_target_file_id": str(tid),
                "coordinated_transaction_id": None,
                "targets": [],
            }

        exp_hash = entry.get("expected_current_hash")
        if exp_hash is not None and target.current_hash != exp_hash:
            return {
                "status": "rejected",
                "code": "target_hash_mismatch",
                "failure_detail": f"Target {tid} content hash mismatch: expected {exp_hash}, found {target.current_hash}.",
                "failed_target_file_id": str(tid),
                "coordinated_transaction_id": None,
                "targets": [],
            }

    # 4. In-memory simulation across all targets
    simulated_plans: list[dict[str, Any]] = []

    for entry in targets:
        tid = _coerce_uuid(entry["target_file_id"])
        target = locked_by_id[tid]
        exp_version = entry.get("expected_target_version")
        exp_hash = entry.get("expected_current_hash")

        # Parse operations or edits
        operations = entry.get("operations")
        edits = entry.get("edits")

        if operations is not None:
            record = build_operations_record(
                target_file_id=str(tid),
                intent=intent,
                operations=operations,
                expected_target_version=exp_version,
                expected_current_hash=exp_hash,
            )
            typed = parse_operations_record(record)
            parsed = to_parsed_operations(typed, target_type=target.target_type)
            protocol_version = OPERATIONS_PROTOCOL_VERSION
            runtime_version = operations_runtime_version(record)
            allow_spans = True
            allow_context = True
        elif edits is not None:
            record = build_typed_record(
                target_file_id=str(tid),
                intent=intent,
                edits=edits,
                expected_target_version=exp_version,
                expected_current_hash=exp_hash,
            )
            typed = parse_typed_record(record)
            parsed = to_parsed_typed(typed, target_type=target.target_type)
            protocol_version = TYPED_PROTOCOL_VERSION
            runtime_version = TYPED_RUNTIME_VERSION
            allow_spans = False
            allow_context = False
        else:
            return {
                "status": "rejected",
                "code": "missing_operations",
                "failure_detail": f"Target {tid} must provide operations or edits.",
                "failed_target_file_id": str(tid),
                "coordinated_transaction_id": None,
                "targets": [],
            }

        # Simulate in-memory execution
        sim_result = apply_pdcp_transaction(
            target.current_content,
            parsed,
            overlapping_matches=True,
            enforce_singleton_selectors=True,
            allow_span_operations=allow_spans,
            allow_replace_all_operations=False,
            allow_span_context=allow_context,
            collect_warnings=True,
        )

        if isinstance(sim_result, RejectedCoreResult):
            return {
                "status": "rejected",
                "code": sim_result.failure_reason.value if hasattr(sim_result.failure_reason, "value") else str(sim_result.failure_reason),
                "failure_detail": sim_result.failure_detail,
                "failed_change_id": sim_result.failed_change_id,
                "failed_target_file_id": str(tid),
                "coordinated_transaction_id": None,
                "targets": [],
            }

        simulated_plans.append({
            "target": target,
            "record": record,
            "typed": typed,
            "result": sim_result,
            "protocol_version": protocol_version,
            "runtime_version": runtime_version,
            "before_version": target.version,
            "before_hash": target.current_hash,
            "expected_version": exp_version,
            "expected_hash": exp_hash,
        })

    # 5. All evaluations succeeded: commit state transitions and write audit records
    coordinated_transaction_id = uuid.uuid4()
    completed_targets: list[dict[str, Any]] = []

    for plan in simulated_plans:
        target = plan["target"]
        sim_res = plan["result"]
        record = plan["record"]
        typed = plan["typed"]

        target.version = target.version + 1
        target.current_content = sim_res.target_content
        target.current_hash = sim_res.after_hash

        record_json = canonical_record_json(record)
        record_hash = canonical_sha256(record_json)

        diag = {
            "coordinated_transaction_id": str(coordinated_transaction_id),
            "target_count": len(targets),
            "participating_targets": [str(t) for t in target_uuids],
        }

        log = AppendOnlyPdcpLogs(
            target_file_id=target.target_file_id,
            editing_cycle_id=target.active_editing_cycle_id,
            submission_source="model_response",
            protocol_version=plan["protocol_version"],
            runtime_version=plan["runtime_version"],
            pdcp_content=record_json,
            pdcp_content_hash=record_hash,
            status="accepted",
            diagnostic_json=diag,
            expected_target_version=plan["expected_version"],
            expected_current_hash=plan["expected_hash"],
            before_version=plan["before_version"],
            after_version=target.version,
            before_hash=plan["before_hash"],
            after_hash=sim_res.after_hash,
            change_count=sim_res.change_count,
            client_request_id=client_request_id,
        )
        session.add(log)
        session.flush()

        for index, edit in enumerate(typed.edits, 1):
            ledger = AppendOnlyManifestLedger(
                target_file_id=target.target_file_id,
                editing_cycle_id=target.active_editing_cycle_id,
                pdcp_log_id=log.pdcp_log_id,
                change_index=index,
                change_id=edit.change_id,
                intent=edit.rationale or typed.intent,
                input_state=None,
                output_state=None,
                affected_region=None,
                user_visible_change=None,
                risk=edit.risk,
                origin="typed",
                derived_json=None,
            )
            session.add(ledger)

        completed_targets.append({
            "target_file_id": str(target.target_file_id),
            "version": target.version,
            "current_hash": target.current_hash,
            "pdcp_log_id": str(log.pdcp_log_id),
        })

    session.flush()

    return {
        "status": "accepted",
        "coordinated_transaction_id": str(coordinated_transaction_id),
        "targets": completed_targets,
    }
