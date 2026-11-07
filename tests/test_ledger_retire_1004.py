# -*- coding: utf-8 -*-
"""tests/test_ledger_retire_1004.py — the ledger/data compat retirement
(issue #1004, slices R2a-R4).

The card's pins:

  1. EVERY legacy rel retires through ``consolidate_ledgers.py
     --retire-legacy``: rows land in the family's consolidated file in
     the order the old dual-read produced them (chronology), with the
     correct stamps; the legacy rel AND its lock file are deleted; a
     second run is a no-op; ``--dry-run`` writes nothing; NO
     ``runs/archive/`` is ever created.
  2. Readers are consolidated-only: with the legacy rels absent every
     reader face returns the consolidated rows; with a STALE legacy
     file present (pre-migration) no reader reads it — the dual-read
     path is gone.
  3. No-legacy repo scan: no production module under scripts/ (and
     hooks/) reads or writes a legacy rel; the retired names
     (LEGACY / SWITCHED / DEFAULT_MIGRATION / ARCHIVE_DIR_REL /
     include_legacy) do not survive in
     scripts/rlvr/consolidated_ledger.py.
  4. Liveness reports all four families from the consolidated files
     only (a dead registered schema reads 0).
  5. Seal round-trip: rows appended through the new family writers
     remain ``trusted_rows``-valid on an ARMED workspace.

Plus the per-family writer pins (R2a/R2b/R2c): the movers land their
rows in the family files, keep their stamps, and retire their per-module
lock rels (the consolidated lock is the single writer guard).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (SCRIPTS, SCRIPTS.parent / "tests", ROOT / "hooks"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from rlvr import consolidated_ledger as cl  # noqa: E402
from rlvr import ledger as rl  # noqa: E402
from rlvr import learning_seal as seal  # noqa: E402
from rlvr import marl  # noqa: E402
from rlvr import posteriors as dts  # noqa: E402
from rlvr import prediction_ledger as pl  # noqa: E402
from rlvr import signal_guard  # noqa: E402
from rlvr import state as rlvr_state  # noqa: E402
from rlvr import step_grain  # noqa: E402
from rlvr import step_ledger as sl  # noqa: E402
from rlvr import strategy_store as ss  # noqa: E402

TS = "2026-11-06T00:00:00Z"

#: every legacy rel of the compat window, per family, with the rows the
#: fixture seeds (mirrors the retire CLI's explicit registry).
FIXTURE_RELS: dict[str, list[tuple[str, list[dict], str]]] = {
    "experience": [
        ("runs/transitions.jsonl",
         [{"schema": "transition/1", "ts": TS, "claim": "C-1",
           "event": "ok"}], "ws"),
        ("runs/q-cell-log.jsonl",
         [{"schema": "q-cell-obs/1", "ts": TS, "signature_hash": "fp1",
           "method_family": "graph"}], "ws"),
        ("runs/step-ledger.jsonl",
         [{"schema": "step-record/1", "ts": TS, "session_id": "s1",
           "call_id": "h1", "tool": "Bash", "input_sha": "a",
           "output_sha": "b", "reads": [], "writes": [],
           "duration_ms": None},
          {"schema": "step-record/2", "ts": TS, "session_id": "s1",
           "step_id": "st1", "claim_ref": "C-1", "tool_calls": 1,
           "call_ids": ["h1"], "first_ts": TS, "last_ts": TS,
           "duration_ms": 1.0}], "ws"),
        ("runs/evidence-credit.jsonl",
         [{"schema": "evidence-item/1", "id": "e1", "ts": TS,
           "step_ref": "st1", "claim_ref": "C-1", "kind": "confirm",
           "artifact_sha": "x", "certified": True},
          {"schema": "credit-amendment/1", "ts": TS, "evidence_id": "e1",
           "action": "confirm", "amount": 1.0, "reason": ""}], "ws"),
    ],
    "settlement": [
        ("runs/rollout-ledger.jsonl",
         [{"schema": "rollout-ledger/1", "rollout_id": "task/C-9",
           "kind": "task", "anchor": "C-9", "ts": TS, "signals": [],
           "reward": None, "settlement": None}], "ws"),
        ("runs/attributed-waste.jsonl",
         [{"schema": "attributed-waste/1", "ts": TS, "claim_ref": "C-1",
           "step_id": "st1", "kind": "wall_s_overrun", "budget_s": 1.0,
           "actual_s": 2.0, "waste_s": 1.0}], "ws"),
        ("cost_events.jsonl",
         [{"ts": TS, "amount": 1.5, "source": "hook"}], "ws"),
    ],
    "telemetry": [
        ("runs/interventions.jsonl",
         [{"schema": "intervention/1", "ts": TS, "trigger": "manual",
           "actor": "op", "subject_sha": "s", "note_sha": "n"}], "ws"),
        ("runs/predictions.jsonl",
         [{"schema": "prediction-ledger/1", "id": "P-1",
           "claim_id": "C-1", "statement": "st", "discriminator": "d",
           "registered_by": "a", "registered_ts": TS,
           "status": "pending"}], "ws"),
        ("runs/situation-stream.jsonl",
         [{"schema": "situation/1", "ts": TS, "trigger": "tick",
           "tick": 1, "state": {}, "signature": "sig",
           "signature_hash": "h"}], "ws"),
        ("runs/strategy-log.jsonl",
         [{"ts": TS, "event": "dispatch", "strategy": "graph",
           "declared": True, "claim": "C-1", "attempts_at_snapshot": 0}],
         "ws"),
    ],
    "knowledge": [
        ("posterior-store.jsonl",
         [{"schema": "posterior-store/1", "ts": TS, "workspace_id": "other",
           "arm_key": "graph", "method_family": "graph",
           "feature_key": "none", "fingerprint": None, "status": "ok",
           "credit": 1.0, "censored": False, "facts_citing": 0,
           "propensity": None, "phi_delta": None,
           "provenance": {"dispatch_id": ""}}], "guard"),
        ("marl-negative.jsonl",
         [{"schema": "marl-negative/1", "ts": TS,
           "signature_class": "cls", "agent_type": None,
           "method_family": "graph", "tool_chain": "a|b", "fails": 1}],
         "guard"),
        ("runs/feature-table.jsonl",
         [{"schema": "feature-table/1", "ts": TS, "run_id": "r1",
           "features": {"f": 1}, "outcome": {"status": "landed"}}], "ws"),
        ("runs/posterior-store.jsonl",
         [{"schema": "posterior-store/1", "ts": TS, "workspace_id": "ws",
           "arm_key": "tree", "method_family": "tree",
           "feature_key": "none", "fingerprint": None, "status": "ok",
           "credit": 0.5, "censored": False, "facts_citing": 0,
           "propensity": None, "phi_delta": None,
           "provenance": {"dispatch_id": ""}}], "ws"),
    ],
}

#: the expected stamps after retirement (single-stamp rels infer the
#: stamp for unstamped rows: cost rows -> cost-event/1, strategy-log
#: rows -> strategy-log/1; every other rel's rows carry their own).
EXPECTED_STAMPS: dict[str, dict[str, tuple[str, ...]]] = {
    "experience": {
        "runs/transitions.jsonl": ("transition/1",),
        "runs/q-cell-log.jsonl": ("q-cell-obs/1",),
        "runs/step-ledger.jsonl": ("step-record/1", "step-record/2"),
        "runs/evidence-credit.jsonl": ("evidence-item/1",
                                       "credit-amendment/1"),
    },
    "settlement": {
        "runs/rollout-ledger.jsonl": ("rollout-ledger/1",),
        "runs/attributed-waste.jsonl": ("attributed-waste/1",),
        "cost_events.jsonl": ("cost-event/1",),
    },
    "telemetry": {
        "runs/interventions.jsonl": ("intervention/1",),
        "runs/predictions.jsonl": ("prediction-ledger/1",),
        "runs/situation-stream.jsonl": ("situation/1",),
        "runs/strategy-log.jsonl": ("strategy-log/1",),
    },
    "knowledge": {
        "posterior-store.jsonl": ("posterior-store/1",),
        "marl-negative.jsonl": ("marl-negative/1",),
        "runs/feature-table.jsonl": ("feature-table/1",),
        "runs/posterior-store.jsonl": ("posterior-store/1",),
    },
}


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    return ws


def _seed_legacy(ws: Path, guard: Path) -> None:
    """Write every fixture legacy rel (registry order, fixture rows)."""
    for family, rels in FIXTURE_RELS.items():
        for rel, rows, scope in rels:
            p = (guard if scope == "guard" else ws) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n"
                                 for r in rows), encoding="utf-8")


def _guard() -> Path:
    """The guarded root this test process resolves (the conftest
    isolation points KUNGLAO_POSTERIOR_STORE at a tmp path)."""
    return ss.store_root()


def _lines(p: Path) -> list[dict]:
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _expected_order(family: str) -> list[dict]:
    """The exact post-retirement read order: legacy rows in registry rel
    order, file order within a rel (the old dual-read's legacy segment),
    with single-stamp inference applied to unstamped rows."""
    out: list[dict] = []
    for rel, rows, _scope in FIXTURE_RELS[family]:
        stamps = EXPECTED_STAMPS[family][rel]
        for row in rows:
            if stamps and len(stamps) == 1 and not row.get("schema"):
                out.append({**row, "schema": stamps[0]})
            else:
                out.append(row)
    return out


# ------------------------------------------------ pin 1: the retire CLI

def test_retire_every_legacy_rel_fixture(tmp_path):
    import consolidate_ledgers as cli
    ws = _ws(tmp_path)
    guard = _guard()
    _seed_legacy(ws, guard)

    rc = cli.main([str(ws), "--retire-legacy"])
    assert rc == 0

    # every legacy rel AND its lock file are deleted
    for family, rels in FIXTURE_RELS.items():
        for rel, _rows, scope in rels:
            p = (guard if scope == "guard" else ws) / rel
            assert not p.exists(), f"{rel} survived retirement"
            assert not (p.parent / f".{p.stem}.lock").exists(), \
                f"{rel}'s lock file survived retirement"
    # the archive dir is never created
    assert not (ws / "runs" / "archive").exists()

    # rows readable from the consolidated files, correct order + stamps
    for family in FIXTURE_RELS:
        got = cl.read(ws, family)
        want = _expected_order(family)
        assert [r.get("schema") for r in got] \
            == [r.get("schema") for r in want], family
        assert got == want, family

    # idempotent: a second run is a no-op (exit 0, files unchanged)
    snap = {f: cl.family_path(ws, f).read_bytes()
            for f in cl.FAMILIES}
    assert cli.main([str(ws), "--retire-legacy"]) == 0
    assert {f: cl.family_path(ws, f).read_bytes()
            for f in cl.FAMILIES} == snap


def test_retire_dry_run_writes_nothing(tmp_path):
    import consolidate_ledgers as cli
    ws = _ws(tmp_path)
    guard = _guard()
    _seed_legacy(ws, guard)
    rc = cli.main([str(ws), "--retire-legacy", "--dry-run"])
    assert rc == 0
    # nothing was written or deleted
    for family, rels in FIXTURE_RELS.items():
        for rel, _rows, scope in rels:
            assert ((guard if scope == "guard" else ws) / rel).is_file()
        assert not cl.family_path(ws, family).exists()
    assert not (ws / "runs" / "archive").exists()


def test_retire_partial_append_keeps_legacy_rel(tmp_path, monkeypatch):
    """A verify failure keeps the legacy rel (exit 3) — nothing lost."""
    import consolidate_ledgers as cli
    ws = _ws(tmp_path)
    _seed_legacy(ws, _guard())
    # refuse the settlement append: a DIRECTORY where the consolidated
    # FILE must live (the os.write open fails -> the append refuses)
    (ws / "runs" / "settlement.jsonl").mkdir()
    rc = cli.main([str(ws), "--retire-legacy"])
    assert rc == 3
    assert (ws / "runs" / "rollout-ledger.jsonl").is_file(), \
        "the legacy rel must survive a failed append"


# ------------------------------------- pin 2: readers are consolidated-only

def test_readers_ignore_stale_legacy_files(tmp_path):
    """With a stale legacy file present, no reader reads it."""
    ws = _ws(tmp_path)
    guard = _guard()
    _seed_legacy(ws, guard)
    # fresh consolidated rows per family (what the readers must return)
    fam_row = {"schema": "case-observation/1", "ts": TS, "case": "x"}
    assert cl.append(ws, "experience", fam_row) is True
    assert rl.record(ws, "task", "C-2", [])["appended"] is True
    assert cl.append(ws, "telemetry",
                     {"schema": "situation/1", "ts": TS,
                      "trigger": "t", "tick": 2, "state": {},
                      "signature": "s", "signature_hash": "h"}) is True
    assert cl.append(ws, "knowledge",
                     {"schema": "feature-table/1", "ts": TS,
                      "run_id": "r2", "features": {}, "outcome": {}}) is True

    # experience: the step-reader sees only the consolidated step row
    assert cl.append(ws, "experience",
                     {"schema": "step-record/1", "ts": TS,
                      "session_id": "s2", "call_id": "h2", "tool": "Read",
                      "input_sha": "a", "output_sha": "b", "reads": [],
                      "writes": [], "duration_ms": None}) is True
    steps = sl.read_steps(ws)
    assert [r["call_id"] for r in steps] == ["h2"]
    # settlement: the rollout ledger reads only its consolidated rows
    rows = rl.read(ws)
    assert [r["rollout_id"] for r in rows] == ["task/C-2"]
    # telemetry: situations + predictions read only consolidated rows
    assert [r["trigger"] for r in rlvr_state.read_situations(ws)] == ["t"]
    assert pl.read_ledger(ws) == []
    # knowledge: negatives/table readers see only consolidated rows
    negs = marl.read_negatives()
    assert negs == []
    # liveness is consolidated-only too (pin 4 overlaps here)
    counts = cl.liveness(ws)
    assert counts["telemetry:situation/1"] == 1
    assert counts["telemetry:intervention/1"] == 0, \
        "the stale legacy intervention must not count"


# --------------------------------------------- pin 3: the no-legacy scan

LEGACY_REL_NAMES = sorted({rel for rels in FIXTURE_RELS.values()
                           for rel, _r, _s in rels})
RETIRED_CORE_NAMES = ("LEGACY", "SWITCHED", "DEFAULT_MIGRATION",
                      "ARCHIVE_DIR_REL", "include_legacy")
#: the retired names' sanctioned code homes: the retire CLI's explicit
#: registry, and the blind-act deny walls (a deny key REFUSES the path —
#: it never opens it; denying more is safe, #721). Both deny walls spell
#: the rel as a BASENAME, which is why the pin checks basenames too.
SCAN_ALLOWLIST = {"consolidate_ledgers.py", "settlement_scorer.py",
                  "rt_read_barrier.py"}
#: a bare basename literal is also a retired-name reference; the scan
#: must not go blind just because a deny wall drops the "runs/" prefix.
LEGACY_BASENAMES = frozenset(Path(rel).name for rel in LEGACY_REL_NAMES)


def _production_py_files() -> list[Path]:
    out = sorted(SCRIPTS.rglob("*.py"))
    out += sorted((SCRIPTS.parent / "hooks").glob("*.py"))
    return [p for p in out
            if not any(part in ("tests", "devkit", "eval", "archive")
                       for part in p.parts)]


def _code_string_constants(path: Path) -> list[tuple[int, str]]:
    """String constants in CODE positions (docstrings and comments are
    excluded — the pin is on reads/writes, never on prose)."""
    import ast
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)):
                docstrings.add(id(node.body[0].value))
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in docstrings):
            out.append((node.lineno, node.value))
    return out


def test_no_legacy_path_repo_scan():
    core = (SCRIPTS / "rlvr" / "consolidated_ledger.py").read_text(
        encoding="utf-8")
    for name in RETIRED_CORE_NAMES:
        assert name not in core, \
            f"consolidated_ledger.py still carries {name!r}"
    offenders: list[str] = []
    for p in _production_py_files():
        for lineno, value in _code_string_constants(p):
            allowed = p.name in SCAN_ALLOWLIST
            for rel in LEGACY_REL_NAMES:
                if rel in value and not allowed:
                    offenders.append(f"{p.name}:{lineno}: {rel}")
            if not allowed and value.strip() in LEGACY_BASENAMES:
                offenders.append(
                    f"{p.name}:{lineno}: {value.strip()} (basename)")
    assert not offenders, \
        "legacy rels referenced outside the retire CLI: " + ", ".join(
            offenders)


# --------------------------------------------------- pin 4: liveness

def test_liveness_reports_all_four_families(tmp_path):
    ws = _ws(tmp_path)
    assert cl.append(ws, "experience",
                     {"schema": "case-observation/1", "ts": TS,
                      "case": "c"}) is True
    assert rl.record(ws, "task", "C-3", [])["appended"] is True
    assert cl.append(ws, "telemetry",
                     {"schema": "intervention/1", "ts": TS,
                      "trigger": "t", "actor": "op", "subject_sha": "s",
                      "note_sha": "n"}) is True
    assert cl.append(ws, "knowledge",
                     {"schema": "marl-negative/1", "ts": TS,
                      "signature_class": "k", "agent_type": None,
                      "method_family": "graph", "tool_chain": None,
                      "fails": 1}) is True
    counts = cl.liveness(ws)
    assert counts["experience:case-observation/1"] == 1
    assert counts["settlement:rollout-ledger/1"] == 1
    assert counts["telemetry:intervention/1"] == 1
    assert counts["knowledge:marl-negative/1"] == 1
    # a dead registered schema reads 0 — visible, never absent
    assert counts["telemetry:rollout-timer/1"] == 0
    assert counts["knowledge:feature-table/1"] == 0
    # every family is represented
    for family in cl.FAMILIES:
        assert any(k.startswith(f"{family}:") for k in counts)


# ---------------------------------------------- pin 5: the seal wall

@pytest.fixture
def armed(tmp_path, monkeypatch):
    key = tmp_path / "learning.key"
    key.write_bytes(b"k" * 48)
    monkeypatch.setattr(seal, "KEY_PATH", key)
    monkeypatch.setattr(seal, "_ANCHOR", {"build": None})
    import kunglao_log as _kl
    _kl._WARN_LAST.clear()
    return key


def test_seal_round_trip_through_family_writers(armed, tmp_path):
    ws = _ws(tmp_path)
    # the cross-task store writer seals at write (unchanged)
    out = ss.append_store_row(ws, method_family="graph", status="ok",
                              credit=1.0)
    assert out["appended"] is True
    # the row landed in the knowledge family file
    kpath = cl.family_path(ws, "knowledge")
    rows = _lines(kpath)
    assert rows and "seal" in rows[-1]
    # the reader's trusted wall verifies it (armed); the cross-task read
    # face is leave-one-out by workspace, so the cross-task face reads
    # without the ws arg
    kept = ss.load_rows()
    assert any(r.get("method_family") == "graph" for r in kept)
    # a forged row appended beside it is refused
    forged = {"schema": ss.STORE_SCHEMA, "ts": TS, "workspace_id": "evil",
              "arm_key": "graph", "method_family": "graph",
              "feature_key": "none", "fingerprint": None, "status": "ok",
              "credit": 0.0, "censored": False, "facts_citing": 0,
              "propensity": None, "phi_delta": None,
              "provenance": {"dispatch_id": ""}}
    with kpath.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(forged) + "\n")
    kept = ss.load_rows()
    assert all(r.get("workspace_id") != "evil" for r in kept)


# ------------------------------------------- R2a/R2b/R2c writer pins

def test_settlement_family_writers(tmp_path):
    ws = _ws(tmp_path)
    spath = cl.family_path(ws, "settlement")
    # the rollout ledger rides the settlement family
    rec = rl.record(ws, "task", "C-4", [{"type": "strategy_arm",
                                         "source": "t", "value": "graph",
                                         "ts": TS}])
    assert rec["appended"] is True
    st = rl.settle(ws, "task/C-4", {"reward": 1.0, "band": "PROVEN",
                                    "rule_id": "r", "evidence_refs": []})
    assert st["appended"] is True
    rows = _lines(spath)
    assert {r["schema"] for r in rows} == {"rollout-ledger/1"}
    # the per-module lock rel is retired — the consolidated lock guards
    assert (spath.parent / ".settlement.lock").exists()
    assert not (spath.parent / ".rollout-ledger.lock").exists()
    # fold/settled semantics ride the family file unchanged
    folded = rl.fold(ws, "task/C-4")
    assert folded is not None and folded["settlement"]["reward"] == 1.0
    assert len(rl.settled(ws, kind="task")) == 1
    # the byte-prefix invariant: the first append's bytes never move
    prefix = spath.read_bytes().splitlines(keepends=True)[0]
    rl.record(ws, "task", "C-4b", [])
    assert spath.read_bytes().startswith(prefix)
    # attributed waste rides the settlement family
    w = step_grain.record_attributed_waste(
        ws, claim_ref="C-4", step_id="st", kind="wall_s_overrun",
        budget_s=1.0, actual_s=2.0)
    assert w is not None and w["schema"] == "attributed-waste/1"
    assert "attributed-waste/1" in [r["schema"] for r in _lines(spath)]


def test_settlement_cost_events(tmp_path):
    import cost_gate
    ws = _ws(tmp_path)
    cost_gate.append_event(ws, 3.25, source="test")
    rows = [r for r in _lines(cl.family_path(ws, "settlement"))
            if r.get("schema") == "cost-event/1"]
    assert len(rows) == 1 and rows[0]["amount"] == 3.25
    # the reader face rides the family read
    events = cost_gate.load_events(ws)
    assert len(events) == 1 and events[0]["amount"] == 3.25
    assert not (ws / "cost_events.jsonl").exists()


def test_telemetry_family_writers(tmp_path):
    ws = _ws(tmp_path)
    tpath = cl.family_path(ws, "telemetry")
    row = pl.register(ws, "C-1", "the binary is packed",
                      "entropy exceeds the threshold", actor="tester")
    assert row is not None and row["schema"] == "prediction-ledger/1"
    assert _lines(tpath)[-1]["id"] == row["id"]
    assert pl.read_ledger(ws)[0]["id"] == row["id"]
    snap = rlvr_state.append_snapshot(ws, "worker-return", tick=3)
    assert snap["appended"] is True
    assert _lines(tpath)[-1]["schema"] == "situation/1"
    assert rlvr_state.read_situations(ws)[-1]["trigger"] == "worker-return"
    iv = sl.record_intervention(ws, trigger="manual", actor="op",
                                subject="s", note="n")
    assert iv is not None and iv["schema"] == "intervention/1"
    assert _lines(tpath)[-1]["trigger"] == "manual"
    assert (tpath.parent / ".telemetry.lock").exists()


def test_telemetry_strategy_log_writer_and_join(tmp_path):
    import dispatch_gate
    from rlvr import triples
    ws = _ws(tmp_path)
    (ws / "claim-register.yaml").write_text(
        "claims:\n  - id: C-1\n    promotion_attempts: 0\n",
        encoding="utf-8")
    dispatch_gate._log_strategy_dispatch(ws, "C-1", "[strategy graph] go")
    trows = _lines(cl.family_path(ws, "telemetry"))
    assert trows[-1]["schema"] == "strategy-log/1"
    assert trows[-1]["event"] == "dispatch"
    assert trows[-1]["strategy"] == "graph"
    assert not (ws / "runs" / "strategy-log.jsonl").exists()
    # the triples join reads the family face
    assert triples._strategy_arm_by_claim(ws) == {"C-1": "graph"}
    # the dispatch-gate PQ history face rides the family too
    claim_q = {"C-1": "q"}  # claim id -> question id (the #109 mapping)
    assert dispatch_gate._pq_dispatched_before(ws, "q", claim_q) is True


def test_knowledge_family_writers(tmp_path):
    ws = _ws(tmp_path)
    kpath = cl.family_path(ws, "knowledge")
    neg = marl.record_negative(ws, method_family="graph",
                               tool_chain=["a", "b"])
    assert neg["appended"] is True
    assert _lines(kpath)[-1]["schema"] == "marl-negative/1"
    assert len(marl.read_negatives()) == 1
    rec = dts.record(ws, "sig-hash", "graph", 1)
    assert rec["appended"] is True
    assert _lines(kpath)[-1]["schema"] == dts.SCHEMA
    assert [r["arm"] for r in dts.read(ws)] == ["graph"]
    # the credit series lands in the family with the workspace identity
    cred = ss.append_workspace_credit_row(
        ws, method_family="tree", status="ok", credit=0.5, claim="C-1",
        credit_kind="step")
    assert cred["appended"] is True
    # the degeneracy series reads the calling workspace's rows only
    vals = signal_guard.recent_credits(ws)
    assert vals == [0.5]
    # the per-module lock rel is retired
    assert not (ws / "runs" / ".posterior-store.lock").exists()
    assert (kpath.parent / ".knowledge-store.lock").exists()


# --------------------------- pin 6: repo-scan mutation probe

def test_basename_scan_pin_catches_a_basename_literal(tmp_path, monkeypatch):
    """Mutation probe: the repo scan is not blind to a bare retired
    basename (the deny-wall spelling that drops the runs/ prefix)."""
    import sys
    mod = sys.modules[__name__]
    fake = tmp_path / "ghost_reader.py"
    fake.write_text('REL = "q-cell-log.jsonl"\n', encoding="utf-8")
    monkeypatch.setattr(mod, "_production_py_files", lambda: [fake])
    try:
        mod.test_no_legacy_path_repo_scan()
    except AssertionError as exc:
        assert "ghost_reader.py" in str(exc)
    else:
        raise AssertionError("the basename literal escaped the repo scan")


def test_verbatim_unstamped_row_counts_as_no_schema_in_liveness(tmp_path):
    """A multi-schema rel's unstamped row is copied verbatim and stays
    VISIBLE under the no-schema liveness key — never silently dropped."""
    import json
    import consolidate_ledgers as cli
    ws = _ws(tmp_path)
    rel = ws / "runs" / "step-ledger.jsonl"
    rel.parent.mkdir(parents=True, exist_ok=True)
    rel.write_text(json.dumps({"ts": TS, "session_id": "s1"}) + "\n",
                   encoding="utf-8")
    assert cli.main([str(ws), "--retire-legacy"]) == 0
    assert cl.liveness(ws)["experience:(no-schema)"] == 1
    assert not rel.exists()
