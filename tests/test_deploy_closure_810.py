# -*- coding: utf-8 -*-
"""tests/test_deploy_closure_810.py — #810 部署反转闭包盲区。

用户裁决方向：完整部署（全量镜像），闭包语义不可救。三条红线：
  R1 全量镜像：scripts/*.py 全量 + references/ templates/ tools/ 数据资产
  R2 校验面：动态引用 ⊆ 已部署集合，缺失 fail-closed 列清单
  R3 激活自检：部署面缺失 → env_incident 落账 + 报缺清单（不静默残废）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import deploy_manifest as dm  # noqa: E402


def _srcs(entries) -> set:
    return {str(e["src"]) for e in entries}


def test_live_run_sample_15_missing_scripts_now_deployed():
    """豆包现场量化缺失的 15 个 scripts 名单全部进部署面。"""
    missing15 = [
        "backtrack_gate", "convergence_check", "convergence_health",
        "env_state_probe", "feedback", "heartbeat_tick", "hooks_selfcheck",
        "kunglao-init", "kunglao-monitor", "kunglao_upgrade",
        "plan_drift_detector", "references_recall", "rollup", "think_seat",
        "verify_status_watch",
    ]
    srcs = _srcs(dm.build_entries())
    for name in missing15:
        assert f"scripts/{name}.py" in srcs, name


def test_data_assets_deployed():
    """references/ templates/ tools/ 数据资产随 hooks/agents 一起物化。"""
    srcs = _srcs(dm.build_entries())
    assert "references/machine_check_map.yaml" in srcs
    assert "references/_INDEX.md" in srcs
    assert "templates/CLAUDE.md.base.tmpl" in srcs
    assert "tools/_INDEX.ext.yaml" in srcs


def test_full_scripts_mirror():
    """scripts/*.py 全量镜像：仓库里每个脚本都必须在清单里，无闭包裁剪。"""
    srcs = _srcs(dm.build_entries())
    disk = {f"scripts/{p.name}" for p in SCRIPTS.glob("*.py")}
    assert disk <= srcs, sorted(disk - srcs)[:5]


def test_dynamic_refs_subset_of_deployed():
    """校验面绿：hooks+scripts 的动态引用 ⊆ 已部署集合（全量镜像下恒真）。"""
    refs = dm.dynamic_script_refs()
    srcs = _srcs(dm.build_entries())
    deployed = {s for s in srcs if s.startswith("scripts/")}
    assert refs <= deployed, sorted(refs - deployed)[:5]
    assert dm.closure_validation(dm.build_entries()) == []


def test_closure_validation_catches_missing():
    """校验面红：从清单里抽掉一个动态引用脚本 → 校验面指名道姓。"""
    entries = dm.build_entries()
    victim = "scripts/plan_drift_detector.py"
    pruned = [e for e in entries if e["src"] != victim]
    out = dm.closure_validation(pruned)
    assert out and any(victim in v for v in out), out


def test_completeness_report(tmp_path):
    """载体 dests 完整性报告：缺一报一，全在则空。"""
    ws = tmp_path / "ws"
    (ws / ".claude" / "scripts").mkdir(parents=True)
    entries = [
        {"dest": ".claude/scripts/a.py", "sha256": "x"},
        {"dest": ".claude/scripts/b.py", "sha256": "x"},
    ]
    (ws / ".claude" / "scripts" / "a.py").write_text("x", encoding="utf-8")
    (ws / ".claude" / "scripts" / "b.py").write_text("x", encoding="utf-8")
    dm.write_carrier(ws, entries)
    import hook_activation as ha
    missing = ha.completeness_report(ws)
    assert missing == [], missing
    (ws / ".claude" / "scripts" / "b.py").unlink()
    missing = ha.completeness_report(ws)
    assert missing == [".claude/scripts/b.py"], missing


def test_activation_writes_env_incident_on_incomplete(tmp_path):
    """R3：激活写入面在部署面缺失时 env_incident 落账（全 ledger glob）。"""
    import hook_activation as ha
    ws = tmp_path / "ws"
    (ws / "runs" / "logs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    entries = [{"dest": ".claude/scripts/a.py", "sha256": "x"},
               {"dest": ".claude/scripts/missing.py", "sha256": "x"}]
    (ws / ".claude" / "scripts").mkdir(parents=True)
    (ws / ".claude" / "scripts" / "a.py").write_text("x", encoding="utf-8")
    dm.write_carrier(ws, entries)
    ha.update_state(ws, tier="none", phase="IDLE",
                    set_active=["completion_gate"])
    rows = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        rows.extend(json.loads(line) for line in
                    p.read_text(encoding="utf-8").splitlines())
    inc = [r for r in rows
           if r.get("action") == "env_incident"
           and "missing.py" in str(r.get("detail", ""))]
    assert inc, "env_incident must be emitted with the missing list"


def test_deployed_writer_emits_canonical_shape(tmp_path):
    """#810 correction (audit B5 CONFIRMED)：deployed 注册以标准事件名为键、
    matcher 在 matcher 字段——并携带旧 writer 丢失的全部接线。"""
    import hook_activation as ha
    import wire_up_settings as wus
    ws = tmp_path / "ws"
    assert ha.register_hooks_deployed(ws) == 0
    settings = json.loads(
        (ws / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings.get("hooks") or {}
    assert not (set(hooks) - wus.HOOK_EVENTS), \
        sorted(set(hooks) - wus.HOOK_EVENTS)

    def matchers(event):
        return {e.get("matcher") for e in hooks.get(event) or []}

    def has_cmd(event, matcher, name):
        for e in hooks.get(event) or []:
            if matcher and e.get("matcher") != matcher:
                continue
            for h in e.get("hooks") or []:
                if name in str(h.get("command", "")):
                    return True
        return False

    # 旧 writer 丢失的三类接线，逐一回归
    assert "Edit|Write|MultiEdit" in matchers("PreToolUse")     # write_guard
    assert has_cmd("PostToolUse", "Bash", "violation_capture.py")
    assert has_cmd("PostToolUse", "Bash", "bash_fact_guard.py")
    assert has_cmd("PreToolUse", "Agent", "worker_budget.py")
    assert has_cmd("PostToolUse", "Agent", "worker_budget.py")  # #675 双注册
    assert has_cmd("PreToolUse", "Bash", "heartbeat_touch.py")
    assert has_cmd("Stop", "", "heartbeat_touch.py")            # #618 双槽
    assert wus.registration_shape_issues(settings) == []


def test_three_checkers_one_truth(tmp_path):
    """伪事件键形状下三个 checker 必须给出同一（否定）答案。"""
    import hook_activation as ha
    import wire_up_settings as wus
    import hooks_selfcheck as hsc
    bad = {"hooks": {"Agent": [{"hooks": [{"command": "x"}]}]}}
    assert wus.registration_shape_issues(bad), "shape validator must flag"
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps(bad), encoding="utf-8")
    out = hsc.check_settings(sp)
    assert out.get("shape_issues"), "hooks_selfcheck must flag"
    r = ha.selfcheck_registration(
        sp, expected_files=["env_check_gate.py"], layer="project")
    assert r["ok"] is False and any("shape" in m for m in r["mismatches"])
