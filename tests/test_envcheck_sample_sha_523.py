# -*- coding: utf-8 -*-
"""#523 G3 / matrix3 P5: read_sample_sha256 only reports a GENUINE
recorded hash.

matrix3's apk-webview-attest-v2 died at C6-pre with ``no sample under
bins/`` — not because a sample hash was recorded, but because the
anchor prose itself contains the substring ``sha256`` (the success
criterion names ``sha256(seed||nonce)``) and the reader was a substring
line-scan. A workspace whose task_spec mentions sha256 in prose has
NOT recorded a sample hash; the bins/ probe must never fire on prose.

The genuine path must survive: a task_spec that records a real
64-hex sample hash still gets verified against bins/ (unchanged
strictness), and garbage values never masquerade as hashes.
"""

import env_check  # pytest.ini pythonpath = . hooks scripts tools


def _write_spec(ws, text):
    spec = ws / "task_spec.yaml"
    spec.parent.mkdir(parents=True, exist_ok=True)
    spec.write_text(text, encoding="utf-8")
    return ws


# the awa shape verbatim in structure: anchors quoting an algorithm
# name that contains "sha256", plus a colon later in the line (the
# two conditions the old line-scan keyed on)
AWA_PROSE = """\
task_id: apk-webview-attest-v2
primary_questions:
  - q: "Defeat the two-layer attestation"
goal_verbatim: |
  then the native check (sha256(seed||nonce)[:8] ^ NATIVE_MASK) accepted,
  retrieving the final payload
success_criterion: "4/4 fresh sessions: seed then native check"
"""

GENUINE = """\
task_id: real-target
sample_sha256: "%s"
"""


def test_anchor_prose_mentioning_sha256_is_not_a_sample_hash(tmp_path):
    ws = _write_spec(tmp_path / "ws", AWA_PROSE)
    assert env_check.read_sample_sha256(ws) is None


def test_genuine_recorded_hex_is_reported(tmp_path):
    h = "a" * 64
    ws = _write_spec(tmp_path / "ws", GENUINE % h)
    assert env_check.read_sample_sha256(ws) == h


def test_non_hex_value_is_not_a_hash(tmp_path):
    ws = _write_spec(tmp_path / "ws", GENUINE % "not-a-hash")
    assert env_check.read_sample_sha256(ws) is None


def test_unparseable_spec_degrades_to_none(tmp_path):
    ws = _write_spec(tmp_path / "ws", "\tbroken: [yaml :: {\n")
    assert env_check.read_sample_sha256(ws) is None


def test_missing_spec_is_none(tmp_path):
    assert env_check.read_sample_sha256(tmp_path / "nope") is None
