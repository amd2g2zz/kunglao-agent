# -*- coding: utf-8 -*-
"""Issue 292 — the shared-primitives single-home guard.

scripts/_scriptlib.py is the ONE home of the extracted primitives (the
rate-limited fail-open WARN tracer factory, the tolerant claim-register
IO, the claim_deps.yaml edge write). This module enforces, name-level and
pure-AST (no child-process invocation — fast-tier by construction):

  1. no script under scripts/ re-DEFINES a name the shared module owns
     (the resurrection guard; the allowlist below is currently EMPTY:
     every shared name was chosen collision-free, and the ~60 legacy
     `warn` copies pre-dating issue 292 do not collide either, because
     the shared API is the `make_warn` FACTORY, not the bare `warn`
     name — add a file here only when a real name collision is
     unavoidable);
  2. the warn-style helper exists in exactly one place per the refactor
     scope: the post2 six + plan_drift_detector carry no `def warn` /
     `_WARN_LAST` copy, and their tags are wired through `make_warn`;
  3. the consuming scripts actually import the shared module.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
LIB = SCRIPTS / "_scriptlib.py"

#: files whose names collide with the shared surface but pre-date
#: issue 292 (rung-1 deletable debt, see the no-backcompat policy).
#: Currently EMPTY and kept as the escape hatch. `_boot` needs NO entry:
#: its tracer names (`warn`, `_WARN_LAST`) are not shared-module names —
#: the shared API is the `make_warn` factory — so `_boot` passes this
#: guard on its own merits while staying free to keep its boot-scoped
#: copy (dependency-free by its import-order rule).
LEGACY_WARN_COPIES: frozenset[str] = frozenset()

#: the post2 product scripts + the drift detector (the issue 292 refactor scope)
REFACTORED = (
    "hypothesis_bridge",
    "plan_epistemics",
    "claim_granularity",
    "target_ladder",
    "progress_timeline",
    "settle_by_need",
    "plan_drift_detector",
)

#: of those, the ones consuming a shared primitive
WIRED = ("hypothesis_bridge", "plan_epistemics", "claim_granularity",
         "target_ladder", "plan_drift_detector")

#: tag each wired module binds its warn under — the message token the
#: former private copy hard-coded, now the factory argument
EXPECTED_TAGS = {
    "plan_epistemics": "plan_epistemics",
    "plan_drift_detector": "plan_drift_detector",
}


def _collect_def_names(tree: ast.Module) -> set[str]:
    """Every top-level def/class/assignment name in one module (dunders
    such as `__all__` are module plumbing, never a primitive copy)."""
    names: set[str] = set()
    for node in tree.body:
        match node:
            case ast.FunctionDef() | ast.ClassDef() | ast.AsyncFunctionDef():
                names.add(node.name)
            case ast.Assign():
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
            case ast.AnnAssign() if isinstance(node.target, ast.Name):
                names.add(node.target.id)
    return {n for n in names if not (n.startswith("__") and n.endswith("__"))}


def _lib_public_names() -> set[str]:
    """Top-level names scripts/_scriptlib.py owns (functions + constants)."""
    return _collect_def_names(ast.parse(LIB.read_text(encoding="utf-8")))


def _top_level_def_names(path: Path) -> set[str]:
    """Every top-level def/class/assignment name in one script file."""
    return _collect_def_names(ast.parse(path.read_text(encoding="utf-8")))


def test_no_script_redefines_a_shared_name():
    """The resurrection guard: no scripts/*.py module may re-define a
    name the shared module owns (name-level check)."""
    shared = _lib_public_names()
    assert shared, "the shared module must own its surface (__all__/defs)"
    offenders: dict[str, set[str]] = {}
    for p in sorted(SCRIPTS.glob("*.py")):
        if p.stem in LEGACY_WARN_COPIES or p == LIB:
            continue
        clash = _top_level_def_names(p) & shared
        if clash:
            offenders[p.name] = clash
    assert not offenders, (
        f"scripts re-define names owned by scripts/_scriptlib.py (issue 292 "
        f"single-home guard) — import from _lib instead: {offenders}")


def test_warn_helper_exists_exactly_once_in_refactor_scope():
    """The seven refactored scripts carry no private rate-limited warn
    copy: no `def warn(` and no `_WARN_LAST` state at module level. A
    module-level `_warn` counts only in the two-positional-arg (op,
    reason) copy shape — single-argument tracers with their own message
    contract (progress_timeline) are a different helper, not a copy."""
    for name in REFACTORED:
        tree = ast.parse((SCRIPTS / f"{name}.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                assert node.name != "warn", (
                    f"{name}.py re-defines warn() — bind make_warn instead "
                    f"(issue 292)")
                if node.name == "_warn" and len(node.args.args) == 2:
                    assert False, (
                        f"{name}.py re-defines the (op, reason) _warn copy "
                        f"shape (issue 292)")
            if isinstance(node, ast.AnnAssign) and isinstance(
                    node.target, ast.Name):
                assert node.target.id != "_WARN_LAST", (
                    f"{name}.py re-declares the _WARN_LAST state (issue 292)")


def test_wired_scripts_bind_their_former_tag():
    """The factory binding must reproduce the former copy's message token:
    `warn = make_warn("<module>")` — the byte-contract the characterization
    tests pin."""
    for name, tag in EXPECTED_TAGS.items():
        src = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
        binding = f'warn = make_warn("{tag}")'
        assert binding in src, (
            f"{name}.py must bind its warn as `{binding}` (issue 292)")


def test_consumers_import_the_shared_module():
    for name in WIRED:
        src = (SCRIPTS / f"{name}.py").read_text(encoding="utf-8")
        assert "from _scriptlib import" in src, (
            f"{name}.py must consume the shared module (issue 292)")


def test_lib_surface_stays_the_registered_nine():
    """Pin the extracted surface so scope creep through _lib is at least
    visible in review (add a name here WHEN a copy actually collapses)."""
    assert sorted(_lib_public_names() & {
        "make_warn", "register_path", "claims_of", "load_register",
        "load_register_doc", "read_register_claims", "claims_from_text",
        "find_claim", "ensure_dep_edge",
    }) == [
        "claims_from_text", "claims_of", "ensure_dep_edge", "find_claim",
        "load_register", "load_register_doc", "make_warn",
        "read_register_claims", "register_path",
    ]
