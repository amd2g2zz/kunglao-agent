# -*- coding: utf-8 -*-
"""rlvr.constants_ref — the reference hash constant tables (entropy
reduction operators: mechanical constant-set diff).

Why this module exists: the crypto search path could not separate a
REFERENCE hash implementation from a MUTATED variant mechanically —
``tools/crypto/algorithms.py`` holds stream ciphers / compression /
envelope code but no hash IVs or round constants, so every
md5-vs-mutated-md5 judgement was prose. This table makes the diff a
set operation.

Provenance of every word: the public standard definitions (MD5 RFC
1321; SHA-1 FIPS 180-4; SHA-256 FIPS 180-4; SM3 GB/T 32905-2016),
GENERATED from their closed-form definitions where the standard gives
one (sine table, prime-root fractions) or pinned to the prescribed
literals where it does not (SM3's two T constants), and CROSS-CHECKED
against full pure-python re-implementations whose digests matched
``hashlib`` on empty / abc / multi-block vectors — the
re-implementations and closed-form checks SHIP with the suite
(tests/test_constants_ref_693.py), so every table word stays
mechanically pinned. ``classify`` is therefore trusted to be exact,
not heuristic.

Faces:
  - ``REFERENCE_TABLES`` / ``reference_words(family)`` — the closed
    family vocabulary and each family's IV + round-constant word list
    (big-endian numeric form, the shape a constant scan produces).
  - ``classify(observed)`` — mechanical diff: which reference family
    the observed word set matches, exact-vs-mutated, and the
    missing/extra word lists (sorted, deterministic). A mutated table
    still IDENTIFIES as its family (max matched words) while
    ``exact`` separates it from the reference.

Fail posture: an empty observed set classifies as no-family (never a
claim); an unknown family name raises (producer error, not data).
"""
from __future__ import annotations

# --- MD5 (RFC 1321): IV + the sine-derived T table ---------------------

MD5_IV = (
    0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476,
)
MD5_T = (
    0xD76AA478, 0xE8C7B756, 0x242070DB, 0xC1BDCEEE,
    0xF57C0FAF, 0x4787C62A, 0xA8304613, 0xFD469501,
    0x698098D8, 0x8B44F7AF, 0xFFFF5BB1, 0x895CD7BE,
    0x6B901122, 0xFD987193, 0xA679438E, 0x49B40821,
    0xF61E2562, 0xC040B340, 0x265E5A51, 0xE9B6C7AA,
    0xD62F105D, 0x02441453, 0xD8A1E681, 0xE7D3FBC8,
    0x21E1CDE6, 0xC33707D6, 0xF4D50D87, 0x455A14ED,
    0xA9E3E905, 0xFCEFA3F8, 0x676F02D9, 0x8D2A4C8A,
    0xFFFA3942, 0x8771F681, 0x6D9D6122, 0xFDE5380C,
    0xA4BEEA44, 0x4BDECFA9, 0xF6BB4B60, 0xBEBFBC70,
    0x289B7EC6, 0xEAA127FA, 0xD4EF3085, 0x04881D05,
    0xD9D4D039, 0xE6DB99E5, 0x1FA27CF8, 0xC4AC5665,
    0xF4292244, 0x432AFF97, 0xAB9423A7, 0xFC93A039,
    0x655B59C3, 0x8F0CCC92, 0xFFEFF47D, 0x85845DD1,
    0x6FA87E4F, 0xFE2CE6E0, 0xA3014314, 0x4E0811A1,
    0xF7537E82, 0xBD3AF235, 0x2AD7D2BB, 0xEB86D391,
)

# --- SHA-1 (FIPS 180-4): the FIVE IV registers + four round constants --

SHA1_IV = (
    0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0,
)
SHA1_K = (
    0x5A827999, 0x6ED9EBA1, 0x8F1BBCDC, 0xCA62C1D6,
)

# --- SHA-256 (FIPS 180-4): IV + 64 round constants --------------------

SHA256_IV = (
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
)
SHA256_K = (
    0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5,
    0x3956C25B, 0x59F111F1, 0x923F82A4, 0xAB1C5ED5,
    0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3,
    0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174,
    0xE49B69C1, 0xEFBE4786, 0x0FC19DC6, 0x240CA1CC,
    0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA,
    0x983E5152, 0xA831C66D, 0xB00327C8, 0xBF597FC7,
    0xC6E00BF3, 0xD5A79147, 0x06CA6351, 0x14292967,
    0x27B70A85, 0x2E1B2138, 0x4D2C6DFC, 0x53380D13,
    0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85,
    0xA2BFE8A1, 0xA81A664B, 0xC24B8B70, 0xC76C51A3,
    0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070,
    0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5,
    0x391C0CB3, 0x4ED8AA4A, 0x5B9CCA4F, 0x682E6FF3,
    0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208,
    0x90BEFFFA, 0xA4506CEB, 0xBEF9A3F7, 0xC67178F2,
)

# --- SM3 (GB/T 32905-2016): IV + two round constants ------------------
# T_j is 0x79CC4519 for rounds 0-15 and 0x7A879D8A for rounds 16-63;
# those two words plus the 8 IV words are the COMPLETE constant set of
# the digest compression function (there is no further round-constant
# table — CK is SM4's, a different standard, and does not belong here).

SM3_IV = (
    0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600,
    0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E,
)
SM3_T = (
    0x79CC4519, 0x7A879D8A,
)

# --- the closed family vocabulary + the diff face ----------------------

REFERENCE_TABLES: dict[str, tuple[int, ...]] = {
    "md5": MD5_IV + MD5_T,
    "sha1": SHA1_IV + SHA1_K,
    "sha256": SHA256_IV + SHA256_K,
    "sm3": SM3_IV + SM3_T,
}

FAMILIES: tuple[str, ...] = tuple(sorted(REFERENCE_TABLES))


def reference_words(family: str) -> list[int]:
    """The family's IV + round-constant words, in declaration order.

    The single read face for the search path — constant scans, the
    invariant table, and the diff all consume THIS, never the raw
    tuples (one import point, drift-proof)."""
    try:
        return list(REFERENCE_TABLES[family])
    except KeyError:
        raise ValueError(
            f"unknown hash family {family!r}; known: {', '.join(FAMILIES)}"
        ) from None


def classify(observed: set[int]) -> dict:
    """Mechanical constant-set diff against every reference table.

    Returns {family, exact, missing, extra}:
      - ``family`` — the table with the MOST matched words (ties break
        alphabetically; zero matches anywhere -> None: an observed set
        that matches no reference never claims a family);
      - ``exact`` — True only when the observed set IS the reference
        table as a set (no missing, no extra words): a mutated variant
        may still IDENTIFY as its family while failing ``exact`` —
        that separation is the whole point;
      - ``missing`` / ``extra`` — sorted word lists (deterministic
        receipts); both empty exactly when ``exact``.

    An empty observed set classifies as no-family with empty diffs."""
    obs = {int(w) for w in observed}
    best_family: str | None = None
    best_matched = 0
    for name in FAMILIES:
        ref = set(REFERENCE_TABLES[name])
        matched = len(ref & obs)
        if matched > best_matched:
            best_matched = matched
            best_family = name
    if best_family is None:
        return {"family": None, "exact": False, "missing": [], "extra": []}
    ref = set(REFERENCE_TABLES[best_family])
    missing = sorted(ref - obs)
    extra = sorted(obs - ref)
    return {
        "family": best_family,
        "exact": not missing and not extra,
        "missing": missing,
        "extra": extra,
    }
