# -*- coding: utf-8 -*-
"""tests/test_crossproject_off_1005.py — the cross-project-off pins
(issue-1005, owner ruling 2026-11-14: no cross-project learning — a
wrongly-recalled foreign memory derails the run).

The property the replay check R9 names, pinned synthetically:

  a. with no env override, every learning-store path resolved by
     strategy_store / consolidated_ledger / marl /
     failure_analysis_gate resolves INSIDE the workspace;
  b. with KUNGLAO_POSTERIOR_STORE set OUTSIDE the workspace, the
     production faces refuse loud (the named reason rides the warn) and
     touch NOTHING at the refused path;
  c. a full settle_round_credit + episode settle pass on a synthetic
     workspace leaves NO new file outside the workspace (the tmp tree
     is snapshotted before and after);
  d. the workspace identity separates same-named workspaces in
     different parents (the former directory-name identity aliased
     them) and is stable across the workspace's lifetime.

All fixtures are SYNTHETIC (privacy rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

import failure_analysis_gate as fag  # noqa: E402
import feature_mining as fm  # noqa: E402
import rlvr.consolidated_ledger as cl  # noqa: E402
import rlvr.marl as marl  # noqa: E402
import rlvr.strategy_store as ss  # noqa: E402

STORE_ENV = "KUNGLAO_POSTERIOR_STORE"


def _ws(tmp_path: Path, name: str = "ws") -> Path:
    ws = tmp_path / name
    (ws / "runs").mkdir(parents=True, exist_ok=True)
    return ws


def _tree(tmp: Path) -> set[str]:
    """Every path under `tmp`, relative (the snapshot face)."""
    return {str(p.relative_to(tmp)) for p in tmp.rglob("*")}


# ---------- (a) every store resolves inside the workspace ----------

class TestEveryStoreResolvesInside:
    def test_strategy_store_faces(self, tmp_path, monkeypatch):
        monkeypatch.delenv(STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        root = ss.store_root(ws)
        assert root == ws / "runs" / "posterior"
        assert root.resolve().is_relative_to(ws.resolve())
        assert cl.family_path(ws, "knowledge").is_relative_to(ws)
        assert marl.neg_store_path(ws).is_relative_to(ws)

    def test_reliability_store_inside(self, tmp_path, monkeypatch):
        from rlvr import source_reliability as sr
        monkeypatch.delenv(STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        assert sr.store_path(ws).is_relative_to(ws.resolve())

    def test_feature_table_inside(self, tmp_path, monkeypatch):
        from rlvr import feature_prior as fp
        monkeypatch.delenv(STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        assert fp.default_table_path(ws).is_relative_to(ws.resolve())

    def test_lessons_faces_inside(self, tmp_path, monkeypatch):
        monkeypatch.delenv(STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        assert fag.lessons_dir(ws) == ws / "analyses" / "lessons"
        assert fag.reflect_queue_path(ws) == \
            ws / "runs" / "learnings-queue.json"
        assert fag.lessons_dir(ws).is_relative_to(ws.resolve())
        # the aggregation's default faces resolve inside the workspace
        (ws / "analyses").mkdir(exist_ok=True)
        (ws / "analyses" / "failure-C-1.yaml").write_text(yaml.safe_dump({
            "claim": "C-1", "outcome": "REFUTED",
            "method_assumption": "a", "next_method": "b",
            "what_happened": "w"}), encoding="utf-8")
        out = fag.aggregate_lessons(ws)
        assert out["queue_added"] == 1
        assert fag.reflect_queue_path(ws).is_relative_to(ws.resolve())
        assert fag.reflect_queue_path(ws).is_file()

    def test_knowledge_family_ignores_nothing(self, tmp_path, monkeypatch):
        """The store faces agree with the consolidated ledger on the
        same file — one store, one resolution."""
        monkeypatch.delenv(STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        assert ss.store_root(ws) / "knowledge-store.jsonl" == \
            cl.family_path(ws, "knowledge")


# ---------- (b) the outside override is refused loud, touches nothing ----------

class TestOutsideOverrideRefused:
    def test_store_root_refuses_and_falls_back_inside(
            self, tmp_path, monkeypatch, caplog):
        outside = tmp_path / "outside-store"
        monkeypatch.setenv(STORE_ENV, str(outside))
        ws = _ws(tmp_path)
        root = ss.store_root(ws)
        assert root == ws / "runs" / "posterior", \
            "the refused override must fall back INSIDE the workspace"
        assert not outside.exists(), "nothing is touched at the refused path"

    def test_writes_never_reach_the_refused_root(
            self, tmp_path, monkeypatch):
        outside = tmp_path / "outside-store"
        monkeypatch.setenv(STORE_ENV, str(outside))
        ws = _ws(tmp_path)
        assert ss.append_store_row(ws, method_family="graph",
                                   status="ok", credit=1.0)["appended"]
        assert marl.record_negative(ws, method_family="frida")["appended"]
        assert cl.append(ws, "knowledge", {"schema": "posterior-store/1",
                                           "workspace_id": "x"})
        # nothing landed outside; everything landed inside
        assert not outside.exists() or not list(outside.rglob("*"))
        rows = [json.loads(ln) for ln in
                cl.family_path(ws, "knowledge").read_text(
                    encoding="utf-8").splitlines() if ln.strip()]
        assert len(rows) == 3

    def test_inside_override_is_honored(self, tmp_path, monkeypatch):
        ws = _ws(tmp_path)
        inside = ws / "runs" / "eval-arm-store"
        monkeypatch.setenv(STORE_ENV, str(inside))
        assert ss.store_root(ws) == inside
        assert cl.family_path(ws, "knowledge") == \
            inside / "knowledge-store.jsonl"

    def test_rootless_resolution_refuses_loud(self, tmp_path, monkeypatch):
        monkeypatch.delenv(STORE_ENV, raising=False)
        with pytest.raises(ValueError, match="workspace"):
            cl.family_path(None, "knowledge")
        assert cl.read(None, "knowledge") == []


def _ws_rows(ws) -> list[dict]:
    p = cl.family_path(ws, "knowledge")
    if not p.is_file():
        return []
    return [json.loads(ln) for ln in
            p.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ---------- (c) a full settle pass writes nothing outside ----------

class TestSettlePassStaysInside:
    def _case_ws(self, tmp_path: Path) -> Path:
        from _dispatch_fixture import mint_dispatches
        from rlvr import q_cells
        import claims_store
        ws = tmp_path / "ws"
        (ws / "runs").mkdir(parents=True)
        (ws / "facts").mkdir()
        (ws / "claim-register.yaml").write_text(yaml.safe_dump(
            {"claims": [{"id": "C-9", "status": "REFUTED"}]}),
            encoding="utf-8")
        mint_dispatches(ws, [{"id": "C-9", "status": "REFUTED"}],
                        family="static-symbolic", pending=False)
        did = str(claims_store.latest_committed_dispatch(
            ws, "C-9")["dispatch_id"])
        q_cells.record_dispatch_observation(
            ws, "dispatch envelope",
            envelope_meta={"method_family": "static-symbolic"},
            claim="C-9", dispatch_id=did)
        return ws

    def test_settle_and_episode_leave_no_outside_file(
            self, tmp_path, monkeypatch):
        import settle_round_credit as src
        from rlvr import ledger as rl
        monkeypatch.delenv(STORE_ENV, raising=False)
        # the learning-seal key is host-level config (~/.claude) by
        # design — in the test it is provisioned INSIDE the workspace so
        # the outside-namespace assertion stays exact
        import rlvr.learning_seal as seal
        monkeypatch.setattr(seal, "KEY_PATH",
                            tmp_path / "ws" / ".claude" / "learning.key",
                            raising=False)
        ws = self._case_ws(tmp_path)
        outside = tmp_path / "outside-store"
        outside.mkdir()
        monkeypatch.setenv(STORE_ENV, str(outside))
        before = _tree(tmp_path)

        src.run(ws)                                   # the round settle
        out = rl.record(ws, kind="task", anchor="C-9",
                        signals=[{"type": "oracle_verdict",
                                  "value": "PASS", "source": "oracle",
                                  "ts": "2026-11-14T00:00:00Z"}])
        assert out.get("appended") is True
        rl.settle(ws, "task/C-9", {"reward": 1.0, "band": "SETTLED_GREEN",
                                   "rule_id": "unit-test",
                                   "evidence_refs": ["C-9"]})

        after = _tree(tmp_path)
        new = after - before
        ws_prefix = str(Path("ws"))
        escaped = sorted(p for p in new
                         if not (p == ws_prefix or p.startswith(ws_prefix
                                                              + "/")))
        assert escaped == [], \
            f"the settle pass wrote outside the workspace: {escaped}"
        assert not list(outside.rglob("*")), \
            "the refused env root was never touched"

    def test_two_same_named_workspaces_get_different_stores(
            self, tmp_path, monkeypatch):
        monkeypatch.delenv(STORE_ENV, raising=False)
        ws_a = tmp_path / "a" / "proj"
        ws_b = tmp_path / "b" / "proj"
        for ws in (ws_a, ws_b):
            ws.mkdir(parents=True)
        assert ss.workspace_id_of(ws_a) != ss.workspace_id_of(ws_b)
        assert ss.workspace_id_of(ws_a) == ss.workspace_id_of(ws_a)
        ss.append_store_row(ws_a, method_family="graph", status="ok",
                            credit=1.0)
        ss.append_store_row(ws_b, method_family="graph", status="ok",
                            credit=0.5)
        assert _ws_rows(ws_a)[0]["credit"] == 1.0
        assert _ws_rows(ws_b)[0]["credit"] == 0.5


# ---------- review-round regressions ----------


class TestReviewRoundRegressions:
    def test_store_root_symlink_escape_refused(self, tmp_path, monkeypatch):
        monkeypatch.delenv(STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        outside = tmp_path / "outside-store"
        outside.mkdir()
        (ws / "runs" / "posterior").symlink_to(outside)
        with pytest.raises(ValueError, match="resolves outside"):
            ss.store_root(ws)
        assert not list(outside.iterdir()), \
            "the escape target was never touched"

    def test_explicit_out_on_family_file_takes_append_face(
            self, tmp_path, monkeypatch):
        monkeypatch.delenv(STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        ss.append_store_row(ws, method_family="graph", status="ok",
                            credit=1.0)
        family = cl.family_path(ws, "knowledge")
        before = family.read_text(encoding="utf-8")
        rc = fm.main(["--out", str(family), "--workspace", str(ws),
                      str(tmp_path / "empty-root")])
        assert rc == 0
        after = family.read_text(encoding="utf-8")
        assert before.strip() in after, \
            "the multi-schema carrier row survived the family face"

    def test_explicit_out_on_foreign_family_file_refused(
            self, tmp_path, monkeypatch):
        monkeypatch.delenv(STORE_ENV, raising=False)
        ws = _ws(tmp_path)
        ss.append_store_row(ws, method_family="graph", status="ok",
                            credit=1.0)
        family = cl.family_path(ws, "knowledge")
        with pytest.raises(ValueError, match="carrier"):
            fm.main(["--out", str(family), str(tmp_path / "empty-root")])
        assert family.read_text(encoding="utf-8").strip(), \
            "the carrier file was never rewritten"

    def test_rebuild_face_on_plain_path_still_writes(
            self, tmp_path, monkeypatch):
        monkeypatch.delenv(STORE_ENV, raising=False)
        out = tmp_path / "feat-table.jsonl"
        rc = fm.main(["--out", str(out), str(tmp_path / "empty-root")])
        assert rc == 0
        assert out.exists()
