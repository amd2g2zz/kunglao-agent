# -*- coding: utf-8 -*-
"""Issue-249 fast unit face — STALLED routes to its own remedy.

The deadlock (issue verbatim): the STALLED flatline clears only on
claim-state change; settling requires dispatch; dispatch is blocked by the
rc=1 gate; minting was hand-edit folklore — so the gate deadlocked its own
"reformulate or decompose" advice.

This module pins the pieces (the full cycle lives in
test_stalled_remedy_full_cycle_249.py, slow tier):

  R1  the STALLED verdict JSON carries the invokable remedy reference
      (operator / claims / dispatch_marker / mint_cmd) — never prose-only
  R2  the STALLED action string carries the same literals (marker + mint
      command); the issue-2 pins ("never dispatched" / "dispatched but flat")
      survive
  G1  HEALTHY / NO_DATA / SPINNING output shapes are untouched (remedy is
      STALLED-only; SPINNING keeps its harder-stop semantics, out of scope)
  R3  stalled_state() — the single state source the exemption face
      consumes — mirrors the verdict and is None (fail-closed) off-STALLED
  R4  the lib predicate's two narrow channels (remedy-declared stuck
      claim / minted OPEN sub-claim) + its fail-closed edges
  R5  worker_budget_core's rc=1 face admits ONLY the prescribed remedy
      dispatch; SPINNING and crash faces are untouched; legacy 1-arg calls
      keep the exact prior block behavior; lib outage is fail-closed
  R6  the sinks pre_check chain forwards the dispatch context to the
      health gate (the wiring the exemption rides)

Fast tier: no subprocess anywhere — the health SUBPROCESS is stubbed at
the _run_py boundary (rc values), but the exemption's detector state is
the REAL scripts/convergence_health.stalled_state against a REAL ledger,
and the predicate is the REAL hooks/lib_kunglao function.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import convergence_health as ch  # noqa: E402
import worker_budget_core as wbc  # noqa: E402
import worker_budget_sinks as wbs  # noqa: E402
from _path_hygiene import load_hooks_lib  # noqa: E402

LIB = load_hooks_lib()
MARKER = LIB.STALLED_REMEDY_MARKER

BASE = datetime(2026, 9, 2, 12, 0, 0, tzinfo=timezone.utc)


def _snap(i: int, open_count: int, open_ids: list[str],
          dispatched_ids: list[str] | None = None) -> dict:
    """One ledger snapshot row (new format), 60s apart — never dedup'd."""
    return {
        "ts": (BASE + timedelta(seconds=60 * i)).isoformat(),
        "decision": "DISPATCH",
        "open_count": open_count,
        "open_ids": open_ids,
        "partial_count": 0,
        "active_workers": 1,
        "blockers": [],
        "facts_total": 5,
        "dispatched_ids": dispatched_ids if dispatched_ids is not None else [],
    }


def _stalled_ledger() -> list[dict]:
    """C-1 dispatched-flat for 5 rounds -> STALLED via flatline AND stuck."""
    return [_snap(i, 1, ["C-1"], ["C-1"]) for i in range(5)]


def _write_ledger(ws: Path, rows: list[dict]) -> None:
    (ws / ch.LEDGER_NAME).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8")


# =====================================================================
# R1/R2: the invokable remedy reference (detector face)
# =====================================================================

class TestStalledRemedyReference:
    def test_stalled_json_carries_remedy(self):
        r = ch.assess(_stalled_ledger())
        assert r["verdict"] == "STALLED"
        remedy = r.get("remedy")
        assert remedy, "issue acceptance: the verdict JSON carries the remedy"
        assert remedy["operator"] == "decompose"
        assert remedy["claims"] == ["C-1"]
        assert remedy["dispatch_marker"] == "remedy: decompose"
        assert "target_ladder.py" in remedy["mint_cmd"]
        assert "--mint" in remedy["mint_cmd"]

    def test_stalled_action_carries_marker_and_mint_cmd(self):
        r = ch.assess(_stalled_ledger())
        assert "`remedy: decompose`" in r["action"]
        assert "target_ladder.py" in r["action"]
        assert "minting breaks the flatline mechanically" in r["action"]

    def test_cross_face_marker_sync(self):
        """The exemption face consumes lib_kunglao's constant; the prose
        prints convergence_health's copy. A drift would print a remedy the
        gate does not admit (or admit one it never printed)."""
        assert MARKER == ch.STALLED_REMEDY_MARKER
        r = ch.assess(_stalled_ledger())
        assert MARKER in r["action"]
        assert MARKER == r["remedy"]["dispatch_marker"]

    def test_stalled_action_keeps_2_pins(self):
        """Guard: the issue-2 wording contract survives the appended remedy."""
        r = ch.assess([_snap(i, 2, ["C-1", "C-2"], ["C-2"])
                       for i in range(4)])
        assert r["verdict"] == "STALLED"
        assert "never dispatched" in r["action"]
        assert "dispatched but flat" in r["action"]

    def test_non_stalled_shapes_untouched(self):
        healthy = ch.assess([
            _snap(0, 3, ["C-1", "C-2", "C-3"], []),
            _snap(1, 2, ["C-1", "C-2"], []),
            _snap(2, 1, ["C-1"], []),
        ])
        assert healthy["verdict"] == "HEALTHY"
        assert "remedy" not in healthy
        no_data = ch.assess([])
        assert no_data["verdict"] == "NO_DATA"
        assert "remedy" not in no_data
        spinning = ch.assess([_snap(i, 2, ["C-1"], ["C-1"])
                              for i in range(8)])
        assert spinning["verdict"] == "SPINNING"
        assert "remedy" not in spinning, \
            "SPINNING harder-stop semantics are out of scope (issue-249)"


# =====================================================================
# R3: stalled_state — the exemption face's single state source
# =====================================================================

class TestStalledState:
    def test_stalled_ws_state(self, tmp_path):
        _write_ledger(tmp_path, _stalled_ledger())
        state = ch.stalled_state(tmp_path)
        assert state is not None
        assert state["verdict"] == "STALLED"
        assert state["stuck_ids"] == ["C-1"]
        assert state["flatlined_open_ids"] == ["C-1"]
        assert state["remedy"]["operator"] == "decompose"

    def test_healthy_ledger_is_none(self, tmp_path):
        _write_ledger(tmp_path, [
            _snap(0, 3, ["C-1", "C-2", "C-3"], []),
            _snap(1, 2, ["C-1", "C-2"], []),
            _snap(2, 1, ["C-1"], []),
        ])
        assert ch.stalled_state(tmp_path) is None

    def test_missing_ledger_is_none(self, tmp_path):
        assert ch.stalled_state(tmp_path) is None

    def test_remedy_depth_counts_admits_in_episode(self, tmp_path):
        _write_ledger(tmp_path, _ledger_with_admits(2))
        state = ch.stalled_state(tmp_path)
        assert state["remedy_depth"] == 2
        assert state["remedy_max_depth"] == ch.REMEDY_MAX_DEPTH

    def test_remedy_depth_resets_on_new_episode(self, tmp_path):
        """A snapshot without the claim restarts the episode — a mint
        reset cannot hide prior cycles, but a real trajectory change
        (claim left the frontier and returned) does."""
        _write_ledger(tmp_path, _ledger_with_admits(2, with_reset=True))
        state = ch.stalled_state(tmp_path)
        assert state["remedy_depth"] == 0

    def test_remedy_depth_ignores_other_claims(self, tmp_path):
        rows = list(_stalled_ledger())
        rows.append({"type": "operator_action",
                     "action": ch.REMEDY_ADMIT_ACTION,
                     "claim_id": "C-2", "ts": BASE.isoformat()})
        _write_ledger(tmp_path, rows)
        assert ch.stalled_state(tmp_path)["remedy_depth"] == 0


def _ledger_with_admits(n_admits: int, with_reset: bool = False) -> list:
    """Stalled ledger + N admit-telemetry rows for C-1 (the rc=1 face
    writes one such row per admitted remedy dispatch); with_reset appends
    a snapshot WITHOUT C-1 (episode restart) and re-stalls it."""
    rows: list = list(_stalled_ledger())
    for _ in range(n_admits):
        rows.append({"type": "operator_action",
                     "action": ch.REMEDY_ADMIT_ACTION,
                     "actor": "hook:worker_budget",
                     "claim_id": "C-1", "ts": BASE.isoformat(),
                     "reason": "telemetry"})
    if with_reset:
        # C-1 leaves the frontier (episode restart), returns, and re-stalls
        # (3+ trailing snapshots with dispatch evidence -> stuck again)
        rows.append(_snap(9, 2, ["C-9"], []))
        rows.extend(_snap(i, 1, ["C-1"], ["C-1"]) for i in (10, 11, 12))
    return rows


# =====================================================================
# R4: the lib predicate — two marker-gated channels, fail-closed edges
# =====================================================================

class TestRemedyPredicate:
    def test_channel_a_stuck_claim_with_marker(self, tmp_path):
        assert LIB.is_stalled_remedy_dispatch(
            tmp_path, "C-1", None, f"plan\n{MARKER}\n",
            stuck_ids=["C-1"], flatlined_open_ids=["C-1"]) is True

    def test_no_marker_never_passes(self, tmp_path):
        assert LIB.is_stalled_remedy_dispatch(
            tmp_path, "C-1", None, "ordinary dispatch",
            stuck_ids=["C-1"], flatlined_open_ids=["C-1"]) is False

    def test_marker_alone_not_enough(self, tmp_path):
        """Marked but the claim sits in the flatlined open set WITHOUT
        stuck evidence (queued frontier) -> neither channel opens."""
        assert LIB.is_stalled_remedy_dispatch(
            tmp_path, "C-Q", None, MARKER,
            stuck_ids=["C-1"], flatlined_open_ids=["C-1", "C-Q"]) is False

    def test_channel_b_minted_open_subclaim(self, tmp_path):
        """The real issue-234 shape: the sibling depends_on the stuck
        parent (mint provenance) and is register-OPEN."""
        (tmp_path / "claim-register.yaml").write_text(
            yaml.safe_dump({"claims": [
                {"id": "C-1", "status": "IN_PROGRESS"},
                {"id": "C-2", "status": "OPEN", "depends_on": ["C-1"]},
            ]}, sort_keys=False), encoding="utf-8")
        assert LIB.is_stalled_remedy_dispatch(
            tmp_path, "C-2", None, MARKER,
            stuck_ids=["C-1"], flatlined_open_ids=["C-1"]) is True

    def test_channel_b_requires_stuck_parent_provenance(self, tmp_path):
        """Review round-1 HIGH — the exploit shape: ->OPEN registration is
        ungated and the marker is printed in the rejection prose, so
        "fresh OPEN + marker" alone must NOT admit. The sub-claim's
        depends_on must reference a STUCK claim."""
        (tmp_path / "claim-register.yaml").write_text(
            yaml.safe_dump({"claims": [
                {"id": "C-1", "status": "IN_PROGRESS"},
                {"id": "C-777", "status": "OPEN"},                    # no deps
                {"id": "C-778", "status": "OPEN", "depends_on": ["C-999"]},
            ]}, sort_keys=False), encoding="utf-8")
        for cid in ("C-777", "C-778"):
            assert LIB.is_stalled_remedy_dispatch(
                tmp_path, cid, None, MARKER,
                stuck_ids=["C-1"], flatlined_open_ids=["C-1"]) is False, cid

    def test_channel_b_real_minted_sibling_admitted(self, tmp_path):
        """Pin (b): a REAL issue-234-minted sibling (depends_on -> the
        stuck parent) is still admitted — the tightening keeps the
        operator the gate prescribes."""
        import target_ladder
        (tmp_path / "claim-register.yaml").write_text(
            yaml.safe_dump({"claims": [{
                "id": "C-1", "status": "IN_PROGRESS", "origin":
                "failure-obstacle", "obstacle_class": "interception",
            }]}, sort_keys=False), encoding="utf-8")
        (tmp_path / "runs").mkdir(exist_ok=True)
        (tmp_path / "runs" / "target-ladder-C-1.yaml").write_text(
            yaml.safe_dump({
                "obstacle_class": "interception",
                "attempts": [
                    {"level": "T1", "family": "hooking", "action": "a",
                     "outcome": "o"},
                    {"level": "T2", "family": "repackaging", "action": "a",
                     "outcome": "o"},
                    {"level": "T3", "family": "ca-install", "action": "a",
                     "outcome": "o"},
                ],
                "inventory": [{"family": "hooking", "tried": "t",
                               "failed_because": "f"}],
            }, sort_keys=False), encoding="utf-8")
        r = target_ladder.mint_sibling_claims(tmp_path, "C-1")
        assert r["refused"] is None and r["minted"], "mint must produce C-2"
        minted_id = r["minted"][0]["id"]
        assert LIB.is_stalled_remedy_dispatch(
            tmp_path, minted_id, None, MARKER,
            stuck_ids=["C-1"], flatlined_open_ids=["C-1"]) is True

    def test_channel_b_closed_at_remedy_max_depth(self, tmp_path):
        """Depth escalation: at >= max consecutive cycles the follow-through
        channel closes (channel A is NOT depth-gated)."""
        (tmp_path / "claim-register.yaml").write_text(
            yaml.safe_dump({"claims": [
                {"id": "C-1", "status": "IN_PROGRESS"},
                {"id": "C-2", "status": "OPEN", "depends_on": ["C-1"]},
            ]}, sort_keys=False), encoding="utf-8")
        deep = 99
        assert LIB.is_stalled_remedy_dispatch(
            tmp_path, "C-2", None, MARKER,
            stuck_ids=["C-1"], flatlined_open_ids=["C-1"],
            remedy_depth=deep) is False
        assert LIB.is_stalled_remedy_dispatch(
            tmp_path, "C-1", None, MARKER,
            stuck_ids=["C-1"], flatlined_open_ids=["C-1"],
            remedy_depth=deep) is True, "channel A must survive escalation"

    def test_channel_b_requires_register_open(self, tmp_path):
        (tmp_path / "claim-register.yaml").write_text(
            yaml.safe_dump({"claims": [
                {"id": "C-2", "status": "IN_PROGRESS",
                 "depends_on": ["C-1"]},
            ]}, sort_keys=False), encoding="utf-8")
        assert LIB.is_stalled_remedy_dispatch(
            tmp_path, "C-2", None, MARKER,
            stuck_ids=["C-1"], flatlined_open_ids=["C-1"]) is False

    def test_channel_b_unreadable_register_fails_closed(self, tmp_path):
        (tmp_path / "claim-register.yaml").write_text(
            "claims: [unclosed", encoding="utf-8")
        assert LIB.is_stalled_remedy_dispatch(
            tmp_path, "C-2", None, MARKER,
            stuck_ids=["C-1"], flatlined_open_ids=["C-1"]) is False

    def test_empty_flatline_state_fails_closed(self, tmp_path):
        assert LIB.is_stalled_remedy_dispatch(
            tmp_path, "C-2", None, MARKER,
            stuck_ids=[], flatlined_open_ids=[]) is False

    def test_blank_claim_id_fails_closed(self, tmp_path):
        assert LIB.is_stalled_remedy_dispatch(
            tmp_path, None, None, MARKER,
            stuck_ids=["C-1"], flatlined_open_ids=["C-1"]) is False


# =====================================================================
# scaffold: a workspace the pre-gates pass (mirror of test_worker_budget)
# =====================================================================

def _healthy_ws(tmp_path: Path) -> Path:
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat(timespec="seconds").replace("+00:00", "Z")
    prev = (now_dt - timedelta(minutes=5)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    (tmp_path / "runs" / ".heartbeat.json").write_text(json.dumps(
        {"last_tick_ts": now, "activity_ts": now, "started_ts": prev,
         "tick_history": [prev, now]}), encoding="utf-8")
    with (tmp_path / "runs" / ".heartbeat.log").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": prev, "actor": "tick"}) + "\n")
        f.write(json.dumps({"ts": now, "actor": "tick"}) + "\n")
    (tmp_path / "analysis_state.txt").write_text(
        f"deadline_ts: {int(time.time()) + 3600}\n", encoding="utf-8")
    (tmp_path / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [
            {"id": "C-1", "status": "IN_PROGRESS", "promotion_attempts": 1},
        ]}, sort_keys=False), encoding="utf-8")
    (tmp_path / "claim_deps.yaml").write_text("deps: {}\n", encoding="utf-8")
    (tmp_path / "task_spec.yaml").write_text(
        yaml.safe_dump({"vm_detonation": "allowed"}, sort_keys=False),
        encoding="utf-8")
    return tmp_path


def _paths_for(ws: Path) -> dict:
    return {
        "workspace": str(ws),
        "state": ws / "analysis_state.txt",
        "register": ws / "claim-register.yaml",
        "deps": ws / "claim_deps.yaml",
        "task_spec": ws / "task_spec.yaml",
    }


def _dispatch_payload(claim: str, marker: bool) -> tuple[dict, str]:
    prompt = (json.dumps({"kunglao_dispatch": {
        "version": 1, "claim": claim, "tier": 1,
        "tools": ["grep"], "agent": "w-test"}})
        + "\nfacts-snapshot: 1 facts"
        + (f"\n{MARKER}\n" if marker else "\n"))
    payload = {"tool_input": {"name": "w-test", "description": "",
                              "prompt": prompt}}
    return payload, prompt


# =====================================================================
# R5: worker_budget_core's rc=1 face
# =====================================================================

class TestCoreRc1Face:
    def _rc(self, code: int):
        from types import SimpleNamespace
        return lambda args, cwd=None: SimpleNamespace(
            returncode=code, stderr="", stdout="")

    def test_remedy_dispatch_admitted_at_rc1(self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _stalled_ledger())
        monkeypatch.setattr(wbc, "_run_py", self._rc(1))
        payload, prompt = _dispatch_payload("C-1", marker=True)
        ok, msg = wbc.check_convergence_health(
            _paths_for(ws), "C-1", payload, prompt)
        assert ok is True
        assert "issue-249" in msg

    def test_ordinary_dispatch_stays_blocked_at_rc1(
            self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _stalled_ledger())
        monkeypatch.setattr(wbc, "_run_py", self._rc(1))
        payload, prompt = _dispatch_payload("C-1", marker=False)
        ok, msg = wbc.check_convergence_health(
            _paths_for(ws), "C-1", payload, prompt)
        assert ok is False
        assert msg == "convergence STALLED - diagnose before dispatching"

    def test_marked_non_stuck_claim_stays_blocked(self, tmp_path, monkeypatch):
        """Marker + a claim in the flatlined open set but NOT stuck (queued
        frontier, not the prescribed remedy) -> blocked."""
        ws = _healthy_ws(tmp_path)
        rows = [_snap(i, 2, ["C-1", "C-Q"], ["C-1"]) for i in range(5)]
        (ws / "claim-register.yaml").write_text(
            yaml.safe_dump({"claims": [
                {"id": "C-1", "status": "IN_PROGRESS", "promotion_attempts": 1},
                {"id": "C-Q", "status": "OPEN", "promotion_attempts": 0},
            ]}, sort_keys=False), encoding="utf-8")
        _write_ledger(ws, rows)
        monkeypatch.setattr(wbc, "_run_py", self._rc(1))
        payload, prompt = _dispatch_payload("C-Q", marker=True)
        ok, _msg = wbc.check_convergence_health(
            _paths_for(ws), "C-Q", payload, prompt)
        assert ok is False

    def test_exploit_fresh_open_claim_blocked_at_rc1(
            self, tmp_path, monkeypatch):
        """Review round-1 HIGH, exploit shape at the gate face: an agent
        appends a fresh unrelated OPEN claim mid-STALLED and quotes the
        rejection prose. ->OPEN registration is ungated, so provenance
        (depends_on -> a stuck claim) is the discriminator; a fresh
        unrelated claim must stay REJECTED."""
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _stalled_ledger())
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text(
            encoding="utf-8"))
        reg["claims"].append({"id": "C-777", "status": "OPEN"})
        (ws / "claim-register.yaml").write_text(
            yaml.safe_dump(reg, sort_keys=False), encoding="utf-8")
        monkeypatch.setattr(wbc, "_run_py", self._rc(1))
        payload, prompt = _dispatch_payload("C-777", marker=True)
        ok, msg = wbc.check_convergence_health(
            _paths_for(ws), "C-777", payload, prompt)
        assert ok is False
        assert msg == "convergence STALLED - diagnose before dispatching"

    def test_channel_b_provenance_subclaim_admitted_at_rc1(
            self, tmp_path, monkeypatch):
        """Pin (b) at the gate face: a real minted sibling (depends_on ->
        the stuck parent, register-OPEN, fresh) is still admitted."""
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _stalled_ledger())
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text(
            encoding="utf-8"))
        reg["claims"].append({"id": "C-2", "status": "OPEN",
                              "depends_on": ["C-1"]})
        (ws / "claim-register.yaml").write_text(
            yaml.safe_dump(reg, sort_keys=False), encoding="utf-8")
        monkeypatch.setattr(wbc, "_run_py", self._rc(1))
        payload, prompt = _dispatch_payload("C-2", marker=True)
        ok, msg = wbc.check_convergence_health(
            _paths_for(ws), "C-2", payload, prompt)
        assert ok is True
        assert "issue-249" in msg

    def test_depth_escalation_closes_channel_b_at_rc1(
            self, tmp_path, monkeypatch):
        """Two prior admitted cycles on the stuck claim -> the follow-through
        channel is closed; channel A (the stuck claim itself) stays open."""
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _ledger_with_admits(2))
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text(
            encoding="utf-8"))
        reg["claims"].append({"id": "C-2", "status": "OPEN",
                              "depends_on": ["C-1"]})
        (ws / "claim-register.yaml").write_text(
            yaml.safe_dump(reg, sort_keys=False), encoding="utf-8")
        monkeypatch.setattr(wbc, "_run_py", self._rc(1))
        payload, prompt = _dispatch_payload("C-2", marker=True)
        ok, _msg = wbc.check_convergence_health(
            _paths_for(ws), "C-2", payload, prompt)
        assert ok is False, "escalation must close the follow-through channel"
        payload_a, prompt_a = _dispatch_payload("C-1", marker=True)
        ok_a, msg_a = wbc.check_convergence_health(
            _paths_for(ws), "C-1", payload_a, prompt_a)
        assert ok_a is True, "channel A must survive the escalation"
        assert "depth=2" in msg_a

    def test_state_exception_fails_closed(self, tmp_path, monkeypatch):
        """Round-1 MEDIUM: the detector-state arm must block, not admit."""
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _stalled_ledger())
        monkeypatch.setattr(wbc, "_run_py", self._rc(1))

        def _boom(ws_):
            raise RuntimeError("state unreadable")
        monkeypatch.setattr(ch, "stalled_state", _boom)
        payload, prompt = _dispatch_payload("C-1", marker=True)
        ok, msg = wbc.check_convergence_health(
            _paths_for(ws), "C-1", payload, prompt)
        assert ok is False
        assert "diagnose before dispatching" in msg

    def test_predicate_exception_fails_closed(self, tmp_path, monkeypatch):
        """Round-1 MEDIUM: the predicate arm must block, not admit."""
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _stalled_ledger())
        monkeypatch.setattr(wbc, "_run_py", self._rc(1))

        def _boom(*a, **k):
            raise RuntimeError("predicate exploded")
        monkeypatch.setattr(LIB, "is_stalled_remedy_dispatch", _boom)
        payload, prompt = _dispatch_payload("C-1", marker=True)
        ok, msg = wbc.check_convergence_health(
            _paths_for(ws), "C-1", payload, prompt)
        assert ok is False
        assert "diagnose before dispatching" in msg

    def test_legacy_one_arg_call_keeps_block(self, tmp_path, monkeypatch):
        """Callers without dispatch context (existing tests/consumers) keep
        the exact prior behavior — the exemption is off without a claim."""
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _stalled_ledger())
        monkeypatch.setattr(wbc, "_run_py", self._rc(1))
        ok, msg = wbc.check_convergence_health({"workspace": str(ws)})
        assert ok is False
        assert msg == "convergence STALLED - diagnose before dispatching"

    def test_state_verdict_drift_fails_closed(self, tmp_path, monkeypatch):
        """rc=1 from the subprocess but the re-derived state is NOT stalled
        -> no exemption (a ledger change between reads must not open)."""
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, [
            _snap(0, 3, ["C-1"], []),
            _snap(1, 2, ["C-1"], []),
            _snap(2, 1, ["C-1"], []),
        ])
        monkeypatch.setattr(wbc, "_run_py", self._rc(1))
        payload, prompt = _dispatch_payload("C-1", marker=True)
        ok, _msg = wbc.check_convergence_health(
            _paths_for(ws), "C-1", payload, prompt)
        assert ok is False

    def test_lib_outage_fails_closed(self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _stalled_ledger())
        monkeypatch.setattr(wbc, "_run_py", self._rc(1))

        def _boom():
            raise RuntimeError("lib gone")
        monkeypatch.setattr(wbc, "load_hooks_lib", _boom)
        payload, prompt = _dispatch_payload("C-1", marker=True)
        ok, msg = wbc.check_convergence_health(
            _paths_for(ws), "C-1", payload, prompt)
        assert ok is False
        assert "diagnose before dispatching" in msg

    def test_spinning_rc2_never_exempt(self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        _write_ledger(ws, _stalled_ledger())
        monkeypatch.setattr(wbc, "_run_py", self._rc(2))
        payload, prompt = _dispatch_payload("C-1", marker=True)
        ok, msg = wbc.check_convergence_health(
            _paths_for(ws), "C-1", payload, prompt)
        assert ok is False
        assert "SPINNING" in msg

    def test_crashed_rc4_fail_open_preserved(self, tmp_path, monkeypatch):
        """Issue scope 5: the exit-4 semantics are untouched — a crashed
        check fails open exactly as before, remedy marker or not."""
        ws = _healthy_ws(tmp_path)
        monkeypatch.setattr(wbc, "_run_py", self._rc(4))
        payload, prompt = _dispatch_payload("C-1", marker=True)
        ok, msg = wbc.check_convergence_health(
            _paths_for(ws), "C-1", payload, prompt)
        assert ok is True
        assert "crashed (rc=4)" in msg


# =====================================================================
# R6: the sinks wiring forwards the dispatch context
# =====================================================================

class TestSinksWiring:
    def test_pre_check_forwards_context_to_health_gate(
            self, tmp_path, monkeypatch):
        ws = _healthy_ws(tmp_path)
        seen: dict = {}

        def _recorder(paths, claim_id=None, payload=None, prompt_text=""):
            seen.update({"claim_id": claim_id, "payload": payload,
                         "prompt": prompt_text})
            return (False, "stop")  # short-circuit the chain after capture

        monkeypatch.setattr(wbs, "check_convergence_health", _recorder)
        payload, prompt = _dispatch_payload("C-1", marker=True)
        wbs.pre_check(payload, _paths_for(ws))
        assert seen["claim_id"] == "C-1"
        assert seen["payload"] is payload
        assert MARKER in seen["prompt"]
