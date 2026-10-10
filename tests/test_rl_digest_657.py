# -*- coding: utf-8 -*-
"""tests/test_rl_digest_657.py — the per-decision RL digest line (option 1).

Issue 657: the RL decides every round (compose / settlement / credit) but
the scrolling transcript carries none of it — the operator must open
runs/*.jsonl by hand. Option 1 lands ONE template-rendered digest line on
the round-closure face (SubagentStop), sourced from the strategy object in
force + the settled-ledger tail:

    RL: lead=<method_lead|none>(<age>) last-settle=<anchor:band|none> round=<n>

Contracts pinned here:
  - the line is a pure template over the strategy object's own fields
    (byte-for-byte on lead/round; the age derives from the object's ts);
  - absent object / unknown schema / non-kunglao workspace -> ZERO output;
  - rate limit: an unchanged decision (same round/lead/settlement) stays
    silent; a new settlement or a new strategy re-emits;
  - the visibility channel is the SubagentStop hook's stdout
    ``{"systemMessage": ...}`` envelope (the Claude Code user-facing
    message field) — exactly one line per emitted round;
  - the determinism wall holds: no model call, no invented text.

Counting unit: one digest line per emitted decision. Never a second line.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from _factories import write_claims_register, write_hook_state

NOW = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    write_claims_register(ws, [{"id": "C-1", "status": "OPEN"}])
    return ws


def _write_strategy(ws: Path, *, tick: int = 3, ts: str | None = None,
                    lead: str | None = "static-decompile") -> Path:
    """Version ONE round-strategy object (the compose single-point's on-disk
    shape) so the digest reads exactly what the producer wrote."""
    directory = ws / "runs" / "round-strategy"
    directory.mkdir(parents=True, exist_ok=True)
    obj = {
        "schema": "round-strategy/1",
        "tick": tick,
        "ts": ts if ts is not None else _iso(NOW),
        "state_fingerprint": "fp-1",
        "composed_from": [],
        "dispatch": {"method_lead": lead, "anti_hints": [],
                     "budget_hint": None},
        "loop": {"monitor_focus": [], "ping_policy": "event_driven_guardian",
                 "stall_rules": []},
        "hooks": {"cards": []},
        "amendments": [],
        "content_hash": "0" * 64,
    }
    path = directory / f"tick-{tick:04d}.yaml"
    path.write_text(yaml.safe_dump(obj, sort_keys=True), encoding="utf-8")
    return path


def _settle(ws: Path, claim: str, band: str = "SETTLED_GREEN",
            ts: str | None = None) -> None:
    import rollout_ledger as rl
    rid = f"task/{claim}"
    rl.record(ws, kind="task", anchor=claim, signals=[
        {"type": "method_family", "source": "envelope",
         "value": "static-decompile", "ts": "t"}], rollout_id=rid)
    rl.settle(ws, rid, {"reward": 1.0, "band": band, "rule_id": "unit-test",
                        "evidence_refs": [claim]}, ts=ts)


class TestDigestRender:
    """The render face: a pure template over the strategy object in force."""

    def test_no_strategy_object_is_the_clean_silent_face(self, tmp_path):
        import rl_digest
        ws = _mk_ws(tmp_path)
        assert rl_digest.render(ws, now=NOW) is None

    def test_line_carries_the_strategy_fields_byte_for_byte(self, tmp_path):
        """lead + round are read off the object verbatim — the pin is the
        byte equality against the producer's own values."""
        import rl_digest
        ws = _mk_ws(tmp_path)
        _write_strategy(ws, tick=7, ts=_iso(NOW - timedelta(minutes=7)),
                        lead="dynamic-trace")
        line = rl_digest.render(ws, now=NOW)
        assert line == ("RL: lead=dynamic-trace(7m) last-settle=none round=7")

    def test_freshness_reads_the_object_age(self, tmp_path):
        import rl_digest
        ws = _mk_ws(tmp_path)
        _write_strategy(ws, ts=_iso(NOW - timedelta(seconds=42)))
        assert "(42s)" in rl_digest.render(ws, now=NOW)

        ws2 = tmp_path / "ws2"
        (ws2 / "runs").mkdir(parents=True)
        write_claims_register(ws2, [{"id": "C-1", "status": "OPEN"}])
        _write_strategy(ws2, ts=_iso(NOW - timedelta(hours=5)))
        assert "(5h)" in rl_digest.render(ws2, now=NOW)

    def test_last_settlement_reads_the_ledger_tail(self, tmp_path):
        """``last-settle`` is the newest settled rollout's anchor + band —
        the claim:outcome pair the operator watches for."""
        import rl_digest
        ws = _mk_ws(tmp_path)
        _write_strategy(ws)
        _settle(ws, "C-1", band="SETTLED_GREEN",
                ts=_iso(NOW - timedelta(minutes=30)))
        _settle(ws, "C-2", band="SETTLED_RED",
                ts=_iso(NOW - timedelta(minutes=5)))
        line = rl_digest.render(ws, now=NOW)
        assert "last-settle=C-2:SETTLED_RED" in line

    def test_absent_lead_and_settlement_render_explicit_none(self, tmp_path):
        """A strategy object in force with no learned lead and an empty
        ledger still renders ONE honest line — 'none', never silence and
        never a fabricated value."""
        import rl_digest
        ws = _mk_ws(tmp_path)
        _write_strategy(ws, lead=None)
        line = rl_digest.render(ws, now=NOW)
        assert line == "RL: lead=none(0s) last-settle=none round=3"

    def test_unknown_schema_renders_nothing(self, tmp_path):
        import rl_digest
        ws = _mk_ws(tmp_path)
        p = _write_strategy(ws)
        doc = yaml.safe_load(p.read_text(encoding="utf-8"))
        doc["schema"] = "round-strategy/99"
        p.write_text(yaml.safe_dump(doc, sort_keys=True), encoding="utf-8")
        assert rl_digest.render(ws, now=NOW) is None

    def test_malformed_object_renders_nothing(self, tmp_path):
        import rl_digest
        ws = _mk_ws(tmp_path)
        directory = ws / "runs" / "round-strategy"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "tick-0003.yaml").write_text("{ not: yaml: [",
                                                  encoding="utf-8")
        assert rl_digest.render(ws, now=NOW) is None

    def test_unparseable_ts_renders_the_unknown_age_face(self, tmp_path):
        """An object whose ts is unreadable keeps its honest '?': the age
        is NEVER fabricated from the wall clock."""
        import rl_digest
        ws = _mk_ws(tmp_path)
        _write_strategy(ws, ts="not-a-timestamp")
        assert "lead=static-decompile(?)" in rl_digest.render(ws, now=NOW)


class TestRateLimit:
    """One line per decision: unchanged rounds stay silent, movement emits."""

    def test_first_emit_returns_the_line_and_records_the_marker(
            self, tmp_path):
        import rl_digest
        ws = _mk_ws(tmp_path)
        _write_strategy(ws)
        line = rl_digest.emit(ws, now=NOW)
        assert line == "RL: lead=static-decompile(0s) last-settle=none round=3"
        marker = json.loads(
            (ws / "runs" / ".rl-digest.json").read_text(encoding="utf-8"))
        assert marker["schema"] == "rl-digest/1"
        assert marker["round"] == 3
        assert marker["line"] == line

    def test_unchanged_decision_is_suppressed(self, tmp_path):
        import rl_digest
        ws = _mk_ws(tmp_path)
        _write_strategy(ws)
        assert rl_digest.emit(ws, now=NOW) is not None
        # same round / lead / settlement one minute later -> silence
        assert rl_digest.emit(ws, now=NOW + timedelta(minutes=1)) is None

    def test_idle_heartbeat_re_emits_after_the_window(self, tmp_path):
        """The age in the line must not rot silently: an unchanged decision
        re-emits once per RATE_LIMIT_MINUTES, never per closure."""
        import rl_digest
        ws = _mk_ws(tmp_path)
        _write_strategy(ws)
        assert rl_digest.emit(ws, now=NOW) is not None
        assert rl_digest.emit(
            ws, now=NOW + timedelta(minutes=rl_digest.RATE_LIMIT_MINUTES - 1)
        ) is None
        line = rl_digest.emit(
            ws, now=NOW + timedelta(minutes=rl_digest.RATE_LIMIT_MINUTES + 1))
        assert line is not None and "(31m)" in line

    def test_new_settlement_re_emits(self, tmp_path):
        import rl_digest
        ws = _mk_ws(tmp_path)
        _write_strategy(ws)
        assert rl_digest.emit(ws, now=NOW) is not None
        _settle(ws, "C-1", ts=_iso(NOW + timedelta(minutes=1)))
        line = rl_digest.emit(ws, now=NOW + timedelta(minutes=2))
        assert line is not None
        assert "last-settle=C-1:SETTLED_GREEN" in line

    def test_new_strategy_round_re_emits(self, tmp_path):
        import rl_digest
        ws = _mk_ws(tmp_path)
        _write_strategy(ws, tick=3)
        assert rl_digest.emit(ws, now=NOW) is not None
        _write_strategy(ws, tick=4, ts=_iso(NOW + timedelta(minutes=1)),
                        lead="pattern-match")
        line = rl_digest.emit(ws, now=NOW + timedelta(minutes=2))
        assert line == "RL: lead=pattern-match(1m) last-settle=none round=4"

    def test_no_strategy_object_never_emits(self, tmp_path):
        import rl_digest
        ws = _mk_ws(tmp_path)
        assert rl_digest.emit(ws, now=NOW) is None
        assert not (ws / "runs" / ".rl-digest.json").exists()


class TestRoundClosureWiring:
    """The visibility channel: the SubagentStop closure face prints ONE
    ``{"systemMessage": ...}`` JSON line (the user-facing hook message
    field) — and nothing at all on the silent faces."""

    def _payload(self, ws: Path) -> dict:
        return {"cwd": str(ws), "session_id": "sess-657",
                "transcript_path": str(ws / "transcript.jsonl")}

    def test_closure_emits_one_digest_line(self, tmp_path, capsys):
        import round_closure
        ws = _mk_ws(tmp_path)
        _settle(ws, "C-1")
        write_hook_state(ws, active_hooks=["completion_gate"])
        rc = round_closure.main_with_payload(self._payload(ws))
        out = capsys.readouterr().out
        assert rc == 0
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert len(lines) == 1, f"exactly one digest line expected: {out!r}"
        doc = json.loads(lines[0])
        assert doc["systemMessage"].startswith("RL: lead=")
        assert " last-settle=C-1:SETTLED_GREEN " in doc["systemMessage"]
        assert "round=" in doc["systemMessage"]

    def test_repeat_closure_on_an_unchanged_workspace_is_silent(
            self, tmp_path, capsys):
        import round_closure
        ws = _mk_ws(tmp_path)
        write_hook_state(ws, active_hooks=["completion_gate"])
        round_closure.main_with_payload(self._payload(ws))
        assert capsys.readouterr().out.strip(), "first closure emits"
        rc = round_closure.main_with_payload(self._payload(ws))
        out = capsys.readouterr().out
        assert rc == 0 and out == "", "the unchanged round must stay silent"

    def test_no_workspace_is_silent(self, tmp_path, capsys):
        """Not a kunglao workspace -> zero output (the gate)."""
        import round_closure
        rc = round_closure.main_with_payload({"cwd": str(tmp_path)})
        assert rc == 0 and capsys.readouterr().out == ""

    def test_no_strategy_object_is_silent(self, tmp_path, capsys):
        """A kunglao workspace whose compose face cannot land a strategy
        object (blocked strategy dir) has nothing in force -> zero output
        from the digest face (the other closure faces stay fail-open)."""
        import round_closure
        ws = _mk_ws(tmp_path)
        write_hook_state(ws, active_hooks=["completion_gate"])
        (ws / "runs" / "round-strategy").write_text("not a dir",
                                                    encoding="utf-8")
        rc = round_closure.main_with_payload(self._payload(ws))
        assert rc == 0 and capsys.readouterr().out == ""

    def test_fail_open_on_a_broken_digest_face(self, tmp_path, capsys,
                                              monkeypatch):
        """A digest-face crash is one warn, never a closure disturbance:
        rc stays 0 and the closure row still lands."""
        import json as _json
        import round_closure
        ws = _mk_ws(tmp_path)
        write_hook_state(ws, active_hooks=["completion_gate"])
        import rl_digest

        def _boom(*a, **k):
            raise RuntimeError("digest face exploded")

        monkeypatch.setattr(rl_digest, "emit", _boom)
        rc = round_closure.main_with_payload(self._payload(ws))
        err = capsys.readouterr()
        assert rc == 0
        assert "systemMessage" not in err.out
        logs = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
        rows = [_json.loads(ln) for ln in
                logs[-1].read_text(encoding="utf-8").splitlines() if ln]
        assert any(r.get("action") == "lifecycle_completed" for r in rows)
