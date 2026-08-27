# -*- coding: utf-8 -*-
"""tests/test_heartbeat_autonomy_754.py — issue #754 心跳自治.

RED contracts (live-run field incident): last_tick_ts == started_ts for the
whole session life (the cron never existed), CronList empty, no
scheduled_tasks.json — yet check_heartbeat_alive passed inside its 35-min
window because ONE registration tick was enough to claim liveness. Three
fixes, one suite:

  T1 (E2) continuous-tick liveness — evaluate_tick_continuity shared by the
      dispatch gate / --heartbeat-check / --verify (#609): >=2 ticks,
      adjacent gap <= 2*interval_min, latest <= 35min. Legacy single-tick
      files REJECT (strict adjudication: the 35-min blind spot IS the bug).
  T2 (E1) durable cron path — loop_scheduler.upsert_durable_loop writes
      <ws>/.claude/scheduled_tasks.json; init handoff self-registers
      (#593 red line precise semantics: writing the SCHEDULER registry is
      not faking loop_registered — the heartbeat file stays untouched until
      the /loop prompt body really executes).
  T3 (E3) verify wired into the analysis entry — kunglao.py analysis:
      stale gate -> durable reconcile -> verify_loop; failure maps to a
      stderr re-arm hint + rc=6.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))



def _load_init(name: str):
    """Load kunglao-init.py by path (CLI module; heavy imports kept lazy)."""
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

import heartbeat as hb_mod  # noqa: E402
import heartbeat_loop_prompt as hlp  # noqa: E402
import hook_activation as ha  # noqa: E402


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def _ago(minutes: float) -> str:
    return _iso(datetime.now(timezone.utc) - timedelta(minutes=minutes))


def _write_hb(ws: Path, state: dict) -> Path:
    runs = ws / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    p = runs / ".heartbeat.json"
    p.write_text(json.dumps(state), encoding="utf-8")
    return p


def _loop_state(*, ticks: list[str], registered: bool = True,
                interval_min: int = 5) -> dict:
    st = {"started_ts": ticks[0] if ticks else _ago(0),
          "interval_min": interval_min,
          "last_tick_ts": ticks[-1] if ticks else None,
          "loop_registered": registered}
    if ticks:
        st["tick_history"] = list(ticks)
    return {k: v for k, v in st.items() if v is not None}


# ===========================================================================
# T1 — continuous-tick liveness (#754 E2)
# ===========================================================================

class TestEvaluateTickContinuity:
    def test_single_fresh_tick_rejected(self):
        """THE blind spot: one very fresh registration tick is NOT alive."""
        alive, detail = hb_mod.evaluate_tick_continuity(
            _loop_state(ticks=[_ago(1)]))
        assert alive is False
        assert "second" in detail.lower() or "single" in detail.lower(), detail

    def test_double_tick_regular_interval_alive(self):
        now = datetime.now(timezone.utc)
        ticks = [_iso(now - timedelta(minutes=6)), _iso(now - timedelta(minutes=1))]
        alive, detail = hb_mod.evaluate_tick_continuity(_loop_state(ticks=ticks))
        assert alive is True, detail

    def test_gap_over_double_interval_rejected(self):
        """Two ticks, but the cadence broke (> 2x interval_min) — a live cron
        cannot produce that shape."""
        now = datetime.now(timezone.utc)
        ticks = [_iso(now - timedelta(minutes=20)), _iso(now - timedelta(minutes=1))]
        alive, detail = hb_mod.evaluate_tick_continuity(_loop_state(ticks=ticks))
        assert alive is False
        assert "gap" in detail.lower() or "cadence" in detail.lower(), detail

    def test_stale_last_tick_rejected(self):
        from liveness_policy import STALE_MINUTES
        old = datetime.now(timezone.utc) - timedelta(minutes=STALE_MINUTES + 10)
        ticks = [_iso(old - timedelta(minutes=5)), _iso(old)]
        alive, detail = hb_mod.evaluate_tick_continuity(_loop_state(ticks=ticks))
        assert alive is False
        assert "stale" in detail.lower(), detail

    def test_legacy_file_without_history_rejected_strict(self):
        """裁决：直接严格。The live-run incident file SHAPE (no tick_history)
        rejects even though last_tick_ts is brand fresh."""
        state = {"started_ts": _ago(0), "interval_min": 5,
                 "last_tick_ts": _ago(0), "loop_registered": True}
        alive, detail = hb_mod.evaluate_tick_continuity(state)
        assert alive is False
        assert "tick_history" in detail, (
            "detail must teach building the history (run one touch/tick)")
        assert "touch" in detail.lower(), detail

    def test_nan_inf_interval_falls_back_to_default(self):
        """r1-F1: a tampered interval_min must never disable the gap bound
        (NaN comparisons are False -> no cadence check at all) nor crash."""
        now = datetime.now(timezone.utc)
        ticks = [_iso(now - timedelta(minutes=60)), _iso(now - timedelta(minutes=1))]
        st = _loop_state(ticks=ticks, interval_min=5)
        st["interval_min"] = float("nan")
        alive, detail = hb_mod.evaluate_tick_continuity(st)
        assert alive is False and "GAP" in detail.upper()
        st["interval_min"] = float("inf")
        assert hb_mod.evaluate_tick_continuity(st)[0] is False

    def test_non_dict_state_fails_closed_not_crash(self):
        """r1-F1: list/int/None state REJECTs with the unreadable teaching,
        it never raises through the dispatch-gate pre_check."""
        for bad in ([1, 2], 42, None, "x"):
            alive, detail = hb_mod.evaluate_tick_continuity(bad)
            assert alive is False
            assert "unreadable" in detail

    def test_empty_or_corrupt_history_fails_closed(self):
        state = _loop_state(ticks=[_ago(1)])
        state["tick_history"] = ["not-a-ts"]
        alive, detail = hb_mod.evaluate_tick_continuity(state)
        assert alive is False
        state2 = _loop_state(ticks=[_ago(1)])
        state2["tick_history"] = []
        assert hb_mod.evaluate_tick_continuity(state2)[0] is False


class TestAppendTickAndWriters:
    def test_append_returns_new_dict_and_caps_at_12(self, tmp_path):
        # minutes :24..:59 -> all inside the 35-min window of the append moment
        base = [f"2026-08-26T00:{m:02d}:00Z" for m in range(24, 24)]
        del base
        import datetime as _dtm
        moment = _dtm.datetime(2026, 8, 26, 0, 59, tzinfo=_dtm.timezone.utc)
        base = [_iso(moment - _dtm.timedelta(minutes=m)) for m in range(30, 0, -1)]
        state = {"last_tick_ts": base[-1], "tick_history": list(base)}
        out = hb_mod.append_tick(dict(state), now=moment)
        hist = out["tick_history"]
        assert len(hist) == hb_mod.TICK_HISTORY_CAP == 12
        assert hist[-1] == "2026-08-26T00:59:00Z"
        # immutability: input untouched (30 entries still there)
        assert len(state["tick_history"]) == 30 and state["tick_history"][0] == base[0]

    def test_append_prunes_out_of_window_entries(self, tmp_path):
        """A tick appended >35min after the last one starts a NEW lifetime:
        ancient entries are pruned so the evaluator never sees fake continuity."""
        import datetime as _dtm
        moment = _dtm.datetime(2026, 8, 26, 3, 0, tzinfo=_dtm.timezone.utc)
        old_pairs = ["2026-08-26T00:00:00Z", "2026-08-26T00:05:00Z"]
        out = hb_mod.append_tick({"tick_history": list(old_pairs)}, now=moment)
        assert out["tick_history"] == ["2026-08-26T03:00:00Z"]

    def test_register_seeds_one_entry_history(self, tmp_path):
        ws = tmp_path
        rc = hb_mod.heartbeat_register(ws)
        assert rc == 0
        data = json.loads((ws / "runs" / ".heartbeat.json").read_text())
        assert data[hb_mod.TICK_HISTORY_KEY]
        assert data["loop_registered"] is False

    def test_register_preserves_proven_marker_and_resets_history_window(
            self, tmp_path):
        ws = tmp_path
        hb_mod.heartbeat_register(ws)
        hb_mod.mark_loop_registered(ws)
        hb_mod.heartbeat_register(ws)  # re-register mid-flight
        data = json.loads((ws / "runs" / ".heartbeat.json").read_text())
        assert data["loop_registered"] is True
        # one fresh entry, NOT polluted by the pre-marker history
        assert len(data["tick_history"]) == 1

    def test_renew_appends_a_tick(self, tmp_path):
        ws = tmp_path
        hb_mod.heartbeat_register(ws)
        ha.update_state(ws, "none", "IDLE")   # active session state first:
        # renew() over cold state bootstraps .hook_state.json and returns
        # before the heartbeat block — the tick path always has live state.
        before = json.loads((ws / "runs" / ".heartbeat.json").read_text())
        assert len(before["tick_history"]) == 1
        ha.renew(ws)
        after = json.loads((ws / "runs" / ".heartbeat.json").read_text())
        assert len(after["tick_history"]) == 2
        assert after["last_tick_ts"] >= before["last_tick_ts"]

    def test_heartbeat_touch_preserves_state_and_appends(self, tmp_path, capsys):
        """scripts/heartbeat_touch.py used to OVERWRITE the whole file
        (losing last_tick_ts/loop_registered/#754 history) — now it merges."""
        ws = tmp_path
        hb_mod.heartbeat_register(ws)
        hb_mod.mark_loop_registered(ws)
        touch = ROOT / "scripts" / "heartbeat_touch.py"
        r = subprocess.run([sys.executable, str(touch), str(ws)],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60)
        assert r.returncode == 0, r.stderr
        data = json.loads((ws / "runs" / ".heartbeat.json").read_text())
        assert data.get("loop_registered") is True, "touch must not erase marker"
        assert data.get("interval_min") == 5, "touch must not erase fields"
        assert len(data["tick_history"]) == 2

    def test_dispatch_gate_single_tick_blind_spot_removed(self, tmp_path):
        """Acceptance: 单 tick fixture → check_heartbeat_alive REJECT."""
        import worker_budget as wb
        ws = tmp_path
        _write_hb(ws, {"started_ts": _ago(0), "interval_min": 5,
                       "last_tick_ts": _ago(0), "activity_ts": _ago(0),
                       "loop_registered": True})
        state_path = ws / "analysis_state.txt"
        state_path.write_text("{}", encoding="utf-8")
        alive, msg = wb.check_heartbeat_alive(state_path)
        assert alive is False, f"blind spot still open: {msg}"
        assert ("second" in msg.lower()) or ("single" in msg.lower()), msg

    def test_dispatch_gate_two_clean_ticks_pass(self, tmp_path):
        import worker_budget as wb
        ws = tmp_path
        _write_hb(ws, _loop_state(ticks=[_ago(6), _ago(1)]))
        state_path = ws / "analysis_state.txt"
        state_path.write_text("{}", encoding="utf-8")
        alive, msg = wb.check_heartbeat_alive(state_path)
        assert alive is True, msg

    def test_heartbeat_check_cli_shares_standard(self, tmp_path, capsys):
        rc = hb_mod.heartbeat_check.__wrapped__(tmp_path) if hasattr(
            hb_mod.heartbeat_check, "__wrapped__") else hb_mod.heartbeat_check(tmp_path)
        assert rc == 1  # no file at all
        _write_hb(tmp_path, _loop_state(ticks=[_ago(1)]))
        capsys.readouterr()
        assert hb_mod.heartbeat_check(tmp_path) == 1
        err = capsys.readouterr().err
        assert "second" in err.lower() or "single" in err.lower() or \
            "tick_history" in err
        _write_hb(tmp_path, _loop_state(ticks=[_ago(6), _ago(1)]))
        capsys.readouterr()
        assert hb_mod.heartbeat_check(tmp_path) == 0


class TestVerifySameStandard609:
    def test_verify_single_fresh_registered_tick_now_fails(self, tmp_path, capsys):
        """--verify uses the SAME continuity standard as the dispatch gate:
        marker true + one fresh tick (the old #609 pass case) is no longer OK."""
        _write_hb(tmp_path, _loop_state(ticks=[_ago(1)]))
        assert hlp.verify_loop(str(tmp_path)) == 1
        assert "NOT TICKING" in capsys.readouterr().err

    def test_verify_two_clean_ticks_ok(self, tmp_path, capsys):
        _write_hb(tmp_path, _loop_state(ticks=[_ago(6), _ago(1)]))
        assert hlp.verify_loop(str(tmp_path)) == 0
        assert "OK" in capsys.readouterr().out

    def test_verify_cadence_broken_fails(self, tmp_path, capsys):
        now = datetime.now(timezone.utc)
        ticks = [_iso(now - timedelta(minutes=25)), _iso(now - timedelta(minutes=1))]
        _write_hb(tmp_path, _loop_state(ticks=ticks))
        assert hlp.verify_loop(str(tmp_path)) == 1
        assert "NOT TICKING" in capsys.readouterr().err


# ===========================================================================
# T2 — durable cron path (#754 E1, absorbs #616 discussion)
# ===========================================================================

class TestDurableLoopScheduler:
    def _ws(self, tmp_path: Path, name: str = "ws") -> Path:
        ws = tmp_path / name
        ws.mkdir(exist_ok=True)
        return ws

    def test_init_handoff_writes_durable_scheduled_tasks(self, tmp_path, capsys):
        """Acceptance: init 后 scheduled_tasks.json 含 loop 条目（durable）.
        emit_activation_handoff is init's last-step integration point."""
        mod = _load_init("kunglao_init_754")
        ws = self._ws(tmp_path)
        (ws / "runs").mkdir(parents=True)
        rc = mod.emit_activation_handoff(ws)
        assert rc == 0
        out = capsys.readouterr().out
        sched = ws / ".claude" / "scheduled_tasks.json"
        assert sched.exists(), f"durable schedule missing after handoff: {out}"
        jobs = json.loads(sched.read_text(encoding="utf-8"))
        entries = jobs["jobs"] if isinstance(jobs, dict) else jobs
        mine = [e for e in entries if e.get("id") == "kunglao-heartbeat"]
        assert len(mine) == 1
        entry = mine[0]
        assert entry.get("durable") is True
        assert entry.get("cron") == "*/5 * * * *"
        assert "--heartbeat-on" in entry.get("prompt", "")
        assert "durable" in out.lower() or "已注册 durable" in out
        assert "7" in out, "must mention the 7-day Claude Code expiry cap"

    def test_red_lines_intact_after_scheduler_write(self, tmp_path):
        """#593 precise semantics: scheduler registry write != faking ticks.
        Mirrors the real init order — bootstrap registers the heartbeat,
        THEN the handoff upserts the durable schedule."""
        mod = _load_init("kunglao_init_754b")
        ws = self._ws(tmp_path)
        (ws / "runs").mkdir(parents=True)
        hb_mod.heartbeat_register(ws)           # init's own step (bootstrap)
        mod.emit_activation_handoff(ws)          # + scheduler upsert inside
        hb_data = json.loads((ws / "runs" / ".heartbeat.json").read_text())
        assert hb_data.get("loop_registered") is not True, (
            "#593/#754: writing .claude/scheduled_tasks.json must never flip "
            "the tick-evidence marker")
        assert len(hb_data.get("tick_history", [])) == 1, (
            "scheduler write must not append fake tick history")
        assert not (ws / ".hook_state.json").exists()

    def test_upsert_idempotent_and_preserves_foreign_entries(self, tmp_path):
        import loop_scheduler as ls
        ws = self._ws(tmp_path)
        assert ls.loop_entry_exists(ws) is False
        foreign = [{"id": "someone-else", "cron": "0 * * * *",
                    "prompt": "hello", "durable": True}]
        sched = ls.scheduled_tasks_path(ws)
        sched.parent.mkdir(parents=True, exist_ok=True)
        sched.write_text(json.dumps({"jobs": foreign}), encoding="utf-8")
        assert ls.upsert_durable_loop(ws) == 0
        jobs = json.loads(sched.read_text())["jobs"]
        ids = [j["id"] for j in jobs]
        assert ids.count("kunglao-heartbeat") == 1
        assert ids.count("someone-else") == 1
        first_prompt = [j for j in jobs if j["id"] == "kunglao-heartbeat"][0]["prompt"]
        # idempotent: second run replaces, never stacks
        assert ls.upsert_durable_loop(ws) == 0
        jobs2 = json.loads(sched.read_text())["jobs"]
        ids2 = [j["id"] for j in jobs2]
        assert ids2.count("kunglao-heartbeat") == 1
        assert ids2.count("someone-else") == 1
        mine2 = [j for j in jobs2 if j["id"] == "kunglao-heartbeat"][0]
        assert mine2["prompt"] == first_prompt
        assert ls.loop_entry_exists(ws) is True

    def test_corrupt_schedule_backed_up_not_clobbered_silently(self, tmp_path):
        import loop_scheduler as ls
        ws = self._ws(tmp_path)
        sched = ls.scheduled_tasks_path(ws)
        sched.parent.mkdir(parents=True, exist_ok=True)
        sched.write_text("{not json", encoding="utf-8")
        assert ls.upsert_durable_loop(ws) == 0
        backups = list(sched.parent.glob("scheduled_tasks.json.corrupt*"))
        assert backups, "corrupt prior content must be preserved side-by-side"
        assert backups[0].read_text() == "{not json"

    def test_unrecognized_but_valid_shape_backed_up(self, tmp_path):
        """r3-M1: valid JSON our reader does not understand (schedules key,
        sibling keys beside jobs) must survive a rebuild byte-for-byte."""
        import loop_scheduler as ls
        ws = self._ws(tmp_path)
        sched = ls.scheduled_tasks_path(ws)
        sched.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps({"schemaVersion": 9,
                          "jobs": [{"id": "foreign", "prompt": "x"}]})
        sched.write_text(raw, encoding="utf-8")
        assert ls.upsert_durable_loop(ws) == 0
        sidecars = list(sched.parent.glob("scheduled_tasks.json.unrecognized-*"))
        assert sidecars and sidecars[0].read_text() == raw
        # foreign JOB entry itself still survives inside the rewrite
        entries = json.loads(sched.read_text())["jobs"]
        assert any(e.get("id") == "foreign" for e in entries)
        assert any(e.get("id") == ls.JOB_ID for e in entries)
        # {"schedules": ...} (no jobs key) -> whole file preserved, ours added
        other = self._ws(tmp_path, "ws-schedules-shape")
        op = ls.scheduled_tasks_path(other)
        op.parent.mkdir(parents=True, exist_ok=True)
        raw2 = json.dumps({"schedules": [{"weird": True}]})
        op.write_text(raw2, encoding="utf-8")
        assert ls.upsert_durable_loop(other) == 0
        assert list(op.parent.glob("*.unrecognized-*"))[0].read_text() == raw2
        assert ls.loop_entry_exists(other) is True

    def test_bom_file_not_treated_as_corrupt(self, tmp_path):
        import loop_scheduler as ls
        ws = self._ws(tmp_path)
        sched = ls.scheduled_tasks_path(ws)
        sched.parent.mkdir(parents=True, exist_ok=True)
        sched.write_bytes(
            b"\xef\xbb\xbf" + json.dumps([{"id": "plain"}]).encode())
        assert ls.upsert_durable_loop(ws) == 0
        assert not list(sched.parent.glob("*.corrupt-*"))
        ids = [e["id"] for e in json.loads(sched.read_text())]
        assert ids.count(ls.JOB_ID) == 1

    def test_cron_expression_rejects_unclean_steps(self, tmp_path):
        import loop_scheduler as ls
        assert ls.interval_to_cron("5m") == "*/5 * * * *"
        for bad in ("48h", "25h", "0m"):
            try:
                ls.interval_to_cron(bad)
                ok = False
            except ValueError:
                ok = True
            assert ok, f"{bad} must refuse an unclean cron step"
        assert ls.interval_to_cron("120m") == "0 */2 * * *"

    def test_no_hooks_bootstrap_skips_scheduler_write(self, tmp_path):
        mod = _load_init("kunglao_init_754c")
        ws = self._ws(tmp_path)
        (ws / "runs").mkdir(parents=True)
        assert mod.bootstrap_observability(ws, no_hooks=True) == 0
        assert not (ws / ".claude" / "scheduled_tasks.json").exists()
        assert not (ws / "runs" / ".heartbeat.json").exists()


# ===========================================================================
# T3 — verify wired into the analysis entry (#754 E3)
# ===========================================================================

KUNGLAO_PY = ROOT / "scripts" / "kunglao.py"


def _stamped_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "aws"
    ws.mkdir(parents=True)
    (ws / "CLAUDE.md").write_text("# kunglao_template_version: 9.9.9\n", encoding="utf-8")
    (ws / "runs").mkdir()
    return ws


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(KUNGLAO_PY), *args],
                          capture_output=True, text=True, timeout=120,
                          encoding="utf-8", errors="replace")


class TestAnalysisEntryGate:
    def test_analysis_happy_path_rc0(self, tmp_path):
        ws = _stamped_ws(tmp_path)
        _write_hb(ws, _loop_state(ticks=[_ago(6), _ago(1)]))
        proc = _cli("analysis", str(ws))
        assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
        # aging rebuild happened at the entry too
        sched = ws / ".claude" / "scheduled_tasks.json"
        assert sched.exists()
        entries = json.loads(sched.read_text())
        entries = entries["jobs"] if isinstance(entries, dict) else entries
        assert any(e.get("id") == "kunglao-heartbeat" for e in entries)

    def test_analysis_verify_failure_maps_to_rearm_hint_rc6(self, tmp_path,
                                                            monkeypatch):
        """Acceptance: monkeypatch verify 返回 1 → 入口 stderr 提示."""
        import io
        from contextlib import redirect_stderr

        import heartbeat_loop_prompt as hlp_mod
        import kunglao as kmod  # router module (in-process for monkeypatch)

        ws = _stamped_ws(tmp_path)
        _write_hb(ws, _loop_state(ticks=[_ago(6), _ago(1)]))
        monkeypatch.setattr(hlp_mod, "verify_loop", lambda ws_arg: 1)

        class Args:
            workspace = str(ws)
        buf_err = io.StringIO()
        with redirect_stderr(buf_err):
            rc = kmod.cmd_analysis(Args())
        err = buf_err.getvalue()
        assert rc == 6, f"expected RC_HEARTBEAT_VERIFY_FAIL=6, got {rc}: {err}"
        assert "heartbeat verify failed" in err
        assert "/kunglao-agent:resume" in err

    def test_rc_constants_distinct(self):
        """rc5 (stale) and rc6 (heartbeat) map to different remediations."""
        import kunglao as kmod
        assert kmod.RC_STALE_WORKSPACE == 5
        assert kmod.RC_HEARTBEAT_VERIFY_FAIL == 6

    def test_analysis_aging_rebuild_restores_missing_entry(self, tmp_path):
        ws = _stamped_ws(tmp_path)
        _write_hb(ws, _loop_state(ticks=[_ago(6), _ago(1)]))
        proc = _cli("analysis", str(ws))
        assert proc.returncode == 0
        sched = ws / ".claude" / "scheduled_tasks.json"
        sched.unlink()
        proc2 = _cli("analysis", str(ws))
        assert proc2.returncode == 0, proc2.stderr
        assert sched.exists()

    def test_analysis_refuses_before_heartbeat_when_stale(self, tmp_path):
        ws = tmp_path / "old-ws"
        ws.mkdir(parents=True)
        (ws / "CLAUDE.md").write_text("# kunglao_template_version: 0.1.0\n", encoding="utf-8")
        proc = _cli("analysis", str(ws))
        assert proc.returncode == 5, proc.stderr
        assert "/kunglao-agent:upgrade" in (proc.stderr + proc.stdout)
