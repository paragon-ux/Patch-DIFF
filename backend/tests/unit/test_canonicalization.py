import pytest

from app.core.canonicalization import canonicalize_text


def test_lf_input_stays_unchanged() -> None:
    assert canonicalize_text("a\nb\n") == "a\nb\n"


def test_crlf_normalizes_to_lf() -> None:
    assert canonicalize_text("a\r\nb\r\n") == "a\nb\n"


def test_cr_normalizes_to_lf() -> None:
    assert canonicalize_text("a\rb\r") == "a\nb\n"


def test_mixed_line_endings_normalize_to_lf() -> None:
    assert canonicalize_text("a\r\nb\rc\n") == "a\nb\nc\n"


def test_tabs_spaces_and_trailing_spaces_are_preserved() -> None:
    assert canonicalize_text("\talpha  \n beta   ") == "\talpha  \n beta   "


def test_final_newline_is_preserved() -> None:
    assert canonicalize_text("alpha\n") == "alpha\n"


def test_missing_final_newline_stays_missing() -> None:
    assert canonicalize_text("alpha") == "alpha"


def test_no_unicode_normalization_is_applied() -> None:
    composed = "\u00e9"
    decomposed = "e\u0301"
    assert canonicalize_text(composed) != canonicalize_text(decomposed)


def test_bytes_input_must_be_valid_utf8() -> None:
    assert canonicalize_text("alpha\r\n".encode("utf-8")) == "alpha\n"
    with pytest.raises(UnicodeDecodeError):
        canonicalize_text(b"\xff")
