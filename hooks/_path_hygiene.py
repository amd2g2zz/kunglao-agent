# -*- coding: utf-8 -*-
r"""hooks/_path_hygiene.py — the single sys.path.insert authority (#671).

Why this module exists: 31 bare `sys.path.insert(0, <dir>)` bootstraps
across hooks/ (census on dev 2b7f946; the issue filed 11, a later sweep
said 32 — the actual count governs) never cleaned up. Harmless for the
short-lived hook subprocess of production; in a long pytest session every
entry persists, and each insert(0) can REORDER resolution of ambiguous
names (hooks/ and scripts/ both ship lib_kunglao.py) — the observed
`ImportError: cannot import name scan_active_workers` cascade.

Two failure halves, two APIs (design D1):

  accumulation -> ensure_on_path: one insert per resolved target per
                  process (ledger), already-present entries left in place;
  reordering   -> on_path: scoped membership that NEVER touches an
                  already-present entry (no insert, no pop, no move) and
                  removes exactly its own entry on exit.

This file is the ONLY hooks/ file permitted a bare sys.path.insert —
enforced by tests/test_syspath_hygiene_671.py.

Import contract (design D3): callers import this module with hooks/ already
on sys.path — true for hook subprocesses (script dir auto-prepended),
pytest (pytest.ini pythonpath), and by-path shims executed inside a pytest
session.

Run: uv run python -m pytest tests/test_syspath_hygiene_671.py -q
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Union

PathLike = Union[str, Path]

_HOOKS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = _HOOKS_DIR.parent / "scripts"

# Process-wide dedupe ledger: resolved targets ensure_on_path has already
# placed (or found) on sys.path — "幂等单次 insert，进程内去重" (#671).
_ENSURED: set = set()


def _norm(target: PathLike) -> str:
    """Resolve to a canonical string so equivalent spellings compare equal
    (the in-tree literal checks missed these — entries stacked)."""
    try:
        return str(Path(target).resolve())
    except OSError:  # pragma: no cover - exotic path shapes
        return str(target)


def _indices_of(norm: str) -> list:
    return [i for i, entry in enumerate(sys.path) if _norm(entry) == norm]


def _on_sys_path(norm: str) -> bool:
    return any(_norm(entry) == norm for entry in sys.path)


@contextmanager
def on_path(target: PathLike) -> Iterator[None]:
    """Scoped sys.path membership: import siblings inside the block.

    Already-present target (resolved-equal entry anywhere on sys.path):
    the block is a no-op for sys.path — no insert, no pop, no reorder.
    Absent target: insert(0) on enter; on exit remove EXACTLY that entry
    (position [0] if still ours, else the first resolved-equal match).
    Nested same-target blocks are safe (inner sees present -> no-op).
    """
    norm = _norm(target)
    if _on_sys_path(norm):
        yield
        return
    sys.path.insert(0, str(target))
    try:
        yield
    finally:
        # Best-effort exact-entry removal — cleanup never raises past the
        # caller's own error handling (hooks wrap these calls in try/except).
        if sys.path and _norm(sys.path[0]) == norm:
            sys.path.pop(0)
        else:
            for i in _indices_of(norm):
                del sys.path[i]
                break


@contextmanager
def scripts_on_path() -> Iterator[None]:
    """on_path(SKILL_DIR/scripts) — the dominant sibling-import target."""
    with on_path(SCRIPTS_DIR):
        yield


def ensure_on_path(target: PathLike, *, front: bool = False) -> None:
    """Idempotent process-wide membership for module-level bootstraps.

    front=False (default): first call for an absent target inserts once and
    records it; a target already on sys.path is LEFT WHERE IT IS (position
    preserved — reordering a session path that already orders hooks before
    scripts is the other half of the #671 bug). Ledger hits return at once.

    front=True: #568-faithful move-to-front (worker_budget's order-robust
    bootstrap): remove any resolved-equal copy, insert once at [0]. Use
    ONLY where order is load-bearing; every other call site must stay
    front=False.
    """
    norm = _norm(target)
    if front:
        if sys.path and _norm(sys.path[0]) == norm:
            _ENSURED.add(norm)
            return
        for i in _indices_of(norm):
            del sys.path[i]
            break
        sys.path.insert(0, str(target))
        _ENSURED.add(norm)
        return
    if norm in _ENSURED:
        return
    if not _on_sys_path(norm):
        sys.path.insert(0, str(target))
    _ENSURED.add(norm)


def ensure_scripts_path() -> None:
    """ensure_on_path(SKILL_DIR/scripts) — module-level long-lived form."""
    ensure_on_path(SCRIPTS_DIR)


def collision_order_inverted(path: list[str] | None = None) -> bool:
    """#770 regression probe: is any hooks/ dir ranked above any scripts/
    dir? Under that ordering the three shared-name twins
    (completion_gate / heartbeat_touch / lib_kunglao) resolve to their
    hooks side on a bare import — the exact shadow the ini ordering exists
    to prevent. Pure predicate over a path list; no mutation."""
    entries = sys.path if path is None else path
    hooks_rank = [i for i, p in enumerate(entries)
                  if p and Path(p).name == "hooks"]
    scripts_rank = [i for i, p in enumerate(entries)
                    if p and Path(p).name == "scripts"]
    if not hooks_rank or not scripts_rank:
        return False
    return min(hooks_rank) < min(scripts_rank)


def load_hooks_lib():
    """Canonical by-path loader for the hooks twin of lib_kunglao (#770).

    A bare `import lib_kunglao` resolves by sys.path ORDER, so an ambient
    scripts/ insert anywhere earlier in the session re-binds every lazy
    consumer to the scripts twin (which lacks the worker-status protocol).
    Loading by resolved path under an isolated module name is
    order-independent and cached across call sites."""
    name = "lib_kunglao_hooks"
    m = sys.modules.get(name)
    if m is not None:
        return m
    import importlib.util as _ilu
    spec = _ilu.spec_from_file_location(
        name, Path(__file__).resolve().parent / "lib_kunglao.py")
    m = _ilu.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m
