# -*- coding: utf-8 -*-
"""tests/test_redteam_face_501.py — issue 501 contract (TDD).

Field evidence (round-8A, 2026-10-02): the #819 promotion gate requires a
verify-note (passes) AND a red-team artifact per claim; the runner has
_run_verifier_act but no red-team face, so a passing verifier parks the
claim with a wake_condition the runner can never satisfy — every run needs
hand-collection. This pins the two missing pieces: (a) a successful
verifier act lands a GATE-CONFORMANT verify-note (the act's own record
name, verification-<claim>.md, is invisible to the gate's name matching);
(b) when promotion refuses solely for the missing red-team, the loop
dispatches the blind red-team act and retries promotion through the repo
gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from e2e import checkpoints, llm_faces, model  # noqa: E402
from test_e2e_runner import (ANCHORS, DERIVE_PY, FakeClock,  # noqa: E402
                             ScriptedRunner, TASK_YAML)


@pytest.fixture()
def stub_repo(tmp_path):
    """Same minimal unit repo as test_e2e_runner's (fixtures cannot be
    called directly across modules — the shape is duplicated verbatim)."""
    repo = tmp_path / "repo"
    task = repo / "eval/v1/tasks/smoke/py-derive-v1"
    (task / "target").mkdir(parents=True)
    (task / "target/derive.py").write_text(DERIVE_PY, encoding="utf-8")
    (task / "task.yaml").write_text(TASK_YAML, encoding="utf-8")
    (repo / "scripts").mkdir()
    return repo


@pytest.fixture()
def ctx(stub_repo, tmp_path):
    ws = tmp_path / "ws"
    ev_dir = tmp_path / "ev"
    ws.mkdir()
    (ws / "runs").mkdir()
    state = model.RunState(
        run_id="a1", unit="py-derive-v1", family="smoke",
        repo=str(stub_repo),
        task_dir=str(stub_repo / "eval/v1/tasks/smoke/py-derive-v1"),
        ws=str(ws), evidence_dir=str(ev_dir), budget_seconds=10_000,
        llm_mode="auto", started_ts="t", started_monotonic=0.0,
        anchors=dict(ANCHORS))
    runner = ScriptedRunner()
    return checkpoints.RunContext(
        state=state, runner=runner,
        face=llm_faces.face_for("auto", runner, ev_dir),
        clock=FakeClock(), sleep_fn=lambda _s: None)


def _register_with_partial(ctx, claim="C-005"):
    """Register carrying the claim as PARTIALLY-VERIFIED (8A park shape)."""
    reg = Path(ctx.ws) / "claim-register.yaml"
    reg.write_text(
        f"claims:\n  - id: {claim}\n    status: PARTIALLY-VERIFIED\n"
        f"    question: q\n", encoding="utf-8")
    return reg


VERIFICATION_RECORD = (
    "---\nclaim: C-005\nverdict: verified\n---\n\n"
    "re-run: uv run python eval/v1/tasks/smoke/py-derive-v1/target/derive.py\n"
    "rc: 0\n"
    "out-sha: " + ("7" * 64) + "\n\n"
    "replay 72/72 byte-exact\n")


# ---------- (a) the verifier act lands a gate-conformant note ----------

def test_verifier_success_writes_gate_conformant_verify_note(ctx):
    (Path(ctx.ws) / "runs" / "verification-C-005.md").write_text(
        VERIFICATION_RECORD, encoding="utf-8")
    _register_with_partial(ctx)
    ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    checkpoints._run_verifier_act(ctx, "C-005", set(), {"acts": []})
    note = Path(ctx.ws) / "runs" / "C-005-verify-note.md"
    text = note.read_text(encoding="utf-8")
    assert "claim_id: C-005" in text
    assert "verifier-identity:" in text
    assert "## Overall verdict\npasses" in text


def test_verifier_refuted_writes_refuted_note_not_passes(ctx):
    (Path(ctx.ws) / "runs" / "verification-C-005.md").write_text(
        VERIFICATION_RECORD.replace("verdict: verified",
                                    "verdict: refuted"),
        encoding="utf-8")
    _register_with_partial(ctx)
    ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    checkpoints._run_verifier_act(ctx, "C-005", set(), {"acts": []})
    text = (Path(ctx.ws) / "runs" / "C-005-verify-note.md").read_text(
        encoding="utf-8")
    assert "## Overall verdict\npasses" not in text
    assert "refuted" in text


def test_verifier_no_record_writes_no_note(ctx):
    """The act landed but wrote no verification record — no note (the gate
    must never see a passes the verifier never issued)."""
    _register_with_partial(ctx)
    ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    checkpoints._run_verifier_act(ctx, "C-005", set(), {"acts": []})
    assert not (Path(ctx.ws) / "runs" / "C-005-verify-note.md").exists()


# ---------- (b) the red-team face ----------

def test_promote_refusal_for_missing_redteam_dispatches_redteam_act(ctx):
    (Path(ctx.ws) / "runs" / "verification-C-005.md").write_text(
        VERIFICATION_RECORD, encoding="utf-8")
    _register_with_partial(ctx)
    ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    detail = {"acts": []}
    checkpoints._run_verifier_act(ctx, "C-005", set(), detail)
    # the red-team act fired (a second claude -p) and its prompt carries
    # the blindness contract + artifact requirements
    prompt = (Path(ctx.state.evidence_dir)
              / "dispatch-prompt-RT-C-005.md").read_text(encoding="utf-8")
    assert "kunglao-redteam" in prompt
    assert "verify-redteam-C-005.md" in prompt
    assert "RED-TEAM VERDICT" in prompt
    assert "verifier-identity:" in prompt
    assert any("kunglao-redteam" in c for c in ctx.runner.calls), \
        "red-team act never dispatched (prompt content rides argv)"


def test_redteam_artifact_lands_then_promotion_retries(ctx):
    """The red-team act wrote its artifact (CONFIRMED, distinct identity,
    later mtime) — promotion must be retried through the repo gate and
    succeed."""
    runs = Path(ctx.ws) / "runs"
    (runs / "verification-C-005.md").write_text(VERIFICATION_RECORD,
                                                encoding="utf-8")
    _register_with_partial(ctx)
    ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    # the RT "act" lands its artifact when ITS dispatch fires (after the
    # verify-note — the #825 provenance order must be real, not staged)
    def _land_redteam(req):
        if "kunglao-redteam" not in Path(req.prompt_file).read_text(
                encoding="utf-8"):
            return None
        (runs / "verify-redteam-C-005.md").write_text(
            "---\nclaim: C-005\nverifier-identity: redteam-act-a1\n---\n"
            "attacked; no divergence found\n\n"
            "RED-TEAM VERDICT: CONFIRMED\n", encoding="utf-8")
        return None
    ctx.face.dispatch_act = (lambda orig: lambda req: (
        _land_redteam(req) or orig(req)))(ctx.face.dispatch_act)
    detail = {"acts": []}
    checkpoints._run_verifier_act(ctx, "C-005", set(), detail)
    import yaml
    doc = yaml.safe_load((Path(ctx.ws) / "claim-register.yaml")
                         .read_text(encoding="utf-8"))
    assert doc["claims"][0]["status"] == "PROVEN", (
        f"promotion not retried/consumed: {doc['claims'][0]['status']}")


def test_refuted_redteam_never_promotes(ctx):
    """A REFUTED red-team verdict parks honestly — no PROVEN over a live
    refutation (the #819 pathology)."""
    runs = Path(ctx.ws) / "runs"
    (runs / "verification-C-005.md").write_text(VERIFICATION_RECORD,
                                                encoding="utf-8")
    _register_with_partial(ctx)
    ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    def _land_redteam(req):
        if "kunglao-redteam" not in Path(req.prompt_file).read_text(
                encoding="utf-8"):
            return None
        (runs / "verify-redteam-C-005.md").write_text(
            "---\nclaim: C-005\nverifier-identity: redteam-act-a1\n---\n"
            "divergence found\n\nRED-TEAM VERDICT: REFUTED\n",
            encoding="utf-8")
        return None
    ctx.face.dispatch_act = (lambda orig: lambda req: (
        _land_redteam(req) or orig(req)))(ctx.face.dispatch_act)
    detail = {"acts": []}
    checkpoints._run_verifier_act(ctx, "C-005", set(), detail)
    import yaml
    doc = yaml.safe_load((Path(ctx.ws) / "claim-register.yaml")
                         .read_text(encoding="utf-8"))
    assert doc["claims"][0]["status"] != "PROVEN"
    assert any("REFUTED" in str(p) or "refut" in str(p).lower()
               for p in detail.get("promotions", [])), (
        "the live refutation must be recorded in the promotion trail")


def test_artifact_missing_records_honestly_no_crash(ctx):
    """RT act returned DONE but wrote no artifact — honest trail row, no
    promotion, no crash (review finding 3)."""
    (Path(ctx.ws) / "runs" / "verification-C-005.md").write_text(
        VERIFICATION_RECORD, encoding="utf-8")
    _register_with_partial(ctx)
    ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    detail = {"acts": []}
    checkpoints._run_verifier_act(ctx, "C-005", set(), detail)
    assert not (Path(ctx.ws) / "runs" / "verify-redteam-C-005.md").exists()
    assert any(p.get("redteam") == "artifact-missing"
               for p in detail["promotions"])
    import yaml
    doc = yaml.safe_load((Path(ctx.ws) / "claim-register.yaml")
                         .read_text(encoding="utf-8"))
    assert doc["claims"][0]["status"] != "PROVEN"


def test_existing_redteam_artifact_blocks_note_rewrite(ctx):
    """Resume face (review finding 2): a landed RT artifact must keep its
    provenance order — the verifier act must NOT rewrite the note."""
    runs = Path(ctx.ws) / "runs"
    (runs / "verification-C-005.md").write_text(VERIFICATION_RECORD,
                                                encoding="utf-8")
    (runs / "verify-redteam-C-005.md").write_text(
        "---\nclaim: C-005\nverifier-identity: redteam-act-prev\n---\n"
        "attacked\n\nRED-TEAM VERDICT: CONFIRMED\n", encoding="utf-8")
    note = runs / "C-005-verify-note.md"
    note.write_text("---\nclaim_id: C-005\n"
                    "verifier-identity: e2e-verifier-act-prev\n---\n"
                    "prior note\n\n## Overall verdict\npasses\n",
                    encoding="utf-8")
    before = note.read_text(encoding="utf-8")
    _register_with_partial(ctx)
    ctx.runner.on("claude", "-p", rc=0, stdout='{"result": "done"}')
    checkpoints._run_verifier_act(ctx, "C-005", set(), {"acts": []})
    assert note.read_text(encoding="utf-8") == before, (
        "note rewritten under a landed RT artifact — mtime order poisoned")
