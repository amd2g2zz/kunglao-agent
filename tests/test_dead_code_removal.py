# -*- coding: utf-8 -*-
"""Issue #318 — dead-code removal guard (SDD+TDD, 2026-08-14 three-audit batch).

The 2026-08-14 audits (overdesign / coderot / consistency) found a set of
assets with ZERO production consumers, some still declared alive by the
manifest or docs. Issue #318 deletes them; these tests prove the removal is
complete AND harmless:

1. The deleted files no longer exist.
2. release-manifest.yaml no longer declares any of them.
3. No live reference remains in code or live docs. Historical records
   (openspec/ change records, docs/design/archive/, references/archive/)
   are exempt — they record past decisions, not current claims. (#355
   removed the docs/superpowers/ plans, docs/devlog/, docs/refactor/ and
   memory/ trees entirely.)
4. The deliberately-KEPT neighbors survive (over-deletion guard):
   - tools/tool-search.py + tools/pipelines/recipes/ — independent catalog
     query + plan templates (#318 retention decision: "可能留作工具");
   - scripts/kunglao_log.py — only the kunglao-log.py wrapper was dead
     (and it never existed in git);
   - tests/test_v1_8_enforcement_gates.py — the canonical suite; the SKILL.md
     smoke command points at tests/, not at the deleted scripts/ launcher.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SELF = Path(__file__).resolve()

# Files deleted by #318 (the kunglao-log.py wrapper is guarded although it
# never existed in git — belt and braces against reintroduction).
# #310 复活 route_capability(带 agenttype 消费方 worker_budget),#318 删除当时为死代码,复活后不再属删除清单
DELETED = [
    "hooks/agent_watch.py",
    "scripts/feature_probe.py",
    "scripts/fact_graph.py",
    "scripts/test_v1_8_enforcement_gates.py",
    "scripts/kunglao-log.py",
    "data/action-type-map.yaml",
    "schemas/verdict-output.json",
    "references/specialist-registry.yaml",
    "tests/test_feature_probe.py",
    "tests/test_fact_graph.py",
    "tests/test_specialist_registry.py",
    "tests/test_verdict_contract.py",
]

# Assets deliberately retained by the #318 retention decision.
KEPT = [
    "tools/tool-search.py",
    "tests/test_tool_search.py",
    "tests/test_recipes.py",
    "scripts/kunglao_log.py",
    "tests/test_kunglao_log.py",
    "tests/test_v1_8_enforcement_gates.py",
]

# Names that must have zero live references (issue #318 acceptance list +
# verdict-output). "kunglao-log" uses the hyphen on purpose: the live
# kunglao_log.py module must NOT match.
# "feature_probe" is NOT in DEAD_NAMES: the feature_probe.py script stays
# deleted (its paths remain in DELETED — existence and full-path reference
# checks still guard it), but the #310 contract consumes the feature_probe
# JSON output artifact (route_capability --features-file / worker_budget
# probe.json), so the bare name legitimately appears in revived #310 files
# as an input-format reference, not a module reference.
DEAD_NAMES = [
    "agent_watch",
    "fact_graph",
    "specialist-registry",
    "action-type-map",
    "kunglao-log",
    "verdict-output",
]

# Live surface scanned for residue: code + manifest + live docs. Historical
# records (openspec/ changes, docs/design/archive/, references/archive/)
# are intentionally excluded (#355 removed the former docs/superpowers/,
# docs/devlog/, docs/refactor/ and memory/ trees).
LIVE_ROOTS = [
    "scripts", "hooks", "tools", "tests", "data", "schemas",
    "references", "agents", "docs/design", "specs", ".github",
]
LIVE_FILES = [
    "README.md", "SKILL.md", "AGENTS.md", "DESIGN.md", "conftest.py",
    "pytest.ini", "release-manifest.yaml", "pyproject.toml",
]
_SCAN_SUFFIXES = (".py", ".yaml", ".yml", ".md", ".json", ".toml", ".ini")


def _scan(path: Path, hits: list[str]) -> None:
    if path.resolve() == SELF:
        return  # this test carries the names as constants — exempt itself
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return
    for lineno, line in enumerate(text.splitlines(), 1):
        for name in DEAD_NAMES:
            if name in line:
                hits.append(f"{path.relative_to(ROOT).as_posix()}:{lineno}: {line.strip()}")
                break


def _live_files() -> list[Path]:
    files: list[Path] = []
    for root in LIVE_ROOTS:
        base = ROOT / root
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.name.startswith("."):
                continue
            if "/archive/" in p.as_posix():
                continue  # archived references are historical records
            if p.suffix in _SCAN_SUFFIXES:
                files.append(p)
    for rel in LIVE_FILES:
        p = ROOT / rel
        if p.is_file():
            files.append(p)
    return files


def test_deleted_files_do_not_exist() -> None:
    """Every #318 deletion target must be gone from the tree."""
    gone = [p for p in DELETED if (ROOT / p).exists()]
    assert not gone, f"dead files still present: {gone}"


def test_manifest_does_not_declare_dead_assets() -> None:
    """release-manifest.yaml must not declare any deleted asset."""
    manifest = yaml.safe_load(
        (ROOT / "release-manifest.yaml").read_text(encoding="utf-8")
    )
    blob = yaml.safe_dump(manifest)
    hits = [n for n in DEAD_NAMES if n in blob]
    assert not hits, f"release-manifest.yaml still declares dead assets: {hits}"


def test_no_live_reference_to_dead_modules() -> None:
    """No live code/docs may reference the dead modules (reference integrity)."""
    hits: list[str] = []
    for p in _live_files():
        _scan(p, hits)
    assert not hits, (
        "live references to dead modules remain:\n" + "\n".join(hits)
    )


def test_no_live_reference_to_deleted_paths() -> None:
    """No live code/docs may carry the exact path string of a deleted file.

    Closes the DEAD_NAMES blind spot found in review (2026-08-14, D1): the
    launcher name `test_v1_8_enforcement_gates` legitimately survives in the
    kept tests/ suite, so the name scan cannot catch docstrings that still
    point at the deleted `scripts/test_v1_8_enforcement_gates.py` path.
    Scanning the full relative path strings catches that class of residue.
    """
    hits: list[str] = []
    for p in _live_files():
        if p.resolve() == SELF:
            continue  # this test carries the paths as constants — exempt itself
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for path in DELETED:
                if path in line:
                    hits.append(f"{p.relative_to(ROOT).as_posix()}:{lineno}: {line.strip()}")
                    break
    assert not hits, (
        "live references to deleted file paths remain:\n" + "\n".join(hits)
    )


def test_kept_neighbors_survive() -> None:
    """The #318 retention decisions must survive (over-deletion guard)."""
    missing = [p for p in KEPT if not (ROOT / p).exists()]
    assert not missing, f"retained assets were over-deleted: {missing}"


def test_recipes_catalog_kept() -> None:
    """The five plan recipes stay (retained with tool-search per #318)."""
    recipes = sorted((ROOT / "tools" / "pipelines" / "recipes").glob("*.yaml"))
    assert {p.stem for p in recipes} == {
        "crypto-decrypt", "go-recovery", "iat-chain", "stage-unpack", "syscall-chain",
    }
