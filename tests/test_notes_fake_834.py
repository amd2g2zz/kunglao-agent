# -*- coding: utf-8 -*-
"""tests/test_notes_fake_834.py — #834 shim 集成测试。

集成点：hooks/completion_gate.py would-PASS 点（NOTES_DUE 清空后）接入
notes 判别器——复制冒充 note → block exit 6 NOTES_FAKE；引用型 note → 放行；
判别器异常 fail-open 放行（双笼，同 notes_due 惯例）。
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
    name = "completion_gate_hook_834"
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


FACT_BODY = (
    "the payload registers its exception handler at 0x14002abcd and "
    "allocates 0x150 bytes via a size gate comparison before the write.\n"
)


def _mk_fact(ws):
    (ws / "facts").mkdir(exist_ok=True)
    (ws / "facts" / "F001-crash.md").write_text(FACT_BODY, encoding="utf-8")


def test_copied_note_blocks_closure(tmp_path, capsys):
    """复制 fact 正文的 note 清空 owed 后，must block rc=6 NOTES_FAKE。"""
    shim = _load_shim()
    ws = _make_ws(tmp_path, [{"id": "C-302", "status": "PROVEN"}])
    rollup.sweep_terminal_claims(ws)
    _activated_state(ws)
    _would_pass_oracle(ws)
    _mk_fact(ws)
    (ws / "notes").mkdir(exist_ok=True)
    (ws / "notes" / "C-302.md").write_text(
        "---\nclaim_id: C-302\n---\n" + FACT_BODY, encoding="utf-8")
    rc = shim.process_event({"cwd": str(ws)})
    out = capsys.readouterr().out
    assert rc == 6, f"copied note must refuse closure rc=6, got rc={rc}"
    decision = json.loads(out)
    assert decision["decision"] == "block"
    assert "NOTES_FAKE" in decision["reason"], decision["reason"]
    assert "C-302.md" in decision["reason"]


def test_reference_note_allows_closure(tmp_path, capsys):
    """引用型 note（fact id + 独立叙事）→ rc=0 放行。"""
    shim = _load_shim()
    ws = _make_ws(tmp_path, [{"id": "C-302", "status": "PROVEN"}])
    rollup.sweep_terminal_claims(ws)
    _activated_state(ws)
    _would_pass_oracle(ws)
    _mk_fact(ws)
    (ws / "notes").mkdir(exist_ok=True)
    (ws / "notes" / "C-302.md").write_text(
        "---\nclaim_id: C-302\n---\n"
        "Timing analysis shows allocation precedes handler registration; "
        "evidence F001 for the size gate. Conclusion provisional.\n",
        encoding="utf-8")
    rc = shim.process_event({"cwd": str(ws)})
    assert rc == 0, f"reference-style note must pass, got rc={rc}"


def test_discriminator_error_fails_open(tmp_path):
    """判别器 IO 错误 fail-open 放行（双笼，永不 deadlock）。"""
    shim = _load_shim()
    ws = _make_ws(tmp_path, [{"id": "C-302", "status": "PROVEN"}])
    rollup.sweep_terminal_claims(ws)
    _activated_state(ws)
    _would_pass_oracle(ws)
    _mk_fact(ws)  # facts 必须存在，否则 R0（无证据即拒）先于 IO 路径触发
    (ws / "notes").mkdir(exist_ok=True)
    (ws / "notes" / "C-302.md").mkdir()  # note 是目录 → read_text 炸 → fail-open
    rc = shim.process_event({"cwd": str(ws)})
    assert rc == 0, f"discriminator IO error must fail-open, got rc={rc}"
