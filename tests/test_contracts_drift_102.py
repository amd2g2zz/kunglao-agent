#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TDD — issue #102 (split from #95 A5): cross-process contract drift.

Root cause of the drift family: producers and consumers define the same
byte-level contract in separate comments. Three instances, one fix layer:

  1. event field name: event_taxonomy's ledger branch keyed on `event_type`
     (kunglao_record.record_event face), but kunglao_log.emit writes the
     word in `action` (contracts.EVENT_FIELD). Seven main-stream classes
     (fact_written / fact_verified / claim_promoted / claim_refuted /
     failure_recorded / intent_opened / intent_closed) classified as None —
     fabricated zeros in every statusline/digest.
  2. bandit row shape: the CONSUMER (scripts/optimizer_bandit.py) was
     DELETED (#95 A7, closed by #104) — per the issue note ("keep the fix
     at the contracts layer; don't resurrect the module") this item closes
     with the deletion. Nothing to assert beyond the contracts registry
     existing: the row-shape lesson generalizes as contracts.py, and no
     producer/consumer pair for the old top-level arm/z shape survives.
  3. plan_drift crash fall-through: dispatch_gate._plan_drift_auto treated
     any rc outside (0,2,3) as pass-through — a detector crash (rc=1 on a
     malformed claim-register.yaml) let dispatch proceed with the traceback
     discarded and zero telemetry. Fix: fail-open is kept (a PreToolUse
     safety net must not block on its own breakage) but the degradation is
     OBSERVABLE — stderr note + `plan_drift_crashed` trace row carrying the
     rc and the detector's last stderr line.

Fix architecture (#102): scripts/contracts.py as the single source —
exit-code registry, event field schema, gate-subprocess legal rc sets.
Producers and consumers import from it; a drift of this class can never
again pass CI silently.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
HOOKS_DIR = REPO_ROOT / "hooks"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import event_taxonomy as et  # noqa: E402
from kunglao_log import emit, iter_jsonl, log_path  # noqa: E402

# the seven controlled ledger words (kunglao_record.EVENT_TYPES) — the same
# words kunglao_log-shaped rows carry in the `action` field
SEVEN_WORDS = ("fact_written", "fact_verified", "claim_promoted",
               "claim_refuted", "failure_recorded", "intent_opened",
               "intent_closed")


def _load_dispatch_gate():
    """Load hooks/dispatch_gate.py as a module (test_plan_drift_auto_602
    convention: by-spec, because scripts/ historically shipped another
    dispatch_gate)."""
    spec = importlib.util.spec_from_file_location(
        "_dispatch_gate_for_102", HOOKS_DIR / "dispatch_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# =====================================================================
# RED 1 — event field name drift (classify_event vs kunglao_log.emit)
# =====================================================================

class TestLedgerActionFieldDrift:
    """kunglao_log.emit-shaped rows must classify through the ledger branch.

    The ledger stream has TWO producer faces sharing one scan
    (event_taxonomy.classify_workspace reads BOTH ledger.jsonl and
    runs/logs/kunglao-*.jsonl with source="ledger"):
      - kunglao_record.record_event writes the word in `event_type`
      - kunglao_log.emit writes the word in `action` (EVENT_FIELD)
    Pre-#102 the branch read `event_type` only, so every kunglao_log-shaped
    row classified as None.
    """

    def test_classify_event_accepts_emit_action_rows(self):
        for word in SEVEN_WORDS:
            row = {"ts": "2026-09-06T00:00:00Z", "actor": "worker",
                   "action": word, "claim": "C-1", "exit": None,
                   "detail": None}
            assert et.classify_event(row, source="ledger") == word, (
                f"#102: kunglao_log.emit-shaped row with action={word!r} "
                f"classified as "
                f"{et.classify_event(row, source='ledger')!r} (fabricated "
                f"zero in statusline/digest)")

    def test_classify_event_event_type_face_unchanged(self):
        """kunglao_record rows keep their classification (no regression)."""
        for word in SEVEN_WORDS:
            assert et.classify_event({"event_type": word},
                                     source="ledger") == word
        assert et.classify_event({"event_type": "unknown_kind"},
                                 source="ledger") is None

    def test_classify_event_unknown_action_stays_none(self):
        """Unknown action words (real EMIT_ACTIONS words among them) must
        NOT be fabricated into a taxonomy class — None is the
        unattributed-rate signal, a wrong class is worse."""
        assert et.classify_event({"action": "dispatch"},
                                 source="ledger") is None
        assert et.classify_event({"action": "tool_call"},
                                 source="ledger") is None
        assert et.classify_event({"action": None}, source="ledger") is None
        assert et.classify_event({"action": ""}, source="ledger") is None

    def test_event_field_schema_constant_used_by_taxonomy(self):
        """The field name comes from contracts.py, not a local literal."""
        import contracts
        assert contracts.EVENT_FIELD == "action"
        assert et.EVENT_FIELD == contracts.EVENT_FIELD, (
            "#102: event_taxonomy must import the event-field schema from "
            "contracts (a second local literal is the drift class itself)")

    def test_roundtrip_real_emitter_through_consumer_parser(self):
        """The #102 contract test: a row emitted by the REAL kunglao_log
        emitter, read back by the REAL stream reader, classifies through the
        REAL consumer parser. Drift of this class can never pass CI."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            emit(ws, "worker", "fact_written", claim="C-1",
                 detail="facts/F001.md")
            rows = list(iter_jsonl(
                log_path(ws).read_text(encoding="utf-8").splitlines()))
            assert len(rows) == 1
            assert et.classify_event(rows[0], source="ledger") == \
                "fact_written"

    def test_fixture_digest_seven_classes_nonzero(self):
        """Acceptance: the seven main-stream classes are non-zero in a
        fixture digest built purely from kunglao_log.emit rows."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            ws = Path(td)
            for word in SEVEN_WORDS:
                emit(ws, "worker", word, claim="C-1")
            counts = et.classify_workspace(ws)
            zero = [w for w in SEVEN_WORDS if counts.get(w, 0) != 1]
            assert not zero, (
                f"#102 acceptance: classes {zero} still read as fabricated "
                f"zeros in the digest; counts={ {w: counts.get(w) for w in SEVEN_WORDS} }")
            digest = et.round_digest_text(ws)
            for word in SEVEN_WORDS:
                assert f"{word}=1" in digest


# =====================================================================
# RED 2 — plan_drift crash fall-through
# =====================================================================

class TestPlanDriftCrashFace:
    """A detector crash must degrade LOUDLY, never silently.

    Contract (post-#102): under --auto the only legal bytes are the
    contracts.PLAN_DRIFT_AUTO_RCS trio {0, 2, 3}; any other rc (rc=1 = an
    unhandled exception inside plan_drift_detector, e.g. a malformed
    claim-register.yaml) takes the explicit crash face:
      - dispatch verdict stays fail-open (None) — NON-FATAL by design;
      - stderr carries an operator-visible note;
      - one `plan_drift_crashed` trace row lands in the unified event log
        with exit=rc and the detector's last stderr line.
    """

    def _ws(self, tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir()
        return ws

    def _trace_rows(self, ws: Path) -> list[dict]:
        logs = ws / "runs" / "logs"
        if not logs.is_dir():
            return []
        rows: list[dict] = []
        for p in sorted(logs.glob("kunglao-*.jsonl")):
            rows.extend(iter_jsonl(
                p.read_text(encoding="utf-8", errors="replace").splitlines()))
        return rows

    def test_crash_rc_returns_fail_open_and_is_observable(
            self, tmp_path, monkeypatch, capsys):
        """rc=1 (crash) -> None (fail-open) + stderr note + trace row."""
        dg = _load_dispatch_gate()
        ws = self._ws(tmp_path)

        class FakeProc:
            returncode = 1
            stdout = ""
            stderr = "yaml.YAMLError: expected ',' or ']'"

        monkeypatch.setattr(sys.modules["subprocess"], "run",
                            lambda *a, **k: FakeProc())
        rc = dg._plan_drift_auto(ws, "C-1", "prompt")
        captured = capsys.readouterr()
        assert rc is None, (
            f"#102: crash face must stay fail-open (None), got {rc!r}")
        assert "plan-drift auto CRASHED" in captured.err, (
            f"#102: crash must draw an operator-visible stderr note, got: "
            f"{captured.err!r}")
        rows = [r for r in self._trace_rows(ws)
                if r.get("action") == "plan_drift_crashed"]
        assert len(rows) == 1, (
            f"#102: exactly one plan_drift_crashed trace row expected, got "
            f"{len(rows)}: {rows}")
        row = rows[0]
        assert row.get("exit") == 1, f"trace row must carry rc, got {row}"
        assert "YAMLError" in str(row.get("detail")), (
            f"#102: trace detail must carry the detector stderr tail "
            f"(post-mortem without source re-read), got {row.get('detail')!r}")
        assert row.get("claim") == "C-1"

    def test_unexpected_rc_also_takes_crash_face(self, tmp_path, monkeypatch,
                                                 capsys):
        """The registry set is the whole contract: rc=42 (an unknown byte)
        takes the SAME explicit crash face — never a silent fall-through."""
        dg = _load_dispatch_gate()
        ws = self._ws(tmp_path)

        class FakeProc:
            returncode = 42
            stdout = ""
            stderr = ""

        monkeypatch.setattr(sys.modules["subprocess"], "run",
                            lambda *a, **k: FakeProc())
        rc = dg._plan_drift_auto(ws, "C-1", "prompt")
        captured = capsys.readouterr()
        assert rc is None
        assert "plan-drift auto CRASHED" in captured.err
        rows = [r for r in self._trace_rows(ws)
                if r.get("action") == "plan_drift_crashed"]
        assert len(rows) == 1 and rows[0].get("exit") == 42

    def test_real_detector_crash_on_malformed_register(
            self, tmp_path, capsys):
        """End-to-end with the REAL detector: a workspace whose
        claim-register.yaml carries bad YAML crashes plan_drift_detector
        --auto with rc=1 (verified probe) — the helper must return fail-open
        with the crash observed on both channels."""
        dg = _load_dispatch_gate()
        ws = self._ws(tmp_path)
        (ws / "claim-register.yaml").write_text(
            "claims:\n- id: C-1\n  status: OPEN\ntitle: [unclosed\n",
            encoding="utf-8")
        (ws / "global_plan.txt").write_text("C-1 in plan\n", encoding="utf-8")

        rc = dg._plan_drift_auto(ws, "C-1", "prompt")
        captured = capsys.readouterr()
        assert rc is None, (
            f"#102: malformed-register crash must fail open, got {rc!r}")
        assert "plan-drift auto CRASHED" in captured.err, captured.err
        rows = [r for r in self._trace_rows(ws)
                if r.get("action") == "plan_drift_crashed"]
        assert rows, "#102: real crash produced no plan_drift_crashed row"
        assert rows[0].get("exit") == 1

    def test_plan_drift_crashed_registered_in_emit_actions(self):
        """#459 discipline: the new action word must be a member of the
        controlled vocabulary (test_event_stream_adoption's anchor scans the
        _emit_trace literal)."""
        assert "plan_drift_crashed" in et.EMIT_ACTIONS

    def test_crash_face_does_not_change_legal_rc_behavior(
            self, tmp_path, monkeypatch):
        """Regression guard: 0 -> None, 2 -> 2, 3 -> 3 (the #602 pins keep
            their bytes; the crash face only claims the space OUTSIDE the
            registry set)."""
        dg = _load_dispatch_gate()
        ws = self._ws(tmp_path)
        for code, expected in ((0, None), (2, 2), (3, 3)):
            class FakeProc:
                returncode = code
                stdout = f"DRIFT_AUTO rc={code}"
                stderr = ""

            monkeypatch.setattr(sys.modules["subprocess"], "run",
                                lambda *a, **k: FakeProc())
            got = dg._plan_drift_auto(ws, "C-1", "prompt")
            assert got == expected, (
                f"#102: rc={code} must map to {expected!r}, got {got!r}")


# =====================================================================
# contracts.py — the single source (#102 architectural fix)
# =====================================================================

class TestContractsRegistry:
    """scripts/contracts.py registers the bytes both sides already speak.

    Scope discipline: the file collects EXISTING facts (convergence_check's
    0-5 + 64 + 65 registry, plan_drift's --auto trio, the event field name)
    — it invents no new contract. convergence_check imports its face, so
    there is exactly ONE definition.
    """

    def test_contracts_module_exists_with_registry(self):
        import contracts
        assert contracts.EXIT_CONVERGED == 0
        assert contracts.EXIT_DISPATCH == 1
        assert contracts.EXIT_VERIFY == 2
        assert contracts.EXIT_SATURATED == 3
        assert contracts.EXIT_BLOCKED == 4
        assert contracts.EXIT_PARK == 5
        assert contracts.EXIT_MISSING_WORKSPACE == 64
        assert contracts.EXIT_CRASHED == 65
        assert contracts.EVENT_FIELD == "action"
        assert contracts.PLAN_DRIFT_AUTO_RCS == frozenset({0, 2, 3})

    def test_registry_values_distinct(self):
        """The #99 consumer contract: every face owns its byte."""
        import contracts
        values = [contracts.EXIT_CONVERGED, contracts.EXIT_DISPATCH,
                  contracts.EXIT_VERIFY, contracts.EXIT_SATURATED,
                  contracts.EXIT_BLOCKED, contracts.EXIT_PARK,
                  contracts.EXIT_MISSING_WORKSPACE, contracts.EXIT_CRASHED]
        assert len(set(values)) == len(values), f"byte collision: {values}"

    def test_convergence_check_imports_its_face(self):
        """Single definition: convergence_check's names ARE contracts'
        objects (imported, not re-stated) — the drift class is structurally
        impossible."""
        import contracts
        import convergence_check as cc
        for name in ("EXIT_CONVERGED", "EXIT_DISPATCH", "EXIT_VERIFY",
                     "EXIT_SATURATED", "EXIT_BLOCKED", "EXIT_PARK",
                     "EXIT_CRASHED"):
            assert getattr(cc, name) == getattr(contracts, name), (
                f"#102: convergence_check.{name} drifted from the registry")
        assert cc.EXIT_CRASHED == 65 and cc.EXIT_MISSING_WORKSPACE == 64

    def test_dispatch_gate_uses_registry_rc_set(self):
        """The gate branches on the contracts set, not a local literal
        (0,2,3) — the plan_drift --auto face."""
        import contracts
        dg = _load_dispatch_gate()
        src = (HOOKS_DIR / "dispatch_gate.py").read_text(encoding="utf-8")
        assert "PLAN_DRIFT_AUTO_RCS" in src, (
            "#102: dispatch_gate must branch on the contracts rc set")
        assert dg is not None and contracts.PLAN_DRIFT_AUTO_RCS == \
            frozenset({0, 2, 3})

    def test_bandit_row_shape_item_closed_by_deletion(self):
        """Issue #102 item 2 (bandit row shape): the only consumer
        (optimizer_bandit.attribute_rows) is DELETED (#95 A7 / #104). The
        issue itself rules the fix stays at the contracts layer — the
        module must NOT be resurrected; the shape lesson survives as
        contracts.py. This test pins the deletion so the unproducible-shape
        consumer cannot silently return."""
        assert not (SCRIPTS_DIR / "optimizer_bandit.py").exists(), (
            "#102 item 2: optimizer_bandit was deleted by #95 A7 — do not "
            "resurrect it (its pinned row shape was unproducible)")
