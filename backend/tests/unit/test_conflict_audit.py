"""The conflict row is unkeyed; only its response echoes the caller's key."""

import uuid
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from app.core.failures import FailureReason
from app.core.hashing import canonical_sha256
from app.core.validity import ValidationStage
from app.services import pdcp_service


@pytest.mark.parametrize("length", [8, 256, 257, 512])
def test_persisted_legacy_key_preview_is_bounded_without_changing_the_response(monkeypatch, length):
    target_id, original_id, conflict_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    key = "k" * length
    target = SimpleNamespace(target_file_id=target_id, current_hash=canonical_sha256("alpha"),
                             current_content="alpha", version=1)
    existing = SimpleNamespace(client_request_id=key, request_fingerprint="0" * 64,
                               pdcp_log_id=original_id, diagnostic_json={})

    class FakeSession:
        identity_map = {}
        no_autoflush = nullcontext()
        def identity_key(self, *args):
            return args
        def execute(self, statement):
            return SimpleNamespace(scalar_one_or_none=lambda: target)
        def scalar(self, statement):
            return existing

    captured = {}
    def persist(session, **kwargs):
        captured.update(kwargs)
        return pdcp_service.SubmitPDCPResult(
            status="rejected", target_file_id=target_id, pdcp_log_id=conflict_id,
            before_hash=target.current_hash, after_hash=None, before_version=1, after_version=None,
            current_hash=target.current_hash, current_version=1,
            failure_reason=kwargs["rejection"].failure_reason,
            diagnostic=kwargs["rejection"].diagnostic, validation_stage=kwargs["stage"],
        )

    monkeypatch.setattr(pdcp_service, "_transaction", lambda session: nullcontext())
    monkeypatch.setattr(pdcp_service, "_resolve_parent_log", lambda *args: (None, None))
    monkeypatch.setattr(pdcp_service, "_upsert_current_pdcp", lambda *args, **kwargs: kwargs)
    monkeypatch.setattr(pdcp_service, "_persist_rejection", persist)
    response = pdcp_service.submit_edits(
        FakeSession(), target_file_id=target_id, intent="Different proposal",
        edits=[{"match": "alpha", "replace": "beta"}], expected_target_version=0,
        client_request_id=key)
    assert response.client_request_id == key and response.pdcp_log_id == conflict_id
    assert captured["client_request_id"] is None
    assert captured["request_fingerprint"] != existing.request_fingerprint
    assert response.diagnostic["submitted_client_request_id"] == key[:256]
    assert response.diagnostic["submitted_client_request_id_truncated"] is (length > 256)
    assert response.diagnostic["existing_pdcp_log_id"] == str(original_id)
    assert response.validation_stage is ValidationStage.PRECONDITION_GUARD
    assert response.failure_reason is FailureReason.CONTEXT_INVALID
