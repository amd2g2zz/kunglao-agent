# -*- coding: utf-8 -*-
"""#127 mechanism utilization — injection trip-tests + liveness contract.

Mutation discipline applied to detectors (issue body): a fixture
DELIBERATELY constructs the pathology and asserts the detector FIRES into
a consumed face — not merely that it returns a dict.

Red-first pairs in this file (the red/green commit pair IS the proof):
  - test_mission_stall_trips_on_epsilon_wiggle: RED against the exact
    float-equality flatness rule (wiggle never trips), GREEN after the
    V_M_FLAT_TOLERANCE band (E2 derivation: wiggle <= 3e-3 must classify
    FLAT, real movement >= 1e-1 must not; T = 1e-2 = geometric midpoint).
  - test_fake_success_flag_is_consumed: RED while the settlement retro's
    FAKE-SUCCESS flag lands only in runs/<ts>-retro-<claim>.md (consumed
    by nothing), GREEN once the flag joins runs/.retro-index.json — the
    index dispatch_gate's micro-retro already reads.
  - test_dormant_flag_fires: RED until detector liveness exists (#600
    DORMANT sentinel generalized).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mission_stall  # noqa: E402
from convergence_health import (  # noqa: E402
    EXIT_SPINNING,
    EXIT_STALLED,
    STALLED_FLATLINE,
    assess,
)


# ---------- fixtures ----------

def _mk_ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(
        {"claims": [{"id": "C-1", "status": "OPEN"}]}), encoding="utf-8")
    return ws


def _write_history(ws: Path, v_ms: list) -> None:
    """Hand-seeded mission ledger history (the schema stall_mission reads:
    runs/mission_ledger.yaml -> mission.history[i].v_m)."""
    led = {"mission": {"pqs": [], "beta": 0.3, "feature_used": True,
                       "history": [{"ts": f"2026-09-07T00:00:{i:02d}Z",
                                    "v_m": v} for i, v in enumerate(v_ms)]}}
    (ws / "runs" / "mission_ledger.yaml").write_text(
        yaml.safe_dump(led, allow_unicode=True, sort_keys=False),
        encoding="utf-8")


def _snap(ts: str, open_count: int, open_ids: list, facts_total: int,
          dispatched_ids: list) -> dict:
    """One convergence-ledger snapshot row (new format: carries
    dispatched_ids). ts values are spaced > SAME_TURN_WINDOW_SEC so the
    dedup pressure valve never collapses the injected trajectory."""
    return {"ts": ts, "open_count": open_count, "open_ids": open_ids,
            "facts_total": facts_total, "dispatched_ids": dispatched_ids}


# ---------- 1. mission_stall: epsilon wiggle must trip (RED first) ----------

def test_mission_stall_trips_on_epsilon_wiggle(tmp_path):
    """Cheap settlements jitter the ledger tail by ~1e-3 — never exactly
    equal. A wired detector that cannot fire under this noise is false
    confidence; the flatness rule must be a tolerance band."""
    ws = _mk_ws(tmp_path)
    _write_history(ws, [1.0, 1.001, 0.999, 1.002, 1.0])
    r = mission_stall.stall_mission(ws, k=3)
    assert r["consecutive_flat"] >= 3, (
        f"epsilon wiggle must classify FLAT, got {r}")
    assert r["stalled"] is True


def test_mission_stall_does_not_trip_on_real_movement(tmp_path):
    """The tolerance must NOT swallow genuine progress: a >= 0.1 move per
    checkpoint (a real PQ settlement) keeps the detector quiet."""
    ws = _mk_ws(tmp_path)
    _write_history(ws, [1.0, 1.1, 1.2, 1.3, 1.4])
    r = mission_stall.stall_mission(ws, k=3)
    assert r["consecutive_flat"] < 3
    assert r["stalled"] is False


# ---------- 2. convergence_health: flatline + churn injections ----------

def test_convergence_health_flatline_injection():
    """Inject 7 same-state snapshots (open work held 7 rounds, dispatch
    evidence present so nothing counts as 'stuck') -> the FLATLINE signal
    fires STALLED with flatline_run >= STALLED_FLATLINE."""
    ledger = [_snap(f"2026-09-07T00:{m:02d}:00Z", 3,
                    ["C-1", "C-2", "C-3"], 10, [])
              for m in range(10, 17)]
    r = assess(ledger)
    assert r["flatline_run"] >= STALLED_FLATLINE
    assert r["verdict"] == "STALLED"
    assert r["exit_code"] == EXIT_STALLED


def test_convergence_health_churn_injection():
    """Inject facts growing +6 while open_count holds -> the CHURN signal
    fires SPINNING (busy spin masquerading as convergence)."""
    ledger = [_snap(f"2026-09-07T00:{m:02d}:00Z", 3,
                    ["C-1", "C-2", "C-3"], facts, ["C-1", "C-2", "C-3"])
              for m, facts in zip(range(10, 15), (10, 11, 12, 13, 16))]
    r = assess(ledger)
    assert r["churn"]["is_churning"] is True, (
        f"facts +6 with open_count held must flag churn, got {r['churn']}")
    assert r["verdict"] == "SPINNING"
    assert r["exit_code"] == EXIT_SPINNING


# ---------- 3. fake-success flag must reach a consumed face ----------

def test_fake_success_flag_is_consumed(tmp_path):
    """A PROVEN settlement over a static PQ categorical (answers_question
    present, PQ row never answered) is coverage theater. The settlement
    retro flags it — and the flag must join runs/.retro-index.json so the
    dispatch face's 前车之鉴 block surfaces it (the retro .md alone is
    consumed by nothing). NO new blocking semantics here (#130 owns that)."""
    from backtrack_loop import (  # noqa: E402
        micro_lessons_context,
        record_settlement,
        settlement_retro,
    )
    ws = _mk_ws(tmp_path)
    (ws / "claim-register.yaml").write_text(yaml.safe_dump(
        {"claims": [{"id": "C-1", "status": "PROVEN",
                     "answers_question": "pq1"}]}), encoding="utf-8")
    led = {"mission": {"pqs": [{"id": "pq1", "state": "unattempted",
                                "coverage": 0.0, "weight": 1.0,
                                "answered_by": [], "blocker": None,
                                "wake": None}],
                       "beta": 0.3, "history": [], "feature_used": True}}
    (ws / "runs" / "mission_ledger.yaml").write_text(
        yaml.safe_dump(led, allow_unicode=True, sort_keys=False),
        encoding="utf-8")

    # the real producer sequence (register_proven_gate.emit_settlements)
    record_settlement(ws, "C-1", "PROVEN", tools=["radare2"])
    retro = settlement_retro(ws, "C-1", to="PROVEN")
    assert retro is not None and retro.exists()

    index = json.loads((ws / "runs" / ".retro-index.json").read_text(
        encoding="utf-8"))
    flagged = [e for entries in index.values() if isinstance(entries, list)
               for e in entries if isinstance(e, dict)]
    with_flag = [e for e in flagged if e.get("fake_success")]
    assert with_flag, (
        f"FAKE-SUCCESS flag must join the retro index, index={index}")
    assert all("FAKE-SUCCESS" in f
               for e in with_flag for f in e["fake_success"])

    # the consumed face: dispatch_gate's micro-retro block renders the flag
    ctx = micro_lessons_context(ws, "C-1")
    assert ctx is not None and "FAKE-SUCCESS" in ctx


# ---------- 4. detector liveness: DORMANT flag (#600 generalized) ----------

def test_dormant_flag_fires(tmp_path):
    """A detector with evaluations > 0 and fires == 0 is DORMANT — it
    exists, it runs, it never fires (the exact mission_stall blindness
    this issue fixes). The liveness report must name it."""
    from detector_liveness import liveness_report  # noqa: E402
    ws = _mk_ws(tmp_path)
    log_dir = ws / "runs" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    rows = [
        {"ts": "2026-09-07T00:00:01Z", "actor": "mission_stall",
         "action": "detector_eval",
         "detail": json.dumps({"detector": "never_fires"})},
        {"ts": "2026-09-07T00:00:02Z", "actor": "mission_stall",
         "action": "detector_eval",
         "detail": json.dumps({"detector": "never_fires"})},
        {"ts": "2026-09-07T00:00:03Z", "actor": "convergence_health",
         "action": "detector_eval",
         "detail": json.dumps({"detector": "healthy_one"})},
        {"ts": "2026-09-07T00:00:04Z", "actor": "convergence_health",
         "action": "detector_fired",
         "detail": json.dumps({"detector": "healthy_one"})},
    ]
    (log_dir / "kunglao-2026-09-07.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    rep = liveness_report(ws)
    nf = rep["detectors"]["never_fires"]
    assert nf["evaluations"] == 2 and nf["fires"] == 0
    assert nf["status"] == "DORMANT"
    assert "never_fires" in rep["dormant"]
    assert rep["detectors"]["healthy_one"]["status"] == "ACTIVE"


def test_dormant_warn_one_time(tmp_path, capsys):
    """The #600 sentinel shape: the WARN prints ONCE + leaves a sentinel;
    the next observation is quiet even though the detector is still
    dormant. Fail-open when runs/ is unwritable is the caller's contract
    (heartbeat_tick wraps it)."""
    from detector_liveness import DORMANT_SENTINEL, dormant_warn
    ws = _mk_ws(tmp_path)
    log_dir = ws / "runs" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    rows = [{"ts": "t1", "actor": "mission_stall", "action": "detector_eval",
             "detail": json.dumps({"detector": "sleepy"})}]
    (log_dir / "kunglao-2026-09-07.jsonl").write_text(
        "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    first = dormant_warn(ws)
    assert first == ["sleepy"]
    out = capsys.readouterr().out
    assert "DORMANT" in out and "sleepy" in out
    assert (ws / DORMANT_SENTINEL).exists()

    second = dormant_warn(ws)
    assert second == [], "sentinel must make the WARN one-time"
    assert capsys.readouterr().out == ""


def test_no_detector_rows_is_no_data_not_dormant(tmp_path):
    """Absence of telemetry says nothing about utilization — a workspace
    with no detector rows must produce NO dormant names (the tick must
    not nag on a fresh workspace)."""
    from detector_liveness import dormant_warn, liveness_report
    ws = _mk_ws(tmp_path)
    rep = liveness_report(ws)
    assert rep["detectors"] == {} and rep["dormant"] == []
    assert dormant_warn(ws) == []
