# -*- coding: utf-8 -*-
"""tests/test_status_narration_811.py — issue 811 状态叙事面（成就前沿只读投影）。

覆盖 issue 811 验收 2/3：一条命令返回 当前 claim / blockers / next /
waiting-on 四要素；中文 UX；与统一模型对齐（episode_phase + commit 菜单
= P2 meta_policy 的只读投影）；只读不写；absent 形状诚实。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import status_narration as sn  # noqa: E402


def _mk_ws(tmp_path, *, claim=None, episode=False, blocker=None,
           dual_case=None):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    claims = []
    if claim:
        claims.append({"id": claim, "status": "IN_PROGRESS",
                       "question": f"{claim}?"})
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True),
        encoding="utf-8")
    if episode and claim:
        ep_dir = ws / "runs" / "episodes"
        ep_dir.mkdir(parents=True)
        (ep_dir / f"episode-{claim}.md").write_text(
            "---\nschema: episode/1\nclaim: %s\n---\nbody\n" % claim,
            encoding="utf-8")
    if blocker:
        (ws / "blockers").mkdir(parents=True)
        (ws / "blockers" / f"{blocker}.md").write_text(
            f"# {blocker}\nvm network down\n", encoding="utf-8")
    if dual_case:
        dg = ws / "runs" / "dual-gate"
        dg.mkdir(parents=True)
        (dg / f"{dual_case}.json").write_text(json.dumps({
            "case_id": dual_case, "source": "user", "status": "open",
            "assertion": "size gate 是因"},
            ensure_ascii=False), encoding="utf-8")
    return ws


def _ws_digest(ws: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(ws.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(ws)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


# ---------- 四要素投影 ----------

def test_full_frontier_has_four_faces(tmp_path):
    ws = _mk_ws(tmp_path, claim="C-01", episode=True, blocker="B-07",
                dual_case="user-sig-001")
    view = sn.build_view(ws)
    assert view["schema"] == "status-narration/1"
    assert set(view["faces"]) == {"current", "blockers", "next",
                                  "waiting_on"}
    assert view["faces"]["current"]["claim"] == "C-01"
    assert view["faces"]["blockers"]["count"] == 1
    assert view["faces"]["waiting_on"]["count"] >= 1


def test_zh_render_contains_four_elements(tmp_path):
    """合成夹具钉：给定前沿状态 → 中文叙事含四要素。"""
    ws = _mk_ws(tmp_path, claim="C-01", episode=True, blocker="B-07",
                dual_case="user-sig-001")
    text = sn.render_zh(sn.build_view(ws))
    assert "C-01" in text            # 当前 claim
    assert "B-07" in text            # 阻塞
    assert "下一步" in text          # next（要素标签存在）
    assert "user-sig-001" in text    # waiting-on
    for tag in ("当前", "阻塞", "下一步", "等待"):
        assert f"【{tag}】" in text, f"missing element tag {tag}"


# ---------- 统一模型对齐：episode_phase + commit 菜单只读投影 ----------

def test_phase_projection_commit_boundary(tmp_path):
    """有 episode 的 claim → commit_boundary，菜单 = persist/tune/switch。"""
    ws = _mk_ws(tmp_path, claim="C-01", episode=True)
    cur = sn.build_view(ws)["faces"]["current"]
    assert cur["phase"] == "commit_boundary"
    assert cur["commit_menu"] == ("persist", "tune", "switch")


def test_phase_projection_episode_start(tmp_path):
    """无 episode → episode_start，菜单 = select（episode 起点）。"""
    ws = _mk_ws(tmp_path, claim="C-01")
    cur = sn.build_view(ws)["faces"]["current"]
    assert cur["phase"] == "episode_start"
    assert cur["commit_menu"] == ("select",)


# ---------- waiting-on 来源 ----------

def test_waiting_on_dual_gate_and_blockers(tmp_path):
    ws = _mk_ws(tmp_path, claim="C-01", blocker="B-07",
                dual_case="user-sig-001")
    wo = sn.build_view(ws)["faces"]["waiting_on"]
    whats = " ".join(str(i.get("what", "")) for i in wo["items"])
    assert "user-sig-001" in whats
    assert "B-07" in whats
    whoms = " ".join(str(i.get("whom", "")) for i in wo["items"])
    assert "verifier" in whoms
    assert "operator" in whoms


def test_waiting_on_empty_when_resolved(tmp_path):
    """无 open case / 无 blocker → waiting_on 空且诚实。"""
    ws = _mk_ws(tmp_path, claim="C-01")
    wo = sn.build_view(ws)["faces"]["waiting_on"]
    assert wo["count"] == 0
    assert wo["items"] == []


# ---------- absent 形状诚实 + 永不 raise ----------

def test_empty_ws_absent_shape(tmp_path):
    ws = _mk_ws(tmp_path)
    view = sn.build_view(ws)
    assert view["faces"]["current"]["claim"] is None
    assert view["faces"]["current"]["phase"] is None
    assert view["faces"]["blockers"]["count"] == 0
    text = sn.render_zh(view)
    for tag in ("当前", "阻塞", "下一步", "等待"):
        assert f"【{tag}】" in text  # 空态也报四要素（诚实「无」）


# ---------- 只读投影钉 ----------

def test_projection_is_read_only(tmp_path):
    ws = _mk_ws(tmp_path, claim="C-01", episode=True, blocker="B-07",
                dual_case="user-sig-001")
    before = _ws_digest(ws)
    sn.build_view(ws)
    sn.render_zh(sn.build_view(ws))
    assert _ws_digest(ws) == before


# ---------- CLI：一条命令返回 ----------

def test_cli_returns_zh_narrative(tmp_path):
    ws = _mk_ws(tmp_path, claim="C-01", episode=True, blocker="B-07")
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "status_narration.py"),
         str(ws)], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert "C-01" in r.stdout
    assert "【当前】" in r.stdout


def test_cli_json_envelope(tmp_path):
    ws = _mk_ws(tmp_path, claim="C-01")
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "status_narration.py"),
         str(ws), "--json"], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    doc = json.loads(r.stdout)
    assert doc["schema"] == "status-narration/1"
