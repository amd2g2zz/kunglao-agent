# -*- coding: utf-8 -*-
"""#142 statusline v2 — producer schema fields, repo renderer, project-scoped deployment.

Coverage map (issue #142 acceptance, Python-side):
  - producer emits the schema-2 field set: v_hist / h_bits+h_pq+h_trend /
    health{oracle,retro,dormant} / now{claim,op} / pq_rows + difficulty /
    the #133/#129 phase-2 placeholder slots
  - frontier PQ categorical entropy via posteriors.PQCategorical.entropy;
    trend = compare vs the previous stored snapshot value
  - health faces: #473 oracle marker check / retro lag < 8 / #127 no DORMANT
  - now chip: active worker claim + short op; parked -> last dispatch claim
  - fine-grained PQ data is producer-owned (a poisoned legacy rl-signals
    log must not move a single rendered number — behavioral pin)
  - renderer renders all chips from fixture snapshots; COARSE-PATH NO-THROW
    regression (the external combined-statusline's undefined `blocked` on
    line 137 — a strict-mode ReferenceError that killed the whole statusline)
  - down-freeze watchdog kept
  - PROJECT-scoped statusLine registration (same #258 project file, different
    key); the user-global settings file is NEVER written
  - hooks_selfcheck keep-alive + repair face; deploy manifest carries the
    renderer into the workspace
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
RENDERER = SCRIPTS / "statusline_render.mjs"
sys.path.insert(0, str(SCRIPTS))

import statusline_snapshot as sls  # noqa: E402

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _make_ws(tmp_path: Path) -> Path:
    """Minimal kunglao workspace: identity + register + runs/."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "analysis_state.txt").write_text(
        "# analysis_state\nproject_type=windows\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _touch_heartbeat(ws: Path) -> None:
    (ws / "runs" / ".heartbeat.json").write_text(json.dumps({
        "started_ts": _iso(datetime.now(timezone.utc) - timedelta(seconds=60)),
        "last_tick_ts": _iso(datetime.now(timezone.utc)),
    }), encoding="utf-8")


def _mission(ws: Path, pqs: list[dict], history: list[float]) -> None:
    """mission_ledger.yaml with explicit PQ rows + a v_m history."""
    now = datetime.now(timezone.utc)
    hist = [{"ts": _iso(now), "v_m": float(v)} for v in history]
    (ws / "runs" / "mission_ledger.yaml").write_text(
        yaml.safe_dump({"mission": {"pqs": pqs, "beta": 0.5,
                                    "history": hist,
                                    "feature_used": True}},
                       sort_keys=False), encoding="utf-8")


def _pq(pid: str, state: str = "unattempted", coverage: float = 0.0,
        weight: float = 1.0) -> dict:
    return {"id": pid, "question": "q", "state": state, "coverage": coverage,
            "answered_by": [], "blocker": None, "wake": None,
            "weight": weight}


def _posteriors(ws: Path, pqs: dict[str, dict[str, float]]) -> None:
    """runs/posteriors.yaml via the real PosteriorLedger persistence."""
    from posteriors import PosteriorLedger, PQCategorical
    led = PosteriorLedger(pqs={pid: PQCategorical(pid, cands)
                               for pid, cands in pqs.items()})
    led.save(ws)


def _worker_status(ws: Path, name: str, body: str, age_s: int = 0) -> Path:
    p = ws / "runs" / f"worker-status-{name}.md"
    p.write_text(body, encoding="utf-8")
    if age_s:
        old = time.time() - age_s
        os.utime(p, (old, old))
    return p


def _retro_state(ws: Path, lag: int) -> None:
    (ws / "runs" / ".retro-state.json").write_text(
        json.dumps({"settlements_since_retro": lag,
                    "last_retro_ts": _iso(datetime.now(timezone.utc))}),
        encoding="utf-8")


def _detector_rows(ws: Path, *, fired: bool) -> None:
    import kunglao_log
    kunglao_log.emit(ws, "test", "detector_eval",
                     detail=json.dumps({"detector": "stall_watch"}))
    if fired:
        kunglao_log.emit(ws, "test", "detector_fired",
                         detail=json.dumps({"detector": "stall_watch"}))


@pytest.fixture
def fake_home(tmp_path, monkeypatch) -> Path:
    """Fake HOME so Path.home()-derived checks bind to the test area
    (same seam the other registration test modules pin)."""
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


def _full_snap() -> dict:
    """Fresh fixture snapshot (flash ts must be wall-clock fresh per test)."""
    return {
        "schema": 2, "state": "analyzing",
        "color": {"hue": 140, "sat": 72, "light": 55},
        "v_hist": [0.1, 0.18, 0.25, 0.31, 0.4, 0.42],
        "v_norm": 0.42,
        "pq": {"answered": 2, "total": 5, "blocked": 1},
        "h_bits": 1.3, "h_trend": "falling",
        "health": {"oracle": True, "retro": True, "dormant": True},
        "now": {"claim": "C-409", "op": "sign-algo probe"},
        "flash": {"seq": 3, "reason": "claim_progress",
                  "ts": _iso(datetime.now(timezone.utc)),
                  "text": "CASE-GREEN"},
    }


# ===========================================================================
# 1. producer — snapshot schema-2 field set
# ===========================================================================

class TestProducerSchema142:
    def test_schema2_fields_present(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        snap = sls.build_snapshot(ws)
        assert snap["schema"] == 2
        for key in ("v_hist", "h_bits", "h_pq", "h_trend", "health", "now",
                    "pq_rows", "difficulty", "v_oracle_gap", "baseline_inv_k"):
            assert key in snap, f"schema-2 field {key} missing"
        # #133/#129 phase-2 slots: named now, populated later.
        assert snap["v_oracle_gap"] is None
        assert snap["baseline_inv_k"] is None
        assert set(snap["health"]) == {"oracle", "retro", "dormant"}
        assert set(snap["now"]) == {"claim", "op"}

    def test_v_hist_last_8_normalized_points(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        pqs = [_pq("PQ-1", "answered", 1.0), _pq("PQ-2")]
        # v_m <= Σweight (2.0) so the normalized series stays in [0,1]
        _mission(ws, pqs, [0.0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.6])
        snap = sls.build_snapshot(ws)
        assert len(snap["v_hist"]) == sls.V_HIST_POINTS
        assert all(0.0 <= v <= 1.0 for v in snap["v_hist"])
        assert snap["v_hist"][-1] == pytest.approx(snap["v_norm"])
        # sparkline momentum: rising history ends above its start
        assert snap["v_hist"][-1] > snap["v_hist"][0]

    def test_v_hist_empty_without_history(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        snap = sls.build_snapshot(ws)
        assert snap["v_hist"] == []

    # ---------- entropy badge ----------

    def test_h_bits_frontier_entropy(self, tmp_path):
        from posteriors import PQCategorical
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        pqs = [_pq("PQ-1", "answered", 1.0), _pq("PQ-2")]
        _mission(ws, pqs, [1.0])
        # frontier = first non-answered PQ (PQ-2); 50/50 -> exactly 1 bit
        _posteriors(ws, {"PQ-1": {"a": 1, "b": 1}, "PQ-2": {"a": 1, "b": 1}})
        snap = sls.build_snapshot(ws)
        assert snap["h_pq"] == "PQ-2"
        assert snap["h_bits"] == pytest.approx(
            PQCategorical("PQ-2", {"a": 1, "b": 1}).entropy(), abs=1e-3)
        assert snap["h_bits"] == pytest.approx(1.0, abs=1e-3)

    def test_h_bits_falls_back_to_max_entropy_pq(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        pqs = [_pq("PQ-1", "answered", 1.0), _pq("PQ-2")]
        _mission(ws, pqs, [1.0])
        # frontier PQ-2 has NO posterior -> deterministic max-entropy fallback
        _posteriors(ws, {"PQ-9": {"a": 1, "b": 1}, "PQ-8": {"a": 9, "b": 1}})
        snap = sls.build_snapshot(ws)
        assert snap["h_pq"] == "PQ-9"

    def test_h_bits_absent_without_posteriors(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        snap = sls.build_snapshot(ws)
        assert snap["h_bits"] is None and snap["h_pq"] is None
        assert snap["h_trend"] == "unknown"

    def test_h_trend_compares_previous_stored_value(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _mission(ws, [_pq("PQ-1")], [1.0])
        _posteriors(ws, {"PQ-1": {"a": 1, "b": 1}})
        prev_tpl = {"schema": 2, "state": "analyzing", "tick": 1,
                    "flash": {"seq": 0, "ts": None, "reason": None,
                              "text": None}}
        for prev_h, expected in ((1.5, "falling"), (1.0, "flat"),
                                 (0.5, "rising"), (None, "unknown")):
            prev = dict(prev_tpl, h_bits=prev_h)
            (ws / "runs" / ".kunglao-statusline.json").write_text(
                json.dumps(prev), encoding="utf-8")
            snap = sls.build_snapshot(ws)
            assert snap["h_trend"] == expected, f"prev h_bits={prev_h}"

    # ---------- health dots ----------

    def test_health_oracle_marker_vs_registered(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        (ws / "task-oracle.yaml").write_text(
            "oracle: pending-user-input-backfill\n", encoding="utf-8")
        assert sls.build_snapshot(ws)["health"]["oracle"] is False
        (ws / "task-oracle.yaml").write_text(
            "goal: recover the algorithm\nchecks: []\n", encoding="utf-8")
        assert sls.build_snapshot(ws)["health"]["oracle"] is True

    def test_health_retro_lag_threshold(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _retro_state(ws, 9)  # >= 8 settlements since retro
        assert sls.build_snapshot(ws)["health"]["retro"] is False
        _retro_state(ws, 2)
        assert sls.build_snapshot(ws)["health"]["retro"] is True

    def test_health_dormant_detectors(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _detector_rows(ws, fired=False)  # evaluated, never fired -> DORMANT
        assert sls.build_snapshot(ws)["health"]["dormant"] is False
        _detector_rows(ws, fired=True)
        assert sls.build_snapshot(ws)["health"]["dormant"] is True

    # ---------- current-task chip ----------

    def test_now_active_worker_claim_and_op(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _worker_status(ws, "w1",
                       "[10:00] claim: C-409 | step: sign-algo probe "
                       "| status: in-progress\n")
        snap = sls.build_snapshot(ws)
        assert snap["now"]["claim"] == "C-409"
        assert snap["now"]["op"] == "sign-algo probe"

    def test_now_op_capped_at_24_chars(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _worker_status(ws, "w1",
                       "claim: C-1 | step: a very long task phrase that "
                       "exceeds the chip budget | status: in-progress\n")
        snap = sls.build_snapshot(ws)
        assert len(snap["now"]["op"]) <= sls.NOW_OP_MAX_CHARS

    def test_now_waiting_worker_is_not_active(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _worker_status(ws, "w1",
                       "claim: C-1 | step: x | status: waiting\n")
        snap = sls.build_snapshot(ws)
        assert snap["now"]["op"] is None

    def test_now_idle_falls_back_to_last_dispatch_claim(self, tmp_path):
        import kunglao_log
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        kunglao_log.emit(ws, "orchestrator", "dispatch", claim="C-7",
                         detail="dispatch")
        snap = sls.build_snapshot(ws)
        assert snap["now"]["claim"] == "C-7"
        assert snap["now"]["op"] is None

    # ---------- producer-owned fine-grained PQ data ----------

    def test_pq_rows_and_difficulty_are_producer_owned(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        pqs = [_pq("PQ-1", "answered", 1.0), _pq("PQ-2", "unattempted", 0.25)]
        _mission(ws, pqs, [1.0])
        (ws / "evidence").mkdir()
        (ws / "evidence" / "difficulty.json").write_text(
            json.dumps({"tier": "hard"}), encoding="utf-8")  # canonical key
        snap = sls.build_snapshot(ws)
        assert snap["pq_rows"] == [
            {"id": "PQ-1", "state": "answered", "coverage": 1.0},
            {"id": "PQ-2", "state": "unattempted", "coverage": 0.25},
        ]
        assert snap["difficulty"] == "hard"

    def test_snapshot_write_round_trips_v2_fields(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _mission(ws, [_pq("PQ-1")], [0.2, 0.6])
        _posteriors(ws, {"PQ-1": {"a": 3, "b": 1}})
        out = sls.write_snapshot(ws)
        snap = json.loads(out.read_text(encoding="utf-8"))
        assert snap["schema"] == 2
        assert snap["v_hist"] and snap["h_bits"] is not None


# ===========================================================================
# 2. renderer — pure view over the snapshot (node subprocess)
# ===========================================================================

def _strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def _write_snapshot(ws: Path, snap: dict, age_s: int = 0) -> None:
    p = ws / "runs" / ".kunglao-statusline.json"
    p.write_text(json.dumps(snap), encoding="utf-8")
    if age_s:
        old = time.time() - age_s
        os.utime(p, (old, old))


# (fixture snapshots are built via _full_snap() — fresh flash ts per call).


def _run_renderer(ws: Path) -> subprocess.CompletedProcess:
    """Drive the renderer subprocess against a fixture workspace (stdin
    JSON names the ws dir; HUD disabled via the KUNGLAO_STATUSLINE_HUD seam)."""
    payload = json.dumps(
        {"workspace": {"current_dir": str(ws)}, "model": {"display_name": "t"}})
    return subprocess.run(
        ["node", str(RENDERER)], input=payload, capture_output=True,
        text=True, timeout=30, cwd=str(ws.parent))


@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
class TestRenderer142:
    @pytest.fixture(autouse=True)
    def _no_hud(self, monkeypatch):
        # deterministic: no claude-hud passthrough in tests
        monkeypatch.setenv("KUNGLAO_STATUSLINE_HUD", "")

    def _run(self, ws: Path, stdin_payload: dict | None = None) -> subprocess.CompletedProcess:
        return _run_renderer(ws)

    def test_renders_all_chips_from_fixture_snapshot(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_snapshot(ws, _full_snap())
        r = self._run(ws)
        assert r.returncode == 0, r.stderr
        out = _strip_ansi(r.stdout)
        assert "analyzing" in out                     # state (cyan face)
        assert any(c in out for c in "▁▂▃▄▅▆▇█")      # sparkline shape
        assert "42%" in out                           # fine v_norm percent
        assert "H1.3b" in out                         # entropy badge
        assert "●●●" in out                           # three solid health dots
        assert "C-409 sign-algo probe" in out         # current-task chip
        assert "⚡CASE-GREEN" in out                  # 5s flash kept
        # deleted as noise: CONVERGENCE HEALTH text / tick number / slope chip
        assert "CONVERGENCE HEALTH" not in out
        assert "tick " not in out
        assert "slope=" not in out

    def test_color_is_data_four_meaning_palette(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_snapshot(ws, _full_snap())
        r = self._run(ws)
        assert r.returncode == 0
        # green = learning (uptrend sparkline + H falling), cyan = working,
        # and NO decorative hues beyond the four-meaning set.
        assert "\x1b[32m" in r.stdout
        assert "\x1b[36m" in r.stdout

    def test_entropy_badge_trend_colors(self, tmp_path):
        ws = _make_ws(tmp_path)
        for trend, color in (("falling", "\x1b[32m"), ("rising", "\x1b[31m"),
                             ("flat", "\x1b[33m")):
            _write_snapshot(ws, dict(_full_snap(), h_trend=trend,
                                     flash={"seq": 0, "reason": None,
                                            "ts": None, "text": None}))
            r = self._run(ws)
            assert r.returncode == 0
            badge_colored = re.search(r"mH1\.3b", r.stdout)
            assert badge_colored, f"badge missing for {trend}"
            idx = r.stdout.find("H1.3b")
            assert color in r.stdout[max(0, idx - 12):idx], \
                f"trend {trend} must color the badge {color!r}"

    def test_health_dots_amber_when_retro_lag(self, tmp_path):
        ws = _make_ws(tmp_path)
        snap = dict(_full_snap(), health={"oracle": True, "retro": False,
                                       "dormant": True})
        _write_snapshot(ws, snap)
        r = self._run(ws)
        assert r.returncode == 0
        # suspect dots render amber (stall-suspect face), healthy stay green
        assert "\x1b[33m●" in r.stdout
        assert "\x1b[32m●" in r.stdout

    def test_health_dots_red_when_oracle_unregistered(self, tmp_path):
        ws = _make_ws(tmp_path)
        snap = dict(_full_snap(), health={"oracle": False, "retro": True,
                                       "dormant": True})
        _write_snapshot(ws, snap)
        r = self._run(ws)
        assert r.returncode == 0
        assert "\x1b[31m●" in r.stdout

    def test_idle_chip_when_parked(self, tmp_path):
        ws = _make_ws(tmp_path)
        snap = dict(_full_snap(), now={"claim": "C-7", "op": None})
        _write_snapshot(ws, snap)
        r = self._run(ws)
        assert r.returncode == 0
        assert "idle · last C-7" in _strip_ansi(r.stdout)

    def test_coarse_path_renders_without_throwing(self, tmp_path):
        """THE #142 crash regression: the external combined-statusline
        referenced an undefined `blocked` on exactly this path (line 137) —
        .mjs strict mode raises ReferenceError and killed the whole
        statusline. The coarse path (legacy snapshot, no v2 fields, no
        fine-grained data) must render as a first-class frame."""
        ws = _make_ws(tmp_path)
        legacy = {"schema": 1, "state": "analyzing",
                  "color": {"hue": 140},
                  "pq": {"answered": 2, "total": 5, "blocked": 1}}
        _write_snapshot(ws, legacy)
        r = self._run(ws)
        assert r.returncode == 0, f"coarse path threw: {r.stderr}"
        assert "ReferenceError" not in r.stderr
        out = _strip_ansi(r.stdout)
        assert "analyzing" in out
        assert "40%" in out
        assert out.strip().endswith("40%")

    def test_down_freeze_watchdog(self, tmp_path):
        ws = _make_ws(tmp_path)
        _write_snapshot(ws, _full_snap(), age_s=36 * 60)  # beyond T_DEAD_MS
        r = self._run(ws)
        assert r.returncode == 0
        out = _strip_ansi(r.stdout)
        assert "DOWN" in out
        assert "○○○" in out  # empty dots — the broken face

    def test_renderer_ignores_legacy_rl_signals_log(self, tmp_path):
        """Producer-owned data (the #142 contract fix, behavioral): the
        external renderer read fine-grained PQ data DIRECTLY from
        runs/rl-signals.jsonl — a zero-spawn contract violation. A poisoned
        legacy log must not move a single rendered number."""
        ws = _make_ws(tmp_path)
        (ws / "runs" / "rl-signals.jsonl").write_text(
            json.dumps({"kind": "voi_settle", "total_claims": 9,
                        "v_norm": 0.99,
                        "pq": {"X": {"cov": 0.99}},
                        "difficulty": {"difficulty": "max"}}),
            encoding="utf-8")
        _write_snapshot(ws, _full_snap())  # says 42%
        r = self._run(ws)
        assert r.returncode == 0, r.stderr
        out = _strip_ansi(r.stdout)
        assert "42%" in out and "99%" not in out, \
            "renderer consumed the legacy raw log — producer-owned data violated"
        assert "q5" not in out and "X:" not in out

    def test_no_snapshot_renders_nothing(self, tmp_path):
        ws = _make_ws(tmp_path)
        r = self._run(ws)
        assert r.returncode == 0
        assert r.stdout == ""


# ===========================================================================
# 3. deployment — PROJECT-scoped registration + keep-alive
# ===========================================================================

class TestStatuslineRegistration142:
    def test_register_statusline_writes_project_settings(self, tmp_path):
        from hook_activation import register_statusline
        ws = _make_ws(tmp_path)
        settings = ws / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"env": {"A": "b"}}), encoding="utf-8")
        res = register_statusline(ws)
        assert res["ok"] is True
        doc = json.loads(settings.read_text(encoding="utf-8"))
        assert doc["env"] == {"A": "b"}, "unrelated keys preserved"
        entry = doc["statusLine"]
        assert entry["type"] == "command"
        assert entry["command"].startswith("node ")
        assert entry["command"].endswith("statusline_render.mjs")
        assert "/scripts/statusline_render.mjs" in entry["command"]

    def test_register_statusline_idempotent(self, tmp_path):
        from hook_activation import register_statusline
        ws = _make_ws(tmp_path)
        first = register_statusline(ws)
        second = register_statusline(ws)
        assert first["command"] == second["command"]
        doc = json.loads((ws / ".claude" / "settings.json")
                         .read_text(encoding="utf-8"))
        assert isinstance(doc["statusLine"], dict)

    def test_register_statusline_prefers_workspace_local_copy(self, tmp_path):
        from hook_activation import register_statusline
        ws = _make_ws(tmp_path)
        local = ws / ".claude" / "scripts"
        local.mkdir(parents=True)
        (local / "statusline_render.mjs").write_text("// deployed copy\n",
                                                     encoding="utf-8")
        res = register_statusline(ws)
        assert res["command"] == f"node {(ws / '.claude' / 'scripts' / 'statusline_render.mjs').as_posix()}"

    def test_register_hooks_wires_statusline_project_scoped(
            self, tmp_path, fake_home):
        """--wire-up now registers BOTH faces into the #258 project file —
        and never touches the user-global settings."""
        from hook_activation import register_hooks
        ws = _make_ws(tmp_path)
        rc = register_hooks(workspace=ws)
        assert rc > 0
        doc = json.loads((ws / ".claude" / "settings.json")
                         .read_text(encoding="utf-8"))
        assert doc["statusLine"]["type"] == "command"
        assert "statusline_render.mjs" in doc["statusLine"]["command"]
        assert not (fake_home / ".claude" / "settings.json").exists(), \
            "user-global settings must never be written (#258/#142)"

    def test_register_hooks_global_opt_in_never_registers_statusline(
            self, tmp_path, fake_home):
        """The user-global escape hatch is hooks-only: even with explicit
        opt-in, the statusline never lands in ~/.claude/settings.json."""
        from hook_activation import register_hooks
        ws = _make_ws(tmp_path)
        register_hooks(workspace=ws, global_opt_in=True)
        doc = json.loads((fake_home / ".claude" / "settings.json")
                         .read_text(encoding="utf-8"))
        assert "statusLine" not in doc, \
            "statusLine is PROJECT-scoped only — no global registration path"

    def test_selfcheck_repairs_missing_statusline(self, tmp_path, fake_home,
                                                  monkeypatch):
        """keep-alive face: hooks fine, statusLine key deleted -> selfcheck
        repairs it in the PROJECT file and records the row."""
        from hook_activation import register_hooks
        ws = _make_ws(tmp_path)
        register_hooks(workspace=ws)
        settings_path = ws / ".claude" / "settings.json"
        doc = json.loads(settings_path.read_text(encoding="utf-8"))
        doc.pop("statusLine")
        settings_path.write_text(json.dumps(doc), encoding="utf-8")

        sys.modules.pop("hooks_selfcheck", None)
        import hooks_selfcheck
        monkeypatch.setattr(sys, "argv", ["hooks_selfcheck.py", str(ws)])
        rc = hooks_selfcheck.main()
        assert rc == 0
        repaired = json.loads(settings_path.read_text(encoding="utf-8"))
        assert "statusline_render.mjs" in repaired["statusLine"]["command"]
        report = json.loads((ws / "runs" / ".hooks-selfcheck.json")
                            .read_text(encoding="utf-8"))
        assert report["statusline"]["ok"] is True

    def test_selfcheck_report_carries_statusline_row(self, tmp_path, fake_home,
                                                     monkeypatch):
        sys.modules.pop("hooks_selfcheck", None)
        import hooks_selfcheck
        ws = _make_ws(tmp_path)
        settings = ws / ".claude" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command",
                 "command": "PYTHONUTF8=1 uv run --project "
                            f"{ROOT.as_posix()} {ROOT / 'hooks' / 'heartbeat_touch.py'}"}]}]},
        }), encoding="utf-8")
        # KONG chain incomplete -> rebuild fires via --wire-up (which also
        # registers the statusline); the report row must end ok either way.
        monkeypatch.setattr(sys, "argv", ["hooks_selfcheck.py", str(ws)])
        hooks_selfcheck.main()
        report = json.loads((ws / "runs" / ".hooks-selfcheck.json")
                            .read_text(encoding="utf-8"))
        assert report["statusline"]["ok"] is True
        assert "statusline_render.mjs" in (report["statusline"]["command"] or "")

    def test_deploy_manifest_carries_the_renderer(self):
        from deploy_manifest import build_entries
        entries = build_entries()
        match = [e for e in entries
                 if e["src"] == "scripts/statusline_render.mjs"]
        assert match, "renderer must ride the deployment manifest"
        assert match[0]["dest"] == ".claude/scripts/statusline_render.mjs"

    def test_committed_manifest_matches_build_entries(self):
        """The committed deploy-manifest.yaml is a full mirror of
        build_entries() (incl. the #142 renderer entry)."""
        import deploy_manifest as dm
        import yaml
        committed = yaml.safe_load(
            (ROOT / "deploy-manifest.yaml").read_text(encoding="utf-8"))
        assert committed.get("files") == dm.build_entries()


# ===========================================================================
# 4. follow-up — entropy face single-sourcing + dual-use display
# ===========================================================================

class TestEntropyFace142:
    """The entropy-trend computation lives in ONE shared module
    (scripts/entropy_face.py): the snapshot renders it, the heartbeat tick
    report carries the SAME computed values, decision-side consumers read
    the display's numbers (dual-use display, owner principle)."""

    def test_snapshot_delegates_to_the_shared_face(self):
        """Single-source pin: the snapshot module must not carry a second
        h_bits/trend computation — it delegates to entropy_face.face."""
        import entropy_face
        assert sls._entropy_face is entropy_face.face

    def test_frontier_entropy_known_value(self, tmp_path):
        from entropy_face import frontier_entropy
        ws = _make_ws(tmp_path)
        _mission(ws, [_pq("PQ-1")], [1.0])
        _posteriors(ws, {"PQ-1": {"a": 1, "b": 1}})
        h_bits, h_pq = frontier_entropy(ws)
        assert h_pq == "PQ-1"
        assert h_bits == pytest.approx(1.0, abs=1e-3)

    def test_trend_transitions(self):
        from entropy_face import trend
        assert trend(0.8, 1.5) == "falling"
        assert trend(1.0, 1.0) == "flat"
        assert trend(1.5, 0.8) == "rising"
        assert trend(None, 1.0) == "unknown"
        assert trend(1.0, None) == "unknown"

    def test_face_reads_prev_from_stored_snapshot(self, tmp_path):
        from entropy_face import face, prev_h_bits
        ws = _make_ws(tmp_path)
        _mission(ws, [_pq("PQ-1")], [1.0])
        _posteriors(ws, {"PQ-1": {"a": 1, "b": 1}})
        assert prev_h_bits(ws) is None  # no snapshot yet
        f = face(ws)
        assert f["h_trend"] == "unknown"
        # store a prev with higher entropy -> next face reads falling
        (ws / "runs" / ".kunglao-statusline.json").write_text(
            json.dumps({"h_bits": 2.0}), encoding="utf-8")
        assert prev_h_bits(ws) == 2.0
        f = face(ws)
        assert f["h_bits"] == pytest.approx(1.0, abs=1e-3)
        assert f["h_trend"] == "falling"

    def test_face_prev_dict_bypasses_disk_read(self, tmp_path):
        from entropy_face import face
        ws = _make_ws(tmp_path)
        _mission(ws, [_pq("PQ-1")], [1.0])
        _posteriors(ws, {"PQ-1": {"a": 1, "b": 1}})
        f = face(ws, prev={"h_bits": 0.5})
        assert f["h_trend"] == "rising"

    def test_face_fail_open_on_empty_ws(self, tmp_path):
        from entropy_face import face
        ws = _make_ws(tmp_path)
        f = face(ws)
        assert f == {"h_bits": None, "h_pq": None, "h_trend": "unknown"}

    def test_snapshot_and_tick_report_read_the_same_values(self, tmp_path):
        """The dual-use contract, end to end: producer and tick report must
        carry byte-identical h fields for the same workspace state."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _mission(ws, [_pq("PQ-1")], [1.0])
        _posteriors(ws, {"PQ-1": {"a": 1, "b": 1}})
        import entropy_face
        snap = sls.build_snapshot(ws)
        face = entropy_face.face(ws)  # tick-face call shape (no prev arg)
        assert snap["h_bits"] == face["h_bits"]
        assert snap["h_pq"] == face["h_pq"]
        # first observation -> both faces say unknown, identically
        assert snap["h_trend"] == face["h_trend"] == "unknown"

    def test_tick_report_carries_entropy_face(self, tmp_path):
        """heartbeat_tick's report face (runs/.heartbeat-tick.json) gains
        h_bits/h_pq/h_trend — the gear-shift signal decision-side."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        _mission(ws, [_pq("PQ-1")], [1.0])
        _posteriors(ws, {"PQ-1": {"a": 1, "test-tick-face": 1}})
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "heartbeat_tick.py"), str(ws)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180)
        out = ws / "runs" / ".heartbeat-tick.json"
        assert out.exists(), (
            f"tick must write the report; rc={r.returncode} "
            f"stderr={r.stderr[-300:]}")
        report = json.loads(out.read_text(encoding="utf-8"))
        assert report["h_pq"] == "PQ-1"
        assert report["h_bits"] == pytest.approx(1.0, abs=1e-3)
        assert report["h_trend"] == "unknown"

    def test_renderer_documented_dual_use_map(self):
        """Owner principle, mechanical pin: the renderer's header must carry
        the dual-use map (every chip -> agent-side consumer)."""
        source = RENDERER.read_text(encoding="utf-8")
        assert "DUAL-USE MAP" in source
        for consumer in ("noop-breaker", "budget pacing",
                         "gear-shift", "backtrack gate",
                         "worker-status protocol"):
            assert consumer in source


# ===========================================================================
# 5. follow-up 2 — event-driven freshness contract (#142 refinement)
# ===========================================================================

class TestTokenZero142:
    """Token-zero invariant: the per-tool-use snapshot refresh rides the
    heartbeat_touch hook, whose output would enter the model context — so
    the refresh must be SILENT on success AND on failure (fail-open both
    ways, zero stdout / zero stderr / zero additionalContext)."""

    def _run_touch(self, tmp_path, monkeypatch, capsys, *, boom):
        """Load the HOOK file by explicit path: `heartbeat_touch` is a
        pre-existing hooks/scripts shared-name twin (#671 class) and the
        registered PreToolUse/Bash hook is hooks/heartbeat_touch.py — the
        by-path load pins the tested artifact regardless of sys.modules
        history from earlier test modules."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "kunglao_142_statusline_touch", ROOT / "hooks" / "heartbeat_touch.py")
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        (ws / "runs" / ".kunglao-statusline.json").write_text(
            json.dumps({"schema": 2, "state": "idle"}), encoding="utf-8")
        calls = []
        if boom:
            def boom_fn(*a, **k):
                calls.append("boom")
                raise RuntimeError("boom")
            monkeypatch.setattr(sls, "write_snapshot", boom_fn)
        else:
            def ok_fn(*a, **k):
                calls.append("ok")
                return ws / "runs" / ".kunglao-statusline.json"
            monkeypatch.setattr(sls, "write_snapshot", ok_fn)
        monkeypatch.chdir(ws)
        rc = hook.main()
        captured = capsys.readouterr()
        return rc, captured, ws, calls

    def test_refresh_success_is_silent(self, tmp_path, monkeypatch, capsys):
        rc, captured, ws, calls = self._run_touch(tmp_path, monkeypatch,
                                                  capsys, boom=False)
        assert rc == 0
        assert calls == ["ok"], "the touch path must refresh the snapshot"
        assert captured.out == "" and captured.err == "", \
            "hook output enters context = token cost; refresh must be silent"

    def test_refresh_failure_is_silent(self, tmp_path, monkeypatch, capsys):
        rc, captured, ws, calls = self._run_touch(tmp_path, monkeypatch,
                                                  capsys, boom=True)
        assert rc == 0  # fail-open: never blocks the tool call
        assert calls == ["boom"], "the refresh ran and its failure was swallowed"
        assert captured.out == "" and captured.err == "", \
            "even a failed refresh must stay token-zero"

    def test_touch_hook_subprocess_is_silent(self, tmp_path):
        """End-to-end: the real hook subprocess emits nothing on either
        stream (Claude Code captures hook stdout into the tool flow)."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        r = subprocess.run(
            [sys.executable, str(ROOT / "hooks" / "heartbeat_touch.py")],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=120, cwd=str(ws))
        assert r.returncode == 0
        assert r.stdout == "" and r.stderr == ""
        assert (ws / "runs" / ".kunglao-statusline.json").exists(), \
            "per-tool-use refresh must write the snapshot"


class TestThreeValuedStaleness142:
    """Renderer staleness is three-valued, not binary: fresh -> snapshot's
    own state face; stale within liveness policy -> IDLE face (dim, not
    red — alive with no events is truthful); beyond policy (or the
    snapshot's own down verdict) -> DOWN red. The 5-min tick is not a
    display dependency anymore."""

    def _run_at_age(self, tmp_path, *, age_min, state="analyzing"):
        ws = _make_ws(tmp_path)
        snap = _full_snap()
        snap["state"] = state
        _write_snapshot(ws, snap, age_s=age_min * 60)
        return _run_renderer(ws)

    def test_stale_within_policy_renders_idle_face(self, tmp_path):
        r = self._run_at_age(tmp_path, age_min=10)  # > tick, < policy
        assert r.returncode == 0
        out = _strip_ansi(r.stdout)
        assert "idle" in out and "DOWN" not in out
        assert "analyzing" not in out  # last-event state is not shown as live

    def test_fresh_renders_snapshot_state(self, tmp_path):
        r = self._run_at_age(tmp_path, age_min=0)
        assert r.returncode == 0
        assert "analyzing" in _strip_ansi(r.stdout)

    def test_beyond_policy_renders_down(self, tmp_path):
        r = self._run_at_age(tmp_path, age_min=36)
        assert r.returncode == 0
        assert "DOWN" in _strip_ansi(r.stdout)

    def test_producer_down_verdict_is_trusted_when_fresh(self, tmp_path):
        """The liveness face's own down verdict (probe-driven) shows DOWN
        even on a fresh snapshot — mtime age never overrides it."""
        r = self._run_at_age(tmp_path, age_min=0, state="down")
        assert r.returncode == 0
        assert "DOWN" in _strip_ansi(r.stdout)
        assert "○○○" in _strip_ansi(r.stdout)

    def test_staleness_boundaries_are_strict(self, tmp_path):
        """Boundary pin for the three-valued horizons (strict >): just
        under 5min = fresh (own state); just over 5min = idle; just under
        35min = still idle (alive); just over 35min = DOWN."""
        cases = [(4 * 60 + 59, "analyzing", False),
                 (5 * 60 + 1, "idle", False),
                 (34 * 60 + 59, "idle", False),
                 (35 * 60 + 1, "DOWN", True)]
        for age_s, label, is_down in cases:
            # drive seconds directly (mtime strictness matters at the edges);
            # one workspace per case (each renders independently)
            ws = _make_ws(tmp_path / f"age-{age_s}")
            snap = _full_snap()
            _write_snapshot(ws, snap, age_s=age_s)
            r = _run_renderer(ws)
            out = _strip_ansi(r.stdout)
            assert r.returncode == 0, r.stderr
            if is_down:
                assert "DOWN" in out, f"age {age_s}s must render DOWN"
            else:
                assert label in out, f"age {age_s}s must render {label}"
                assert "DOWN" not in out, f"age {age_s}s must not render DOWN"
