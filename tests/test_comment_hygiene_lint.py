# -*- coding: utf-8 -*-
"""Contract tests for the formal-content hygiene lint.

Fixtures are built in tmp trees. Offending marker text lives only in
string literals, never in this file's own comments or docstrings, so the
lint's self-scan stays clean.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import comment_hygiene_lint as chl  # noqa: E402


# --------------------------------------------------------------- fixtures
# The offending shapes below are payload strings: the lint must treat
# string literals as inert, which these module-level constants also prove
# for the self-scan.

_R1_COMMENT = "value = compute(x)  #451\n"
_R1_DOCSTRING = (
    "'''Package helpers.\n"
    "\n"
    "    Wording follows the brief in #451.\n"
    "    '''\n"
)
_CLEAN = "value = compute(x)\n"
_R2_COMMENT = "value = compute(x)  # landed via follow-up\n"
_R2_DOCSTRING = "'''Demo.\n\n    This wave only touches constants.\n    '''\n"
_R2_DOCSTRING_DOUBLE = (
    "'''Demo.\n\n    This wave is scope-only; the plan landed via review.\n    '''\n"
)
_INERT_LITERALS = (
    "TRACKER_SHAPE = 'see #451 for wording'\n"
    "MARKER_TEXT = 'aggregation-first plan'\n"
)


def _proj(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, src in files.items():
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(src, encoding="utf-8")
    return tmp_path


def _baseline(tmp_path: Path, entries: dict) -> Path:
    path = tmp_path / "scripts" / "hygiene_baseline.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"schema": chl.BASELINE_SCHEMA, "files": entries}
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return path


def _run(tmp_path: Path, *extra: str) -> int:
    return chl.main(["--root", str(tmp_path), *extra])


def _kinds(tmp_path: Path, *extra: str) -> list[str]:
    payload = chl.build_report(["--root", str(tmp_path), "--json", *extra])
    return [v["kind"] for v in payload["violations"]]


# ------------------------------------------------------------ R1: refs

def test_r1_comment_hit_flags_file(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _R1_COMMENT})
    counts, _structural = chl.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == (1, 0)
    _baseline(tmp_path, {})
    assert _run(tmp_path) == 1
    assert _kinds(tmp_path) == ["unbaselined"]


def test_r1_docstring_hit_flags_file(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _R1_DOCSTRING + _CLEAN})
    counts, _structural = chl.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == (1, 0)
    _baseline(tmp_path, {})
    assert _run(tmp_path) == 1
    assert _kinds(tmp_path) == ["unbaselined"]


def test_clean_tree_passes_without_baseline(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _CLEAN, "tests/other.py": _CLEAN})
    assert _run(tmp_path) == 0
    assert _kinds(tmp_path) == []


def test_string_literals_are_inert(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _INERT_LITERALS + _CLEAN})
    assert _run(tmp_path) == 0


# ------------------------------------------------------------ R2: prose

def test_r2_comment_marker_flags_file(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _R2_COMMENT})
    counts, _structural = chl.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == (0, 1)
    assert _run(tmp_path) == 1


def test_r2_docstring_marker_flags_file(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _R2_DOCSTRING + _CLEAN})
    counts, _structural = chl.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == (0, 1)
    assert _run(tmp_path) == 1


def test_r2_counts_one_unit_per_docstring(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _R2_DOCSTRING_DOUBLE + _CLEAN})
    counts, _structural = chl.scan_counts(tmp_path)
    assert counts["scripts/mod.py"] == (0, 1)


# ------------------------------------------------------- R3: the ratchet

def test_r3_exact_baseline_passes(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _R1_COMMENT})
    _baseline(tmp_path, {"scripts/mod.py": {"r1": 1}})
    assert _run(tmp_path) == 0


def test_r3_increase_fails(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _R1_COMMENT + _R1_COMMENT})
    _baseline(tmp_path, {"scripts/mod.py": {"r1": 1}})
    assert _run(tmp_path) == 1
    assert _kinds(tmp_path) == ["increase"]


def test_r3_zero_entry_must_be_deleted(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _CLEAN})
    _baseline(tmp_path, {"scripts/mod.py": {"r1": 1}})
    assert _run(tmp_path) == 1
    assert _kinds(tmp_path) == ["cleared-entry"]


def test_r3_loose_entry_must_be_tightened(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _R1_COMMENT})
    _baseline(tmp_path, {"scripts/mod.py": {"r1": 3}})
    assert _run(tmp_path) == 1
    assert _kinds(tmp_path) == ["loose-entry"]


def test_r3_stale_entry_fails(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _CLEAN})
    _baseline(tmp_path, {"scripts/gone.py": {"r1": 1}})
    assert _run(tmp_path) == 1
    assert _kinds(tmp_path) == ["stale-entry"]


def test_missing_baseline_with_debt_fails(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _R1_COMMENT})
    assert _run(tmp_path) == 1
    assert "no-baseline" in _kinds(tmp_path)


def test_emit_baseline_is_deterministic_and_minimal(tmp_path: Path):
    _proj(tmp_path, {
        "scripts/dirty.py": _R1_COMMENT,
        "scripts/clean.py": _CLEAN,
    })
    out_a = tmp_path / "a.yaml"
    out_b = tmp_path / "b.yaml"
    args = ("--emit-baseline",)
    assert _run(tmp_path, *args, "--baseline", str(out_a)) == 0
    assert _run(tmp_path, *args, "--baseline", str(out_b)) == 0
    assert out_a.read_bytes() == out_b.read_bytes()
    doc = yaml.safe_load(out_a.read_text(encoding="utf-8"))
    assert doc["schema"] == chl.BASELINE_SCHEMA
    assert list(doc["files"]) == ["scripts/dirty.py"]
    assert doc["files"]["scripts/dirty.py"] == {"r1": 1}


def test_emit_baseline_refuses_syntax_errors(tmp_path: Path):
    _proj(tmp_path, {"scripts/broken.py": "def f(:\n"})
    out = tmp_path / "a.yaml"
    assert _run(tmp_path, "--emit-baseline", "--baseline", str(out)) == 1
    assert not out.exists()


# ------------------------------------------------- structural fail-closed

def test_syntax_error_fails_closed(tmp_path: Path):
    _proj(tmp_path, {"scripts/broken.py": "def f(:\n"})
    assert _run(tmp_path) == 1
    assert _kinds(tmp_path) == ["syntax"]


def test_unreadable_file_fails_closed(tmp_path: Path):
    target = tmp_path / "scripts" / "mod.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"\xff\xfe\x00 not utf-8\n")
    assert _run(tmp_path) == 1
    assert "unreadable" in _kinds(tmp_path)


def test_allowlisted_file_is_skipped(tmp_path: Path, monkeypatch):
    _proj(tmp_path, {"scripts/gen.py": _R1_COMMENT})
    monkeypatch.setattr(chl, "ALLOWLIST", frozenset({"scripts/gen.py"}))
    assert _run(tmp_path) == 0


# --------------------------------------- mapping pass (arms at the map)

_FM = (
    "---\n"
    "name: a\n"
    "description: demo card\n"
    "domain: x\n"
    "family: f\n"
    "---\n"
    "\n"
    "body\n"
)


def _mapping(tmp_path: Path, rows: list[dict]) -> None:
    relib = tmp_path / "references" / "re-library"
    relib.mkdir(parents=True, exist_ok=True)
    doc = {"schema": chl.MAPPING_SCHEMA, "cards": rows}
    (relib / "_mapping.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def test_mapping_absent_is_trivial(tmp_path: Path):
    _proj(tmp_path, {"references/re-library/a.md": "no fm, no map\n"})
    assert _run(tmp_path) == 0
    assert _kinds(tmp_path) == []


def test_mapping_pre_move_state_passes(tmp_path: Path):
    """Pre-move: the source exists, the destination does not yet."""
    _proj(tmp_path, {"references/re-library/a.md": _FM})
    _mapping(tmp_path, [{"from": "references/re-library/a.md",
                         "to": "references/re-library/x/a.md",
                         "domain": "x", "family": "f"}])
    assert _run(tmp_path) == 0
    assert _kinds(tmp_path) == []


def test_mapping_flags_file_outside_the_map(tmp_path: Path):
    _proj(tmp_path, {"references/re-library/a.md": _FM,
                     "references/re-library/stray.md": _FM})
    _mapping(tmp_path, [{"from": "references/re-library/a.md",
                         "to": "references/re-library/x/a.md",
                         "domain": "x", "family": "f"}])
    assert "outside-mapping" in _kinds(tmp_path)


def test_mapping_flags_dangling_row(tmp_path: Path):
    _mapping(tmp_path, [{"from": "references/re-library/ghost.md",
                         "to": "references/re-library/x/ghost.md",
                         "domain": "x", "family": "f"}])
    assert "dangling-row" in _kinds(tmp_path)


def test_mapping_rejects_depth_over_three(tmp_path: Path):
    _proj(tmp_path, {"references/re-library/a.md": _FM})
    _mapping(tmp_path, [{"from": "references/re-library/a.md",
                         "to": "references/re-library/a/b/c/d/a.md",
                         "domain": "x", "family": "f"}])
    assert "depth" in " ".join(_kinds(tmp_path))


def test_mapping_requires_matching_frontmatter(tmp_path: Path):
    _proj(tmp_path, {"references/re-library/a.md":
                     _FM.replace("domain: x", "domain: y")})
    _mapping(tmp_path, [{"from": "references/re-library/a.md",
                         "to": "references/re-library/x/a.md",
                         "domain": "x", "family": "f"}])
    assert "fm-mismatch" in " ".join(_kinds(tmp_path))


def test_mapping_requires_parsable_frontmatter(tmp_path: Path):
    _proj(tmp_path, {"references/re-library/a.md":
                     "---\nname: a\n  bad: [unclosed\n---\nbody\n"})
    _mapping(tmp_path, [{"from": "references/re-library/a.md",
                         "to": "references/re-library/x/a.md",
                         "domain": "x", "family": "f"}])
    assert "fm-parse" in " ".join(_kinds(tmp_path))


def test_mapping_data_files_skip_frontmatter(tmp_path: Path):
    _proj(tmp_path, {"references/re-library/seeds.yaml": "k: v\n"})
    _mapping(tmp_path, [{"from": "references/re-library/seeds.yaml",
                         "to": "references/re-library/x/seeds.yaml",
                         "domain": "x", "family": "f"}])
    assert _kinds(tmp_path) == []


# ------------------------------------------------------------ gate faces

def test_exit_codes_via_subprocess(tmp_path: Path):
    _proj(tmp_path, {"scripts/mod.py": _CLEAN})
    argv = [sys.executable, str(SCRIPTS / "comment_hygiene_lint.py"),
            "--root", str(tmp_path)]
    clean = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert clean.returncode == 0
    (tmp_path / "scripts" / "mod.py").write_text(_R1_COMMENT, encoding="utf-8")
    dirty = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert dirty.returncode == 1


def test_real_tree_gate_is_green():
    """The committed baseline ratchets the live tree to a zero exit."""
    assert chl.main([]) == 0
