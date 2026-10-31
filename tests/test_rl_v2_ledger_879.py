# -*- coding: utf-8 -*-
"""tests/test_rl_v2_ledger_879.py — the unified ledger semantics (879).

#878 landed the v2 row KINDS; #879 makes the ledger the system's ONLY
(s,a,r) store with real semantics:

  1. state snapshot columns — an action row records the state it was
     decided from (the ``s`` axis, additive column, fold-blind);
  2. single-writer VERIFIED — concurrent appends serialize through the
     consolidated ledger's flock and no row is ever lost or torn;
  3. the pandas load/query face — trajectory_dataframe() loads the
     whole multi-schema stream into one DataFrame (append order
     preserved; legacy-only files load; empty workspaces load);
  4. consumer regression — value_table over a MIXED ledger (old obs +
     v2 rows) is byte-identical to the same ledger without v2 rows
     (the fold's prefix wall holds under the v2 faces);
  5. archive posture — the legacy rels (q-cell-log / transitions /
     step-ledger) receive NO writes from any v2 face; the consolidated
     experience file is the only home.
"""
from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT / "scripts", ROOT / "experiments" / "learning-loop"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import ledger_frame  # noqa: E402
from rlvr import l1_value, q_cells  # noqa: E402

_SIG = "a" * 12
# the spec-legal probe params (issue 924): the potential-based comparison
# data the probe contract requires on every probe row
_PROBE_PARAMS = {"portfolio": "probe-portfolio/1", "rank": 1,
                 "arms": 2, "potential_based": True, "leader": "l"}


def _seed_qcell_obs(ws) -> None:
    q_cells.append_observation(ws, _SIG, "mod-crypto", 1.0,
                               source="settlement",
                               arm_key_col="mod-crypto|facts_snapshot"
                                          "|none|0")
    q_cells.append_observation(ws, _SIG, "mod-crypto", 0.0,
                               source="settlement",
                               arm_key_col="mod-crypto|facts_snapshot"
                                          "|none|0")


def _seed_l1(ws) -> None:
    l1_value.record_observation(ws, _SIG, "dispatch", 1.0, claim="C-001")
    l1_value.record_observation(ws, _SIG, "dispatch", 0.0, claim="C-002")


# ------------------------------------------------- state snapshot cols

def test_state_snapshot_column_round_trips(tmp_path):
    ws = tmp_path / "ws"
    q_cells.append_action(ws, kind="assign_step", rollout_id="ro-1",
                          step_id="s-1", target="step-1",
                          params={"method_family": "m"},
                          state_snapshot={"signature_hash": _SIG,
                                          "goal_depth": 2})
    (row,) = q_cells.trajectory_rows(ws)
    assert row["state_snapshot"] == {"signature_hash": _SIG,
                                     "goal_depth": 2}


def test_state_snapshot_absent_and_rejected(tmp_path):
    ws = tmp_path / "ws"
    q_cells.append_action(ws, kind="probe", rollout_id="ro-1",
                          target="fam-a", params=_PROBE_PARAMS)
    (row,) = q_cells.trajectory_rows(ws)
    assert "state_snapshot" not in row      # additive-column discipline
    with pytest.raises(ValueError):
        q_cells.append_action(ws, kind="probe", rollout_id="ro-1",
                              target="fam-a", params=_PROBE_PARAMS,
                              state_snapshot="ro-1-state")


# -------------------------------------------- single-writer VERIFIED

def test_single_writer_concurrent_appends_serialize(tmp_path):
    ws = tmp_path / "ws"

    def blast(worker: int) -> None:
        for i in range(25):
            q_cells.append_result(ws, rollout_id=f"ro-{worker}",
                                  step_id=f"s-{i:02d}", r_t=0.5,
                                  verified=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(blast, range(8)))

    rows = q_cells.trajectory_rows(ws)
    assert len(rows) == 200                 # zero lost writes
    assert {r["schema"] for r in rows} == {"q-cell-result/1"}
    for w in range(8):                      # no torn/interleaved rows
        mine = sorted(r["step_id"] for r in rows
                      if r["rollout_id"] == f"ro-{w}")
        assert mine == [f"s-{i:02d}" for i in range(25)]
    assert (ws / "runs" / ".experience.lock").is_file()  # the flock face


def test_append_action_rejects_non_json_payloads(tmp_path):
    """The serializability wall (#879 review): a payload json.dumps
    refuses would otherwise fail INSIDE the ledger write — the whole
    action row silently vanishing (warn-and-False). Rejected loudly
    at the boundary instead."""
    ws = tmp_path / "ws"
    with pytest.raises(ValueError):
        q_cells.append_action(ws, kind="probe", rollout_id="ro-1",
                              target="x",
                              params={**_PROBE_PARAMS,
                                      "snapshot_excerpt": Path(".")})
    with pytest.raises(ValueError):
        q_cells.append_action(ws, kind="probe", rollout_id="ro-1",
                              target="x", params=_PROBE_PARAMS,
                              state_snapshot={"t": object()})


def test_dataframe_columns_cover_every_ledger_field(tmp_path):
    """The projection's column union is TOTAL: every key on every
    appended row (richest obs shape included) has a df column — no
    silently truncated analyst queries (#879 review)."""
    ws = tmp_path / "ws"
    q_cells.append_observation(ws, _SIG, "mod-crypto", 0.5,
                               source="settlement", claim="C-1",
                               agent="kunglao-worker",
                               dispatch_id="d-1", fingerprint="fp",
                               arm_key_col="mod-crypto|facts_snapshot"
                                          "|none|0",
                               action_type="dispatch", phi_delta=0.1,
                               credit_kind="step",
                               recipe_id="r1", recipe_propensity=0.4,
                               recipe_source="sampled",
                               reward=0.6, confidence_band="C0a",
                               tier=2, tools=["grep", "xxd"],
                               sampler_view={"propensity": 0.5,
                                             "sampled_family": "mod-crypto",
                                             "prior_source": "llm"})
    q_cells.append_action(ws, kind="assign_step", rollout_id="ro-1",
                          step_id="s-1", target="step-1",
                          params={"method_family": "m"},
                          state_snapshot={"signature_hash": _SIG},
                          policy_version="v2")
    q_cells.append_result(ws, rollout_id="ro-1", step_id="s-1",
                          r_t=0.5, verified=True, R_t=0.7, A_t=0.2)
    df = ledger_frame.trajectory_dataframe(ws)
    for row in q_cells.trajectory_rows(ws):
        missing = set(row) - set(df.columns)
        assert not missing, f"projection dropped fields: {sorted(missing)}"


# ------------------------------------------- pandas load/query face

def test_trajectory_dataframe_load_query_round_trip(tmp_path):
    ws = tmp_path / "ws"
    _seed_qcell_obs(ws)
    q_cells.append_action(ws, kind="assign_step", rollout_id="ro-1",
                          step_id="s-1", target="step-1",
                          params={"method_family": "m"})
    q_cells.append_result(ws, rollout_id="ro-1", step_id="s-1",
                          r_t=0.5, verified=True, R_t=0.7)
    df = ledger_frame.trajectory_dataframe(ws)
    assert list(df["schema"]) == ["q-cell-obs/1", "q-cell-obs/1",
                                  "q-cell-action/1", "q-cell-result/1"]
    mine = df[df["rollout_id"] == "ro-1"]
    assert len(mine) == 2
    res = mine[mine["schema"] == "q-cell-result/1"].iloc[0]
    assert res["r_t"] == 0.5
    assert res["R_t"] == 0.7


def test_trajectory_dataframe_empty_and_legacy_only(tmp_path):
    empty = tmp_path / "empty"
    df = ledger_frame.trajectory_dataframe(empty)
    assert len(df) == 0
    assert {"schema", "ts", "rollout_id"} <= set(df.columns)

    legacy = tmp_path / "legacy"
    _seed_qcell_obs(legacy)
    df_old = ledger_frame.trajectory_dataframe(legacy)
    assert list(df_old["schema"]) == ["q-cell-obs/1", "q-cell-obs/1"]


# -------------------------------------------- consumer regression

def test_value_table_identical_with_v2_rows_present(tmp_path):
    ws_old = tmp_path / "old"
    _seed_l1(ws_old)
    ws_mixed = tmp_path / "mixed"
    _seed_l1(ws_mixed)
    q_cells.append_action(ws_mixed, kind="assign_step", rollout_id="ro-1",
                          step_id="s-1", target="step-1",
                          params={"method_family": "m"})
    q_cells.append_result(ws_mixed, rollout_id="ro-1", step_id="s-1",
                          r_t=0.9, verified=True, R_t=0.7, A_t=0.2)
    # value_table embeds the workspace path — compare the CELLS payload
    assert (l1_value.value_table(ws_old)["cells"]
            == l1_value.value_table(ws_mixed)["cells"])
    assert l1_value.value_table(ws_mixed)["cells"]  # non-empty: real fold


# ------------------------------------------------ archive posture

def test_legacy_archive_rels_receive_no_writes(tmp_path):
    ws = tmp_path / "ws"
    _seed_qcell_obs(ws)
    _seed_l1(ws)
    q_cells.append_action(ws, kind="select_task", rollout_id="ro-1",
                          target="claim-C-001")
    q_cells.append_result(ws, rollout_id="ro-1", step_id="s-1",
                          r_t=0.5, verified=True)
    assert (ws / "runs" / "experience.jsonl").is_file()
    for rel in ("q-cell-log.jsonl", "transitions.jsonl",
                "step-ledger.jsonl", "evidence-credit.jsonl"):
        assert not (ws / "runs" / rel).exists(), rel
