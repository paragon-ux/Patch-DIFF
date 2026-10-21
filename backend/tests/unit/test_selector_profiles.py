"""Selectors constrain every current match; recorded runtimes retain old behavior."""

import pytest

from app.core.failures import FailureReason
from app.core.result import AcceptedCoreResult, RejectedCoreResult
from app.core.versions import (
    LEGACY_RUNTIME_VERSION, PREVIOUS_RUNTIME_VERSION,
    PRE_SELECTOR_RUNTIME_VERSION, RUNTIME_VERSION,
    UnsupportedRuntimeVersionError, resolve_runtime_profile,
)
from app.pdcp.applier import apply_pdcp_transaction
from app.pdcp.disambiguation import resolve_match_span
from app.pdcp.parser import parse_pdcp
from app.pdcp.protocol_validator import validate_pdcp
from app.pdcp.typed import parse_typed_record, to_parsed_transaction
from backend.tests.unit.test_typed_transaction import pdcp_text, record

# Expected selected spans are independent, explicit offsets into each buffer.
BUFFERS = ["L yy R", "L xx R", "L xx M xx R", "L xxx R"]
A = FailureReason.MATCH_ABSENT
M = FailureReason.MATCH_AMBIGUOUS
I = FailureReason.DISAMBIGUATION_INVALID
CASES = [
    ({}, [A, (2, 4), M, M]),
    ({"occurrence_index": "1"}, [A, (2, 4), (2, 4), (2, 4)]),
    ({"occurrence_index": "2"}, [A, I, (7, 9), (3, 5)]),
    ({"occurrence_index": "4"}, [A, I, I, I]),
    ({"anchor_before": "L"}, [A, (2, 4), I, I]),
    ({"anchor_before": "M"}, [A, I, (7, 9), I]),
    ({"anchor_before": "missing"}, [A, I, I, I]),
    ({"anchor_after": "R"}, [A, (2, 4), I, I]),
    ({"anchor_after": "M"}, [A, I, (2, 4), I]),
    ({"anchor_after": "missing"}, [A, I, I, I]),
    ({"occurrence_index": "1", "anchor_before": "M"}, [A, I, I, I]),
    ({"occurrence_index": "2", "anchor_after": "M"}, [A, I, I, I]),
    ({"occurrence_index": "1", "anchor_before": "L", "anchor_after": "R"},
     [A, (2, 4), (2, 4), (2, 4)]),
]


@pytest.mark.parametrize("format_", ["typed", "legacy"])
@pytest.mark.parametrize("sequential", [False, True])
@pytest.mark.parametrize("buffer_index", range(len(BUFFERS)),
                         ids=["absent", "singleton", "multiple", "overlap"])
@pytest.mark.parametrize("selectors,expected", CASES)
def test_selector_constraint_matrix(format_, sequential, buffer_index, selectors, expected):
    target = BUFFERS[buffer_index]
    changes = [("xx", "Z", selectors)]
    initial = target
    if sequential:
        initial = "seed"
        changes.insert(0, ("seed", target, None))
    if format_ == "typed":
        edits = [
            {"match": match, "replace": replace, **{
                key: int(value) if key == "occurrence_index" else value
                for key, value in (selection or {}).items()
            }}
            for match, replace, selection in changes
        ]
        parsed = to_parsed_transaction(parse_typed_record(record(edits)), target_type="text/plain")
    else:
        parsed = parse_pdcp(pdcp_text(*changes))
        validate_pdcp(parsed)
    result = apply_pdcp_transaction(initial, parsed)
    wanted = expected[buffer_index]
    if isinstance(wanted, tuple):
        assert isinstance(result, AcceptedCoreResult)
        fact = result.change_facts[-1]
        assert (fact["span_start"], fact["span_end"]) == wanted
        start, end = wanted
        assert result.target_content == target[:start] + "Z" + target[end:]
    else:
        assert isinstance(result, RejectedCoreResult)
        assert result.failure_reason is wanted
        assert result.after_hash is None
        assert result.failed_change_id == f"chg_{len(changes):03d}"


@pytest.mark.parametrize("runtime", [
    LEGACY_RUNTIME_VERSION, PREVIOUS_RUNTIME_VERSION, PRE_SELECTOR_RUNTIME_VERSION,
])
@pytest.mark.parametrize("selectors", [
    {"occurrence_index": "2"}, {"anchor_before": "missing"}, {"anchor_after": "missing"},
    {"occurrence_index": "1", "anchor_before": "missing", "anchor_after": "missing"},
])
def test_old_profiles_preserve_ignored_singleton_selectors(runtime, selectors):
    profile = resolve_runtime_profile(runtime)
    span = resolve_match_span("hello", "hello", selectors,
                              overlapping=profile.overlapping_matches,
                              enforce_singleton_selectors=profile.enforce_singleton_selectors)
    assert (span.start, span.end) == (0, 5)


def test_profile_semantics_are_distinct_and_unknown_profiles_fail_closed():
    assert resolve_runtime_profile(RUNTIME_VERSION).enforce_singleton_selectors is True
    for runtime in (LEGACY_RUNTIME_VERSION, PREVIOUS_RUNTIME_VERSION, PRE_SELECTOR_RUNTIME_VERSION):
        assert resolve_runtime_profile(runtime).enforce_singleton_selectors is False
    assert resolve_runtime_profile(LEGACY_RUNTIME_VERSION).overlapping_matches is False
    assert resolve_runtime_profile(PRE_SELECTOR_RUNTIME_VERSION).overlapping_matches is True
    for runtime in (None, "unknown"):
        with pytest.raises(UnsupportedRuntimeVersionError):
            resolve_runtime_profile(runtime)


def test_advisory_region_hint_still_allows_a_singleton():
    assert resolve_match_span("hello", "hello", {"region_hint": "advisory"}).start == 0
