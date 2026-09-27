# -*- coding: utf-8 -*-
"""Issue 292 — characterization net for the post2 product scripts.

Pins the CURRENT bytes of every CLI face (stdout, stderr, exit code) and
the current semantics of every helper scheduled for the _scriptlib extraction,
so the refactor to the shared module is provably zero-behavior-change:

  - scripts/hypothesis_bridge.py   --check / --mint(refused) / --sync
  - scripts/plan_epistemics.py     --mint json + plain faces, warn
                                   rate-limit contract, register read
  - scripts/claim_granularity.py   --check ok / monolithic / missing-plan
  - scripts/target_ladder.py       --check faces, --mint refusal,
                                   _load_claims/_claims_from_text/_find_claim
  - scripts/progress_timeline.py   render_and_repair file bytes + note
  - scripts/settle_by_need.py      the four routing decisions
  - scripts/plan_drift_detector.py check no-drift + --auto ok + warn

Every face runs IN-PROCESS (no child process invocation, no network) —
mains that take no argv parameter are driven through a patched sys.argv.
Captured 2026-09-21 against base e45edc7 (pre-refactor), pinned verbatim.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import claim_granularity as cg  # noqa: E402
import hypothesis_bridge as hb  # noqa: E402
import plan_drift_detector as pdd  # noqa: E402
import plan_epistemics as pe  # noqa: E402
import progress_timeline as pt  # noqa: E402
import settle_by_need as sbn  # noqa: E402
import target_ladder as tl  # noqa: E402


def run_face(fn, argv=None):
    """Run fn in-process, capture (stdout, stderr, rc). SystemExit is a rc."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            rc = fn() if argv is None else fn(argv)
        except SystemExit as exc:
            rc = exc.code
    return out.getvalue(), err.getvalue(), rc


def patch_argv(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", list(argv))


# ---------------------------------------------------------------- fixtures --

GOOD_PLAN = (
    "goal: prove dispatch\nsteps:\n"
    "  1. static xref -> caller list\n"
    "  2. trace table -> handler\n"
    "  3. confirm binding\nfallback:\n  - report blocker\n"
)
MONO_PLAN = "goal: g\nsteps:\n" + "".join(
    f"  {i}. step {i} does things\n" for i in range(1, 13))


@pytest.fixture
def hb_ws(tmp_path):
    return tmp_path / "hb"


@pytest.fixture
def pe_ws(tmp_path):
    return tmp_path / "pe"


@pytest.fixture
def cg_ws(tmp_path):
    ws = tmp_path / "cg"
    (ws / "runs").mkdir(parents=True)
    return ws


@pytest.fixture
def tl_ws(tmp_path):
    ws = tmp_path / "tl"
    ws.mkdir()
    return ws


@pytest.fixture
def pt_ws(tmp_path):
    ws = tmp_path / "pt"
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True)
    row = {"ts": "2026-09-21T10:00:00Z", "epoch": 5, "actor": "worker",
           "action": "evidence_captured", "claim": "C-001",
           "detail": "found the loader"}
    (logs / "kunglao-2026-09-21.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8")
    return ws


@pytest.fixture
def pdd_ws(tmp_path):
    ws = tmp_path / "pdd"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n", encoding="utf-8")
    (ws / "global_plan.txt").write_text(
        "# plan\n- C-001: prove the dispatch mode\n", encoding="utf-8")
    return ws


# ------------------------------------------------- hypothesis_bridge (252) --

def test_hb_check_bare_ok(hb_ws):
    assert run_face(hb.main, [str(hb_ws), "--check"]) == (
        "OK: no orphan representations\n", "", 0)


def test_hb_mint_refuses_missing_family(hb_ws):
    out, err, rc = run_face(hb.main, [str(hb_ws), "--mint", "H-1", "cand-a"])
    assert (out, err, rc) == (
        f"REFUSED: hypothesis H-1 not found under {hb_ws / 'hypotheses'}"
        " — refusing to mint arms against a nonexistent family\n", "", 1)


def test_hb_sync_bare_empty(hb_ws):
    assert run_face(hb.main, [str(hb_ws), "--sync"]) == (
        "confirmed=[] superseded=[] refuted=[] pending=0 skipped=[]\n", "", 0)


# -------------------------------------------------- plan_epistemics (250) --

def test_pe_mint_json_bare_ws(pe_ws):
    assert run_face(pe.main, ["--mint", str(pe_ws), "--json"]) == (
        '{\n  "target_class": null,\n  "minted": [],\n  "report": []\n}\n',
        "", 0)


def test_pe_mint_plain_bare_ws(pe_ws):
    assert run_face(pe.main, ["--mint", str(pe_ws)]) == (
        "target_class: None\n"
        "OK: nothing to mint (idempotent or no target class)\n", "", 0)


def test_pe_no_args_exit_2():
    assert run_face(pe.main, [])[2] == 2


def test_pe_warn_rate_limit_bytes(capsys):
    """THE warn contract (issue 275/276 face): first reason prints once,
    same (op, reason) is suppressed, a changed reason prints again."""
    pe.warn("cap292_probe", "r1")
    pe.warn("cap292_probe", "r1")
    pe.warn("cap292_probe", "r2")
    err = capsys.readouterr().err
    assert err == (
        "[kunglao-agent] plan_epistemics WARN (fail-open):"
        " cap292_probe: r1\n"
        "[kunglao-agent] plan_epistemics WARN (fail-open):"
        " cap292_probe: r2\n")


def test_pe_read_register_semantics(tmp_path):
    ws = tmp_path / "reg"
    ws.mkdir()
    assert pe._read_register(ws) == []
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n", encoding="utf-8")
    assert pe._read_register(ws) == [{"id": "C-001", "status": "OPEN"}]
    (ws / "claim-register.yaml").write_text("claims: [broken\n",
                                            encoding="utf-8")
    assert pe._read_register(ws) == []  # fail-open on malformed YAML


# ------------------------------------------------ claim_granularity (241) --

def test_cg_check_ok_face(cg_ws, monkeypatch):
    (cg_ws / "runs" / "plan-C001.md").write_text(GOOD_PLAN, encoding="utf-8")
    patch_argv(monkeypatch, "claim_granularity.py", str(cg_ws),
               "--check", "C-001")
    assert run_face(cg.main) == (
        "OK: plan-C001.md (3 steps <= 8, 2 domain group(s))\n", "", 0)


def test_cg_check_monolithic_guidance(cg_ws, monkeypatch):
    (cg_ws / "runs" / "plan-C001.md").write_text(MONO_PLAN, encoding="utf-8")
    patch_argv(monkeypatch, "claim_granularity.py", str(cg_ws),
               "--check", "C-001")
    out, err, rc = run_face(cg.main)
    assert (out, err, rc) == (
        "GRANULARITY GATE: claim C-001 plan plan-C001.md is monolithic"
        " (plan-size: 12 enumerated steps > GRANULARITY_MAX_STEPS=8)"
        " - split before re-dispatch: run python scripts/"
        "claim_granularity.py <ws> --split C-001"
        " (mint_split_claims: the issue-234 fan-out at creation time)"
        " to mint domain sub-claims with depends_on edges + a"
        " domain_family tag (each unit under GRANULARITY_MAX_STEPS=8"
        " steps), then dispatch the sub-claims; observed split:"
        " unclassified (inferred) steps"
        " [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]\n", "", 1)


def test_cg_check_missing_plan_face(cg_ws, monkeypatch):
    patch_argv(monkeypatch, "claim_granularity.py", str(cg_ws),
               "--check", "C-999")
    assert run_face(cg.main) == (
        "no runs/plan-C-999*.md on disk — nothing to check"
        " (plan-first owns the no-plan case)\n", "", 1)


# ----------------------------------------------------- target_ladder (234) --

def test_tl_check_without_register_passes_open(tl_ws, monkeypatch):
    patch_argv(monkeypatch, "target_ladder.py", str(tl_ws),
               "--check", "C-001")
    assert run_face(tl.main) == (
        "OK: C-001 ladder walked + inventory non-empty + siblings minted\n",
        "", 0)


def test_tl_mint_refuses_missing_register(tl_ws, monkeypatch):
    patch_argv(monkeypatch, "target_ladder.py", str(tl_ws),
               "--mint", "C-001")
    assert run_face(tl.main) == (
        f"REFUSED: no claim-register.yaml under {tl_ws}\n", "", 1)


def test_tl_check_blocker_bytes(tl_ws, monkeypatch):
    (tl_ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n    status: OPEN\n"
        "    origin: failure-obstacle\n"
        "    obstacle_class: heap-probe\n    obstacle_for: C-000\n",
        encoding="utf-8")
    patch_argv(monkeypatch, "target_ladder.py", str(tl_ws),
               "--check", "C-001")
    out, err, rc = run_face(tl.main)
    assert (out, err, rc) == (
        f"TARGET LADDER GATE: obstacle claim C-001 cannot settle CONFIRMED"
        f" (PROVEN) — walk the 3-level target/attack-surface ladder first"
        f" (missing levels: T1,T2,T3 (no ladder artifact)); artifact:"
        f" {tl_ws / 'runs' / 'target-ladder-C-001.yaml'}"
        f" (scripts/target_ladder.py)\n", "", 1)


def test_tl_register_helper_semantics(tmp_path):
    """The three helpers claim_granularity borrows — semantics pinned
    before they move to the shared module (byte-equal port required)."""
    ws = tmp_path / "tlreg"
    ws.mkdir()
    assert tl._load_claims(ws) == ([], None)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-001\n", encoding="utf-8")
    claims, p = tl._load_claims(ws)
    assert claims == [{"id": "C-001"}] and p is not None
    assert tl._claims_from_text("claims: [broken\n") == []  # fail-open
    assert tl._claims_from_text("claims:\n  - id: C-002\n") == \
        [{"id": "C-002"}]
    assert tl._find_claim(claims, "C-001") == {"id": "C-001"}
    assert tl._find_claim(claims, "C-404") is None


def test_tl_load_claims_empty_register_is_not_a_crash(tmp_path):
    """Review-fix round: the base `_load_claims` tolerated a 0-byte /
    null-document register (parse -> None -> `or {}` -> ([], path)).
    The shared port must keep that exact semantics — an empty register
    is fail-open empty, never an AttributeError."""
    ws = tmp_path / "tlempty"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text("", encoding="utf-8")
    claims, p = tl._load_claims(ws)
    assert claims == []
    assert p == ws / "claim-register.yaml"
    # the null-doc YAML spelling of the same degenerate state
    (ws / "claim-register.yaml").write_text("null\n", encoding="utf-8")
    assert tl._load_claims(ws) == ([], ws / "claim-register.yaml")


def test_tl_check_face_empty_register_matches_base_bytes(tl_ws, monkeypatch):
    """The gate-check face on a 0-byte register must produce the same
    bytes it produces with no register at all (fail-open OK face) —
    not a traceback (base behavior, review round)."""
    (tl_ws / "claim-register.yaml").write_text("", encoding="utf-8")
    patch_argv(monkeypatch, "target_ladder.py", str(tl_ws),
               "--check", "C-001")
    assert run_face(tl.main) == (
        "OK: C-001 ladder walked + inventory non-empty + siblings minted\n",
        "", 0)


# -------------------------------------------------- progress_timeline (282) --

EXPECTED_PROGRESS = (
    "# progress.txt — rendered case timeline (issue-282)\n"
    "# source of truth: runs/logs/kunglao-*.jsonl (kunglao_log)"
    " + runs/progress-narrative.jsonl (worker narrative)\n"
    "# rows: E = one ledger event (seq/tick/ts/actor/action/claim"
    " :: detail) | N = narrative entry at its tick\n"
    "# events=1 narrative=0\n"
    "#---\n"
    "E seq=1 tick=5 ts=2026-09-21T10:00:00Z actor=worker"
    " action=evidence_captured claim=C-001 :: found the loader\n"
)


def test_pt_render_and_repair_file_bytes(pt_ws):
    result = pt.render_and_repair(pt_ws)
    assert result == {"status": "rendered", "wrote": True, "reason": None,
                      "events": 1, "narrative": 0}
    written = (pt_ws / "progress.txt").read_text(encoding="utf-8")
    assert written == EXPECTED_PROGRESS


def test_pt_render_and_repair_second_run_no_write(pt_ws):
    pt.render_and_repair(pt_ws)
    assert pt.render_and_repair(pt_ws) == {
        "status": "rendered", "wrote": False, "reason": None,
        "events": 1, "narrative": 0}


def test_pt_render_note(pt_ws):
    pt.render_and_repair(pt_ws)
    assert pt.render_note(pt_ws) == "timeline current (events=1)"


def test_pt_read_events_row_shape(pt_ws):
    assert pt.read_events(pt_ws) == [{
        "ts": "2026-09-21T10:00:00Z", "epoch": 5, "actor": "worker",
        "action": "evidence_captured", "claim": "C-001",
        "detail": "found the loader"}]


# ------------------------------------------------------ settle_by_need (248) --

NEEDS = {"Q1": "yes_no_with_evidence", "Q2": "model_selection"}


def test_sbn_reproduction_settles_generation_side():
    assert sbn.settle_attempt({"answers_question": "Q2"},
                              {"class": "reproduction"}, NEEDS) == {
        "settled": True, "claim_stays_open": False, "reroute_to": None,
        "reason": "reproduction evidence settles the model_selection"
                  " claim (#248)"}


def test_sbn_replay_rerouted_from_generation_side():
    assert sbn.settle_attempt({"answers_question": "Q2"},
                              {"class": "replay-observation"}, NEEDS) == {
        "settled": False, "claim_stays_open": True,
        "reroute_to": "input-contract",
        "reason": "replay observation cannot settle a generation-side"
                  " proposition (need=model_selection) — re-routed to the"
                  " input-contract claim; the algorithm claim stays open"
                  " (#248)"}


def test_sbn_replay_settles_input_contract():
    assert sbn.settle_attempt({"answers_question": "Q1"},
                              {"class": "replay-observation"}, NEEDS) == {
        "settled": True, "claim_stays_open": False, "reroute_to": None,
        "reason": "acceptance-side observation settles an input-contract"
                  " claim (need=yes_no_with_evidence) (#248)"}


def test_sbn_unknown_class_fails_closed():
    assert sbn.settle_attempt({"answers_question": "Q1"},
                              {"class": "weird"}, NEEDS) == {
        "settled": False, "claim_stays_open": True, "reroute_to": None,
        "reason": "evidence class 'weird' is not admissible here — claim"
                  " stays open (#248)"}


# ------------------------------------------------ plan_drift_detector (237) --

def test_pdd_check_no_drift_face(pdd_ws):
    assert run_face(lambda: pdd.check(pdd_ws)) == (
        "OK: no plan drift detected\n", "", 0)


def test_pdd_auto_ok_face(pdd_ws, monkeypatch):
    patch_argv(monkeypatch, "plan_drift_detector.py", str(pdd_ws), "--auto")
    assert run_face(pdd.main) == (
        "OK: no plan drift detected\nDRIFT_AUTO: ok -> proceed\n", "", 0)


def test_pdd_phase_plan_not_orphaned(pdd_ws):
    """v1.9.29 guard: a plan sharing NO claim-id namespace with the
    register is phase-level — no ORPHAN_CLAIM structural false positive."""
    (pdd_ws / "global_plan.txt").write_text("# plan\n- C-002: gone\n",
                                            encoding="utf-8")
    assert run_face(lambda: pdd.check(pdd_ws)) == (
        "OK: no plan drift detected\n", "", 0)


def test_pdd_warn_rate_limit_bytes(capsys):
    pdd.warn("cap292_probe", "r1")
    pdd.warn("cap292_probe", "r1")
    pdd.warn("cap292_probe", "r2")
    err = capsys.readouterr().err
    assert err == (
        "[kunglao-agent] plan_drift_detector WARN (fail-open):"
        " cap292_probe: r1\n"
        "[kunglao-agent] plan_drift_detector WARN (fail-open):"
        " cap292_probe: r2\n")


# --------------------------------------------- shared-module import hygiene --

def test_yaml_still_the_register_grammar():
    """The extraction keeps PyYAML as the single register grammar; the
    shared module must not grow a second parser (sanity pin)."""
    reg = yaml.safe_load("claims:\n  - id: C-001\n") or {}
    assert reg["claims"][0]["id"] == "C-001"
