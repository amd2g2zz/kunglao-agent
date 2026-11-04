#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_climb3_grader_matrixlaunch_pins_818.py — #818 climb
segment 3F.

Behavior pins on REAL fixtures for the two orchestration faces the
earlier segments left unmeasured:

  scripts/eval_chain_grader.py — the dense per-layer grader called
  IN-PROCESS over minted chain units and their reference / decoy /
  empty / tampered workspaces (every checkpoint op class: digest,
  exec, markers, clean; the SKIP face when a layer's toolchain is
  absent; the REFUSED face; the CLI's scores write-back).

  scripts/eval_matrix_runner.py — the launch schedule executed for
  real in its DRY face (unit resolution honesty, the would-launch row,
  the warm-fault prediction, the progress spine) plus the plan-time
  resolve_unit faces over a synthetic operator corpus.

Pin discipline: expectations derive from the fixture each test computed —
no repo-state literalization (units are minted from the modules' own
generators; the dry run touches nothing by contract).
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _p in (str(ROOT), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import eval_chain_grader as cgr  # noqa: E402
import eval_chain_mint as cm  # noqa: E402
import eval_chain as cn  # noqa: E402
import eval_matrix_runner as emr  # noqa: E402
import eval_chain_render as rd  # noqa: E402


# ------------------------------------------------------------ chain grader

def _mint(task_id: str, tmp_path: Path) -> Path:
    return cm.write_task_unit(task_id, tmp_path / "corpus")


def _cfg(task_id: str) -> dict:
    unit = cn.UNIT_BY_ID[task_id]
    cfg = cm.stage_cfg(unit)
    cfg["task_id"] = task_id
    cfg["unit"] = unit
    return cfg


def _write_ws(tmp_path: Path, name: str, files: dict[str, bytes]) -> Path:
    ws = tmp_path / name
    for rel, data in files.items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return ws


class TestChainGrader:
    def test_reference_workspace_is_dense_green(self, tmp_path) -> None:
        tdir = _mint("chain-l3-py-v1", tmp_path)
        ws = _write_ws(tmp_path, "ref", cm.reference_workspace(
            _cfg("chain-l3-py-v1")))
        rc, scores = cgr.grade(str(tdir), ws)
        assert rc == cgr.RC_PASS
        assert scores["verdict"] == "PASS"
        assert scores["layers_completed"] == scores["layers_total"] == 6
        assert scores["dense_score"] == 1.0
        assert scores["hard_failures"] == 0 and scores["skipped_ops"] == 0
        # every op class ran and passed
        ops = {op["op"] for layer in scores["layers"]
               for op in layer["ops"]}
        assert ops == {"digest", "exec", "markers", "clean"}

    def test_empty_workspace_scores_zero_and_fails(self, tmp_path) -> None:
        tdir = _mint("chain-l2-py-v1", tmp_path)
        ws = _write_ws(tmp_path, "empty", {})
        ws.mkdir(exist_ok=True)  # an empty analysis workspace
        rc, scores = cgr.grade(str(tdir), ws)
        assert rc == cgr.RC_FAIL
        assert scores["layers_completed"] == 0
        assert scores["hard_failures"] > 0

    def test_decoy_trajectory_scores_partial(self, tmp_path) -> None:
        tdir = _mint("chain-l2-py-v1", tmp_path)
        ws = _write_ws(tmp_path, "decoy", cm.decoy_workspace(
            _cfg("chain-l2-py-v1")))
        rc, scores = cgr.grade(str(tdir), ws)
        assert rc == cgr.RC_FAIL
        total = scores["layers_total"]
        assert 0 < scores["layers_completed"] < total
        # the peeled layers credited, the core layer did not
        by_id = {layer["id"]: layer["completed"]
                 for layer in scores["layers"]}
        assert by_id[cn.L_OBFUSCATION] is True
        assert by_id[cn.L_CIPHER] is False

    def test_tampered_digest_fails_its_layer_only(self, tmp_path) -> None:
        task_id = "chain-l1-py-v1"
        tdir = _mint(task_id, tmp_path)
        files = dict(cm.reference_workspace(_cfg(task_id)))
        cfg_idx = "2"
        config_key = f"layer_out/{cfg_idx}-config.json"
        files[config_key] = b'{"tampered": true}\n'
        ws = _write_ws(tmp_path, "tampered", files)
        rc, scores = cgr.grade(str(tdir), ws)
        assert rc == cgr.RC_FAIL
        by_id = {layer["id"]: layer for layer in scores["layers"]}
        assert by_id[cn.L_OBFUSCATION]["completed"] is True
        assert by_id[cn.L_CONFIG]["completed"] is False
        digest_op = by_id[cn.L_CONFIG]["ops"][0]
        assert digest_op["op"] == "digest" and digest_op["pass"] is False

    def test_missing_markers_refuse_the_layer(self, tmp_path) -> None:
        task_id = "chain-l3-py-v1"
        tdir = _mint(task_id, tmp_path)
        files = dict(cm.reference_workspace(_cfg(task_id)))
        path_doc = json.loads(files["layer_out/5-path.json"])
        path_doc["true_path"]["sel_value"] = "0x00000000"
        files["layer_out/5-path.json"] = json.dumps(
            path_doc, indent=2, sort_keys=True).encode("utf-8")
        ws = _write_ws(tmp_path, "wrong-branch", files)
        rc, scores = cgr.grade(str(tdir), ws)
        assert rc == cgr.RC_FAIL
        by_id = {layer["id"]: layer for layer in scores["layers"]}
        assert by_id[cn.L_DECOY]["completed"] is False
        markers_op = by_id[cn.L_DECOY]["ops"][0]
        assert markers_op["op"] == "markers" and \
            markers_op["pass"] is False

    def test_junk_survival_fails_the_clean_op(self, tmp_path) -> None:
        task_id = "chain-l3-py-v1"
        tdir = _mint(task_id, tmp_path)
        files = dict(cm.reference_workspace(_cfg(task_id)))
        clean = files["layer_out/2-clean.py"].decode("utf-8")
        # reintroduce one junk marker into the stripped reference form
        marker = rd.junk_markers(_cfg(task_id))[0]
        files["layer_out/2-clean.py"] = (
            clean + "\n# " + marker + "\n").encode("utf-8")
        ws = _write_ws(tmp_path, "junky", files)
        rc, scores = cgr.grade(str(tdir), ws)
        assert rc == cgr.RC_FAIL
        by_id = {layer["id"]: layer for layer in scores["layers"]}
        assert by_id[cn.L_JUNK]["completed"] is False

    def test_absent_toolchain_degrades_to_skip_never_false_fail(
            self, tmp_path, monkeypatch) -> None:
        if shutil.which("node") is None:
            pytest.skip("node absent; the scrub below is the only reality")
        # an L2 unit: its cipher layer's exec op needs the toolchain
        tdir = _mint("chain-l2-js-v1", tmp_path)
        ws = _write_ws(tmp_path, "ref-js", cm.reference_workspace(
            _cfg("chain-l2-js-v1")))
        real_which = shutil.which
        monkeypatch.setattr(
            shutil, "which",
            lambda cmd: None if cmd == "node" else real_which(cmd))
        rc, scores = cgr.grade(str(tdir), ws)
        assert rc == cgr.RC_SKIP
        assert scores["verdict"] == "SKIP"
        assert scores["skipped_ops"] > 0
        # the non-exec layer still graded mechanically
        assert scores["layers_completed"] >= 1

    def test_refusal_faces(self, tmp_path, capsys) -> None:
        tdir = _mint("chain-l1-py-v1", tmp_path)
        with pytest.raises(cgr.Refusal, match="workspace dir not found"):
            cgr.grade(str(tdir), tmp_path / "no-such-ws")
        rc = cgr.main(["--task", "no-such-unit",
                       "--workspace", str(tmp_path),
                       "--out", str(tmp_path / "scores")])
        stream = capsys.readouterr().out
        assert rc == cgr.RC_REFUSED
        assert "VERDICT REFUSED" in stream

    def test_main_writes_the_scores_doc(self, tmp_path, capsys) -> None:
        tdir = _mint("chain-l1-py-v1", tmp_path)
        ws = _write_ws(tmp_path, "ref", cm.reference_workspace(
            _cfg("chain-l1-py-v1")))
        out = tmp_path / "scores"
        rc = cgr.main(["--task", str(tdir), "--workspace", str(ws),
                       "--out", str(out)])
        stream = capsys.readouterr().out
        assert rc == 0
        assert "METRIC layers_completed=2" in stream
        assert "METRIC layers_total=2" in stream
        assert "VERDICT PASS" in stream
        score_files = list(out.rglob("*chain-l1-py-v1*.json"))
        assert score_files
        doc = json.loads(score_files[0].read_text(encoding="utf-8"))
        assert doc["schema"] == cgr.SCHEMA_SCORES
        assert doc["dense_score"] == 1.0


# ======================================== matrix runner launch schedule

def _plan(tmp_path: Path, arm_id: str, unit: str, *,
          corpus: str = "operator", tier: str = "smoke",
          store_kind: str = "none", store_mode: str = "per-run",
          runner_face: str = "cc-default",
          env_extra: tuple = ()) -> emr.RunPlan:
    run_dir = tmp_path / "matrix" / arm_id / unit
    return emr.RunPlan(
        arm_id=arm_id, runner_face=runner_face, unit=unit, tier=tier,
        corpus=corpus, run_dir=run_dir, store_kind=store_kind,
        env_extra=env_extra, store_mode=store_mode)


def _operator_corpus(tmp_path: Path, unit: str = "py-derive-a") -> Path:
    import eval_targets as tg
    corpus = tmp_path / "op-corpus"
    tg.write_task_unit("py-derive", 640001, unit,
                       corpus / "v1" / "tasks" / "smoke")
    return corpus


class TestMatrixLaunchFaces:
    def test_resolve_unit_honors_the_declared_corpus(
            self, tmp_path) -> None:
        corpus = _operator_corpus(tmp_path)
        ok, detail = emr.resolve_unit(
            {"id": "py-derive-a", "corpus": "operator",
             "tier": "smoke"}, corpus)
        assert ok is True
        assert detail == str(corpus)
        ok_missing, detail_missing = emr.resolve_unit(
            {"id": "ghost-unit", "corpus": "operator",
             "tier": "smoke"}, corpus)
        assert ok_missing is False
        assert "no task.yaml" in detail_missing
        ok_rootless, _ = emr.resolve_unit(
            {"id": "py-derive-a", "corpus": "operator",
             "tier": "smoke"}, None)
        assert ok_rootless is False  # an operator corpus needs its root
        ok_repo, detail_repo = emr.resolve_unit(
            {"id": "py-derive-a", "corpus": "repo", "tier": "smoke"},
            None)
        # the repo face is a decided (bool, str) either way — the
        # plan-time honesty check never guesses
        assert isinstance(ok_repo, bool)
        assert isinstance(detail_repo, str) and detail_repo

    def test_dry_launch_records_the_would_launch_and_touches_nothing(
            self, tmp_path) -> None:
        _operator_corpus(tmp_path)
        plan = _plan(tmp_path, "a-cc", "py-derive-a")
        row = emr._launch_one(
            plan, budget_usd=2.0, wall_cap_s=600, session_cmd=None,
            plugin_dir=None, warm_source=None, warm_context_from=None,
            operator_root=str(tmp_path / "op-corpus"), dry_run=True)
        assert row["status"] == "planned"
        assert row["arm"] == "a-cc" and row["unit"] == "py-derive-a"
        assert row["argv"] and "eval_loop_runner" in " ".join(row["argv"])
        assert row["store"] == "none"
        assert not plan.run_dir.exists()  # dry: nothing materialized

    def test_unresolvable_unit_is_a_named_state(self, tmp_path) -> None:
        plan = _plan(tmp_path, "a-cc", "ghost-unit")
        row = emr._launch_one(
            plan, budget_usd=2.0, wall_cap_s=600, session_cmd=None,
            plugin_dir=None, warm_source=None, warm_context_from=None,
            operator_root=str(tmp_path / "op-corpus"), dry_run=True)
        assert row["status"] == "unresolvable"
        assert "no task.yaml" in row["detail"]

    def test_warm_fault_is_predicted_by_the_dry_run(
            self, tmp_path) -> None:
        _operator_corpus(tmp_path)
        plan = _plan(tmp_path, "a-warm", "py-derive-a",
                     store_kind="warm", runner_face="loop")
        row = emr._launch_one(
            plan, budget_usd=2.0, wall_cap_s=600, session_cmd=None,
            plugin_dir=None, warm_source=None, warm_context_from=None,
            operator_root=str(tmp_path / "op-corpus"), dry_run=True)
        assert row["status"] == "refused"
        assert "warm claim would be false" in row["detail"]

    def test_launch_dry_writes_the_progress_spine(self, tmp_path) -> None:
        _operator_corpus(tmp_path)
        plans = [_plan(tmp_path, "a-cc", "py-derive-a"),
                 _plan(tmp_path, "b-cc", "py-derive-a")]
        out = tmp_path / "run"
        progress = emr.launch(
            plans, out, budget_usd=2.0, wall_cap_s=600, session_cmd=None,
            plugin_dir=None, warm_source=None, warm_context_from=None,
            operator_root=str(tmp_path / "op-corpus"), max_parallel=1,
            dry_run=True)
        assert progress["dry_run"] is True
        assert len(progress["runs"]) == 2
        assert all(r["status"] == "planned"
                   for r in progress["runs"])
        spine = json.loads((out / "progress.json").read_text(
            encoding="utf-8"))
        assert spine["schema"] == emr.SCHEMA_PROGRESS
        assert len(spine["runs"]) == 2
