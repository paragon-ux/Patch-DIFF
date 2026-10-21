"""Prompt context construction for MCP orchestration."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.pdcp.models import (
    OPTIONAL_DISAMBIGUATION_FIELDS,
    REQUIRED_MANIFEST_FIELDS,
    SUPPORTED_MANIFEST_FIELDS,
    SUPPORTED_PROTOCOL_VERSION,
    VALID_RISK_VALUES,
)
from app.pdcp.parser import MATCH_DELIMITER, REPLACE_DELIMITER, SEPARATOR_DELIMITER
from app.core.input_text import invalid_text_paths, safe_input_text
from app.storage.models import AppendOnlyManifestLedger, CloudTargetFiles


def pdcp_rules_text(
    *,
    target_file_id: uuid.UUID | str | None = None,
    target_type: str | None = None,
    current_hash: str | None = None,
    target_context: str | None = None,
) -> str:
    required_fields = "\n".join(f"# {field}: <value>" for field in sorted(REQUIRED_MANIFEST_FIELDS))
    optional_fields = ", ".join(sorted(OPTIONAL_DISAMBIGUATION_FIELDS))
    allowed_fields = ", ".join(sorted(SUPPORTED_MANIFEST_FIELDS))
    risk_values = ", ".join(sorted(VALID_RISK_VALUES))
    example = _minimal_pdcp_example(
        target_file_id=target_file_id,
        target_type=target_type,
        current_hash=current_hash,
    )
    return f"""Emit exactly one raw declarative .pdcp transaction using PDCP {SUPPORTED_PROTOCOL_VERSION}.

Protocol header format:
PDCP {SUPPORTED_PROTOCOL_VERSION}
target_file_id: {target_file_id or "<target_file_id>"}
target_type: {target_type or "<target_type>"}
target_hash: {current_hash or "<optional_current_sha256_hash>"}

Manifest contract:
- Each change block must have exactly one # MANIFEST block immediately before its MATCH/REPLACE block.
- Required manifest fields, all non-empty:
{required_fields}
- Optional disambiguation/hash fields: {optional_fields}
- Allowed manifest fields are exactly: {allowed_fields}
- Unknown manifest fields are invalid.
- Valid risk values are exactly: {risk_values}

Exact MATCH/REPLACE delimiter lines:
{MATCH_DELIMITER}
<non-empty exact current target text>
{SEPARATOR_DELIMITER}
<replacement text; may be empty for deletion>
{REPLACE_DELIMITER}

Transaction rules:
- MATCH payload must be non-empty.
- Empty REPLACE means deletion.
- MATCH is exact, case-sensitive, whitespace-sensitive, and multiline after LF canonicalization.
- Do not use fuzzy matching, semantic matching, AST matching, line-number authority, automatic repair, or full-document rewrite.
- PDCP is declarative and non-executable: do not generate apply functions, imports, loops, conditionals, tool calls, shell commands, network calls, filesystem calls, or runtime logic outside payloads.
- Output raw .pdcp content only. For chat-rendered clients, put the PDCP in a plain code block while drafting, then submit only the raw code-block contents through MCP with no Markdown fences, blockquotes, or surrounding prose.

Literal replacement scope and audit rules:
- Quoted literal replacements are case-sensitive by default unless the user explicitly requests case-insensitive replacement or capitalization variants.
- Do not change capitalization variants unless requested by the user or explicitly declared in the manifest intent/user_visible_change.
- If changing capitalization variants, the manifest must say so.
- For quoted literal replacement requests, prefer one change block per actual occurrence so the manifest count is not confused with occurrence count.
- If one change block changes multiple occurrences in the same MATCH payload, the manifest intent/user_visible_change must state that multiple occurrences are changed.

Post-submit verification guidance:
- After an accepted literal replacement, verify the final target against the requested literal.
- Report the actual number of changed occurrences.
- Report whether capitalization variants were changed.
- Do not summarize manifest entry count as occurrence count.

Valid minimal PDCP example for this target:
{example}"""


def build_prompt_context(
    session: Session,
    *,
    target_file_id: uuid.UUID | str,
    user_request: str,
    context_policy: str = "relevant_spans",
) -> dict[str, Any]:
    if invalid_text_paths({"user_request": user_request, "context_policy": context_policy}):
        return {"status": "invalid_argument", "target_file_id": safe_input_text(target_file_id),
                "failure_detail": "Read inputs must be UTF-8 without NUL."}
    target_uuid = _try_coerce_uuid(target_file_id)
    if target_uuid is None:
        return {
            "status": "invalid_argument",
            "target_file_id": safe_input_text(target_file_id),
            "failure_detail": "target_file_id is not a valid UUID.",
        }
    target = session.get(CloudTargetFiles, target_uuid)
    if target is None:
        return {"status": "not_found", "target_file_id": safe_input_text(target_file_id)}

    return {
        "target_file_id": str(target.target_file_id),
        "target_type": target.target_type,
        "current_hash": target.current_hash,
        "version": target.version,
        "active_editing_cycle_id": str(target.active_editing_cycle_id),
        "manifest_summary": _active_manifest_summary(session, target),
        "target_context": _target_context(target.current_content, context_policy),
        "context_policy": context_policy,
        "target_chars": len(target.current_content),
        "context_truncated": len(_target_context(target.current_content, context_policy)) < len(target.current_content),
        "pdcp_rules": pdcp_rules_text(
            target_file_id=target.target_file_id,
            target_type=target.target_type,
            current_hash=target.current_hash,
            target_context=target.current_content,
        ),
        "user_request": user_request,
    }


def _active_manifest_summary(session: Session, target: CloudTargetFiles) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(AppendOnlyManifestLedger)
        .where(
            AppendOnlyManifestLedger.target_file_id == target.target_file_id,
            AppendOnlyManifestLedger.editing_cycle_id == target.active_editing_cycle_id,
        )
        .order_by(AppendOnlyManifestLedger.ledger_sequence)
    ).all()
    return [
        {
            "change_id": row.change_id,
            "intent": row.intent,
            "input_state": row.input_state,
            "output_state": row.output_state,
            "affected_region": row.affected_region,
            "user_visible_change": row.user_visible_change,
            "risk": row.risk,
            "origin": row.origin,
            "derived": row.derived_json,
        }
        for row in rows
    ]


def _target_context(content: str, context_policy: str) -> str:
    if context_policy == "full":
        return content
    # Convenience preview only: a bounded PREFIX, not relevance retrieval. Hosts that
    # need specific regions should use read_target / find_occurrences (authoritative
    # reads). `context_truncated` in build_prompt_context reports when this applies.
    return content[:4000]


def _try_coerce_uuid(value: uuid.UUID | str) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _minimal_pdcp_example(
    *,
    target_file_id: uuid.UUID | str | None,
    target_type: str | None,
    current_hash: str | None,
) -> str:
    header = [
        f"PDCP {SUPPORTED_PROTOCOL_VERSION}",
        f"target_file_id: {target_file_id or '<target_file_id>'}",
        f"target_type: {target_type or '<target_type>'}",
    ]
    if current_hash is not None:
        header.append(f"target_hash: {current_hash}")

    match_payload = "Original phrase."
    replace_payload = "Updated phrase."
    return "\n".join(
        [
            *header,
            "",
            "# MANIFEST",
            "# change_id: chg_001",
            "# intent: Describe the intended edit.",
            "# input_state: Describe the current text state.",
            "# output_state: Describe the desired text state.",
            "# affected_region: Describe the exact region being changed.",
            "# user_visible_change: Describe what the user will see changed.",
            "# risk: low",
            "",
            MATCH_DELIMITER,
            match_payload,
            SEPARATOR_DELIMITER,
            replace_payload,
            REPLACE_DELIMITER,
        ]
    )
