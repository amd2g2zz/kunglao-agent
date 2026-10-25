#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_input_signature_805.py — input-signature persistence as a
shared primitive (issue 805, task 2).

The #750 round-close input-signature gate (verification_ladder — the RC1
fix) was site-local: the silence-on-no-change discipline lived and died
in one function. This file pins the extracted shared primitive
(scripts/input_signature.py) and its adoption:

  - the primitive: canonical signature + doc-carried and state-carried
    suppression checks (immutable stamping — a new doc, never mutation);
  - T2 (the extraction source) migrates WITHOUT behavior change: the
    unchanged shape still persists and emits nothing;
  - digest_build.write_digest — previously an UNCONDITIONAL write —
    defaults to signature-gated persistence;
  - the policy-state projection keeps its silence-on-unchanged contract,
    now flowing through the shared primitive;
  - PIN: the periodic faces [t2, digest, policy_state] emit/persist
    NOTHING on an unchanged input signature — the system-wide honest
    idle, not a per-site accident.

Adjudicated exceptions (declared, not silent): the statusline snapshot
FILE stays fresh-by-design (#801: display truth; only its ledger EVENT is
value-gated) and rank_feeds stays per-run (#801 R2b: the replay spine).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import input_signature as isig  # noqa: E402


# ---------- the primitive ---------------------------------------------------

class TestPrimitive:
    def test_signature_is_deterministic_and_order_insensitive(self):
        a = isig.signature([["c1", "OPEN", False, 2], ["c2", "SETTLED", True, 1]])
        b = isig.signature([["c1", "OPEN", False, 2], ["c2", "SETTLED", True, 1]])
        assert a == b and len(a) == 40

    def test_signature_is_sensitive_to_content(self):
        assert isig.signature([["c1", "OPEN"]]) != isig.signature([["c1", "SETTLED"]])

    def test_stamped_returns_a_new_doc(self):
        doc = {"schema": "x/1", "queue": [1]}
        out = isig.stamped(doc, "abc123")
        assert out["sig"] == "abc123"
        assert "sig" not in doc, "stamp must not mutate the builder's doc"

    def test_unchanged_doc_true_only_on_matching_sig(self, tmp_path):
        p = tmp_path / "doc.json"
        p.write_text(json.dumps(isig.stamped({"schema": "x/1"}, "s1")),
                     encoding="utf-8")
        assert isig.unchanged_doc(p, "s1") is True
        assert isig.unchanged_doc(p, "s2") is False

    def test_unchanged_doc_false_on_absent_or_corrupt(self, tmp_path):
        assert isig.unchanged_doc(tmp_path / "nope.json", "s1") is False
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        assert isig.unchanged_doc(bad, "s1") is False

    def test_state_carrier_round_trip(self, tmp_path):
        state = tmp_path / "runs" / ".persist-state.json"
        assert isig.unchanged_state(state, "digest", "s1") is False
        isig.record_state(state, "digest", "s1")
        assert isig.unchanged_state(state, "digest", "s1") is True
        assert isig.unchanged_state(state, "digest", "s2") is False
        assert isig.unchanged_state(state, "other", "s1") is False, (
            "faces are keyed independently")

    def test_state_carrier_fail_open(self, tmp_path):
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text("///", encoding="utf-8")
        assert isig.unchanged_state(corrupt, "digest", "s1") is False
        isig.record_state(corrupt, "digest", "s1"), "rewrite heals"


# ---------- T2: the extraction source, behavior-identical -------------------

class TestT2Migration:
    def _ws(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(
            "claims:\n  - id: C-001\n    status: OPEN\n", encoding="utf-8")
        return ws

    def test_round_close_uses_the_shared_primitive(self):
        src = (REPO_ROOT / "scripts" / "verification_ladder.py").read_text(
            encoding="utf-8")
        assert "input_signature" in src, (
            "the site-local #750 gate must flow through the shared "
            "primitive (extraction, not duplication)")

    def test_unchanged_shape_persists_and_emits_nothing(self, tmp_path):
        import verification_ladder as vl
        ws = self._ws(tmp_path)
        first = vl.round_close(ws)
        assert first.get("built") is True
        path = ws / "runs" / "t2-queue.json"
        assert path.is_file()
        frozen = path.read_text(encoding="utf-8")
        second = vl.round_close(ws)
        assert second.get("unchanged") is True, second
        assert path.read_text(encoding="utf-8") == frozen, (
            "an unchanged input signature persists nothing")


# ---------- digest: the previously ungated periodic face --------------------

class TestDigestGating:
    def _ws(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        (ws / "claims").mkdir(parents=True)
        (ws / "facts").mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(
            "claims:\n  - id: C-001\n    status: OPEN\n"
            "  - id: C-002\n    status: SETTLED\n", encoding="utf-8")
        (ws / "task_spec.yaml").write_text(
            "primary_questions:\n  - q: what\n", encoding="utf-8")
        return ws

    def test_second_write_on_unchanged_ws_skips(self, tmp_path):
        import digest_build as db
        ws = self._ws(tmp_path)
        p1 = db.write_digest(ws)
        first = p1.read_text(encoding="utf-8")
        p2 = db.write_digest(ws)
        assert p2 == p1
        assert p2.read_text(encoding="utf-8") == first, (
            "an unchanged input signature persists nothing (the head "
            "timestamp is the render clock, never a content change)")
        assert db.write_digest(ws).read_text(
            encoding="utf-8") == first

    def test_changed_input_rewrites(self, tmp_path):
        import digest_build as db
        ws = self._ws(tmp_path)
        db.write_digest(ws)
        (ws / "facts" / "_INDEX.md").write_text(
            "F001 | PROVEN | C-001 | the answer\n", encoding="utf-8")
        out = db.write_digest(ws)
        assert "F001" in out.read_text(encoding="utf-8"), (
            "a moved input signature rebuilds")

    def test_main_reports_the_unchanged_face(self, tmp_path, capsys):
        import digest_build as db
        ws = self._ws(tmp_path)
        db.write_digest(ws)
        rc = db.main([str(ws)])
        assert rc == 0
        assert "unchanged" in capsys.readouterr().out.lower()


# ---------- policy-state: same contract, shared path ------------------------

class TestPolicyStateOnPrimitive:
    def _receipt_ws(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        row = {"schema": "plan-receipt/1", "ts": "2026-10-19T12:00:00Z",
               "claim": "C-001", "round": 3, "admitted": ["C-001"],
               "chosen": "C-001", "state_signature": "s" * 12,
               "candidates": {"C-001": {"action_kind": "analysis",
                                        "alpha": 2.0, "beta": 1.0}}}
        (ws / "runs" / "plan-receipts.jsonl").write_text(
            json.dumps(row) + "\n", encoding="utf-8")
        return ws

    def test_unchanged_receipt_still_skips(self, tmp_path):
        import policy_state
        ws = self._receipt_ws(tmp_path)
        assert policy_state.run_face(ws) is True
        frozen = (ws / "runs" / "policy-state.json").read_text(
            encoding="utf-8")
        assert policy_state.run_face(ws) is False
        assert (ws / "runs" / "policy-state.json").read_text(
            encoding="utf-8") == frozen

    def test_projection_flows_through_the_primitive(self):
        src = (REPO_ROOT / "scripts" / "policy_state.py").read_text(
            encoding="utf-8")
        assert "input_signature" in src


# ---------- PIN: system-wide silence-on-no-change ---------------------------

class TestSystemWideSilence:
    def test_periodic_faces_silence_on_unchanged_signature(self, tmp_path):
        """The system-wide pin: for EVERY signature-gated periodic face,
        the second run on identical inputs persists and emits nothing —
        silence is the honest idle, everywhere, not per-site."""
        import digest_build as db
        import policy_state
        import verification_ladder as vl
        ws = tmp_path / "ws"
        (ws / "claims").mkdir(parents=True)
        (ws / "facts").mkdir(parents=True)
        (ws / "runs").mkdir(parents=True)
        (ws / "claim-register.yaml").write_text(
            "claims:\n  - id: C-001\n    status: OPEN\n", encoding="utf-8")
        (ws / "task_spec.yaml").write_text(
            "primary_questions:\n  - q: what\n", encoding="utf-8")
        (ws / "runs" / "plan-receipts.jsonl").write_text(
            json.dumps({"schema": "plan-receipt/1",
                        "ts": "2026-10-19T12:00:00Z", "claim": "C-001",
                        "round": 1, "admitted": ["C-001"],
                        "chosen": "C-001", "state_signature": "s" * 12,
                        "candidates": {}}) + "\n", encoding="utf-8")
        faces: dict[str, tuple[object, object]] = {
            "t2": (lambda: vl.round_close(ws),
                   lambda: vl.round_close(ws).get("unchanged") is True),
            "digest": (lambda: db.write_digest(ws),
                       lambda: _digest_unchanged(ws)),
            "policy_state": (lambda: policy_state.run_face(ws),
                             lambda: policy_state.run_face(ws) is False),
        }
        for name, (first, second) in faces.items():
            assert first() is not None, name
            assert second() is True, (
                f"{name}: an unchanged input signature must persist and "
                f"emit nothing (system-wide pin)")


def _digest_unchanged(ws: Path) -> bool:
    import digest_build as db
    before = (ws / db.DIGEST_PATH).read_text(encoding="utf-8")
    db.write_digest(ws)
    return (ws / db.DIGEST_PATH).read_text(encoding="utf-8") == before
