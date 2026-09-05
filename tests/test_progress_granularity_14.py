# -*- coding: utf-8 -*-
"""tests/test_progress_granularity_14.py — #14 sub-PQ progress granularity.

One-vote-per-PQ progress overstates convergence: a PQ with one PROVEN of five
claims counts the same as a fully settled PQ, and open hypotheses / partial
facts inside an unresolved PQ move nothing until terminal. #14 replaces the
single vote with a weighted function of the PQ's claims' states (per-claim
credit), damps fractional credit on hard/max-difficulty samples (remaining
work is understated, never overstated), and lands the result ADDITIVELY —
raw coverage / v_m / v_norm fields and the #823 settlement math are untouched.

RED contract (every case below must fail before the GREEN implementation):
  1. PQ with 1 PROVEN of 3 claims → 0 < progress < 1 (pre-change: 0).
  2. answered PQ → progress exactly 1.0 regardless of shape (settlement
     authoritative, PR #69).
  3. PARTIALLY-VERIFIED contributes its 0.5 weight (PARTIAL of 2 → 0.25).
  4. IN_PROGRESS with recent activity → 0.25; stale in-flight → 0.0.
  5. max-difficulty open PQ < same-shape easy PQ; missing difficulty.json →
     undamped (equal to easy).
  6. additive: value_m raw fields, per_pq state/contrib, on-disk coverage,
     and the #823 anti-stupid edge-claim invariant all unchanged.
  7. cockpit_summary carries progress_fraction additively.
  8. CLI face (--progress) renders per-PQ bars; empty workspace → no crash.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import mission_ledger as ml  # noqa: E402

SCRIPTS = ROOT / "scripts"

# Fixed clock: freshness tests must not depend on wall time. Only the
# IN_PROGRESS recency classification consumes this — V_m units stay
# wall-clock-free (#10).
NOW = datetime(2026, 9, 5, 12, 0, 0, tzinfo=timezone.utc)


def _claim(cid, status="OPEN", answers=None, last_activity_at=None):
    c = {"id": cid, "status": status}
    if answers is not None:
        c["answers_question"] = answers
    if last_activity_at is not None:
        c["last_activity_at"] = last_activity_at
    return c


def _mk_ws(tmp_path, pqs, claims, tier=None, name="ws", spec_extra=None):
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True)
    spec = {"primary_questions": pqs}
    if spec_extra:
        spec.update(spec_extra)
    (ws / "task_spec.yaml").write_text(
        yaml.safe_dump(spec, allow_unicode=True), encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True), encoding="utf-8")
    if tier is not None:
        ev = ws / "evidence"
        ev.mkdir()
        (ev / "difficulty.json").write_text(
            json.dumps({"schema": "difficulty-calibration/1", "tier": tier}),
            encoding="utf-8")
    return ws


def _prog(ws, pq_id, now=NOW):
    v = ml.value_m(ws, now=now)
    return next(r for r in v["per_pq_progress"] if r["id"] == pq_id)


# ---------------------------------------------------------------------------
# 1-4: per-claim credit model
# ---------------------------------------------------------------------------


class TestPerClaimCredit:
    def test_proven_one_of_three_fractional(self, tmp_path):
        """1 PROVEN of 3 linked claims → strictly between 0 and 1 (was 0)."""
        ws = _mk_ws(tmp_path, [{"id": "q1"}],
                    [_claim("C-1", "PROVEN", "q1"),
                     _claim("C-2", "OPEN", "q1"),
                     _claim("C-3", "OPEN", "q1")])
        ml.init(ws, None)
        p = _prog(ws, "q1")
        assert 0.0 < p["progress"] < 1.0
        assert abs(p["progress"] - 1 / 3) < 1e-6
        assert p["claim_count"] == 3
        assert abs(p["credit"] - 1.0) < 1e-9

    def test_answered_pq_exactly_one(self, tmp_path):
        """Settlement (PR #69) is authoritative: answered stays exactly 1.0."""
        ws = _mk_ws(tmp_path, [{"id": "q1"}],
                    [_claim("C-1", "PROVEN", "q1"),
                     _claim("C-2", "OPEN", "q1")])
        ml.init(ws, None)
        ml.update(ws)
        assert _prog(ws, "q1")["progress"] == 1.0

    def test_partial_credit_half(self, tmp_path):
        """PARTIALLY-VERIFIED carries the 0.5 weight: 1 of 2 → 0.25."""
        ws = _mk_ws(tmp_path, [{"id": "q1"}],
                    [_claim("C-1", "PARTIALLY-VERIFIED", "q1"),
                     _claim("C-2", "OPEN", "q1")])
        ml.init(ws, None)
        p = _prog(ws, "q1")
        assert abs(p["credit"] - 0.5) < 1e-9
        assert abs(p["progress"] - 0.25) < 1e-9

    def test_in_progress_fresh_quarter(self, tmp_path):
        """IN_PROGRESS touched within the fresh window earns 0.25."""
        ws = _mk_ws(tmp_path, [{"id": "q1"}],
                    [_claim("C-1", "IN_PROGRESS", "q1",
                            last_activity_at="2026-09-05T11:00:00Z")])
        ml.init(ws, None)
        p = _prog(ws, "q1")
        assert abs(p["credit"] - 0.25) < 1e-9
        assert abs(p["progress"] - 0.25) < 1e-9

    def test_in_progress_stale_zero(self, tmp_path):
        """IN_PROGRESS untouched beyond the window is presumed dead → 0.0."""
        ws = _mk_ws(tmp_path, [{"id": "q1"}],
                    [_claim("C-1", "IN_PROGRESS", "q1",
                            last_activity_at="2026-08-30T00:00:00Z")])
        ml.init(ws, None)
        assert _prog(ws, "q1")["credit"] == 0.0

    def test_in_progress_no_timestamps_counts_as_fresh(self, tmp_path):
        """No activity fields = not provably stale (claim_expiry precedent:
        unknown age is treated fresh, not stale)."""
        ws = _mk_ws(tmp_path, [{"id": "q1"}],
                    [_claim("C-1", "IN_PROGRESS", "q1")])
        ml.init(ws, None)
        assert abs(_prog(ws, "q1")["credit"] - 0.25) < 1e-9

    def test_open_credit_zero(self, tmp_path):
        ws = _mk_ws(tmp_path, [{"id": "q1"}],
                    [_claim("C-1", "OPEN", "q1")])
        ml.init(ws, None)
        assert _prog(ws, "q1")["progress"] == 0.0


# ---------------------------------------------------------------------------
# 5: difficulty-aware damping
# ---------------------------------------------------------------------------


class TestDifficultyDamping:
    def _shape(self):
        return [_claim("C-1", "PARTIALLY-VERIFIED", "q1"),
                _claim("C-2", "OPEN", "q1")]

    def test_max_damped_below_easy_and_missing_undamped(self, tmp_path):
        easy = _mk_ws(tmp_path, [{"id": "q1"}], self._shape(),
                      tier=None, name="easy")
        mx = _mk_ws(tmp_path, [{"id": "q1"}], self._shape(),
                    tier="max", name="mx")
        ml.init(easy, None)
        ml.init(mx, None)
        pe, pm = _prog(easy, "q1"), _prog(mx, "q1")
        assert abs(pe["progress"] - 0.25) < 1e-9  # missing difficulty → undamped
        assert pe["damped"] is False
        assert pm["progress"] < pe["progress"]  # the "overstated progress" fix
        assert pm["damped"] is True

    def test_hard_and_max_exact_factors(self, tmp_path):
        hard = _mk_ws(tmp_path, [{"id": "q1"}], self._shape(),
                      tier="hard", name="hard")
        mx = _mk_ws(tmp_path, [{"id": "q1"}], self._shape(),
                    tier="max", name="mx")
        ml.init(hard, None)
        ml.init(mx, None)
        assert abs(_prog(hard, "q1")["progress"] - 0.25 * 0.75) < 1e-9
        assert abs(_prog(mx, "q1")["progress"] - 0.25 * 0.5) < 1e-9

    def test_damping_never_touches_answered(self, tmp_path):
        ws = _mk_ws(tmp_path, [{"id": "q1"}],
                    [_claim("C-1", "PROVEN", "q1")], tier="max")
        ml.init(ws, None)
        ml.update(ws)
        p = _prog(ws, "q1")
        assert p["progress"] == 1.0
        assert p["damped"] is False

    def test_task_spec_difficulty_key_fallback(self, tmp_path):
        """difficulty_calibration.mount() also copies the tier into
        task_spec.yaml (#16 open-loop contract) — that mount must damp too."""
        ws = _mk_ws(tmp_path, [{"id": "q1"}], self._shape(), tier=None,
                    name="spec", spec_extra={"difficulty": {"tier": "max"}})
        ml.init(ws, None)
        p = _prog(ws, "q1")
        assert p["damped"] is True
        assert abs(p["progress"] - 0.25 * 0.5) < 1e-9

    def test_unknown_tier_undamped(self, tmp_path):
        ws = _mk_ws(tmp_path, [{"id": "q1"}], self._shape(), name="u")
        (ws / "evidence").mkdir()
        (ws / "evidence" / "difficulty.json").write_text(
            json.dumps({"tier": "warp"}), encoding="utf-8")
        ml.init(ws, None)
        assert abs(_prog(ws, "q1")["progress"] - 0.25) < 1e-9


# ---------------------------------------------------------------------------
# 6: additive surface — raw fields untouched
# ---------------------------------------------------------------------------


class TestAdditiveSurface:
    def test_value_m_raw_fields_intact(self, tmp_path):
        ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}],
                    [_claim("C-1", "PROVEN", "q1")])
        ml.init(ws, None)
        ml.update(ws)
        v = ml.value_m(ws, now=NOW)
        for k in ("v_m", "prev_v_m", "a_t", "v_norm", "a_t_norm",
                  "total_weight", "per_pq", "answered", "blocked",
                  "unattempted"):
            assert k in v, k
        assert v["v_m"] == 1.0  # exact #823 formula: answered w=1 cov=1
        assert v["answered"] == 1 and v["blocked"] == 0
        # per_pq rows keep the #10 raw projection EXACTLY — progress lives
        # in per_pq_progress, never written into the pinned surface
        # (same byte-identical guard test_vm_normalization_10 enforces).
        assert v["per_pq"] == {"q1": {"state": "answered", "contrib": 1.0},
                               "q2": {"state": "unattempted", "contrib": 0.0}}

    def test_ledger_coverage_fields_unchanged(self, tmp_path):
        """Fractional credit is computed, never written back into coverage."""
        ws = _mk_ws(tmp_path, [{"id": "q1"}],
                    [_claim("C-1", "PROVEN", "q1"),
                     _claim("C-2", "OPEN", "q1"),
                     _claim("C-3", "OPEN", "q1")])
        ml.init(ws, None)
        ml.value_m(ws, now=NOW)
        pq = ml.load(ws)["mission"]["pqs"][0]
        assert pq["coverage"] == 0.0
        assert pq["state"] == "unattempted"

    def test_anti_stupid_edge_claims_zero_progress(self, tmp_path):
        """#823 invariant extended to the new face: edge claims all PROVEN
        with zero PQ links move progress_fraction strictly 0."""
        ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}],
                    [_claim("C-e1", "PROVEN"), _claim("C-e2", "VERIFIED")])
        ml.init(ws, None)
        v = ml.value_m(ws, now=NOW)
        assert v["progress_fraction"] == 0.0
        assert all(r["credit"] == 0.0 for r in v["per_pq_progress"])

    def test_progress_fraction_aggregate(self, tmp_path):
        ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}],
                    [_claim("C-1", "PROVEN", "q1"),
                     _claim("C-2", "PARTIALLY-VERIFIED", "q2"),
                     _claim("C-3", "OPEN", "q2")])
        ml.init(ws, None)
        ml.update(ws)
        v = ml.value_m(ws, now=NOW)
        assert abs(v["progress_fraction"] - (1.0 + 0.25) / 2) < 1e-9

    def test_progress_fraction_weighted(self, tmp_path):
        ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}],
                    [_claim("C-1", "PROVEN", "q1"),
                     _claim("C-2", "PARTIALLY-VERIFIED", "q2"),
                     _claim("C-3", "OPEN", "q2")])
        ml.init(ws, None)
        # weights live on ledger entries (repin-style), not task_spec (#10)
        led = ml.load(ws)
        led["mission"]["pqs"][0]["weight"] = 2.0
        ml._save(ws, led)
        ml.update(ws)
        v = ml.value_m(ws, now=NOW)
        assert abs(v["progress_fraction"] - (2 * 1.0 + 1 * 0.25) / 3) < 1e-9

    def test_emit_snapshot_carries_progress_fraction(self, tmp_path):
        ws = _mk_ws(tmp_path, [{"id": "q1"}],
                    [_claim("C-1", "PROVEN", "q1")])
        ml.init(ws, None)
        ml.update(ws)
        ml.emit_snapshot(ws, epoch=1, arm="N")
        rows = []
        for p in sorted((Path(ws) / "runs" / "logs").glob("kunglao-*.jsonl")):
            rows += [json.loads(line)
                     for line in p.read_text(encoding="utf-8").splitlines()
                     if line.strip()]
        detail = json.loads(
            [r for r in rows if r["action"] == "mission_snapshot"][0]["detail"])
        assert "progress_fraction" in detail


# ---------------------------------------------------------------------------
# 7: cockpit additive surface
# ---------------------------------------------------------------------------


class TestCockpitSurface:
    def test_cockpit_progress_fraction_additive(self, tmp_path):
        import tuition_curve as tc
        ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}],
                    [_claim("C-1", "PROVEN", "q1"),
                     _claim("C-2", "PARTIALLY-VERIFIED", "q2"),
                     _claim("C-3", "OPEN", "q2")])
        (ws / "runs" / "logs").mkdir(parents=True)
        ml.init(ws, None)
        ml.update(ws)
        ml.value_m(ws, now=NOW)
        cs = tc.cockpit_summary(ws)
        for k in ("v", "v_norm", "d_slope", "d_slope_norm", "eta_checkpoints",
                  "total_weight", "answered", "blocked", "unattempted",
                  "cost", "burn", "tuition"):
            assert k in cs, k
        assert abs(cs["progress"]["progress_fraction"] - 0.625) < 1e-9
        ids = [row["id"] for row in cs["progress"]["per_pq"]]
        assert ids == ["q1", "q2"]


# ---------------------------------------------------------------------------
# 8: CLI face
# ---------------------------------------------------------------------------


class TestCliFace:
    def test_empty_workspace_no_crash(self, tmp_path):
        ws = tmp_path / "empty"
        ws.mkdir()
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "progress_report.py"),
             "--progress", str(ws)],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert "Traceback" not in r.stderr

    def test_renders_per_pq_bars(self, tmp_path):
        ws = _mk_ws(tmp_path, [{"id": "q1"}, {"id": "q2"}],
                    [_claim("C-1", "PROVEN", "q1"),
                     _claim("C-2", "PROVEN", "q1"),
                     _claim("C-3", "PARTIALLY-VERIFIED", "q2"),
                     _claim("C-4", "OPEN", "q2")], tier="hard")
        ml.init(ws, None)
        ml.update(ws)
        r = subprocess.run(
            [sys.executable, str(SCRIPTS / "progress_report.py"),
             "--progress", str(ws)],
            capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert "q1" in r.stdout and "q2" in r.stdout
        assert "[" in r.stdout and "#" in r.stdout and "-" in r.stdout
        assert "damp" in r.stdout.lower()  # damping flag visible
