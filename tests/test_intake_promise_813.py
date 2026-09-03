# -*- coding: utf-8 -*-
"""tests/test_intake_promise_813.py — #813 Phase 0 预扫描 promise 块。

build(report, task_spec, ws) 纯函数产出 promise dict；apply() 合并进
task_spec.yaml 的 `promise:` 键（不可解析 → PromiseError fail-closed；
task_spec 缺失 → runs/intake-promise.yaml 降级）。

本宿主铁律（memory）：apkid/DIE 缺失是 WARN 不卡 init——但"跳过且不记录"
才是 #813 要消灭的，所以 missing 必须带 fix 提示显式记录。
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import intake_promise  # noqa: E402


def _report(*items) -> SimpleNamespace:
    return SimpleNamespace(items=list(items))


def _item(name: str, status: str, fix: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(name=name, status=status, fix=fix)


def _ws(tmp_path, task_spec=None, evidence=None):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    if task_spec is not None:
        (ws / "task_spec.yaml").write_text(
            yaml.safe_dump(task_spec, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    if evidence is not None:
        (ws / "evidence").mkdir(exist_ok=True)
        import json
        (ws / "evidence" / "apkid.json").write_text(
            json.dumps(evidence), encoding="utf-8")
    return ws


# ---------- prescan 探测状态（显式记录，消灭"跳过且不记录"） ----------

def test_apkid_missing_explicit_warn(tmp_path):
    """apkid 探测 FAIL（WARN-tier）→ missing + fix 提示显式记录。"""
    ws = _ws(tmp_path, task_spec={"constraints": {"dynamic_re": "allowed"}})
    rep = _report(_item("apkid", "FAIL", fix="pip install apkid"))
    p = intake_promise.build(rep, {"constraints": {"dynamic_re": "allowed"}}, ws)
    assert p["prescan"]["apkid"]["state"] == "missing"
    assert "install" in p["prescan"]["apkid"]["note"]
    assert p["prescan"]["apkid"]["tier"] == "WARN"


def test_apkid_available(tmp_path):
    ws = _ws(tmp_path)
    rep = _report(_item("apkid", "PASS"))
    p = intake_promise.build(rep, None, ws)
    assert p["prescan"]["apkid"]["state"] == "available"
    assert p["prescan"]["die"]["state"] == "not_probed"


def test_not_probed_is_explicit(tmp_path):
    """探针层不在 project_type 集内 → not_probed 显式记录，不静默缺键。"""
    ws = _ws(tmp_path)
    rep = _report(_item("apkid", "PASS"))
    p = intake_promise.build(rep, None, ws)
    assert p["prescan"]["die"]["state"] == "not_probed"
    assert "note" in p["prescan"]["die"]


# ---------- 混淆先验（与 route_capability #692 WP6 同源同键） ----------

def test_obfuscation_prior_extracted(tmp_path):
    ws = _ws(tmp_path, evidence={"summary": {"obfuscator": [
        "proguard", "dash_o"]}})
    rep = _report(_item("apkid", "PASS"))
    p = intake_promise.build(rep, None, ws)
    assert p["obfuscation_prior"]["obfuscators"] == ["proguard", "dash_o"]
    assert p["obfuscation_prior"]["source"] == "evidence/apkid.json"


def test_obfuscation_prior_null_when_absent(tmp_path):
    ws = _ws(tmp_path)
    rep = _report(_item("apkid", "PASS"))
    p = intake_promise.build(rep, None, ws)
    assert p["obfuscation_prior"]["obfuscators"] == []
    assert p["obfuscation_prior"]["source"] is None


# ---------- java 可达性（#807 死胡同根因面） ----------

def test_static_only_unreachable_dead_end_note(tmp_path):
    """static-only + 三个 java 前端全缺 → unreachable + #807 死胡同警示。"""
    ws = _ws(tmp_path, task_spec={"constraints": {"dynamic_re": "forbidden"}})
    rep = _report(_item("jadx", "FAIL"), _item("baksmali", "FAIL"),
                  _item("apktool", "FAIL"))
    p = intake_promise.build(
        rep, {"constraints": {"dynamic_re": "forbidden"}}, ws)
    jr = p["java_reachability"]
    assert jr["verdict"] == "unreachable"
    assert "#807" in jr["note"]
    assert jr["static_only"] is True


def test_java_reachability_reachable_and_degraded(tmp_path):
    ws = _ws(tmp_path)
    rep = _report(_item("jadx", "PASS"), _item("baksmali", "FAIL"),
                  _item("apktool", "FAIL"))
    p = intake_promise.build(rep, None, ws)
    assert p["java_reachability"]["verdict"] == "reachable"
    rep2 = _report(_item("jadx", "FAIL"), _item("baksmali", "PASS"),
                   _item("apktool", "FAIL"))
    p2 = intake_promise.build(rep2, None, ws)
    assert p2["java_reachability"]["verdict"] == "degraded"


def test_static_only_with_jadx_no_dead_end(tmp_path):
    """static-only 但 jadx 可用 → reachable，无死胡同警示。"""
    ws = _ws(tmp_path, task_spec={"constraints": {"dynamic_re": "forbidden"}})
    rep = _report(_item("jadx", "PASS"))
    p = intake_promise.build(
        rep, {"constraints": {"dynamic_re": "forbidden"}}, ws)
    jr = p["java_reachability"]
    assert jr["verdict"] == "reachable"
    assert jr["static_only"] is True
    assert "#807" not in jr["note"]


# ---------- apply：task_spec 合并 / 降级 / fail-closed ----------

def test_apply_merges_into_task_spec_preserving_user_keys(tmp_path):
    ws = _ws(tmp_path, task_spec={
        "constraints": {"dynamic_re": "allowed"},
        "primary_questions": ["q1"],
    })
    rep = _report(_item("apkid", "PASS"))
    promise = intake_promise.build(rep, {"constraints": {}}, ws)
    path = intake_promise.apply(ws, promise)
    assert path == ws / "task_spec.yaml"
    merged = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert merged["constraints"] == {"dynamic_re": "allowed"}
    assert merged["primary_questions"] == ["q1"]
    assert merged["promise"]["prescan"]["apkid"]["state"] == "available"


def test_apply_fallback_runs_file_when_task_spec_absent(tmp_path):
    ws = _ws(tmp_path)
    rep = _report(_item("apkid", "PASS"))
    promise = intake_promise.build(rep, None, ws)
    path = intake_promise.apply(ws, promise)
    assert path == ws / "runs" / "intake-promise.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert "prescan" in data


def test_apply_unparseable_task_spec_raises(tmp_path):
    ws = _ws(tmp_path)
    (ws / "task_spec.yaml").write_text("a: [1,\n  broken", encoding="utf-8")
    rep = _report(_item("apkid", "PASS"))
    promise = intake_promise.build(rep, None, ws)
    with pytest.raises(intake_promise.PromiseError):
        intake_promise.apply(ws, promise)
