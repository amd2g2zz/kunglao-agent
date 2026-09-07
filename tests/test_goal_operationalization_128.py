# -*- coding: utf-8 -*-
"""TDD RED — issue #128: Phase-0 goal operationalization read-back.

Contract (issue body): the user's verbatim task stays in task-oracle.yaml
(#473, unchanged); the goal -> operationalization translation becomes an
audited artifact — deliverables / acceptance / not-done counterexamples /
diff-vs-verbatim / capability-probe cases — confirmed with the user in ONE
round, with re-scope forcing re-confirmation.

The load-bearing half is the not_done list: capability substitution, scope
narrowing, and persuasion-to-downgrade launder through an unconfirmed
operationalization; once a narrowed goal enters the oracle, every later
step is "honest" — the pollution is at the source. Naming what does NOT
count as done makes each narrowing point a human-visible negative.

Fixture shape (SYNTHETIC, the issue's key-recovery example): deliverable is
a reproducible decrypt capability, so the capability rule (R3) must demand
probe cases; the three counterexamples are the issue's own.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import goal_operationalization as go  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture — the issue's key-recovery operationalization, key-recovery shaped.
# ---------------------------------------------------------------------------

def _doc(**over):
    doc = {
        "schema": go.SCHEMA_ID,
        "verbatim_ref": "task-oracle.yaml",
        "status": go.STATUS_PENDING,
        "deliverables": [
            "A recovered key that decrypts arbitrary fresh ciphertext offline",
        ],
        "acceptance": [
            "decrypt(held_out_ct) == known_plaintext with no network and no "
            "target process running",
        ],
        "not_done": [
            "an emulator harness running once does not count as done",
            "decrypting only the captured batch does not count as done",
            "decryption depending on a live target process does not count as done",
        ],
        "diff_vs_verbatim": [
            "adds: the verbatim 'get the key' is operationalized as an "
            "offline decrypt acceptance check",
            "excludes: dynamic unpacking of packed variants (not asked for)",
        ],
        "probe_cases": [
            "fresh-input: decrypt a held-out ciphertext never present in the capture",
            "no-dependency: decryption runs with the target process absent",
            "materialized-artifact: the key file exists on disk with a recorded sha256",
        ],
    }
    doc.update(over)
    return doc


# ===========================================================================
# (1) doc contract — SKILL.md names the read-back protocol
# ===========================================================================

def test_skill_md_names_goal_operationalization_readback():
    text = (ROOT / "skills" / "kunglao-agent" / "SKILL.md").read_text(
        encoding="utf-8")
    for needle in (
        "goal-operationalization.yaml",       # the audited artifact
        "operationalization",                  # the protocol is named
        "not-done counterexamples",            # the load-bearing half
        "does not count as done",              # counterexample form
        "diff declaration",                    # no silent equivalence
        "probe cases",                         # capability-probe derivation
        "oracle behavior statement",           # situational fact about the oracle
        "red is information",                  # anti-defeatist framing
        "re-scope",                            # edit != confirmed
        "re-confirmation",                     # fresh round on re-scope
    ):
        assert needle in text, (
            f"SKILL.md must name the read-back protocol anchor {needle!r} (#128)")


def test_init_skill_registers_the_skeleton():
    text = (ROOT / "skills" / "init" / "SKILL.md").read_text(encoding="utf-8")
    assert "goal-operationalization.yaml" in text, (
        "init flow must register the operationalization skeleton (#128)")
    assert "pending-confirmation" in text, (
        "init registration must carry the pending marker (#128)")


# ===========================================================================
# (2) template — skeleton with the pending marker, mirroring #473
# ===========================================================================

def _template_doc():
    tpl = ROOT / "templates" / "state" / "goal-operationalization.yaml"
    assert tpl.exists(), f"template missing: {tpl}"
    return yaml.safe_load(tpl.read_text(encoding="utf-8"))


def test_template_exists_with_fields_and_pending_marker():
    doc = _template_doc()
    for field in ("deliverables", "acceptance", "not_done",
                  "diff_vs_verbatim", "probe_cases"):
        assert field in doc, f"template lacks {field}"
        assert isinstance(doc[field], list), field
    assert doc["status"] == "pending-confirmation"
    assert doc["schema"] == go.SCHEMA_ID


def test_template_carries_optional_oracle_behavior_acknowledgment():
    doc = _template_doc()
    assert "oracle_behavior_acknowledged" in doc, (
        "optional oracle-behavior acknowledgment field missing (#128 addendum)")
    assert isinstance(doc["oracle_behavior_acknowledged"], bool)


def test_skeleton_is_pending_but_not_yet_audited():
    """The skeleton is a legal PENDING file, never a legal confirmed one:
    empty lists mean unaudited — validate() must say so, not wave it through."""
    rep = go.validate(_template_doc())
    assert rep["effective_status"] == go.STATUS_PENDING
    assert rep["errors"], "empty skeleton must not validate clean"


# ===========================================================================
# (3) validator rules
# ===========================================================================

def test_rejects_empty_not_done():
    rep = go.validate(_doc(not_done=[]))
    assert any("not_done" in e for e in rep["errors"]), rep


def test_rejects_empty_diff_vs_verbatim_as_silent_equivalence():
    rep = go.validate(_doc(diff_vs_verbatim=[]))
    assert any("diff_vs_verbatim" in e for e in rep["errors"]), rep
    assert any("silent equivalence" in e.lower() for e in rep["errors"]), rep


def test_rejects_rubber_stamp_identity_diff():
    for stamp in ("identical to the verbatim task", "no delta"):
        rep = go.validate(_doc(diff_vs_verbatim=[stamp]))
        assert any("silent equivalence" in e.lower() for e in rep["errors"]), (
            f"{stamp!r} must refuse as a rubber stamp: {rep}")


def test_capability_rule_requires_probe_cases():
    rep = go.validate(_doc(probe_cases=[]))
    assert any("probe_cases" in e for e in rep["errors"]), rep


def test_non_capability_goal_needs_no_probe_cases():
    rep = go.validate(_doc(
        deliverables=["A written report of suspicious string artifacts"],
        acceptance=["the report lists every artifact with its offset"],
        probe_cases=[]))
    assert not any("probe_cases" in e for e in rep["errors"]), rep


def test_schema_wall_rejects_unknown_schema():
    with pytest.raises(go.GoalOpError):
        go.validate(_doc(schema="goal-operationalization/0"))


def test_rescope_re_pends_a_confirmed_file(tmp_path):
    """R4: edit != confirmed — a confirmed file whose content hash no longer
    matches confirmed_sha256 validates as pending-confirmation again."""
    confirmed = go.confirm(_doc())
    rep = go.validate(confirmed)
    assert rep["errors"] == [], rep
    assert rep["effective_status"] == go.STATUS_CONFIRMED
    tampered = dict(confirmed,
                    not_done=list(confirmed["not_done"]) + ["scope cut nobody approved"])
    rep2 = go.validate(tampered)
    assert rep2["effective_status"] == go.STATUS_PENDING, rep2
    assert rep2["rescoped"] is True, rep2


def test_confirm_refuses_to_seal_an_invalid_file():
    with pytest.raises(go.GoalOpError):
        go.confirm(_doc(not_done=[]))


# ===========================================================================
# (4) fixture demo — the key-recovery goal operationalizes and validates
# ===========================================================================

def test_fixture_demo_key_recovery_operationalization(tmp_path):
    doc = _doc()
    rep = go.validate(doc)
    assert rep["errors"] == [], rep
    assert rep["capability"] is True, "decrypt deliverable must read as capability"
    assert rep["effective_status"] == go.STATUS_PENDING
    joined = " ".join(doc["probe_cases"])
    for kind in ("fresh-input", "no-dependency", "materialized-artifact"):
        assert kind in joined, kind
    # stored separately from the verbatim task: a pointer, never the payload
    assert doc["verbatim_ref"] == "task-oracle.yaml"
    # file round-trip (hypothesis_store-style IO)
    path = tmp_path / "goal-operationalization.yaml"
    go.dump(path, doc)
    rep2 = go.validate(go.load(path))
    assert rep2["errors"] == [], rep2
    assert rep2["capability"] is True
