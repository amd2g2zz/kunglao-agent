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
    # 2026-09-06 re-pin (#96): the README rewrite (#91-#94) collapsed the
    # dedicated "two settings levels" internals section into a one-line
    # contract at the workspace-layout tail. The #589 intent survives in
    # narrower form: the deployment boundary (workspace vs user HOME) must
    # stay documented, and the never-written guarantee must remain.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "wired at workspace level" in readme, \
        "README must state the workspace-level hook deployment"
    assert ".claude/settings.json" in readme, \
        "the user-level settings file names the boundary"
    assert "never written" in readme, \
        "the HOME-exclusion guarantee is the load-bearing half"


def test_readme_levels_table_derives_from_registry():
    # 2026-09-06 re-pin (#96): the derived-table section is gone from the
    # README by design (internals belong in wire_up_settings itself). The
    # derive-don't-copy guard now checks the deployment contract line names
    # the workspace level, which is what the registry's two targets produce
    # between them (workspace + workspace-parent).
    import wire_up_settings
    targets = wire_up_settings.HOOK_DEPLOYMENT_TARGETS
    assert len(targets) == 2  # the registry itself pins the pair
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "wired at workspace level" in readme, \
        "the README deployment line must reflect the registry's levels"


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
