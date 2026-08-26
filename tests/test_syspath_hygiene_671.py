# -*- coding: utf-8 -*-
r"""Issue #671 — hooks/ sys.path.insert hygiene: guard + semantics pins.

Count basis (proposal table): issue body filed 11 sites; the dispatch-time
sweep said 32; the actual census on dev 2b7f946 (this branch's base) is 31
sites / 13 files via grep -rn "sys\.path\.insert" hooks/ — the actual
count governs and the reconciliation is posted to the issue.

Two failure halves pinned here (design D1):
  accumulation — repeated inserts stack equivalent entries;
  reordering   — insert(0) on an already-present entry flips import order
                 (the lib_kunglao ambiguity: pytest's session path already
                 orders hooks before scripts).

Guard model follows tests/test_no_absolute_paths.py (scanner + planted
negative sample); whitelist is one NAMED FILE (the insert authority), not
a directory.

Run: uv run python -m pytest tests/test_syspath_hygiene_671.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks"

INSERT_RE = re.compile(r"sys\s*\.\s*path\s*\.\s*insert")
# The insert authority itself — the ONLY file allowed a bare insert.
EXEMPT_NAMES = ("_path_hygiene.py",)


def scan(root: Path) -> list[str]:
    """Return '<relpath>:<line>' bare sys.path.insert violations under root."""
    out: list[str] = []
    for py in sorted(root.rglob("*.py")):
        rel = py.relative_to(root).as_posix()
        if py.name in EXEMPT_NAMES:
            continue
        text = py.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            if INSERT_RE.search(line):
                out.append(f"{rel}:{i}")
    return out


def _safe_resolve(p: str) -> Path:
    try:
        return Path(p).resolve()
    except OSError:  # pragma: no cover - unresolved exotic entry
        return Path(p)


def _resolved_indices(target) -> list[int]:
    """Indices of sys.path entries resolving equal to target."""
    norm = Path(str(target)).resolve()
    return [i for i, p in enumerate(sys.path) if _safe_resolve(p) == norm]


@pytest.fixture(autouse=True)
def _restore_sys_path():
    """The hygiene suite must not itself be a polluter: snapshot/restore."""
    snap = list(sys.path)
    yield
    sys.path[:] = snap


@pytest.fixture
def hygiene():
    """Fresh _path_hygiene with a cleared ledger (test isolation)."""
    import _path_hygiene as ph
    saved = set(ph._ENSURED)
    ph._ENSURED.clear()
    yield ph
    ph._ENSURED.clear()
    ph._ENSURED.update(saved)


# ---------- the live guard ----------

def test_hooks_tree_has_no_bare_sys_path_insert():
    """Any PR that lands a bare sys.path.insert in hooks/ goes red here
    (#671 acceptance at adoption: 31 sites -> 0)."""
    violations = scan(HOOKS)
    assert not violations, (
        f"{len(violations)} bare sys.path.insert site(s) in hooks/ — "
        "route membership through hooks/_path_hygiene.py "
        "(on_path / scripts_on_path / ensure_on_path / ensure_scripts_path). "
        f"Full list: {violations}")


def test_scanner_flags_planted_violation(tmp_path: Path):
    """Negative sample: the guard must provably go red."""
    bad = tmp_path / "planted_hook.py"
    bad.write_text("import sys\nsys.path.insert(0, 'x')\n", encoding="utf-8")
    assert scan(tmp_path) == ["planted_hook.py:2"]


def test_scanner_skips_whitelist_authority(tmp_path: Path):
    """Exactly one whitelist entry: the authority module's own name."""
    ok = tmp_path / "_path_hygiene.py"
    ok.write_text(
        "import sys\nsys.path.insert(0, 'authorized')\n", encoding="utf-8")
    assert scan(tmp_path) == []


def test_scanner_catches_whitespace_variant(tmp_path: Path):
    """Obfuscated spacing must not evade the guard."""
    bad = tmp_path / "sneaky.py"
    bad.write_text("sys . path . insert(0, 'x')\n", encoding="utf-8")
    assert scan(tmp_path) == ["sneaky.py:1"]


# ---------- semantics: scoped membership ----------

def test_on_path_inserts_then_pops(tmp_path: Path, hygiene):
    target = tmp_path / "never_on_path"
    snap = list(sys.path)
    with hygiene.on_path(target):
        assert sys.path[0] == str(target)
    assert sys.path == snap


def test_on_path_pops_on_exception(tmp_path: Path, hygiene):
    """try/finally: cleanup survives a raising body (callers rely on
    except-paths around sibling imports)."""
    target = tmp_path / "boom_dir"
    snap = list(sys.path)
    with pytest.raises(RuntimeError):
        with hygiene.on_path(target):
            raise RuntimeError("boom")
    assert sys.path == snap


def test_on_path_present_target_untouched(tmp_path: Path, hygiene):
    """Already-present target: no insert, no pop, no position change —
    the anti-reorder half of the fix."""
    mid = tmp_path / "mid_list"
    sys.path.append(str(mid))
    snap = list(sys.path)
    idx = sys.path.index(str(mid))
    with hygiene.on_path(mid):
        assert sys.path == snap
    assert sys.path == snap
    assert sys.path.index(str(mid)) == idx


def test_scripts_on_path_is_scripts_scoped(hygiene):
    snap = list(sys.path)
    with hygiene.scripts_on_path():
        assert _resolved_indices(hygiene.SCRIPTS_DIR), (
            "scripts/ must be importable inside the block")
    assert sys.path == snap


# ---------- semantics: idempotent ensure ----------

def test_ensure_idempotent_single_entry(hygiene):
    """3 calls -> exactly ONE resolved-equal entry (insert branch: entry
    removed first so the ledger-then-insert path is exercised)."""
    sys.path[:] = [
        p for p in sys.path
        if _safe_resolve(p) != Path(str(hygiene.SCRIPTS_DIR)).resolve()
    ]
    assert not _resolved_indices(hygiene.SCRIPTS_DIR)
    hygiene.ensure_scripts_path()
    hygiene.ensure_scripts_path()
    hygiene.ensure_scripts_path()
    assert len(_resolved_indices(hygiene.SCRIPTS_DIR)) == 1


def test_ensure_present_target_position_stable(tmp_path: Path, hygiene):
    """Pre-present target stays where it is — ensure must NOT flip a
    session path that already orders hooks before scripts."""
    pre = tmp_path / "pre_present"
    sys.path.append(str(pre))
    idx = sys.path.index(str(pre))
    hygiene.ensure_on_path(pre)
    assert sys.path.index(str(pre)) == idx


def test_ensure_resolves_equivalent_spellings(tmp_path: Path, hygiene):
    """Accumulation fix: a differently-spelled equivalent entry counts as
    present (the in-tree literal checks missed this)."""
    real = tmp_path / "equiv"
    real.mkdir()
    spelled = str(tmp_path / "sub_dir" / ".." / "equiv")
    sys.path.append(spelled)
    hygiene.ensure_on_path(real)
    assert len(_resolved_indices(real)) == 1, (
        "equivalent spelling must not stack a second entry")


def test_ensure_front_moves_without_duplicate(tmp_path: Path, hygiene):
    """#568-faithful move-to-front: remove any copy, insert once at 0."""
    front = tmp_path / "front_target"
    sys.path.append(str(front))
    hygiene.ensure_on_path(front, front=True)
    assert sys.path[0] == str(front)
    assert len(_resolved_indices(front)) == 1


# ---------- semantics: a real hook entry point ----------

def test_real_hook_entry_leaves_sys_path_unchanged(tmp_path: Path, hygiene):
    """End-to-end pin: completion_gate._kunglao_active (a migrated
    function-scoped site) imports scripts/hook_activation inside a with —
    sys.path must equal its pre-call snapshot afterwards.

    The hook module is loaded BY PATH under a unique name: a session-wide
    `import completion_gate` can hit a scripts/-side copy another test
    registered in sys.modules (the very ambiguity this change fights).
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "cg_hygiene_671", HOOKS / "completion_gate.py")
    cg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cg)
    assert Path(cg.__file__).resolve().parent.name == "hooks"
    (tmp_path / ".hook_state.json").write_text("{}", encoding="utf-8")
    snap = list(sys.path)
    cg._kunglao_active(tmp_path)
    assert sys.path == snap
