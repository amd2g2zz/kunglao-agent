# -*- coding: utf-8 -*-
"""tests/test_guardian_kpi_429.py — the three guardian-KPI surfaces into the
Q report (issue #429 W3-T3.1, v0.1.6 measurement face).

Pins the W3 plan clauses:
  - T3.1 guardian trigger-rate trends: retry/stall/SATURATED rates from the
    ledger/worker event surfaces, per-task trend, rendered beside #432's
    method_family_health block — 「守护者触发率=RL策略失败率的无偏指标」;
  - T3.1 verifier-drift readout: settlement amendments on LLM-discretionary
    vs mechanical settlement rows — a PURE ledger query (zero new
    mechanisms); a significantly higher discretionary amendment rate =
    verifier-leg drift alarm;
  - T3.1 reject-rate trend (output compliance) from the existing
    gate-telemetry face (runs/gate-telemetry.jsonl).

All three faces are PURE READS + RENDER: they never write, never gate,
and land in q_report as ADDITIVE keys — the q-report/1 cells arithmetic
and the method_family_health block stay byte-identical (the #432 additive
precedent). Degradation is an explicit "unavailable" marker, never a
silent empty block.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import experience_triples as xt  # noqa: E402
import guardian_kpi as gk  # noqa: E402
import rollout_ledger as rl  # noqa: E402
import scalar_settlement as ss  # noqa: E402

TS = "2026-09-27T00:00:00Z"
TS_LATE = "2026-09-28T00:00:00Z"


def _emit(ws: Path, action: str, *, actor="orchestrator", claim=None,
          exit=None, detail=None, ts=TS) -> None:
    """One unified-log event row (kunglao_log.emit's row shape)."""
    logs = ws / "runs" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": ts, "actor": actor, "action": action,
        "claim": claim, "tool": None, "artifact": None,
        "duration_ms": None, "exit": exit, "detail": detail,
        "arm": None, "epoch": 0, "hypothesis_ref": None,
        "matched_rule": None, "trace_id": None, "version": "test",
        "channel": "local", "null_reasons": {},
    }
    with (logs / "kunglao-test.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _converge(ws: Path, word: str, rc: int, *, ts=TS) -> None:
    _emit(ws, "converge", detail=f"{word} open=1 partial=0 slots=3 workers=0",
          exit=rc, ts=ts)


def _register_claim(ws: Path, cid: str, status: str,
                    promotion_attempts: int = 0) -> None:
    reg = ws / "claim-register.yaml"
    rows = []
    if reg.is_file():
        for line in reg.read_text(encoding="utf-8").splitlines():
            if line.startswith("claims:"):
                continue
            rows.append(line)
    body = "\n".join(rows).strip()
    reg.write_text(
        "claims:\n" + body + ("\n" if body else "") +
        f"- id: {cid}\n  status: {status}\n"
        f"  promotion_attempts: {promotion_attempts}\n",
        encoding="utf-8")


def _settled_task(ws: Path, anchor: str, *, oracle: bool = True,
                  reward=1.0, settle_twice=False, kind="task") -> str:
    """A settled ledger rollout; oracle=True stamps the mechanical verdict."""
    signals = [{"type": "strategy_arm", "source": "eval", "value": "arm-a",
                "ts": TS}]
    if oracle:
        signals.append({"type": "oracle_verdict", "source": "checker",
                        "value": "pass", "ts": TS})
    rl.record(ws, kind=kind, anchor=anchor, signals=signals)
    st = {"reward": reward, "band": "SETTLED_GREEN", "rule_id": "r/1",
          "evidence_refs": []}
    rl.settle(ws, f"{kind}/{anchor}", st)
    if settle_twice:
        rl.settle(ws, f"{kind}/{anchor}", dict(st, reward=reward + 1.0))
    return f"{kind}/{anchor}"


# ---------------------------------------------------------------------------
# 1. guardian trigger-rate trends
# ---------------------------------------------------------------------------

class TestGuardianTriggers:
    def test_schema_and_rationale(self, tmp_path):
        doc = gk.guardian_triggers(tmp_path)
        assert doc["schema"] == "guardian-kpi/1"
        assert doc["rationale"] == "守护者触发率=RL策略失败率的无偏指标"

    def test_saturated_rate_from_converge_rows(self, tmp_path):
        _converge(tmp_path, "DISPATCH", 1)
        _converge(tmp_path, "SATURATED", 3)
        _converge(tmp_path, "BLOCKED", 4)
        doc = gk.guardian_triggers(tmp_path)
        assert doc["converge_rows"] == 3
        assert doc["decisions"]["SATURATED"] == 1
        assert doc["decisions"]["DISPATCH"] == 1
        assert doc["decisions"]["BLOCKED"] == 1
        assert doc["saturated_rate"] == pytest.approx(1 / 3)

    def test_decision_word_wins_over_rc(self, tmp_path):
        """The detail's leading word is the decision; rc is the fallback
        for rows without a parseable word (contracts EXIT_* bytes)."""
        _emit(tmp_path, "converge", detail="", exit=3)
        doc = gk.guardian_triggers(tmp_path)
        assert doc["decisions"]["SATURATED"] == 1

    def test_stall_fires_from_detector_and_action_rows(self, tmp_path):
        _emit(tmp_path, "detector_fired", actor="mission_stall",
              detail=json.dumps({"detector": "mission_stall", "stalled": True}))
        _emit(tmp_path, "plan_stall", actor="ask_gate", claim="C-1")
        _emit(tmp_path, "lifecycle_stalled", actor="s2")
        doc = gk.guardian_triggers(tmp_path)
        assert doc["stall"]["fires"] == 3

    def test_stall_detector_evals_are_not_fires(self, tmp_path):
        _emit(tmp_path, "detector_eval", actor="mission_stall",
              detail=json.dumps({"detector": "mission_stall"}))
        doc = gk.guardian_triggers(tmp_path)
        assert doc["stall"]["fires"] == 0

    def test_retry_from_redo_rows_and_register(self, tmp_path):
        _emit(tmp_path, "redo_leak_warn", actor="dispatch_gate",
              claim="C-9", detail="value-overlap")
        _register_claim(tmp_path, "C-1", "OPEN", promotion_attempts=2)
        _register_claim(tmp_path, "C-2", "OPEN", promotion_attempts=0)
        _register_claim(tmp_path, "C-3", "PROVEN", promotion_attempts=1)
        doc = gk.guardian_triggers(tmp_path)
        assert doc["retry"]["redo_leak_rows"] == 1
        assert doc["retry"]["claims_retried"] == 1   # C-1 live + retried
        assert doc["retry"]["claims_live"] == 2      # C-1, C-2 (C-3 terminal)

    def test_per_task_trend_groups_by_claim(self, tmp_path):
        _emit(tmp_path, "redo_leak_warn", actor="dispatch_gate", claim="C-1")
        _emit(tmp_path, "redo_leak_warn", actor="dispatch_gate", claim="C-1")
        _emit(tmp_path, "plan_stall", actor="ask_gate", claim="C-2")
        doc = gk.guardian_triggers(tmp_path)
        tasks = {t["claim"]: t for t in doc["per_task"]}
        assert tasks["C-1"]["retry"] == 2
        assert tasks["C-1"]["total"] == 2
        assert tasks["C-2"]["stall"] == 1

    def test_day_trend_buckets(self, tmp_path):
        _converge(tmp_path, "SATURATED", 3, ts="2026-09-27T10:00:00Z")
        _converge(tmp_path, "SATURATED", 3, ts="2026-09-27T11:00:00Z")
        _converge(tmp_path, "DISPATCH", 1, ts="2026-09-28T10:00:00Z")
        doc = gk.guardian_triggers(tmp_path)
        days = {d["day"]: d for d in doc["trend"]}
        assert days["2026-09-27"]["saturated"] == 2
        assert days["2026-09-27"]["converge"] == 2
        assert days["2026-09-28"]["saturated"] == 0

    def test_cold_start_unavailable_marker(self, tmp_path):
        """No event-log face at all -> explicit unavailability, never a
        silent zero block (#432 visible-not-silent precedent)."""
        doc = gk.guardian_triggers(tmp_path)
        assert "unavailable" in doc

    def test_read_only_never_writes(self, tmp_path):
        _converge(tmp_path, "SATURATED", 3)
        before = sorted(str(p.relative_to(tmp_path))
                        for p in tmp_path.rglob("*") if p.is_file())
        gk.guardian_triggers(tmp_path)
        after = sorted(str(p.relative_to(tmp_path))
                       for p in tmp_path.rglob("*") if p.is_file())
        assert before == after


# ---------------------------------------------------------------------------
# 2. verifier-drift readout (amendment ratio, pure ledger query)
# ---------------------------------------------------------------------------

class TestVerifierDrift:
    def test_schema_and_basis(self, tmp_path):
        doc = gk.verifier_drift(tmp_path)
        assert doc["schema"] == "verifier-drift/1"
        assert "oracle_verdict" in doc["basis"]  # declared classification

    def test_mechanical_vs_discretionary_classification(self, tmp_path):
        _settled_task(tmp_path, "T-M", oracle=True)      # mechanical
        _settled_task(tmp_path, "T-D", oracle=False)     # discretionary
        doc = gk.verifier_drift(tmp_path)
        assert doc["rollouts"]["mechanical"] == 1
        assert doc["rollouts"]["discretionary"] == 1

    def test_self_distill_is_discretionary(self, tmp_path):
        rl.register_kind("self_distill", "test")  # open enum, registered
        _settled_task(tmp_path, "L-1", oracle=False, kind="self_distill")
        doc = gk.verifier_drift(tmp_path)
        assert doc["rollouts"]["discretionary"] == 1
        assert doc["rollouts"]["mechanical"] == 0

    def test_settlement_amendment_counts_revision_not_identity(self, tmp_path):
        """One settled row with no revision: zero amendments. A second
        settle() with a CHANGED settlement = exactly one amendment."""
        _settled_task(tmp_path, "T-M", oracle=True, settle_twice=False)
        doc = gk.verifier_drift(tmp_path)
        assert doc["settlement_amendments"]["mechanical"] == 0
        _settled_task(tmp_path, "T-M2", oracle=True, settle_twice=True)
        doc = gk.verifier_drift(tmp_path)
        assert doc["settlement_amendments"]["mechanical"] == 1

    def test_amendment_rates_are_per_class_quotients(self, tmp_path):
        # mechanical: 2 rollouts, 0 revisions
        _settled_task(tmp_path, "T-M1", oracle=True)
        _settled_task(tmp_path, "T-M2", oracle=True)
        # discretionary: 2 rollouts, 1 revision
        _settled_task(tmp_path, "T-D1", oracle=False)
        _settled_task(tmp_path, "T-D2", oracle=False, settle_twice=True)
        doc = gk.verifier_drift(tmp_path)
        assert doc["rollouts"]["mechanical"] == 2
        assert doc["rollouts"]["discretionary"] == 2
        assert doc["amendment_rate"]["mechanical"] == 0.0
        assert doc["amendment_rate"]["discretionary"] == pytest.approx(0.5)

    def test_drift_ratio_is_rate_quotient(self, tmp_path):
        # mechanical: 1 rollout revised once -> rate 1.0
        _settled_task(tmp_path, "T-M1", oracle=True, settle_twice=True)
        # discretionary: 2 rollouts, 1 revision -> rate 0.5
        _settled_task(tmp_path, "T-D1", oracle=False)
        _settled_task(tmp_path, "T-D2", oracle=False, settle_twice=True)
        doc = gk.verifier_drift(tmp_path)
        assert doc["amendment_rate"]["mechanical"] == pytest.approx(1.0)
        assert doc["amendment_rate"]["discretionary"] == pytest.approx(0.5)
        assert doc["drift_ratio"] == pytest.approx(0.5)

    def test_drift_ratio_none_when_mechanical_rate_zero(self, tmp_path):
        """The quotient is undefined at mechanical rate 0 — None, with the
        raw rates left visible for the reader (honest absence)."""
        _settled_task(tmp_path, "T-M1", oracle=True)
        _settled_task(tmp_path, "T-D1", oracle=False, settle_twice=True)
        doc = gk.verifier_drift(tmp_path)
        assert doc["drift_ratio"] is None
        assert doc["amendment_rate"]["mechanical"] == 0.0
        assert doc["amendment_rate"]["discretionary"] == pytest.approx(1.0)

    def test_drift_ratio_none_when_no_mechanical_base(self, tmp_path):
        _settled_task(tmp_path, "T-D1", oracle=False, settle_twice=True)
        doc = gk.verifier_drift(tmp_path)
        assert doc["drift_ratio"] is None

    def test_drift_alarm_fires_on_high_discretionary_rate(self, tmp_path):
        """2 clean mechanical rows vs 2 revised discretionary rows: the
        discretionary amendment rate exceeds DRIFT_ALARM_FACTOR x the
        mechanical rate on a sufficient row base -> alarm."""
        _settled_task(tmp_path, "T-M1", oracle=True)
        _settled_task(tmp_path, "T-M2", oracle=True)
        _settled_task(tmp_path, "T-D1", oracle=False, settle_twice=True)
        _settled_task(tmp_path, "T-D2", oracle=False, settle_twice=True)
        doc = gk.verifier_drift(tmp_path)
        assert doc["drift_alarm"] is True

    def test_no_alarm_when_rates_comparable(self, tmp_path):
        """Symmetric revision pressure on both classes = healthy verifier
        legs — no alarm even with revisions present."""
        _settled_task(tmp_path, "T-M1", oracle=True, settle_twice=True)
        _settled_task(tmp_path, "T-M2", oracle=True)
        _settled_task(tmp_path, "T-D1", oracle=False, settle_twice=True)
        _settled_task(tmp_path, "T-D2", oracle=False)
        doc = gk.verifier_drift(tmp_path)
        assert doc["drift_alarm"] is False

    def test_no_alarm_below_min_rows(self, tmp_path):
        """The alarm needs a row base (MIN_ROWS_FOR_ALARM per class) —
        1 revised discretionary row vs 1 clean mechanical row is noise."""
        _settled_task(tmp_path, "T-M1", oracle=True)
        _settled_task(tmp_path, "T-D1", oracle=False, settle_twice=True)
        doc = gk.verifier_drift(tmp_path)
        assert doc["drift_alarm"] is False

    def test_unclassified_rows_visible(self, tmp_path):
        rl.register_kind("mystery_kind", "test")
        _settled_task(tmp_path, "X-1", oracle=True, kind="mystery_kind")
        doc = gk.verifier_drift(tmp_path)
        assert doc["rollouts"]["unclassified"] == 1

    def test_round_credit_is_mechanical(self, tmp_path):
        signals = [{"type": "round_credit_signal",
                    "source": "scalar_settlement",
                    "value": {"credited": 1, "waste": 0}, "ts": TS}]
        rl.record(tmp_path, kind=ss.KIND_ROUND_CREDIT, anchor="C-1",
                  signals=signals, ts=TS)
        rl.settle(tmp_path, f"{ss.KIND_ROUND_CREDIT}/C-1",
                  {"reward": 1.0, "band": ss.BAND_ROUND_CREDIT,
                   "rule_id": ss.RULE_ROUND_CREDIT, "evidence_refs": [],
                   "credited": ["F001"], "waste": 0.0, "round": 1,
                   "untraced": [], "settled_ts": TS})
        doc = gk.verifier_drift(tmp_path)
        assert doc["rollouts"]["mechanical"] == 1
        assert doc["rollouts"]["discretionary"] == 0

    def test_read_only_never_writes(self, tmp_path):
        _settled_task(tmp_path, "T-M", oracle=True)
        before = (tmp_path / "runs" / "rollout-ledger.jsonl").read_bytes()
        gk.verifier_drift(tmp_path)
        after = (tmp_path / "runs" / "rollout-ledger.jsonl").read_bytes()
        assert before == after

    def test_cold_start_empty_counts(self, tmp_path):
        doc = gk.verifier_drift(tmp_path)
        assert doc["rollouts"] == {"mechanical": 0, "discretionary": 0,
                                   "unclassified": 0}
        assert doc["drift_ratio"] is None


# ---------------------------------------------------------------------------
# 3. reject-rate trend (gate telemetry, output compliance)
# ---------------------------------------------------------------------------

class TestRejectRate:
    def _tel(self, ws: Path, gate: str, rc, ts=TS) -> None:
        runs = ws / "runs"
        runs.mkdir(parents=True, exist_ok=True)
        meaning = {0: "pass", 1: "reject", 2: "hard_block"}.get(rc, "rc=?")
        row = {"ts": ts, "gate": gate, "rc": rc, "rc_meaning": meaning}
        with (runs / "gate-telemetry.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")

    def test_schema(self, tmp_path):
        doc = gk.reject_rate(tmp_path)
        assert doc["schema"] == "gate-reject-kpi/1"

    def test_by_gate_counts_and_rate(self, tmp_path):
        self._tel(tmp_path, "reuse_gate", 0)
        self._tel(tmp_path, "reuse_gate", 1)
        self._tel(tmp_path, "dual_gate", 2)
        doc = gk.reject_rate(tmp_path)
        gates = {g["gate"]: g for g in doc["by_gate"]}
        assert gates["reuse_gate"]["calls"] == 2
        assert gates["reuse_gate"]["rejects"] == 1
        assert gates["reuse_gate"]["rate"] == pytest.approx(0.5)
        assert gates["dual_gate"]["hard_blocks"] == 1

    def test_overall_reject_rate_excludes_passes(self, tmp_path):
        self._tel(tmp_path, "a", 0)
        self._tel(tmp_path, "a", 1)
        self._tel(tmp_path, "b", 2)
        doc = gk.reject_rate(tmp_path)
        assert doc["rows"] == 3
        assert doc["rejects"] == 1
        assert doc["hard_blocks"] == 1
        assert doc["overall_reject_rate"] == pytest.approx(2 / 3)

    def test_exception_rows_counted(self, tmp_path):
        self._tel(tmp_path, "a", None)
        doc = gk.reject_rate(tmp_path)
        assert doc["exceptions"] == 1
        assert doc["rejects"] == 0

    def test_day_trend(self, tmp_path):
        self._tel(tmp_path, "a", 1, ts="2026-09-27T10:00:00Z")
        self._tel(tmp_path, "a", 0, ts="2026-09-27T11:00:00Z")
        self._tel(tmp_path, "a", 2, ts="2026-09-28T10:00:00Z")
        doc = gk.reject_rate(tmp_path)
        days = {d["day"]: d for d in doc["trend"]}
        assert days["2026-09-27"]["rejects"] == 1
        assert days["2026-09-28"]["hard_blocks"] == 1

    def test_cold_start_zero_rows(self, tmp_path):
        doc = gk.reject_rate(tmp_path)
        assert doc["rows"] == 0
        assert doc["by_gate"] == []
        assert doc["overall_reject_rate"] is None


# ---------------------------------------------------------------------------
# 4. Q report integration (additive keys, byte-identical existing face)
# ---------------------------------------------------------------------------

class TestQReportIntegration:
    def test_q_report_carries_all_three_kpi_keys(self, tmp_path):
        _converge(tmp_path, "SATURATED", 3)
        _settled_task(tmp_path, "T-M", oracle=True)
        self_tel = tmp_path / "runs" / "gate-telemetry.jsonl"
        self_tel.parent.mkdir(parents=True, exist_ok=True)
        self_tel.write_text(json.dumps(
            {"ts": TS, "gate": "g", "rc": 1, "rc_meaning": "reject"}) + "\n",
            encoding="utf-8")
        doc = xt.q_report(tmp_path)
        assert "guardian_kpi" in doc
        assert "verifier_drift" in doc
        assert "reject_rate" in doc
        assert doc["guardian_kpi"]["schema"] == "guardian-kpi/1"
        assert doc["verifier_drift"]["schema"] == "verifier-drift/1"
        assert doc["reject_rate"]["schema"] == "gate-reject-kpi/1"

    def test_existing_keys_unchanged_shape(self, tmp_path):
        """The #432 additive discipline: the Q arithmetic face keeps its
        exact key set and value types; the KPI faces are ADDITIVE keys."""
        _settled_task(tmp_path, "T-M", oracle=True)
        doc = xt.q_report(tmp_path)
        assert doc["schema"] == "q-report/1"
        assert isinstance(doc["cells"], list)
        assert isinstance(doc["rows"], int)
        assert "method_family_health" in doc
        assert set(doc) == {"schema", "cells", "rows",
                            "method_family_health", "guardian_kpi",
                            "verifier_drift", "reject_rate"}

    def test_q_report_cold_start_still_carries_kpis(self, tmp_path):
        doc = xt.q_report(tmp_path)
        assert set(doc) >= {"guardian_kpi", "verifier_drift", "reject_rate"}
        assert "unavailable" in doc["guardian_kpi"]

    def test_q_report_never_writes(self, tmp_path):
        _settled_task(tmp_path, "T-M", oracle=True)
        before = sorted(str(p.relative_to(tmp_path))
                        for p in tmp_path.rglob("*") if p.is_file())
        xt.q_report(tmp_path)
        after = sorted(str(p.relative_to(tmp_path))
                       for p in tmp_path.rglob("*") if p.is_file())
        assert before == after
