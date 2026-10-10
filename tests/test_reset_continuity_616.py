# -*- coding: utf-8 -*-
"""tests/test_reset_continuity_616.py — #616 in-session deploy-day stall.

RED: the #415.3 continuity-baseline reset gate treated ANY actor="tick"
sidecar row as proof "the cron has fired" — but per #415 a durable cron
registered MID-SESSION does not fire until the next Claude Code session, so
every in-session tick is a MANUAL heartbeat_tick.py run. A workspace that
ticked manually and then went quiet > 2x interval had NO legal in-session
recovery: the reset refused ("real tick row(s) present"), and the pre-#616
continuity window (UNION of "last 12 ticks OR within 2h") kept the stale gap
pair voting no matter how many fresh re-arm ticks landed — locked for up to
2h (live: five fresh ticks did not clear a 25-min pair).

Contracts pinned here:
  R1 reset gate provenance — manual-origin rows do NOT block the reset;
     cron-origin rows do (the durable loop has fired); legacy unmarked rows
     do (fail-closed: provenance unknown).
  R2 anti-tamper (#830) — the gate reads the durable sidecar, never the
     .heartbeat.json cache: a rewritten cache cannot buy a reset while
     cron/legacy rows sit in the sidecar, and the rotation keeps the old
     rows (audit preserved, never erased).
  R3 loop_registered survives the reset (recovery no longer needs a
     --loop-registered re-mark).
  R4 bounded re-arm — one window (CONTINUITY_WINDOW_TICKS) of on-cadence
     ticks after a stall clears the stale pair; the tick BEFORE the bound
     still REJECTs (#754 continuous-tick detection not weakened).
  R5 tick CLI provenance — heartbeat_tick.py writes origin="manual" by
     default, origin="cron" under --origin cron, and the /loop prompt body
     (the cron channel) invokes it with --origin cron while the manual
     re-arm chain guidance does not.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import heartbeat  # noqa: E402
from liveness_policy import CONTINUITY_WINDOW_TICKS  # noqa: E402

NOW = datetime.now(timezone.utc)


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    return ws


def _row(ws: Path, ts: str, *, origin: str | None = "manual",
         actor: str = "tick") -> None:
    """Append one durable sidecar row; origin=None writes a legacy row."""
    entry = {"ts": ts, "actor": actor}
    if origin is not None:
        entry["origin"] = origin
    with (ws / "runs" / ".heartbeat.log").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")


def _state(ws: Path, *, marker: bool = False, history=()) -> None:
    (ws / "runs" / ".heartbeat.json").write_text(json.dumps(
        {"ts": _ts(NOW), "interval_min": 5, "loop_registered": marker,
         "tick_history": list(history)}), encoding="utf-8")


def _read_state(ws: Path) -> dict:
    return json.loads(
        (ws / "runs" / ".heartbeat.json").read_text(encoding="utf-8"))


# ===========================================================================
# R1 — reset gate provenance: manual ticks are not proof the cron fired
# ===========================================================================

class TestResetGateProvenance616:
    def test_manual_ticks_do_not_block_the_reset(self, tmp_path):
        """THE #616 bug: mid-session manual ticks were read as 'the cron has
        fired' and refused the only legal in-session recovery."""
        ws = _ws(tmp_path)
        for m in (30, 25, 20):
            _row(ws, _ts(NOW - timedelta(minutes=m)), origin="manual")
        _state(ws)
        got = heartbeat.reset_continuity_baseline(ws)
        assert got["status"] == "reset", got
        assert got["manual_ticks"] == 3, got
        rotated = list((ws / "runs").glob(".heartbeat.log.reset-*"))
        assert len(rotated) == 1 and rotated[0] == (
            ws / "runs" / got["rotated_to"]), (got, rotated)
        # audit preserved: the manual rows survive in the rotated log
        assert rotated[0].read_text(encoding="utf-8").count('"actor": "tick"') == 3
        state = _read_state(ws)
        assert state["continuity_baseline_reset"] == state["tick_history"][-1]

    def test_cron_tick_row_still_refuses(self, tmp_path):
        """A cron-provenance tick IS proof the durable loop ran."""
        ws = _ws(tmp_path)
        _row(ws, _ts(NOW - timedelta(minutes=25)), origin="manual")
        _row(ws, _ts(NOW - timedelta(minutes=20)), origin="cron")
        _state(ws)
        got = heartbeat.reset_continuity_baseline(ws)
        assert got["status"] == "refused", got
        assert "cron" in got["reason"], got
        assert not list((ws / "runs").glob(".heartbeat.log.reset-*"))
        assert _read_state(ws)["tick_history"] == []

    def test_legacy_unmarked_row_refuses_fail_closed(self, tmp_path):
        """Pre-#616 rows carry no provenance: unknown -> fail-closed (the
        #415.3 wording is kept for the refusal)."""
        ws = _ws(tmp_path)
        _row(ws, _ts(NOW - timedelta(minutes=25)), origin=None)
        _state(ws)
        got = heartbeat.reset_continuity_baseline(ws)
        assert got["status"] == "refused", got
        assert "real tick" in got["reason"], got

    def test_hook_register_renew_rows_never_block(self, tmp_path):
        """Non-tick sidecar streams stay irrelevant to the gate."""
        ws = _ws(tmp_path)
        _row(ws, _ts(NOW - timedelta(minutes=30)), origin=None, actor="hook")
        _row(ws, _ts(NOW - timedelta(minutes=29)), origin=None,
             actor="register")
        _row(ws, _ts(NOW - timedelta(minutes=28)), origin=None, actor="renew")
        _state(ws)
        assert heartbeat.reset_continuity_baseline(ws)["status"] == "reset"


# ===========================================================================
# R2 — anti-tamper: the decision reads the durable sidecar, not the cache
# ===========================================================================

class TestResetGateAntiTamper:
    def test_cache_rewrite_cannot_buy_a_reset(self, tmp_path):
        """#830: rewriting .heartbeat.json (clean fresh history, marker
        true) must not erase the sidecar's cron evidence."""
        ws = _ws(tmp_path)
        _row(ws, _ts(NOW - timedelta(minutes=20)), origin="cron")
        _state(ws, marker=True,
               history=[_ts(NOW - timedelta(minutes=6)),
                        _ts(NOW - timedelta(minutes=1))])
        got = heartbeat.reset_continuity_baseline(ws)
        assert got["status"] == "refused", got
        assert "cron" in got["reason"], got

    def test_reset_rotation_never_erases_history(self, tmp_path):
        """The allowed reset preserves every old row in the rotated log."""
        ws = _ws(tmp_path)
        _row(ws, _ts(NOW - timedelta(minutes=25)), origin="manual")
        _state(ws)
        got = heartbeat.reset_continuity_baseline(ws)
        assert got["status"] == "reset", got
        rotated = ws / "runs" / got["rotated_to"]
        body = rotated.read_text(encoding="utf-8").strip().splitlines()
        assert len(body) == 1 and json.loads(body[0])["origin"] == "manual"


# ===========================================================================
# R3 — the reset preserves loop_registered (no re-mark needed)
# ===========================================================================

class TestMarkerPreservedAcrossReset:
    def test_marker_survives(self, tmp_path):
        ws = _ws(tmp_path)
        _row(ws, _ts(NOW - timedelta(minutes=30)), origin="manual")
        _state(ws, marker=True)
        got = heartbeat.reset_continuity_baseline(ws)
        assert got["status"] == "reset", got
        assert _read_state(ws)["loop_registered"] is True

    def test_marker_stays_false_when_absent(self, tmp_path):
        ws = _ws(tmp_path)
        _row(ws, _ts(NOW - timedelta(minutes=30)), origin="manual")
        _state(ws, marker=False)
        assert heartbeat.reset_continuity_baseline(ws)["status"] == "reset"
        assert _read_state(ws)["loop_registered"] is False


# ===========================================================================
# R4 — bounded re-arm: one window of on-cadence ticks clears the stale pair
# ===========================================================================

class TestBoundedRearm616:
    def _stall_then_resume(self, ws: Path, resumed: int) -> Path:
        """A stale pair (35 min > 2x5m) + `resumed` on-cadence minutes."""
        _row(ws, _ts(NOW - timedelta(minutes=40)), origin="manual")
        for m in range(resumed - 1, -1, -1):
            _row(ws, _ts(NOW - timedelta(minutes=m)), origin="manual")
        return ws / "runs" / ".heartbeat.log"

    def test_stale_pair_still_rejects_one_tick_before_the_bound(
            self, tmp_path):
        """#754 detection intact: the tick before the bound still REJECTs."""
        ws = _ws(tmp_path)
        log = self._stall_then_resume(ws, CONTINUITY_WINDOW_TICKS - 1)
        alive, detail = heartbeat.evaluate_tick_continuity(
            {"interval_min": 5, "tick_history": []}, log_path=log, now=NOW)
        assert alive is False, detail
        assert "gap" in detail.lower(), detail

    def test_recovered_cadence_clears_the_pair_at_the_bound(self, tmp_path):
        """#616 requirement: bounded recovery — CONTINUITY_WINDOW_TICKS
        on-cadence ticks after the stall and the pair stops voting (the
        pre-#616 union held it until 12 ticks or 2h)."""
        ws = _ws(tmp_path)
        log = self._stall_then_resume(ws, CONTINUITY_WINDOW_TICKS)
        alive, detail = heartbeat.evaluate_tick_continuity(
            {"interval_min": 5, "tick_history": []}, log_path=log, now=NOW)
        assert alive is True, detail
        assert "aged out" in detail, detail


# ===========================================================================
# R5 — tick CLI provenance + the cron channel wiring
# ===========================================================================

def _load_tick(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "heartbeat_tick_uut_616", ROOT / "scripts" / "heartbeat_tick.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def fake_run(script, ws, *extra):  # keep the tick mechanical-only
        return {"script": script, "rc": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(mod, "run", fake_run)
    monkeypatch.setattr(mod, "_oracle_registered", lambda ws: True)
    return mod


def _tick_rows(ws: Path) -> list[dict]:
    log = ws / "runs" / ".heartbeat.log"
    return [json.loads(ln) for ln in
            log.read_text(encoding="utf-8").splitlines()
            if ln.strip() and json.loads(ln).get("actor") == "tick"]


class TestTickOriginWiring616:
    def test_default_tick_row_is_manual(self, tmp_path, monkeypatch, capsys):
        mod = _load_tick(monkeypatch)
        ws = _ws(tmp_path)
        mod.main([str(ws)])
        rows = _tick_rows(ws)
        assert rows and rows[-1]["origin"] == "manual", rows

    def test_cron_origin_flag_marks_the_row(self, tmp_path, monkeypatch,
                                            capsys):
        mod = _load_tick(monkeypatch)
        ws = _ws(tmp_path)
        mod.main([str(ws), "--origin", "cron"])
        rows = _tick_rows(ws)
        assert rows and rows[-1]["origin"] == "cron", rows

    def test_loop_prompt_channel_carries_cron_origin(self, tmp_path):
        import heartbeat_loop_prompt as hlp
        body = hlp.build_prompt(str(tmp_path), "5m")
        assert "--origin cron" in body
        assert "heartbeat_tick.py" in body
        # the manual re-arm guidance (constitution) must NOT claim cron
        assert "--origin" not in hlp.constitution(str(tmp_path))
