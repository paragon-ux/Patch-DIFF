import hashlib

from app.core.hashing import canonical_sha256


def test_hash_helper_hashes_canonicalized_text() -> None:
    expected = hashlib.sha256("alpha\n".encode("utf-8")).hexdigest()
    assert canonical_sha256("alpha\r\n") == expected


def test_crlf_and_lf_variants_hash_the_same() -> None:
    assert canonical_sha256("a\r\nb\r\n") == canonical_sha256("a\nb\n")


def test_unicode_equivalent_codepoint_different_strings_hash_differently() -> None:
    assert canonical_sha256("\u00e9") != canonical_sha256("e\u0301")


def test_hash_is_lowercase_hex_sha256() -> None:
    digest = canonical_sha256("PatchDIFF")
    assert len(digest) == 64
    assert digest == digest.lower()
    int(digest, 16)
