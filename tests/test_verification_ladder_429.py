# -*- coding: utf-8 -*-
"""tests/test_verification_ladder_429.py — the verification ladder (T0/T1/T2)
plus mainline ΔV decision recording (issue 429 §1/§8, W2-T2.4).

Pins:
  T1  mid-round oracle probe trigger for long rounds: verified-write
      debounce coalesces N writes into ONE probe batch; a min-interval
      floor separates batches; firing consumes the existing oracle cadence
      face (wired, never rebuilt).
  T2  round-close priority queue over sides ordered by UNBLOCKING VALUE:
      stalled sides first (no-evidence most-stalled, then oldest
      evidence), active sides after; terminal sides excluded; drain pops
      the head up to budget and persists the remainder.
  ΔV  mainline decision rows on the rollout ledger, kind
      "mainline_decision" (same pipeline as round_credit): pure
      mechanical replay of the situation stream, closed action
      vocabulary, deterministic v_anchor deltas, optional sampling
      provenance; recording is idempotent (same ledger -> same rows).
  Wiring: mechanism registry entry + long_round gate + the runner's
      worker-return recording face.
All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rollout_ledger as rl  # noqa: E402
import state_signature as ssig  # noqa: E402
import verification_ladder as vl  # noqa: E402


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc)


NOW = _parse("2026-09-29T12:00:00Z")


def _register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}), encoding="utf-8")


def _signal(ws: Path, kind: str, ts: str, **fields) -> None:
    p = ws / "runs" / "signals.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": ts, "kind": kind}
    row.update(fields)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _situation(ws: Path, ts: str, trigger: str, state: dict,
               tick: int = 1) -> None:
    p = ws / "runs" / "situation-stream.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"schema": ssig.SITUATION_SCHEMA, "ts": ts, "trigger": trigger,
           "tick": tick, "state": state,
           "signature": ssig.signature_str(state),
           "signature_hash": ssig.signature_hash(state)}
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _snap(facts: int = 0, verified: int = 0, chain: tuple | None = None,
          budget_present: bool = False, fraction: float = 0.0) -> dict:
    return {
        "schema": ssig.SCHEMA,
        "facts": {"count": facts, "verified": verified,
                  "bucket": ssig.fact_bucket(facts)},
        "claims": {"pattern": ""},
        "budget": {"fraction": fraction,
                   "bucket": ssig.budget_bucket(fraction),
                   "present": budget_present},
        "chain": None if chain is None else {"k": chain[0], "n": chain[1]},
        "phase": None,
        "sides": {},
    }


def _evidence(ws: Path, claim: str, age_min: float,
              verdict: str = "passes") -> Path:
    """A verify-note evidence file with a controlled mtime (the outcome
    capture convention: name contains '-verify-', claim_id frontmatter)."""
    p = ws / "runs" / f"{claim}-verify-note.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"---\nclaim_id: {claim}\n---\n\n## Overall verdict\n"
                 f"{verdict}\n", encoding="utf-8")
    stamp = NOW.timestamp() - age_min * 60
    os.utime(p, (stamp, stamp))
    return p


# ---------- T1: long-round trigger + debounced probe batch ------------------

class TestT1Trigger:
    def test_fresh_workspace_not_due(self, tmp_path):
        due = vl.t1_due(tmp_path, now=NOW)
        assert due["due"] is False
        assert due["pending_writes"] == 0

    def test_long_round_fires(self, tmp_path):
        """The RED-pinned core: the trigger fires on a long-round fixture
        (>= threshold coalesced writes), never on a short one."""
        for i in range(vl.T1_ROUND_TURNS_THRESHOLD):
            _signal(tmp_path, "deliver", _ts(NOW - timedelta(minutes=i)),
                    claim=f"C-{i}")
        due = vl.t1_due(tmp_path, now=NOW)
        assert due["due"] is True
        assert due["pending_writes"] >= vl.T1_ROUND_TURNS_THRESHOLD

    def test_short_round_not_due(self, tmp_path):
        _signal(tmp_path, "deliver", _ts(NOW), claim="C-1")
        due = vl.t1_due(tmp_path, now=NOW)
        assert due["due"] is False

    def test_note_write_feeds_the_same_counter(self, tmp_path):
        for _ in range(vl.T1_ROUND_TURNS_THRESHOLD):
            vl.note_write(tmp_path, ts=_ts(NOW))
        due = vl.t1_due(tmp_path, now=NOW)
        assert due["due"] is True

    def test_debounce_coalesces_writes_into_one_batch(self, tmp_path):
        """N writes coalesce into ONE probe batch: the first fire consumes
        the whole batch (one cadence call, counter reset), the immediate
        second fire is a no-op."""
        calls: list[Path] = []

        def _fake_cadence(ws, **kw):
            calls.append(Path(ws))
            return {"fired": False, "reason": "no_armed_cases"}

        import oracle_cadence
        orig = oracle_cadence.run_cadence
        oracle_cadence.run_cadence = _fake_cadence
        try:
            for _ in range(vl.T1_ROUND_TURNS_THRESHOLD + 2):
                vl.note_write(tmp_path, ts=_ts(NOW))
            first = vl.fire_t1(tmp_path, now=NOW)
            second = vl.fire_t1(tmp_path, now=NOW)
        finally:
            oracle_cadence.run_cadence = orig
        assert first["fired"] is True
        assert second["fired"] is False
        assert len(calls) == 1  # ONE batch for N coalesced writes

    def test_min_interval_separates_batches(self, tmp_path):
        """A second batch is not due until the min interval elapses after
        the previous probe."""
        vl.note_write(tmp_path, n=vl.T1_ROUND_TURNS_THRESHOLD, ts=_ts(NOW))
        vl.fire_t1(tmp_path, now=NOW)
        vl.note_write(tmp_path, n=vl.T1_ROUND_TURNS_THRESHOLD,
                      ts=_ts(NOW + timedelta(minutes=1)))
        soon = vl.t1_due(tmp_path, now=NOW + timedelta(minutes=5))
        assert soon["due"] is False
        late = vl.t1_due(
            tmp_path, now=NOW + timedelta(minutes=vl.T1_MIN_INTERVAL_MIN + 1))
        assert late["due"] is True

    def test_fire_emits_registered_probe_event(self, tmp_path):
        import event_taxonomy
        assert "oracle_probe_t1" in event_taxonomy.EMIT_ACTIONS
        for _ in range(vl.T1_ROUND_TURNS_THRESHOLD):
            vl.note_write(tmp_path, ts=_ts(NOW))
        res = vl.fire_t1(tmp_path, now=NOW)
        assert res["fired"] is True
        rows = [
            json.loads(line)
            for line in (tmp_path / "runs" / "logs").glob("kunglao-*.jsonl")
            for line in line.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert any(r.get("action") == "oracle_probe_t1" for r in rows)


# ---------- T2: unblocking-value priority queue -----------------------------

class TestT2Queue:
    def _fixture(self, ws: Path) -> None:
        _register(ws, [
            {"id": "C-001", "status": "OPEN"},
            {"id": "C-002", "status": "OPEN"},
            {"id": "C-003", "status": "OPEN"},
            {"id": "C-004", "status": "PROVEN"},
        ])
        _evidence(ws, "C-001", age_min=200)   # stale -> stalled
        _evidence(ws, "C-002", age_min=5)     # fresh -> active
        # C-003: no evidence at all -> most stalled

    def test_stalled_sides_first_active_after_terminal_excluded(self, tmp_path):
        self._fixture(tmp_path)
        q = vl.build_t2_queue(tmp_path, now=NOW)["queue"]
        ids = [e["claim_id"] for e in q]
        assert "C-004" not in ids          # terminal sides are closure, excluded
        assert ids[0] == "C-003"           # no evidence = most stalled
        assert ids[1] == "C-001"           # stale evidence next
        assert ids[-1] == "C-002"          # active last
        assert q[0]["stalled"] is True
        assert q[-1]["stalled"] is False

    def test_within_class_oldest_evidence_first(self, tmp_path):
        _register(tmp_path, [
            {"id": "C-001", "status": "OPEN"},
            {"id": "C-002", "status": "OPEN"},
        ])
        _evidence(tmp_path, "C-001", age_min=90)
        _evidence(tmp_path, "C-002", age_min=30)
        q = vl.build_t2_queue(tmp_path, now=NOW)["queue"]
        assert [e["claim_id"] for e in q] == ["C-001", "C-002"]

    def test_stall_threshold_respected(self, tmp_path):
        _register(tmp_path, [{"id": "C-001", "status": "OPEN"}])
        _evidence(tmp_path, "C-001", age_min=10)
        q = vl.build_t2_queue(tmp_path, now=NOW, stall_min=60)["queue"]
        assert q[0]["stalled"] is False

    def test_drain_pops_head_persists_remainder(self, tmp_path):
        self._fixture(tmp_path)
        res = vl.drain_t2_queue(tmp_path, budget=2, now=NOW)
        assert [e["claim_id"] for e in res["dispatched"]] == ["C-003", "C-001"]
        assert [e["claim_id"] for e in res["remaining"]] == ["C-002"]
        doc = json.loads(
            (tmp_path / "runs" / "t2-queue.json").read_text(encoding="utf-8"))
        assert doc["schema"] == vl.T2_QUEUE_SCHEMA
        assert [e["claim_id"] for e in doc["remaining"]] == ["C-002"]

    def test_queue_is_deterministic(self, tmp_path):
        self._fixture(tmp_path)
        a = vl.build_t2_queue(tmp_path, now=NOW)
        b = vl.build_t2_queue(tmp_path, now=NOW)
        assert a["queue"] == b["queue"]

    def test_round_close_persists_and_emits(self, tmp_path):
        import event_taxonomy
        assert "t2_queue_built" in event_taxonomy.EMIT_ACTIONS
        self._fixture(tmp_path)
        res = vl.round_close(tmp_path, now=NOW)
        assert res["built"] is True
        assert res["queued"] == 3
        assert (tmp_path / "runs" / "t2-queue.json").is_file()
        rows = [
            json.loads(line)
            for line in (tmp_path / "runs" / "logs").glob("kunglao-*.jsonl")
            for line in line.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        assert any(r.get("action") == "t2_queue_built" for r in rows)

    def test_round_close_without_register_is_fail_open(self, tmp_path):
        res = vl.round_close(tmp_path, now=NOW)
        assert res["built"] is False
        assert res["reason"] == "no-register"


# ---------- mainline ΔV decision rows ---------------------------------------

class TestMainlineRows:
    def test_kind_is_registered_central(self):
        assert "mainline_decision" in rl.kinds()

    def test_actions_are_the_closed_vocabulary(self):
        assert vl.MAINLINE_ACTIONS == (
            "spawn", "switch", "allocate", "park_revive", "conclude")

    def test_first_snapshot_yields_no_row(self, tmp_path):
        _situation(tmp_path, _ts(NOW), "worker_return", _snap(facts=2))
        assert vl.mainline_rows(tmp_path) == []

    def test_worker_return_pair_maps_to_spawn_with_delta(self, tmp_path):
        """The RED-pinned row schema: s_M signature, closed action, ΔV from
        the deterministic v_anchor face."""
        before = _snap(facts=0)
        after = _snap(facts=2, verified=1, chain=(1, 3))
        _situation(tmp_path, _ts(NOW - timedelta(minutes=30)),
                   "worker_return", before)
        _situation(tmp_path, _ts(NOW), "terminal", after)
        rows = vl.mainline_rows(tmp_path)
        assert len(rows) == 1
        row = rows[0]
        assert row["action"] == "conclude"   # the trigger-derived mapping
        assert row["delta_v"] == pytest.approx(
            ssig.v_anchor(after) - ssig.v_anchor(before))
        assert row["state_signature"] == ssig.signature_str(after)
        assert row["state_signature_hash"] == ssig.signature_hash(after)
        assert row["rollout_id"] == (
            f"mainline_decision/{_ts(NOW)}")

    def test_replay_is_deterministic(self, tmp_path):
        _situation(tmp_path, _ts(NOW - timedelta(minutes=30)),
                   "worker_return", _snap(facts=0))
        _situation(tmp_path, _ts(NOW), "terminal", _snap(facts=2))
        assert vl.mainline_rows(tmp_path) == vl.mainline_rows(tmp_path)

    def test_unknown_trigger_maps_to_switch(self, tmp_path):
        _situation(tmp_path, _ts(NOW - timedelta(minutes=30)),
                   "worker_return", _snap(facts=0))
        _situation(tmp_path, _ts(NOW), "premise_shift", _snap(facts=1))
        rows = vl.mainline_rows(tmp_path)
        assert rows[0]["action"] == "switch"


class TestMainlineLedger:
    def _stream(self, ws: Path) -> None:
        _situation(ws, _ts(NOW - timedelta(minutes=30)), "worker_return",
                   _snap(facts=0))
        _situation(ws, _ts(NOW), "terminal", _snap(facts=4, verified=2,
                                                   chain=(2, 3)))

    def test_settle_lands_row_with_all_fields(self, tmp_path):
        self._stream(tmp_path)
        res = vl.settle_mainline_decisions(tmp_path, ts=_ts(NOW))
        assert res["settled"] == 1
        rid = f"mainline_decision/{_ts(NOW)}"
        fold = rl.fold(tmp_path, rid)
        assert fold is not None
        assert fold["kind"] == "mainline_decision"
        types = {s["type"] for s in fold["signals"]}
        assert {"state_before", "action", "delta_v"} <= types
        st = fold["settlement"]
        row = vl.mainline_rows(tmp_path)[0]
        assert st["reward"] == pytest.approx(row["delta_v"])
        assert st["band"] == vl.BAND_MAINLINE
        assert st["rule_id"] == vl.RULE_MAINLINE
        assert st["evidence_refs"]

    def test_settle_is_idempotent_same_ledger_same_rows(self, tmp_path):
        """Determinism pin: replaying the same stream twice appends nothing
        new and the folded row is unchanged."""
        self._stream(tmp_path)
        first = vl.settle_mainline_decisions(tmp_path, ts=_ts(NOW))
        rid = f"mainline_decision/{_ts(NOW)}"
        before = rl.fold(tmp_path, rid)
        second = vl.settle_mainline_decisions(tmp_path, ts=_ts(NOW))
        assert second["settled"] == 0
        assert rl.fold(tmp_path, rid) == before
        assert first["rows"] == second["rows"]

    def test_explicit_api_refuses_unknown_action(self, tmp_path):
        res = vl.record_mainline_decision(
            tmp_path, "teleport", before=_snap(), after=_snap(facts=1),
            ts=_ts(NOW))
        assert res["recorded"] is False
        assert "action" in res["reason"]

    def test_explicit_api_carries_sampling_provenance(self, tmp_path):
        """P_LLM⊗Q sampling provenance rides the row when the dispatch
        face used it (record-first, learn later)."""
        res = vl.record_mainline_decision(
            tmp_path, "switch", before=_snap(facts=1), after=_snap(facts=2),
            sampling={"mode": "P_LLM⊗Q", "llm_proposal": "switch",
                      "q_adjust": 0.0},
            ts=_ts(NOW))
        assert res["recorded"] is True
        fold = rl.fold(tmp_path, res["rollout_id"])
        prov = [s for s in fold["signals"]
                if s["type"] == "sampling_provenance"]
        assert len(prov) == 1
        assert prov[0]["value"]["mode"] == "P_LLM⊗Q"

    def test_explicit_api_without_sampling_omits_the_signal(self, tmp_path):
        res = vl.record_mainline_decision(
            tmp_path, "spawn", before=_snap(), after=_snap(facts=1),
            ts=_ts(NOW))
        fold = rl.fold(tmp_path, res["rollout_id"])
        assert all(s["type"] != "sampling_provenance"
                   for s in fold["signals"])


# ---------- wiring: registry, gate, runner face ------------------------------

class TestWiring:
    def test_long_round_gate_registered(self, tmp_path):
        import mechanism_scheduler as ms
        assert "long_round" in ms.GATES
        assert ms.GATES["long_round"](tmp_path, set()) is False
        for _ in range(vl.T1_ROUND_TURNS_THRESHOLD):
            vl.note_write(tmp_path, ts=_ts(NOW))
        assert ms.GATES["long_round"](tmp_path, set()) is True

    def test_mechanism_registered_in_the_registry(self):
        import mechanism_scheduler as ms
        entries, errors = ms.load_registry()
        assert not errors
        names = {e["name"] for e in entries}
        assert "oracle_probe_t1" in names
        entry = next(e for e in entries if e["name"] == "oracle_probe_t1")
        assert entry["entry"] == "scripts/verification_ladder.py"
        assert entry["trigger"]["gate"] == "long_round"
        assert entry["cost_class"] in ("cheap", "medium", "expensive")
        assert entry["cockpit_signal"]

    def test_record_experience_wires_ladder_faces(self, tmp_path, monkeypatch):
        """The runner's worker-return recording face fires the round-close
        queue and the mainline settlement (fail-open cage unchanged)."""
        import eval_loop_runner as elr
        import experience_triples
        import tc_journal
        calls: list[str] = []
        monkeypatch.setattr(vl, "round_close",
                            lambda ws, **kw: calls.append("round_close"))
        monkeypatch.setattr(
            vl, "settle_mainline_decisions",
            lambda ws, **kw: calls.append("mainline"))
        monkeypatch.setattr(tc_journal, "harvest_from_log", lambda ws: None)
        monkeypatch.setattr(ssig, "append_snapshot",
                            lambda ws, trigger: None)
        monkeypatch.setattr(experience_triples, "extract", lambda ws: None)
        elr._record_experience(tmp_path, "worker_return")
        assert calls == ["round_close", "mainline"]

    def test_cli_t1_on_fresh_workspace_is_clean_noop(self, tmp_path):
        rc = vl.main([str(tmp_path), "--t1"])
        assert rc == 0


# ---------- tolerance + env-override + CLI faces ----------------------------

class TestToleranceAndCli:
    def test_corrupt_t1_state_reads_fresh(self, tmp_path):
        p = tmp_path / "runs" / ".ladder-t1.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json", encoding="utf-8")
        assert vl.t1_state(tmp_path) == {"last_probe_ts": None,
                                         "batches_fired": 0}
        due = vl.t1_due(tmp_path, now=NOW)
        assert due["due"] is False

    def test_garbage_last_probe_ts_never_wedges_the_trigger(self, tmp_path):
        """An unparseable probe stamp is honest absence: pending writes
        still count from the epoch, the interval floor does not apply."""
        p = tmp_path / "runs" / ".ladder-t1.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"last_probe_ts": "garbage",
                                 "batches_fired": 3}), encoding="utf-8")
        for _ in range(vl.T1_ROUND_TURNS_THRESHOLD):
            vl.note_write(tmp_path, ts=_ts(NOW))
        due = vl.t1_due(tmp_path, now=NOW)
        assert due["due"] is True

    def test_dirty_signal_rows_are_skipped(self, tmp_path):
        p = tmp_path / "runs" / "signals.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write("{junk\n")
            fh.write(json.dumps({"ts": _ts(NOW), "kind": "deliver"}) + "\n")
            fh.write(json.dumps({"ts": _ts(NOW), "kind": vl.T1_NOTE_KIND,
                                 "n": "not-a-number"}) + "\n")
        assert vl.pending_writes(tmp_path) == 2  # junk skipped, bad n -> 1

    def test_threshold_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KUNGLAO_T1_MIN_WRITES", "2")
        _signal(tmp_path, "deliver", _ts(NOW), claim="C-1")
        _signal(tmp_path, "deliver", _ts(NOW), claim="C-2")
        assert vl.t1_due(tmp_path, now=NOW)["due"] is True

    def test_interval_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KUNGLAO_T1_MIN_INTERVAL_MIN", "5")
        vl.note_write(tmp_path, n=vl.T1_ROUND_TURNS_THRESHOLD, ts=_ts(NOW))
        vl.fire_t1(tmp_path, now=NOW)
        vl.note_write(tmp_path, n=vl.T1_ROUND_TURNS_THRESHOLD,
                      ts=_ts(NOW + timedelta(minutes=1)))
        assert vl.t1_due(
            tmp_path, now=NOW + timedelta(minutes=6))["due"] is True

    def test_stall_min_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KUNGLAO_T2_STALL_MIN", "5")
        _register(tmp_path, [{"id": "C-001", "status": "OPEN"}])
        _evidence(tmp_path, "C-001", age_min=10)
        q = vl.build_t2_queue(tmp_path, now=NOW)["queue"]
        assert q[0]["stalled"] is True

    def test_unreadable_register_is_fail_open(self, tmp_path):
        p = tmp_path / "claim-register.yaml"
        p.write_text("{unparseable: [", encoding="utf-8")
        res = vl.build_t2_queue(tmp_path, now=NOW)
        assert res["built"] is False
        assert res["reason"] == "register-unreadable"

    def test_drain_without_register_is_empty(self, tmp_path):
        res = vl.drain_t2_queue(tmp_path, now=NOW)
        assert res["dispatched"] == []
        assert res["remaining"] == []

    def test_redteam_evidence_counts_for_staleness(self, tmp_path):
        _register(tmp_path, [{"id": "C-001", "status": "OPEN"}])
        p = tmp_path / "runs" / "verify-redteam-C-001.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("claim: C-001\nRED-TEAM VERDICT: CONFIRMED\n",
                     encoding="utf-8")
        stamp = NOW.timestamp() - 120 * 60
        os.utime(p, (stamp, stamp))
        q = vl.build_t2_queue(tmp_path, now=NOW)["queue"]
        assert q[0]["stalled"] is True
        assert "evidence-age" in q[0]["reason"]

    def test_cli_missing_workspace_rc2(self, tmp_path):
        assert vl.main([str(tmp_path / "absent"), "--t1"]) == 2

    def test_cli_without_flag_prints_help_rc2(self, tmp_path, capsys):
        assert vl.main([str(tmp_path)]) == 2
        assert "usage" in capsys.readouterr().err.lower()

    def test_cli_t2_persists_queue_rc0(self, tmp_path):
        _register(tmp_path, [{"id": "C-001", "status": "OPEN"}])
        rc = vl.main([str(tmp_path), "--t2"])
        assert rc == 0
        assert (tmp_path / "runs" / "t2-queue.json").is_file()
