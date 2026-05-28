from app.pdcp.matcher import MatchSpan, find_exact_occurrences


def test_exact_single_match_succeeds() -> None:
    assert find_exact_occurrences("alpha beta gamma", "beta") == (MatchSpan(6, 10),)


def test_zero_match_returns_empty_tuple() -> None:
    assert find_exact_occurrences("alpha", "beta") == ()


def test_duplicate_matches_return_left_to_right_non_overlapping_spans() -> None:
    assert find_exact_occurrences("one one one", "one") == (
        MatchSpan(0, 3),
        MatchSpan(4, 7),
        MatchSpan(8, 11),
    )


def test_case_mismatch_does_not_match() -> None:
    assert find_exact_occurrences("Alpha", "alpha") == ()


def test_whitespace_mismatch_does_not_match() -> None:
    assert find_exact_occurrences("alpha  beta", "alpha beta") == ()


def test_multiline_match_succeeds() -> None:
    assert find_exact_occurrences("a\nb\nc", "a\nb") == (MatchSpan(0, 3),)


def test_crlf_canonicalization_supports_matching() -> None:
    assert find_exact_occurrences("a\r\nb\r\nc", "a\nb") == (MatchSpan(0, 3),)


def test_unicode_equivalent_codepoint_different_strings_do_not_match() -> None:
    assert find_exact_occurrences("\u00e9", "e\u0301") == ()
