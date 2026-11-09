# -*- coding: utf-8 -*-
"""tests/test_scheduler_events_1001.py — the event-driven wake path.

The loop's wake mechanism was pure time polling: a fixed cron woke the
session whether or not anything happened. This slice adds the EVENT
spine, additive to the old monitor stack (that removal is its own
reviewed change):

  - ``runs/scheduler/events.jsonl`` — the append-only stream of the
    scheduler's MATERIAL events (closed five-kind vocabulary), written
    by the faces that already record the underlying facts (one fail-open
    append each, derived from data the producer has in hand). The events
    are EPHEMERAL WAKE SIGNALS, not learning rows — every kind has a
    durable ledger home already, so the stream carries NO
    consolidated-ledger row and registers nothing in NATIVE_SCHEMAS
    (pinned here).
  - ``scripts/scheduler_watch.py`` — the NON-LLM watcher: a poll loop
    that tails the stream by byte offset and, on new material events,
    emits the wake contract (the timer wake contract's shape family) to
    stdout exactly once per batch. Quiet stream -> zero output. All
    paths resolve absolute at startup (a session ``cd`` must never empty
    the watch list) and an empty watch list is a visible warn, never a
    silent dead watcher.
  - the drain face (loop_scheduler) — on wake, drains each unread event
    exactly once (idempotent row-count cursor) and acts per type through
    the existing faces (the materiality gate runs before any LLM turn:
    the watcher and the drain are both mechanical).

Pinned here: the stream round-trip + both materiality gates, the three
producer seams (gate reject / settle / deadline fired), the watcher's
exactly-once emission + absolute-path pins, the watcher's no-model-call
AST wall, and the drain's idempotent dispatch.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

import scheduler_events as se  # noqa: E402
import scheduler_watch as sw  # noqa: E402
import loop_scheduler as ls  # noqa: E402
from rlvr import rollout_timer_host as host  # noqa: E402

NOW = datetime(2026, 11, 5, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def ws(tmp_path) -> Path:
    workspace = tmp_path / "ws"
    (workspace / "runs").mkdir(parents=True)
    return workspace


def _events_file(ws: Path) -> Path:
    return ws / "runs" / "scheduler" / "events.jsonl"


def _load_hook(name: str, mod_id: str):
    """Load one hooks/ module by path (the unit-face pattern of the
    dispatch-gate passthrough tests: the hook runs as a script, so the
    bare import would need the hooks dir first on the path)."""
    spec = importlib.util.spec_from_file_location(mod_id, ROOT / "hooks"
                                                  / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ------------------------------------------------ the events stream ----

class TestEventStream:
    def test_append_read_roundtrip(self, ws):
        assert se.append(ws, se.KIND_GATE_REJECT, claim="C-1",
                         reason="granularity") is True
        rows = se.read(ws)
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "gate-reject"
        assert row["claim"] == "C-1"
        assert row["reason"] == "granularity"
        assert row["schema"] == se.SCHEMA
        assert row["ts"]  # identity stamp

    def test_every_closed_vocabulary_kind_is_material(self, ws):
        for kind in se.KINDS:
            assert se.is_material(kind) is True
            assert se.append(ws, kind, claim="C-1") is True
        assert len(se.read(ws)) == len(se.KINDS)

    def test_writer_side_gate_refuses_non_material_kinds(self, ws):
        """The materiality gate is the WRITER-side filter: a heartbeat or
        tick can never enter the file — one warn + False, nothing lands."""
        for noise in ("tick", "heartbeat", "schedule_scan"):
            assert se.append(ws, noise, claim="C-1") is False
        assert se.read(ws) == []
        assert not _events_file(ws).exists() or \
            _events_file(ws).read_text(encoding="utf-8").strip() == ""

    def test_reader_side_gate_drops_unknown_kinds(self, ws):
        """The materiality gate is also the READER-side closed-vocabulary
        check: a hand-placed non-material row is dropped, never woken."""
        se.append(ws, se.KIND_WORKER_EXIT, claim="C-1")
        p = _events_file(ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": "2026-11-05T12:00:00Z",
                                 "schema": se.SCHEMA,
                                 "kind": "heartbeat"}) + "\n")
        rows = se.material_rows(ws)
        assert [r["kind"] for r in rows] == [se.KIND_WORKER_EXIT]

    def test_events_are_ephemeral_wake_signals_no_ledger_row(self, ws):
        """The events-are-X decision, pinned: ephemeral wake signals ride
        the signals-stream pattern — the append writes ONLY the events
        file, never a consolidated-ledger row, and the stamp is NOT
        registered in NATIVE_SCHEMAS (every kind's durable home is the
        ledger it already rides; a duplicate telemetry row no reward face
        reads would be pure IO waste)."""
        from rlvr import consolidated_ledger as ledger
        se.append(ws, se.KIND_SETTLE_COMPLETED, claim="C-1")
        assert _events_file(ws).is_file()
        assert not (ws / "runs" / "experience.jsonl").exists()
        assert not (ws / "runs" / "telemetry.jsonl").exists()
        assert not (ws / "runs" / "settlement.jsonl").exists()
        for family, stamps in ledger.NATIVE_SCHEMAS.items():
            assert se.SCHEMA not in stamps, (
                f"the wake stream must not register in {family}")

    def test_tolerant_read_skips_dirty_rows(self, ws):
        p = _events_file(ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"kind": "gate-reject", "claim": "C-1"}\n'
                     'not json at all\n[1, 2]\n'
                     '{"kind": "settle-completed", "claim": "C-2"}\n',
                     encoding="utf-8")
        rows = se.material_rows(ws)
        assert [r["kind"] for r in rows] == ["gate-reject",
                                             "settle-completed"]

    def test_append_never_raises_on_blocked_path(self, ws):
        """Fail-open posture: a write failure degrades to False, never an
        exception into the producer's path."""
        blocker = ws / "runs" / "scheduler"
        blocker.write_text("not a dir\n", encoding="utf-8")
        assert se.append(ws, se.KIND_GATE_REJECT, claim="C-1") is False
        assert se.read(ws) == []

    def test_append_failure_warns_scoped_to_the_workspace(
            self, ws, monkeypatch):
        """The failure warn's workspace pin lands for THIS call and is
        restored after (the library face never leaves the process's
        diagnostics resolution changed)."""
        import kunglao_log
        blocker = ws / "runs" / "scheduler"
        blocker.write_text("not a dir\n", encoding="utf-8")
        prior = kunglao_log.warn_workspace()
        seen = {}
        real = kunglao_log.warn_once_stateful

        def spy(op, reason, state_key=None):
            seen["op"] = op
            seen["ws_at_warn"] = kunglao_log.warn_workspace()
            return real(op, reason, state_key=state_key)

        monkeypatch.setattr(kunglao_log, "warn_once_stateful", spy)
        assert se.append(ws, se.KIND_GATE_REJECT, claim="C-1") is False
        assert seen["op"] == "scheduler_events.append"
        assert Path(seen["ws_at_warn"]) == ws
        assert kunglao_log.warn_workspace() == prior

    def test_count_rows_cursor(self, ws):
        assert se.count_rows(ws) == 0
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1")
        se.append(ws, se.KIND_GATE_REJECT, claim="C-2")
        assert se.count_rows(ws) == 2


# ------------------------------------------------ the producer seams ----

class TestProducerSeams:
    def test_gate_reject_writes_its_event_row(self, ws):
        """The dispatch gate's reject tail: the same fact the
        dispatch-reject row records also lands one wake-stream row —
        derived from the data already in hand, one append, fail-open."""
        gate = _load_hook("dispatch_gate", "_gate_for_scheduler_events")
        gate._stamp_reject("top1", "dispatch the ranked claim")
        gate._log_dispatch_reject(ws, "C-1")
        rows = se.read(ws)
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == se.KIND_GATE_REJECT
        assert row["claim"] == "C-1"
        assert row["reason"] == "top1"

    def test_gate_reject_row_lands_even_when_the_stream_breaks(
            self, ws, monkeypatch):
        """SEAM ORDERING: the durable dispatch-reject ledger row lands
        FIRST; a stream failure (the append face down) must never abort
        it — the event seam's cage is nested, after the row."""
        from rlvr import dispatch_reject
        gate = _load_hook("dispatch_gate", "_gate_for_scheduler_events")
        gate._stamp_reject("top1", "dispatch the ranked claim")

        def _down(*a, **k):
            raise RuntimeError("stream down")
        monkeypatch.setattr(se, "append", _down)
        gate._log_dispatch_reject(ws, "C-1")
        assert len(dispatch_reject.reject_rows(ws)) == 1
        assert se.read(ws) == []

    def test_gate_reject_row_lands_even_when_the_module_is_missing(
            self, ws, monkeypatch):
        """The partial-deploy window: the stream module unimportable —
        the nested cage catches the ImportError and the DURABLE row
        still lands (the stderr note names the event seam, not the
        reject write)."""
        from rlvr import dispatch_reject
        gate = _load_hook("dispatch_gate", "_gate_for_scheduler_events")
        gate._stamp_reject("granularity", "split the claim")
        monkeypatch.setitem(sys.modules, "scheduler_events", None)
        gate._log_dispatch_reject(ws, "C-1")
        assert len(dispatch_reject.reject_rows(ws)) == 1

    def test_gate_reject_ledger_row_still_lands(self, ws):
        """The seam is additive: the dispatch-reject ledger row the
        decision machine reads still lands unchanged."""
        from rlvr import dispatch_reject
        gate = _load_hook("dispatch_gate", "_gate_for_scheduler_events_2")
        gate._stamp_reject("granularity", "split the claim")
        gate._log_dispatch_reject(ws, "C-9")
        rows = dispatch_reject.reject_rows(ws)
        assert len(rows) == 1
        assert rows[0]["o"]["status"] == "rejected"

    def test_settle_writes_its_event_row(self, ws):
        """The settle path's receipt is already in hand — the seam
        derives the settle-completed event from it."""
        closure = _load_hook("round_closure", "_closure_for_scheduler_events")
        receipt = {"claim": "C-1", "outcome": "completed",
                   "wall_s": 41.0, "step_id": "s-1"}
        assert closure.emit_settle_event(ws, receipt) is True
        rows = se.read(ws)
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == se.KIND_SETTLE_COMPLETED
        assert row["claim"] == "C-1"
        assert row["outcome"] == "completed"

    def test_settle_seam_ignores_receiptless_rounds(self, ws):
        """A round close with nothing settled (no receipt) is quiet — the
        stream carries no synthetic rows."""
        closure = _load_hook("round_closure", "_closure_for_scheduler_events2")
        assert closure.emit_settle_event(ws, None) is False
        assert closure.emit_settle_event(ws, {"outcome": "completed"}) is False
        assert se.read(ws) == []

    def test_deadline_fired_writes_its_event_row(self, ws):
        armed = host.arm_for_dispatch(ws, "C-1", "r-1",
                                      method_family="claim", now=NOW)
        assert armed is not None
        wake = host.deadline_wake_face(ws, "r-1",
                                       now=NOW + timedelta(minutes=31))
        assert wake is not None
        assert wake["stop"]["stop_reason"] == "deadline"
        rows = [r for r in se.read(ws)
                if r["kind"] == se.KIND_DEADLINE_FIRED]
        assert len(rows) == 1
        assert rows[0]["rollout_id"] == "r-1"
        assert rows[0]["claim"] == "C-1"

    def test_deadline_wake_replay_writes_no_second_row(self, ws):
        """A replayed wake (the contract re-printed for an already-fired
        rollout) is idempotent, not a NEW event — the fire contract's
        own idempotence keeps the stream free of duplicates."""
        host.arm_for_dispatch(ws, "C-1", "r-1", method_family="claim",
                              now=NOW)
        host.deadline_wake_face(ws, "r-1", now=NOW + timedelta(minutes=31))
        replay = host.deadline_wake_face(ws, "r-1",
                                         now=NOW + timedelta(minutes=32))
        assert replay is not None  # the idempotent wake receipt (rc 0 face)
        fired = [r for r in se.read(ws)
                 if r["kind"] == se.KIND_DEADLINE_FIRED]
        assert len(fired) == 1

    def test_deadline_event_loss_window_heals_on_replay(self, ws):
        """The loss window, closed: a crash between the durable fire and
        the event append leaves the replay idempotent with NO event —
        the replay's stream scan finds the row missing and LANDS IT
        (exactly-once: a replay that finds its row stays quiet)."""
        host.arm_for_dispatch(ws, "C-1", "r-1", method_family="claim",
                              now=NOW)
        host.deadline_wake_face(ws, "r-1", now=NOW + timedelta(minutes=31))
        p = _events_file(ws)
        kept = [ln for ln in p.read_text(encoding="utf-8").splitlines()
                if ln.strip() and f'"{se.KIND_DEADLINE_FIRED}"' not in ln]
        p.write_text("\n".join(kept) + ("\n" if kept else ""),
                     encoding="utf-8")
        assert se.read(ws) == []  # the crash happened before the append
        host.deadline_wake_face(ws, "r-1", now=NOW + timedelta(minutes=32))
        fired = [r for r in se.read(ws)
                 if r["kind"] == se.KIND_DEADLINE_FIRED]
        assert len(fired) == 1  # healed, exactly once


# --------------------------------------------------- the watcher ----

class TestWatcher:
    def test_watch_paths_resolve_absolute(self, tmp_path):
        paths = sw.resolve_watch_paths(tmp_path)
        assert len(paths) == 1
        assert paths[0].is_absolute()
        assert paths[0].name == "events.jsonl"

    def test_cwd_change_does_not_empty_the_watch_list(self, tmp_path):
        """The cd caveat, pinned: the watch list is a pure function of
        the workspace argument (resolved absolute at startup) — a session
        cd must never empty it nor move it."""
        paths = sw.resolve_watch_paths(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        old = os.getcwd()
        try:
            os.chdir(elsewhere)
            assert sw.resolve_watch_paths(tmp_path) == paths
        finally:
            os.chdir(old)

    def test_empty_watch_list_warns_visibly(self, tmp_path, capsys):
        """An empty watch list is a VISIBLE warn + usage rc, never a
        silently dead watcher."""
        rc = sw.main([str(tmp_path / "missing-ws"), "--once"])
        assert rc == 2
        err = capsys.readouterr().err
        assert "watch list is empty" in err.lower() or "empty" in err.lower()

    def test_material_event_emits_wake_contract_exactly_once(self, ws):
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1", reason="top1")
        contract = sw.poll_once(ws)
        assert contract is not None
        assert contract["kind"] == "scheduler-event"
        assert len(contract["events"]) == 1
        # no re-emit on re-poll: the byte cursor persisted past the row
        assert sw.poll_once(ws) is None

    def test_batched_events_emit_one_contract(self, ws):
        """Three material events inside one poll interval arrive as ONE
        wake contract (the quiet-period economy: wakes are batched, the
        drain acts per type)."""
        for claim in ("C-1", "C-2", "C-3"):
            se.append(ws, se.KIND_WORKER_EXIT, claim=claim)
        contract = sw.poll_once(ws)
        assert contract is not None
        assert len(contract["events"]) == 3
        assert sw.poll_once(ws) is None

    def test_quiet_stream_emits_zero_output(self, ws):
        """A quiet day costs zero: no events -> no contract, no output."""
        assert sw.poll_once(ws) is None
        se.append(ws, "heartbeat", claim="C-1")  # refused at write anyway
        assert sw.poll_once(ws) is None

    def test_non_material_rows_never_wake(self, ws):
        p = _events_file(ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"ts": "2026-11-05T12:00:00Z",
                                 "schema": se.SCHEMA,
                                 "kind": "tick"}) + "\n", encoding="utf-8")
        assert sw.poll_once(ws) is None
        # the byte cursor still advanced past the noise
        state = json.loads((ws / "runs" / "scheduler" / "watch-state.json")
                           .read_text(encoding="utf-8"))
        assert state["offset"] == p.stat().st_size

    def test_partial_line_held_until_complete(self, ws):
        p = _events_file(ws)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"kind": "gate-reject", "claim": "C-1"',
                     encoding="utf-8")  # no trailing newline yet
        assert sw.poll_once(ws) is None  # no complete line yet
        with p.open("a", encoding="utf-8") as fh:
            fh.write("}\n")
        contract = sw.poll_once(ws)
        assert contract is not None
        assert contract["events"][0]["claim"] == "C-1"

    def test_truncated_file_resets_cursor(self, ws):
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1")
        assert sw.poll_once(ws) is not None
        p = _events_file(ws)
        p.write_text("", encoding="utf-8")  # truncate/rotate
        assert sw.poll_once(ws) is None  # no bogus re-read

    def test_wake_contract_shape_matches_the_timer_wake_family(self, ws):
        se.append(ws, se.KIND_SETTLE_COMPLETED, claim="C-1")
        contract = sw.poll_once(ws)
        assert contract is not None
        # the same contract keys the timer wake publishes (kind / once /
        # steps / may_start_rollout / prompt), never a rollout start
        assert contract["once"] is True
        assert contract["may_start_rollout"] is False
        assert isinstance(contract["steps"], list) and contract["steps"]
        assert "drain" in contract["prompt"].lower()

    def test_once_cli_emits_the_contract_to_stdout(self, ws, capsys):
        se.append(ws, se.KIND_VERDICT_LANDED, claim="C-1")
        rc = sw.main([str(ws), "--once"])
        assert rc == 0
        out = capsys.readouterr().out
        contract = json.loads(out.strip().splitlines()[-1])
        assert contract["kind"] == "scheduler-event"

    def test_once_cli_on_quiet_stream_prints_nothing(self, ws, capsys):
        assert sw.main([str(ws), "--once"]) == 0
        assert capsys.readouterr().out.strip() == ""

    def test_wake_artifact_staged_once_and_consumed_by_the_drain(
            self, ws, capsys):
        """THE DELIVERY CHAIN, pinned end-to-end: material event ->
        watcher stages the trigger artifact exactly once -> the drain
        face consumes it (contract rides the receipt, file cleared) ->
        a second drain sees no wake."""
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1")
        assert sw.main([str(ws), "--once"]) == 0
        capsys.readouterr()
        artifact = ws / "runs" / ".scheduler-wake.json"
        doc = json.loads(artifact.read_text(encoding="utf-8"))
        assert doc["kind"] == "scheduler-event"
        # a re-poll over the same batch does not re-emit (quiet stdout)
        assert sw.main([str(ws), "--once"]) == 0
        assert capsys.readouterr().out.strip() == ""
        assert json.loads(artifact.read_text(encoding="utf-8")) == doc
        # the drain CONSUMES the staged wake: contract in, file gone
        receipt = ls.drain_events(ws)
        assert receipt["wake"]["kind"] == "scheduler-event"
        assert not artifact.exists()
        # exactly-once: the next drain sees no wake
        assert ls.drain_events(ws)["wake"] is None

    def test_watcher_restart_after_a_drain_emits_nothing(self, ws):
        """The consumption truth wins on restart: the watcher's first
        read seeds its byte cursor past the rows the drain cursor
        already consumed — a restart after a drain never re-emits a
        stale contract (a real LLM wake saved)."""
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1")
        se.append(ws, se.KIND_SETTLE_COMPLETED, claim="C-2")
        assert sw.poll_once(ws) is not None
        assert ls.drain_events(ws)["drained"] == 2
        state = sw.state_path(ws, sw.WATCH_STATE_NAME)
        state.unlink()  # the restart lost its byte cursor
        assert sw.poll_once(ws) is None  # seeded past the drained rows

    def test_second_watcher_instance_skips_with_rc3(self, ws, capsys):
        """Mutual exclusion: a held watcher lock skips the second
        instance (never double-emit) — rc 3, stderr note."""
        lock = ws / "runs" / "scheduler" / sw.WATCHER_LOCK_NAME
        fd = sw._acquire_lock(lock)
        try:
            assert fd is not None
            assert sw.main([str(ws), "--once"]) == 3
            assert "skipping" in capsys.readouterr().err
        finally:
            sw._release_lock(fd)

    def test_midrun_workspace_loss_is_a_visible_death(self, ws, capsys):
        """A workspace deleted under a live watcher is a VISIBLE death:
        the per-pass watch-list check warns on stderr and exits rc 2 —
        never a silently ticking None forever."""
        assert sw.main([str(ws), "--once"]) == 0  # healthy pass
        import shutil
        shutil.rmtree(ws)
        assert sw.main([str(ws), "--once"]) == 2
        assert "watch list is EMPTY" in capsys.readouterr().err


# -------------------------------------- the watcher's no-model wall ----

class TestNoModelCallPath:
    MODULES = ("scheduler_watch", "scheduler_events")
    IMPORT_ALLOWLIST = {
        "__future__", "json", "os", "sys", "time", "argparse", "pathlib",
        "fcntl", "harness_common", "kunglao_log", "scheduler_events",
    }
    FORBIDDEN_FRAGMENTS = (
        "llm", "model", "judge", "anthropic", "openai", "claude", "gpt",
        "completion", "subprocess", "socket", "urllib", "http", "requests",
        "popen",
    )
    # escape-hatch needles assembled from parts so this file does not
    # itself carry the raw call shapes it forbids (the settlement-wall
    # test file's convention)
    _ESC_NEEDLES = ("subpro" + "cess", "os." + "system", "pop" + "en",
                    "ev" + "al(", "ex" + "ec(", "__im" + "port__",
                    "import" + "lib")

    def _imports(self, name: str) -> list[str]:
        tree = ast.parse((ROOT / "scripts" / f"{name}.py")
                         .read_text(encoding="utf-8"))
        found: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.append(node.module)
        return found

    def test_import_surface_is_allowlisted(self):
        for name in self.MODULES:
            outside = [m for m in self._imports(name)
                       if m.split(".")[0] not in self.IMPORT_ALLOWLIST]
            assert not outside, f"{name} imports outside allowlist: {outside}"

    def test_imports_carry_no_model_call_fragments(self):
        for name in self.MODULES:
            bad = [m for m in self._imports(name)
                   for frag in self.FORBIDDEN_FRAGMENTS
                   if frag in m.lower()]
            assert not bad, f"model-call surface inside {name}: {bad}"

    def test_watcher_source_has_no_exec_escape_hatches(self):
        source = (ROOT / "scripts" / "scheduler_watch.py").read_text(
            encoding="utf-8")
        hits = [n for n in self._ESC_NEEDLES if n in source]
        assert not hits, f"escape hatch inside the watcher: {hits}"


# ------------------------------------------------------ the drain ----

class TestDrain:
    def test_unread_events_drain_once(self, ws):
        """The idempotent cursor: each event is drained exactly once —
        a second drain over the same stream is a zero no-op."""
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1")
        se.append(ws, se.KIND_SETTLE_COMPLETED, claim="C-2")
        receipt = ls.drain_events(ws)
        assert receipt["drained"] == 2
        assert receipt["cursor"] == 2
        again = ls.drain_events(ws)
        assert again["drained"] == 0
        assert again["cursor"] == 2

    def test_drain_counts_only_material_rows(self, ws):
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1")
        p = _events_file(ws)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": "2026-11-05T12:00:00Z",
                                 "schema": se.SCHEMA,
                                 "kind": "heartbeat"}) + "\n")
        receipt = ls.drain_events(ws)
        assert receipt["drained"] == 1
        assert receipt["by_type"] == {se.KIND_GATE_REJECT: 1}

    def test_drain_cli_str_workspace_drains_all_five_types(
            self, ws, capsys):
        """THE PRODUCTION INVOCATION SHAPE, pinned: the wake contract's
        CLI passes a plain STRING workspace — every one of the five
        action faces must act without a TypeError (the drain boundary
        coerces to Path once), and the receipt carries no error key."""
        (ws / "analysis_state.txt").write_text(
            "[active_workers]\n[/active_workers]\n", encoding="utf-8")
        se.append(ws, se.KIND_WORKER_EXIT, claim="C-1")
        se.append(ws, se.KIND_VERDICT_LANDED, claim="C-1")
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1")
        se.append(ws, se.KIND_DEADLINE_FIRED, claim="C-2", rollout_id="r-9")
        se.append(ws, se.KIND_SETTLE_COMPLETED, claim="C-1")
        rc = ls.main([str(ws), "--drain-events"])
        assert rc == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["drained"] == 5
        assert set(receipt["actions"]) == set(se.KINDS)
        for kind, result in receipt["actions"].items():
            assert "error" not in result, f"{kind} failed on a str ws"

    def test_failed_kind_blocks_the_cursor_prefix(self, ws, monkeypatch):
        """A failed action's rows are NEVER consumed with the action
        failed: the cursor advances only past the succeeded PREFIX; the
        failed kind's earliest row stays below it and retries on the
        next drain (the actions are idempotent reads, so the retry is
        safe)."""
        def _boom(w, rows):
            raise RuntimeError("face down")
        monkeypatch.setitem(ls.DRAIN_ACTIONS, se.KIND_GATE_REJECT, _boom)
        # the worker reconcile face needs the initialized-workspace file
        (ws / "analysis_state.txt").write_text(
            "[active_workers]\n[/active_workers]\n", encoding="utf-8")
        se.append(ws, se.KIND_WORKER_EXIT, claim="C-1")  # idx 0 — acts
        se.append(ws, se.KIND_GATE_REJECT, claim="C-2")  # idx 1 — fails
        receipt = ls.drain_events(ws)
        assert receipt["drained"] == 1          # the succeeded prefix only
        assert receipt["cursor"] == 1           # the failed row stays
        assert "error" in receipt["actions"][se.KIND_GATE_REJECT]
        retry = ls.drain_events(ws)             # the failed row re-tried
        assert retry["attempted"] == 1

    def test_poison_kind_advances_after_the_cap(self, ws, monkeypatch):
        """The poison policy: a kind that blocks POISON_SKIP_AFTER
        consecutive drains advances despite the failing face (a
        permanently broken face must not wedge the wake path); the
        receipt marks it poisoned and the face is still called."""
        calls = {"n": 0}

        def _boom(w, rows):
            calls["n"] += 1
            raise RuntimeError("down")
        monkeypatch.setitem(ls.DRAIN_ACTIONS, se.KIND_GATE_REJECT, _boom)
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1")
        for _ in range(ls.POISON_SKIP_AFTER):
            receipt = ls.drain_events(ws)
            assert receipt["drained"] == 0 and receipt["cursor"] == 0
        receipt = ls.drain_events(ws)
        assert receipt["drained"] == 1 and receipt["cursor"] == 1
        assert receipt["actions"][se.KIND_GATE_REJECT]["poisoned"] is True
        assert calls["n"] == ls.POISON_SKIP_AFTER + 1

    def test_drain_cursor_truncation_guard(self, ws):
        """A rebuilt/pruned stream shorter than the persisted cursor
        RESETS it (never skips new events forever) — the receipt
        reports the cursor actually persisted."""
        state_dir = ws / "runs" / "scheduler"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "drain-state.json").write_text(
            json.dumps({"rows": 100}), encoding="utf-8")
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1")
        se.append(ws, se.KIND_SETTLE_COMPLETED, claim="C-2")
        receipt = ls.drain_events(ws)
        assert receipt["drained"] == 2   # both drained after the reset
        assert receipt["cursor"] == 2    # the persisted truth

    def test_concurrent_drain_skips_on_the_lock(self, ws):
        """Mutual exclusion: a held drain lock skips the second drain
        (never double-act) — the skip receipt leaves cursor and the
        staged wake artifact untouched."""
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1")
        assert sw.main([str(ws), "--once"]) == 0  # stage the artifact
        lock_fd = ls._acquire_drain_lock(ws)
        try:
            receipt = ls.drain_events(ws)
            assert receipt["skipped"] == "lock-held"
            assert receipt["wake"] is None      # artifact NOT consumed
            assert (ws / "runs" / ".scheduler-wake.json").exists()
            assert se.read(ws)                  # the event was not consumed
        finally:
            ls._release_drain_lock(lock_fd)
        receipt = ls.drain_events(ws)           # after release: full drain
        assert receipt["drained"] == 1
        assert receipt["wake"] is not None

    def test_drain_actions_dispatch_to_existing_faces(self, ws):
        """The per-type actions dispatch to the faces that already own
        each fact — the receipt carries each face's own result shape."""
        # the worker reconcile face rewrites analysis_state.txt (the
        # initialized-workspace contract) — seed the initialized shape
        (ws / "analysis_state.txt").write_text(
            "[active_workers]\n[/active_workers]\n", encoding="utf-8")
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1", reason="granularity")
        se.append(ws, se.KIND_SETTLE_COMPLETED, claim="C-1")
        se.append(ws, se.KIND_DEADLINE_FIRED, claim="C-2", rollout_id="r-9")
        se.append(ws, se.KIND_WORKER_EXIT, claim="C-1")
        se.append(ws, se.KIND_VERDICT_LANDED, claim="C-1")
        receipt = ls.drain_events(ws)
        assert receipt["drained"] == 5
        actions = receipt["actions"]
        # the dispatch-reject feedback face (its own shape)
        assert actions[se.KIND_GATE_REJECT]["retry_max"] == 3
        assert "by_claim" in actions[se.KIND_GATE_REJECT]
        # the digest emit face (silent on a bare workspace)
        assert "digest" in actions[se.KIND_SETTLE_COMPLETED]
        # the timer-state read face for the fired rollout
        assert "r-9" in actions[se.KIND_DEADLINE_FIRED]["rollouts"]
        # the worker reconcile face (active count)
        assert "active" in actions[se.KIND_WORKER_EXIT]
        # the verdict-status watch face (scan report)
        assert "notes_scanned" in actions[se.KIND_VERDICT_LANDED]

    def test_drain_routes_per_event_type(self, ws, monkeypatch):
        """The action table routes each drained event to its own face —
        one call per type present, none for absent types."""
        calls: list[str] = []
        for kind in se.KINDS:
            monkeypatch.setitem(ls.DRAIN_ACTIONS, kind,
                                (lambda tag: lambda w, rows:
                                 calls.append(tag) or {"ok": True})(kind))
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1")
        se.append(ws, se.KIND_SETTLE_COMPLETED, claim="C-2")
        receipt = ls.drain_events(ws)
        assert sorted(calls) == [se.KIND_GATE_REJECT, se.KIND_SETTLE_COMPLETED]
        assert receipt["drained"] == 2

    def test_drain_table_covers_the_closed_vocabulary(self):
        assert set(ls.DRAIN_ACTIONS) == set(se.KINDS)

    def test_quiet_stream_drains_to_zero_without_face_calls(
            self, ws, monkeypatch):
        calls: list[str] = []
        for kind in se.KINDS:
            monkeypatch.setitem(ls.DRAIN_ACTIONS, kind,
                                (lambda tag: lambda w, rows:
                                 calls.append(tag) or {})(kind))
        receipt = ls.drain_events(ws)
        assert receipt["drained"] == 0
        assert calls == []

    def test_wake_faces_are_registered_declarations(self):
        """The consumption wiring's registry face: the watcher (os
        channel) and the drain (cli channel) are declared mechanisms —
        the registry validates and the two entries ride the declared
        out-of-session / CLI faces."""
        import mechanism_scheduler as ms
        result = ms.validate_registry()
        assert result["ok"] is True, result["errors"]
        entries, errors = ms.load_registry()
        assert not errors
        by_name = {e["name"]: e for e in entries}
        watch = by_name["scheduler_event_watch"]
        drain = by_name["scheduler_event_drain"]
        assert watch["channel"] == "os" and watch["entry"] == \
            "scripts/scheduler_watch.py"
        assert drain["channel"] == "cli" and drain["entry"] == \
            "scripts/loop_scheduler.py"

    def test_quiet_day_replay_harness_pins_and_metric(self):
        """EXP-C1's committed harness: drives the REAL watcher face over
        synthetic quiet/material/noise days, pins hold, and the
        acceptance's quiet_tokens metric row reads 0."""
        harness = ROOT / "experiments" / "scheduler" / "quiet_day_replay.py"
        assert harness.is_file()  # committed via the tracked-home allowlist
        spec = importlib.util.spec_from_file_location(
            "_quiet_day_replay_test", harness)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.run_replay(seed=1001)
        assert mod.check_pins(result) == []
        metrics = {m["metric"]: m for m in mod.metric_rows(result)}
        assert metrics["quiet_tokens"] is not None
        assert metrics["quiet_tokens"]["value"] == 0

    def test_drain_cli_prints_the_receipt(self, ws, capsys):
        se.append(ws, se.KIND_GATE_REJECT, claim="C-1")
        rc = ls.main([str(ws), "--drain-events"])
        assert rc == 0
        receipt = json.loads(capsys.readouterr().out)
        assert receipt["drained"] == 1
        # idempotent through the CLI face too
        assert ls.main([str(ws), "--drain-events"]) == 0
        assert json.loads(capsys.readouterr().out)["drained"] == 0
