#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""subagent_review.py — Gate 5 (Subagent Review / Maker-Checker) (#462).

Issue evidence: the 3-element subagent contract (plan-to-execute /
state-sync / tool-discovery + no-self-invention) is enforced for
kunglao-worker but is missing from the FIVE specialist agents
(ghidra-light / go-symbols / floss-filter / pefile-signature /
verdict-scorer). Specialists are the long-running, high-blast-radius
agents — exactly the ones that need the contract.

Local-pre-commit mechanical enforcement:
  - if the staged change touches scripts/ / hooks/ / docs/ / tests/,
    there MUST be at least one .subagent-review/*.json in the working
    tree (uncommitted is fine — the review is in-flight evidence)
  - the JSON's required fields must all be present
  - the `verified_by` field must NOT be the orchestrator's own
    handle — that's the maker-checker anti-self-stamp rule
  - each `tools_used` citation must RESOLVE (#493): a citation that
    resolves nowhere is a self-invention signal — the field-incident
    replay showed a 5-field-complete review could still cite the
    hand-written scripts/decompile_funcs_headless.py driver and pass

When the staged change does NOT touch domain paths (e.g. pure
pyproject / openspec / devkit scaffolding), Gate 5 is N/A — passes
trivially. This keeps the rule targeted: we only enforce it where
subagent delegation is the natural work shape.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Domain paths that warrant subagent review. Matched as a prefix on the
# changed-file path; one match → Gate 5 enforces, no match → Gate 5 N/A.
DOMAIN_PREFIXES = (
    "scripts/",
    "hooks/",
    "docs/",
    "tests/",
    "references/",
    "skills/",
)

# Required fields in .subagent-review/*.json
REQUIRED_FIELDS = (
    "agent",
    "plan",
    "status_sync",
    "tools_used",
    "verified_by",
)

# Forbidden values of verified_by — the orchestrator's own handle must
# not self-stamp. The full list lives in .claude/settings.json; this
# substring list catches the common cases without re-reading the file.
SELF_VERIFIERS = (
    "kunglao-agent",
    "main",
    "anthropic",
    "claude",
)

# #493 — tools_used resolvability. Legal resolution classes:
#   (a) scripts/re/** — the workspace RE-tool namespace deployed per
#       engagement (three-point check #1 in agents/*.md); never present
#       in the skill repo itself, so trusted by prefix;
#   (b) a bare logical name registered in tools/_INDEX.yaml;
#   (c) a real file under scripts/ / tools/ / references/ (registered
#       toolshelf + skill CLIs + reference docs), `#anchor` suffix
#       allowed — EXCEPT on the index itself: tools/_INDEX.yaml#<name>
#       resolves only when <name> is a REGISTERED tool (#493 LOW patch).
WORKSPACE_TOOL_NAMESPACE = "scripts/re/"
RESOLVABLE_ROOTS = ("scripts/", "tools/", "references/")
INDEX_CITATION_BASE = "tools/_INDEX.yaml"


def _yaml_key_names(path: Path, key: str) -> set[str] | None:
    """Names under `<key>:` of a yaml index file; None = missing or
    unreadable (caller decides the fail-closed direction)."""
    if not path.is_file():
        return None
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — unreadable index = no names
        return None
    items = data.get(key) if isinstance(data, dict) else None
    names: set[str] = set()
    for entry in items or []:
        if isinstance(entry, dict) and entry.get("name"):
            names.add(str(entry["name"]))
    return names


def _index_tool_names(repo_root: Path) -> set[str]:
    """Registered logical tool names from tools/_INDEX.yaml, plus the
    ext catalog names from tools/_INDEX.ext.yaml (#476 — a review may
    cite an ext capability by its logical name). A missing or broken
    INTERNAL index fails CLOSED toward strict: the empty set makes every
    bare name unresolvable — the gate gets stricter, never looser. A
    broken/absent EXT file drops only the ext names: internal entries
    remain verifiable, so strictness never depends on the ext catalog
    (ambiguity between the two sets is prevented at generation time by
    tools/ext-scan.py's collision guard and re-checked by Gate 7)."""
    internal = _yaml_key_names(repo_root / "tools" / "_INDEX.yaml", "tools")
    if internal is None:
        return set()
    ext = _yaml_key_names(repo_root / "tools" / "_INDEX.ext.yaml", "ext")
    return internal | (ext or set())


def _tool_resolves(entry: object, repo_root: Path) -> bool:
    """True iff a tools_used citation resolves to a real tool (see
    WORKSPACE_TOOL_NAMESPACE / RESOLVABLE_ROOTS above). Mechanical
    judgment only — no name sniffing, no natural-language inference.
    Rejection precedes namespace trust (#493 F1/F2): traversal and
    empty segments never resolve, even when the raw string carries
    the trusted scripts/re/ prefix; a bare prefix cites nothing.
    Anchored index citations (#493 LOW): tools/_INDEX.yaml#<name>
    resolves only when <name> is registered; anchors elsewhere are
    stripped and ignored (historic semantics)."""
    text = str(entry).strip()
    if not text:
        return False
    base, _, anchor = text.partition("#")
    path = base.strip().replace("\\", "/")
    if not path:
        return False  # anchor-only citation names nothing
    if path.startswith("./"):
        path = path[2:]
    segments = path.split("/")
    if any(not s for s in segments):
        return False  # empty segment: leading/trailing/double slash
    if ".." in segments:
        # Traversal is not resolution — and this check runs BEFORE the
        # namespace prefix trust below: scripts/re/../../etc/passwd
        # carries the trusted prefix yet never resolves (#493 F1).
        return False
    if path == INDEX_CITATION_BASE and anchor.strip():
        # #493 LOW patch (FAULT-INJECT bypass bonus): an anchored index
        # citation must NAME a registered tool — the anchor is not
        # decoration riding a real whitelisted file. A missing/broken
        # index yields the empty name set, so this fails CLOSED toward
        # strict (same direction as bare names below). Anchors on any
        # other base keep the strip-and-ignore semantics.
        return anchor.strip() in _index_tool_names(repo_root)
    if text.startswith(WORKSPACE_TOOL_NAMESPACE):
        # Trusted by prefix (deployed per engagement; not enumerable
        # here). The rejections above already ran, so reaching this
        # branch guarantees a non-empty, traversal-free remainder under
        # the prefix — bare "scripts/re/" cites nothing (#493 F2).
        return True
    if len(segments) == 1:
        return path in _index_tool_names(repo_root)
    if not path.startswith(RESOLVABLE_ROOTS):
        return False  # outside the whitelist domains
    return (repo_root / path).exists()


def _staged_files() -> list[str]:
    """Return the list of staged (cached) file paths relative to repo root."""
    r = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRT"],
        capture_output=True, text=True, cwd=REPO_ROOT,
        errors="replace")
    if r.returncode != 0:
        return []
    return [line.strip() for line in r.stdout.splitlines() if line.strip()]


def _is_domain_path(path: str) -> bool:
    return any(path.startswith(p) or path == p.rstrip("/") for p in DOMAIN_PREFIXES)


def _review_files() -> list[Path]:
    """Return .subagent-review/*.json in the working tree (uncommitted fine)."""
    rev_dir = REPO_ROOT / ".subagent-review"
    if not rev_dir.is_dir():
        return []
    return sorted(rev_dir.glob("*.json"))


def _validate_one(path: Path) -> tuple[bool, str]:
    """Return (ok, message). ok=False if a required field is missing,
    JSON is malformed, or verified_by self-stamps."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return False, f"  {path.name}: JSON parse error: {exc}"
    if not isinstance(data, dict):
        return False, f"  {path.name}: top-level is not a dict"
    missing = [f for f in REQUIRED_FIELDS if not data.get(f)]
    if missing:
        return False, f"  {path.name}: missing fields {missing}"
    vb = str(data.get("verified_by", "")).lower()
    if any(s in vb for s in SELF_VERIFIERS):
        return False, (
            f"  {path.name}: verified_by={data['verified_by']!r} "
            f"looks like self-stamp (must be an INDEPENDENT verifier)")
    if not data.get("tools_used"):
        # tools_used is required; #462 evidence 3 — self-invention is the
        # biggest regression vector. Empty list is a soft fail.
        return False, f"  {path.name}: tools_used is empty (no reuse record)"
    tools = data.get("tools_used")
    if not isinstance(tools, (list, tuple)):
        # schema says array; a bare string/scalar is not a citation carrier
        return False, (
            f"  {path.name}: tools_used must be an array of tool citations")
    bad = [t for t in tools if not _tool_resolves(t, REPO_ROOT)]
    if bad:
        return False, (
            f"  {path.name}: tools_used cites unresolvable tool(s): {bad}\n"
            "    Resolvable = scripts/re/** (workspace RE namespace), a name\n"
            "    registered in tools/_INDEX.yaml or the\n"
            "    tools/_INDEX.ext.yaml describe-only catalog (#476), or a\n"
            "    real file under\n"
            "    scripts/ tools/ references/ (#anchor allowed; a\n"
            "    tools/_INDEX.yaml#<name> anchor must NAME a registered\n"
            "    tool).\n"
            "    An unresolvable citation is a self-invention signal (#493).")
    return True, ""


def check() -> int:
    staged = _staged_files()
    domain_touched = [p for p in staged if _is_domain_path(p)]
    if not domain_touched:
        # Gate 5 N/A: no domain paths changed → pass trivially.
        print("[PASS] Gate 5 (no domain paths staged; subagent review N/A)")
        return 0

    reviews = _review_files()
    if not reviews:
        print("HARD_PAUSE Gate 5: domain paths staged, no .subagent-review/*.json found")
        print("  Touched:")
        for p in domain_touched:
            print(f"    {p}")
        print("  Required: at least one .subagent-review/<id>.json in the working tree")
        print("  with fields: agent / plan / status_sync / tools_used / verified_by")
        print("  Schema: see devkit/docs/subagent-review.md")
        return 2

    failures: list[str] = []
    for r in reviews:
        ok, msg = _validate_one(r)
        if not ok:
            failures.append(msg)

    if failures:
        print(f"HARD_PAUSE Gate 5: {len(failures)} review(s) failed validation:")
        for f in failures:
            print(f)
        print("  Schema: see devkit/docs/subagent-review.md")
        return 2

    print(f"[PASS] Gate 5 ({len(reviews)} review file(s) valid)")
    return 0


def main(argv: list[str] | None = None) -> int:
    return check()


if __name__ == "__main__":
    sys.exit(main())