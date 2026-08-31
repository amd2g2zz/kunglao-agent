# -*- coding: utf-8 -*-
"""tests/test_bash_fact_guard_809.py - #809 Bash-channel governance hook."""
import importlib.util
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    name = "bash_fact_guard_809_test"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, ROOT / "hooks" / "bash_fact_guard.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _mk_ws(tmp_path):
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir()
    return ws


def _payload(ws, cmd):
    return {"cwd": str(ws), "tool_name": "Bash", "tool_input": {"command": cmd}}


OLD_FACT = ("---\nid: F001\nclaim: crash in worker\n"
            "status: PARTIALLY-VERIFIED\n---\nbody text only.\n")


def test_violation_recorded_and_surfaced(tmp_path, capsys):
    import datetime as dt
    mod = _load()
    ws = _mk_ws(tmp_path)
    (ws / "facts" / "F001.md").write_text(OLD_FACT, encoding="utf-8")
    cmd = "cat > facts/F001.md <<'EOF'\nbody text only.\nEOF"
    out = mod.evaluate(_payload(ws, cmd))
    assert out is not None and out["targets"], out
    rc = mod.main(stdin_stream=io.StringIO(json.dumps(_payload(ws, cmd))))
    assert rc == 0
    err = capsys.readouterr().out
    assert "F001.md" in err and "additionalContext" in err
    logs = ws / "runs" / "logs"
    assert logs.is_dir(), "ledger dir must be created by emit"
    rows = []
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    assert any(r.get("action") == "write_blocked"
               and r.get("actor") == "bash_fact_guard" for r in rows), rows[-3:]


def test_non_facts_command_silent(tmp_path, capsys):
    mod = _load()
    ws = _mk_ws(tmp_path)
    assert mod.evaluate(_payload(ws, "ls -la && echo hi")) is None
    rc = mod.main(stdin_stream=io.StringIO(json.dumps(_payload(ws, "ls -la"))))
    assert rc == 0 and capsys.readouterr().out == ""


def test_target_not_existing_silent(tmp_path):
    mod = _load()
    ws = _mk_ws(tmp_path)
    assert mod.evaluate(_payload(ws, "echo x > facts/F999.md")) is None


def test_broken_payload_fail_open(tmp_path):
    mod = _load()
    ws = _mk_ws(tmp_path)
    assert mod.main(stdin_stream=io.StringIO("{ not json")) == 0
