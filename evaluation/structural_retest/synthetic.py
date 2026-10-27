"""Deterministic non-model host for infrastructure tests ONLY; never a study result."""
from __future__ import annotations

import copy
import uuid

from evaluation.structural_retest.host_adapter import CAPABILITIES, INTERFACE_VERSION, SEMANTICS, TOOLS


def description() -> dict:
    common = {"provider": "SYNTHETIC-NO-PROVIDER", "exact_provider_model_id": "SYNTHETIC-NO-MODEL",
              "effective_reasoning_setting": "High", "host_name": "deterministic-test-host", "host_version": "1",
              "decoding_settings": {}, "context_limit": 100000, "output_limit": 16000,
              "model_configuration_timestamp": "2026-01-01T00:00:00+00:00",
              "capabilities": sorted(CAPABILITIES), "tool_semantics": SEMANTICS,
              "usage_contract": {"input_includes_cached": True, "output_includes_reasoning": True,
                                 "actual_input_output": True, "hard_total_limit": True},
              "permission_evidence": {"enforced": True, "probe_sha256": "0" * 64},
              "provider_evidence": {"source": "synthetic-fixture", "verified": True, "response_sha256": "0" * 64,
                                    "model_id": "SYNTHETIC-NO-MODEL", "reasoning": "High",
                                    "requested_model_verified": "Gemini 3.8 Flash High"}}
    return {"interface_version": INTERFACE_VERSION, "synthetic": True,
            "arms": {arm: {**copy.deepcopy(common), "tool_permissions": sorted(TOOLS[arm])} for arm in "ABC"}}


class SyntheticHost:
    synthetic = True

    def __init__(self, scripts=None, host_description=None):
        self.scripts = scripts or {}
        self.info = host_description or description()
        self.contexts = {}
        self.turns = {}
        self.live_model_invocations = 0

    async def describe(self):
        return copy.deepcopy(self.info)

    async def open_context(self, specification):
        context_id = str(uuid.uuid4())
        self.contexts[context_id] = specification
        self.turns[context_id] = iter(self.scripts.get(specification["arm"], []))
        return context_id

    async def turn(self, context_id, tool_results, limits):
        spec = self.contexts[context_id]
        response = next(self.turns[context_id], {"finished": True, "tool_calls": []})
        if callable(response):
            response = response(spec, tool_results)
        return {"provider": "SYNTHETIC-NO-PROVIDER", "model_id": "SYNTHETIC-NO-MODEL", "reasoning": "High",
                "provider_request_id": str(uuid.uuid4()), "usage": {"input_tokens": 1, "output_tokens": 1,
                "cached_tokens": 0, "reasoning_tokens": 0}, "synthetic": True, **response}

    async def close_context(self, context_id):
        pass
