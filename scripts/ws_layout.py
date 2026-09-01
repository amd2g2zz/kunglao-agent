#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ws_layout.py — the ONE workspace-resolution source (#863 Family C).

Nine scripts carried private ``_resolve_ws`` copies in 4 shapes (issue
#863): one manifest-aware probe (convergence_check only), two silent
hardcoded-sibling probes (claim-register vs the convergence ledger
sentinel), and the #228 hard-error probe (heartbeat_tick / hooks_selfcheck /
heartbeat_touch / statusline_snapshot). 8 of the 9 hardcoded the sibling
directory name, silently ignoring a manifest ``layout.workspace_dir``
override — latent bug B2 (the fix-first ruling folds the behavior fix into
this extraction: every former copy now honors the layout).

Two public entrypoints:

  * ``resolve_quiet(arg, sentinel=None)`` — the silent family: explicit arg
    wins (verbatim, no resolve()); else probe
    ``<cwd>/<layout.workspace_dir>`` for the sentinel file; absent → fall
    back to cwd. ``sentinel=None`` uses ``layout.claim_register``;
    convergence_health passes its ledger name (its own sentinel is the
    convergence ledger, not the claim register).
  * ``resolve_strict(arg)`` — the #228 family: explicit arg wins, resolved
    absolute; else probe cwd THEN ``<cwd>/<layout.workspace_dir>`` (cwd-first
    order preserved from the inline copies) for the claim register OR the
    orchestrator state file; nothing found → stderr guidance +
    ``sys.exit(2)``. Never guess a workspace (#228: a wrong one means state
    written to the wrong tree).

Layout names come from ``env_manifest.layout_conventions`` — absent
manifest → DEFAULT_LAYOUT (the pre-#450 literals), behavior byte-identical
to the hardcoded copies. The B2 fix only changes workspaces that declare a
layout override, aligning all nine consumers with
``hooks/dispatch_gate.py::_resolve_workspace`` (#450 contract face).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# The orchestrator state file (workspace root). NOT a layout convention —
# no manifest field has ever carried it; the strict family probes it beside
# the claim register since its inception.
ANALYSIS_STATE = "analysis_state.txt"


def resolve_quiet(arg: str | None, *, sentinel: str | None = None) -> Path:
    """Silent family: arg wins; else the manifest workspace_dir sibling
    holding the sentinel; else cwd (pre-#450 fallback, byte-identical)."""
    if arg:
        return Path(arg)
    # function-level on purpose: keep the consumers' module import graph
    # unchanged (env_manifest reconfigures stdout at import; the former
    # inline copies loaded it lazily, and downstream output bytes must not
    # shift as a side effect of this extraction).
    import env_manifest  # (same scripts/ dir)
    cwd = Path(os.getcwd())
    layout = env_manifest.layout_conventions(cwd)
    sub = cwd / layout.workspace_dir
    marker = sentinel if sentinel is not None else layout.claim_register
    return sub if (sub / marker).exists() else cwd


def resolve_strict(arg: str | None) -> Path:
    """#228 family: arg wins (resolved); else probe cwd then the manifest
    workspace_dir sibling for the claim register or the state file; nothing
    found → stderr guidance + exit 2 (never guess a workspace)."""
    if arg:
        return Path(arg).resolve()
    import env_manifest  # (same scripts/ dir; lazy — see resolve_quiet)
    cwd = Path(os.getcwd())
    layout = env_manifest.layout_conventions(cwd)
    for cand in (cwd, cwd / layout.workspace_dir):
        if (cand / layout.claim_register).exists() \
                or (cand / ANALYSIS_STATE).exists():
            return cand.resolve()
    print(f"ERROR: no workspace found under cwd ({cwd}); pass the workspace "
          f"explicitly: python {Path(sys.argv[0]).name} <workspace>",
          file=sys.stderr)
    sys.exit(2)
