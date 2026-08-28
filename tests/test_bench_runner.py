# -*- coding: utf-8 -*-
"""B4 (#823): bench_runner — lane scheduling, budgets, terminal states.

Tests cover the SCHEDULING + RECEIPT contracts; execution goes through
an injectable executor (the real one shells out to `claude -p`, never
with --dangerously-skip-permissions).
"""
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bench_runner as br


def _manifest(tmp: Path, seed=42):
    samples = []
    for st, n in (("S1", 2), ("S3", 3)):
        for i in range(n):
            samples.append({"id": f"{st}-s{i}", "stratum": st,
                            "path": f"vault://{st}-{i}.bin",
                            "sha256": "0" * 64, "first_seen": "2026-07",
                            "truth_tier": "A",
                            "truth_sources": ["a", "b"],
                            "scoring_pqs": ["PQ1"], "excluded_pqs": []})
    m = tmp / "manifest.yaml"
    m.write_text(yaml.safe_dump({"schema": "kunglao-bench-manifest/1",
                                 "seed": seed, "samples": samples}),
                 encoding="utf-8")
    return m


def test_budget_table_locked():
    assert br.BUDGETS["S1"] == {"max_turns": 700, "wall_h": 6, "budget_min": 360}
    assert br.BUDGETS["S2"] == {"max_turns": 800, "wall_h": 6, "budget_min": 360}
    assert br.BUDGETS["S3"] == {"max_turns": 900, "wall_h": 8, "budget_min": 480}
    assert br.BUDGETS["S4"] == {"max_turns": 500, "wall_h": 4, "budget_min": 240}
    assert br.BUDGETS["S3"]["wall_h"] == 8  # the user-ruled ceiling


def test_arm_env_flag_wiring():
    assert br.arm_env("N") == {"KUNGLAO_VALUE_ALGO": "1"}
    assert br.arm_env("O") == {}


def test_lane_a_plans_n_serial():
    plan = br.build_plan(_manifest(Path("/tmp/unused")), "S3", lane="A")
    assert all(spec["arm"] == "N" for spec in plan)
    assert all(spec["serial"] is True for spec in plan)
    assert len(plan) == 3
    s3 = br.BUDGETS["S3"]
    assert plan[0]["max_turns"] == s3["max_turns"]
    assert plan[0]["wall_cap_s"] == s3["wall_h"] * 3600


def test_lane_b_plans_o_parallel():
    plan = br.build_plan(_manifest(Path("/tmp/unused")), "S1", lane="B")
    assert all(spec["arm"] == "O" and spec["serial"] is False
               for spec in plan)


def test_plan_determinism_same_seed(tmp_path):
    m = _manifest(tmp_path, seed=99)
    p1 = br.build_plan(m, "S1", lane="A")
    p2 = br.build_plan(m, "S1", lane="A")
    assert [(s["sample"], s["workspace"]) for s in p1] == \
           [(s["sample"], s["workspace"]) for s in p2]


def test_pilot_filters_stratum(tmp_path):
    m = _manifest(tmp_path)
    plan = br.build_plan(m, "S3", lane="A")
    assert {s["stratum"] for s in plan} == {"S3"}


def test_stub_executor_done_receipt(tmp_path):
    m = _manifest(tmp_path)
    plan = br.build_plan(m, "S1", lane="A")
    receipts = br.run_plan(plan[:1], executor=lambda spec: {
        "outcome": "done", "transcript": "t.jsonl", "compaction_count": 2},
        out_dir=tmp_path)
    r = receipts[0]
    assert r["outcome"] == "done"
    assert r["schema"] == "kunglao-bench-run/1"
    assert r["compaction_count"] == 2


def test_stub_executor_crashed_on_raise(tmp_path):
    m = _manifest(tmp_path)
    plan = br.build_plan(m, "S1", lane="A")

    def boom(spec):
        raise RuntimeError("VM lost")
    receipts = br.run_plan(plan[:1], executor=boom, out_dir=tmp_path)
    assert receipts[0]["outcome"] == "crashed"


def test_timeout_is_a_legal_terminal_state(tmp_path):
    m = _manifest(tmp_path)
    plan = br.build_plan(m, "S1", lane="A")
    receipts = br.run_plan(plan[:1], executor=lambda spec: {
        "outcome": "timeout", "transcript": "t.jsonl",
        "compaction_count": 5}, out_dir=tmp_path)
    assert receipts[0]["outcome"] == "timeout"
    assert receipts[0]["workspace"]  # frozen workspace recorded, not cleaned
