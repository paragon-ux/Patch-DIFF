"""Deterministic bounded supplementary diagnostic policies."""
import json
import sys

import pytest

from app.core.diagnostics import exact_candidates, near_miss_query
from app.core.result import FailureBufferContext
from app.pdcp.matcher import find_exact_occurrences
from app.services import near_miss_service
from app.services.near_miss_service import near_misses
from app.services.rejection_context import available_context, bound_candidates, context_identity


def diagnostic(buffer, query):
    return {"failure_context": available_context(FailureBufferContext.capture(buffer), observed_target_version=0,
                                                 observed_target_hash="f" * 64),
            "near_miss_query": near_miss_query(query)}


@pytest.mark.parametrize("buffer,query,found", [
    ("foo  bar", "foo bar", True), ("alphb alphc", "alpha", True),
    ("\U0001f642x", "\U0001f642y", True), ("zzzzzz", "alpha", False), ("", "alpha", False),
    ("z" * 256 + "alpha", "alphx", False),
])
def test_near_miss_whitespace_unicode_none_and_distant_prefix(buffer, query, found):
    inputs = diagnostic(buffer, query)
    result = near_misses(inputs, caller_owned=False)
    assert result["status"] == "computed" and bool(result["candidates"]) is found
    assert all(item["distance"] > 0 for item in result["candidates"])
    assert result == near_misses(inputs, caller_owned=False)
    order = [(item["distance"], item["start"], item["end"]) for item in result["candidates"]]
    assert order == sorted(order)
    assert result["returned_count"] <= 3
    assert all(item["text"] == buffer[item["start"]:item["end"]] for item in result["candidates"])
    assert len(json.dumps({"near_misses": result}, ensure_ascii=True, separators=(",", ":")).encode("ascii")) <= 8192


def test_near_miss_ties_sort_by_position_and_end():
    result = near_misses(diagnostic("cat bat hat", "mat"), caller_owned=False)
    assert [(item["start"], item["end"]) for item in result["candidates"]] == [(0, 3), (1, 3), (4, 7)]


def test_near_miss_omissions_are_explicit_and_no_partial_rank_on_exhaustion(monkeypatch):
    assert near_misses(diagnostic("alpha", "a" * 65), caller_owned=False)["omission_reason"] == "match_too_large"
    assert near_misses({}, caller_owned=False)["omission_reason"] == "historical_context_unavailable"
    monkeypatch.setattr(near_miss_service, "MAX_COMPARISON_CELLS", 0)
    result = near_misses(diagnostic("alphb", "alpha"), caller_owned=False)
    assert result["omission_reason"] == "work_budget_exhausted" and result["candidates"] == []
    result = near_misses(diagnostic("alphb", "alpha"), caller_owned=True)
    assert result["omission_reason"] == "caller_transaction"


def test_exact_overlap_candidates_and_actual_worst_case_json_caps():
    buffer = "\U0001f642" * 500
    spans = find_exact_occurrences(buffer, "\U0001f642" * 64)
    value = exact_candidates(buffer, spans)
    context = available_context(FailureBufferContext(buffer[:256], sys.maxsize, sys.maxsize),
                                observed_target_version=-(2**63), observed_target_hash="\U0001f642" * 64)
    value.update(context_identity(context))
    value = bound_candidates("exact_candidates", value)
    assert value["truncated"] is True and value["occurrence_count"] == 437
    assert value["returned_count"] <= 5
    assert [item["occurrence_index"] for item in value["candidates"]] == list(range(1, value["returned_count"]+1))
    assert all(len(item["match_preview"]) <= 64 and len(item["before"]) <= 20 and len(item["after"]) <= 20
               for item in value["candidates"])
    assert len(json.dumps({"exact_candidates": value}, ensure_ascii=True, separators=(",", ":")).encode("ascii")) <= 8192
    enrichment = {"failure_context": context, "current_context": context, "exact_candidates": value,
                  "correlation_id": "f" * 36}
    assert len(json.dumps(enrichment, ensure_ascii=True, separators=(",", ":")).encode("ascii")) <= 18432


def test_real_work_limit_omits_incomplete_ranking():
    result = near_misses(diagnostic("b" * 256, "a" * 64), caller_owned=False)
    assert result["status"] == "omitted" and result["omission_reason"] == "work_budget_exhausted"
    assert result["candidates"] == []
