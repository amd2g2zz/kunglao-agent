# -*- coding: utf-8 -*-
"""tests/test_write_guard_unlock_820.py — #820 连坐解锁 TDD。

A 连坐修复  B 门不弱化  C 修复面可见  D 解锁落账  E 隔离落账  F 越界文件拒
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"
WRITE_GUARD = HOOKS / "write_guard.py"

RC_ALLOW = 0
RC_BLOCK = 2


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "notes").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-001\n"
        "    status: OPEN\n"
        "    statement: sample resolves imports dynamically\n",
        encoding="utf-8")
    (ws / "analysis_state.txt").write_text("kunglao workspace\n", encoding="utf-8")
    return ws


def _payload(ws, tool, file_path, **tool_input):
    return json.dumps({
        "tool_name": tool,
        "cwd": str(ws),
        "tool_input": {"file_path": str(file_path), **tool_input},
    }, ensure_ascii=False)


def _run_guard(ws, payload):
    env = {k: v for k, v in os.environ.items()}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(ROOT / "hooks"), str(ROOT / "scripts")])
    return subprocess.run(
        [sys.executable, str(WRITE_GUARD)],
        input=payload, capture_output=True, text=True, timeout=120,
        env=env, errors="replace")


_SHA = "a" * 64

GOOD_FACT = """---
id: F007-dynamic-imports
type: fact
title: Worker thread write
status: INFERRED
created: 2026-08-20
last_reviewed: 2026-08-20
claim_id: C-001
claim: sample resolves imports dynamically
boundary_type: observation
promotion_gate: resolve the loader stub under dynamic-trace
source: static-decompile
confidence: medium
verify_status: partial
reproduce: python runs/verify-f007.py
expected: %s
verified: pending
provenance:
  - {role: decompiled_c, path: evidence/f007.c, content_sha256: %s, credibility: B2}
---

# F007 - Worker thread write

## Status
INFERRED
""" % (_SHA, _SHA)


def _legacy_fact(cid="F001"):
    return """---
id: %s
type: fact
title: Early fact
status: VERIFIED-BY-W1-INVALID-ENUM
created: 2026-08-20
last_reviewed: 2026-08-20
claim_id: C-legacy
claim: legacy schema fact
boundary_type: observation
source: static_re
confidence: high
verify_status: partial
reproduce: python runs/verify-f001.py
expected: %s
verified: pending
provenance:
  - {role: decompiled_c, path: evidence/f001.c, credibility: B2}
---

# %s - Early fact

## Status
VERIFIED-BY-INVALID-ENUM
""" % (cid, _SHA, cid)


def _ledger_rows(ws):
    rows = []
    logs = ws / "runs" / "logs"
    if logs.is_dir():
        for p in sorted(logs.glob("kunglao-*.jsonl")):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rows.append(json.loads(line))
    return rows


def _viols(stderr):
    return [l.strip() for l in stderr.splitlines()
            if l.strip().startswith("- ")]


def test_unrelated_violations_no_longer_block(tmp_path):
    """A 连坐修复：legacy F001 不拦干净 F007（修复前 rc=2 = RED）。"""
    ws = _mk_ws(tmp_path)
    (ws / "facts" / "F001-legacy.md").write_text(_legacy_fact(), encoding="utf-8")
    p = _payload(ws, "Write", ws / "facts" / "F007-clean.md", content=GOOD_FACT)
    r = _run_guard(ws, p)
    assert r.returncode == 0, "stderr=" + r.stderr[:400]


def test_own_violations_still_block(tmp_path):
    """B 门不弱化：F009 自身违规照拦且全部归因 F009。"""
    ws = _mk_ws(tmp_path)
    (ws / "facts" / "F001-legacy.md").write_text(_legacy_fact(), encoding="utf-8")
    p = _payload(ws, "Write", ws / "facts" / "F009-dirty.md",
                 content=_legacy_fact("F009"))
    r = _run_guard(ws, p)
    assert r.returncode == 2, r.stderr[:400]
    viols = _viols(r.stderr)
    assert viols, r.stderr
    for v in viols:
        assert "F009" in v, "attribution: " + v
    assert not any("F001" in v for v in viols), viols


def test_block_detail_shows_repair_surface(tmp_path):
    """C block detail 带其他文件违规分布。"""
    ws = _mk_ws(tmp_path)
    ws = _mk_ws(tmp_path)
    (ws / "facts" / "F001-legacy.md").write_text(_legacy_fact(), encoding="utf-8")
    p = _payload(ws, "Write", ws / "facts" / "F009-dirty.md",
                 content=_legacy_fact("F009"))
    r = _run_guard(ws, p)
    assert r.returncode == 2
    assert "workspace audit" in r.stderr, r.stderr[:400]
    assert "F001-legacy.md" in r.stderr, r.stderr[:400]


def test_unlock_waives_and_logs(tmp_path):
    """D unlock 落账 + 豁免消费落账。"""
    ws = _mk_ws(tmp_path)
    legacy = _legacy_fact()
    (ws / "facts" / "F001-legacy.md").write_text(legacy, encoding="utf-8")
    p = _payload(ws, "Write", ws / "facts" / "F001-legacy.md", content=legacy)
    r = _run_guard(ws, p)
    assert r.returncode == 2, "pre-unlock rewrite must block"

    sys.path.insert(0, str(SCRIPTS))
    import write_guard_unlock as wgu
    rc = wgu.main(["unlock", str(ws), "--file", "F001-legacy.md",
                   "--reason", "legacy schema migration in progress"])
    assert rc == 0
    actions = [row.get("action") for row in _ledger_rows(ws)]
    assert "write_guard_unlock" in actions, actions

    r2 = _run_guard(ws, p)
    assert r2.returncode == 0, "waived rewrite must pass: " + r2.stderr[:300]
    actions2 = [row.get("action") for row in _ledger_rows(ws)]
    assert "write_guard_waiver_used" in actions2, actions2


def test_quarantine_moves_and_logs(tmp_path):
    """E quarantine 移出 lint 语料并落账。"""
    ws = _mk_ws(tmp_path)
    (ws / "facts" / "F001-legacy.md").write_text(_legacy_fact(), encoding="utf-8")
    sys.path.insert(0, str(SCRIPTS))
    import write_guard_unlock as wgu
    rc = wgu.main(["quarantine", str(ws), "--file", "F001-legacy.md",
                   "--reason", "legacy garbage beyond repair"])
    assert rc == 0
    assert not (ws / "facts" / "F001-legacy.md").exists()
    assert (ws / "facts" / "_quarantine" / "F001-legacy.md").exists()
    actions = [row.get("action") for row in _ledger_rows(ws)]
    assert "write_guard_quarantine" in actions, actions
    p = _payload(ws, "Write", ws / "facts" / "F007-clean.md", content=GOOD_FACT)
    r = _run_guard(ws, p)
    assert r.returncode == 0, r.stderr[:300]


def test_unlock_missing_file_rejected(tmp_path):
    """F 不存在的文件 → rc=2。"""
    ws = _mk_ws(tmp_path)
    sys.path.insert(0, str(SCRIPTS))
    import write_guard_unlock as wgu
    assert wgu.main(["unlock", str(ws), "--file", "F999-nope.md",
                     "--reason", "x"]) == 2
    assert wgu.main(["quarantine", str(ws), "--file", "F999-nope.md",
                     "--reason", "x"]) == 2
