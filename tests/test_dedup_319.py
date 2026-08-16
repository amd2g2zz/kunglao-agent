# -*- coding: utf-8 -*-
"""tests/test_dedup_319.py — issue #319 merge/dedup batch: mechanical invariant locks.

Four audit-confirmed duplicate/fork structures, each locked by a mechanical
invariant so the dedup state cannot regress:

1. templates/ top level carries no duplicate of templates/state/ — the six
   state templates have exactly one source (templates/state/), and docs
   reference that single source.
2. Exactly one pre-commit gate under .claude/ — the tracked HMAC template
   (.claude/git-hooks/pre-commit); the legacy .claude/hooks/pre-commit is
   retired, AGENTS.md names the single gate, and no file references the
   legacy path.
3. docs/ has no design/refactor fork — docs/refactor/ retired (#263);
   docs/README.md layout table matches the actual directory set; live
   specs/ carry no dangling docs/refactor/ references.
4. The structured {"error","exit_code"} stderr emitter has a single source
   in tools/static — common.error; die_probe reuses it instead of its own
   _error() copy (issue #319 names exactly this pair; the other static CLIs
   keep their local emitters by the #278 absorption contract and are out of
   scope here).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STATE_TEMPLATE_NAMES = (
    "blocker.md",
    "claim-register.yaml",
    "claim_deps.yaml",
    "failure-registry.yaml",
    "task-oracle.yaml",
    "task_spec.yaml",
)

EMITTER_STMT = 'print(json.dumps({"error": message, "exit_code": code}), file=sys.stderr)'


# ---------------------------------------------------------------------
# 1. templates: single source in templates/state/
# ---------------------------------------------------------------------

def test_state_templates_are_the_single_source():
    state = ROOT / "templates" / "state"
    top = ROOT / "templates"
    for name in STATE_TEMPLATE_NAMES:
        assert (state / name).is_file(), f"templates/state/{name} missing"
        assert not (top / name).exists(), (
            f"templates/{name} duplicates templates/state/{name} — "
            f"delete the top-level copy")


def test_docs_reference_state_template_paths_only():
    offenders = []
    for doc in (ROOT / "docs").rglob("*.md"):
        text = doc.read_text(encoding="utf-8")
        for name in STATE_TEMPLATE_NAMES:
            for m in re.finditer(rf"templates/(?:[\w-]+/)*{re.escape(name)}", text):
                if not m.group(0).startswith("templates/state/"):
                    offenders.append(f"{doc.relative_to(ROOT)} -> {m.group(0)}")
    assert not offenders, (
        "docs must reference the single template source templates/state/:\n"
        + "\n".join(offenders))


# ---------------------------------------------------------------------
# 2. single pre-commit gate
# ---------------------------------------------------------------------

def test_single_tracked_precommit_gate():
    assert not (ROOT / ".claude" / "hooks" / "pre-commit").exists(), (
        "legacy .claude/hooks/pre-commit (3-review-file gate) must stay deleted")
    gates = sorted(p.relative_to(ROOT) for p in ROOT.glob(".claude/**/pre-commit"))
    assert gates == [Path(".claude") / "git-hooks" / "pre-commit"], (
        f"exactly one tracked gate expected, found: {gates}")
    hook = (ROOT / ".claude" / "git-hooks" / "pre-commit").read_text(encoding="utf-8")
    assert "scripts/review_gate.py" in hook


def test_agents_md_confirms_the_single_gate():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert ".claude/git-hooks/pre-commit" in text, (
        "AGENTS.md must name the single gate source (tracked template + install target)")


def test_no_reference_to_legacy_precommit_path():
    offenders = []
    self_file = Path(__file__).resolve()
    for p in ROOT.rglob("*"):
        if not p.is_file() or ".git" in p.parts or ".review-gate" in p.parts:
            continue  # runtime dirs (.git, review-gate evidence) are not repo content
        if p.resolve() == self_file:
            continue  # this test states the prohibition itself
        if p.suffix not in (".md", ".py", ".yaml", ".txt", ".sh", ".tmpl"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if ".claude/hooks/pre-commit" in text:
            offenders.append(str(p.relative_to(ROOT)))
    assert not offenders, (
        "no file may reference the retired .claude/hooks/pre-commit path:\n"
        + "\n".join(offenders))


# ---------------------------------------------------------------------
# 3. docs tree: no design/refactor fork
# ---------------------------------------------------------------------

def test_docs_single_design_tree():
    assert not (ROOT / "docs" / "refactor").exists(), (
        "docs/refactor/ retired in #263 — docs/design/ is the single design tree")
    # #355: historical design docs moved under docs/design/archive/
    for name in ("archive/design-spec.md", "archive/module-design.md",
                 "loop-engineering.md"):
        assert (ROOT / "docs" / "design" / name).is_file()


def test_docs_readme_layout_matches_actual_dirs():
    readme = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    actual = {p.name for p in (ROOT / "docs").iterdir() if p.is_dir()}
    listed = set(re.findall(r"\| `([\w-]+)/` \|", readme))
    assert listed == actual, (
        f"docs/README.md layout table drift: listed={sorted(listed)} "
        f"actual={sorted(actual)}")


def test_specs_carry_no_dangling_docs_refactor_refs():
    offenders = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "specs").rglob("*.md")
        if "docs/refactor/" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        "live specs must not reference the retired docs/refactor/ tree:\n"
        + "\n".join(offenders))


# ---------------------------------------------------------------------
# 4. single error emitter: common.error reused by die_probe
# ---------------------------------------------------------------------

def test_error_emitter_single_source_in_common():
    common = (ROOT / "tools" / "static" / "common.py").read_text(encoding="utf-8")
    die = (ROOT / "tools" / "static" / "die_probe.py").read_text(encoding="utf-8")
    assert EMITTER_STMT in common, "common.error must stay the single emitter"
    assert EMITTER_STMT not in die, (
        "die_probe must reuse common.error instead of re-printing the emitter")
    assert "def _error(" not in die, "die_probe must not define its own _error()"
    assert re.search(r"^from common import error\b", die, re.M), (
        "die_probe must import the shared emitter from common")


def test_die_probe_error_output_keeps_structured_shape():
    """Behavior lock: die_probe's error path still emits {"error","exit_code"}
    JSON on stderr with exit 2 after reusing common.error."""
    r = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "static" / "die_probe.py"),
         "--binary", "definitely-missing.exe"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=60,
    )
    assert r.returncode == 2
    err = json.loads(r.stderr)
    assert set(err) == {"error", "exit_code"}
    assert err["exit_code"] == 2
