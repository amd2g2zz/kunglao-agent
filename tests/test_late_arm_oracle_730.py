# -*- coding: utf-8 -*-
"""tests/test_late_arm_oracle_730.py — the late-arm oracle gap (issue #730).

`record_case_settlements` keys its observations on `banked` — the set of
dispatches whose FIRST settlement rode this pass. That made re-runs
idempotent, but it also made the observation depend on ARMING ORDER: a
case armed after a claim has settled can never observe that claim,
because the claim's id never appears in `banked` again. Live consequence:
`runs/posteriors.yaml` is never created in the late-arm ordering, the
ranker prices every dispatchable claim from the wide Beta(1,1) prior
forever, and no settled claim ever moves a case posterior — while the
settlement count looks healthy.

The ordering is the COMMON one in practice: you learn what to ask after
the first claims land.

The fix separates two effects that were forced through one list:

  - the dedup record is made EXPLICIT (an auditable `case-observation/1`
    row in the consolidated experience ledger, #721) instead of being
    implied by `banked`;
  - `amend_case_settlements` sweeps EVERY decisive-terminal claim against
    the armed cases, so arming order stops mattering.

The invariant this suite pins:

    every (ARMED case, decisive-terminal claim linked to that case's
    question) pair is observed EXACTLY ONCE, whatever the order.

The faces:

1. ``test_late_armed_case_observes_already_settled_claim`` — the defect
   itself: arm a case after settlement, the amendment produces the
   observation the fresh path could never produce;
2. ``test_amendment_records_failure_for_refuted_claim`` — the other side
   of the ladder (REFUTED banks failure mass);
3. ``test_pre_arm_ordering_keeps_its_existing_behaviour`` — arming before
   settlement still observes exactly once, and the amendment that follows
   is a no-op (no double count);
4. ``test_amendment_is_idempotent`` — re-running amends nothing;
5. ``test_mixed_ordering_observes_each_claim_once`` — fresh and amended
   legs compose to one observation per claim;
6. ``test_observation_rows_are_auditable`` — the row names the case, the
   claim, the outcome and its source;
7. ``test_no_fabricated_bucket`` — the honest-absence shapes: no
   question, no linked case, a non-decisive terminal status;
   ``test_amendment_never_observes_an_unarmed_case`` — the amendment
   writes only complete, deliberate question-linkages;
8. ``test_duplicate_case_id_across_files_observes_once`` /
   ``test_fresh_leg_never_re_observes_an_amended_pair`` — the pair is the
   unit, within a pass AND across passes;
9. ``test_refused_row_append_is_not_reported_as_an_observation`` — a row
   that never landed is not counted as an observation;
10. ``test_run_observes_a_late_armed_case_end_to_end`` — the acceptance
    path through the real pass;
    ``test_run_attributes_a_new_settlement_to_the_fresh_leg`` — the
    ordering pin (a reversed pair of legs reports the fresh run as a
    no-op);
    ``test_run_propagates_an_observation_error`` — a refused row reaches
    the pass result;
    ``test_new_schema_is_registered_for_liveness`` — the liveness face.

The ARMING-ONLY sweep is the amendment's contract; the fresh leg keeps
its original ``target_pq`` link (its own suite pins that).

Every observation is itself an auditable row (case_id/claim_id/passed/
source) — the ledger is the dedup record, so the belief and its evidence
stay reconcilable.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import settle_round_credit as src  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402


# ---------- synthetic fixture helpers --------------------------------------

def _ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    return ws


def _register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")


def _armed_case(ws: Path, cid: str, pq: str) -> None:
    """All five arming fields filled — the issue-678 T5 armed shape."""
    cdir = ws / "oracle" / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"{cid}.yaml").write_text(yaml.safe_dump({
        "id": cid,
        "channel": "probe",
        "target_pq": pq,
        "hypothesis_ref": "H-001",
        "update_map": {"red_up": ["H-002"]},
        "expected": {"evidence_refs": ["E-001"]},
        "mutations": [{"kind": "omit", "target": "E-001"}],
    }), encoding="utf-8")


def _case_state(ws: Path, cid: str) -> dict:
    """The stored posterior for one case ({} when the ledger is absent)."""
    p = ws / "runs" / "posteriors.yaml"
    if not p.is_file():
        return {}
    doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return (doc.get("cases") or {}).get(cid) or {}


def _obs_rows(ws: Path) -> list[dict]:
    """Every case-observation row in the consolidated experience ledger."""
    return cl.read(ws, "experience", schema_prefix="case-observation/")


# ---------- 1. the defect: late-armed case, already-settled claim ----------

def test_late_armed_case_observes_already_settled_claim(tmp_path):
    """A claim settles while NO case is armed; a case targeting its
    question is armed afterwards. The fresh path observes nothing (the
    claim is not in `banked` any more — the live defect), and the
    amendment produces exactly the observation it missed."""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-005", "status": "PROVEN",
                    "answers_question": "q2", "question": "q"}])

    # the claim settles while nothing is armed — the honest cold start
    fresh = src.record_case_settlements(ws, ["C-005"])
    assert fresh["case_observations"] == 0, fresh
    assert not (ws / "runs" / "posteriors.yaml").exists()

    # ...then the oracle is armed, after the fact
    _armed_case(ws, "case-q2", "q2")

    out = src.amend_case_settlements(ws)
    assert out["case_observations"] == 1, out
    assert out["cases_passed"] == 1, out
    st = _case_state(ws, "case-q2")
    assert st["alpha"] == 2.0, st   # Beta(1,1) + one pass
    assert st["beta"] == 1.0, st


def test_amendment_records_failure_for_refuted_claim(tmp_path):
    """A REFUTED claim (the credit ladder's fail vocabulary, on the other
    side of the same observation) banks the failure mass the ranker needs
    to stop pricing that case as a coin flip."""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-009", "status": "REFUTED",
                    "answers_question": "q2", "question": "q"}])
    _armed_case(ws, "case-q2", "q2")

    out = src.amend_case_settlements(ws)
    assert out["case_observations"] == 1, out
    assert out["cases_failed"] == 1, out
    st = _case_state(ws, "case-q2")
    assert st["alpha"] == 1.0, st
    assert st["beta"] == 2.0, st


# ---------- 2. pre-arm ordering is untouched -------------------------------

def test_pre_arm_ordering_keeps_its_existing_behaviour(tmp_path):
    """Arming BEFORE settlement — the ordering the fresh path already
    handled — still observes exactly once, and the amendment that follows
    finds nothing to add. The fix widens coverage; it must not double the
    mass the existing path already banked."""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-001", "status": "PROVEN",
                    "answers_question": "pq-main", "question": "q"}])
    _armed_case(ws, "case-probe-1", "pq-main")

    fresh = src.record_case_settlements(ws, ["C-001"])
    assert fresh["case_observations"] == 1, fresh
    assert _case_state(ws, "case-probe-1")["alpha"] == 2.0

    after = src.amend_case_settlements(ws)
    assert after["case_observations"] == 0, after
    assert _case_state(ws, "case-probe-1")["alpha"] == 2.0  # no double count


def test_amendment_is_idempotent(tmp_path):
    """Re-running the amendment adds nothing: the observation row IS the
    dedup record, so a re-run is a byte-identical no-op."""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-005", "status": "PROVEN",
                    "answers_question": "q2", "question": "q"}])
    _armed_case(ws, "case-q2", "q2")

    first = src.amend_case_settlements(ws)
    assert first["case_observations"] == 1, first
    rows_after_first = _obs_rows(ws)
    alpha_after_first = _case_state(ws, "case-q2")["alpha"]

    again = src.amend_case_settlements(ws)
    assert again["case_observations"] == 0, again
    assert _obs_rows(ws) == rows_after_first        # no new rows
    assert _case_state(ws, "case-q2")["alpha"] == alpha_after_first


def test_mixed_ordering_observes_each_claim_once(tmp_path):
    """Two claims answer the same question — one settled before the arm,
    one after. Both are observed, each exactly once: the fresh and
    amended legs compose under one invariant instead of overlapping."""
    ws = _ws(tmp_path)
    _register(ws, [
        {"id": "C-005", "status": "PROVEN", "answers_question": "q2"},
        {"id": "C-009", "status": "REFUTED", "answers_question": "q2"},
    ])
    # C-005's settlement rode a pass with nothing armed
    assert src.record_case_settlements(ws, ["C-005"])["case_observations"] == 0

    _armed_case(ws, "case-q2", "q2")
    # C-009 settles WITH the case armed — the fresh leg banks it
    assert src.record_case_settlements(ws, ["C-009"])["case_observations"] == 1

    # the amendment closes the gap on C-005 and leaves C-009 alone
    out = src.amend_case_settlements(ws)
    assert out["case_observations"] == 1, out
    assert len(_obs_rows(ws)) == 2, _obs_rows(ws)
    st = _case_state(ws, "case-q2")
    assert st["alpha"] == 2.0, st   # C-005 passed
    assert st["beta"] == 2.0, st    # C-009 failed


# ---------- 3. the observation is an auditable row -------------------------

def test_observation_rows_are_auditable(tmp_path):
    """Each observation lands one `case-observation/1` row in the
    consolidated experience ledger naming the case, the claim and the
    outcome — the ledger IS the dedup record, so the belief stays
    reconcilable with what produced it."""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-005", "status": "PROVEN",
                    "answers_question": "q2"}])
    _armed_case(ws, "case-q2", "q2")

    src.amend_case_settlements(ws)
    rows = _obs_rows(ws)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["case_id"] == "case-q2"
    assert row["claim_id"] == "C-005"
    assert row["passed"] is True
    assert row["source"] == "late-arm"


# ---------- 4. no fabricated buckets ---------------------------------------

def test_no_fabricated_bucket(tmp_path):
    """Three honest-absence shapes, each writing nothing: a claim with no
    ``answers_question``, a question no armed case targets, and a
    non-decisive terminal status (STALE says nothing about the case)."""
    ws = _ws(tmp_path)
    _register(ws, [
        {"id": "C-no-q", "status": "PROVEN"},                    # no question
        {"id": "C-other-q", "status": "PROVEN",
         "answers_question": "q9"},                              # unarmed pq
        {"id": "C-stale", "status": "STALE", "answers_question": "q2"},
    ])
    _armed_case(ws, "case-q2", "q2")

    out = src.amend_case_settlements(ws)
    assert out["case_observations"] == 0, out
    assert _obs_rows(ws) == []
    assert not (ws / "runs" / "posteriors.yaml").exists()


def test_amendment_never_observes_an_unarmed_case(tmp_path):
    """The AMENDMENT observes only armed cases — it back-fills claims that
    settled before their case existed, so it must only ever write a
    complete, deliberate question-linkage. An unarmed (thin) doc is a
    stub with a bare ``target_pq``: not a hypothesis anybody committed
    to, so observing against it would move a posterior on the strength
    of a placeholder.

    (The FRESH leg keeps the link it has always had — ``target_pq``
    alone — which its own suite pins. Only the amendment is armed-only.
    Arming is NOT runner-loadability: the loader's ``expected`` shape
    differs, tracked as its own defect.)"""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-005", "status": "PROVEN",
                    "answers_question": "q2"}])
    cdir = ws / "oracle" / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "case-thin.yaml").write_text(
        yaml.safe_dump({"id": "case-thin", "target_pq": "q2"}),
        encoding="utf-8")

    out = src.amend_case_settlements(ws)
    assert out["case_observations"] == 0, out
    assert _obs_rows(ws) == []
    assert not (ws / "runs" / "posteriors.yaml").exists()


def test_run_attributes_a_new_settlement_to_the_fresh_leg(tmp_path):
    """The pass's attribution split, and the ordering pin with teeth: a
    claim banking THIS pass is observed by the fresh leg (``source`` =
    ``fresh``) and the amendment reports nothing. Reversing the two legs
    in ``run()`` would let the amendment claim that pair first and report
    the fresh leg as a no-op — which is exactly what this catches."""
    from settle_round_credit import run

    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-005", "status": "PROVEN",
                    "answers_question": "q2"}])
    _armed_case(ws, "case-q2", "q2")

    out = run(ws)                        # C-005 settles on THIS pass
    assert out["case_observations"] == 1, out
    assert out["case_observations_late_arm"] == 0, out
    assert [r["source"] for r in _obs_rows(ws)] == ["fresh"], _obs_rows(ws)


def test_run_propagates_an_observation_error(tmp_path):
    """A refused audit row must reach the PASS result. The amendment's
    error field used to be dropped by ``run()``, so a ledger that could
    not be written read as 'nothing to do' in the mechanism's cockpit."""
    from settle_round_credit import run

    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-005", "status": "PROVEN",
                    "answers_question": "q2"}])
    first = run(ws)                      # settles with nothing armed
    assert first["case_observations"] == 0, first

    _armed_case(ws, "case-q2", "q2")     # armed after the fact
    target = cl.family_path(ws, "experience")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()                       # the ledger cannot be written

    out = run(ws)
    assert out["case_observations_late_arm"] == 0, out
    assert out.get("case_observations_error"), out


# ---------- 5. one pair is one observation ---------------------------------

def test_retired_case_collects_no_observations(tmp_path):
    """A case retired out of the acceptance net (`status: retired`) is
    skipped by the runner's loader and must not keep collecting
    observations here either."""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-005", "status": "PROVEN",
                    "answers_question": "q2"}])
    _armed_case(ws, "case-done", "q2")
    cdir = ws / "oracle" / "cases"
    (cdir / "case-done.yaml").write_text(
        yaml.safe_dump({**yaml.safe_load(
            (cdir / "case-done.yaml").read_text(encoding="utf-8")),
            "status": "retired"}),
        encoding="utf-8")

    out = src.amend_case_settlements(ws)
    assert out["case_observations"] == 0, out
    assert _obs_rows(ws) == []
    assert not (ws / "runs" / "posteriors.yaml").exists()


def test_duplicate_case_id_across_files_observes_once(tmp_path):
    """Two case docs claiming the SAME id are one case: the pair is the
    unit, so the batch must not observe it twice within a single pass."""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-005", "status": "PROVEN",
                    "answers_question": "q2"}])
    _armed_case(ws, "case-dup", "q2")
    cdir = ws / "oracle" / "cases"
    (cdir / "also.yaml").write_text(yaml.safe_dump({
        "id": "case-dup", "channel": "probe", "target_pq": "q2",
        "hypothesis_ref": "H-001", "update_map": {"red_up": ["H-002"]},
        "expected": {"evidence_refs": ["E-001"]},
        "mutations": [{"kind": "omit", "target": "E-001"}],
    }), encoding="utf-8")

    out = src.amend_case_settlements(ws)
    assert out["case_observations"] == 1, out
    assert len(_obs_rows(ws)) == 1, _obs_rows(ws)
    assert _case_state(ws, "case-dup")["alpha"] == 2.0


def test_fresh_leg_never_re_observes_an_amended_pair(tmp_path):
    """The cross-pass ordering: an amendment observed the pair on an
    earlier pass, then a LATER pass banks that same claim (the settle
    path retries a dispatch whose first write failed). The pair is
    already on the ledger, so the fresh leg must not bank it again —
    otherwise one Bernoulli event lands twice and the prior drifts."""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-009", "status": "PROVEN",
                    "answers_question": "q2"}])
    _armed_case(ws, "case-q2", "q2")

    assert src.amend_case_settlements(ws)["case_observations"] == 1
    fresh = src.record_case_settlements(ws, ["C-009"])
    assert fresh["case_observations"] == 0, fresh
    assert len(_obs_rows(ws)) == 1, _obs_rows(ws)
    assert _case_state(ws, "case-q2")["alpha"] == 2.0   # once, not twice


def test_refused_row_append_is_not_reported_as_an_observation(tmp_path):
    """When the row cannot land, the count must not claim an observation
    that never happened — otherwise the pass reads healthy while the
    ledger stays empty and every tick re-observes."""
    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-005", "status": "PROVEN",
                    "answers_question": "q2"}])
    _armed_case(ws, "case-q2", "q2")
    target = cl.family_path(ws, "experience")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()                      # a directory where the file must be

    out = src.amend_case_settlements(ws)
    assert out["case_observations"] == 0, out
    assert out.get("case_observations_error"), out


# ---------- 6. the run() pass + the liveness face --------------------------

def test_run_observes_a_late_armed_case_end_to_end(tmp_path):
    """The acceptance path, in the live ordering: the claim settles on a
    pass with nothing armed (the honest cold start), the oracle is armed
    afterwards, and the NEXT pass observes it — then stops."""
    from settle_round_credit import run

    ws = _ws(tmp_path)
    _register(ws, [{"id": "C-005", "status": "PROVEN",
                    "answers_question": "q2"}])

    first = run(ws)                      # settles; nothing armed yet
    assert first["case_observations"] == 0, first
    assert not (ws / "runs" / "posteriors.yaml").exists()

    _armed_case(ws, "case-q2", "q2")     # armed after the fact
    out = run(ws)
    assert out["case_observations_late_arm"] == 1, out
    assert _case_state(ws, "case-q2")["alpha"] == 2.0

    again = run(ws)
    assert again["case_observations"] == 0, again
    assert _case_state(ws, "case-q2")["alpha"] == 2.0


def test_new_schema_is_registered_for_liveness(tmp_path):
    """The schema born in the consolidated file is pre-seeded, so a
    writer that dies reads DEAD rather than absent."""
    ws = _ws(tmp_path)
    assert cl.liveness(ws)["experience:case-observation/1"] == 0

    _register(ws, [{"id": "C-005", "status": "PROVEN",
                    "answers_question": "q2"}])
    _armed_case(ws, "case-q2", "q2")
    src.amend_case_settlements(ws)
    assert cl.liveness(ws)["experience:case-observation/1"] == 1
