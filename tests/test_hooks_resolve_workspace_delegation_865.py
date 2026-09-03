# -*- coding: utf-8 -*-
"""#865: hooks-side _resolve_workspace ×3 must bind the canonical
hooks.lib_kunglao.resolve_workspace_canonical function ITSELF — not a
wrapper, not a re-implementation, not a hardcoded sibling literal.

Three copy sites are pinned (B3 drift CONFIRMED by audit, see issue #865
body for full citation chain):

  hooks/dispatch_gate.py:104   _resolve_workspace  (after #450 manifest fix;
                               docstring already correct)
  hooks/env_check_gate.py:88   _resolve_workspace  (drift: hardcoded
                               "malware-analysis-workspace", no manifest)
  hooks/recall_inject.py:123   _resolve_workspace  (byte-identical to
                               env_check_gate, same drift)

The fix: extend hooks.lib_kunglao with `resolve_workspace_canonical`
(sibling to the existing analysis_state.txt-flavoured
`resolve_workspace`) that uses `_env_layout` + layout.claim_register
for probe, then the three hooks' private copies become one-liners
delegating to it. The dispatch_gate inline body has been correctly
reading the manifest since #450; this test re-pins the new identity so
the fix cannot regress without a test failure.

Mirror of test_ws_layout_delegation_863c.test_resolve_ws_alias_identity —
the 863c test covered scripts/ws_layout consumers; this file covers the
hooks/lib_kunglao consumer layer that #865 explicitly identifies as
"3 hooks copies not yet delegated".
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "hooks"

# Sibling modules under hooks/ need each other + scripts/ on sys.path
# (hooks/lib_kunglao.py uses on_path() at call time; this guard covers
# the test's own import path).
sys.path.insert(0, str(HOOKS))
sys.path.insert(0, str(ROOT / "scripts"))


def _import(mod_name: str):
    return importlib.import_module(mod_name)


def test_hooks_resolve_workspace_delegates_to_canonical():
    """Each hooks/_resolve_workspace must call through to
    hooks.lib_kunglao.resolve_workspace_canonical — same path on the
    same payload, regardless of which hook entry the caller took.

    Why call-through (not identity): the hooks twin of lib_kunglao is
    loaded via load_hooks_lib() (#770 + #863 Family B) to avoid the
    scripts/ twin binding under pytest. An identity check (`is`) would
    still work in production (where hooks/lib_kunglao.py is the only
    lib_kunglao on sys.path) but breaks the moment an embedder or test
    inserts scripts/ earlier — the exact failure mode #865 is closing.
    The fix is to pin the call-through behavior: every hooks copy
    produces the same Path as the canonical helper for the same payload,
    so future inline drift fails the equality check before it reaches
    runtime.
    """
    import sys
    if str(HOOKS) not in sys.path:
        sys.path.insert(0, str(HOOKS))
    from _path_hygiene import load_hooks_lib
    lk = load_hooks_lib()
    canonical = getattr(lk, "resolve_workspace_canonical", None)
    assert canonical is not None, (
        "hooks/lib_kunglao.py must expose resolve_workspace_canonical — "
        "the hooks-side single source for workspace resolution (#865). "
        "Without it, the 3 hooks copies cannot delegate and the B3 drift "
        "is structurally unrecoverable.")

    fixtures = [
        # minimal payload — cwd only
        {"cwd": "/tmp"},
        # payload with explicit workspace (still cwd wins per the inline contract)
        {"cwd": "/tmp", "workspace": "/var/elsewhere"},
        # empty payload — should not crash, returns None
        {},
    ]

    sites = ["dispatch_gate", "env_check_gate", "recall_inject"]
    drifted = {}
    for name in sites:
        mod = _import(name)
        hook_resolver = getattr(mod, "_resolve_workspace", None)
        if hook_resolver is None:
            drifted[name] = "_resolve_workspace not defined"
            continue
        for payload in fixtures:
            expected = canonical(payload)
            got = hook_resolver(payload)
            if got != expected:
                drifted[name] = (
                    f"payload={payload!r}: got {got!r}, "
                    f"canonical returned {expected!r}")
                break
    assert drifted == {}, (
        "hooks/_resolve_workspace must call through to "
        "hooks.lib_kunglao.resolve_workspace_canonical (#865); "
        f"drifted: {drifted}")


def test_hooks_resolve_workspace_docstrings_do_not_claim_dispatch_equivalence():
    """The 2/3 docstring drift (#865 B3, audit ruling): env_check_gate
    and recall_inject's docstrings still claim 'same resolution as
    dispatch_gate.py: cwd -> malware-analysis-workspace' — false under
    the manifest fix. After delegation the three hooks docstrings should
    say 'delegate to hooks.lib_kunglao.resolve_workspace_canonical' so
    future readers do not chase a phantom dispatch_gate copy."""
    expected_phrase = "resolve_workspace_canonical"
    sites = ["dispatch_gate", "env_check_gate", "recall_inject"]
    bad = {}
    for name in sites:
        path = HOOKS / f"{name}.py"
        if not path.exists():
            bad[name] = "<file gone>"
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if expected_phrase not in text:
            bad[name] = f"missing '{expected_phrase}' phrase"
    assert bad == {}, (
        "each hooks/<gate>.py must reference resolve_workspace_canonical "
        "so the docstring stops claiming dispatch_gate-equivalence (#865 "
        f"B3); bad: {bad}")
