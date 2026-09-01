# -*- coding: utf-8 -*-
"""tests/test_summary_fake_826.py — #826 shim 集成测试。

集成点：hooks/completion_gate.py would-PASS 点（NOTES_FAKE 之后）接入
summary 判别器——不确定性蒸发的 summary → block rc=7 SUMMARY_FAKE；
合规 summary → 放行；判别器异常 fail-open（双笼，同 NOTES_DUE 惯例）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import rollup  # noqa: E402

HOOKS = ROOT / "hooks"


def _load_shim():
    name = "completion_gate_hook_826"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, HOOKS / "completion_gate.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _make_ws(tmp_path, claims):
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, allow_unicode=True), encoding="utf-8")
    return ws


def _activated_state(ws):
    import datetime as dt
    expires = (dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(minutes=30)
               ).isoformat(timespec="seconds").replace("+00:00", "Z")
    (ws / ".hook_state.json").write_text(json.dumps({
        "ts": "2026-08-13T00:00:00Z",
        "tier": "none",
        "phase": "IDLE",
        "active_hooks": ["completion_gate"],
        "paused_hooks": [],
        "user_override": {},
        "expires_at": expires,
    }), encoding="utf-8")


def _would_pass_oracle(ws):
    oracle = {
        "task_text": "analyze the payload",
        "open_items": [{"id": "OC-1", "closed_by": "verifier"}],
    }
    (ws / "task-oracle.yaml").write_text(
        yaml.safe_dump(oracle, sort_keys=False), encoding="utf-8")


FACT_PROVEN = (
    "---\nid: F001\nstatus: PROVEN\n---\n"
    "handler at 0x14002abcd, allocation 0x150 via size gate.\n")

FACT_PARTIAL = (
    "---\nid: F002\nstatus: PARTIALLY-VERIFIED\n---\n"
    "offset 0x150 hypothesis unconfirmed, pending dynamic check.\n")


def _mk_facts(ws):
    (ws / "facts").mkdir(exist_ok=True)
    (ws / "facts" / "F001.md").write_text(FACT_PROVEN, encoding="utf-8")
    (ws / "facts" / "F002.md").write_text(FACT_PARTIAL, encoding="utf-8")


def test_evaporating_summary_blocks_closure(tmp_path, capsys):
    """完成词 + 非 PROVEN fact + 无暂定节 → block rc=7 SUMMARY_FAKE。"""
    shim = _load_shim()
    ws = _make_ws(tmp_path, [{"id": "C-302", "status": "PROVEN"}])
    rollup.sweep_terminal_claims(ws)
    _activated_state(ws)
    _would_pass_oracle(ws)
    _mk_facts(ws)
    (ws / "notes").mkdir(exist_ok=True)
    (ws / "notes" / "C-302.md").write_text(
        "---\nid: C-302\nclaim_id: C-302\nverify_status: pending\n"
        "---\n# durable result\n\n"
        "Timing analysis: the size gate precedes the handler write. "
        "Evidence: F001, F002.\n",
        encoding="utf-8")
    (ws / "summary.md").write_text(
        "# 分析收敛完成\n\nq1 已全部闭合，协议已完整还原。\n",
        encoding="utf-8")
    rc = shim.process_event({"cwd": str(ws)})
    out = capsys.readouterr().out
    assert rc == 7, f"evaporating summary must refuse closure rc=7, got rc={rc}"
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "SUMMARY_FAKE" in decision["reason"], decision["reason"]


def test_compliant_summary_allows_closure(tmp_path, capsys):
    """带暂定节 + 不确定性传播的合规 summary → rc=0 放行。"""
    shim = _load_shim()
    ws = _make_ws(tmp_path, [{"id": "C-302", "status": "PROVEN"}])
    rollup.sweep_terminal_claims(ws)
    _activated_state(ws)
    _would_pass_oracle(ws)
    _mk_facts(ws)
    (ws / "notes").mkdir(exist_ok=True)
    (ws / "notes" / "C-302.md").write_text(
        "---\nid: C-302\nclaim_id: C-302\nverify_status: pending\n"
        "---\n# durable result\n\n"
        "Timing analysis: the size gate precedes the handler write. "
        "Evidence: F001, F002.\n",
        encoding="utf-8")
    (ws / "summary.md").write_text(
        "# 分析小结\n\nhandler 已定位（F001）；偏移为暂定（F002），"
        "待动态验证。\n",
        encoding="utf-8")
    rc = shim.process_event({"cwd": str(ws)})
    assert rc == 0, f"compliant summary must pass, got rc={rc}"


def test_discriminator_error_fails_open(tmp_path):
    """判别器 IO 错误 fail-open 放行（双笼，永不 deadlock）。"""
    shim = _load_shim()
    ws = _make_ws(tmp_path, [{"id": "C-302", "status": "PROVEN"}])
    rollup.sweep_terminal_claims(ws)
    _activated_state(ws)
    _would_pass_oracle(ws)
    _mk_facts(ws)
    (ws / "notes").mkdir(exist_ok=True)
    (ws / "notes" / "C-302.md").write_text(
        "---\nid: C-302\nclaim_id: C-302\nverify_status: pending\n"
        "---\n# durable result\n\nEvidence: F001, F002.\n",
        encoding="utf-8")
    (ws / "summary.md").mkdir()  # summary 是目录 → read_text 炸 → fail-open
    rc = shim.process_event({"cwd": str(ws)})
    assert rc == 0, f"discriminator IO error must fail-open, got rc={rc}"
