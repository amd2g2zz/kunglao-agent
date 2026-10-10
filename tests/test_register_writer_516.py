#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_register_writer_516.py — register single-writer enforcement (#516).

Field evidence (combat re-run wt1, dev@46b6a9d0, zero-intervention): a
worker hand-wrote claim-register.yaml and landed YAML that does not parse
(ScannerError 'mapping values are not allowed here' line 44 — evidence
prose carrying `): `), killing the run at convergence for the FOURTH time
in the accident class. Postmortem surfaces three enforcement holes:

  A  Write/Edit face — the proven-gate reader treats an unparseable new
     text as {} ("no transitions") and ALLOWS the corruption through.
  B  Bash face — `cat > claim-register.yaml <<EOF` / python open(...,'w')
     / sed -i never see write_guard at all (matcher is Edit|Write only);
     the field ledger shows workers habitually write files via Bash.
  C  Form — even a VALID hand-typed register diff is instruction-violating
     (#482 prompt says safe_dump, never hand-edit): nothing mechanical
     refuses it.

This file pins the #516 contract: claim-register.yaml is single-writer —
the sanctioned mutator is scripts/ws_yaml.py (canonical safe_dump), the
runner writes on disk through its own process (never a tool call), and
every other tool-face write is refused. Subprocess-driven like the #819
suite (no mocks); helper imports mirror test_canonical_chain_752.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import wire_up_settings  # noqa: E402

WRITE_GUARD = ROOT / "hooks" / "write_guard.py"
WS_YAML = SCRIPTS / "ws_yaml.py"

RC_ALLOW, RC_BLOCK = 0, 2

# The wt1 corruption, verbatim shape: evidence prose with `): ` inside an
# unquoted scalar -> ScannerError mapping-values (accident class instance 4).
CORRUPT = (
    "claims:\n"
    "  - id: C-004\n"
    "    status: PARTIALLY-VERIFIED\n"
    "    evidence: F005 = battery (scratch/run.py -> evidence/x.json): "
    "4/4 ok\n"
)

# Valid YAML, hand-typed flow style — parses clean, renders nothing like a
# canonical safe_dump (block style) — the C-hole fixture.
HANDTYPED_VALID = (
    "claims: [{id: C-001, status: OPEN, statement: 'flow style hand typed'}]\n"
)

# The on-disk baseline: built through the sanctioned writer's own kwargs so
# the canonical allowed-write fixture is a true no-transition rewrite.
GOOD_DOC = {
    "claims": [
        {"id": "C-001", "status": "OPEN",
         "statement": "synthetic claim for writer tests"},
        {"id": "C-002", "status": "PARTIALLY-VERIFIED",
         "wake_condition": "wait for the red-team artifact"},
    ],
}

# Prose that killed three runs before this fix: colons + parens inside the
# value. ws_yaml must land it QUOTED (safe_dump decides), never raw.
WAKE_WITH_COLONS = (
    "red-team artifact (runs/verify-redteam-C-002.md): pending — "
    "resume when CONFIRMED lands")


def _seed_doc(ws: Path) -> Path:
    """Seed the register through the sanctioned writer's own rendering."""
    from ws_yaml import canonical_dump  # noqa: PLC0415
    reg = ws / "claim-register.yaml"
    reg.write_text(canonical_dump(GOOD_DOC), encoding="utf-8")
    return reg


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "notes").mkdir(parents=True)
    (ws / "runs").mkdir(parents=True)
    (ws / "analysis_state.txt").write_text(
        "kunglao workspace\n", encoding="utf-8")
    return ws


def _payload(tool: str, cwd: Path, **tool_input) -> str:
    return json.dumps({
        "tool_name": tool,
        "cwd": str(cwd),
        "tool_input": tool_input,
    }, ensure_ascii=False)


def _write_payload(cwd: Path, file_path: Path, content: str) -> str:
    return _payload("Write", cwd, file_path=str(file_path), content=content)


def _bash_payload(cwd: Path, command: str) -> str:
    return _payload("Bash", cwd, command=command)


def _run_guard(payload: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items()}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT), str(ROOT / "hooks"), str(SCRIPTS)])
    return subprocess.run(
        [sys.executable, str(WRITE_GUARD)],
        input=payload, capture_output=True, text=True, timeout=60,
        env=env, errors="replace")


def _ws_yaml(ws: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(WS_YAML), *args],
        capture_output=True, text=True, timeout=30,
        cwd=str(ws), env={**os.environ, "PYTHONIOENCODING": "utf-8"})


# --------------------------------------------------------------------------
# Hole A — the Write/Edit face must refuse an unparseable post-image
# --------------------------------------------------------------------------

def test_write_invalid_register_refused(tmp_path):
    ws = _mk_ws(tmp_path)
    reg = _seed_doc(ws)
    before = reg.read_text(encoding="utf-8")
    r = _run_guard(_write_payload(ws, reg, CORRUPT))
    assert r.returncode == RC_BLOCK, r.stderr
    assert "claim-register.yaml" in r.stderr
    # original intact — the refused write never landed
    assert reg.read_text(encoding="utf-8") == before


def test_proven_gate_unparseable_fail_closed(tmp_path):
    from register_proven_gate import check_register_transitions  # noqa: E402

    ws = _mk_ws(tmp_path)
    res = check_register_transitions(ws, CORRUPT, None)
    assert not res.get("ok")
    assert any("parse" in str(v).lower() for v in res["violations"]), res


# --------------------------------------------------------------------------
# Hole C — a valid but hand-typed post-image is not the sanctioned form
# --------------------------------------------------------------------------

def test_write_valid_but_handtyped_refused(tmp_path):
    ws = _mk_ws(tmp_path)
    reg = _seed_doc(ws)
    r = _run_guard(_write_payload(ws, reg, HANDTYPED_VALID))
    assert r.returncode == RC_BLOCK, r.stderr


def test_write_canonical_roundtrip_allowed(tmp_path):
    ws = _mk_ws(tmp_path)
    reg = _seed_doc(ws)
    # canonical no-transition rewrite of the very same doc must pass
    r = _run_guard(_write_payload(ws, reg, reg.read_text(encoding="utf-8")))
    assert r.returncode == RC_ALLOW, r.stderr


# --------------------------------------------------------------------------
# Hole B — the Bash face: register write-intent is refused, reads are not
# --------------------------------------------------------------------------

def test_bash_heredoc_write_blocked(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_doc(ws)
    r = _run_guard(_bash_payload(
        ws, "cat > claim-register.yaml <<EOF\nclaims: []\nEOF"))
    assert r.returncode == RC_BLOCK, r.stderr
    assert "ws_yaml" in r.stderr  # the repair path rides the block reason


def test_bash_redirect_append_blocked(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_doc(ws)
    r = _run_guard(_bash_payload(
        ws, "echo 'claims: []' >> claim-register.yaml"))
    assert r.returncode == RC_BLOCK, r.stderr


def test_bash_python_open_w_blocked(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_doc(ws)
    r = _run_guard(_bash_payload(
        ws, "python3 -c \"open('claim-register.yaml','w')"
        ".write('claims: []')\""))
    assert r.returncode == RC_BLOCK, r.stderr


def test_bash_sed_i_blocked(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_doc(ws)
    r = _run_guard(_bash_payload(
        ws, "sed -i 's/OPEN/PROVEN/' claim-register.yaml"))
    assert r.returncode == RC_BLOCK, r.stderr


def test_bash_readonly_allowed(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_doc(ws)
    for cmd in ("grep -n status claim-register.yaml",
                "cat claim-register.yaml",
                "python3 scripts/ws_yaml.py get claim-register.yaml "
                "claims.0.status"):
        r = _run_guard(_bash_payload(ws, cmd))
        assert r.returncode == RC_ALLOW, (cmd, r.stderr)


def test_bash_ws_yaml_set_allowed(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_doc(ws)
    r = _run_guard(_bash_payload(
        ws, f"python3 {WS_YAML} set claim-register.yaml "
        f"claims.0.status PARTIALLY-VERIFIED"))
    assert r.returncode == RC_ALLOW, r.stderr


# --------------------------------------------------------------------------
# The sanctioned helper path (issue AC2: status flips, wake updates)
# --------------------------------------------------------------------------

def test_helper_status_flip(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_doc(ws)
    r = _ws_yaml(ws, "set", "claim-register.yaml",
                 "claims.0.status", "PARTIALLY-VERIFIED")
    assert r.returncode == 0, r.stderr
    import yaml  # noqa: PLC0415

    doc = yaml.safe_load((ws / "claim-register.yaml").read_text(
        encoding="utf-8"))
    assert doc["claims"][0]["status"] == "PARTIALLY-VERIFIED"


def test_helper_wake_update_with_colons(tmp_path):
    """The four-instance killer: prose with `): ` must land QUOTED."""
    ws = _mk_ws(tmp_path)
    _seed_doc(ws)
    r = _ws_yaml(ws, "set", "claim-register.yaml",
                 "claims.1.wake_condition", WAKE_WITH_COLONS)
    assert r.returncode == 0, r.stderr
    import yaml  # noqa: PLC0415

    text = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    doc = yaml.safe_load(text)  # parses — safe_dump quoted the prose
    assert doc["claims"][1]["wake_condition"] == WAKE_WITH_COLONS


def test_helper_output_is_canonical(tmp_path):
    """ws_yaml's on-disk bytes ARE the canonical form write_guard accepts —
    canonical safe_dump plus the re-emitted comment stamp (the stamp rides
    the comment header, so the YAML body stays the canonical rendering)."""
    from ws_yaml import canonical_dump  # noqa: PLC0415

    ws = _mk_ws(tmp_path)
    _seed_doc(ws)
    _ws_yaml(ws, "set", "claim-register.yaml",
             "claims.1.wake_condition", WAKE_WITH_COLONS)
    text = (ws / "claim-register.yaml").read_text(encoding="utf-8")
    import yaml  # noqa: PLC0415

    doc = yaml.safe_load(text)
    tail = canonical_dump(doc)
    assert text.endswith(tail)
    head = text[:len(text) - len(tail)]
    assert all(ln.startswith("#") for ln in head.splitlines()), head


# --------------------------------------------------------------------------
# The append face — list-valued fields grow one sanctioned item at a time
# --------------------------------------------------------------------------

def _seed_list_doc(ws: Path) -> Path:
    """A register whose list-valued field exists and is empty."""
    from ws_yaml import canonical_dump  # noqa: PLC0415
    reg = ws / "claim-register.yaml"
    reg.write_text(canonical_dump({
        "claims": [{"id": "C-001", "status": "OPEN",
                    "statement": "synthetic claim",
                    "depends_on": []}],
    }), encoding="utf-8")
    return reg


def _read_doc(reg: Path):
    import yaml  # noqa: PLC0415
    return yaml.safe_load(reg.read_text(encoding="utf-8"))


def test_append_adds_one_list_item(tmp_path):
    ws = _mk_ws(tmp_path)
    reg = _seed_list_doc(ws)
    r = _ws_yaml(ws, "append", "claim-register.yaml",
                 "claims.0.depends_on", "C-000")
    assert r.returncode == 0, r.stderr
    assert _read_doc(reg)["claims"][0]["depends_on"] == ["C-000"]


def test_append_never_builds_a_container(tmp_path):
    """The #516 rule holds on the append face: a container literal lands
    as the literal STRING, never as a nested structure."""
    ws = _mk_ws(tmp_path)
    reg = _seed_list_doc(ws)
    _ws_yaml(ws, "append", "claim-register.yaml",
             "claims.0.depends_on", "[C-000, C-001]")
    assert _read_doc(reg)["claims"][0]["depends_on"] == ["[C-000, C-001]"]


def test_append_preserves_order_and_existing_items(tmp_path):
    ws = _mk_ws(tmp_path)
    reg = _seed_list_doc(ws)
    _ws_yaml(ws, "append", "claim-register.yaml",
             "claims.0.depends_on", "C-000")
    _ws_yaml(ws, "append", "claim-register.yaml",
             "claims.0.depends_on", "C-002")
    assert _read_doc(reg)["claims"][0]["depends_on"] == ["C-000", "C-002"]


def test_append_bytes_stay_canonical(tmp_path):
    """The append rendering is the canonical safe_dump (plus the comment
    stamp) — the writer's byte contract holds on this face too."""
    from ws_yaml import canonical_dump  # noqa: PLC0415
    ws = _mk_ws(tmp_path)
    reg = _seed_list_doc(ws)
    _ws_yaml(ws, "append", "claim-register.yaml",
             "claims.0.depends_on", "C-000")
    text = reg.read_text(encoding="utf-8")
    tail = canonical_dump(_read_doc(reg))
    assert text.endswith(tail)
    head = text[:len(text) - len(tail)]
    assert all(ln.startswith("#") for ln in head.splitlines()), head


def test_append_materializes_an_absent_final_key(tmp_path):
    """The mapping-of-lists shape (claim_deps.yaml depends_on[<id>]): an
    absent final key under an existing mapping grows a real list — `set`
    cannot build one (a container literal lands as a string), so append is
    the only sanctioned first-item path."""
    from ws_yaml import canonical_dump  # noqa: PLC0415
    ws = _mk_ws(tmp_path)
    reg = _seed_list_doc(ws)
    r = _ws_yaml(ws, "append", "claim-register.yaml",
                 "claims.0.decomposition", "C-000")
    assert r.returncode == 0, r.stderr
    doc = _read_doc(reg)
    assert doc["claims"][0]["decomposition"] == ["C-000"]
    assert isinstance(doc["claims"][0]["decomposition"], list)
    # claim_deps shape: depends_on is a mapping of child -> parent list
    deps = ws / "claim_deps.yaml"
    deps.write_text(canonical_dump({"depends_on": {}}), encoding="utf-8")
    r2 = _ws_yaml(ws, "append", "claim_deps.yaml",
                  "depends_on.C-009", "C-001")
    assert r2.returncode == 0, r2.stderr
    assert _read_doc(deps)["depends_on"] == {"C-009": ["C-001"]}


def test_append_refuses_a_missing_parent_path(tmp_path):
    """No structure invention: the parent path must exist (exit 5) and an
    existing non-list target is refused (exit 3) — nothing lands."""
    ws = _mk_ws(tmp_path)
    reg = _seed_list_doc(ws)
    before = reg.read_text(encoding="utf-8")
    missing = _ws_yaml(ws, "append", "claim-register.yaml",
                       "claims.9.depends_on", "C-000")
    assert missing.returncode == 5, missing.stderr
    deep = _ws_yaml(ws, "append", "claim-register.yaml",
                    "no_such_section.list", "C-000")
    assert deep.returncode == 5, deep.stderr
    scalar = _ws_yaml(ws, "append", "claim-register.yaml",
                      "claims.0.status", "PROVEN")
    assert scalar.returncode == 3, scalar.stderr
    assert "not a list" in scalar.stderr
    assert reg.read_text(encoding="utf-8") == before, "nothing landed"


def test_append_typo_grows_one_visible_key_only(tmp_path):
    """A final-segment typo is inspectable and reversible (get/del), never
    a nested structure: exactly one new list key appears."""
    ws = _mk_ws(tmp_path)
    reg = _seed_list_doc(ws)
    _ws_yaml(ws, "append", "claim-register.yaml",
             "claims.0.depends_on_typo", "C-000")
    doc = _read_doc(reg)
    assert doc["claims"][0]["depends_on_typo"] == ["C-000"]
    assert [k for k in doc if k != "claims"] == []
    got = _ws_yaml(ws, "get", "claim-register.yaml",
                   "claims.0.depends_on_typo")
    assert got.returncode == 0 and got.stdout.strip() == "[C-000]", got.stdout


def test_append_requires_a_value(tmp_path):
    ws = _mk_ws(tmp_path)
    _seed_list_doc(ws)
    r = _ws_yaml(ws, "append", "claim-register.yaml", "claims.0.depends_on")
    assert r.returncode == 2, r.stderr


def test_append_register_write_settles(tmp_path, monkeypatch):
    """The append face rides the register's settlement emitter leg — the
    sanctioned-writer semantics are identical on every mutating command."""
    import register_proven_gate  # noqa: PLC0415
    import ws_yaml  # noqa: PLC0415

    ws = _mk_ws(tmp_path)
    reg = _seed_list_doc(ws)
    calls: list = []
    monkeypatch.setattr(
        register_proven_gate, "emit_settlements",
        lambda parent, text, old_text: calls.append(parent))
    rc = ws_yaml.main(["append", str(reg), "claims.0.depends_on", "C-000"])
    assert rc == 0
    assert calls == [ws], calls


def test_append_non_register_write_does_not_settle(tmp_path, monkeypatch):
    import register_proven_gate  # noqa: PLC0415
    import ws_yaml  # noqa: PLC0415

    ws = _mk_ws(tmp_path)
    other = ws / "mission_ledger.yaml"
    other.write_text("arms: []\n", encoding="utf-8")
    calls: list = []
    monkeypatch.setattr(
        register_proven_gate, "emit_settlements",
        lambda parent, text, old_text: calls.append(parent))
    rc = ws_yaml.main(["append", str(other), "arms", "arm-1"])
    assert rc == 0
    assert calls == [], "the emission leg arms ONLY on the register carrier"


# --------------------------------------------------------------------------
# Wiring — write_guard gains the second PreToolUse row (Bash face)
# --------------------------------------------------------------------------

def test_write_guard_double_registered():
    assert "write_guard.py" in wire_up_settings.DOUBLE_REGISTERED_HOOKS
    assert "write_guard.py" in wire_up_settings.WIRE_UP_HOOK_FILES


def test_register_hooks_wires_bash_face(tmp_path, monkeypatch):
    import hook_activation  # noqa: E402

    home = tmp_path / "fake-home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setenv("HOME", str(home))
    ws = _mk_ws(tmp_path)
    # neutralize install resolution to the repo checkout under test
    monkeypatch.setattr(
        hook_activation, "_canonical_hooks_dir",
        lambda: ROOT / "hooks")
    rc = hook_activation.register_hooks(ws)
    assert rc >= 0
    settings = json.loads((ws / ".claude" / "settings.json").read_text(
        encoding="utf-8"))
    matchers = set()
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        for h in entry.get("hooks", []):
            if "write_guard.py" in str(h.get("command", "")):
                matchers.add(entry.get("matcher") or "")
    assert "Edit|Write|MultiEdit" in matchers
    assert "Bash" in matchers
