#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_dispatch_protocol.py — dispatch protocol v0/v1 (#452).

Covers:
- v1 (JSON) parsing — happy path + malformed
- v0 (regex) parsing — happy path + legacy forms
- v1 takes precedence over v0 (JSON wins when both present)
- Unparseable dispatch → visible signal (no silent return 0; #452 AC)
- Roundtrip via lib_kunglao.parse_dispatch (the single source).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from _factories import write_hook_state

REPO_ROOT = Path(__file__).resolve().parents[1]

# Load hooks/lib_kunglao.py EXPLICITLY — pytest.ini puts scripts/ on the
# pythonpath which contains a DIFFERENT lib_kunglao.py (the legacy one).
# The dispatch protocol lives in hooks/lib_kunglao.py.
def _load_hooks_lib_kunglao():
    spec = importlib.util.spec_from_file_location(
        "_hooks_lib_kunglao_for_dispatch_test",
        REPO_ROOT / "hooks" / "lib_kunglao.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_lk = _load_hooks_lib_kunglao()
DISPATCH_JSON_RE = _lk.DISPATCH_JSON_START_RE  # alias for back-compat name
DISPATCH_PROTOCOL_VERSION = _lk.DISPATCH_PROTOCOL_VERSION
DISPATCH_RE = _lk.DISPATCH_RE
parse_dispatch = _lk.parse_dispatch
parse_dispatch_json = _lk.parse_dispatch_json


# ----- v1 (JSON) protocol ---------------------------------------------

class TestV1Protocol:
    def test_happy_path(self) -> None:
        text = ('{"kunglao_dispatch": {"version": 1, "claim": "C-409", '
                '"tier": 1, "tools": ["pe_analyze", "strings-classify"], '
                '"agent": "ghidra-light"}}\nrest of prompt')
        tier, tools, claim_id = parse_dispatch(text)
        assert tier == 1
        assert tools == ["pe_analyze", "strings-classify"]
        assert claim_id == "C-409"

    def test_json_parsed_metadata_round_trip(self) -> None:
        text = ('{"kunglao_dispatch": {"version": 1, "claim": "C-007", '
                '"tier": 2, "tools": ["floss"], "agent": "floss-filter", '
                '"task": "decode packed strings"}}')
        tier, tools, claim_id, meta = parse_dispatch_json(text)
        assert claim_id == "C-007"
        assert tier == 2
        assert tools == ["floss"]
        assert meta == {"agent": "floss-filter", "task": "decode packed strings"}

    def test_v1_takes_precedence_over_v0(self) -> None:
        """When both v0 and v1 markers are present, v1 wins (JSON is canonical)."""
        text = (
            '[T1 tools=grep] claim C-001 fallback-prompt\n'
            '{"kunglao_dispatch": {"version": 1, "claim": "C-999", "tier": 1, "tools": []}}'
        )
        tier, _, claim_id = parse_dispatch(text)
        assert claim_id == "C-999", "v1 must win over v0"

    def test_wrong_version_returns_empty(self) -> None:
        text = ('{"kunglao_dispatch": {"version": 99, "claim": "C-1", "tier": 1}}')
        assert parse_dispatch_json(text) == (0, [], None, None)

    def test_invalid_claim_format_returns_empty(self) -> None:
        text = ('{"kunglao_dispatch": {"version": 1, "claim": "claim-1", "tier": 1}}')
        assert parse_dispatch_json(text) == (0, [], None, None)

    def test_invalid_tier_returns_empty(self) -> None:
        text = ('{"kunglao_dispatch": {"version": 1, "claim": "C-1", "tier": 9}}')
        assert parse_dispatch_json(text) == (0, [], None, None)

    def test_malformed_json_returns_empty(self) -> None:
        text = ('{"kunglao_dispatch": {"version": 1, "claim": "C-1", NOT VALID JSON')
        assert parse_dispatch_json(text) == (0, [], None, None)

    def test_missing_kunglao_dispatch_key(self) -> None:
        text = '{"other_key": {"version": 1, "claim": "C-1"}}'
        assert parse_dispatch_json(text) == (0, [], None, None)

    def test_non_string_tools_normalised(self) -> None:
        text = ('{"kunglao_dispatch": {"version": 1, "claim": "C-1", '
                '"tier": 1, "tools": ["a", 2, "", "b"]}}')
        _, tools, _ = parse_dispatch(text)
        # Non-string items are coerced via str() and trimmed; empty dropped.
        # `2` becomes `"2"`, `""` dropped, others preserved.
        assert tools == ["a", "2", "b"]


# ----- v0 (regex) protocol --------------------------------------------

class TestV0Protocol:
    def test_happy_path(self) -> None:
        tier, tools, claim_id = parse_dispatch("[T1 tools=grep,strings-classify] claim C-001")
        assert tier == 1
        assert tools == ["grep", "strings-classify"]
        assert claim_id == "C-001"

    def test_with_prose_after(self) -> None:
        text = "[T2 tools=pe_analyze] claim C-007 investigate overlay section"
        tier, tools, claim_id = parse_dispatch(text)
        assert tier == 2
        assert tools == ["pe_analyze"]
        assert claim_id == "C-007"

    def test_no_match_returns_zeros(self) -> None:
        assert parse_dispatch("no dispatch here") == (0, [], None)

    def test_partial_match_does_not_match(self) -> None:
        assert parse_dispatch("[T1] claim C-001") == (0, [], None)


# ----- dispatch_gate.py unparseable signal (#452 AC) ------------------

class TestDispatchGateWarning:
    """#452 AC: when neither v0 nor v1 matches, the hook MUST emit a
    visible signal (stderr + hookSpecificOutput). Pre-#452 silent-return-0
    hid protocol drift; the test asserts the warning is now observable."""

    def test_warn_function_emits_to_stderr(self, capsys) -> None:
        from dispatch_gate import _warn_unparseable

        _warn_unparseable(None, "v0/v1 both unmatched")
        captured = capsys.readouterr()
        assert "unrecognized dispatch protocol" in captured.err
        out = json.loads(captured.out.strip().splitlines()[0])
        assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "WARN" in out["hookSpecificOutput"]["additionalContext"]

    def test_unparseable_dispatch_triggers_warning(self, tmp_path: Path) -> None:
        """End-to-end: an Agent prompt with no protocol header must trigger
        the warning (no longer silent)."""
        ws = tmp_path / "malware-analysis-workspace"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text("", encoding="utf-8")
        write_hook_state(ws, active_hooks=["dispatch_gate"])

        import subprocess

        script = REPO_ROOT / "hooks" / "dispatch_gate.py"
        payload = json.dumps({
            "cwd": str(tmp_path),
            "tool_input": {"prompt": "do something, no protocol header"},
        })
        r = subprocess.run(
            [sys.executable, str(script)],
            input=payload, capture_output=True, text=True, timeout=30,
            cwd=REPO_ROOT, errors="replace",
        )
        assert r.returncode == 0, f"hook should not block ({r.stdout}{r.stderr})"
        # #452 AC: visible signal — stderr carries the warning
        assert "unrecognized dispatch protocol" in r.stderr, \
            f"expected warning in stderr; got {r.stderr!r}"
        assert "WARN" in r.stdout

    def test_v1_dispatch_does_not_warn(self, tmp_path: Path) -> None:
        """A well-formed v1 dispatch must NOT trigger the warning."""
        ws = tmp_path / "malware-analysis-workspace"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text("", encoding="utf-8")
        write_hook_state(ws, active_hooks=["dispatch_gate"])

        import subprocess

        script = REPO_ROOT / "hooks" / "dispatch_gate.py"
        payload = json.dumps({
            "cwd": str(tmp_path),
            "tool_input": {"prompt": '{"kunglao_dispatch": {"version": 1, "claim": "C-1", "tier": 1}}'},
        })
        r = subprocess.run(
            [sys.executable, str(script)],
            input=payload, capture_output=True, text=True, timeout=30,
            cwd=REPO_ROOT, errors="replace",
        )
        assert r.returncode == 0
        # No warning because the protocol was recognised
        assert "unrecognized dispatch protocol" not in r.stderr, \
            f"v1 should NOT warn; got stderr={r.stderr!r}"


# ----- dispatch protocol version constant ------------------------------

def test_protocol_version_is_one() -> None:
    assert DISPATCH_PROTOCOL_VERSION == 1


# ----- #447 must-stop at dispatch time (Type S hook) ------------------

class TestDispatchMustStop:
    """#447: irreversible actions in the dispatch prompt MUST HARD_PAUSE
    (rc=2 + stderr + hookSpecificOutput) BEFORE the worker runs."""

    def _setup_ws(self, tmp_path: Path) -> Path:
        ws = tmp_path / "malware-analysis-workspace"
        ws.mkdir(parents=True)
        (ws / "claim-register.yaml").write_text("", encoding="utf-8")
        write_hook_state(ws, active_hooks=["dispatch_gate"])
        return tmp_path

    def _run_hook(self, tmp_path: Path, prompt: str):
        import subprocess
        script = REPO_ROOT / "hooks" / "dispatch_gate.py"
        payload = json.dumps({
            "cwd": str(tmp_path),
            "tool_input": {"prompt": prompt},
        })
        return subprocess.run(
            [sys.executable, str(script)],
            input=payload, capture_output=True, text=True, timeout=30,
            cwd=REPO_ROOT, errors="replace",
        )

    def test_must_stop_unit_match(self) -> None:
        import importlib
        import dispatch_gate as dg
        importlib.reload(dg)
        assert dg._must_stop_dispatch("vmrun delete VM-1") is not None
        assert dg._must_stop_dispatch("git push --force origin") is not None
        assert dg._must_stop_dispatch("publish to pypi") is not None
        assert dg._must_stop_dispatch("normal analysis work") is None

    def test_irreversible_dispatch_hard_pauses(self, tmp_path: Path) -> None:
        """A dispatch prompt containing an irreversible action MUST exit 2
        (hard pause) + emit stderr signal."""
        self._setup_ws(tmp_path)
        prompt = ('[T2 tools=vmrun] claim C-409 '
                  'task: cleanup environment, vmrun delete VM-1')
        r = self._run_hook(tmp_path, prompt)
        assert r.returncode == 2, \
            f"must-stop must HARD_PAUSE; got rc={r.returncode}, " \
            f"stdout={r.stdout!r}, stderr={r.stderr!r}"
        assert "HARD_PAUSE" in r.stderr
        assert "must-stop" in r.stderr

    def test_normal_dispatch_does_not_hard_pause(self, tmp_path: Path) -> None:
        """A normal dispatch prompt (no irreversible action) exits 0 (silent),
        not 2 — must-stop is narrow."""
        self._setup_ws(tmp_path)
        prompt = "[T1 tools=grep] claim C-401 static string extraction"
        r = self._run_hook(tmp_path, prompt)
        assert r.returncode == 0, \
            f"normal dispatch must stay silent; stderr={r.stderr!r}"
        assert "must-stop" not in r.stderr

    def test_declared_irreversible_field_fires_must_stop(self, tmp_path: Path) -> None:
        """#447 declaration-over-inference: a v1 dispatch declaring
        `"reversible": false` MUST hard-pause — language-independent, no
        prose inference involved. The dispatch text itself carries no
        irreversible keyword in any language."""
        self._setup_ws(tmp_path)
        prompt = ('{"kunglao_dispatch": {"version": 1, "claim": "C-77", '
                  '"tier": 2, "tools": ["vmr-shell"], '
                  '"reversible": false}}\n'
                  'task text contains no dangerous keyword at all')
        r = self._run_hook(tmp_path, prompt)
        assert r.returncode == 2, \
            f"declared irreversible must HARD_PAUSE; rc={r.returncode}, " \
            f"stderr={r.stderr!r}"
        assert "must-stop" in r.stderr

    def test_declared_reversible_true_does_not_fire(self, tmp_path: Path) -> None:
        """`"reversible": true` (or absent) = ordinary dispatch; the field
        only fires on an explicit false declaration."""
        self._setup_ws(tmp_path)
        prompt = ('{"kunglao_dispatch": {"version": 1, "claim": "C-78", '
                  '"tier": 1, "tools": ["grep"], '
                  '"reversible": true}}')
        r = self._run_hook(tmp_path, prompt)
        assert r.returncode == 0, \
            f"reversible:true must stay silent; stderr={r.stderr!r}"

    def test_chinese_prose_alone_is_not_irreversible(self, tmp_path: Path) -> None:
        """Declaration-over-inference doctrine: Chinese prose (or any prose)
        without a declared field or command-grammar hit must NOT hard-pause.
        Prose sniffing is a tripwire in the TEXT gate, never load-bearing
        here."""
        self._setup_ws(tmp_path)
        prompt = ('{"kunglao_dispatch": {"version": 1, "claim": "C-79", '
                  '"tier": 1, "tools": ["strings"]}}\n'
                  '描述文本: 删除虚拟机的可能性讨论, but no command executed')
        r = self._run_hook(tmp_path, prompt)
        assert r.returncode == 0, \
            f"prose alone must not fire dispatch must-stop; stderr={r.stderr!r}"