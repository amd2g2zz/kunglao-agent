# -*- coding: utf-8 -*-
"""tests/test_ex3_bucket_calibration_429.py — EX-3 harness determinism pin
(issue #429 W3-T3.2, v0.1.6 bucket-boundary calibration replay).

EX-3 replays dispatch-history fact trajectories over the FACT_BUCKET_EDGES
discretization (scripts/state_signature.py, untouched) and reports the fill
distribution. The plan clause: "边界不当→调 FACT_BUCKET_EDGES（声明+钉）" —
this harness NEVER edits the live edges; it produces the evidence table and
a declared verdict (calibrate / no-calibration).

Pins:
  - the replay is a pure read over the campaign root (never writes);
  - bucket mapping rides state_signature.fact_bucket exactly (one source);
  - same root -> byte-identical result document (determinism — the pin);
  - workspaces = the #240 marker set (claim-register.yaml present);
  - trajectory face = .convergence_ledger.jsonl facts_total history, with
    the terminal facts/F*.md count as the declared fallback;
  - the verdict document carries declared decision inputs + reason.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
FIXTURES = ROOT / "tests" / "fixtures" / "experiments"
sys.path.insert(0, str(FIXTURES))

import state_signature as ssig  # noqa: E402
from ex3_bucket_calibration import replay, verdict  # noqa: E402

TS = "2026-09-27T00:00:00Z"


def _ws(root: Path, name: str, facts_total_history: list[int],
        fact_files: int | None = None) -> Path:
    """One synthetic campaign workspace: the #240 marker + a convergence
    ledger with facts_total snapshots + optional terminal fact files."""
    ws = root / name
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-1\n  status: OPEN\n", encoding="utf-8")
    lines = "".join(
        json.dumps({"ts": TS, "decision": "DISPATCH",
                    "facts_total": n, "schema": "conv/1"}) + "\n"
        for n in facts_total_history)
    (ws / ".convergence_ledger.jsonl").write_text(lines, encoding="utf-8")
    if fact_files:
        for i in range(fact_files):
            (ws / "facts").mkdir(exist_ok=True)
            (ws / "facts" / f"F{i:03d}-synthetic.md").write_text(
                "---\nstatus: PROVEN\n---\nbody\n", encoding="utf-8")
    return ws


class TestReplay:
    def test_schema_and_shape(self, tmp_path):
        _ws(tmp_path, "ws-a", [0, 1, 5])
        doc = replay(tmp_path)
        assert doc["schema"] == "ex3-bucket-calibration/1"
        assert doc["workspaces_scanned"] == 1
        assert doc["samples"] == 3

    def test_bucket_mapping_rides_state_signature(self, tmp_path):
        """Every trajectory point lands in the bucket fact_bucket picks —
        one discretization source, zero re-implementation."""
        _ws(tmp_path, "ws-a", [0, 3, 5, 12, 30, 60])
        doc = replay(tmp_path)
        expected = {}
        for n in (0, 3, 5, 12, 30, 60):
            b = ssig.fact_bucket(n)
            expected[str(b)] = expected.get(str(b), 0) + 1
        assert doc["fill_distribution"] == expected

    def test_convergence_history_is_the_trajectory(self, tmp_path):
        _ws(tmp_path, "ws-a", [0, 0, 9, 9])
        doc = replay(tmp_path)
        assert doc["samples"] == 4
        assert doc["fill_distribution"]["0"] == 2
        assert doc["fill_distribution"]["2"] == 2  # 9 -> bucket 5-9

    def test_terminal_fallback_without_ledger(self, tmp_path):
        """No convergence ledger -> the terminal fact-file count is the
        single declared trajectory point."""
        ws = _ws(tmp_path, "ws-b", [], fact_files=7)
        (ws / ".convergence_ledger.jsonl").unlink()
        doc = replay(tmp_path)
        assert doc["workspaces_scanned"] == 1
        assert doc["samples"] == 1
        assert doc["fill_distribution"]["2"] == 1  # 7 -> bucket 5-9

    def test_workspaces_without_marker_ignored(self, tmp_path):
        (tmp_path / "not-a-workspace").mkdir()
        (tmp_path / "not-a-workspace" / "notes.txt").write_text("x")
        _ws(tmp_path, "ws-a", [0])
        doc = replay(tmp_path)
        assert doc["workspaces_scanned"] == 1

    def test_per_workspace_max_trajectory_count(self, tmp_path):
        _ws(tmp_path, "ws-a", [0, 4, 21])
        doc = replay(tmp_path)
        per_ws = {w["workspace"]: w for w in doc["per_workspace"]}
        assert per_ws["ws-a"]["trajectory_max"] == 21

    def test_empty_root_zero_scanned(self, tmp_path):
        doc = replay(tmp_path)
        assert doc["workspaces_scanned"] == 0
        assert doc["samples"] == 0
        # stable-frame contract (event_taxonomy precedent): every bucket
        # always present, 0 when unseen
        assert doc["fill_distribution"] == {"0": 0, "1": 0, "2": 0,
                                            "3": 0, "4": 0, "5": 0}

    def test_read_only_never_writes(self, tmp_path):
        _ws(tmp_path, "ws-a", [0, 5])
        before = sorted(str(p.relative_to(tmp_path))
                        for p in tmp_path.rglob("*") if p.is_file())
        replay(tmp_path)
        after = sorted(str(p.relative_to(tmp_path))
                       for p in tmp_path.rglob("*") if p.is_file())
        assert before == after


class TestDeterminism:
    def test_same_root_same_document(self, tmp_path):
        _ws(tmp_path, "ws-a", [0, 1, 9, 20])
        _ws(tmp_path, "ws-b", [2], fact_files=2)
        one = replay(tmp_path)
        two = replay(tmp_path)
        assert json.dumps(one, sort_keys=True) == \
            json.dumps(two, sort_keys=True)

    def test_scan_order_stable(self, tmp_path):
        """Workspace order must be sorted, not filesystem order."""
        _ws(tmp_path, "zz-ws", [0])
        _ws(tmp_path, "aa-ws", [3])
        doc = replay(tmp_path)
        names = [w["workspace"] for w in doc["per_workspace"]]
        assert names == sorted(names)


class TestVerdict:
    def test_verdict_declares_inputs_and_reason(self, tmp_path):
        _ws(tmp_path, "ws-a", [0, 1, 9])
        doc = verdict(replay(tmp_path))
        assert doc["verdict"] in ("calibrate", "no-calibration")
        assert doc["reason"]
        assert "declared_criteria" in doc

    def test_empty_data_is_no_calibration(self, tmp_path):
        doc = verdict(replay(tmp_path))
        assert doc["verdict"] == "no-calibration"
        assert "no samples" in doc["reason"].lower()

    def test_reason_reports_top_filled_bucket_not_frame_index(self, tmp_path):
        """Regression: the reason's 'max filled bucket index' counts only
        buckets that actually hold mass — the stable-frame zeros must not
        read as filled."""
        _ws(tmp_path, "ws-a", [0, 1, 9] * 20)  # 60 samples, buckets 0-2 only
        doc = verdict(replay(tmp_path))
        assert doc["verdict"] == "no-calibration"
        assert "max filled bucket index 2" in doc["reason"]
