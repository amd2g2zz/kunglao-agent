#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_settlement_pq_257.py — the settlement->PQ wiring (issue 257).

Wires oracle case settlement to posteriors.py update_eliminate/
update_evidence so ΔH_PQ goes live for the first time: per-event SIGNED
delta_h_bits (h_before − h_after; negative = softening, EXP-3b) plus the
separate h_standing_bits field (the priority_ratio dh quantity), an
idempotent get-or-seed from task_spec primary_questions candidates
(mint-time-writer tolerance), fail-open-with-annotation on unmatched
candidate names (design D1) and on eliminating the last survivor (D3).

Expected numbers are the EXP-3 spike fixture (tests/fixtures/
exp3_delta_h.json) — exact call sequences, 6dp values.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import event_taxonomy
import kunglao_log
import oracle_runner
from posteriors import PQCategorical, PosteriorLedger

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "exp3_delta_h.json").read_text(
        encoding="utf-8"))

PQ_ID = FIXTURE["pq_id"]  # q_jni_registration

BASE_PQ_UPDATE = """\
pq_update:
  green_up:
    static_xref_dlsym: 2.5
  eliminate_on_pass:
    - jni_register_natives
"""


def _case_yaml(pq_update: str = BASE_PQ_UPDATE,
               target_pq: str | None = PQ_ID) -> str:
    lines = ["id: case-a", "channel: device-trace",
             "hypothesis_ref: H-001"]
    if target_pq is not None:
        lines.append(f"target_pq: {target_pq}")
    lines += ["update_map:",
              "  green_up: [H-001]",
              "  red_up: [H-002]",
              "mutations:",
              "  - field: auth_algo",
              "    kind: swap",
              "expected:",
              "  - field: auth_algo",
              "    value: hmac-sha256",
              "    evidence_refs: [F001]"]
    if pq_update:
        lines.append(pq_update.rstrip("\n"))
    return "\n".join(lines) + "\n"


TASK_SPEC = """\
primary_questions:
  - id: {pq_id}
    q: "which mechanism registers the native method?"
    need: model_selection
    candidates:
      - jni_register_natives
      - static_xref_dlsym
      - runtime_dlopen
"""


def _seeded_ledger() -> PosteriorLedger:
    """The EXP-3 situational set: the spike's hand-built priors."""
    return PosteriorLedger(pqs={PQ_ID: PQCategorical(PQ_ID,
                                                     dict(FIXTURE["priors"]))})


def _make_ws(tmp_path: Path, case_yaml: str,
             task_spec: str | None = TASK_SPEC) -> Path:
    (tmp_path / "oracle" / "cases").mkdir(parents=True)
    (tmp_path / "oracle" / "cases" / "case-a.yaml").write_text(
        case_yaml, encoding="utf-8")
    if task_spec is not None:
        (tmp_path / "task_spec.yaml").write_text(
            task_spec.format(pq_id=PQ_ID), encoding="utf-8")
    return tmp_path


def _report(status: str, case_id: str = "case-a") -> dict:
    return {
        "cases": {case_id: {"status": status, "pending_entries": 0,
                            "instrumented": True, "failures": [],
                            "error": None, "forensics": {}}},
        "counts": {"red": 1 if status == "fail" else 0,
                   "green": 1 if status == "pass" else 0,
                   "pending": 1 if status == "pending" else 0},
    }


@pytest.fixture
def events(monkeypatch):
    """Capture kunglao_log.emit calls (producers resolve emit at call
    time — module-attribute patch, same shape as the 157-suite
    fixture)."""
    calls: list[dict] = []

    def _fake(ws, actor, action, **kw):
        calls.append({"ws": ws, "actor": actor, "action": action, **kw})

    monkeypatch.setattr(kunglao_log, "emit", _fake)
    return calls


def _pq_event_rows(calls: list[dict]) -> list[dict]:
    out = []
    for c in calls:
        if c.get("action") != "pq_posterior_update":
            continue
        detail = c.get("detail")
        try:
            detail = json.loads(detail) if isinstance(detail, str) else detail
        except (json.JSONDecodeError, TypeError):
            detail = {"raw": detail}
        out.append(detail if isinstance(detail, dict) else {"raw": detail})
    return out


# ------------------------- EXP-3 fixture numbers ---------------------------

def test_evidence_event_delta_h_matches_exp3_fixture(tmp_path) -> None:
    """Event 1: green_up evidence {static_xref_dlsym: 2.5} on the fixture
    priors -> signed ΔH 0.069654 (6dp), h 1.485475 -> 1.415821."""
    ws = _make_ws(tmp_path, _case_yaml())
    led = _seeded_ledger()
    records = oracle_runner.record_pq_updates(ws, _report("pass"), led)
    assert len(records) == 2  # evidence event + eliminate event, in order
    rec = records[0]
    assert rec["status"] == "applied"
    assert rec["case_id"] == "case-a"
    assert rec["pq_id"] == PQ_ID
    assert rec["channel"] == "evidence"
    assert rec["name"] == "static_xref_dlsym"
    assert rec["strength"] == pytest.approx(2.5)
    assert rec["delta_h_bits"] == pytest.approx(0.069654, abs=1e-6)
    assert rec["h_before_bits"] == pytest.approx(1.485475, abs=1e-6)
    assert rec["h_after_bits"] == pytest.approx(1.415821, abs=1e-6)
    # standing entropy is the SEPARATE field (equal to h_after per event)
    assert rec["h_standing_bits"] == pytest.approx(1.415821, abs=1e-6)


def test_eliminate_event_delta_h_is_largest_in_fixture_sequence(
        tmp_path) -> None:
    """Events 1-3 as three settlements on one ledger: deltas
    0.069654 / 0.673333 / 0.405198; the elimination is the largest single
    ΔH; standing entropy after the sequence is 0.337290 (the EXP-3
    priority_ratio price is nonzero from then on)."""
    ws = _make_ws(tmp_path, _case_yaml())
    led = _seeded_ledger()
    deltas = []
    for status, pq_update in (
            ("pass", "pq_update:\n  green_up:\n"
                     "    static_xref_dlsym: 2.5"),
            ("pass", "pq_update:\n  eliminate_on_pass:\n"
                     "    - jni_register_natives"),
            ("pass", "pq_update:\n  green_up:\n"
                     "    runtime_dlopen: 0.25")):
        (ws / "oracle" / "cases" / "case-a.yaml").write_text(
            _case_yaml(pq_update=pq_update), encoding="utf-8")
        records = oracle_runner.record_pq_updates(ws, _report(status), led)
        assert records and records[-1]["status"] == "applied"
        deltas.append(records[-1]["delta_h_bits"])
    assert deltas[0] == pytest.approx(0.069654, abs=1e-6)
    assert deltas[1] == pytest.approx(0.673333, abs=1e-6)
    assert deltas[2] == pytest.approx(0.405198, abs=1e-6)
    assert max(deltas) == deltas[1]  # elimination is the largest single ΔH
    assert led.pqs[PQ_ID].entropy() == pytest.approx(0.337290, abs=1e-6)


def test_softening_records_negative_signed_delta(tmp_path) -> None:
    """EXP-3b control: strength 0.5 on the leader RAISES entropy — the
    signed convention keeps delta_h_bits = -0.185269, unclamped, with
    h_standing_bits (0.522559) as its own field."""
    ws = _make_ws(tmp_path, _case_yaml(
        pq_update="pq_update:\n  green_up:\n"
                  "    static_xref_dlsym: 0.5"))
    led = PosteriorLedger(pqs={PQ_ID: PQCategorical(
        PQ_ID, {"static_xref_dlsym": 0.9375, "runtime_dlopen": 0.0625})})
    records = oracle_runner.record_pq_updates(ws, _report("pass"), led)
    assert records[0]["delta_h_bits"] == pytest.approx(-0.185269, abs=1e-6)
    assert records[0]["delta_h_bits"] < 0  # signed, NOT clamped
    assert records[0]["h_standing_bits"] == pytest.approx(0.522559,
                                                          abs=1e-6)
    assert records[0]["h_before_bits"] == pytest.approx(0.337290, abs=1e-6)


# ------------------------------- persistence -------------------------------

def test_ledger_round_trip_persists_pqs(tmp_path) -> None:
    """record_posteriors end-to-end (fixture priors pre-saved on disk):
    the settled categorical survives the save/load round-trip exactly."""
    ws = _make_ws(tmp_path, _case_yaml())
    _seeded_ledger().save(ws)
    path = oracle_runner.record_posteriors(ws, _report("pass"))
    assert path is not None and path.exists()
    reloaded = PosteriorLedger.load(ws)
    assert reloaded.degraded is False
    assert PQ_ID in reloaded.pqs
    # evidence event then elimination, per the declared order
    assert reloaded.pqs[PQ_ID].probs["jni_register_natives"] == 0.0
    assert reloaded.pqs[PQ_ID].probs["static_xref_dlsym"] == \
        pytest.approx(0.789474, abs=1e-6)


def test_pq_id_matches_priority_ratio_keying(tmp_path) -> None:
    """pq_id is the answers_question/target_pq string priority_ratio keys
    on (priority_ratio.py :690/:714) — the ranker consumption lights up."""
    ws = _make_ws(tmp_path, _case_yaml())
    oracle_runner.record_posteriors(ws, _report("pass"))
    led = PosteriorLedger.load(ws)
    answers_question = PQ_ID  # case target_pq == claim answers_question
    pq_cat = led.pqs.get(answers_question)
    assert pq_cat is not None
    assert pq_cat.entropy() > 0.0  # settlement bookkeeping delta is real (ΔH no longer priced — #295)
    assert pq_cat.argmax() == "static_xref_dlsym"


# ------------------------------ fail-open D1 -------------------------------

def test_unmatched_candidate_fails_open_with_annotation(
        tmp_path, events) -> None:
    """KeyError on an unknown candidate name -> skipped annotation, the
    valid event still applies with its measured ΔH, no crash (D1)."""
    ws = _make_ws(tmp_path, _case_yaml(
        pq_update="pq_update:\n  green_up:\n    ghost_candidate: 2.5\n"
                  "    static_xref_dlsym: 2.5\n"
                  "  eliminate_on_pass:\n    - jni_register_natives"))
    led = _seeded_ledger()
    records = oracle_runner.record_pq_updates(ws, _report("pass"), led)
    by_name = {r["name"]: r for r in records if r["name"]}
    assert by_name["ghost_candidate"]["status"] == "skipped"
    assert by_name["ghost_candidate"]["reason"]
    assert by_name["static_xref_dlsym"]["status"] == "applied"
    assert by_name["static_xref_dlsym"]["delta_h_bits"] == pytest.approx(
        0.069654, abs=1e-6)
    # the skip is auditable in the event tail too
    skipped = [d for d in _pq_event_rows(events)
               if d.get("name") == "ghost_candidate"]
    assert skipped and skipped[0]["status"] == "skipped"


# ---------------------------- settled-PQ guard -----------------------------

def test_settled_pq_last_candidate_eliminate_guard(tmp_path) -> None:
    """Eliminating the last survivor is an annotated no-op (D3), never the
    library ValueError. Eliminated candidates stay as 0.0 keys — the guard
    counts NONZERO mass, not dict length."""
    ws = _make_ws(tmp_path, _case_yaml(
        pq_update="pq_update:\n  eliminate_on_pass:\n"
                  "    - runtime_dlopen"))
    led = PosteriorLedger(pqs={PQ_ID: PQCategorical(
        PQ_ID, {"static_xref_dlsym": 0.9, "runtime_dlopen": 0.1})})
    recs = oracle_runner.record_pq_updates(ws, _report("pass"), led)
    assert recs[0]["status"] == "applied"
    assert led.pqs[PQ_ID].probs["static_xref_dlsym"] == pytest.approx(1.0)
    assert led.pqs[PQ_ID].probs["runtime_dlopen"] == 0.0  # zero-mass remnant
    # drive the settled PQ again: eliminating the sole survivor skips
    recs2 = oracle_runner.record_pq_updates(ws, _report("pass"), led)
    assert recs2 and recs2[0]["status"] == "skipped"
    assert "settled" in recs2[0]["reason"] or "survivor" in recs2[0]["reason"]
    assert led.pqs[PQ_ID].probs["static_xref_dlsym"] == pytest.approx(1.0)


# -------------------------------- seeding ----------------------------------

def test_seed_from_task_spec_uniform_and_idempotent(tmp_path) -> None:
    """Absent pq -> seeded uniform from task_spec candidates; an existing
    (settled) pq is NEVER reseeded (mint-time writer tolerance)."""
    ws = _make_ws(tmp_path, _case_yaml())
    led = PosteriorLedger()
    pq = oracle_runner.ensure_pq(led, ws, PQ_ID)
    assert pq is not None
    assert led.pqs[PQ_ID] is pq
    assert pq.probs["jni_register_natives"] == pytest.approx(1 / 3)
    assert pq.probs["static_xref_dlsym"] == pytest.approx(1 / 3)
    assert pq.probs["runtime_dlopen"] == pytest.approx(1 / 3)
    # settle it away from uniform, then re-ensure: no reseed
    pq.update_eliminate("runtime_dlopen")
    settled = pq.probs
    again = oracle_runner.ensure_pq(led, ws, PQ_ID)
    assert again is pq
    assert again.probs == settled


def test_end_to_end_seeds_when_absent(tmp_path) -> None:
    """record_posteriors with an EMPTY ledger seeds from task_spec and
    applies the declared events (the first-real-settlement acceptance:
    ΔH nonzero for the first time on a real settlement)."""
    ws = _make_ws(tmp_path, _case_yaml())
    path = oracle_runner.record_posteriors(ws, _report("pass"))
    assert path is not None
    led = PosteriorLedger.load(ws)
    assert PQ_ID in led.pqs
    assert led.pqs[PQ_ID].entropy() < 1.0  # events moved it off uniform H


# ------------------------------ no-op faces --------------------------------

def test_pending_and_missing_declaration_are_noops(tmp_path) -> None:
    """Pending verdicts, missing target_pq, missing pq_update: no records,
    no pqs key, no crash. Unknown pq with no task_spec entry -> annotated
    seed skip, no categorical invented."""
    led = _seeded_ledger()
    ws = _make_ws(tmp_path, _case_yaml())
    assert oracle_runner.record_pq_updates(ws, _report("pending"), led) == []

    ws2 = _make_ws(tmp_path / "w2", _case_yaml(target_pq=None))
    led2 = _seeded_ledger()
    assert oracle_runner.record_pq_updates(ws2, _report("pass"), led2) == []

    ws3 = _make_ws(tmp_path / "w3", _case_yaml(pq_update=""))
    led3 = _seeded_ledger()
    assert oracle_runner.record_pq_updates(ws3, _report("pass"), led3) == []

    ws4 = _make_ws(tmp_path / "w4", _case_yaml(), task_spec=None)
    led4 = PosteriorLedger()
    records = oracle_runner.record_pq_updates(ws4, _report("pass"), led4)
    assert records and all(r["status"] == "skipped" for r in records)
    assert PQ_ID not in led4.pqs


def test_malformed_declaration_is_annotated_not_fatal(tmp_path) -> None:
    """A wrong-shaped pq_update value is a per-case annotated skip (D4) —
    never a refusal into the settlement path."""
    ws = _make_ws(tmp_path, _case_yaml(pq_update="pq_update: not-a-mapping"))
    led = _seeded_ledger()
    records = oracle_runner.record_pq_updates(ws, _report("pass"), led)
    assert records
    assert all(r["status"] == "skipped" for r in records)
    assert all(r.get("reason") for r in records)


# ------------------------------ event face ---------------------------------

def test_emitted_events_use_registered_word(tmp_path, events) -> None:
    """Applied + skipped PQ events emit `pq_posterior_update` rows (a
    registered EMIT_ACTIONS word) carrying the signed delta."""
    assert "pq_posterior_update" in event_taxonomy.EMIT_ACTIONS
    ws = _make_ws(tmp_path, _case_yaml())
    _seeded_ledger().save(ws)  # fixture priors, so deltas are the fixture's
    oracle_runner.record_posteriors(ws, _report("pass"))
    rows = _pq_event_rows(events)
    assert rows, "expected pq_posterior_update event rows"
    applied = [d for d in rows if d.get("status") == "applied"]
    assert applied
    assert applied[0]["pq_id"] == PQ_ID
    assert applied[0]["delta_h_bits"] == pytest.approx(0.069654, abs=1e-6)
