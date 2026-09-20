# -*- coding: utf-8 -*-
"""tests/test_terminal_settlement_136.py — terminal credit assignment (issue 136).

Issue 136 (v0.1.6 P1 slice): at master-oracle-green closure the loop writes
ONE task-terminal settlement row back-referencing the enabling chain — the
case-green lineage that led to closure, read from the issue-130 reference graph
(cases -> hypotheses -> claims) in the CLOSURE direction — plus the
premise_corrections that fired en route. The row lands in the EXISTING
settlement/ledger surface (kunglao_log.emit, runs/logs/kunglao-*.jsonl —
the same organ claim_settled rows use; the no-new-organs doctrine, issue 137)..

Consumption (issue 136 fix point 3): case_bank.retrieve weights terminal-chain
entries above mid-loop entries WITHIN each roi class (owner ruling 4's
failures-first class rank stays the primary sort — a chain lesson is worth
more than a mid-loop lesson, but a counterexample still outranks a
positive). hypothesis_seeder.seed_case_candidates consumes retrieve(), so
cold-start priors inherit the ordering.

All fixtures here are SYNTHETIC (privacy rule: no real workspace data).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from _factories import write_claims_register  # noqa: E402
from convergence_check import decide  # noqa: E402

ACTION = "task_terminal_settlement"


# ---------- synthetic workspace builders ----------

_CASE_YAML = """\
id: {case_id}
channel: device-trace
hypothesis_ref: {hyp_ref}
update_map:
  green_up: [{hyp_ref}]
  red_up: []
params: {{user: alice}}
expected:
  - field: auth_algo
    value: hmac-sha256
    pending-observation: true
mutations:
  - field: auth_algo
    kind: swap
"""


def _base_ws(tmp_path: Path) -> Path:
    """Synthetic closure-ready workspace (the RED4 completeness-test shape + oracle face).

    Two PROVEN claims answering two primary questions, zero orphans, all
    oracle cases green, two CONFIRMED hypotheses — decide() reads CONVERGED.
    """
    ws = tmp_path / "ws-terminal"
    ws.mkdir(parents=True)
    (ws / "runs").mkdir()
    write_claims_register(ws, [
        {"id": "C-101", "status": "PROVEN", "answers_question": "q1"},
        {"id": "C-102", "status": "PROVEN", "answers_question": "q2"},
    ])
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n  - q1: family\n  - q2: C2 config\n",
        encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text("# _INDEX\n", encoding="utf-8")

    # master-green face: both cases pass (the oracle status-file shape)
    (ws / "runs" / "oracle-status.json").write_text(json.dumps({
        "schema": "oracle-status/1",
        "cases": {
            "case-a": {"status": "pass", "pending_entries": 0,
                       "instrumented": True},
            "case-b": {"status": "pass", "pending_entries": 0,
                       "instrumented": True},
        },
        "low_discriminativity": [],
        "counts": {"red": 0, "green": 2, "pending": 0},
    }), encoding="utf-8")

    # the issue-130 reference graph, cases leg: case -> hypothesis
    cases_dir = ws / "oracle" / "cases"
    cases_dir.mkdir(parents=True)
    (cases_dir / "case-a.yaml").write_text(
        _CASE_YAML.format(case_id="case-a", hyp_ref="H-001"), encoding="utf-8")
    (cases_dir / "case-b.yaml").write_text(
        _CASE_YAML.format(case_id="case-b", hyp_ref="H-002"), encoding="utf-8")

    # the graph, hypotheses leg: hypothesis -> claim
    (ws / "hypotheses").mkdir()
    (ws / "hypotheses" / "H-001.md").write_text(
        "---\nid: H-001\nclaim_id: C-101\ncompetitor_group: pq-q1\n"
        "candidates: [AES]\nstatus: confirmed\nschema_rev: 1\n---\n\n# H-001\n",
        encoding="utf-8")
    (ws / "hypotheses" / "H-002.md").write_text(
        "---\nid: H-002\nclaim_id: C-102\ncompetitor_group: pq-q2\n"
        "candidates: [ChaCha20]\nstatus: confirmed\nschema_rev: 1\n---\n\n"
        "# H-002\n", encoding="utf-8")
    return ws


def _seed_ledger(ws: Path) -> None:
    """Green order + claim settlements as REAL ledger rows (append order is
    the order the chain reader must recover — case-a greened FIRST)."""
    from kunglao_log import emit
    for case_id, status in (("case-a", "pass"), ("case-b", "pass")):
        emit(ws, actor="oracle_runner", action="observation",
             detail=json.dumps({"case_id": case_id, "status": status,
                                "forensics": {}}))
    for cid in ("C-101", "C-102"):
        emit(ws, actor="hook:write_guard", action="claim_settled", claim=cid,
             detail=json.dumps({"from": "IN_PROGRESS", "to": "PROVEN",
                                "tools": [], "outcome": "PROVEN"}))


def _seed_case_bank(ws: Path, entries: list[dict]) -> None:
    import case_bank
    for e in entries:
        case_bank.append(ws, e)


def _terminal_rows(ws: Path) -> list[dict]:
    from kunglao_log import tail
    return [r for r in tail(ws, 10 ** 6)
            if r.get("action") == ACTION]


def _chain_of(ws: Path) -> list[dict]:
    rows = _terminal_rows(ws)
    assert rows, "no terminal settlement row in the ledger"
    detail = json.loads(rows[-1].get("detail") or "{}")
    return detail.get("chain") or []


# =====================================================================
# writer: closure -> one terminal row with the correct enabling chain
# =====================================================================

def test_closure_writes_terminal_row_with_enabling_chain(tmp_path):
    """Master-green fixture: the terminal row exists and its chain reads the
    issue-130 graph closure-side in GREEN ORDER (case-a before case-b), each leg
    resolved case -> hypothesis -> claim."""
    from terminal_settlement import write_terminal_settlement
    ws = _base_ws(tmp_path)
    _seed_ledger(ws)

    res = write_terminal_settlement(ws)
    assert res.get("written") is True

    rows = _terminal_rows(ws)
    assert len(rows) == 1, "exactly one terminal settlement row"
    detail = json.loads(rows[0].get("detail") or "{}")
    assert detail.get("schema") == "task-terminal-settlement/1"

    chain = detail["chain"]
    assert [c["case_id"] for c in chain] == ["case-a", "case-b"], \
        "chain order must be the case-green order, not alphabetical"
    assert [c["order"] for c in chain] == [1, 2]
    assert [c["hypothesis_ref"] for c in chain] == ["H-001", "H-002"]
    assert [c["claim_id"] for c in chain] == ["C-101", "C-102"]

    # the settlements the arc closed, in settlement order
    assert detail["claims_settled"] == [
        {"claim": "C-101", "to": "PROVEN"},
        {"claim": "C-102", "to": "PROVEN"},
    ]


def test_terminal_row_carries_premise_corrections(tmp_path):
    """premise_corrections fired en route ride the terminal row (issue 136 fix
    point 2: the mission's 'what worked' in ONE queryable artifact)."""
    from terminal_settlement import write_terminal_settlement
    ws = _base_ws(tmp_path)
    _seed_ledger(ws)
    _seed_case_bank(ws, [
        {"claim_id": "C-101", "method": "ida-struct", "roi_class": "POSITIVE",
         "context_tags": ["packed"],
         "premise_correction": "assumed AES-128; key schedule showed 256"},
        {"claim_id": "C-888", "method": "strings-scan", "roi_class": "POSITIVE",
         "context_tags": ["packed"]},  # no correction
    ])

    write_terminal_settlement(ws)
    rows = _terminal_rows(ws)
    detail = json.loads(rows[0].get("detail") or "{}")
    corr = detail["premise_corrections"]
    assert len(corr) == 1, "only the entry WITH a correction rides the row"
    assert corr[0]["claim_id"] == "C-101"
    assert "key schedule" in corr[0]["premise_correction"]
    assert corr[0]["in_chain"] is True


def test_decide_converged_hooks_the_writer(tmp_path):
    """The closure POINT is convergence_check.decide(): a CONVERGED verdict
    writes the row (emit path on); the decide() dict itself is untouched
    (byte-frozen anchors — the ledger row IS the artifact)."""
    ws = _base_ws(tmp_path)
    _seed_ledger(ws)
    d = decide(ws)
    assert d["decision"] == "CONVERGED"
    rows = _terminal_rows(ws)
    assert len(rows) == 1, "CONVERGED decide() must write the terminal row"
    assert rows[0].get("actor") == "convergence_check"


# =====================================================================
# idempotency + edge cases
# =====================================================================

def test_closure_twice_is_one_row(tmp_path):
    """Repeated CONVERGED ticks must not stack rows (arc dedup: no NEW
    settlements since the last terminal row -> no second write)."""
    from terminal_settlement import write_terminal_settlement
    ws = _base_ws(tmp_path)
    _seed_ledger(ws)
    assert write_terminal_settlement(ws)["written"] is True
    assert write_terminal_settlement(ws).get("duplicate") is True
    assert len(_terminal_rows(ws)) == 1


def test_reopen_then_reclose_opens_a_new_arc(tmp_path):
    """Defined dedup semantics: settlements AFTER the last terminal row are a
    NEW arc — the next closure writes a fresh row (value attribution happens
    at EVERY arc close; per-attempt records stay the WHAT-half)."""
    from terminal_settlement import write_terminal_settlement
    from kunglao_log import emit
    ws = _base_ws(tmp_path)
    _seed_ledger(ws)
    write_terminal_settlement(ws)
    emit(ws, actor="hook:write_guard", action="claim_settled", claim="C-103",
         detail=json.dumps({"from": "OPEN", "to": "DEAD", "tools": [],
                            "outcome": "DEAD"}))
    res = write_terminal_settlement(ws)
    assert res.get("written") is True and not res.get("duplicate")
    assert len(_terminal_rows(ws)) == 2
    detail = json.loads(_terminal_rows(ws)[-1].get("detail") or "{}")
    assert detail["claims_settled"][-1]["claim"] == "C-103"


def test_empty_enabling_chain_writes_empty_row(tmp_path):
    """Master-green with ZERO case-greens/settlements: the row exists with an
    empty chain — never a crash, never a missing artifact."""
    from terminal_settlement import write_terminal_settlement
    ws = tmp_path / "ws-bare"
    ws.mkdir()
    (ws / "runs").mkdir()
    write_claims_register(ws, [
        {"id": "C-1", "status": "PROVEN", "answers_question": "q1"}])
    (ws / "task_spec.yaml").write_text(
        "primary_questions:\n  - q1: family\n", encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text("# _INDEX\n", encoding="utf-8")

    res = write_terminal_settlement(ws)
    assert res.get("written") is True
    detail = json.loads(_terminal_rows(ws)[0].get("detail") or "{}")
    assert detail["chain"] == []
    assert detail["claims_settled"] == []
    assert detail["premise_corrections"] == []


def test_partial_chain_resolves_what_it_can(tmp_path):
    """A green case whose hypothesis_ref dangles (and one with no
    hypothesis_ref at all) degrades to null legs + null_reasons — the row
    still lands (the issue-880 null_reasons honesty pattern)."""
    from terminal_settlement import write_terminal_settlement
    ws = _base_ws(tmp_path)
    cases_dir = ws / "oracle" / "cases"
    (cases_dir / "case-b.yaml").write_text(
        _CASE_YAML.format(case_id="case-b", hyp_ref="H-404"), encoding="utf-8")
    (cases_dir / "case-c.yaml").write_text(
        _CASE_YAML.format(case_id="case-c", hyp_ref=""), encoding="utf-8")
    (ws / "runs" / "oracle-status.json").write_text(json.dumps({
        "schema": "oracle-status/1",
        "cases": {
            "case-a": {"status": "pass", "pending_entries": 0,
                       "instrumented": True},
            "case-b": {"status": "pass", "pending_entries": 0,
                       "instrumented": True},
            "case-c": {"status": "pass", "pending_entries": 0,
                       "instrumented": True},
        },
    }), encoding="utf-8")

    write_terminal_settlement(ws)
    chain = {c["case_id"]: c for c in _chain_of(ws)}
    assert chain["case-b"]["claim_id"] is None
    assert (chain["case-b"].get("null_reasons") or {}).get("claim_id") \
        == "hypothesis_unresolved"
    assert chain["case-c"]["hypothesis_ref"] is None
    assert (chain["case-c"].get("null_reasons") or {}).get("hypothesis_ref") \
        == "not_declared"
    assert chain["case-a"]["claim_id"] == "C-101", \
        "the resolvable leg must still resolve"


# =====================================================================
# consumption: retrieval weights terminal-chain above mid-loop
# =====================================================================

def test_retrieve_puts_terminal_chain_above_mid_loop_positives(tmp_path):
    """Order is the observable: within the POSITIVE class the chain entry
    outranks a NEWER mid-loop entry (the weighting constant is modest:
    recency decides only inside each tier)."""
    import case_bank
    ws = _base_ws(tmp_path)
    _seed_ledger(ws)
    _seed_case_bank(ws, [
        {"claim_id": "C-101", "method": "ida-struct", "roi_class": "POSITIVE",
         "context_tags": ["packed"]},   # in the terminal chain (older)
        {"claim_id": "C-888", "method": "strings-scan",
         "roi_class": "POSITIVE", "context_tags": ["packed"]},  # mid-loop, newer
    ])
    from terminal_settlement import write_terminal_settlement
    write_terminal_settlement(ws)

    hits = case_bank.retrieve(ws, ["packed"], limit=5)
    assert [h["claim_id"] for h in hits][:2] == ["C-101", "C-888"], \
        "terminal-chain lesson must surface ABOVE the newer mid-loop lesson"


def test_retrieve_failures_first_survives_chain_weighting(tmp_path):
    """Owner ruling 4 is untouched: the class rank (NEGATIVE first) stays the
    PRIMARY sort — chain weighting is within-class only."""
    import case_bank
    ws = _base_ws(tmp_path)
    _seed_ledger(ws)
    _seed_case_bank(ws, [
        {"claim_id": "C-101", "method": "ida-struct", "roi_class": "POSITIVE",
         "context_tags": ["packed"]},   # chain
        {"claim_id": "C-777", "method": "frida-trace", "roi_class": "NEGATIVE",
         "context_tags": ["packed"], "attribution": "wrong base picked"},
    ])
    from terminal_settlement import write_terminal_settlement
    write_terminal_settlement(ws)

    hits = case_bank.retrieve(ws, ["packed"], limit=5)
    assert hits[0]["roi_class"] == "NEGATIVE", \
        "counterexample pruning stays the primary sort (ruling 4)"
    assert [h["claim_id"] for h in hits][1:] == ["C-101"]


def test_seeder_inherits_chain_order(tmp_path):
    """hypothesis_seeder.seed_case_candidates consumes retrieve(), so the
    cold-start prior candidates list terminal-chain lessons FIRST."""
    import hypothesis_seeder
    ws = _base_ws(tmp_path)
    _seed_ledger(ws)
    _seed_case_bank(ws, [
        {"claim_id": "C-888", "method": "strings-scan",
         "roi_class": "POSITIVE", "context_tags": ["packed"]},  # mid-loop first
        {"claim_id": "C-101", "method": "ida-struct", "roi_class": "POSITIVE",
         "context_tags": ["packed"]},   # chain, appended later (older)
    ])
    from terminal_settlement import write_terminal_settlement
    write_terminal_settlement(ws)

    (ws / "evidence").mkdir()
    (ws / "evidence" / "die.json").write_text(json.dumps(
        {"derived": {"detected_packer": "UPX"}}), encoding="utf-8")

    n = hypothesis_seeder.seed_case_candidates(ws)
    assert n == 2
    from hypothesis_store import HypothesisStore
    carrier = next(h for h in HypothesisStore(ws / "hypotheses").list_all()
                   if hypothesis_seeder.CASE_BODY_MARKER in h.body)
    assert "C-101" in carrier.candidates[0], \
        "the terminal-chain prior must be the FIRST seeded candidate"
    assert "C-888" in carrier.candidates[1]


# =====================================================================
# vocabulary registration (the controlled-vocabulary contract: the emit word is registered)
# =====================================================================

def test_emit_word_is_registered():
    import event_taxonomy
    assert ACTION in event_taxonomy.EMIT_ACTIONS
