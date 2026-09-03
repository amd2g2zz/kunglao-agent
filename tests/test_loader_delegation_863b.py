# -*- coding: utf-8 -*-
"""#863 Family B — loader-prologue delegation contract (enforcement test).

Before: ~22 `spec_from_file_location` loader prologues (issue table: 21,
5 byte-identical) were copied across scripts/, hooks/ and devkit/ —
enforcement-by-copying. After: ``hooks/_path_hygiene.load_module_by_path``
is the ONE loader (the #671 by-path authority owns path-based loading);
every former prologue delegates, and the ``importlib.util.
spec_from_file_location`` call itself is CONFINED to the util plus the two
#671 self-bootstrap fallbacks (``hooks/dispatch_gate.py`` and
``hooks/lib_kunglao.py`` bootstrap ``_path_hygiene`` itself when hooks/ is
not importable — code that loads the loader cannot call the loader).

Mirrors the Family A rewrite shape (tests/test_utf8_stdout_convention.py):
a marker-based delegation assert + a mechanical confinement scan + util
contract pins. Behavioral equivalence of the worker-liveness protocol
consumers stays pinned by tests/test_worker_liveness_protocol.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The util + the physically-irreducible #671 bootstraps. Each non-util entry
# must state WHY it cannot delegate (same discipline as the #444 ALLOWLIST).
ALLOWED_SPEC_SITES = {
    "hooks/_path_hygiene.py":
        "THE util — the single spec_from_file_location definition "
        "(load_module_by_path); load_hooks_lib delegates to it",
    "hooks/dispatch_gate.py":
        "#671 self-bootstrap: loads _path_hygiene ITSELF by path when "
        "hooks/ is not importable (test subprocess-driver pattern) — the "
        "bootstrap of the loader cannot route through the loader",
    "hooks/lib_kunglao.py":
        "#671 self-bootstrap: same bootstrap-of-the-loader exception as "
        "dispatch_gate",
}


def _repo_python_files():
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith("tests/"):        # fixtures may rebuild shapes freely
            continue
        if rel.startswith((".git", ".review", "openspec/", ".worktrees",
                           ".venv/", "venv/")):  # deps/virtualenvs, not repo code
            continue
        yield p, rel


# --------------------------------------------------------------------------
# confinement: the importlib.util.spec_from_file_location call lives in
# exactly the allowed sites — every former prologue copy is gone.
# --------------------------------------------------------------------------

def test_spec_from_file_location_confined():
    offenders = []
    for p, rel in _repo_python_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        if "spec_from_file_location" in text and rel not in ALLOWED_SPEC_SITES:
            offenders.append(rel)
    assert offenders == [], (
        "loader prologues must delegate to hooks/_path_hygiene."
        "load_module_by_path (#863 Family B); remaining "
        "spec_from_file_location sites: "
        f"{sorted(offenders)}. Allowed: {sorted(ALLOWED_SPEC_SITES)}"
    )


# --------------------------------------------------------------------------
# delegation wiring: every former copy site references the canonical loader
# (static half; the behavioral half is the existing protocol test suite).
# --------------------------------------------------------------------------

WIRING = {
    # scripts-side consumers of hooks/lib_kunglao.py (the byte-identical
    # five + their exists-check variants) route through load_hooks_lib:
    "scripts/backtrack_gate.py": "load_hooks_lib",
    "scripts/convergence_check.py": "load_hooks_lib",
    "scripts/event_taxonomy.py": "load_hooks_lib",
    # external_kicker hosts TWO former prologues: the hooks-lib protocol
    # loader and the should_kick drift-twin loader.
    "scripts/external_kicker.py": ("load_hooks_lib", "load_module_by_path"),
    "scripts/kunglao_status.py": "load_hooks_lib",
    "scripts/lib_kunglao.py": "load_hooks_lib",
    "scripts/progress_report.py": "load_hooks_lib",
    "scripts/reconcile_workers.py": "load_hooks_lib",
    # generic by-path loads route through the util:
    "scripts/references_recall.py": "load_module_by_path",
    "scripts/heartbeat.py": "load_module_by_path",
    "scripts/kunglao.py": "load_module_by_path",
    "scripts/kunglao_upgrade.py": "load_module_by_path",
    "scripts/release_check_selfcheck.py": "load_module_by_path",
    # hooks-side consumers (same-dir import, no plumbing):
    "hooks/completion_gate.py": "load_module_by_path",
    "hooks/state_anchor.py": "load_module_by_path",
    "hooks/worker_budget.py": "load_module_by_path",
    "hooks/recall_inject.py": "load_module_by_path",
    # devkit consumers:
    "devkit/doc_sync.py": "load_module_by_path",
    "devkit/governance_binding.py": "load_module_by_path",
    # the util itself must exist where we say it is:
    "hooks/_path_hygiene.py": "load_module_by_path",
}


def test_loader_wiring_is_delegated():
    missing = {}
    for rel, markers in WIRING.items():
        required = (markers,) if isinstance(markers, str) else markers
        path = ROOT / rel
        if not path.exists():
            missing[rel] = "<file gone>"
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker in required:
            if marker not in text:
                missing[rel] = marker
    assert missing == {}, (
        "every former loader-prologue copy must reference the canonical "
        f"loader (#863 Family B); missing wiring: {missing}"
    )


# --------------------------------------------------------------------------
# util contract pins (get-or-create semantics the former prologues relied on)
# --------------------------------------------------------------------------

def _load_util():
    sys.path.insert(0, str(ROOT / "hooks"))  # noqa: noqa — test-only, restored below
    try:
        import _path_hygiene
        return _path_hygiene
    finally:
        sys.path.remove(str(ROOT / "hooks"))


def test_load_module_by_path_caches_single_instance(tmp_path):
    """Same name+path loaded twice returns ONE module object and executes
    the module body exactly once (get-or-create contract)."""
    ph = _load_util()
    mod_path = tmp_path / "probe_mod.py"
    mod_path.write_text(
        "TOUCHED = []\nTOUCHED.append('exec')\nVALUE = 41 + 1\n",
        encoding="utf-8")
    name = "loader_probe_863b"
    sys.modules.pop(name, None)
    try:
        first = ph.load_module_by_path(name, mod_path)
        second = ph.load_module_by_path(name, mod_path)
        assert first is second
        assert first.VALUE == 42
        assert first.TOUCHED == ["exec"], (
            "module body must execute exactly once per process "
            "(get-or-create, not re-exec)")
        assert sys.modules[name] is first
    finally:
        sys.modules.pop(name, None)


def test_load_module_by_path_missing_file_raises(tmp_path):
    """No silent fallback: a missing file surfaces the loader error (callers
    keep their own fail-open or loud-missing policies)."""
    ph = _load_util()
    try:
        ph.load_module_by_path("loader_probe_missing_863b",
                               tmp_path / "no_such_mod.py")
    except Exception as exc:  # noqa: BLE001 — pin the raise, not the type
        assert isinstance(exc, (FileNotFoundError, AttributeError)), (
            f"unexpected error shape: {exc!r}")
    else:
        raise AssertionError("missing file must raise, not return")


def test_load_hooks_lib_delegates_to_util():
    """load_hooks_lib keeps its #770 contract: returns the hooks twin loaded
    by path under lib_kunglao_hooks, registered in sys.modules."""
    ph = _load_util()
    lib = ph.load_hooks_lib()
    assert hasattr(lib, "parse_worker_status")
    assert sys.modules.get("lib_kunglao_hooks") is lib
    source = (ROOT / "hooks" / "_path_hygiene.py").read_text(encoding="utf-8")
    body = source.split("def load_hooks_lib", 1)[1]
    assert "spec_from_file_location" not in body.split("\ndef ", 1)[0], (
        "load_hooks_lib must DELEGATE to load_module_by_path, not keep its "
        "own importlib prologue (#863 Family B)")
