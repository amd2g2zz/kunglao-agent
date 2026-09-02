# -*- coding: utf-8 -*-
"""tests/test_compat_removal_863d.py — Package 2 batch-1 removal guards (#863).

Owner policy 2026-09-01: NO backward compatibility. The five pure-compat
artifacts retired by 863-d must stay retired — these textual tripwires fail
if any of them is resurrected (same discipline as the textual markers in
test_worker_liveness_protocol.py and the source.count tripwire in
test_toolchain_stdio.py).
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_priority_ratio_next_tier_cost_removed():
    """#863 Package 2 item 1: the deprecated next_tier_cost() shim is gone.

    Zero live consumers verified in arbitration: kunglao-decide._cheapness_order
    calls priority_ratio.cheapness directly (the banner comment above the shim
    claimed this caller but never matched the code)."""
    assert "next_tier_cost" not in _src("scripts/priority_ratio.py"), (
        "next_tier_cost was retired by 863-d (#863 Package 2, no-backward-compat "
        "policy) — do not resurrect without a new zero-consumer audit")


def test_blind_gate_zero_hits_compat_pair_removed():
    """#863 Package 2 item 2: the narrow #48 zero-hits compat pair is gone.

    The diagnostic routes through the broader _has_env_negative_basis (#56)
    since the env-negative-rule change; the narrow subset (pattern tuple +
    helper) had zero callers and zero test imports (test names mentioning
    zero_hits exercise the broadened basis, not this helper)."""
    src = _src("scripts/blind_gate.py")
    assert "_ZERO_HITS_PATTERNS" not in src
    assert "_has_zero_hits" not in src


def test_references_recall_parse_index_shim_removed():
    """#863 Package 2 item 3: the parse_index back-compat shim is gone.

    Callers consume build_index directly (Index.entries/.scenes); the shim
    had zero callers and zero test references (parse_index_text in
    tools/_lib/index_schema.py is a different symbol)."""
    assert "def parse_index(" not in _src("scripts/references_recall.py")


def test_convergence_check_scan_active_workers_shell_removed():
    """#863 Package 2 item 4: the _scan_active_workers named shell is gone.

    It existed only so test_worktree_marker.py could import it (its own
    docstring said so); the protocol owner is hooks/lib_kunglao
    .scan_active_workers (#444), consumed via _scan_workers. The two marker
    tests now drive _scan_workers directly. hooks/lib_kunglao.py:254's
    "Pre-#444 mirrors" provenance comment and docs/design prose are
    historical statements, deliberately left in place."""
    assert "_scan_active_workers" not in _src("scripts/convergence_check.py")


def test_dispatch_gate_import_failure_is_explicit_not_v0_fallback(monkeypatch):
    """#863 Package 2 item 5 (RED first): with the DISPATCH_RE re-export and
    its local v0 regex fallback retired, a lib_kunglao import failure must
    surface as an explicit (None, reason) — never a silent degrade to
    v0-only parsing (the #444 no-silent-fallback precedent)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_dispatch_gate_863d_probe", ROOT / "hooks" / "dispatch_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def _boom():
        raise ImportError("simulated lib_kunglao outage")
    monkeypatch.setattr(mod, "load_hooks_lib", _boom)
    claim_id, reason = mod._parse_dispatch("[T2 tools=x] claim C-007")
    assert claim_id is None
    assert "lib_kunglao import failed" in reason


def test_dispatch_gate_dispatch_regex_reexport_removed():
    """#863 Package 2 item 5: the compat re-export of the retired v0 regex is
    gone from dispatch_gate, together with its in-module v0 fallback.

    The canonical regex lives in hooks/lib_kunglao.py (retirement-gate
    owner); the gate now fails explicitly when lib_kunglao is unimportable
    (see the import-failure pin above) instead of silently degrading to
    v0-only parsing."""
    src = _src("hooks/dispatch_gate.py")
    assert "DISPATCH_RE" not in src, (
        "the dispatch_gate compat re-export was retired by 863-d — the regex "
        "owner is hooks/lib_kunglao.py; do not resurrect")
    assert "v0-local-fallback" not in src
