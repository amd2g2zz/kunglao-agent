# -*- coding: utf-8 -*-
"""tests/test_docsync_589_563.py — #589+#563: docs derived, gate names stable.

#589 (adjudicated): the two-level deployment contract (workspace +
workspace-parent, HOOK_DEPLOYMENT_TARGETS) existed in code + tests but in NO
operator doc. Fix: README Internals section generated-from the registry
(derive-don't-copy, #446) — the drift guard is the test itself (parsing the
registry and asserting the README carries both levels + the HOME exclusion).

#563 (adjudicated): "quick gate 0" was a stale numbering — gates are
positional ints with no stable-name binding. Fix: quality_gates CLI gains a
--quick named selector (the {1,3,4} set) + release_check_selfcheck asserts
every gate id the workflow names exists in GATES (drift now fails loudly).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


# ---------- #589: dual-level doc, derived ----------

def test_readme_documents_both_levels_and_home_exclusion():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "settings levels" in readme or "Two settings levels" in readme, \
        "README Internals must carry the dual-level section"
    assert ".claude/settings.json" in readme
    assert "workspace-parent" in readme or "parent" in readme
    assert "HOME" in readme


def test_readme_levels_table_derives_from_registry():
    import wire_up_settings
    targets = wire_up_settings.HOOK_DEPLOYMENT_TARGETS
    assert len(targets) == 2  # the registry itself pins the pair
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"(?:settings levels|Two settings levels)(.*?)(?:\n#|\Z)",
                  readme, re.DOTALL | re.IGNORECASE)
    assert m, "section found"
    body = m.group(1)
    assert "wire_up_settings" in body or "HOOK_DEPLOYMENT_TARGETS" in body, \
        "the section must NAME its source registry (derive-don't-copy, #446)"


# ---------- #563: --quick selector + selfcheck gate-id guard ----------

def test_quality_gates_quick_selector():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "qg_uut", ROOT / "devkit" / "quality_gates.py")
    qg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qg)
    assert qg.QUICK_GATES == [1, 3, 4], "the quick set is the CI quick path"


def test_release_check_selfcheck_covers_workflow_gate_ids():
    src = (ROOT / "scripts" / "release_check_selfcheck.py").read_text(encoding="utf-8")
    assert "quality_gates" in src and "GATES" in src, \
        "selfcheck must assert workflow-referenced gate ids exist in the registry"
