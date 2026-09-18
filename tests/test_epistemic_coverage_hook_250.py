# -*- coding: utf-8 -*-
"""Issue 250 — settle-time epistemic coverage annotation (piece 4 wiring).

hooks/completion_gate.py's PASS path annotates (never blocks) whether the
settling workspace's fact assumptions resolve to terminal epistemic
claims. The R4 anti-Goodhart property under test: the annotation MUST NOT
change the exit code — an unresolved presupposition is recorded to the
event log while the session still ends.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
from pathlib import Path

import yaml

_HERE = Path(__file__).parent
HOOKS = _HERE.parent / "hooks"
sys.path.insert(0, str(_HERE))

from _factories import write_hook_state  # noqa: E402


def _load_hook_module():
    name = "completion_gate_hook_250"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, HOOKS / "completion_gate.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _activated(ws: Path) -> None:
    write_hook_state(ws, active_hooks=["completion_gate"],
                     ts="2026-08-11T12:00:00Z", tier="none", phase="IDLE",
                     user_override={}, expires_minutes=30)


def _write_fact(ws: Path, fid: str, claim_id: str,
                assumptions: list) -> None:
    d = ws / "facts"
    d.mkdir(parents=True, exist_ok=True)
    fm = yaml.safe_dump({
        "id": fid, "type": "fact", "title": "scoped observation",
        "status": "PROVEN", "created": "2026-09-18",
        "last_reviewed": "2026-09-18", "claim_id": claim_id,
        "assumptions": assumptions,
    }, sort_keys=False)
    (d / f"{fid}.md").write_text(f"---\n{fm}---\n\nbody\n", encoding="utf-8")


def _register(ws: Path, claims: list[dict]) -> None:
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": claims}, sort_keys=False),
        encoding="utf-8")


def _events(ws: Path) -> list[dict]:
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return []
    rows: list[dict] = []
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(ln))
            except ValueError:
                continue
    return rows


def _run(ws: Path) -> tuple[int, str]:
    mod = _load_hook_module()
    payload = {"hook_event_name": "Stop", "session_id": "t250",
               "cwd": str(ws), "stop_hook_active": False}
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = mod.main(io.StringIO(json.dumps(payload)))
    return rc, buf.getvalue()


def _pass_ws(tmp_path: Path, epistemic_status: str) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    _activated(ws)
    (ws / "task-oracle.yaml").write_text(
        "task_text: settle the dispatch question\n"
        "open_items: []\ndeferrals: []\n", encoding="utf-8")
    _register(ws, [
        {"id": "C-101", "status": "PROVEN"},
        {"id": "C-110", "status": epistemic_status,
         "boundary_type": "epistemic",
         "answers_question": "q_dispatch_mode"},
    ])
    _write_fact(ws, "F001-xref", "C-101", ["q_dispatch_mode=static"])
    return ws


def test_uncovered_presupposition_annotates_but_does_not_block(tmp_path):
    ws = _pass_ws(tmp_path, "OPEN")
    rc, out = _run(ws)
    assert rc == 0, "coverage annotation must NEVER block settlement (R4)"
    assert out.strip() == "", "PASS stays a silent pass-through"
    actions = [e.get("action") for e in _events(ws)]
    assert "epistemic_coverage" in actions
    ev = next(e for e in _events(ws) if e.get("action") == "epistemic_coverage")
    assert "q_dispatch_mode" in str(ev.get("detail"))
    assert "C-101" in str(ev.get("detail"))


def test_covered_presupposition_is_silent(tmp_path):
    ws = _pass_ws(tmp_path, "REFUTED")  # terminal = addressed (dead-ends count)
    rc, out = _run(ws)
    assert rc == 0
    assert "epistemic_coverage" not in [e.get("action") for e in _events(ws)]


def test_no_facts_no_annotation(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    _activated(ws)
    (ws / "task-oracle.yaml").write_text(
        "task_text: plain settle\nopen_items: []\ndeferrals: []\n",
        encoding="utf-8")
    _register(ws, [{"id": "C-101", "status": "PROVEN"}])
    rc, out = _run(ws)
    assert rc == 0
    assert "epistemic_coverage" not in [e.get("action") for e in _events(ws)]
