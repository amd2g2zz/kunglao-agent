# -*- coding: utf-8 -*-
"""tests/test_rollout_ledger_366.py — unified rollout ledger (U1).

The ONE rollout row schema for all RLVA rollout kinds: append-only
runs/rollout-ledger.jsonl, kinds registered centrally (open enum), the
settled(kind, window) query is the ONE prior-feed interface (U4's
consumer face is tested against compute_priors in
test_reward_adapters_366.py).

Acceptance checkboxes covered here:
  - Row schema lint + append-only enforcement tested.
  - Prior interface: one call returns settled rows filtered by kind/window
    (mixed kinds).
All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rollout_ledger as rl  # noqa: E402


def _sig(type_: str, source: str, value, ts="2026-09-24T00:00:00Z",
         **extra):
    sig = {"type": type_, "source": source, "value": value, "ts": ts}
    sig.update(extra)
    return sig


# ---------- kinds registry (open enum, registered centrally) ----------

class TestKindsRegistry:
    def test_initial_kinds_registered(self):
        assert set(rl.ROLLOUT_KINDS) >= {"task", "self_distill", "hybrid_distill"}

    def test_unregistered_kind_refused(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        res = rl.record(ws, kind="alien_kind", anchor="x-1",
                        signals=[_sig("s", "src", 1)])
        assert res["appended"] is False
        assert "kind" in res.get("reason", "")

    def test_register_kind_extends_the_enum(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        assert rl.register_kind("future_kind", note="scrub test") is True
        res = rl.record(ws, kind="future_kind", anchor="x-2",
                        signals=[_sig("s", "src", 1)])
        assert res["appended"] is True
        # re-registration is idempotent
        assert rl.register_kind("future_kind") is False


# ---------- schema lint ----------

class TestSchemaLint:
    def test_valid_row_lints_clean(self):
        row = {"rollout_id": "task/C-1", "kind": "task", "anchor": "C-1",
               "ts": "2026-09-24T00:00:00Z",
               "signals": [_sig("oracle_verdict", "oracle_runner", "pass")],
               "reward": None, "settlement": None}
        assert rl.row_schema_lint(row) == []

    def test_missing_fields_flagged(self):
        assert rl.row_schema_lint({"kind": "task"}) != []

    def test_bad_signal_shape_flagged(self):
        row = {"rollout_id": "t", "kind": "task", "anchor": "a",
               "ts": "2026-09-24T00:00:00Z",
               "signals": [{"type": "s"}],  # missing source/value/ts
               "reward": None, "settlement": None}
        assert any("signal" in e for e in rl.row_schema_lint(row))

    def test_reward_and_settlement_null_until_settled(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="task", anchor="C-9",
                  signals=[_sig("claim_terminal", "rollup", "PROVEN")])
        row = rl.read(ws)[0]
        assert row["reward"] is None and row["settlement"] is None

    def test_dirty_rows_skipped_on_read(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        p = ws / "runs" / "rollout-ledger.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text('{"rollout_id": "a"}\nnot json at all\n\n'
                     '{"rollout_id": "b", "kind": "task", "anchor": "a", '
                     '"ts": "2026-09-24T00:00:00Z", "signals": [], '
                     '"reward": null, "settlement": null}\n',
                     encoding="utf-8")
        rows = rl.read(ws)
        assert [r.get("rollout_id") for r in rows] == ["b"]


# ---------- append-only enforcement ----------

class TestAppendOnly:
    def test_append_never_rewrites_existing_bytes(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="task", anchor="C-1",
                  signals=[_sig("s1", "src", 1)])
        rl.settle(ws, "task/C-1",
                  settlement={"reward": 1.0, "band": "SETTLED_GREEN",
                              "rule_id": "task/oracle-green",
                              "evidence_refs": ["runs/oracle-status.json"]})
        p = ws / "runs" / "rollout-ledger.jsonl"
        after_first = p.read_bytes()
        # a later activity on ANOTHER rollout must only append
        rl.record(ws, kind="task", anchor="C-2",
                  signals=[_sig("s1", "src", 2)])
        data = p.read_bytes()
        assert data.startswith(after_first)

    def test_settlement_is_an_amendment_not_a_rewrite(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="self_distill", anchor="lesson-a",
                  signals=[_sig("lesson_written", "rollup", "sig-1")])
        before = (ws / "runs" / "rollout-ledger.jsonl").read_bytes()
        rl.settle(ws, "self_distill/lesson-a",
                  settlement={"reward": 0.0, "band": "NEUTRAL",
                              "rule_id": "self_distill/pending",
                              "evidence_refs": ["lesson_written"]})
        data = (ws / "runs" / "rollout-ledger.jsonl").read_bytes()
        assert data.startswith(before)  # append-only: original row intact
        assert len(rl.read(ws)) == 2    # identity row + settlement amendment

    def test_locked_append_survives_concurrent_writers(self, tmp_path):
        """Two writers racing on the same ledger both land (the .lock file
        serializes the append section)."""
        ws = tmp_path / "ws"
        ws.mkdir()
        n = 20
        import threading
        def worker(i: int) -> None:
            rl.record(ws, kind="task", anchor=f"C-{i:03d}",
                      signals=[_sig("s", "src", i)])
        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        rows = rl.read(ws)
        assert len(rows) == n
        assert len({r["rollout_id"] for r in rows}) == n

    def test_lock_file_pattern_used(self):
        """The lock is a .lock file next to the ledger (the repo's pattern)."""
        assert rl.LOCK_REL.endswith(".lock")
        assert "runs" in rl.LOCK_REL


# ---------- record(): identity append + dedupe ----------

class TestRecord:
    def test_record_appends_once_per_signal_set(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        sigs = [_sig("claim_terminal", "rollup", "PROVEN")]
        a = rl.record(ws, kind="task", anchor="C-1", signals=sigs)
        b = rl.record(ws, kind="task", anchor="C-1", signals=sigs)
        assert a["appended"] and not b["appended"]
        assert len(rl.read(ws)) == 1

    def test_grown_signal_set_lands_as_amendment(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="task", anchor="C-1",
                  signals=[_sig("claim_terminal", "rollup", "DEFERRED")])
        res = rl.record(ws, kind="task", anchor="C-1",
                        signals=[_sig("claim_terminal", "rollup", "PROVEN"),
                                 _sig("oracle_verdict", "oracle_runner", "pass")])
        assert res["appended"] is True
        fold = rl.fold(ws, "task/C-1")
        assert fold["signals"][0]["value"] == "PROVEN"
        assert len(fold["signals"]) == 2

    def test_rollout_id_defaults_to_kind_anchor(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="self_distill", anchor="lesson-x",
                  signals=[_sig("lesson_written", "rollup", "sig")])
        assert rl.read(ws)[0]["rollout_id"] == "self_distill/lesson-x"


# ---------- fold + settled() (the ONE prior interface) ----------

class TestSettledQuery:
    def _seed_mixed(self, ws: Path) -> None:
        rl.record(ws, kind="task", anchor="C-1",
                  signals=[_sig("claim_terminal", "rollup", "PROVEN"),
                           _sig("oracle_verdict", "oracle_runner", "pass")])
        rl.settle(ws, "task/C-1",
                  settlement={"reward": 1.0, "band": "SETTLED_GREEN",
                              "rule_id": "task/oracle-green",
                              "evidence_refs": ["runs/oracle-status.json"]})
        rl.record(ws, kind="self_distill", anchor="lesson-a",
                  signals=[_sig("lesson_written", "rollup", "sig-a")])
        rl.settle(ws, "self_distill/lesson-a",
                  settlement={"reward": 0.0, "band": "NEUTRAL",
                              "rule_id": "self_distill/pending",
                              "evidence_refs": ["lesson_written"]})
        rl.record(ws, kind="self_distill", anchor="lesson-b",
                  signals=[_sig("lesson_written", "rollup", "sig-b")])
        # lesson-b intentionally left unsettled

    def test_settled_filters_by_kind(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        self._seed_mixed(ws)
        task = rl.settled(ws, kind="task")
        assert len(task) == 1
        assert task[0]["band"] == "SETTLED_GREEN"
        sd = rl.settled(ws, kind="self_distill")
        assert len(sd) == 1
        assert sd[0]["rollout_id"] == "self_distill/lesson-a"

    def test_settled_unsettled_rows_excluded(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        self._seed_mixed(ws)
        ids = {r["rollout_id"] for r in rl.settled(ws)}
        assert "self_distill/lesson-b" not in ids

    def test_settled_window_by_ts(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="task", anchor="C-1",
                  signals=[_sig("s", "src", 1, ts="2026-09-01T00:00:00Z")])
        rl.settle(ws, "task/C-1",
                  settlement={"reward": 1.0, "band": "SETTLED_GREEN",
                              "rule_id": "task/oracle-green",
                              "evidence_refs": []},
                  ts="2026-09-01T01:00:00Z")
        rl.record(ws, kind="task", anchor="C-2",
                  signals=[_sig("s", "src", 2, ts="2026-09-20T00:00:00Z")])
        rl.settle(ws, "task/C-2",
                  settlement={"reward": 0.0, "band": "SETTLED_RED",
                              "rule_id": "task/oracle-red",
                              "evidence_refs": []},
                  ts="2026-09-20T01:00:00Z")
        win = rl.settled(ws, window=("2026-09-15T00:00:00Z", None))
        assert [r["rollout_id"] for r in win] == ["task/C-2"]
        win2 = rl.settled(ws, window=(None, "2026-09-15T00:00:00Z"))
        assert [r["rollout_id"] for r in win2] == ["task/C-1"]

    def test_settled_row_carries_signals_from_identity(self, tmp_path):
        """The prior feed reads one row that folds identity + signals +
        settlement (no second read path needed)."""
        ws = tmp_path / "ws"
        ws.mkdir()
        self._seed_mixed(ws)
        row = rl.settled(ws, kind="task")[0]
        types = {s["type"] for s in row["signals"]}
        assert types == {"claim_terminal", "oracle_verdict"}
        assert row["settlement"]["rule_id"] == "task/oracle-green"
        assert row["reward"] == 1.0

    def test_pending_settlement_lists_unsettled_folds(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        self._seed_mixed(ws)
        pend = rl.pending_settlement(ws)
        assert [p["rollout_id"] for p in pend] == ["self_distill/lesson-b"]

    def test_settled_missing_ledger_is_empty(self, tmp_path):
        assert rl.settled(tmp_path / "nope") == []


# ---------- persistence shape ----------

class TestPersistence:
    def test_rows_are_jsonl_with_schema_stamp(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        rl.record(ws, kind="task", anchor="C-1",
                  signals=[_sig("s", "src", 1)])
        p = ws / "runs" / "rollout-ledger.jsonl"
        lines = p.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["schema"] == rl.SCHEMA
        assert row["kind"] == "task"

    def test_import_surface_is_machine_only(self):
        """The ledger module itself must not drag any model-call surface
        into the settlement currency's write path (defense in depth — the
        engine-level test lives in test_reward_settlement_366)."""
        import ast
        tree = ast.parse((SCRIPTS / "rollout_ledger.py").read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        banned = ("llm", "model", "judge", "anthropic", "openai",
                  "subprocess", "socket", "urllib", "http")
        bad = [m for m in imported for b in banned if b in m.lower()]
        assert not bad, f"rollout_ledger must stay machine-only, saw {bad}"
