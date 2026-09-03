# -*- coding: utf-8 -*-
"""tests/test_budget_channel_862.py — #862 budget 通道归一。

B4 CONFIRMED: battery 只从 description 解析 dispatch 形状 → 生产通道（prompt）
上 cid-keyed 门静默失效。合同通道 = prompt（dispatch-protocol.md 协议 v1
JSON envelope）。弃用通道（description 形状）→ fail-closed REJECT `devchannel`。
pass-token 归一：devreason 只认 canonical `agent-reasoning:`。
"""
import contextlib
import importlib.util
import io
import sys
from pathlib import Path

_HERE = Path(__file__).parent
# #770: hooks/scripts 以 importlib 隔离名加载，禁止顶层 sys.path.insert
# （共享名模块解析顺序会被本文件改写，殃及后续套件）。


def _load(name, relpath):
    path = _HERE.parent / relpath
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_pre_check_mod = _load("worker_budget_sinks_862", "hooks/worker_budget_sinks.py")
pre_check = _pre_check_mod.pre_check

_tb = _load("test_worker_budget_862", "tests/test_worker_budget.py")
_healthy_ws = _tb._healthy_ws
_paths_for = _tb._paths_for
_write_register = _tb._write_register

ENV = ('{"kunglao_dispatch": {"version": 1, "claim": "C-001", "tier": 1, '
       '"tools": ["grep"], "agent": "w-test"}}')


def _env(tier=1, tools="grep"):
    env = ENV
    if tier != 1:
        env = env.replace('"tier": 1', f'"tier": {tier}')
    if tools != "grep":
        env = env.replace('"tools": ["grep"]', f'"tools": ["{tools}"]')
    return env




def _payload(prompt, description=""):
    return {"tool_input": {"name": "w-test",
                           "description": description,
                           "prompt": prompt}}


def _run(payload, paths):
    buf_err, buf_out = io.StringIO(), io.StringIO()
    with contextlib.redirect_stderr(buf_err), \
            contextlib.redirect_stdout(buf_out):
        rc = pre_check(payload, paths)
    return rc, buf_err.getvalue(), buf_out.getvalue()


def test_prompt_channel_gates_apply(tmp_path):
    """#862: 形状在 prompt（合同通道）→ cid-keyed cap 门真实生效。

    红：当前只解析 description → prompt 信封被无视 → cap 门空转通过。"""
    ws = _healthy_ws(tmp_path)
    _write_register(ws / "claim-register.yaml", [
        {"id": "C-001", "status": "OPEN", "promotion_attempts": 3,
         "evidence_tier_attempted": 1},
    ])
    rc, err, _ = _run(_payload(_env() + "\nfacts-snapshot: 1 facts\n"
                               "agent-reasoning: test"), _paths_for(ws))
    assert rc == 2, err
    assert "REJECT cap" in err, err


def test_description_only_shape_rejected(tmp_path):
    """#862 负例：形状仅在 description（弃用通道）→ REJECT devchannel。

    红：当前 description 解析有效 → 门照常空转通过。"""
    ws = _healthy_ws(tmp_path)
    rc, err, _ = _run(_payload(prompt="facts-snapshot: 1 facts\n",
                               description="[T1 tools=grep] claim C-001 strings"),
                      _paths_for(ws))
    assert rc == 2, err
    assert "devchannel" in err, err


def test_devreason_requires_canonical_marker(tmp_path):
    """#862: 偏差场景（派发 rank#2 的 C-001）下裸 reasoning: 不再过门，
    canonical agent-reasoning: 通过。"""
    ws = _healthy_ws(tmp_path)
    _write_register(ws / "claim-register.yaml", [
        {'id': 'C-001', 'status': 'OPEN', 'promotion_attempts': 0,
         'evidence_tier_attempted': 3,
         'statement': 'decompile main'},
        {'id': 'C-002', 'status': 'OPEN', 'promotion_attempts': 0,
         'evidence_tier_attempted': 1,
         'statement': 'strings triage of packer; xor decode; config extract'},
    ])
    (ws / 'runs' / 'plan-C002-x.md').write_text(
        'goal: c2' + chr(10) + 'steps:' + chr(10) + 'fallback:' + chr(10),
        encoding='utf-8')
    env_c001 = ENV.replace('"tier": 1', '"tier": 2')
    rc, err, _ = _run(_payload(env_c001 + chr(10) + 'facts-snapshot: 1 facts' + chr(10)
                               + 'reasoning: why not rank1'), _paths_for(ws))
    assert rc == 2, err
    assert 'devreason' in err, err
    rc2, err2, _ = _run(_payload(env_c001 + chr(10) + 'facts-snapshot: 1 facts' + chr(10)
                                 + 'agent-reasoning: why not rank1'),
                        _paths_for(ws))
    assert rc2 == 0, err2

def test_no_shape_anywhere_passthrough(tmp_path):
    """无形状（非 kunglao Agent 调用）→ cid 门空转（既有语义，不回归）。"""
    ws = _healthy_ws(tmp_path)
    rc, err, _ = _run(_payload("facts-snapshot: 1 facts\n"), _paths_for(ws))
    assert rc == 0, err
