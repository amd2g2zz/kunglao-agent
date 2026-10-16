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


# --------------------------------------------------------------------------
# lint convergence: scope (_INDEX.md), severity (warning != violation),
# structured detail (all rules), cap-and-escalate (repeat-block ladder).
# --------------------------------------------------------------------------

_SHA = "b" * 64


def _valid_fact_text(with_verify_status: bool) -> str:
    """A schema-legal fact (lint_fact returns [] or warning-only)."""
    fm = [
        ("id", "F001-x"), ("type", "fact"), ("title", "F001-x title"),
        ("status", "INFERRED"), ("created", "2026-10-01"),
        ("last_reviewed", "2026-10-01"), ("claim_id", "C-001"),
        ("claim", "imports resolved at runtime"),
        ("boundary_type", "observation"),
        ("promotion_gate", "resolve the loader stub under dynamic-trace"),
        ("source", "static-decompile"), ("confidence", "medium"),
    ]
    if with_verify_status:
        fm.append(("verify_status", "partial"))
    fm += [("reproduce", "python runs/verify.py"), ("expected", _SHA),
           ("verified", "pending")]
    lines = []
    for k, v in fm:
        lines.append(f"{k}: {v}")
    lines += [
        "provenance:",
        f"  - {{role: decompiled_c, path: evidence/x.c, "
        f"content_sha256: {_SHA}, credibility: B2}}",
    ]
    return "---\n" + "\n".join(lines) + "\n---\n\n## Status\nINFERRED\n"


CLEAN_FACT = _valid_fact_text(True)
WARN_ONLY_FACT = _valid_fact_text(False)

INDEX_ROWS_OK = (
    "| fact | status | claim | conclusion |\n"
    "|---|---|---|---|\n"
    "| F001-x | INFERRED | C-001 | imports resolved at runtime |\n")
INDEX_ROWS_DRIFTED = (
    "| fact | status | claim |\n"
    "| F001-x | INFERRED | C-001 |\n")


def _ledger_rows(ws):
    rows = []
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return rows
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _actions(ws, *names):
    return [r for r in _ledger_rows(ws) if r.get("action") in names]


def _write_cmd(rel, text):
    return f"cat > {rel} <<'EOF'\n{text}EOF"


def test_index_row_table_write_is_silent(tmp_path, capsys):
    """A 4-column row-table _INDEX.md write is silent: no blocked emit, no
    output. The index contract is the row table, not the fact schema."""
    mod = _load()
    ws = _mk_ws(tmp_path)
    (ws / "facts" / "_INDEX.md").write_text(INDEX_ROWS_OK, encoding="utf-8")
    cmd = _write_cmd("facts/_INDEX.md", INDEX_ROWS_OK)
    out = mod.evaluate(_payload(ws, cmd))
    assert out is not None and out["targets"] == [], out
    rc = mod.main(stdin_stream=io.StringIO(json.dumps(_payload(ws, cmd))))
    assert rc == 0 and capsys.readouterr().out == ""
    assert _actions(ws, "write_blocked", "write_escalated") == []


def test_index_drifted_row_still_blocks(tmp_path, capsys):
    """A drifted _INDEX.md row (3 columns) is an error-class row finding and
    still blocks — with the structured row detail, not the fact schema."""
    mod = _load()
    ws = _mk_ws(tmp_path)
    (ws / "facts" / "_INDEX.md").write_text(INDEX_ROWS_DRIFTED,
                                            encoding="utf-8")
    cmd = _write_cmd("facts/_INDEX.md", INDEX_ROWS_DRIFTED)
    rc = mod.main(stdin_stream=io.StringIO(json.dumps(_payload(ws, cmd))))
    assert rc == 0
    out = capsys.readouterr().out
    assert "additionalContext" in out and "BAD_INDEX_SHAPE" in out
    assert _actions(ws, "write_blocked"), "drifted index row must be recorded"


def test_warning_only_fact_write_is_not_violation(tmp_path, capsys):
    """A warning-only fact write is never framed as a violation and never
    emitted as blocked: at most one soft informational note."""
    mod = _load()
    ws = _mk_ws(tmp_path)
    (ws / "facts" / "F001-x.md").write_text(WARN_ONLY_FACT, encoding="utf-8")
    cmd = _write_cmd("facts/F001-x.md", WARN_ONLY_FACT)
    out = mod.evaluate(_payload(ws, cmd))
    assert out is not None and out["targets"], out
    assert all(not t["errors"] for t in out["targets"]), out
    rc = mod.main(stdin_stream=io.StringIO(json.dumps(_payload(ws, cmd))))
    assert rc == 0
    printed = capsys.readouterr().out
    assert "violated" not in printed.lower()
    assert _actions(ws, "write_blocked", "write_escalated") == []


def test_error_findings_block_with_structured_detail(tmp_path, capsys):
    """Error-class findings block with structured detail naming EVERY rule
    (no two-rule cap) plus the schema doc pointer."""
    mod = _load()
    ws = _mk_ws(tmp_path)
    (ws / "facts" / "F001.md").write_text(OLD_FACT, encoding="utf-8")
    cmd = _write_cmd("facts/F001.md", OLD_FACT)
    rc = mod.main(stdin_stream=io.StringIO(json.dumps(_payload(ws, cmd))))
    assert rc == 0
    out = capsys.readouterr().out
    for rule in ("BAD_TYPE", "MISSING_TITLE", "MISSING_PROVENANCE",
                 "BAD_STATUS", "MISSING_EXTENSION_FIELD"):
        assert rule in out, f"{rule} missing from detail: {out}"
    assert "references/schemas/schema.md" in out
    assert _actions(ws, "write_blocked")


def test_repeat_blocks_escalate_then_reset(tmp_path, capsys):
    """Cap-and-escalate ladder: the first block of a streak records
    write_blocked; repeats stay ledger-silent; the escalation event fires at
    the disable threshold; a clean pass resets the ladder."""
    mod = _load()
    ws = _mk_ws(tmp_path)
    state_path = ws / "runs" / "write-blocks.json"
    bad = _payload(ws, _write_cmd("facts/F001.md", OLD_FACT))
    good = _payload(ws, _write_cmd("facts/F001.md", CLEAN_FACT))
    (ws / "facts" / "F001.md").write_text(OLD_FACT, encoding="utf-8")

    for i in range(4):
        assert mod.main(
            stdin_stream=io.StringIO(json.dumps(bad))) == 0, i
        capsys.readouterr()
        assert _actions(ws, "write_escalated") == [], f"early escalate at {i + 1}"
    assert len(_actions(ws, "write_blocked")) == 1, "streak must be deduped"
    assert state_path.is_file()
    assert any(int(n) >= 3 for rec in json.loads(
        state_path.read_text(encoding="utf-8")).values()
        for n in rec.values())

    # 5th consecutive block crosses the threshold exactly once
    (ws / "facts" / "F001.md").write_text(OLD_FACT, encoding="utf-8")
    assert mod.main(stdin_stream=io.StringIO(json.dumps(bad))) == 0
    capsys.readouterr()
    esc = _actions(ws, "write_escalated")
    assert len(esc) == 1
    assert "F001.md" in esc[0].get("detail", "")
    assert "5" in esc[0].get("detail", "")

    # blocks 6-7 stay ledger-silent (escalation fired once at crossing)
    for _ in range(2):
        assert mod.main(stdin_stream=io.StringIO(json.dumps(bad))) == 0
        capsys.readouterr()
    assert len(_actions(ws, "write_escalated")) == 1

    # a clean pass resets the ladder
    (ws / "facts" / "F001.md").write_text(CLEAN_FACT, encoding="utf-8")
    assert mod.main(stdin_stream=io.StringIO(json.dumps(good))) == 0
    assert capsys.readouterr().out == ""
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "F001.md" not in state, state

    # a fresh streak needs the full run-up again
    (ws / "facts" / "F001.md").write_text(OLD_FACT, encoding="utf-8")
    for _ in range(4):
        assert mod.main(stdin_stream=io.StringIO(json.dumps(bad))) == 0
        capsys.readouterr()
    assert len(_actions(ws, "write_escalated")) == 1
    assert mod.main(stdin_stream=io.StringIO(json.dumps(bad))) == 0
    capsys.readouterr()
    assert len(_actions(ws, "write_escalated")) == 2
