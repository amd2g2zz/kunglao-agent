# -*- coding: utf-8 -*-
"""kunglao_agent_cli — thin console-script wrappers over the scripts/ entry
points (issue #416 entry-point registration).

#416: the kunglao CLI family existed only as `python scripts/<file>.py`
invocations — pyproject.toml had no [project.scripts], so every doc
reference to bare `kunglao ...` (skills/analysis/SKILL.md, skills/init/
SKILL.md) had no backing surface and discovery-by-archaeology failed.

These wrappers ONLY register entry points; they carry zero business logic.
Hyphenated filenames (kunglao-init.py) are illegal module paths, so every
target is loaded from its file path via importlib (see load_script_module).
Each wrapper mirrors its target's own `__main__` guard — the UTF-8 boot the
script performs when run directly — so the console-script face is
behavior-identical to `python scripts/<file>.py`. The registered callables
return the target's main() rc; the console-script shim turns that into the
process exit code.

Registered face (pyproject [project.scripts]):
    kunglao            -> kunglao.py (router: 9 subcommands)
    kunglao-init       -> kunglao-init.py
    kunglao-verify     -> kunglao-verify.py
    kunglao-upgrade    -> kunglao_upgrade.py (no hyphenated file exists)
    heartbeat-tick     -> heartbeat_tick.py
    convergence-check  -> convergence_check.py

Entry points resolve against a repository checkout (the parent of this
package plus scripts/); this is the supported install shape (`uv sync` in
the repo root creates an editable install).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

__all__ = ["load_script_module", "scripts_dir"]


def scripts_dir() -> Path:
    """Locate the repo's scripts/ directory from this package's location."""
    candidate = Path(__file__).resolve().parent.parent / "scripts"
    if candidate.is_dir():
        return candidate
    raise ImportError(
        "kunglao_agent_cli: scripts/ not found next to the package "
        f"(looked at {candidate}); entry points require a repository "
        "checkout (uv sync in the repo root)")


def load_script_module(filename: str):
    """Import a scripts/ entry file by filename and return its module.

    scripts/ is inserted on sys.path first so the target's own top-level
    sibling imports (kunglao_verify, _entry, _boot, _hooks_path, ...) keep
    resolving exactly as when the file is run directly. Modules are cached
    in sys.modules under a deterministic package-private name, so repeated
    loads (and tests monkeypatching the target) share one module object.
    Loading never runs the target: every entry script gates execution behind
    its __main__ guard (#370 contract).
    """
    scripts = scripts_dir()
    path = scripts / filename
    if not path.is_file():
        raise ImportError(f"kunglao_agent_cli: entry script not found: {path}")
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    modname = "kunglao_agent_cli._target_" + Path(filename).stem.replace("-", "_")
    if modname in sys.modules:
        return sys.modules[modname]
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"kunglao_agent_cli: cannot build import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[modname] = module
    spec.loader.exec_module(module)
    return module
