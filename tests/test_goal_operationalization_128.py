# -*- coding: utf-8 -*-
"""TDD — issue #128: Phase-0 goal operationalization (owner-amended).

Final contract after the three owner amendments on this branch:

  A1 (kept): the oracle behavior statement is read back at Phase 0 — red is
     information, not failure; cases stay anchored to captured ground truth;
     acceptance is machine-judged.
  A2: the capability-verb keyword scan is REPLACED by a declared structural
     bit — `generalization: required | not-applicable | unknown` — answering
     ONE question: must the deliverable work on inputs beyond the captured /
     observed evidence? required/unknown => the fresh-input probe case is
     mandatory (fail-closed); not-applicable must also appear as an explicit
     diff_vs_verbatim entry (declaring non-generalization IS a narrowing).
     For protocol client simulation the fresh-input case IS the master
     oracle (generate valid output for never-captured inputs); replay of
     captured pairs is the verification ladder, never the closure.
  A3: the mandatory confirmation round is REVOKED. Phase 0 is mechanical
     pre-registration (timestamped); no user wait. The not_done list is the
     IMMUTABLE machine-checked constitution: after the first dispatch the
     file is append-only — dropping/rewording a not_done / deliverables /
     acceptance entry is REFUSED (contradiction face), generalization never
     flips, and any other post-dispatch drift becomes a re-scope record
     that delivery must restate. The human lives at the verbatim task
     (#473) and at the delivery receipt; ask_for_direction stays the only
     escalation channel.

Fixture shapes (SYNTHETIC): key-recovery (the issue's own counterexamples)
and encrypted-XHR client simulation (the owner's domain-framing example).
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

TS = "2026-09-07T00:00:00Z"


# ---------------------------------------------------------------------------
# Fixtures — key-recovery and client-simulation operationalizations.
# ---------------------------------------------------------------------------

def _doc(**over):
    doc = {
        "schema": go.SCHEMA_ID,
        "verbatim_ref": "task-oracle.yaml",
        "declared_ts": TS,
        "generalization": "required",
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
        "oracle_behavior_acknowledged": True,
        "first_dispatch_ts": "",
    }
    doc.update(over)
    return doc


def _sim_doc(**over):
    """Simulation-shaped goal (owner domain framing): construct valid
    encrypted-XHR requests — the fresh-input case is the named acceptance."""
    doc = {
        "schema": go.SCHEMA_ID,
        "verbatim_ref": "task-oracle.yaml",
        "declared_ts": TS,
        "generalization": "required",
        "deliverables": [
            "A simulated encrypted-XHR client that constructs valid requests "
            "(algorithm + key + parameter handling) for arbitrary inputs",
        ],
        "acceptance": [
            "fresh-input: the simulated client generates a request accepted "
            "by the real server-side check for a never-captured input",
        ],
        "not_done": [
            "replaying a captured request does not count as done",
            "a request hardcoded to the captured parameter set does not count as done",
        ],
        "diff_vs_verbatim": [
            "adds: 'talk to the endpoint' is operationalized as constructing "
            "requests for never-captured inputs, not replaying them",
        ],
        "probe_cases": [
            "fresh-input: generate a valid request for an input absent from the capture",
            "no-dependency: request construction runs offline against the recorded checker",
            "materialized-artifact: the client script exists on disk and re-runs",
        ],
        "oracle_behavior_acknowledged": True,
        "first_dispatch_ts": "",
    }
    doc.update(over)
    return doc


# ===========================================================================
# (1) doc contract — SKILL.md names the pre-registration protocol
# ===========================================================================

def test_skill_md_names_goal_operationalization_protocol():
    text = (ROOT / "skills" / "kunglao-agent" / "SKILL.md").read_text(
        encoding="utf-8")
    for needle in (
        "goal-operationalization.yaml",       # the audited artifact
        "pre-registration",                    # mechanical Phase-0 act
        "not-done counterexamples",            # the load-bearing half
        "does not count as done",              # counterexample form
        "diff declaration",                    # no silent equivalence
        "generalization",                      # the declared structural bit
        "fresh-input",                         # the master-oracle probe shape
        "oracle behavior statement",           # A1 injected context
        "red is information",                  # anti-defeatist framing
        "append-only",                         # post-dispatch constitution
        "re-scope record",                     # drift-event face
        "restates",                            # delivery receipt audit point
        "ask_for_direction",                   # the only escalation channel
    ):
        assert needle in text, (
            f"SKILL.md must name the protocol anchor {needle!r} (#128)")


def test_skill_md_carries_no_confirmation_round():
    """A3: the mandatory user confirmation round is revoked — the protocol
    must not smuggle it back (the human is at the verbatim task + delivery)."""
    text = (ROOT / "skills" / "kunglao-agent" / "SKILL.md").read_text(
        encoding="utf-8")
    assert "confirmation round" not in text
    assert "pending-confirmation" not in text


def test_init_skill_registers_the_skeleton():
    text = (ROOT / "skills" / "init" / "SKILL.md").read_text(encoding="utf-8")
    assert "goal-operationalization.yaml" in text, (
        "init flow must register the operationalization skeleton (#128)")
    assert "pre-registers" in text, (
        "init registration must name the mechanical pre-registration act")


# ===========================================================================
# (2) template — pre-registration skeleton (A3 shape, no state machine)
# ===========================================================================

def _template_text():
    tpl = ROOT / "templates" / "state" / "goal-operationalization.yaml"
    assert tpl.exists(), f"template missing: {tpl}"
    return tpl.read_text(encoding="utf-8")


def _template_doc():
    return yaml.safe_load(_template_text())


def test_template_exists_with_fields():
    doc = _template_doc()
    for field in ("deliverables", "acceptance", "not_done",
                  "diff_vs_verbatim", "probe_cases"):
        assert field in doc, f"template lacks {field}"
        assert isinstance(doc[field], list), field
    assert doc["schema"] == go.SCHEMA_ID
    assert doc["generalization"] in go.GENERALIZATION_VALUES
    for field in ("declared_ts", "first_dispatch_ts", "verbatim_ref",
                  "oracle_behavior_acknowledged"):
        assert field in doc, field
    assert "constitution" in doc, "the frozen pre-dispatch copy field"


def test_template_carries_no_confirmation_state_machine():
    text = _template_text()
    assert "pending-confirmation" not in text
    assert "confirmed" not in text, "A3 revoked the confirmation machinery"


def test_skeleton_is_pending_but_not_yet_audited():
    """The skeleton is a legal pre-dispatch file, never a clean one: empty
    lists mean unaudited — validate() must say so, not wave it through."""
    rep = go.validate(_template_doc())
    assert rep["errors"], "empty skeleton must not validate clean"
    assert rep["post_dispatch"] is False


# ===========================================================================
# (3) validator — R1/R2 unchanged, R3 = declared generalization bit (A2)
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


def test_generalization_required_or_unknown_needs_probe_cases():
    for bit in ("required", "unknown"):
        rep = go.validate(_doc(generalization=bit, probe_cases=[]))
        assert any("probe_cases" in e for e in rep["errors"]), (bit, rep)


def test_generalization_requires_the_fresh_input_case():
    """A2: the fresh-input probe is the master-oracle shape — present by
    name, not just any probe."""
    rep = go.validate(_doc(probe_cases=[
        "no-dependency: decryption runs with the target process absent"]))
    assert any("fresh-input" in e for e in rep["errors"]), rep


def test_generalization_not_applicable_needs_declared_diff_entry():
    """Declaring non-generalization IS a scope narrowing — it must be a
    visible diff_vs_verbatim entry the delivery receipt restates."""
    rep = go.validate(_doc(
        generalization="not-applicable",
        deliverables=["A written report of suspicious string artifacts"],
        acceptance=["the report lists every artifact with its offset"],
        probe_cases=[]))
    assert any("not-applicable" in e and "diff_vs_verbatim" in e
               for e in rep["errors"]), rep
    ok = go.validate(_doc(
        generalization="not-applicable",
        deliverables=["A written report of suspicious string artifacts"],
        acceptance=["the report lists every artifact with its offset"],
        probe_cases=[],
        diff_vs_verbatim=[
            "not-applicable: one-off artifact analysis — the deliverable "
            "need not work beyond the captured evidence"]))
    assert not any("generalization" in e for e in ok["errors"]), ok


def test_generalization_missing_or_invalid_is_a_loud_wall():
    doc = _doc()
    del doc["generalization"]
    with pytest.raises(go.GoalOpError):
        go.validate(doc)
    with pytest.raises(go.GoalOpError):
        go.validate(_doc(generalization="whenever convenient"))


def test_undeclared_timestamp_is_not_a_record():
    rep = go.validate(_doc(declared_ts=""))
    assert any("declared_ts" in e for e in rep["errors"]), rep


def test_schema_wall_rejects_unknown_schema():
    with pytest.raises(go.GoalOpError):
        go.validate(_doc(schema="goal-operationalization/0"))


# ===========================================================================
# (4) post-dispatch law (A3): append-only constitution + re-scope records
# ===========================================================================

def test_stamp_dispatch_freezes_the_constitution():
    stamped = go.stamp_dispatch(_doc(), "2026-09-07T12:00:00Z")
    assert stamped["first_dispatch_ts"] == "2026-09-07T12:00:00Z"
    assert stamped["constitution"]["not_done"] == _doc()["not_done"]
    assert stamped["constitution"]["generalization"] == "required"
    rep = go.validate(stamped)
    assert rep["errors"] == [], rep
    assert rep["post_dispatch"] is True
    assert rep["rescopes"] == [], rep


def test_stamp_dispatch_refuses_twice_and_refuses_unaudited():
    stamped = go.stamp_dispatch(_doc(), "2026-09-07T12:00:00Z")
    with pytest.raises(go.GoalOpError):
        go.stamp_dispatch(stamped, "2026-09-07T13:00:00Z")
    with pytest.raises(go.GoalOpError):
        go.stamp_dispatch(_doc(not_done=[]), "2026-09-07T12:00:00Z")


def _stamped(**over):
    return go.stamp_dispatch(_doc(**over), "2026-09-07T12:00:00Z")


def test_post_dispatch_not_done_drop_or_reword_is_refused():
    dropped = _stamped()
    dropped["not_done"] = dropped["not_done"][:2]
    rep = go.validate(dropped)
    assert any("not_done" in e and "append-only" in e
               for e in rep["errors"]), rep
    reworded = _stamped()
    reworded["not_done"] = [
        "an emulator harness running twice does not count as done"
        if e.startswith("an emulator harness running once")
        else e for e in reworded["not_done"]]
    rep2 = go.validate(reworded)
    assert any("not_done" in e and "append-only" in e
               for e in rep2["errors"]), rep2


def test_post_dispatch_deliverable_withdrawal_is_refused():
    shrunk = _stamped()
    shrunk["deliverables"] = []
    rep = go.validate(shrunk)
    assert any("deliverables" in e and "withdraw" in e.lower()
               for e in rep["errors"]), rep


def test_post_dispatch_generalization_flip_is_refused():
    flipped = _stamped(generalization="required")
    flipped["generalization"] = "not-applicable"
    rep = go.validate(flipped)
    assert any("generalization" in e and "flip" in e.lower()
               for e in rep["errors"]), rep


def test_post_dispatch_appends_and_other_edits_are_rescope_records():
    """(c) of A3: appends are legal; every other post-dispatch drift is a
    re-scope record the delivery receipt must restate — never silent."""
    grown = _stamped()
    grown["not_done"] = grown["not_done"] + [
        "passing the recorded checker with a replayed transcript does not count as done"]
    rep = go.validate(grown)
    assert rep["errors"] == [], rep
    assert any("not_done" in r for r in rep["rescopes"]), rep

    edited = _stamped()
    edited["probe_cases"] = edited["probe_cases"][:1]
    rep2 = go.validate(edited)
    assert rep2["errors"] == [], rep2
    assert any("probe_cases" in r for r in rep2["rescopes"]), rep2


def test_pre_dispatch_edits_are_free():
    """Before the first dispatch the file is a draft: no constitution, no
    re-scope records — only the content rules apply."""
    rep = go.validate(_doc(deliverables=["Something else entirely"]))
    assert rep["rescopes"] == [], rep


# ===========================================================================
# (5) delivery receipt audit point (A3 item 4)
# ===========================================================================

def test_restatement_carries_not_done_and_generalization():
    stamped = go.stamp_dispatch(_sim_doc(), "2026-09-07T12:00:00Z")
    stamped["not_done"] = stamped["not_done"] + [
        "passing the recorded checker with a replayed transcript does not count as done"]
    text = go.restatement(stamped)
    for entry in stamped["not_done"]:
        assert entry in text, entry
    assert "required" in text, "the generalization declaration must restate"
    assert stamped["declared_ts"] in text


# ===========================================================================
# (6) fixture demos — key recovery AND client simulation
# ===========================================================================

def test_fixture_demo_key_recovery_operationalization(tmp_path):
    doc = _doc()
    rep = go.validate(doc)
    assert rep["errors"] == [], rep
    assert rep["post_dispatch"] is False
    # stored separately from the verbatim task: a pointer, never the payload
    assert doc["verbatim_ref"] == "task-oracle.yaml"
    path = tmp_path / "goal-operationalization.yaml"
    go.dump(path, doc)
    rep2 = go.validate(go.load(path))
    assert rep2["errors"] == [], rep2


def test_fixture_demo_client_simulation_operationalization():
    rep = go.validate(_sim_doc())
    assert rep["errors"] == [], rep
    # fresh-input case is the named acceptance, not an optional extra probe
    assert any(e.startswith("fresh-input") for e in _sim_doc()["acceptance"])
    # the narrowing negative the owner named is in the constitution
    assert any("replaying a captured request does not count as done"
               in e for e in _sim_doc()["not_done"])
    # simulation with generalization required but no probes is refused
    rep2 = go.validate(_sim_doc(probe_cases=[]))
    assert any("probe_cases" in e for e in rep2["errors"]), rep2
