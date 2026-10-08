# -*- coding: utf-8 -*-
"""tests/test_verification_debt_568.py — the verification-debt feature.

D = sum(dependency-count x age-weight) over all unverified-but-depended-on
claims, the scheduling gate that routes high debt to the verifier, the
BLOCKED-path repair pin, and the compose/statusline faces.

Sections:
  1. the debt module math (age saturation, dependency counting, status
     exclusions, fail-open reads, the slope prior)
  2. the compose face (strategy object carries debt; the seam section)
  3. the decision-table gate (event declared, probe order, the smoke
     PARTIAL shape rerouting, anchor-byte discipline)
  4. the statusline face (snapshot field + renderer chip)

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _p in (SCRIPTS,):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from rlvr import verification_debt as vdebt  # noqa: E402
from rlvr import compose  # noqa: E402
import convergence_check as cc  # noqa: E402

NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
OLD_TS = (NOW - timedelta(hours=72)).isoformat()
FRESH_TS = (NOW - timedelta(hours=1)).isoformat()


# ---------------------------------------------------------------- fixtures

def _ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    return ws


def _register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, sort_keys=False,
                       allow_unicode=True), encoding="utf-8")


def _deps(ws: Path, depends_on: dict, competitor_groups: dict | None = None
          ) -> None:
    (ws / "claim_deps.yaml").write_text(
        yaml.safe_dump({"depends_on": depends_on,
                        "competitor_groups": competitor_groups or {}},
                       sort_keys=False), encoding="utf-8")


def _claim(cid: str, status: str = "OPEN", history: list | None = None,
           **fields) -> dict:
    c = {"id": cid, "status": status}
    if history is not None:
        c["history"] = history
    c.update(fields)
    return c


def _old_history() -> list[str]:
    return [f"worker dispatched and returned partial {OLD_TS}"]


def _spec(ws: Path) -> None:
    (ws / "task_spec.yaml").write_text(
        "primary_questions: []\n"
        "goal_verbatim: retrieve the family config\n"
        "success_criterion: family named with evidence\n"
        "verification_method: static\n", encoding="utf-8")


# ===========================================================================
# 1. the debt module math
# ===========================================================================

class TestDebtMath:
    def test_empty_workspace_reads_zero(self, tmp_path, monkeypatch):
        warns: list[tuple] = []
        monkeypatch.setattr(
            vdebt, "warn",
            lambda tag, msg, *a, **k: warns.append((tag, msg)))
        face = vdebt.debt(_ws(tmp_path), now=NOW)
        assert face["D"] == 0.0
        assert face["per_claim"] == {}
        assert face["slope"] is None
        assert face["top"] is None
        assert face["verifiable_open"] == []
        # absence is the idle face, never a degradation: a bare workspace
        # (no register at all) reads zero SILENTLY
        assert warns == []

    def test_dependency_count_is_direct_dependents(self, tmp_path):
        ws = _ws(tmp_path)
        _register(ws, [_claim("C-1", "PARTIALLY-VERIFIED", _old_history()),
                       _claim("C-2", "OPEN", _old_history()),
                       _claim("C-3", "OPEN", _old_history())])
        _deps(ws, {"C-2": ["C-1"], "C-3": ["C-1"]})
        face = vdebt.debt(ws, now=NOW)
        row = face["per_claim"]["C-1"]
        assert row["dependents"] == ["C-2", "C-3"]
        assert row["contribution"] == pytest.approx(2 * 2.0)
        assert face["D"] == pytest.approx(4.0)
        assert face["top"] == "C-1"
        assert face["verifiable_open"] == ["C-1"]

    def test_age_weight_saturates(self, tmp_path):
        ws = _ws(tmp_path)
        _register(ws, [_claim("C-1", "PARTIALLY-VERIFIED", _old_history()),
                       _claim("C-2", "OPEN")])
        _deps(ws, {"C-2": ["C-1"]})
        face = vdebt.debt(ws, now=NOW)
        # 72h >> the saturation window: capped weight
        assert face["per_claim"]["C-1"]["weight"] == vdebt.AGE_WEIGHT_CAP
        assert face["per_claim"]["C-1"]["age_hours"] == pytest.approx(72.0)

        ws2 = _ws(tmp_path, "fresh")
        _register(ws2, [_claim("C-1", "PARTIALLY-VERIFIED",
                               [f"dispatched {FRESH_TS}"]),
                        _claim("C-2", "OPEN")])
        _deps(ws2, {"C-2": ["C-1"]})
        face2 = vdebt.debt(ws2, now=NOW)
        # 1h / 24h, at the face's 4-dp rounding
        assert face2["per_claim"]["C-1"]["weight"] == pytest.approx(0.0417)
        assert face2["D"] == pytest.approx(0.0417)

    def test_terminal_park_and_stamp_contribute_zero(self, tmp_path):
        ws = _ws(tmp_path)
        _register(ws, [
            _claim("C-1", "PROVEN", _old_history()),
            _claim("C-2", "PARK", _old_history()),
            _claim("C-3", "STAMP", _old_history()),
            _claim("C-9", "OPEN", _old_history()),
        ])
        _deps(ws, {"C-9": ["C-1", "C-2", "C-3"]})
        face = vdebt.debt(ws, now=NOW)
        assert face["D"] == 0.0
        assert face["per_claim"] == {}

    def test_unverified_without_dependents_is_not_debt(self, tmp_path):
        ws = _ws(tmp_path)
        _register(ws, [_claim("C-1", "PARTIALLY-VERIFIED", _old_history())])
        _deps(ws, {})
        face = vdebt.debt(ws, now=NOW)
        assert face["D"] == 0.0
        assert "C-1" not in face["per_claim"]

    def test_broken_register_reads_zero(self, tmp_path, monkeypatch):
        ws = _ws(tmp_path)
        (ws / "claim-register.yaml").write_text(
            "claims: [ {id: C-1, status: OPEN, history: [broken\n  - x",
            encoding="utf-8")
        warns: list[tuple] = []
        monkeypatch.setattr(
            vdebt, "warn",
            lambda tag, msg, *a, **k: warns.append((tag, msg)))
        face = vdebt.debt(ws, now=NOW)
        assert face["D"] == 0.0
        assert face["per_claim"] == {}
        assert warns, "a broken registry read must warn, never go silent"

    def test_broken_deps_reads_zero(self, tmp_path, monkeypatch):
        ws = _ws(tmp_path)
        _register(ws, [_claim("C-1", "PARTIALLY-VERIFIED", _old_history())])
        (ws / "claim_deps.yaml").write_text(
            "depends_on: [C-1\n  - not: [a: map", encoding="utf-8")
        warns: list[tuple] = []
        monkeypatch.setattr(
            vdebt, "warn",
            lambda tag, msg, *a, **k: warns.append((tag, msg)))
        face = vdebt.debt(ws, now=NOW)
        assert face["D"] == 0.0
        assert warns

    def test_register_only_dep_field_fallback(self, tmp_path):
        """A fresh workspace may carry the per-claim depends_on fields
        before the DAG file has edges (the priority-ranking fallback
        precedent) — those edges count too."""
        ws = _ws(tmp_path)
        _register(ws, [_claim("C-1", "PARTIALLY-VERIFIED", _old_history()),
                       _claim("C-2", "OPEN", _old_history(),
                              depends_on=["C-1"])])
        _deps(ws, {})
        face = vdebt.debt(ws, now=NOW)
        assert face["per_claim"]["C-1"]["dependents"] == ["C-2"]
        assert face["D"] == pytest.approx(2.0)

    def test_unknown_age_reads_cap_not_zero(self, tmp_path):
        """A claim with no readable transition timestamp never proves
        freshness: the saturating weight applies (under-counting debt is
        the exact diagnosed failure; over-counting only reorders work
        toward verification)."""
        ws = _ws(tmp_path)
        _register(ws, [_claim("C-1", "PARTIALLY-VERIFIED"),
                       _claim("C-2", "OPEN")])
        _deps(ws, {"C-2": ["C-1"]})
        face = vdebt.debt(ws, now=NOW)
        assert face["per_claim"]["C-1"]["age_hours"] is None
        assert face["per_claim"]["C-1"]["weight"] == vdebt.AGE_WEIGHT_CAP
        assert face["D"] == pytest.approx(2.0)

    def test_direct_dependents_only_no_transitive_closure(self, tmp_path):
        ws = _ws(tmp_path)
        _register(ws, [_claim("C-1", "PARTIALLY-VERIFIED", _old_history()),
                       _claim("C-2", "OPEN", _old_history()),
                       _claim("C-3", "OPEN", _old_history())])
        _deps(ws, {"C-2": ["C-1"], "C-3": ["C-2"]})
        face = vdebt.debt(ws, now=NOW)
        assert face["per_claim"]["C-1"]["dependents"] == ["C-2"]
        assert face["per_claim"]["C-2"]["dependents"] == ["C-3"]
        assert face["D"] == pytest.approx(4.0)

    def test_slope_from_prior_statusline_snapshot(self, tmp_path):
        ws = _ws(tmp_path)
        _register(ws, [_claim("C-1", "PARTIALLY-VERIFIED", _old_history()),
                       _claim("C-2", "OPEN")])
        _deps(ws, {"C-2": ["C-1"]})
        prior = ws / "runs" / ".kunglao-statusline.json"
        prior.write_text(json.dumps({"vd": {"D": 6.0}}), encoding="utf-8")
        face = vdebt.debt(ws, now=NOW)
        # current D = 2.0 against a stored prior of 6.0: debt paid down
        assert face["slope"] == pytest.approx(-4.0)

        (prior.parent / "none").mkdir()
        ws2 = _ws(tmp_path, "noprior")
        _register(ws2, [_claim("C-1", "PARTIALLY-VERIFIED", _old_history()),
                        _claim("C-2", "OPEN")])
        _deps(ws2, {"C-2": ["C-1"]})
        assert vdebt.debt(ws2, now=NOW)["slope"] is None

    def test_gate_constant_is_policy_visible(self):
        assert vdebt.DEBT_GATE == 8.0

    def test_gate_boundary_is_strict(self, tmp_path):
        """D exactly at the gate does not fire (strict >)."""
        ws = _ws(tmp_path)
        # one dependent x capped weight 2.0 x 4 hub claims = 8.0 exactly
        _register(ws, [_claim(f"C-{i}", "PARTIALLY-VERIFIED", _old_history())
                       for i in range(1, 5)] + [_claim("C-9", "OPEN")])
        _deps(ws, {"C-9": ["C-1", "C-2", "C-3", "C-4"]})
        face = vdebt.debt(ws, now=NOW)
        assert face["D"] == pytest.approx(vdebt.DEBT_GATE)
        assert not face["D"] > vdebt.DEBT_GATE


# ===========================================================================
# 2. the compose face
# ===========================================================================

class _Store:
    def method_lead(self, state_fingerprint):
        return None

    def decayed_weight(self, row_id):
        return 1.0

    def cell_count(self, state_fingerprint):
        return 0


class TestComposeFace:
    def _debt_ws(self, tmp_path: Path) -> Path:
        ws = _ws(tmp_path)
        _register(ws, [_claim("C-1", "PARTIALLY-VERIFIED", _old_history()),
                       _claim("C-2", "OPEN"),
                       _claim("C-3", "OPEN")])
        _deps(ws, {"C-2": ["C-1"], "C-3": ["C-1"]})
        return ws

    def test_strategy_object_carries_debt_and_validates(self, tmp_path):
        ws = self._debt_ws(tmp_path)
        obj = compose.compose(ws, tick=1, store=_Store())
        assert compose.validate_strategy(obj) == []
        assert obj["debt"]["D"] == pytest.approx(4.0)  # 2 x cap weight
        assert obj["debt"]["top"] == "C-1"
        assert obj["debt"]["slope"] is None

    def test_seam_renders_debt_section_when_positive(self, tmp_path):
        ws = self._debt_ws(tmp_path)
        obj = compose.compose(ws, tick=1, store=_Store())
        sections = compose._seam_sections(ws, obj)
        debt_sections = [s for s in sections
                         if s["title"] == "verification-debt"]
        assert debt_sections, "positive debt must render in the seam"
        assert "C-1" in debt_sections[0]["body"]

    def test_zero_debt_renders_no_section(self, tmp_path):
        ws = _ws(tmp_path)
        _register(ws, [_claim("C-1", "PROVEN")])
        obj = compose.compose(ws, tick=1, store=_Store())
        assert obj["debt"]["D"] == 0.0
        assert all(s["title"] != "verification-debt"
                   for s in compose._seam_sections(ws, obj))

    def test_debt_reader_failure_fails_open(self, tmp_path, monkeypatch):
        ws = self._debt_ws(tmp_path)

        def _boom(_ws, *a, **k):
            raise OSError("boom")

        monkeypatch.setattr(vdebt, "debt", _boom)
        warned: list[str] = []
        monkeypatch.setattr(compose, "warn",
                            lambda tag, msg, *a, **k: warned.append(tag))
        obj = compose.compose(ws, tick=1, store=_Store())
        assert compose.validate_strategy(obj) == []
        assert obj["debt"]["D"] == 0.0
        assert warned, "compose debt degrade must be loud"


# ===========================================================================
# 3. the decision-table gate
# ===========================================================================

def _smoke_ws(base: Path, name: str = "smoke") -> Path:
    """The diagnosed shape: five claims stuck PARTIALLY-VERIFIED, all
    blocked, real dependency edges onto the hub, no partial fact rows,
    no workers — the loop used to read BLOCKED here with zero verifier
    acts."""
    ws = _ws(base, name)
    _spec(ws)
    claims = [_claim(f"C-{i}", "PARTIALLY-VERIFIED", _old_history(),
                     blocked=True)
              for i in range(1, 6)]
    claims.append(_claim("C-6", "OPEN", _old_history(), blocked=True))
    _register(ws, claims)
    _deps(ws, {f"C-{i}": ["C-1"] for i in range(2, 7)})
    (ws / "blockers").mkdir()
    (ws / "blockers" / "BLK-1.md").write_text("reason: env down\n",
                                              encoding="utf-8")
    return ws


class TestDecisionGate:
    def test_event_and_transition_declared(self):
        assert "DEBT_GATE" in cc.Event.__members__
        transition = cc.TRANSITIONS.get(
            (cc.State.SCHEDULE, cc.Event.DEBT_GATE))
        assert transition is not None
        state, builder = transition
        assert state is cc.State.DISPATCH_VERIFIER
        assert callable(builder)

    def test_debt_event_precedes_every_blocked_event_in_schedule(self):
        """The repair pin, structural form: in the SCHEDULE probe order
        the debt event fires before every event whose transition lands
        BLOCKED, so verifiable debt can never be read as blocked."""
        probes = cc.STAGE_PROBES[cc.State.SCHEDULE]
        debt_idx = probes.index(cc.Event.DEBT_GATE)
        blocked_events = [
            event for event in probes
            if cc.TRANSITIONS.get((cc.State.SCHEDULE, event), (None,))[0]
            is cc.State.BLOCKED]
        assert blocked_events, "sanity: the schedule tail blocks today"
        for event in blocked_events:
            assert debt_idx < probes.index(event), (
                f"{event} must not mask the debt gate")

    def test_smoke_shape_routes_verifier_not_blocked(self, tmp_path):
        ws = _smoke_ws(tmp_path)
        face = vdebt.debt(ws, now=datetime.now(timezone.utc))
        assert face["D"] > vdebt.DEBT_GATE
        decision = cc.decide(ws, emit_snapshot=False)
        assert decision["decision"] == "DISPATCH_VERIFIER"
        assert decision["action"], "the action must exist"
        assert decision["verification_debt"]["top"] == "C-1"
        assert "C-1" in decision["action"]

    def test_below_gate_keeps_the_old_table(self, tmp_path):
        ws = _ws(tmp_path)
        _spec(ws)
        _register(ws, [_claim("C-1", "PARTIALLY-VERIFIED", _old_history(),
                              blocked=True),
                       _claim("C-2", "OPEN", _old_history(),
                              blocked=True)])
        _deps(ws, {"C-2": ["C-1"]})
        decision = cc.decide(ws, emit_snapshot=False)
        # D = 2.0 < gate: the all-blocked tail keeps its verdict
        assert decision["decision"] == "BLOCKED"

    def test_zero_debt_decision_dict_stays_anchor_shaped(self, tmp_path):
        ws = _ws(tmp_path)
        _spec(ws)
        _register(ws, [_claim("C-1", "OPEN")])
        decision = cc.decide(ws, emit_snapshot=False)
        assert "verification_debt" not in decision

    def test_debt_reader_failure_fails_open_to_zero(self, tmp_path,
                                                    monkeypatch):
        ws = _smoke_ws(tmp_path)

        def _boom(_ws, *a, **k):
            raise OSError("boom")  # the degrade net's exception family

        monkeypatch.setattr(vdebt, "debt", _boom)
        decision = cc.decide(ws, emit_snapshot=False)
        # old behavior restored: the all-blocked tail reads BLOCKED
        assert decision["decision"] == "BLOCKED"

    def test_verifiable_debt_claims_never_reach_drain(self, tmp_path):
        """Any claim that can contribute debt is non-terminal and not
        in-flight, so it sits in opens and the machine routes to
        SCHEDULE — the DRAIN completion stage is unreachable with
        verifiable debt on the books."""
        ws = _smoke_ws(tmp_path)
        inputs = cc._decide_inputs(ws)
        assert inputs.opens, "debt-bearing claims must be open work"
        assert cc._work_pending(inputs)
        state, _ = cc._run_machine(inputs)
        assert state is not cc.State.CONVERGED
        assert state is not cc.State.DRAIN


# ===========================================================================
# 4. the statusline face
# ===========================================================================

class TestStatuslineFace:
    def test_snapshot_carries_vd_face(self, tmp_path):
        import statusline_snapshot as sls
        ws = _smoke_ws(tmp_path)
        snap = sls.build_snapshot(ws)
        vd = snap.get("vd")
        assert isinstance(vd, dict)
        assert vd["D"] > vdebt.DEBT_GATE
        assert vd["hot"] is True
        assert vd["top"] == "C-1"

    def test_snapshot_vd_cold_when_no_debt(self, tmp_path):
        import statusline_snapshot as sls
        ws = _ws(tmp_path)
        _register(ws, [_claim("C-1", "PROVEN")])
        snap = sls.build_snapshot(ws)
        vd = snap.get("vd")
        assert isinstance(vd, dict)
        assert vd["D"] == 0.0
        assert vd["hot"] is False


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
RENDERER = SCRIPTS / "statusline_render.mjs"


def _run_renderer(ws: Path) -> subprocess.CompletedProcess:
    payload = json.dumps(
        {"workspace": {"current_dir": str(ws)},
         "model": {"display_name": "t"}})
    env = dict(os.environ)
    env["KUNGLAO_STATUSLINE_HUD"] = ""
    env["KUNGLAO_STATUSLINE_NOW_MS"] = "0"
    return subprocess.run(
        ["node", str(RENDERER)], input=payload, capture_output=True,
        text=True, timeout=30, cwd=str(ws.parent), env=env)


def _base_snap() -> dict:
    ts = "2026-10-08T00:00:00Z"
    return {"schema": 2, "ts": ts, "tick": 1, "state": "analyzing",
            "state_since": ts, "color": {"hue": 140, "sat": 72, "light": 55},
            "probe_codes": [], "probe_detail": [], "degraded": {},
            "pq": {"answered": 0, "total": 2, "coverage": 0.0,
                   "v_m": 0.0, "v_norm": 0.42},
            "v_norm": 0.42, "v_hist": [],
            "flash": {"seq": 0, "ts": None, "reason": None, "text": None}}


@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
class TestRendererChip:
    def _out(self, tmp_path: Path, vd: dict | None) -> str:
        ws = _ws(tmp_path, f"r{abs(hash(json.dumps(vd, sort_keys=True))) % 9999}")
        snap = _base_snap()
        if vd is not None:
            snap["vd"] = vd
        (ws / "runs" / ".kunglao-statusline.json").write_text(
            json.dumps(snap), encoding="utf-8")
        r = _run_renderer(ws)
        assert r.returncode == 0, r.stderr
        return ANSI_RE.sub("", r.stdout)

    def test_positive_debt_renders_chip(self, tmp_path):
        out = self._out(tmp_path, {"D": 12.5, "slope": 2.0, "top": "C-1",
                                   "hot": True})
        assert "vd:D=12.5" in out

    def test_zero_debt_hides_chip(self, tmp_path):
        out = self._out(tmp_path, {"D": 0.0, "slope": None, "top": None,
                                   "hot": False})
        assert "vd:" not in out

    def test_absent_vd_field_is_tolerated(self, tmp_path):
        out = self._out(tmp_path, None)
        assert "vd:" not in out
        assert "analyzing" in out  # the rest of the line still renders
