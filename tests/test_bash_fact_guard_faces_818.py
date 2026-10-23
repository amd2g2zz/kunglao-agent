# -*- coding: utf-8 -*-
"""tests/test_bash_fact_guard_faces_818.py — the PostToolUse/Bash facts
write recorder (#809) on REAL fixture workspaces.

Issue #818 coverage climb (counts double: Wave-0/0.5 tooth). The hook
adjudicates the Bash-channel facts writes that write_guard's
PreToolUse/Edit|Write matcher cannot see. Real files, real lint, real
ledger rows — no mocks:

  - the command's facts/ targets lint with THEIR OWN contract (fact
    schema for F*.md, the 4-column row ruler for _INDEX.md);
  - only error-class findings block-record; warning-class rides as one
    soft note;
  - the per-(file, rule) repeat ladder: first violation lands the
    write_blocked ledger row, the warn rung (3) fires the canonical
    repeat warn, the disable rung (5) lands write_escalated exactly at
    the crossing, and a clean write resets the file's ladder;
  - fail-open everywhere: a broken payload or a crashing lint never
    breaks Bash (exit 0, silence).
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import bash_fact_guard as bfg  # noqa: E402  (hooks/ on pytest path)
from _factories import write_certified_fact  # noqa: E402

BAD_ROW = "F001 | not-a-real-status | C-001 | conclusion text"


def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    return ws


def _payload(ws: Path, command: str) -> dict:
    return {"cwd": str(ws), "tool_input": {"command": command}}


def _certified_fact(ws: Path, fid: str = "F001") -> Path:
    """A grammar-clean fact: the certified factory shape plus an explicit
    verify_status (the factory shape alone carries one warning-class
    finding — VERIFY_STATUS_ABSENT — which this fixture also removes so
    the CLEAN ladder faces have a truly clean file)."""
    p = write_certified_fact(ws, fid, "C-001")
    text = p.read_text(encoding="utf-8")
    p.write_text(text.replace(
        "status: INFERRED\n", "status: INFERRED\nverify_status: pending\n"),
        encoding="utf-8")
    return p


def _violating_fact(ws: Path, fid: str = "F099") -> Path:
    p = ws / "facts" / f"{fid}.md"
    p.write_text("---\nid: F099\ntype: note\n---\nwrong carrier type\n",
                 encoding="utf-8")
    return p


# ---------- resolve_ws ----------

def test_resolve_ws_prefers_the_nested_workspace(tmp_path) -> None:
    nested = tmp_path / "malware-analysis-workspace"
    (nested / "runs").mkdir(parents=True)
    assert bfg.resolve_ws(_payload(tmp_path, "x")) == nested
    flat = tmp_path / "flat"
    (flat / "runs").mkdir(parents=True)
    assert bfg.resolve_ws(_payload(flat, "x")) == flat
    assert bfg.resolve_ws(_payload(tmp_path / "nowhere", "x")) is None


# ---------- light_detail ----------

def test_light_detail_appends_only_for_mapped_and_real_docs() -> None:
    detail = "contract breach"
    lit = bfg.light_detail("facts_write_contract_lint", detail)
    assert lit != detail                       # schema.md exists in-repo
    assert "references/schemas/schema.md" in lit
    assert bfg.light_detail("unmapped_pattern", detail) == detail


# ---------- evaluate ----------

def test_evaluate_ignores_non_facts_commands(tmp_path) -> None:
    ws = _ws(tmp_path)
    _violating_fact(ws)
    cmd = "cat notes/other.md > /dev/null"
    assert bfg.evaluate(_payload(ws, cmd)) is None


def test_evaluate_no_workspace_returns_none(tmp_path) -> None:
    assert bfg.evaluate(_payload(tmp_path, "echo facts/F001.md")) is None


def test_evaluate_missing_target_file_is_skipped(tmp_path) -> None:
    ws = _ws(tmp_path)
    # the command NAMES the target but the file never landed
    assert bfg.evaluate(_payload(ws, "cat > facts/F001.md <<'EOF'\nx\nEOF"
                        )) is None


def test_evaluate_rejects_unsafe_relative_targets(tmp_path) -> None:
    ws = _ws(tmp_path)
    (ws / "facts" / "..").resolve()
    cmd = "cat > facts/..%2Fescape.md"
    # regex only captures [A-Za-z0-9._-]+\.md — path separators never match
    assert bfg.evaluate(_payload(ws, cmd)) is None


def test_evaluate_clean_fact_is_reported_clean(tmp_path) -> None:
    ws = _ws(tmp_path)
    _certified_fact(ws)
    res = bfg.evaluate(_payload(ws, "cat > facts/F001.md <<'EOF'\nbody\nEOF"))
    assert res is not None
    assert res["clean"] == ["F001.md"]
    assert res["targets"] == []
    assert res["ws"] == ws


def test_evaluate_violating_fact_yields_error_findings(tmp_path) -> None:
    ws = _ws(tmp_path)
    _violating_fact(ws)
    res = bfg.evaluate(_payload(ws, "tee facts/F099.md <<< x"))
    assert res is not None
    assert res["clean"] == []
    (target,) = res["targets"]
    assert target["file"] == "F099.md"
    codes = {code for code, _msg in target["errors"]}
    assert "BAD_TYPE" in codes
    # the warning-class finding rides the separate soft channel
    assert [code for code, _m in target["warnings"]] == \
        ["VERIFY_STATUS_ABSENT"]


def test_evaluate_index_uses_the_row_ruler(tmp_path) -> None:
    ws = _ws(tmp_path)
    (ws / "facts" / "_INDEX.md").write_text(
        "| fact | status | claim | conclusion |\n"
        "|---|---|---|---|\n"
        f"{BAD_ROW}\n", encoding="utf-8")
    res = bfg.evaluate(_payload(ws, "cat > facts/_INDEX.md <<'EOF'\nx\nEOF"))
    assert res is not None
    (target,) = res["targets"]
    codes = {code for code, _msg in target["errors"]}
    assert "BAD_INDEX_STATUS" in codes


def test_evaluate_duplicate_targets_dedupe(tmp_path) -> None:
    ws = _ws(tmp_path)
    _certified_fact(ws)
    res = bfg.evaluate(_payload(
        ws, "cat facts/F001.md && cp facts/F001.md facts/F001.md"))
    assert res is not None
    assert res["clean"] == ["F001.md"]


# ---------- the repeat ladder ----------

def _blocked_result(ws: Path) -> dict:
    _violating_fact(ws)
    res = bfg.evaluate(_payload(ws, "tee facts/F099.md <<< x"))
    assert res is not None and res["targets"]
    return res


def test_ladder_first_block_then_warn_then_escalation(tmp_path) -> None:
    ws = _ws(tmp_path)
    for streak in range(1, 7):
        res = _blocked_result(ws)
        ladder = bfg._apply_repeat_ladder(ws, res)
        if streak == 1:
            assert [t["file"] for t in ladder["first"]] == ["F099.md"]
        else:
            assert ladder["first"] == []
        warned = [rules for _f, rules in ladder["warned"]]
        escalated = ladder["escalated"]
        if streak == bfg._WARN_AT:
            assert warned == [["BAD_TYPE"] + []] or warned
            assert any("BAD_TYPE" in rules for rules in warned)
        else:
            assert not any("BAD_TYPE" in rules for rules in warned)
        if streak == bfg._ESCALATE_AT:
            (rel, rules, n), = escalated
            assert rel == "F099.md" and n == bfg._ESCALATE_AT
        else:
            assert escalated == []
    state = json.loads(
        (ws / "runs" / bfg.BLOCK_STATE_NAME).read_text(encoding="utf-8"))
    assert state["F099.md"]["BAD_TYPE"] == 6


def test_ladder_clean_write_resets_the_file_ladder(tmp_path) -> None:
    ws = _ws(tmp_path)
    res = _blocked_result(ws)
    bfg._apply_repeat_ladder(ws, res)
    res2 = _blocked_result(ws)
    bfg._apply_repeat_ladder(ws, res2)
    _certified_fact(ws, "F099")
    clean = bfg.evaluate(_payload(ws, "tee facts/F099.md <<< x"))
    assert clean is not None and clean["clean"] == ["F099.md"]
    ladder = bfg._apply_repeat_ladder(ws, clean)
    assert ladder == {"first": [], "warned": [], "escalated": []}
    state = json.loads(
        (ws / "runs" / bfg.BLOCK_STATE_NAME).read_text(encoding="utf-8"))
    assert "F099.md" not in state


def test_ladder_warn_only_target_never_advances(tmp_path) -> None:
    ws = _ws(tmp_path)
    # a warnings-only target: certified fact (clean shape) is not it; use
    # an index row with a merely-drifted status spelling that lints as a
    # WARNING-class finding — none exists, so a target with only warnings
    # is synthesized directly
    res = {"targets": [{"file": "F099.md", "errors": [],
                        "warnings": [("SOME_WARN", "soft")]}],
           "clean": [], "ws": ws}
    ladder = bfg._apply_repeat_ladder(ws, res)
    assert ladder == {"first": [], "warned": [], "escalated": []}


# ---------- _surface: ledger + additionalContext ----------

def _read_events(ws: Path) -> list:
    logs = ws / "runs" / "logs"
    if not logs.is_dir():
        return []
    rows = []
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        rows.extend(json.loads(ln) for ln in
                    p.read_text(encoding="utf-8").splitlines() if ln.strip())
    return rows


def test_surface_first_block_lands_write_blocked_row_and_context(
        tmp_path, capsys) -> None:
    ws = _ws(tmp_path)
    res = _blocked_result(ws)
    ladder = bfg._apply_repeat_ladder(ws, res)
    bfg._surface(ws, res, ladder)
    payload = json.loads(capsys.readouterr().out)
    assert "Bash-channel facts write blocked by contract lint" in \
        payload["additionalContext"]
    assert "this pattern is documented" in payload["additionalContext"]
    actions = [r.get("action") for r in _read_events(ws)]
    assert "write_blocked" in actions


def test_surface_beyond_first_block_no_new_ledger_row(
        tmp_path, capsys) -> None:
    ws = _ws(tmp_path)
    res = _blocked_result(ws)
    bfg._surface(ws, res, bfg._apply_repeat_ladder(ws, res))
    capsys.readouterr()
    res2 = _blocked_result(ws)
    bfg._surface(ws, res2, bfg._apply_repeat_ladder(ws, res2))
    assert json.loads(capsys.readouterr().out)["additionalContext"]
    actions = [r.get("action") for r in _read_events(ws)]
    assert actions.count("write_blocked") == 1


def test_surface_escalation_lands_write_escalated_row(
        tmp_path, capsys) -> None:
    ws = _ws(tmp_path)
    for _ in range(bfg._ESCALATE_AT - 1):
        bfg._surface(ws, _blocked_result(ws),
                     bfg._apply_repeat_ladder(ws, _blocked_result(ws)))
    capsys.readouterr()
    res = _blocked_result(ws)
    bfg._surface(ws, res, bfg._apply_repeat_ladder(ws, res))
    actions = [r.get("action") for r in _read_events(ws)]
    assert "write_escalated" in actions
    out = capsys.readouterr().out
    assert "repeat-block ladder crossed" in out


def test_surface_warn_only_note_never_uses_violation_framing(
        tmp_path, capsys) -> None:
    ws = _ws(tmp_path)
    res = {"targets": [{"file": "F099.md", "errors": [],
                        "warnings": [("W1", "m1"), ("W2", "m2")]}],
           "clean": [], "ws": ws}
    bfg._surface(ws, res, {"first": [], "warned": [], "escalated": []})
    payload = json.loads(capsys.readouterr().out)
    assert "informational" in payload["additionalContext"]
    assert "not contract violations" in payload["additionalContext"]
    assert _read_events(ws) == []


def test_surface_clean_result_is_silent(tmp_path, capsys) -> None:
    ws = _ws(tmp_path)
    res = {"targets": [], "clean": ["F001.md"], "ws": ws}
    bfg._surface(ws, res, {"first": [], "warned": [], "escalated": []})
    assert capsys.readouterr().out == ""


# ---------- main: the fail-open entry ----------

def _run_main(payload_text: str) -> int:
    return bfg.main(io.StringIO(payload_text))


def test_main_broken_json_fails_open(tmp_path) -> None:
    assert _run_main("{not json") == 0


def test_main_empty_command_is_silent(tmp_path) -> None:
    ws = _ws(tmp_path)
    assert _run_main(json.dumps({"cwd": str(ws),
                                 "tool_input": {"command": ""}})) == 0


def test_main_blocked_flow_emits_context_and_exit_zero(tmp_path, capsys,
                                                       monkeypatch) -> None:
    # keep the process-wide canonical warn dedupe from leaking state
    monkeypatch.setattr("kunglao_log._WARN_LAST", {}, raising=False)
    ws = _ws(tmp_path)
    _violating_fact(ws)
    rc = _run_main(json.dumps(_payload(ws, "tee facts/F099.md <<< x")))
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert "blocked by contract lint" in payload["additionalContext"]
