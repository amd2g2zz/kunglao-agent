# -*- coding: utf-8 -*-
"""#24 doc-pointer lighting: violation warnings carry verified doc pointers.

R4 postmortem: the agent re-triggered the same bash-loop warning and cost
notices 4x — it explored by trial-and-error instead of reading the docs
that document the protected patterns. Lighting, not gating (owner): when a
warning fires, the warning text itself names the authoritative doc so the
next action is a read, not another blind probe.

Honesty rules pinned here:
  - a pattern with NO verified doc keeps its text unchanged (no fake
    pointers)
  - a mapped pointer whose target is missing from disk is never emitted
  - every pointer in every hook map must resolve to a real repo file
"""
import importlib.util
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The incident sed, verbatim shape (same fixture as #718).
_INCIDENT_SED = ("sed -i "
                 "'s/verify_status: pending-verifier/verify_status: passes/' "
                 "notes/N-101-q2-answer.md")

_TRACEBACK = ("running selfcheck...\n"
              "Traceback (most recent call last):\n"
              '  File "scripts/hooks_selfcheck.py", line 88, in main\n'
              "    raise HookWiringSelfcheckError(detail)\n"
              "HookWiringSelfcheckError: 2 mismatch(es)\n")

_OLD_FACT = ("---\nid: F001\nclaim: crash in worker\n"
             "status: PARTIALLY-VERIFIED\n---\nbody text only.\n")


def _load(name: str, rel: str):
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(name, ROOT / rel)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


def _vc():
    return _load("doc_pointer_lighting_vc_24", "hooks/violation_capture.py")


def _bfg():
    return _load("doc_pointer_lighting_bfg_24", "hooks/bash_fact_guard.py")


def _mk_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / "runs" / "logs").mkdir(parents=True)
    return ws


def _ledger_rows(ws: Path) -> list[dict]:
    rows = []
    for p in sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# mapped patterns → the warning text names the verified doc
# ---------------------------------------------------------------------------

def test_tamper_warning_names_guardrails_doc(tmp_path):
    """violation_sed_tamper (out-of-band carrier rewrite) -> guardrails.md,
    the doc that forbids anyone but an independent verifier writing
    verify_status."""
    mod = _vc()
    ws = _mk_ws(tmp_path)
    payload = json.dumps({"cwd": str(ws),
                          "tool_input": {"command": _INCIDENT_SED},
                          "tool_response": {"stdout": "", "stderr": ""}})
    assert mod.main(io.StringIO(payload)) == 0
    tamper = [r for r in _ledger_rows(ws)
              if r["action"] == "violation_sed_tamper"]
    assert tamper, "incident sed must still be recorded"
    assert "references/guardrails.md" in tamper[0]["detail"]
    assert "read before retrying" in tamper[0]["detail"]


def test_env_incident_names_error_taxonomy_doc(tmp_path):
    """env_incident (traceback in Bash output) -> error-response-taxonomy.md,
    the mandatory stop/retry-once/ask/escalate classification."""
    mod = _vc()
    ws = _mk_ws(tmp_path)
    payload = json.dumps({"cwd": str(ws),
                          "tool_input": {"command": "python scripts/x.py"},
                          "tool_response": {"stdout": _TRACEBACK,
                                            "stderr": ""}})
    assert mod.main(io.StringIO(payload)) == 0
    inc = [r for r in _ledger_rows(ws) if r["action"] == "env_incident"]
    assert inc, "traceback must still be recorded"
    assert "references/error-response-taxonomy.md" in inc[0]["detail"]
    assert "read before retrying" in inc[0]["detail"]


def test_bash_fact_guard_violation_names_schema_doc(tmp_path, capsys):
    """facts-write lint violation surfaced via additionalContext carries the
    fact-file schema doc pointer."""
    mod = _bfg()
    ws = tmp_path / "ws"
    (ws / "facts").mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "facts" / "F001.md").write_text(_OLD_FACT, encoding="utf-8")
    cmd = "cat > facts/F001.md <<'EOF'\nbody text only.\nEOF"
    payload = {"cwd": str(ws), "tool_name": "Bash",
               "tool_input": {"command": cmd}}
    assert mod.main(stdin_stream=io.StringIO(json.dumps(payload))) == 0
    out = capsys.readouterr().out
    assert "additionalContext" in out and "F001.md" in out
    assert "references/schema.md" in out
    assert "read before retrying" in out


# ---------------------------------------------------------------------------
# honesty: no fake pointers
# ---------------------------------------------------------------------------

def test_unmapped_warning_text_unchanged():
    """A pattern with no doc mapping keeps its warning text verbatim."""
    vc, bfg = _vc(), _bfg()
    assert vc.light_detail("not_a_real_action", "keep me") == "keep me"
    assert bfg.light_detail("not_a_real_action", "keep me") == "keep me"


def test_missing_doc_target_no_fake_pointer(monkeypatch):
    """A mapped pointer whose file is missing from disk is never appended."""
    vc, bfg = _vc(), _bfg()
    ghost = "references/__no_such_doc_24__.md"
    for mod, action in ((vc, "violation_sed_tamper"),
                        (bfg, next(iter(bfg.DOC_POINTERS)))):
        monkeypatch.setattr(mod, "DOC_POINTERS", {action: ghost})
        assert mod.light_detail(action, "raw") == "raw"


def test_pointer_targets_exist_in_repo():
    """Every mapped pointer resolves to a real repo file — keeps the map
    honest against doc renames/moves."""
    for mod in (_vc(), _bfg()):
        assert mod.DOC_POINTERS, "hook must ship a pointer map"
        for ptr in mod.DOC_POINTERS.values():
            assert (ROOT / ptr).is_file(), f"fake pointer target: {ptr}"


def test_recalled_decorator_is_pure_on_mapped_pattern():
    """The decorator only appends — the original detail text survives
    verbatim as a prefix (telemetry substrings stay greppable)."""
    vc = _vc()
    ptr = vc.DOC_POINTERS["violation_sed_tamper"]
    out = vc.light_detail("violation_sed_tamper", "base detail")
    assert out.startswith("base detail")
    assert ptr in out
