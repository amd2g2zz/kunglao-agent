# -*- coding: utf-8 -*-
"""Issue 212 statusline v2 ASSEMBLY — wire the library parts into a live statusline.

Issue 142 shipped the two library halves (scripts/statusline_render.mjs +
scripts/statusline_snapshot.py); the wiring never landed, so a freshly
initialized workspace showed no statusline at all. This module pins the
ASSEMBLY contract (issue 212 + the owner priority update + the field
diagnosis follow-ups):

  1. init FIRST step registers statusLine in <ws>/.claude/settings.json
     (project-scoped, timeout field, idempotent kunglao-owned key);
     --no-hooks / plugin seam is the documented opt-out.
  2. init deploys the data-plane copy (<ws>/.claude/scripts/
     statusline_snapshot.py) with the manifest sha256, and the heartbeat
     tick hook INVOKES the deployed copy (not the skill-root original).
  3. one heartbeat tick produces <ws>/runs/.kunglao-statusline.json; the
     renderer turns it into a minimal always-works line even with ZERO
     analysis data (success/failure visible; absent data = hidden segment,
     never a broken line).
  4. crash-class immunity (field diagnosis: the legacy combined-statusline
     referenced an undefined field and died on data-poor workspaces): the
     repo renderer must emit a valid minimal line on a workspace with no
     rich data at all.
  5. terminal color degradation: NO_COLOR / TERM=dumb renders the same
     readable line without ANSI escapes.
  6. init seeds the mission-ledger baseline (runs/mission_ledger.yaml) so
     the progress segment renders a real 0/N from tick one, and closes the
     three scaffold seed claims (C-001..C-003) as PROVEN-by-construction so
     the state segment does not lie "analyzing" forever on an idle
     workspace. The progress denominator is LIVE: claims registered later
     grow N on the next tick (closed monotonic, total non-decreasing).
  7. difficulty + perf faces ride both planes (calibrated tier / raw
     signals; claims closed/total, rolling win-rate, heartbeat age, worker
     liveness) and render as conditional segments.
  8. upgrade re-verifies the registration on EVERY run, reports it as the
     FIRST line of output, and self-heals a removed/stale registration.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
RENDERER = SCRIPTS / "statusline_render.mjs"
HEARTBEAT_HOOK = ROOT / "hooks" / "heartbeat_touch.py"

sys.path.insert(0, str(SCRIPTS))

from _factories import seed_bins, seed_oracle_anchors  # noqa: E402

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------

def _make_ws(tmp_path: Path) -> Path:
    """Minimal kunglao workspace (same shape the issue-142 module pins)."""
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "analysis_state.txt").write_text(
        "# analysis_state\nproject_type=windows\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    return ws


def _touch_heartbeat(ws: Path) -> None:
    (ws / "runs" / ".heartbeat.json").write_text(json.dumps({
        "started_ts": "2026-01-01T00:00:00Z",
        "last_tick_ts": "2026-01-01T00:00:00Z",
    }), encoding="utf-8")


def _clean_env() -> dict:
    """Renderer env without ambient color settings (tests opt in explicitly)."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("NO_COLOR", "KUNGLAO_STATUSLINE_NOW_MS")}
    env["TERM"] = "xterm"
    env["KUNGLAO_STATUSLINE_HUD"] = ""
    return env


def _run_renderer(ws: Path, env_extra: dict | None = None,
                  stdin_payload: dict | None = None) -> subprocess.CompletedProcess:
    payload = json.dumps({"workspace": {"current_dir": str(ws)},
                          "model": {"display_name": "t"}}) \
        if stdin_payload is None else json.dumps(stdin_payload)
    env = _clean_env()
    env.update(env_extra or {})
    return subprocess.run(["node", str(RENDERER)], input=payload,
                          capture_output=True, text=True, timeout=30,
                          cwd=str(ws.parent), env=env)


def _run_hook(ws: Path, hook: Path = HEARTBEAT_HOOK) -> subprocess.CompletedProcess:
    """One heartbeat tick: the touch hook with cwd = workspace (hook
    subprocesses inherit the session cwd)."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, str(hook)], cwd=str(ws),
                          capture_output=True, text=True, timeout=120, env=env)


def _run_init(ws: Path, extra: list[str] | None = None,
              anchors: bool = True) -> subprocess.CompletedProcess:
    """Hermetic full init run (the test_kunglao_init harness shape)."""
    if anchors:
        seed_oracle_anchors(ws)
    argv = [sys.executable, str(SCRIPTS / "kunglao-init.py"), str(ws),
            *(extra or []), "--skip-toolchain", "--type", "windows",
            "--profile-root", str(ws.parent / "profile-root")]
    env = {k: v for k, v in os.environ.items() if k != FLAG_NAME}
    env["PYTHONIOENCODING"] = "utf-8"
    env[FLAG_NAME] = "0"
    env["CLAUDE_CODE_HOST_EXEC_PROTECTION"] = "enabled"
    return subprocess.run(
        [*argv, "--host-exec-protection", "enabled"],
        capture_output=True, text=True, timeout=180, env=env, errors="replace")


def _load_upgrade():
    spec = importlib.util.spec_from_file_location(
        "kunglao_upgrade_212", SCRIPTS / "kunglao_upgrade.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _current_stamp_line() -> str:
    sys.path.insert(0, str(SCRIPTS))
    import template_version
    return f"# {template_version.STAMP_KEY}: {template_version.read_skill_version()}"


@pytest.fixture
def fake_home(tmp_path, monkeypatch) -> Path:
    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    return home


# ===========================================================================
# 1. init FIRST step — statusLine registration (owner priority update)
# ===========================================================================

class TestInitFirstStepRegistration:
    def test_init_reports_statusline_and_registers_it(self, tmp_path):
        """Fresh init: the statusline is the FIRST STEP — its report leads
        the operator stream (stderr; stdout stays the machine channel) and
        <ws>/.claude/settings.json carries the statusLine entry."""
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        r = _run_init(ws)
        assert r.returncode == 0, r.stderr
        init_lines = [ln for ln in r.stderr.splitlines()
                      if ln.startswith("kunglao-init:")]
        assert init_lines, r.stderr
        sl_idx = next(i for i, ln in enumerate(init_lines)
                      if "statusline" in ln.lower())
        # the guard echo may precede; NO later-step line may (the statusline
        # deployment is the FIRST STEP — before toolchain, interview,
        # scaffold, wiring).
        later = ("project_type=", "initialized", "mcp ", "hooks ",
                 "task-oracle", "scaffold", "template_version")
        for ln in init_lines[:sl_idx]:
            assert not any(m in ln for m in later), \
                f"late-step line before the statusline report: {ln}"
        doc = json.loads((ws / ".claude" / "settings.json")
                         .read_text(encoding="utf-8"))
        entry = doc["statusLine"]
        assert entry["type"] == "command"
        assert entry["command"].startswith("node ")
        assert entry["command"].endswith("statusline_render.mjs")

    def test_registration_carries_timeout(self, tmp_path):
        """The statusLine entry pins a timeout (renderer must finish well
        under it — the legacy 19-min-tick class is exactly what it kills)."""
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        assert _run_init(ws).returncode == 0
        entry = json.loads((ws / ".claude" / "settings.json")
                           .read_text(encoding="utf-8"))["statusLine"]
        assert isinstance(entry.get("timeout"), int) and entry["timeout"] > 0

    def test_registration_idempotent_rerun_keeps_single_key(self, tmp_path):
        """Repeated init overwrites ONLY the kunglao-owned key (never
        duplicates, never stacks)."""
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        assert _run_init(ws).returncode == 0
        s1 = json.loads((ws / ".claude" / "settings.json").read_text(encoding="utf-8"))
        assert _run_init(ws).returncode == 0
        s2 = json.loads((ws / ".claude" / "settings.json").read_text(encoding="utf-8"))
        assert s2["statusLine"] == s1["statusLine"]
        assert json.dumps(s2).count("statusLine") == json.dumps(s1).count("statusLine")

    def test_no_hooks_opt_out_skips_registration(self, tmp_path):
        """--no-hooks is the documented opt-out: the engineering layer is
        skipped INCLUDING the statusline wiring."""
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        assert _run_init(ws, extra=["--no-hooks"]).returncode == 0
        settings = ws / ".claude" / "settings.json"
        doc = (json.loads(settings.read_text(encoding="utf-8"))
               if settings.exists() else {})
        assert "statusLine" not in doc


# ===========================================================================
# 2. data-plane deployment — the workspace copy the tick hook must invoke
# ===========================================================================

class TestDeployedDataPlane:
    def test_init_deploys_snapshot_script_with_manifest_sha(self, tmp_path):
        """Post-init, <ws>/.claude/scripts/statusline_snapshot.py exists and
        its bytes match the deploy-manifest sha256 (registration alone is
        NOT deployment)."""
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        assert _run_init(ws).returncode == 0
        deployed = ws / ".claude" / "scripts" / "statusline_snapshot.py"
        assert deployed.is_file(), "init must materialize the data plane"
        import deploy_manifest as dm
        manifest = yaml.safe_load(
            (ROOT / "deploy-manifest.yaml").read_text(encoding="utf-8"))
        entry = next(e for e in manifest["files"]
                     if e["dest"] == ".claude/scripts/statusline_snapshot.py")
        data = deployed.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        assert dm.observed_workspace_digest(ws, manifest["files"]) == \
            dm.manifest_digest(manifest["files"]), \
            "deployed closure must be byte-fresh after init"

    def test_heartbeat_tick_writes_snapshot(self, tmp_path):
        """One heartbeat tick -> <ws>/runs/.kunglao-statusline.json exists."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        r = _run_hook(ws)
        assert r.returncode == 0, r.stderr
        assert (ws / "runs" / ".kunglao-statusline.json").is_file()

    def test_tick_invokes_the_deployed_copy(self, tmp_path):
        """The tick hook must invoke the DEPLOYED data plane at
        <ws>/.claude/scripts/statusline_snapshot.py (workspace-relative),
        not the skill-root original — a sentinel deployed copy proves which
        module actually ran."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        scripts = ws / ".claude" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "statusline_snapshot.py").write_text(
            "from pathlib import Path\n"
            "def write_snapshot(ws, now=None):\n"
            "    marker = Path(ws) / 'runs' / '.sentinel-212'\n"
            "    marker.parent.mkdir(parents=True, exist_ok=True)\n"
            "    marker.write_text('deployed-copy-ran', encoding='utf-8')\n"
            "    return marker\n",
            encoding="utf-8")
        r = _run_hook(ws)
        assert r.returncode == 0, r.stderr
        assert (ws / "runs" / ".sentinel-212").is_file(), \
            "tick must invoke the DEPLOYED copy at <ws>/.claude/scripts/, " \
            "not the skill-root original"

    def test_tick_survives_a_broken_deployed_copy(self, tmp_path):
        """Degradation ladder: a deployed copy that fails to load falls back
        to the ambient import and the snapshot still lands (the statusline
        degrades — the heartbeat and the tick never do)."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        scripts = ws / ".claude" / "scripts"
        scripts.mkdir(parents=True)
        (scripts / "statusline_snapshot.py").write_text(
            "raise ImportError('simulated bare env: no yaml')\n",
            encoding="utf-8")
        r = _run_hook(ws)
        assert r.returncode == 0, r.stderr
        snap = ws / "runs" / ".kunglao-statusline.json"
        assert snap.is_file(), "snapshot must survive a broken deployed copy"
        body = json.loads(snap.read_text(encoding="utf-8"))
        assert body.get("schema") == 2


# ===========================================================================
# 3. minimal always-works path + crash-class immunity
# ===========================================================================

@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
class TestMinimalAlwaysWorks:
    def test_zero_analysis_data_still_renders_a_line(self, tmp_path):
        """Success/failure must be visible with ZERO analysis data: producer
        snapshot from a bare workspace -> renderer emits a non-empty state
        line (never a broken line, never no statusline)."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        sys.path.insert(0, str(SCRIPTS))
        import statusline_snapshot as sls
        sls.write_snapshot(ws)
        r = _run_renderer(ws)
        assert r.returncode == 0, r.stderr
        assert "ReferenceError" not in r.stderr
        out = ANSI_RE.sub("", r.stdout)
        assert out.strip(), "minimal heartbeat/status segment must render"
        assert any(s in out for s in ("idle", "analyzing", "DOWN", "stall")), out

    def test_legacy_crash_class_immune_on_data_poor_workspace(self, tmp_path):
        """FIELD DIAGNOSIS (issue 212): the legacy combined-statusline
        referenced an undefined field and exited with NOTHING on a workspace
        without rich data (no rl-signals, no ledger, no settlements). The
        repo renderer claims structural immunity — PROVE it: every optional
        snapshot field absent, only the state face present."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        sys.path.insert(0, str(SCRIPTS))
        import statusline_snapshot as sls
        sls.write_snapshot(ws)
        snap = json.loads((ws / "runs" / ".kunglao-statusline.json")
                          .read_text(encoding="utf-8"))
        for field in ("v_hist", "h_bits", "h_pq", "h_trend", "health", "now",
                      "pq_rows", "difficulty", "difficulty_src", "perf"):
            snap.pop(field, None)
        snap["pq"] = {}
        rich = ws / "runs" / "rl-signals.jsonl"
        assert not rich.exists(), "fixture must be data-poor"
        path = ws / "runs" / ".kunglao-statusline.json"
        path.write_text(json.dumps(snap), encoding="utf-8")
        r = _run_renderer(ws)
        assert r.returncode == 0, r.stderr
        assert "ReferenceError" not in r.stderr and not r.stderr.strip(), r.stderr
        out = ANSI_RE.sub("", r.stdout)
        assert out.strip(), "a data-poor workspace still gets a live line"

    def test_no_color_ascii_fallback(self, tmp_path):
        """Graceful degradation extends to the TERMINAL: NO_COLOR renders the
        same readable line with zero ANSI escapes."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        sys.path.insert(0, str(SCRIPTS))
        import statusline_snapshot as sls
        sls.write_snapshot(ws)
        for env in ({"NO_COLOR": "1"}, {"TERM": "dumb"}):
            r = _run_renderer(ws, env_extra=env)
            assert r.returncode == 0, r.stderr
            assert "\x1b[" not in r.stdout, \
                f"color-off env {env} must render plain text"
            assert any(s in r.stdout for s in ("idle", "analyzing", "DOWN")), r.stdout

    def test_renderer_end_to_end_latency(self, tmp_path):
        """Perf budget (owner reference pattern): renderer < 50ms target
        end-to-end. CI-safe hard ceiling asserted; the measured value is the
        report surface."""
        import time as _t
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        sys.path.insert(0, str(SCRIPTS))
        import statusline_snapshot as sls
        sls.write_snapshot(ws)
        timings = []
        for _ in range(5):
            t0 = _t.perf_counter()
            r = _run_renderer(ws)
            timings.append((_t.perf_counter() - t0) * 1000)
            assert r.returncode == 0, r.stderr
        best = min(timings)
        assert best < 500, f"renderer best-of-5 {best:.0f}ms exceeds CI ceiling"
        print(f"\n#212 renderer end-to-end: best={best:.0f}ms "
              f"(runs={[f'{t:.0f}' for t in timings]}; budget target 50ms)")


# ===========================================================================
# 4. data plane — difficulty + perf faces
# ===========================================================================

class TestDataPlaneFaces:
    def test_difficulty_face_from_calibration_output(self, tmp_path):
        """Calibrated tier (evidence/difficulty.json — the calibration
        surface's mounted output) rides the snapshot as a face."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        (ws / "evidence").mkdir()
        (ws / "evidence" / "difficulty.json").write_text(
            json.dumps({"tier": "hard"}), encoding="utf-8")
        sys.path.insert(0, str(SCRIPTS))
        import statusline_snapshot as sls
        snap = sls.build_snapshot(ws)
        face = snap["difficulty_src"]
        assert isinstance(face, dict) and face.get("tier") == "hard"
        assert face.get("source") == "calibrated"
        assert snap["difficulty"] == "hard"  # legacy string key unchanged

    def test_difficulty_face_raw_signals_when_not_mounted(self, tmp_path):
        """No mounted tier: the calibration surface consumes the raw
        evidence (apkid signals) — reused, never re-derived."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        (ws / "evidence").mkdir()
        (ws / "evidence" / "apkid.json").write_text(json.dumps({
            "status": "ok",
            "summary": {"packer": ["Upx"], "obfuscator": ["ObfA"],
                        "anti_debug": ["Ptrace"], "anti_vm": ["Qemu"]},
        }), encoding="utf-8")
        sys.path.insert(0, str(SCRIPTS))
        import statusline_snapshot as sls
        snap = sls.build_snapshot(ws)
        face = snap["difficulty_src"]
        assert isinstance(face, dict)
        assert face.get("source") == "raw-signals"
        assert face.get("tier") or face.get("score") is not None

    def test_difficulty_absent_is_none(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        sys.path.insert(0, str(SCRIPTS))
        import statusline_snapshot as sls
        snap = sls.build_snapshot(ws)
        assert snap["difficulty_src"] is None

    def test_perf_face_claims_winrate_workers(self, tmp_path):
        """Perf face: claims closed/total (live ledger), rolling win-rate
        (settlement stream), heartbeat age, worker liveness."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        (ws / "claim-register.yaml").write_text(
            "claims:\n"
            "  - id: C-1\n    status: PROVEN\n"
            "  - id: C-2\n    status: OPEN\n"
            "  - id: C-3\n    status: PROVEN\n",
            encoding="utf-8")
        sets = ws / "runs" / "roi-settlements.jsonl"
        rows = [
            {"ts": "2026-01-01T00:00:01Z", "claim_id": "C-1",
             "method": "static", "roi_class": "POSITIVE"},
            {"ts": "2026-01-01T00:00:02Z", "claim_id": "C-2",
             "method": "dynamic", "roi_class": "NEGATIVE"},
            {"ts": "2026-01-01T00:00:03Z", "claim_id": "C-3",
             "method": "static", "roi_class": "POSITIVE"},
        ]
        sets.write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                        encoding="utf-8")
        from _factories import write_worker_status
        write_worker_status(ws, "w1", "in-progress")  # issue 915 protocol shape
        sys.path.insert(0, str(SCRIPTS))
        import statusline_snapshot as sls
        snap = sls.build_snapshot(ws)
        perf = snap["perf"]
        assert perf["claims"] == {"closed": 2, "total": 3}
        assert perf["win_rate"] is not None and 0 < perf["win_rate"] <= 1
        assert perf["heartbeat_age_min"] is not None
        assert perf["workers"]["total"] >= 1

    def test_progress_tracks_the_live_ledger(self, tmp_path):
        """The denominator is LIVE (owner correction): claims registered
        between ticks grow N; closed is monotonic; total non-decreasing.
        The init baseline is a starting point, never a cap."""
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        sys.path.insert(0, str(SCRIPTS))
        import statusline_snapshot as sls
        reg = ws / "claim-register.yaml"
        reg.write_text(
            "claims:\n"
            "  - id: C-1\n    status: PROVEN\n"
            "  - id: C-2\n    status: PROVEN\n"
            "  - id: C-3\n    status: OPEN\n", encoding="utf-8")
        s1 = sls.build_snapshot(ws)
        assert s1["perf"]["claims"] == {"closed": 2, "total": 3}
        reg.write_text(
            "claims:\n"
            "  - id: C-1\n    status: PROVEN\n"
            "  - id: C-2\n    status: PROVEN\n"
            "  - id: C-3\n    status: OPEN\n"
            "  - id: C-4\n    status: OPEN\n"
            "  - id: C-5\n    status: PROVEN\n", encoding="utf-8")
        s2 = sls.build_snapshot(ws)
        assert s2["perf"]["claims"]["total"] == 5, "N must grow with the ledger"
        assert s2["perf"]["claims"]["closed"] == 3
        assert s2["perf"]["claims"]["closed"] >= s1["perf"]["claims"]["closed"]
        assert s2["perf"]["claims"]["total"] >= s1["perf"]["claims"]["total"]

    def test_perf_face_fail_open_on_garbage(self, tmp_path):
        ws = _make_ws(tmp_path)
        _touch_heartbeat(ws)
        (ws / "runs" / "roi-settlements.jsonl").write_text(
            "not json at all\n", encoding="utf-8")
        sys.path.insert(0, str(SCRIPTS))
        import statusline_snapshot as sls
        snap = sls.build_snapshot(ws)  # never raises
        assert snap["perf"]["claims"]["total"] == 0
        assert snap["perf"]["win_rate"] is None


# ===========================================================================
# 5. init baseline — mission ledger + seed claims closed
# ===========================================================================

class TestInitBaselines:
    def test_init_seeds_mission_ledger_baseline(self, tmp_path):
        """FIELD DIAGNOSIS: the progress segment rendered nothing because
        runs/mission_ledger.yaml was never initialized. Init must seed the
        ledger so a real 0/N baseline exists from tick one."""
        ws = tmp_path / "ws"
        seed_bins(ws)
        seed_oracle_anchors(ws)
        (ws / "task_spec.yaml").write_text(
            "goal_verbatim: legacy goal\n"
            "success_criterion: legacy criterion\n"
            "verification_method: manual\n"
            "primary_questions:\n"
            "  PQ-1: what does the sample do?\n"
            "  PQ-2: where is the decoder?\n", encoding="utf-8")
        (ws / "runs").mkdir()
        assert _run_init(ws, anchors=False).returncode == 0
        led = yaml.safe_load((ws / "runs" / "mission_ledger.yaml")
                             .read_text(encoding="utf-8"))
        pqs = led["mission"]["pqs"]
        assert len(pqs) == 2
        assert all(p["state"] == "unattempted" for p in pqs)

    def test_ledger_seeding_idempotent(self, tmp_path):
        """Re-init (resume/force) never crashes on the existing ledger and
        never duplicates it."""
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        assert _run_init(ws).returncode == 0
        assert _run_init(ws).returncode == 0

    def test_init_closes_seed_claims_proven(self, tmp_path):
        """FIELD DIAGNOSIS: the state segment lied "analyzing" forever — the
        scaffold seed claims stayed OPEN although init verified them by
        construction. Init must close C-001..C-003 PROVEN with evidence."""
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        assert _run_init(ws).returncode == 0
        reg = yaml.safe_load((ws / "claim-register.yaml")
                             .read_text(encoding="utf-8"))
        seeds = {c["id"]: c for c in reg["claims"]}
        for sid in ("C-001", "C-002", "C-003"):
            assert seeds[sid]["status"] == "PROVEN", \
                f"{sid} must be closed by init (got {seeds[sid]['status']})"
            assert seeds[sid].get("evidence"), f"{sid} must carry its evidence"

    def test_seeds_closed_state_is_not_analyzing(self, tmp_path):
        """With the seeds closed, the statusline state computed from a fresh
        workspace falls through to the truthful idle face — never a lying
        "analyzing"."""
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        assert _run_init(ws).returncode == 0
        _touch_heartbeat(ws)
        # init's own event emissions sit in the toss window (dispatch rows
        # <= 120s); drop the ledger so the state machine judges the steady
        # state (no recent events) rather than init's own just-written rows.
        import shutil as _shutil
        logs = ws / "runs" / "logs"
        if logs.is_dir():
            _shutil.rmtree(logs)
        sys.path.insert(0, str(SCRIPTS))
        import statusline_snapshot as sls
        snap = sls.build_snapshot(ws)
        assert snap["state"] != "analyzing"
        assert snap["state"] == "idle"

    def test_upgrade_does_not_reopen_seeds(self, tmp_path, fake_home):
        ws = tmp_path / "ws"
        seed_bins(ws)
        (ws / "runs").mkdir()
        assert _run_init(ws).returncode == 0
        up = _load_upgrade()
        assert up.main([str(ws), "--json"]) == 0
        reg = yaml.safe_load((ws / "claim-register.yaml")
                             .read_text(encoding="utf-8"))
        assert all(c["status"] == "PROVEN" for c in reg["claims"])


# ===========================================================================
# 6. renderer render plane — difficulty badge + perf segments
# ===========================================================================

@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
class TestRenderPlaneSegments:
    def _snap(self, ws: Path, **overrides) -> None:
        _touch_heartbeat(ws)
        sys.path.insert(0, str(SCRIPTS))
        import statusline_snapshot as sls
        sls.write_snapshot(ws)
        path = ws / "runs" / ".kunglao-statusline.json"
        snap = json.loads(path.read_text(encoding="utf-8"))
        snap.update(overrides)
        path.write_text(json.dumps(snap), encoding="utf-8")

    def test_difficulty_badge_renders_when_present(self, tmp_path):
        ws = _make_ws(tmp_path)
        self._snap(ws, difficulty="hard",
                   difficulty_src={"tier": "hard", "score": 0.62,
                                   "source": "calibrated"})
        r = _run_renderer(ws)
        assert r.returncode == 0, r.stderr
        assert "D:hard" in ANSI_RE.sub("", r.stdout)

    def test_difficulty_badge_hidden_when_absent(self, tmp_path):
        ws = _make_ws(tmp_path)
        self._snap(ws, difficulty=None, difficulty_src=None)
        r = _run_renderer(ws)
        assert r.returncode == 0
        assert "D:" not in ANSI_RE.sub("", r.stdout)

    def test_perf_segments_render_when_present(self, tmp_path):
        ws = _make_ws(tmp_path)
        self._snap(
            ws,
            perf={"claims": {"closed": 3, "total": 8}, "win_rate": 0.67,
                  "heartbeat_age_min": 0.1,
                  "workers": {"total": 2, "active": 1,
                              "last_activity_age_s": 12.0}})
        r = _run_renderer(ws)
        assert r.returncode == 0, r.stderr
        out = ANSI_RE.sub("", r.stdout)
        assert "C3/8" in out, "claims progress (closed/total) must render"
        assert "W67%" in out, "rolling win-rate must render"
        assert re.search(r"\bw1/2\b", out), "worker liveness must render"

    def test_perf_segments_hidden_when_absent(self, tmp_path):
        ws = _make_ws(tmp_path)
        self._snap(ws, perf=None)
        r = _run_renderer(ws)
        assert r.returncode == 0
        out = ANSI_RE.sub("", r.stdout)
        assert not re.search(r"W\d", out), "win-rate segment must hide"
        assert not re.search(r"\bC\d+/\d+\b", out), "claims segment must hide"
        assert not re.search(r"\bw\d/\d\b", out), "worker segment must hide"

    def test_all_segments_absent_minimal_line_valid(self, tmp_path):
        ws = _make_ws(tmp_path)
        self._snap(ws, perf=None, difficulty=None, difficulty_src=None,
                   v_hist=[], h_bits=None, now={"claim": None, "op": None},
                   health=None, pq={})
        r = _run_renderer(ws)
        assert r.returncode == 0, r.stderr
        out = ANSI_RE.sub("", r.stdout).strip()
        assert out, "minimal line must survive every segment absent"
        assert "idle" in out or "analyzing" in out


# ===========================================================================
# 7. upgrade — re-verify + self-heal, FIRST line of output
# ===========================================================================

def _current_ws(tmp_path: Path) -> Path:
    """An already-current workspace (upgrade fast path) with a live
    registration removed by the caller."""
    ws = _make_ws(tmp_path)
    stamp = _current_stamp_line()
    (ws / "CLAUDE.md").write_text(stamp + "\n# ws\n", encoding="utf-8")
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(stamp + "\n# facts\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        stamp + "\nclaims: []\n# [initialized] 2026-09-01\n", encoding="utf-8")
    (ws / "task_spec.yaml").write_text(
        "goal_verbatim: g\nsuccess_criterion: c\nverification_method: manual\n",
        encoding="utf-8")
    scripts = ws / ".claude" / "scripts"
    scripts.mkdir(parents=True)
    shutil.copy2(RENDERER, scripts / "statusline_render.mjs")
    return ws


class TestUpgradeSelfHeal:
    def test_removed_registration_restored_and_reported_first(self, tmp_path,
                                                              fake_home,
                                                              capsys):
        """UPGRADE re-verifies the registration on every run (self-heal if
        removed) and reports it as the FIRST line of upgrade output."""
        ws = _current_ws(tmp_path)
        up = _load_upgrade()
        from hook_activation import register_statusline
        assert register_statusline(ws)["ok"]
        settings = ws / ".claude" / "settings.json"
        doc = json.loads(settings.read_text(encoding="utf-8"))
        doc.pop("statusLine")
        settings.write_text(json.dumps(doc), encoding="utf-8")
        rc = up.main([str(ws), "--json"])
        assert rc == 0
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert lines, "upgrade must produce output"
        assert "statusline" in lines[0].lower(), \
            f"statusline check must be the FIRST upgrade line, got: {lines[0]}"
        doc = json.loads(settings.read_text(encoding="utf-8"))
        assert "statusline_render.mjs" in doc["statusLine"]["command"], \
            "removed registration must be self-healed"

    def test_ok_registration_reported_not_rewritten(self, tmp_path, fake_home,
                                                    capsys):
        ws = _current_ws(tmp_path)
        up = _load_upgrade()
        from hook_activation import register_statusline
        assert register_statusline(ws)["ok"]
        settings = ws / ".claude" / "settings.json"
        before = settings.read_text(encoding="utf-8")
        assert up.main([str(ws), "--json"]) == 0
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert "statusline" in lines[0].lower()
        assert "ok" in lines[0].lower()
        assert settings.read_text(encoding="utf-8") == before, \
            "a valid registration must be left byte-identical"

    def test_dry_run_reports_without_writing(self, tmp_path, fake_home,
                                             capsys):
        ws = _current_ws(tmp_path)
        up = _load_upgrade()
        rc = up.main([str(ws), "--dry-run", "--json"])
        assert rc == 0
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert "statusline" in lines[0].lower()
        assert not (ws / ".claude" / "settings.json").exists(), \
            "dry run must write nothing"

    def test_unknown_origin_refused_reports_statusline_first(self, tmp_path,
                                                             fake_home,
                                                             capsys):
        ws = _make_ws(tmp_path)  # no version stamp
        up = _load_upgrade()
        rc = up.main([str(ws), "--json"])
        assert rc == 3  # RC_UNKNOWN_ORIGIN
        lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
        assert lines and "statusline" in lines[0].lower()
        assert not (ws / ".claude" / "settings.json").exists(), \
            "a refused run writes nothing"

    def test_selfheal_recorded_in_items(self, tmp_path, fake_home, capsys):
        ws = _current_ws(tmp_path)
        up = _load_upgrade()
        assert up.main([str(ws), "--json"]) == 0
        out = capsys.readouterr().out
        envelope = json.loads([ln for ln in out.splitlines() if ln.strip()][-1])
        names = [i.get("name") for i in envelope.get("items") or []]
        assert any("statusline" in str(n) for n in names), \
            f"self-heal must be recorded as an item: {names}"
