# -*- coding: utf-8 -*-
"""tests/test_secondstop_anchor_831.py — #831 second-stop 锚定与对账。

契约（蓝图 L2 / openspec issue-831）：
  A1 首次 sanctioned second-stop PASS → 放行 + ledger 追加锚
     (type=second_stop_pass, record_sha256 = canonical-json sha256)
  A2 重复放行不重复锚（幂等）
  A3 锚定后改写/回填 oracle 豁免记录 → BLOCK（fail-closed, #831 核心攻击面）
  A4 ledger 不可读 → BLOCK（无法证明制裁）
  A5 锚定写失败 → BLOCK（等价于无法证明制裁）
  A6 无制裁仍 BLOCK（#147/#199 回归守卫）
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"

SECOND_STOP_EVENT = "second_stop_pass"


def _load_shim():
    name = "completion_gate_hook_831"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, HOOKS / "completion_gate.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _sha(adj: dict) -> str:
    return hashlib.sha256(json.dumps(
        adj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _mk_ws(tmp_path: Path, oracle: dict) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "claim-register.yaml").write_text("claims: []\n", encoding="utf-8")
    (ws / "task-oracle.yaml").write_text(
        yaml.safe_dump(oracle, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    return ws


def _run(ws: Path) -> tuple[int, str]:
    mod = _load_shim()
    payload = {"hook_event_name": "Stop", "session_id": "t",
               "cwd": str(ws), "stop_hook_active": True}
    buf = io.StringIO()
    import contextlib
    with contextlib.redirect_stdout(buf):
        rc = mod.main(io.StringIO(json.dumps(payload)))
    return rc, buf.getvalue()


def _anchor_rows(ws: Path) -> list[dict]:
    p = ws / ".convergence_ledger.jsonl"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("type") == SECOND_STOP_EVENT:
            rows.append(row)
    return rows


def _adj(second_stop=True, last="PASS", extra=None) -> dict:
    adj = {"second_stop": second_stop, "last_decision": last}
    if extra:
        adj.update(extra)
    return {"adjudication": {"stop_hook_active": adj}}


def test_first_sanctioned_pass_anchors(tmp_path):
    adj = {"second_stop": True, "last_decision": "PASS",
           "last_decision_at": "2026-08-31T02:55:00Z"}
    ws = _mk_ws(tmp_path, {"task_text": "x",
                           "adjudication": {"stop_hook_active": adj}})
    rc, out = _run(ws)
    assert rc == 0, out
    rows = _anchor_rows(ws)
    assert len(rows) == 1, rows
    assert rows[0]["record_sha256"] == _sha(adj)
    assert rows[0]["actor"] == "completion_gate"


def test_repeat_pass_no_duplicate_anchor(tmp_path):
    adj = {"second_stop": True, "last_decision": "PASS"}
    ws = _mk_ws(tmp_path, {"task_text": "x",
                           "adjudication": {"stop_hook_active": adj}})
    rc1, _ = _run(ws)
    rc2, _ = _run(ws)
    assert rc1 == 0 and rc2 == 0
    assert len(_anchor_rows(ws)) == 1


def test_backdated_rewrite_blocks(tmp_path):
    adj0 = {"second_stop": True, "last_decision": "PASS"}
    ws = _mk_ws(tmp_path, {"task_text": "x",
                           "adjudication": {"stop_hook_active": adj0}})
    assert _run(ws)[0] == 0
    # 攻击：锚定后回填 last_decision_at（#831 现场形态）
    ws_oracle = ws / "task-oracle.yaml"
    bad = {"task_text": "x",
           "adjudication": {"stop_hook_active": dict(
               adj0, last_decision_at="2026-08-31T02:55:00Z")}}
    (ws_oracle).write_text(
        yaml.safe_dump(bad, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    rc, out = _run(ws)
    assert rc == 1, out
    d = json.loads(out)
    assert d["decision"] == "block"
    assert "#831" in d["reason"] and ("rewritten" in d["reason"]
                                      or "backdated" in d["reason"])


def test_ledger_unreadable_blocks(tmp_path):
    adj = {"second_stop": True, "last_decision": "PASS"}
    ws = _mk_ws(tmp_path, {"task_text": "x",
                           "adjudication": {"stop_hook_active": adj}})
    (ws / ".convergence_ledger.jsonl").mkdir()
    rc, out = _run(ws)
    assert rc == 1, out
    assert "#831" in json.loads(out)["reason"]


def test_ledger_write_failure_blocks(tmp_path):
    adj = {"second_stop": True, "last_decision": "PASS"}
    ws = _mk_ws(tmp_path, {"task_text": "x",
                           "adjudication": {"stop_hook_active": adj}})
    (ws / ".convergence_ledger.jsonl").mkdir()
    rc, out = _run(ws)
    assert rc == 1
    # 第二次跑（ledger 仍不可写/不可读）同样 fail-closed，不静默放行
    rc2, out2 = _run(ws)
    assert rc2 == 1 and "#831" in json.loads(out2)["reason"]


def test_unsanctioned_still_blocks(tmp_path):
    ws = _mk_ws(tmp_path, {"task_text": "x"})
    rc, out = _run(ws)
    assert rc == 1
    d = json.loads(out)
    assert "second stop without oracle sanction" in d["reason"]
