"""Fail-closed host attestation, frozen inputs and external Gate 2 evidence."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from urllib.request import Request, urlopen

from evaluation.structural_retest.host_adapter import CAPABILITIES, HOST_FIELDS, INTERFACE_VERSION, SEMANTICS, TOOLS
from evaluation.structural_retest.telemetry import digest


def validate_host(description: dict, *, synthetic=False) -> list[str]:
    errors = []
    if description.get("interface_version") != INTERFACE_VERSION:
        errors.append("host interface version")
    if description.get("synthetic") is not synthetic:
        errors.append("synthetic/live evidence mismatch")
    arms = description.get("arms", {})
    for arm in "ABC":
        info = arms.get(arm, {})
        for key in HOST_FIELDS:
            if info.get(key) is None or info.get(key) == "" or info.get(key) == "inherit":
                errors.append(f"{arm}: unresolved {key}")
        proof = info.get("provider_evidence", {})
        if not proof.get("response_sha256") or not proof.get("source") or proof.get("verified") is not True:
            errors.append(f"{arm}: unverified provider evidence")
        if proof.get("model_id") != info.get("exact_provider_model_id") or proof.get("reasoning") != info.get("effective_reasoning_setting"):
            errors.append(f"{arm}: provider identity/setting mismatch")
        if proof.get("requested_model_verified") != "Gemini 3.8 Flash High" or info.get("effective_reasoning_setting") != "High":
            errors.append(f"{arm}: requested Gemini/High not verified")
        if not synthetic:
            for label, value in (("provider response", proof.get("response_sha256")),
                                 ("permission probe", info.get("permission_evidence", {}).get("probe_sha256")),
                                 ("host build", info.get("host_build_sha256")),
                                 ("decoding evidence", info.get("decoding_evidence_sha256"))):
                if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                    errors.append(f"{arm}: missing {label} SHA-256")
            if arm != "A" and not re.fullmatch(r"[0-9a-f]{64}", info.get("mcp_schema_sha256") or ""):
                errors.append(f"{arm}: missing real MCP schema binding")
            if arm == "A":
                binding = info.get("native_binding") or {}
                if not binding.get("executable_path") or not binding.get("version_output") or not re.fullmatch(r"[0-9a-f]{64}", binding.get("sha256") or ""):
                    errors.append("A: missing verified native executable binding")
        if set(info.get("tool_permissions", [])) != TOOLS[arm]:
            errors.append(f"{arm}: tool permissions")
        if not CAPABILITIES <= set(info.get("capabilities", [])) or info.get("tool_semantics") != SEMANTICS:
            errors.append(f"{arm}: missing host isolation/usage/tool capabilities")
        if info.get("permission_evidence", {}).get("enforced") is not True or not info.get("permission_evidence", {}).get("probe_sha256"):
            errors.append(f"{arm}: underlying host permissions unverified")
        if info.get("usage_contract") != {"input_includes_cached": True, "output_includes_reasoning": True,
                                           "actual_input_output": True, "hard_total_limit": True}:
            errors.append(f"{arm}: insufficient actual usage/token enforcement")
        if type(info.get("context_limit")) is not int or info.get("context_limit", 0) <= 0 or type(info.get("output_limit")) is not int or info.get("output_limit", 0) <= 0:
            errors.append(f"{arm}: invalid model limits")
        try:
            date = datetime.fromisoformat(info["model_configuration_timestamp"])
            if date.tzinfo is None or date > datetime.now(timezone.utc):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            errors.append(f"{arm}: invalid configuration timestamp")
    parity = ("provider", "exact_provider_model_id", "effective_reasoning_setting", "host_name", "host_version",
              "decoding_settings", "context_limit", "output_limit", "usage_contract")
    for key in parity:
        if len({digest(arms.get(a, {}).get(key)) for a in "ABC"}) != 1:
            errors.append(f"A/B/C configuration mismatch: {key}")
    return errors


def github_review(url: str) -> dict:
    match = re.fullmatch(r"https://github\.com/paragon-ux/Patch-DIFF/pull/16#pullrequestreview-(\d+)", url)
    if not match:
        raise ValueError("Approval must be a PR #16 GitHub review permalink")
    request = Request("https://api.github.com/repos/paragon-ux/Patch-DIFF/pulls/16/reviews/" + match[1],
                      headers={"Accept": "application/vnd.github+json", "User-Agent": "PatchDIFF-Gate2"})
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def validate_approval(receipt: dict, commit: str, manifest_sha256: str, host_sha256: str, resolver=github_review):
    """A local 'approved' flag is never authority. Resolve the external review afresh.

    The independent reviewer writes one JSON fenced block with the exact binding
    below. This does not authenticate a reviewer's expertise; the owner selects
    the independent reviewer and remains responsible for that authorization.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Exact reviewed commit required")
    review = resolver(receipt.get("review_url", ""))
    blocks = re.findall(r"```json\s*\n(.*?)\n```", review.get("body", ""), re.S)
    bindings = [json.loads(block) for block in blocks]
    wanted = {"gate": "Gate 2", "decision": "approved", "study_id": "primary-original-21-five-file-v1",
              "commit": commit, "manifest_sha256": manifest_sha256, "host_evidence_sha256": host_sha256,
              "independent_review": True, "live_execution_authorized": True}
    if (wanted not in bindings or review.get("commit_id") != commit or review.get("state") not in {"APPROVED", "COMMENTED"}
            or not review.get("submitted_at") or not review.get("user", {}).get("login")):
        raise ValueError("Missing/mismatched external Gate 2 approval")
    if receipt.get("review_sha256") != digest(review):
        raise ValueError("Approval evidence does not match retrieved review")
    return {"review_url": receipt["review_url"], "review_sha256": digest(review),
            "reviewer": review["user"]["login"], "binding": wanted}
