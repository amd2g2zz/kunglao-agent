#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI YAML lint — repo-owned so CI breakage reproduces locally (issue #147 P0).

Parses .github/workflows/*.yml with yaml.safe_load and prints any parse
error with line context. Exit 0 = all parse; 1 = at least one broken.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


def main() -> int:
    broken = False
    for p in sorted(WORKFLOWS.glob("*.yml")):
        text = p.read_text(encoding="utf-8")
        try:
            yaml.safe_load(text)
        except yaml.YAMLError as exc:
            broken = True
            mark = getattr(exc, "problem_mark", None)
            line = mark.line + 1 if mark else "?"
            print(f"YAML BROKEN: {p} line {line}: {exc}", file=sys.stderr)
    return 1 if broken else 0


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())


def check_quality_gate_ids() -> bool:
    """#563: every gate id the release workflow names must exist in the
    quality_gates GATES registry — stale numbering fails loudly."""
    import re
    import importlib.util
    wf = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "release-check.yml"
    spec = importlib.util.spec_from_file_location(
        "qg", Path(__file__).resolve().parent.parent / "devkit" / "quality_gates.py")
    qg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qg)
    registry = set(qg.GATES)
    text = wf.read_text(encoding="utf-8") if wf.exists() else ""
    cited = {int(n) for n in re.findall(r"quality_gates\.py\s+((?:\d+\s*)+)", text)
             for n in n.split()} if text else set()
    missing = cited - registry
    if missing:
        print(f"SELF-FAIL: workflow cites gate ids {sorted(missing)} not in GATES "
              f"{sorted(registry)} (stale numbering)")
        return False
    return True
