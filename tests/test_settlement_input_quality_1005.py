# -*- coding: utf-8 -*-
"""tests/test_settlement_input_quality_1005.py — the blind settlement
input carries the value question, a resolvable rules pin, and evidence.

The live audit found three defects on the production park path:

  1. QUESTION — ``round_closure`` called ``park_blind_input`` with no
     question, so every parked doc said ``question: ""`` and the
     settler judged artifacts without knowing which value question the
     claim answers. The register already carries ``answers_question``
     (the pq id) and ``task_spec.primary_questions`` carries the text;
     nothing joined the two.
  2. RULES PIN — the doc pinned the normalized rules path, which
     STRIPPED the leading slash of the absolute repo path: the settler
     received ``Users/.../reward-rules.yaml`` — neither absolute nor
     workspace-relative, so it could not open the table it is required
     to rule under.
  3. EMPTY WINDOW — a step whose window scan returned no raw artifact
     still parked a doc with zero pinned bytes, spending a blind
     settler run over nothing.

Pins are load-bearing: each one fails on the pre-fix tree and names the
consumer the defect starves.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
for p in (str(ROOT), str(SCRIPTS), str(HOOKS), str(ROOT / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from _factories import write_claims_register  # noqa: E402
from rlvr import settlement_scorer as bss  # noqa: E402
from rlvr import settlement_wire as wire  # noqa: E402

QUESTION = "Does the sample carry a second-stage loader?"
ARTIFACT = "evidence/raw-step.bin"


def _ws(tmp_path: Path, *, answers="q1", spec=None) -> Path:
    ws = tmp_path / "ws"
    (ws / "evidence").mkdir(parents=True)
    (ws / ARTIFACT).write_bytes(b"raw-step-artifact-bytes")
    (ws / "runs").mkdir()
    claim = {"id": "C-1", "status": "IN_PROGRESS"}
    if answers is not None:
        claim["answers_question"] = answers
    write_claims_register(ws, [claim])
    if spec is not None:
        (ws / "task_spec.yaml").write_text(spec, encoding="utf-8")
    return ws


CANONICAL_SPEC = (
    "primary_questions:\n"
    "  - id: q1\n"
    f"    q: {QUESTION}\n"
    "    need: yes_no_with_evidence\n"
)


# ------------------------------------------------------- 1. the question

def test_claim_question_resolves_register_through_task_spec(tmp_path) -> None:
    ws = _ws(tmp_path, spec=CANONICAL_SPEC)
    assert wire.claim_question(ws, "C-1") == QUESTION


def test_claim_question_supports_the_legacy_shapes(tmp_path) -> None:
    """The canonical parse accepts three shapes; the text lookup must
    not silently know only one of them."""
    legacy_list = _ws(tmp_path / "a", spec=(
        "primary_questions:\n  - q1: legacy one-key text\n"))
    assert wire.claim_question(legacy_list, "C-1") == "legacy one-key text"
    mapping = _ws(tmp_path / "b", spec=(
        "primary_questions:\n  q1: top-level mapping text\n"))
    assert wire.claim_question(mapping, "C-1") == "top-level mapping text"
    bare = _ws(tmp_path / "c", spec="primary_questions:\n  - q1\n")
    assert wire.claim_question(bare, "C-1") == "q1"


def test_claim_question_degrades_to_empty_never_guesses(tmp_path) -> None:
    assert wire.claim_question(_ws(tmp_path / "a"), "C-1") == ""
    assert wire.claim_question(
        _ws(tmp_path / "b", answers=None, spec=CANONICAL_SPEC), "C-1") == ""
    assert wire.claim_question(
        _ws(tmp_path / "c", answers="q9", spec=CANONICAL_SPEC), "C-1") == ""
    assert wire.claim_question(
        _ws(tmp_path / "d", spec=CANONICAL_SPEC), "C-404") == ""


def test_park_blind_input_fills_the_question_by_default(tmp_path) -> None:
    """The production defect was a caller that passed nothing. The
    writer now resolves the question itself, so a future caller cannot
    re-open the hole by omission."""
    ws = _ws(tmp_path, spec=CANONICAL_SPEC)
    doc = wire.park_blind_input(ws, "C-1", [ARTIFACT])["doc"]
    assert doc["question"] == QUESTION


def test_park_blind_input_keeps_an_explicit_empty_question(tmp_path) -> None:
    ws = _ws(tmp_path, spec=CANONICAL_SPEC)
    doc = wire.park_blind_input(ws, "C-1", [ARTIFACT], question="")["doc"]
    assert doc["question"] == ""


def test_round_closure_parks_the_resolved_question(tmp_path) -> None:
    """The end-to-end production face: the doc the settler will read
    carries the question, not ""."""
    import round_closure
    ws = _ws(tmp_path, spec=CANONICAL_SPEC)
    ts = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    stamp = (datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()
    os.utime(ws / ARTIFACT, (stamp, stamp))
    round_closure._blind_settlement_face(
        ws, wire, {"claim": "C-1", "ts": ts})
    doc = json.loads(
        (ws / "runs" / "settlement-input-C-1.json").read_text(
            encoding="utf-8"))
    assert doc["question"] == QUESTION
    assert doc["artifacts"], "the window's raw artifact is pinned"


# ------------------------------------------------------ 2. the rules pin

def test_the_rules_pin_is_absolute_and_resolvable(tmp_path) -> None:
    ws = _ws(tmp_path, spec=CANONICAL_SPEC)
    rules = tmp_path / "reward-rules.yaml"
    rules.write_text("rules: synthetic-settlement-rules\n", encoding="utf-8")
    doc = wire.park_blind_input(
        ws, "C-1", [ARTIFACT], rules_path=rules)["doc"]
    pinned = doc["rules"]["path"]
    assert os.path.isabs(pinned), (
        "the settler must be able to OPEN the table it rules under; a "
        f"slash-stripped host path is neither absolute nor ws-relative: "
        f"{pinned!r}")
    assert Path(pinned) == rules.resolve()
    assert bss.check_blind_input(doc)["ok"] is True


# -------------------------------------------------- 3. the empty window

def test_settler_input_refuses_an_empty_artifact_window(tmp_path) -> None:
    ws = _ws(tmp_path, spec=CANONICAL_SPEC)
    with pytest.raises(ValueError, match="artifact"):
        bss.settler_input(ws, claim="C-1", identity="settle-1",
                          artifact_paths=[])


def test_park_blind_input_refuses_an_empty_artifact_window(tmp_path) -> None:
    ws = _ws(tmp_path, spec=CANONICAL_SPEC)
    with pytest.raises(ValueError, match="artifact"):
        wire.park_blind_input(ws, "C-1", [])


def test_a_zero_artifact_parked_doc_never_settles(tmp_path) -> None:
    """The trust wall, not just the writer: a hand-crafted doc with no
    pinned bytes must not settle. The review probe on the pre-fix tree
    banked full credit from `artifacts: []` + a credited action with an
    empty evidence list + an oracle pass — so this pin builds exactly
    that creditable shape (a passing verification record included), and
    only the gate's evidence floor keeps it from settling."""
    ws = _ws(tmp_path, spec=CANONICAL_SPEC)
    parked = wire.park_blind_input(ws, "C-1", [ARTIFACT])
    doc = json.loads((ws / parked["path"]).read_text(encoding="utf-8"))
    doc["artifacts"] = []
    (ws / parked["path"]).write_text(
        json.dumps(doc, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8")
    verdict = {"schema": "settlement-verdict/1",
               "identity": doc["identity"], "claim": "C-1",
               "actions": [{"action_id": "step-1", "credit": 1.0,
                            "evidence": []}],
               "trajectory_credit": 1.0}
    (ws / "runs" / "settlement-verdict-C-1.json").write_text(
        json.dumps(verdict, sort_keys=True) + "\n", encoding="utf-8")
    (ws / "runs" / "verification-C-1.md").write_text(
        "verdict: verified\n", encoding="utf-8")
    res = wire.settle_parked(ws, "C-1", oracle_verdict="pass")
    assert res["settled"] is False
    assert "artifact" in res["reason"]


def test_round_closure_skips_parking_on_an_empty_window(
        tmp_path, monkeypatch) -> None:
    """An empty window is a WARN, not a settler run: no doc parks."""
    import round_closure
    ws = _ws(tmp_path, spec=CANONICAL_SPEC)
    calls: list = []

    class FakeWire:
        @staticmethod
        def step_window_artifacts(ws, since, until=None):  # noqa: ANN001
            return []

        @staticmethod
        def park_blind_input(*a, **k):  # noqa: ANN002, ANN003
            calls.append((a, k))
            raise AssertionError("an empty window must not park")

        @staticmethod
        def settle_face(ws):  # noqa: ANN001
            return []

    out = round_closure._blind_settlement_face(
        ws, FakeWire, {"claim": "C-1", "ts": "2026-11-06T00:00:00Z"})
    assert calls == []
    assert out == {}
