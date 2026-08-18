# -*- coding: utf-8 -*-
"""Issue #445 — hook registration path unification (three paths -> one).

RED contract (dev baseline 6462fe4, 2026-08-18): THREE independent
registration writers coexist — wire_up_settings.wire_up_settings (full
registry, ws-level + legacy user-global opt-in), external_kicker.
ensure_project_hooks (5-entry bootstrap subset, ws-parent level) and
kunglao-init deploy_hooks/_patch_settings (worker_budget subset) — each
with its OWN hand-rolled entry construction, and NONE self-checks after
writing (the historical class: hooks written to a layer that does not
fire, silently). This file pins the #445 acceptance:

  AC1  exactly ONE canonical registration entry
       (hook_activation.register_hooks); the legacy names are declared
       deprecated aliases; only the canonical module constructs entries.
  AC2  post-registration self-check (written location vs declared fire
       layer + coverage + command shape); mismatch -> CLI --wire-up FAIL
       (exit 1) and init FAIL (RC_HOOK_WIRING), never a silent OK/WARN.
  AC3  external_kicker.ensure_project_hooks is an EXPLICITLY DECLARED
       subordinate of the canonical entry and shares its construction
       source byte-for-byte.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
HOOKS = ROOT / "hooks"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import external_kicker  # noqa: E402
import hook_activation  # noqa: E402
import wire_up_settings  # noqa: E402


def _load_init():
    """kunglao-init.py is hyphen-named (not importable by statement) — load
    it by path under a stable module name (the repo's explicit-path loading
    convention; one shared instance across this file's tests)."""
    name = "kunglao_init"
    mod = sys.modules.get(name)
    if mod is None:
        spec = importlib.util.spec_from_file_location(
            name, SCRIPTS / "kunglao-init.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    """Path.home() -> tmp (the #258 regression probe: user-global settings
    must never be written by a project-layer registration)."""
    home = tmp_path / "fake-home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pathlib.Path, "home", lambda: home)
    return home


def _collect_commands(settings: dict) -> list[str]:
    cmds = []
    for entries in settings.get("hooks", {}).values():
        for e in entries:
            for h in e.get("hooks", []):
                cmds.append(str(h.get("command", "")))
    return cmds


def _basenames(settings: dict) -> set[str]:
    return {c.replace("\\", "/").rsplit("/", 1)[-1] for c in _collect_commands(settings)}


# ===========================================================================
# AC1 — exactly one registration entry
# ===========================================================================

def test_canonical_entry_is_declared_and_callable() -> None:
    """hook_activation declares THE registration entry (#445 D1)."""
    assert hook_activation.CANONICAL_REGISTRATION_ENTRY == (
        "hook_activation.register_hooks"), (
        "the canonical entry must be declared by name in hook_activation")
    assert callable(hook_activation.register_hooks), (
        "hook_activation.register_hooks must exist as the canonical writer")


def test_legacy_names_are_declared_aliases_and_subordinates() -> None:
    """The legacy names survive ONLY as declared aliases / subordinates."""
    assert "wire_up_settings.wire_up_settings" in (
        hook_activation.DEPRECATED_ALIASES), (
        "the legacy writer must be a declared deprecated alias")
    assert "external_kicker.ensure_project_hooks" in (
        hook_activation.DECLARED_SUBORDINATE_WRITERS), (
        "the kicker bootstrap writer must be a declared subordinate")


def test_wire_up_settings_function_is_deprecated_delegating_alias(
        tmp_path, monkeypatch) -> None:
    """wire_up_settings() must DELEGATE to register_hooks under a
    DeprecationWarning — no second writer, a pure pass-through (#445 D2)."""
    calls: list[dict] = []

    def _recorder(workspace=None, global_opt_in=False):
        calls.append({"workspace": workspace, "global_opt_in": global_opt_in})
        return 9

    monkeypatch.setattr(hook_activation, "register_hooks", _recorder)
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.warns(DeprecationWarning, match="hook_activation.register_hooks"):
        n = wire_up_settings.wire_up_settings(workspace=ws, global_opt_in=True)
    assert n == 9, "alias must return the canonical writer's count"
    assert calls == [{"workspace": ws, "global_opt_in": True}], (
        "alias must forward its arguments verbatim")


def test_only_canonical_module_constructs_hook_entries() -> None:
    """Static single-entry scan (#445 D6): after docstring stripping, the
    hook-entry construction signature `{"matcher": ...}` may appear in
    exactly ONE module — hook_activation. RED baseline: it also appears in
    wire_up_settings, external_kicker and kunglao-init (three hand-rolled
    writers, the D1 proliferation)."""
    offenders: list[str] = []
    for mod in sorted(list(SCRIPTS.glob("*.py")) + list(HOOKS.glob("*.py"))):
        source = mod.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:  # fail loud, never skip silently
            pytest.fail(f"{mod.name}: unparseable ({exc})")
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.ClassDef)):
                body = node.body
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    node.body = body[1:] or [ast.Pass()]
        if re.search(r'["\']matcher["\']\s*:', ast.unparse(tree)):
            offenders.append(mod.name)
    assert offenders == ["hook_activation.py"], (
        f"hook-entry construction must exist ONLY in hook_activation.py "
        f"(the canonical entry); found in: {offenders}")


# ===========================================================================
# AC2 — post-registration self-check; mismatch FAILs (CLI + init)
# ===========================================================================

def test_register_hooks_cli_ok_and_selfcheck_passes(tmp_path, fake_home,
                                                    monkeypatch, capsys) -> None:
    """Happy path: --wire-up writes the ws-level target, self-check passes,
    CLI exits 0 with OK (#445 D5)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(sys, "argv",
                        ["hook_activation.py", str(ws), "--wire-up"])
    rc = hook_activation.main()
    out = capsys.readouterr()
    assert rc == 0, f"--wire-up must succeed on a clean write: {out.err}"
    assert "OK:" in out.out, "success must stay recognizable (OK line)"
    target = ws / ".claude" / "settings.json"
    settings = json.loads(target.read_text(encoding="utf-8"))
    assert _basenames(settings) == set(wire_up_settings.WIRE_UP_HOOK_FILES), (
        "the canonical writer must register the full registry")
    result = hook_activation.selfcheck_registration(
        target, expected_files=wire_up_settings.WIRE_UP_HOOK_FILES,
        workspace=ws, layer="project")
    assert result["ok"] is True, f"self-check must pass on its own write: {result}"
    assert not (fake_home / ".claude" / "settings.json").exists(), (
        "project-layer registration must never write the user-global file (#258)")


def test_wire_up_cli_fails_loud_on_layer_mismatch(tmp_path, fake_home,
                                                  monkeypatch, capsys) -> None:
    """THE #445 scenario, reproduced: the writer resolves the USER-GLOBAL
    file for a project-layer registration (the wire_up_settings.py:20
    historical bug). The CLI must FAIL (exit 1) — never print OK."""
    ws = tmp_path / "ws"
    ws.mkdir()
    wrong_layer = fake_home / ".claude" / "settings.json"

    def _mismatched_target(workspace, global_opt_in=False):
        return wrong_layer  # the historical mis-wiring, injected at the seam

    monkeypatch.setattr(hook_activation, "_resolve_registration_target",
                        _mismatched_target)
    monkeypatch.setattr(sys, "argv",
                        ["hook_activation.py", str(ws), "--wire-up"])
    rc = hook_activation.main()
    out = capsys.readouterr()
    assert rc == 1, "layer mismatch must FAIL the registration (exit 1)"
    assert "FAIL" in out.err, f"failure reason must reach stderr: {out.err}"
    assert "OK:" not in out.out, "a failed wiring must never print OK"


def test_register_hooks_raises_on_layer_mismatch(tmp_path, fake_home,
                                                 monkeypatch) -> None:
    """API-level fail-closed: register_hooks raises HookWiringSelfcheckError
    when the write lands on a non-firing layer (caller cannot ignore it)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setattr(
        hook_activation, "_resolve_registration_target",
        lambda workspace, global_opt_in=False:
            fake_home / ".claude" / "settings.json")
    with pytest.raises(hook_activation.HookWiringSelfcheckError):
        hook_activation.register_hooks(workspace=ws)


def test_selfcheck_flags_dropped_entries(tmp_path, fake_home) -> None:
    """Coverage leg: a settings rewrite that DROPS a hook segment (the
    v1.9.37 'hooks lost again' class) must fail the self-check."""
    ws = tmp_path / "ws"
    ws.mkdir()
    hook_activation.register_hooks(workspace=ws)
    target = ws / ".claude" / "settings.json"
    settings = json.loads(target.read_text(encoding="utf-8"))
    del settings["hooks"]["Stop"]  # completion_gate silently dropped
    target.write_text(json.dumps(settings), encoding="utf-8")
    result = hook_activation.selfcheck_registration(
        target, expected_files=wire_up_settings.WIRE_UP_HOOK_FILES,
        workspace=ws, layer="project")
    assert result["ok"] is False, "dropped entries must fail the self-check"
    assert "completion_gate.py" in result["missing"]


def test_selfcheck_flags_user_global_layer(tmp_path, fake_home) -> None:
    """Layer leg: a user-global file carrying PERFECT entries still fails a
    project-layer check — the file does not fire for this workspace."""
    ws = tmp_path / "ws"
    ws.mkdir()
    hook_activation.register_hooks(workspace=ws)
    content = (ws / ".claude" / "settings.json").read_text(encoding="utf-8")
    wrong_layer = fake_home / ".claude" / "settings.json"
    wrong_layer.write_text(content, encoding="utf-8")
    result = hook_activation.selfcheck_registration(
        wrong_layer, expected_files=wire_up_settings.WIRE_UP_HOOK_FILES,
        workspace=ws, layer="project")
    assert result["ok"] is False, "user-global is not a project fire layer"
    assert any("layer" in m for m in result["mismatches"]), (
        f"the mismatch report must name the layer problem: {result['mismatches']}")


# ===========================================================================
# AC2 (init leg) — deploy_hooks self-check -> RC_HOOK_WIRING FAIL
# ===========================================================================

def _seeded_hooks_json(ws: Path) -> Path:
    target = ws / "seeded-settings.json"
    target.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    return target


def test_init_deploy_hooks_runs_selfcheck(tmp_path, fake_home) -> None:
    """Positive wiring proof (no vacuous green): a REAL init deploy is
    followed by a REAL self-check that passes and lands in the report."""
    kunglao_init = _load_init()
    ws = tmp_path / "ws"
    ws.mkdir()
    hooks_json = _seeded_hooks_json(ws)
    report = kunglao_init.deploy_hooks(ws, hooks_json)
    assert report["deployed"] is True, "seeded --hooks-json must be deployed"
    assert report["selfcheck"]["ok"] is True, (
        f"a healthy deploy must self-check clean: {report['selfcheck']}")
    assert report["selfcheck"]["layer"] == "operator-declared"


def test_init_deploy_hooks_mismatch_is_fail_not_warn(tmp_path, fake_home,
                                                     monkeypatch) -> None:
    """#445 explicit demand: init self-check mismatch -> FAIL (RC_HOOK_WIRING),
    never a warning + RC_OK."""
    kunglao_init = _load_init()
    ws = tmp_path / "ws"
    ws.mkdir()
    hooks_json = _seeded_hooks_json(ws)
    monkeypatch.setattr(
        hook_activation, "selfcheck_registration",
        lambda *a, **k: {"ok": False,
                         "mismatches": ["layer: user-global is not a fire layer"]})
    report = kunglao_init.deploy_hooks(ws, hooks_json)
    assert report["selfcheck"]["ok"] is False, (
        "a failing self-check must be carried in the report")
    assert kunglao_init.hook_deploy_rc(report) == kunglao_init.RC_HOOK_WIRING
    assert kunglao_init.RC_HOOK_WIRING != 0, "wiring failure is a FAIL exit"


def test_hook_deploy_rc_mapping() -> None:
    """The report->exit-code mapping: healthy/skip -> RC_OK; self-check
    mismatch -> RC_HOOK_WIRING (init FAIL channel)."""
    kunglao_init = _load_init()
    assert kunglao_init.hook_deploy_rc(
        {"deployed": False, "reason": "no settings.json"}) == 0, (
        "the nothing-written skip stays benign")
    assert kunglao_init.hook_deploy_rc(
        {"deployed": True, "selfcheck": {"ok": True}}) == 0
    assert kunglao_init.hook_deploy_rc(
        {"deployed": True, "selfcheck": {"ok": False}}) == (
        kunglao_init.RC_HOOK_WIRING)


# ===========================================================================
# AC3 — kicker: declared subordinate, shared construction source
# ===========================================================================

def test_external_kicker_declares_registration_relation() -> None:
    """The kicker's relationship to the canonical entry is machine-readable
    (#445 D3): names the canonical entry, declares the subordinate role."""
    rel = external_kicker.REGISTRATION_RELATION
    assert rel["canonical_entry"] == hook_activation.CANONICAL_REGISTRATION_ENTRY, (
        "the kicker must point at THE canonical entry")
    assert "subordinate" in rel["role"], (
        f"the kicker is a declared subordinate, not a peer entry: {rel['role']}")


def test_kicker_entries_are_canonical_builder_output(tmp_path) -> None:
    """Single construction source: every entry ensure_project_hooks writes
    is byte-identical to hook_activation.build_hook_entry output — the two
    paths can no longer drift apart in command shape."""
    hook_dir = tmp_path / "hooks"
    out, _ = external_kicker.ensure_project_hooks({}, str(hook_dir))
    hooks_seg = out["hooks"]
    for event, matcher, hook_file in external_kicker.KUNGLAO_HOOK_ENTRIES:
        expected = hook_activation.build_hook_entry(hook_dir, hook_file, matcher)
        assert expected in hooks_seg[event], (
            f"{event}/{matcher}/{hook_file}: kicker entry must BE the "
            f"canonical builder output:\n  kicker:    {hooks_seg[event]}\n  canonical: {expected}")


def test_init_entry_construction_uses_canonical_builder(tmp_path) -> None:
    """init's _ensure produces canonical-builder-shaped entries (no third
    hand-rolled constructor)."""
    kunglao_init = _load_init()
    hook_dir = tmp_path / "hooks"
    entries, added = kunglao_init._ensure([], "Agent", kunglao_init.HOOK_FILES[0],
                                          hook_dir)
    assert added is True
    assert entries[-1] == hook_activation.build_hook_entry(
        hook_dir, kunglao_init.HOOK_FILES[0], "Agent")
