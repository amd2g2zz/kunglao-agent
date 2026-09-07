# -*- coding: utf-8 -*-
"""tests/test_oracle_cadence_132.py — #132 oracle reward channel mechanical cadence.

The oracle red/green channel (#97/#108) was wired-but-blind at the input
side: scripts/oracle_runner.py had NO mechanical caller in the live loop —
its only production reference was an instruction embedded in a decide action
string, so whether the reward signal ever fired depended on the orchestrator
LLM obeying a sentence. This file pins the settlement-cadence contract that
replaces LLM-obedience triggering with a mechanical hook:

  1. Settlement cadence: capturing + settling a claim mechanically runs the
     armed case set against the registered client
     (``<ws>/oracle/client.py``, the #108 load_client contract shape) and
     records posteriors — the test drives ONLY outcome_capture.capture();
     there is no prompt, instruction or LLM artifact anywhere in the path.
  2. Fail-loud, never silent skip: a broken registered client is ALL-RED
     (every armed case lands red + ``oracle_cadence_warn`` event), a missing
     client with armed cases is a loud warn, a refused case set is a loud
     warn — and capture/settlement/banking still succeed (the cadence never
     breaks its host, the #110 fail-open precedent).
  3. Loud missing-intent: a captured outcome for a claim with NO recorded
     dispatch intent emits the #105 ``intent_unparsed`` word at the
     settlement face (dispatch flow unchanged, no hard reject) and the
     census (``missing_intent_face``) makes the absence COUNTED and visible
     on the cockpit face (tuition_curve.cockpit_summary carries it
     additively).
  4. #132 amendment — SEPARATION observation at cadence: when a case has
     greened under >=2 DISTINCT candidate client implementations, emit
     ``case_vacuous`` (the case measures the environment, not the model —
     the empirical twin of #126's declared update_map tooth). Single-client
     green emits nothing; a re-run of the SAME client emits nothing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kunglao_log  # noqa: E402
import oracle_cadence as cad  # noqa: E402  (RED: module absent)
import outcome_capture as oc  # noqa: E402
import posteriors as po  # noqa: E402
import roi_settlement as roi  # noqa: E402
from event_taxonomy import EMIT_ACTIONS  # noqa: E402


# ---------------------------------------------------------------- fixtures

HYP_A = "H-201"      # competitor_group: grp-cad (open)
HYP_B = "H-202"      # grp-cad's second OPEN member (live competition)

CASE_ID = "cadence-auth"

GOOD_CLIENT = (
    "def compute(params):\n"
    "    return {'auth_algo': 'hmac-sha256'}\n"
)

# A DIFFERENT candidate implementation that greens the same case: distinct
# source bytes -> distinct client fingerprint (#132 separation observation).
GOOD_CLIENT_V2 = (
    "# candidate 2 — an independent implementation of the same bet\n"
    "def compute(params):\n"
    "    return {'auth_algo': 'hmac-sha256', 'impl': 2}\n"
)

BROKEN_CLIENT = "raise RuntimeError('client exploded at import')\n"

ARMED_CASE = {
    "id": CASE_ID,
    "channel": "device-trace",
    "hypothesis_ref": HYP_A,
    "update_map": {"green_up": [HYP_A, HYP_B], "red_up": [HYP_B]},
    "params": {"user": "alice"},
    "expected": [
        {"field": "auth_algo", "value": "hmac-sha256",
         "evidence_refs": ["F001"]},
    ],
    "mutations": [{"field": "auth_algo", "kind": "swap"}],
}


def _write_hypothesis(ws: Path, hyp_id: str, group: str) -> None:
    p = ws / "hypotheses" / f"{hyp_id}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "---\n"
        f"id: {hyp_id}\n"
        "claim_id: C-1\n"
        f"competitor_group: {group}\n"
        "candidates: [AES, ChaCha20]\n"
        "status: open\n"
        "schema_rev: 1\n"
        "---\n"
        "\npq:q1\n\nSeeded scaffold — the armed case realizes this bet.\n",
        encoding="utf-8")


def _write_case(ws: Path, case: dict, name: str = "armed-case.yaml") -> Path:
    p = ws / "oracle" / "cases" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        yaml.safe_dump(case, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return p


def _write_client(ws: Path, source: str) -> Path:
    p = ws / "oracle" / "client.py"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(source, encoding="utf-8")
    return p


def _mk_ws(tmp_path: Path, *, intent: bool = True) -> Path:
    """Fixture workspace: armed case set (satisfies the #126 admission
    contract), a resolvable fact anchor, and one claimed outcome waiting to
    settle (C-1, intent recorded unless ``intent=False``)."""
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "facts" / "F001.md").write_text(
        "# F001\n\nauth_algo pins hmac-sha256 (byte-anchored).\n",
        encoding="utf-8")
    _write_hypothesis(ws, HYP_A, "grp-cad")
    _write_hypothesis(ws, HYP_B, "grp-cad")
    _write_case(ws, ARMED_CASE)
    (ws / "runs").mkdir()
    if intent:
        roi.record_intent(ws, "C-1", method="static-derive",
                          context_tags=["android"],
                          uncertainty="which auth algo the binary uses",
                          expected_artifact="")
    _verify_note(ws, "a-verify-01.md", "C-1", "passes")
    return ws


def _verify_note(ws: Path, name: str, claim_id: str, verdict: str) -> None:
    runs = ws / "runs"
    runs.mkdir(exist_ok=True)
    (runs / name).write_text(
        f"---\nclaim_id: {claim_id}\n---\n\n## Overall verdict\n{verdict}\n",
        encoding="utf-8")


def _record_intent(ws: Path, claim_id: str) -> None:
    roi.record_intent(ws, claim_id, method="static-derive",
                      context_tags=["android"],
                      uncertainty=f"uncertainty of {claim_id}",
                      expected_artifact="")


def _record_emits(monkeypatch) -> list[dict]:
    """Seam-capture every kunglao_log.emit call (call-through recorder, the
    test_case_bank_110 pattern — the real row still lands on the log)."""
    calls: list[dict] = []
    real_emit = kunglao_log.emit

    def _recorder(ws, actor, action, **kw):
        calls.append({"actor": actor, "action": action, **kw})
        return real_emit(ws, actor, action, **kw)

    monkeypatch.setattr(kunglao_log, "emit", _recorder)
    return calls


def _log_events(ws: Path) -> list[dict]:
    """Durable rows from the unified log (the loudness proof is the FILE)."""
    out: list[dict] = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8",
                                errors="replace").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# --------------------------------- 1. the cadence is mechanical (no LLM)

def test_settling_claim_runs_oracle_mechanically(tmp_path: Path) -> None:
    """Acceptance: settling a claim runs the armed cases + moves posteriors
    mechanically. The driver is outcome_capture.capture() ALONE — zero LLM
    instruction exists anywhere in the path (the hook is a function call,
    not a sentence)."""
    ws = _mk_ws(tmp_path)
    _write_client(ws, GOOD_CLIENT)
    assert not (ws / "runs" / "oracle-status.json").exists()
    assert not (ws / "runs" / "posteriors.yaml").exists()

    added = oc.capture(ws)

    assert added == 1
    status = json.loads(
        (ws / "runs" / "oracle-status.json").read_text(encoding="utf-8"))
    assert status["counts"] == {"red": 0, "green": 1, "pending": 0}
    led = po.PosteriorLedger.load(ws)
    case = led.cases[CASE_ID]
    assert case.alpha == 2.0 and case.beta == 1.0, \
        "the green verdict must land as a Bernoulli observation"
    rows = cad.read_cadence_rows(ws)
    assert rows and rows[-1]["case_id"] == CASE_ID
    assert rows[-1]["status"] == "pass"


def test_each_new_settlement_feeds_the_channel(tmp_path: Path) -> None:
    """Each capture batch that settles feeds the channel: a later settlement
    runs the cadence again under the CURRENT registered client, so a wrong
    implementation lands the red observation mechanically (the case observes
    the model-under-test, not the claim's verify verdict)."""
    ws = _mk_ws(tmp_path)
    _write_client(ws, GOOD_CLIENT)
    oc.capture(ws)
    wrong = _write_client(ws, GOOD_CLIENT.replace("'hmac-sha256'", "'des'"))
    assert wrong.name == "client.py"
    _record_intent(ws, "C-2")
    _verify_note(ws, "b-verify-02.md", "C-2", "passes")
    oc.capture(ws)

    led = po.PosteriorLedger.load(ws)
    case = led.cases[CASE_ID]
    assert case.alpha == 2.0 and case.beta == 2.0


def test_duplicate_settlement_does_not_refire_cadence(tmp_path: Path) -> None:
    """A replayed capture (ledger deleted, same verify file — the #110
    pattern) settles NOTHING new, so the cadence must not refire: identical
    observations must not double-count into the posterior."""
    ws = _mk_ws(tmp_path)
    _write_client(ws, GOOD_CLIENT)
    oc.capture(ws)
    alpha = po.PosteriorLedger.load(ws).cases[CASE_ID].alpha

    (ws / oc.LEDGER_NAME).unlink()
    oc.capture(ws)

    assert po.PosteriorLedger.load(ws).cases[CASE_ID].alpha == alpha == 2.0


# -------------------------- 2. fail-loud faces (never a silent skip)

def test_broken_client_is_all_red_with_loud_warn(tmp_path: Path,
                                                 monkeypatch) -> None:
    """A registered client that cannot even import is ALL-RED (every armed
    case lands red + posteriors take the red observations) and the
    ``oracle_cadence_warn`` event hits the durable log — never "skip"."""
    ws = _mk_ws(tmp_path)
    _write_client(ws, BROKEN_CLIENT)
    calls = _record_emits(monkeypatch)

    oc.capture(ws)

    status = json.loads(
        (ws / "runs" / "oracle-status.json").read_text(encoding="utf-8"))
    assert status["counts"] == {"red": 1, "green": 0, "pending": 0}
    led = po.PosteriorLedger.load(ws)
    assert led.cases[CASE_ID].beta == 2.0 and led.cases[CASE_ID].alpha == 1.0
    durable = [e for e in _log_events(ws)
               if e.get("action") == "oracle_cadence_warn"]
    assert durable and "client_broken" in str(durable[0].get("detail"))
    assert any(c["action"] == "oracle_cadence_warn"
               and "client_broken" in str(c.get("detail")) for c in calls)


def test_missing_client_with_armed_cases_is_loud(tmp_path: Path,
                                                 monkeypatch) -> None:
    """Armed cases but NO registered client: the reward channel cannot fire
    — that must be a loud warn, never a silent skip, and it must fabricate
    no observation (no green status, no posterior movement)."""
    ws = _mk_ws(tmp_path)  # no oracle/client.py
    calls = _record_emits(monkeypatch)

    oc.capture(ws)

    durable = [e for e in _log_events(ws)
               if e.get("action") == "oracle_cadence_warn"]
    assert durable and "client_not_registered" in str(durable[0].get("detail"))
    assert any(c["action"] == "oracle_cadence_warn"
               and "client_not_registered" in str(c.get("detail"))
               for c in calls)
    assert not (ws / "runs" / "oracle-status.json").exists()
    assert not (ws / "runs" / "posteriors.yaml").exists()


def test_refused_case_set_is_loud_and_never_blocks_capture(
        tmp_path: Path, monkeypatch) -> None:
    """A case set that fails the #126 admission lint is a loud warn (the
    runner's refusal contract: no status file), while the settlement +
    banking host flow proceeds untouched."""
    ws = _mk_ws(tmp_path)
    _write_client(ws, GOOD_CLIENT)
    bad = dict(ARMED_CASE)
    bad["id"] = "bad-refs"
    bad["expected"] = [
        {"field": "auth_algo", "value": "hmac-sha256",
         "evidence_refs": ["F999"]}]
    bad["mutations"] = [{"field": "auth_algo", "kind": "swap"}]
    _write_case(ws, bad, "bad-case.yaml")
    calls = _record_emits(monkeypatch)

    added = oc.capture(ws)

    assert added == 1, "capture itself must succeed"
    assert len(roi.read_settlements(ws)) == 1
    warns = [c for c in calls if c["action"] == "oracle_cadence_warn"]
    assert any("case_set_refused" in str(c.get("detail")) for c in warns)
    assert not (ws / "runs" / "oracle-status.json").exists()


def test_cadence_faces_run_the_mutation_pass(tmp_path: Path) -> None:
    """The #108 mutation-must-fail discipline runs ROUTINELY at cadence (not
    discretionary): the status file carries the mutation result face."""
    ws = _mk_ws(tmp_path)
    _write_client(ws, GOOD_CLIENT)
    oc.capture(ws)
    status = json.loads(
        (ws / "runs" / "oracle-status.json").read_text(encoding="utf-8"))
    # the armed case declares auth_algo/swap: the mutated client must turn
    # the case red, so nothing is flagged low-discriminativity
    assert status.get("low_discriminativity") == []


# ------------------------- 3. loud missing-intent (counted, not gating)

def test_unintended_outcome_is_loud_and_counted(tmp_path: Path,
                                                monkeypatch) -> None:
    """A captured outcome for a claim with NO recorded intent: the
    settlement face emits the #105 ``intent_unparsed`` word (loud, counted)
    and the census names the claim — the absence becomes visible instead of
    hiding as an UNRESOLVED non-settlement."""
    ws = _mk_ws(tmp_path, intent=False)
    _write_client(ws, GOOD_CLIENT)
    calls = _record_emits(monkeypatch)

    oc.capture(ws)

    assert any(c["action"] == "intent_unparsed"
               and "NO_INTENT" in str(c.get("detail")) for c in calls)
    durable = [e for e in _log_events(ws)
               if e.get("action") == "intent_unparsed"]
    assert durable, "the loud face must be durable on the unified log"
    face = cad.missing_intent_face(ws)
    assert face["intent_unparsed_events"] >= 1
    assert "C-1" in face["unintended_outcome_claims"]


def test_undeclared_intent_dispatch_is_counted(tmp_path: Path) -> None:
    """Acceptance: an undeclared-intent DISPATCH (no uncertainty in the
    prompt, #105's fail-open face) is COUNTED by the census — the cockpit
    answer to 'how much of the comparison signal is missing'."""
    from test_dispatch_intent_105 import _mk_ws as _mk105, _run_gate
    root = tmp_path
    ws = _mk105(root)
    proc = _run_gate(root, ws,
                     "[T1 tools=Read,Write] claim C-1 sweep with no "
                     "declaration")
    assert proc.returncode == 0
    face = cad.missing_intent_face(ws)
    assert face["intent_unparsed_events"] >= 1


def test_cockpit_summary_surfaces_intent_face(tmp_path: Path) -> None:
    """The census rides the cockpit face (tuition_curve.cockpit_summary,
    additive + fail-open like the #882 trio)."""
    import mission_ledger
    import tuition_curve as tc

    ws = _mk_ws(tmp_path, intent=False)
    mission_ledger.init(ws, {"primary_questions": ["q1"]})
    oc.capture(ws)
    summary = tc.cockpit_summary(ws)
    assert summary["intent"]["intent_unparsed_events"] >= 1
    assert "C-1" in summary["intent"]["unintended_outcome_claims"]


# -------------------------- 4. #132 amendment: separation observation

def test_case_vacuous_fires_on_second_green_client(tmp_path: Path,
                                                   monkeypatch) -> None:
    """Two DISTINCT candidate clients both green the case -> the case's
    outcome is invariant across the hypothesis space -> ``case_vacuous``.
    A single-client green emits nothing; a re-run of the SAME client emits
    nothing more."""
    ws = _mk_ws(tmp_path)
    _write_client(ws, GOOD_CLIENT)
    first = _record_emits(monkeypatch)
    oc.capture(ws)
    assert not any(c["action"] == "case_vacuous" for c in first), \
        "single-client green: no vacuous observation"

    # a SECOND settlement runs the cadence under a DIFFERENT candidate client
    _write_client(ws, GOOD_CLIENT_V2)
    _record_intent(ws, "C-2")
    _verify_note(ws, "b-verify-02.md", "C-2", "passes")
    second = _record_emits(monkeypatch)
    oc.capture(ws)
    vacuous = [c for c in second if c["action"] == "case_vacuous"]
    assert len(vacuous) == 1
    assert CASE_ID in str(vacuous[0].get("detail"))

    # the same client again -> already observed, no re-fire
    _record_intent(ws, "C-3")
    _verify_note(ws, "c-verify-03.md", "C-3", "passes")
    third = _record_emits(monkeypatch)
    oc.capture(ws)
    assert not any(c["action"] == "case_vacuous" for c in third)


# --------------------------------------------- 5. vocabulary registration

def test_cadence_emit_words_are_registered() -> None:
    """Emit-face words come from the controlled vocabulary (#459; the
    emit_gate forward net also demands a production emitter literal)."""
    assert "oracle_cadence_warn" in EMIT_ACTIONS
    assert "case_vacuous" in EMIT_ACTIONS
