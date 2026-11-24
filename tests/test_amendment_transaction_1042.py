# -*- coding: utf-8 -*-
"""tests/test_amendment_transaction_1042.py — the case-amendment is one
transaction, and revocation retries until it lands.

Two defect classes pinned here:

  1. The pair-amendment used to mutate the case posterior BEFORE the
     ``case-amendment/1`` append and persisted the ledger regardless of
     the append's result: a refused row left a flipped belief with ZERO
     ledger rows, and every following pass flipped the belief AGAIN (the
     ±1 compounded while the fold never saw a row). The shipped shape is
     COMMIT-FIRST: the audit row lands first, the posterior moves only
     after ``ok``, a refusal mutates nothing, and the next pass retries
     idempotently (the fold still sees the pair unamended).

  2. ``_revoke_derived_rows`` was fire-and-forget: a revoke failure was
     one warn with no retry channel, and because the amendment row HAD
     landed, the pair never re-entered the amendment entries — the stale
     derived knowledge stayed forever with a null error field. The
     shipped shape is DISCOVERY-BASED RETRY: every reconcile pass
     re-attempts revocation for claims whose amendments have landed
     while derived rows still match the claim in the workspace-local
     knowledge family (the stale source itself is the durable pending
     marker — no new state family). Failures surface on the sibling
     ``case_revocations_error`` field so decide()/telemetry see them.

The save-failure window stays loud and unswallowed: a landed row followed
by a failed posterior save is reported in that pass's telemetry error
field. Nothing retries that save — a later pass reads the pair as amended
and applies nothing — so the belief and the fold stay apart; the repair
is tracked separately. No silent re-derivation.

The isolation cut then makes the transaction airtight: every production
posterior writer holds the workspace's process lock across its
read-modify-save interval or refuses; a revocation removes only rows
bound to this
workspace and claim; and a row whose binding cannot be confirmed keeps
its bytes and is reported — through the production Stop.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import settle_round_credit as src  # noqa: E402
from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import crystallize  # noqa: E402
from rlvr import marl  # noqa: E402
from rlvr import q_cells as qc  # noqa: E402

FAM = "upx-unpack"

#: the four production entry points that write ``runs/posteriors.yaml``
POSTERIOR_WRITERS = ("case correction", "late-arm observation",
                     "oracle verdict", "question seed")

#: how a historical negative can lack a trustworthy workspace binding
UNCONFIRMED_BINDINGS = ("missing", "legacy basename", "malformed", "non-string")


# ---------- fixtures --------------------------------------------------------

def _ws(tmp_path: Path, claims: list[dict]) -> Path:
    """Workspace with a REAL dispatch ledger row per claim (a fixture
    without one settles nothing under the no-backcompat contract)."""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")
    from _dispatch_fixture import mint_dispatches

    mint_dispatches(ws, claims, pending=False)
    return ws


def _arm_case(ws: Path, cid: str, pq: str) -> None:
    cdir = ws / "oracle" / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / f"{cid}.yaml").write_text(yaml.safe_dump({
        "id": cid,
        "channel": "probe",
        "target_pq": pq,
        "hypothesis_ref": "H-001",
        "update_map": {"red_up": ["H-002"]},
        "expected": [{"field": "probe", "value": "observed",
                      "evidence_refs": ["E-001"]}],
        "mutations": [{"kind": "omit", "target": "E-001"}],
    }), encoding="utf-8")


def _observe(ws: Path, cid: str, claim: str, passed: bool) -> None:
    """Drive the production first-observation face directly for setup."""
    src._apply_case_observations(ws, [(cid, claim, passed)], source="fresh")


def _belief(ws: Path, cid: str) -> tuple[float, float]:
    import posteriors_case as po
    led = po.PosteriorLedger.load(ws)
    cp = led.cases.get(cid)
    return (cp.alpha, cp.beta) if cp else (1.0, 1.0)


def _amendment_rows(ws: Path) -> list[dict]:
    return cl.read(ws, "experience", schema_prefix="case-amendment")


def _flip_register(ws: Path, claim: str, pq: str, status: str) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": claim, "status": status,
                                    "answers_question": pq}]}),
        encoding="utf-8")


def _pending_correction(tmp_path: Path) -> Path:
    """case-q2 observed C-1 pass; the register now reads REFUTED, so one
    correction is pending."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")
    return ws


def _refuse_experience_appends(monkeypatch) -> None:
    """Every experience-family append returns False (the refusal face)."""
    def _refused(*_a, **_k):
        return False

    monkeypatch.setattr(cl, "append", _refused)


def _seed_negative(ws: Path, claim: str) -> None:
    """One derived class-negative attributed to ``claim`` (the derived
    knowledge a flip must revoke), through the REAL write face."""
    qc.append_observation(ws, "eeee00000000", FAM, None,
                          source="dispatch", claim=claim, agent="analyst",
                          tools=["upx", "strings"],
                          arm_key_col=qc.arm_key(
                              FAM, "facts_snapshot", "none", 0))
    out = crystallize.crystallize_settlement(
        ws, claim=claim, step_id="step-1", outcome="blocked")
    assert out["negative"] is True, out


def _neg_rows(ws) -> list[dict]:
    return [r for r in marl.read_negatives(ws)
            if str(r.get("claim_ref") or "")]


def _events(ws: Path, action: str) -> list[dict]:
    """The workspace's event rows carrying one action word."""
    return [row
            for day in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
            for row in map(json.loads, day.read_text(encoding="utf-8").splitlines())
            if row.get("action") == action]


def _armed_seal(tmp_path, monkeypatch):
    """Arm the learning channel on the conftest-isolated key path."""
    from rlvr import learning_seal as seal

    key = seal.KEY_PATH
    key.parent.mkdir(parents=True, exist_ok=True)
    key.write_bytes(b"k" * 48)
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
    return key


def _posterior_write(face: str, ws: Path) -> dict:
    """One production posterior writer, by entry point. Returns what the
    entry returns ({} for the two that return nothing). The oracle
    verdict is one red on case-q2; the question seed is q-other."""
    import oracle_runner as orun
    import plan_epistemics

    if face == "case correction":
        return src.reconcile_case_settlements(ws)
    if face == "late-arm observation":
        return src.amend_case_settlements(ws)
    if face == "oracle verdict":
        orun.record_posteriors(ws, {"cases": {"case-q2": {"status": "fail"}}})
        return {}
    plan_epistemics.seed_situational_pqs(ws, [
        {"boundary_type": "epistemic", "answers_question": "q-other",
         "candidates": {"first": 1, "second": 1}}], {})
    return {}


def _refusal(face: str, ws: Path) -> str:
    """The error a writer surfaces when it refuses: the text it raised,
    or the error fields of what it returned. Empty when it did not
    refuse."""
    try:
        out = _posterior_write(face, ws)
    except ValueError as exc:
        return str(exc)
    return " | ".join(str(value) for key, value in out.items()
                      if key.endswith("_error") and value)


# ---------- 1. commit-first: refusal touches nothing ------------------------

def test_append_refusal_leaves_belief_and_ledger_unchanged(
        tmp_path, monkeypatch):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")
    _refuse_experience_appends(monkeypatch)

    out = src.reconcile_case_settlements(ws)
    assert out.get("case_amendments_error"), out
    assert out["case_amendments"] == 0
    assert _belief(ws, "case-q2") == (2.0, 1.0)   # untouched
    assert _amendment_rows(ws) == []              # nothing landed


def test_repeated_refused_passes_do_not_drift(tmp_path, monkeypatch):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")
    _refuse_experience_appends(monkeypatch)

    for _ in range(4):
        out = src.reconcile_case_settlements(ws)
        assert out.get("case_amendments_error"), out
        assert _belief(ws, "case-q2") == (2.0, 1.0)
    assert _amendment_rows(ws) == []


# ---------- 2. the save window stays loud -----------------------------------

def test_save_failure_is_loud(tmp_path, monkeypatch):
    import posteriors_case as po

    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")

    def _boom(self, _ws):
        raise OSError("synthetic save failure")

    monkeypatch.setattr(po.PosteriorLedger, "save", _boom)
    out = src.reconcile_case_settlements(ws)
    assert out.get("case_amendments_error"), out
    assert "OSError" in out["case_amendments_error"]
    # the row landed (append-only history keeps it) and the next pass
    # sees the pair amended — no double-apply
    monkeypatch.undo()
    assert len(_amendment_rows(ws)) == 1
    again = src.reconcile_case_settlements(ws)
    assert again["case_amendments"] == 0, again


# ---------- 3. revocation retries until it lands -----------------------------

def test_revoke_failure_is_loud_and_retries_next_pass(
        tmp_path, monkeypatch):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _seed_negative(ws, "C-1")
    _flip_register(ws, "C-1", "q2", "REFUTED")

    def _boom(*_a, **_k):
        raise OSError("synthetic revoke failure")

    monkeypatch.setattr(crystallize, "revoke_claim", _boom)
    out1 = src.reconcile_case_settlements(ws)
    assert out1["case_amendments"] == 1, out1      # the flip landed
    assert len(_amendment_rows(ws)) == 1
    assert len(_neg_rows(ws)) == 1                 # derived row survived
    assert out1.get("case_revocations_error"), out1   # the LOUD face

    # the store heals: the next pass re-attempts and completes
    monkeypatch.undo()
    out2 = src.reconcile_case_settlements(ws)
    assert _neg_rows(ws) == [], out2
    assert out2.get("revoked_claims") == ["C-1"], out2
    assert not out2.get("case_revocations_error"), out2
    assert out2["case_amendments"] == 0            # no double-apply


def test_revoke_success_is_idempotent_second_pass(tmp_path):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _seed_negative(ws, "C-1")
    _flip_register(ws, "C-1", "q2", "REFUTED")

    out1 = src.reconcile_case_settlements(ws)
    assert out1["case_amendments"] == 1, out1
    assert _neg_rows(ws) == []
    assert out1.get("revoked_claims") == ["C-1"], out1

    rows_before = _amendment_rows(ws)
    out2 = src.reconcile_case_settlements(ws)
    assert out2["case_amendments"] == 0, out2
    assert out2.get("revoked_claims") == [], out2  # no re-attempt
    assert not out2.get("case_revocations_error"), out2
    assert _amendment_rows(ws) == rows_before      # no new rows


# ---------- 4. the armed seal round-trips -----------------------------------

def test_armed_seal_round_trip_still_settles(tmp_path, monkeypatch):
    import posteriors_case as po

    _armed_seal(tmp_path, monkeypatch)
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")

    out = src.reconcile_case_settlements(ws)
    assert out["case_amendments"] == 1, out
    assert _belief(ws, "case-q2") == (1.0, 2.0)
    led = po.PosteriorLedger.load(ws)
    assert not led.degraded, led.warnings
    assert len(_amendment_rows(ws)) == 1


@pytest.mark.parametrize("face", POSTERIOR_WRITERS)
def test_ledger_sealed_by_another_build_is_refused_and_left_untouched(
        tmp_path, monkeypatch, face):
    """An armed workspace upgraded since its ledger was sealed. The
    writer refuses for good — it names both builds — and never replaces
    the file with the empty ledger it could read. No re-seal is built
    (a separate change owns the repair)."""
    from posteriors_case import LEDGER_REL
    from rlvr import learning_seal as seal

    _armed_seal(tmp_path, monkeypatch)
    build = {"id": "v0.1.5"}
    monkeypatch.setattr(seal, "_live_version", lambda: build["id"])
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN", "answers_question": "q2"},
                        {"id": "C-2", "status": "PROVEN", "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
        {"id": "C-1", "status": "REFUTED", "answers_question": "q2"},
        {"id": "C-2", "status": "PROVEN", "answers_question": "q2"}]}),
        encoding="utf-8")
    ledger = ws / LEDGER_REL
    sealed = ledger.read_bytes()
    build["id"] = "v0.1.6"
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})  # a new process anchors on its own build

    refusal = _refusal(face, ws)

    # the refusal names the build that sealed the file and the running one
    assert "v0.1.5" in refusal and "v0.1.6" in refusal, refusal
    assert ledger.read_bytes() == sealed


def test_incomplete_ledger_refuses_the_amendment_and_keeps_its_bytes(tmp_path):
    """One entry the ledger cannot parse leaves the snapshot incomplete:
    the writer refuses instead of saving the ledger without the entry."""
    import posteriors_case as po

    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")
    ledger = ws / po.LEDGER_REL
    doc = yaml.safe_load(ledger.read_text(encoding="utf-8"))
    doc["cases"]["case-broken"] = {"alpha": "not-a-number", "beta": 1}
    ledger.write_text(yaml.safe_dump(doc), encoding="utf-8")
    incomplete = ledger.read_bytes()

    out = src.reconcile_case_settlements(ws)

    assert out["case_amendments"] == 0, out
    assert "case-broken" in out["case_amendments_error"]   # names what it could not read
    assert ledger.read_bytes() == incomplete


# ---------- 5. the pass surface carries the revocation error -----------------

def test_run_surfaces_the_revocation_error(tmp_path, monkeypatch):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _seed_negative(ws, "C-1")
    _flip_register(ws, "C-1", "q2", "REFUTED")

    def _boom(*_a, **_k):
        raise OSError("synthetic revoke failure")

    monkeypatch.setattr(crystallize, "revoke_claim", _boom)
    out = src.run(ws)
    assert out.get("case_amendments") == 1, out
    assert out.get("case_observations_error"), out
    assert "C-1" in out["case_observations_error"]


# ---------- 6. concurrent posterior writers ---------------------------------

def _correction_paused_after_its_snapshot(ws, snapshot_read, proceed):
    """The correction in its own process: it takes the posterior lock,
    reads its snapshot and waits there until the competing writer has
    run. The pause hangs on the ledger file's own read, not on the name
    of the loader the lock context calls."""
    from posteriors_case import LEDGER_REL

    ledger = Path(ws) / LEDGER_REL
    read_text = Path.read_text
    reads: list[bool] = []

    def read_then_pause(self, *args, **kwargs):
        text = read_text(self, *args, **kwargs)
        if self == ledger and not reads:
            reads.append(True)
            snapshot_read.set()
            assert proceed.wait(30), "competing writer did not run"
        return text

    Path.read_text = read_then_pause
    assert src.reconcile_case_settlements(ws)["case_amendments"] == 1


def _writer_after_its_lock_attempt(ws, face, proceed):
    """The competing writer in its own process: it signals once it is
    about to take the posterior lock, then writes."""
    import platform_matrix

    lock = platform_matrix.fd_lock

    def signal_then_lock(fd, **kwargs):
        proceed.set()
        return lock(fd, **kwargs)

    platform_matrix.fd_lock = signal_then_lock
    _posterior_write(face, ws)


def _interleave_with_competing_writer(ws: Path, face: str,
                                      paused=_correction_paused_after_its_snapshot) -> None:
    """Two processes and the real lock: the correction runs until it has
    read its snapshot under the lock, then the competing writer starts.
    Fails the test unless both exit cleanly. A correction that is still
    waiting when it is stopped means the competing writer never reached
    the lock."""
    import multiprocessing

    ctx = multiprocessing.get_context("spawn")
    snapshot_read, proceed = ctx.Event(), ctx.Event()
    correction = ctx.Process(target=paused,
                             args=(ws, snapshot_read, proceed))
    other = ctx.Process(target=_writer_after_its_lock_attempt,
                        args=(ws, face, proceed))
    correction.start()
    try:
        assert snapshot_read.wait(30), "the correction never reached its snapshot read"
        other.start()
        for process in (correction, other):
            process.join(30)
    finally:
        for process in (correction, other):
            if process.is_alive():
                process.terminate()
                process.join()
    assert (correction.exitcode, other.exitcode) == (0, 0), (
        f"the correction and the {face} writer exited "
        f"({correction.exitcode}, {other.exitcode})")


def test_question_seeded_during_case_correction_is_preserved(tmp_path):
    import posteriors_case as po

    ws = _pending_correction(tmp_path)

    _interleave_with_competing_writer(ws, "question seed")

    led = po.PosteriorLedger.load(ws)     # the reopened snapshot holds both effects
    assert (_belief(ws, "case-q2"), sorted(led.pqs)) == ((1.0, 2.0), ["q-other"])


def test_concurrent_corrections_apply_the_amendment_once(tmp_path):
    ws = _pending_correction(tmp_path)

    _interleave_with_competing_writer(ws, "case correction")

    assert (_belief(ws, "case-q2"), len(_amendment_rows(ws))) == ((1.0, 2.0), 1)


def test_oracle_verdict_during_case_correction_is_preserved(tmp_path):
    ws = _pending_correction(tmp_path)

    _interleave_with_competing_writer(ws, "oracle verdict")

    assert _belief(ws, "case-q2") == (1.0, 3.0)    # the correction, then the red on top


def test_case_observation_during_case_correction_is_preserved(tmp_path):
    ws = _pending_correction(tmp_path)
    (ws / "claim-register.yaml").write_text(yaml.safe_dump({"claims": [
        {"id": "C-1", "status": "REFUTED", "answers_question": "q2"},
        {"id": "C-2", "status": "PROVEN", "answers_question": "q2"}]}),
        encoding="utf-8")

    _interleave_with_competing_writer(ws, "late-arm observation")

    assert _belief(ws, "case-q2") == (2.0, 2.0)    # the correction, then C-2's green on top


# ---------- 7. discovery mirrors revoke's pre-move window --------------------

def test_pre_move_stale_row_is_discovered_and_retried(
        tmp_path, monkeypatch):
    """The R4 pre-move window: a stale derived row sitting in a pre-move
    knowledge rel (not yet migrated) must read PENDING to the discovery
    face, or a revoke that failed before reaching it stays silent until
    migration resurrects the row."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")
    import consolidate_ledgers as _migrate_cli
    from rlvr.strategy_store import workspace_id_of

    rel = "marl-negative.jsonl"
    assert rel in _migrate_cli.LEGACY_SOURCES["knowledge"]
    (ws / rel).write_text(json.dumps({
        "schema": "marl-negative/1", "ts": "2026-11-17T00:00:00Z",
        "signature_class": "unknown", "agent_type": None,
        "method_family": "upx-unpack", "tool_chain": "upx", "fails": 1,
        "workspace_id": workspace_id_of(ws), "claim_ref": "C-1", "step_ref": "step-1"}) + "\n",
        encoding="utf-8")

    def _boom(*_a, **_k):
        raise OSError("synthetic revoke failure")

    monkeypatch.setattr(crystallize, "revoke_claim", _boom)
    out1 = src.reconcile_case_settlements(ws)
    assert out1["case_amendments"] == 1, out1
    assert out1.get("case_revocations_error"), out1   # PENDING is loud
    assert (ws / rel).is_file()                       # sweep never ran

    # healed: the sweep removes the pre-move row (no resurrection)
    monkeypatch.undo()
    out2 = src.reconcile_case_settlements(ws)
    assert out2.get("revoked_claims") == ["C-1"], out2
    assert not out2.get("case_revocations_error"), out2
    assert not (ws / rel).exists()


# ---------- 8. mixed land/refuse counts per entry ----------------------------

def test_mixed_land_and_refuse_counts_per_entry(tmp_path, monkeypatch):
    """One entry lands, a LATER append refuses: the landed entry applied
    and saved, the refused entry re-fires alone next pass, and the
    counts are per-entry exact."""
    ws = _ws(tmp_path, [
        {"id": "C-1", "status": "PROVEN", "answers_question": "q1"},
        {"id": "C-2", "status": "PROVEN", "answers_question": "q2"},
    ])
    _arm_case(ws, "case-q1", "q1")
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q1", "C-1", True)
    _observe(ws, "case-q2", "C-2", True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [
            {"id": "C-1", "status": "REFUTED", "answers_question": "q1"},
            {"id": "C-2", "status": "REFUTED", "answers_question": "q2"},
        ]}), encoding="utf-8")

    calls = {"n": 0}
    real_append = cl.append

    def _fail_second(*a, **k):
        calls["n"] += 1
        if calls["n"] >= 2:
            return False
        return real_append(*a, **k)

    monkeypatch.setattr(cl, "append", _fail_second)
    out = src.reconcile_case_settlements(ws)
    assert out["case_amendments"] == 1, out
    assert "1 amendment row(s) refused" in out["case_amendments_error"], out
    assert _belief(ws, "case-q1") == (1.0, 2.0)   # landed entry applied
    assert _belief(ws, "case-q2") == (2.0, 1.0)   # refused entry untouched
    assert len(_amendment_rows(ws)) == 1

    # next pass, healed: ONLY the refused entry re-fires, exactly once
    monkeypatch.undo()
    out2 = src.reconcile_case_settlements(ws)
    assert out2["case_amendments"] == 1, out2
    assert not out2.get("case_amendments_error"), out2
    assert len(_amendment_rows(ws)) == 2
    assert _belief(ws, "case-q1") == (1.0, 2.0)   # no double-apply
    assert _belief(ws, "case-q2") == (1.0, 2.0)


# ---------- 9. ownership: what a correction may remove -----------------------

def _unattributed_negative(ws: Path, binding: str) -> bytes:
    """One stale negative for C-1 whose workspace binding cannot be
    confirmed, in hand-written bytes (the form a preserved row keeps)."""
    identity = {"legacy basename": ws.name, "malformed": "old-name",
                "non-string": 42}.get(binding)
    stamp = "" if identity is None else f', "workspace_id":{json.dumps(identity)}'
    return f'{{ "schema":"marl-negative/1", "claim_ref":"C-1"{stamp} }}\r\n\n'.encode()


@pytest.mark.parametrize("binding", UNCONFIRMED_BINDINGS)
def test_unattributed_negative_is_preserved_and_reported_across_passes(
        tmp_path, binding):
    """A row that matches the amended claim but cannot be confirmed as
    this workspace's. It survives verbatim next to an attributed row and
    an unrelated claim's row, the pass reports it, and a retry — the
    workspace reopened under a path that is not the row's binding —
    neither removes it nor applies the amendment again."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    ws = ws.rename(ws.with_name("ab12cd34ef56"))   # a basename that looks like a workspace id
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")
    store = cl.family_path(ws, "knowledge")
    store.parent.mkdir(parents=True, exist_ok=True)
    stale = _unattributed_negative(ws, binding)
    store.write_bytes(stale)
    _seed_negative(ws, "C-9")
    unrelated = store.read_bytes()[len(stale):]
    _seed_negative(ws, "C-1")

    passes = [src.reconcile_case_settlements(ws) for _ in range(2)]

    # the attributed row is revoked and the stale one reported; the retry
    # applies nothing again and still reports it
    assert [(out["case_amendments"], out["revoked_claims"],
             out.get("case_revocations_unavailable"))
            for out in passes] == [(1, ["C-1"], ["C-1"]), (0, [], ["C-1"])]
    assert store.read_bytes() == stale + unrelated


def test_negative_bound_to_another_workspace_is_never_revoked(tmp_path):
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _flip_register(ws, "C-1", "q2", "REFUTED")
    store = cl.family_path(ws, "knowledge")
    store.parent.mkdir(parents=True, exist_ok=True)
    foreign = (json.dumps({"schema": "marl-negative/1", "claim_ref": "C-1",
                           "workspace_id": "aaaaaaaaaaaa"}) + "\n").encode()
    store.write_bytes(foreign)

    out = src.reconcile_case_settlements(ws)

    assert (out["case_amendments"], out["revoked_claims"]) == (1, [])
    assert store.read_bytes() == foreign


# ---------- 10. the production Stop reads the unavailable report -------------

def _completing_mission_with_unattributed_knowledge(tmp_path: Path) -> Path:
    """A mission the production Stop can complete, whose claim also has
    a stale negative with no workspace binding: C-001 was observed red on
    its armed case and now reads PROVEN, so a correction is pending."""
    from test_producer_attribution_1005 import FAM_WORKER, FID1, _mint, _write_fact
    from test_production_terminal_1005 import terminal_workspace

    ws = terminal_workspace(tmp_path)
    (ws / "facts").mkdir(exist_ok=True)
    _mint(ws, {"id": "C-001", "status": "PROVEN", "title": "synthetic result",
               "answers_question": "pq1",
               "maker_identity": "synthetic-worker-1"}, FAM_WORKER)
    _write_fact(ws, FID1, "C-001")
    _arm_case(ws, "case-pq1", "pq1")
    _observe(ws, "case-pq1", "C-001", False)
    store = cl.family_path(ws, "knowledge")
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps({"schema": "marl-negative/1", "claim_ref": "C-001"}) + "\n",
                     encoding="utf-8")
    return ws


def test_production_stop_names_claims_whose_revocation_is_unavailable(
        tmp_path, capsys):
    """The terminal path is the only reader of the settle pass's
    ``case_revocations_unavailable``: the terminal record, one event per
    claim and the console warn are what make the kept stale knowledge
    visible."""
    from rlvr import production_terminal

    ws = _completing_mission_with_unattributed_knowledge(tmp_path)

    assert production_terminal.settle_stop(ws)["status"] == "completed"

    record = json.loads((ws / "runs" / "production-terminal.json").read_text(encoding="utf-8"))
    assert record["case_revocations_unavailable"] == ["C-001"]
    assert [row["claim"] for row in _events(ws, "case_revocation_unavailable")] == ["C-001"]
    assert any("WARN" in line and "C-001" in line
               for line in capsys.readouterr().err.splitlines())


def test_unavailable_revocation_is_reported_once_across_stops(tmp_path):
    from rlvr import production_terminal

    ws = _completing_mission_with_unattributed_knowledge(tmp_path)

    stops = [production_terminal.settle_stop(ws)["status"] for _ in range(2)]

    assert stops == ["completed", "completed"]
    assert [row["claim"] for row in _events(ws, "case_revocation_unavailable")] == ["C-001"]


# ---------- 11. an unreadable knowledge store through the real entry ---------

def _stale_negative_in_a_pre_move_file(tmp_path) -> tuple[Path, Path, bytes]:
    """A pending correction whose stale negative sits in a pre-move
    knowledge file. Returns the workspace, that file and its bytes."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")
    _observe(ws, "case-q2", "C-1", True)
    _seed_negative(ws, "C-1")
    _flip_register(ws, "C-1", "q2", "REFUTED")
    target = ws / "marl-negative.jsonl"
    cl.family_path(ws, "knowledge").rename(target)
    return ws, target, target.read_bytes()


def _reject_knowledge_reads(monkeypatch, target: Path) -> None:
    import errno

    real_open = Path.open

    def reject_knowledge_read(path, *args, **kwargs):
        if path == target and (not args or "r" in args[0]):
            raise OSError(errno.EIO, "injected knowledge read error")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", reject_knowledge_read)


def test_unreadable_knowledge_is_reported_and_kept_by_the_settlement_entry(
        tmp_path, monkeypatch):
    ws, target, original = _stale_negative_in_a_pre_move_file(tmp_path)

    with monkeypatch.context() as fault:
        _reject_knowledge_reads(fault, target)
        out = src.run(ws)

    assert "injected knowledge read error" in out["case_observations_error"]
    assert target.read_bytes() == original


def test_next_settlement_revokes_knowledge_that_was_unreadable(tmp_path, monkeypatch):
    ws, target, _original = _stale_negative_in_a_pre_move_file(tmp_path)
    with monkeypatch.context() as fault:
        _reject_knowledge_reads(fault, target)
        src.run(ws)                      # the pass that could not read it

    out = src.run(ws)

    assert (out["case_amendments"], out.get("case_observations_error")) == (0, None)
    assert not target.exists() and _neg_rows(ws) == [] and len(_amendment_rows(ws)) == 1


# ---------- 12. the knowledge lock ------------------------------------------

def _knowledge_store(tmp_path: Path) -> tuple[Path, Path]:
    """An empty workspace and its knowledge file (not yet written)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    store = cl.family_path(ws, "knowledge")
    store.parent.mkdir(parents=True)
    return ws, store


def test_knowledge_append_is_refused_while_the_lock_is_unavailable(tmp_path, monkeypatch):
    import platform_matrix

    ws, store = _knowledge_store(tmp_path)
    store.write_bytes(b'{"schema": "feature-table/1", "key": "a"}\n')
    before = store.read_bytes()
    monkeypatch.setattr(platform_matrix, "fd_lock", lambda fd: "unlocked-noop")

    assert not cl.append(ws, "knowledge", {"schema": "feature-table/1", "key": "b"})
    assert store.read_bytes() == before


def test_knowledge_revoke_is_refused_while_the_lock_is_unavailable(tmp_path, monkeypatch):
    import platform_matrix
    from rlvr.strategy_store import workspace_id_of

    ws, store = _knowledge_store(tmp_path)
    store.write_bytes((json.dumps({
        "schema": "marl-negative/1", "claim_ref": "C-1",
        "workspace_id": workspace_id_of(ws)}) + "\n").encode())
    before = store.read_bytes()
    monkeypatch.setattr(platform_matrix, "fd_lock", lambda fd: "unlocked-noop")

    with pytest.raises(OSError):
        crystallize.revoke_claim(ws, "C-1")
    assert store.read_bytes() == before


def _competing_knowledge_writer(ws, mode, reading, contended):
    import errno
    import os
    import platform_matrix

    if mode == "revoke":
        read = crystallize.knowledge_lines
        target = cl.family_path(ws, "knowledge")

        def pause_inside_rewrite(path):
            lines = read(path)
            if path == target and not reading.is_set():
                reading.set()
                assert contended.wait(30)
            return lines

        crystallize.knowledge_lines = pause_inside_rewrite
        assert crystallize.revoke_claim(ws, "C-1")["negatives_removed"] == 1
    else:
        lock = platform_matrix.fd_lock

        def check_contended(fd):
            # The append's actual fd must hit the same byte held by the rewriter.
            if os.name == "nt":
                import msvcrt
                attempt, args = msvcrt.locking, (fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                attempt, args = fcntl.flock, (fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with pytest.raises(OSError) as error:
                attempt(*args)
            assert error.value.errno in (errno.EACCES, errno.EAGAIN, errno.EDEADLK)
            contended.set()
            return lock(fd)

        platform_matrix.fd_lock = check_contended
        assert cl.append(ws, "knowledge", {"schema": "feature-table/1", "key": "new"})


def test_knowledge_append_waits_for_inflight_rewrite(tmp_path):
    import multiprocessing
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN", "answers_question": "q2"}])
    _seed_negative(ws, "C-1")
    ctx = multiprocessing.get_context("spawn")
    reading, contended = ctx.Event(), ctx.Event()
    revoke, append = [ctx.Process(target=_competing_knowledge_writer,
                                  args=(ws, mode, reading, contended))
                      for mode in ("revoke", "append")]
    revoke.start()
    try:
        assert reading.wait(30)
        append.start()
        for process in (revoke, append):
            process.join(30)
            assert process.exitcode == 0
    finally:
        for process in (revoke, append):
            if process.is_alive():
                process.terminate()
                process.join()
    assert cl.read(ws, "knowledge") == [{"schema": "feature-table/1", "key": "new"}]


# ---------- 13. the posterior lock ------------------------------------------

def _correction_with_a_seeded_question(tmp_path) -> tuple[Path, list[Path]]:
    """A pending correction, a question already in the ledger and a
    derived negative for the claim. Returns the workspace and the three
    files a refused pass must leave alone."""
    import plan_epistemics
    from posteriors_case import LEDGER_REL

    ws = _pending_correction(tmp_path)
    plan_epistemics.seed_situational_pqs(ws, [
        {"boundary_type": "epistemic", "answers_question": "q-other",
         "candidates": {"first": 1, "second": 1}}], {})
    _seed_negative(ws, "C-1")
    return ws, [ws / LEDGER_REL, cl.family_path(ws, "experience"),
                cl.family_path(ws, "knowledge")]


def _reject_posterior_reads(monkeypatch, ledger: Path) -> None:
    import errno

    real_read = Path.read_text

    def unreadable(path, *args, **kwargs):
        if path == ledger:
            raise OSError(errno.EIO, "injected posterior read error")
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", unreadable)


def test_unreadable_posterior_refuses_amendment_without_side_effects(tmp_path, monkeypatch):
    from posteriors_case import LEDGER_REL

    ws, paths = _correction_with_a_seeded_question(tmp_path)
    before = [p.read_bytes() for p in paths]

    with monkeypatch.context() as fault:
        _reject_posterior_reads(fault, ws / LEDGER_REL)
        out = src.reconcile_case_settlements(ws)

    assert out["case_amendments"] == 0, out
    assert "injected posterior read error" in out["case_amendments_error"]
    assert [p.read_bytes() for p in paths] == before


def test_amendment_lands_once_the_posterior_is_readable(tmp_path, monkeypatch):
    import posteriors_case as po

    ws, _paths = _correction_with_a_seeded_question(tmp_path)
    with monkeypatch.context() as fault:
        _reject_posterior_reads(fault, ws / po.LEDGER_REL)
        src.reconcile_case_settlements(ws)        # the refused pass

    out = src.reconcile_case_settlements(ws)

    assert (out["case_amendments"], out.get("case_amendments_error")) == (1, None)
    assert "q-other" in po.PosteriorLedger.load(ws).pqs   # the refusal cost nothing


def _observation_paused_after_its_read_under_the_lock(ws, read_under_lock, proceed):
    """The first observation pass in its own process: once it holds the
    posterior lock it reads the observed pairs again; it waits there
    until the competing pass has run."""
    import platform_matrix

    read, lock = cl.read, platform_matrix.fd_lock
    held: list[bool] = []

    def lock_then_note(fd, **kwargs):
        result = lock(fd, **kwargs)
        held.append(True)
        return result

    def read_then_pause(ws_, family, **kwargs):
        rows = read(ws_, family, **kwargs)
        if family == "experience" and held and not read_under_lock.is_set():
            read_under_lock.set()
            assert proceed.wait(30), "competing pass did not run"
        return rows

    platform_matrix.fd_lock = lock_then_note
    cl.read = read_then_pause
    out = src.amend_case_settlements(ws)
    assert out["case_observations"] == 1, out


def test_concurrent_observations_of_one_pair_apply_it_once(tmp_path):
    """Two settlement passes observe the same unobserved pair. The second
    reads the first pass's row under the lock and applies nothing: one
    Bernoulli event moves the belief once."""
    ws = _ws(tmp_path, [{"id": "C-1", "status": "PROVEN",
                         "answers_question": "q2"}])
    _arm_case(ws, "case-q2", "q2")

    _interleave_with_competing_writer(
        ws, "late-arm observation",
        paused=_observation_paused_after_its_read_under_the_lock)

    assert (_belief(ws, "case-q2"),
            len(cl.read(ws, "experience", schema_prefix="case-observation"))) == ((2.0, 1.0), 1)
