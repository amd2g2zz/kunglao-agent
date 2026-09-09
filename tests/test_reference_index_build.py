# -*- coding: utf-8 -*-
"""Contract tests for the reference index generator.

Fixtures build tmp roots with a small mapping plus two FM-complete cards;
the generated tiers must parse with the recall engine's structural forms,
byte-match frontmatter, and regenerate deterministically.
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

import reference_index_build as rib  # noqa: E402

CARD_FM = (
    "---\n"
    "name: demo-card\n"
    "description: covers the demo scenario; not for the other case.\n"
    "domain: web\n"
    "family: labs\n"
    "---\n"
    "\n"
    "body\n"
)


def _root(tmp_path: Path) -> Path:
    relib = tmp_path / "references" / "re-library"
    relib.mkdir(parents=True)
    (relib / "demo-card.md").write_text(CARD_FM, encoding="utf-8")
    doc = {
        "schema": rib.MAPPING_SCHEMA,
        "domains": {"web": "Web RE knowledge"},
        "scenarios": {"Demo scenario": "web (demo-card)"},
        "cards": [{"from": "references/re-library/demo-card.md",
                   "to": "references/re-library/web/labs/demo-card.md",
                   "domain": "web", "family": "labs"}],
    }
    (relib / "_mapping.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return tmp_path


def _run(tmp_path: Path, *extra: str) -> int:
    return rib.main(["--root", str(tmp_path), *extra])


def test_generates_global_and_domain_tiers(tmp_path: Path):
    _root(tmp_path)
    assert _run(tmp_path) == 0
    global_text = (tmp_path / "references" / "_INDEX.md").read_text(encoding="utf-8")
    assert "| web | demo-card | Web RE knowledge |" in global_text
    assert "| Demo scenario | web (demo-card) |" in global_text
    assert "| `_index-web.md` | web |" in global_text
    dom = (tmp_path / "references" / "_index-web.md").read_text(encoding="utf-8")
    assert "[demo-card.md](re-library/demo-card.md)" in dom
    assert "covers the demo scenario" in dom  # FM description, verbatim


def test_rows_emit_the_existing_face(tmp_path: Path):
    _root(tmp_path)
    _run(tmp_path)
    moved = tmp_path / "references" / "re-library" / "web" / "labs" / "demo-card.md"
    moved.parent.mkdir(parents=True)
    moved.write_text(CARD_FM, encoding="utf-8")
    (tmp_path / "references" / "re-library" / "demo-card.md").unlink()
    _run(tmp_path)
    dom = (tmp_path / "references" / "_index-web.md").read_text(encoding="utf-8")
    assert "[demo-card.md](re-library/web/labs/demo-card.md)" in dom


def test_generation_is_deterministic(tmp_path: Path):
    _root(tmp_path)
    a = tmp_path / "a"
    b = tmp_path / "b"
    for out in (a, b):
        shutil_tree(tmp_path, out)
    _run(a)
    _run(b)
    for rel in ("references/_INDEX.md", "references/_index-web.md"):
        assert (a / rel).read_bytes() == (b / rel).read_bytes()


def shutil_tree(src: Path, dst: Path) -> None:
    import shutil

    shutil.copytree(src, dst)


def test_check_gate_flags_drift(tmp_path: Path):
    _root(tmp_path)
    assert _run(tmp_path) == 0
    assert _run(tmp_path, "--check") == 0
    dom = tmp_path / "references" / "_index-web.md"
    dom.write_text(dom.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    assert _run(tmp_path, "--check") == 1


def test_preserves_marked_hand_region(tmp_path: Path):
    _root(tmp_path)
    hand = ("## Top-level references\n\n"
            "| `case-book.md` | failure-cases | five failure modes | when |\n")
    (tmp_path / "references" / "_INDEX.md").write_text(
        rib.HAND_BEGIN + "\n" + hand + rib.HAND_END + "\n", encoding="utf-8")
    _run(tmp_path)
    text = (tmp_path / "references" / "_INDEX.md").read_text(encoding="utf-8")
    assert hand in text
    assert rib.HAND_BEGIN in text and rib.HAND_END in text


def test_migrates_unmarked_top_level_section(tmp_path: Path):
    _root(tmp_path)
    legacy = ("# old index\n\n## Top-level references\n\n"
              "| `case-book.md` | failure-cases | five failure modes | when |\n"
              "\n## re-library/\n\nstale rows\n")
    (tmp_path / "references" / "_INDEX.md").write_text(legacy, encoding="utf-8")
    _run(tmp_path)
    text = (tmp_path / "references" / "_INDEX.md").read_text(encoding="utf-8")
    assert "| `case-book.md` | failure-cases | five failure modes | when |" in text
    assert "stale rows" not in text


def test_refuses_when_mapping_block_missing(tmp_path: Path):
    _root(tmp_path)
    map_path = tmp_path / "references" / "re-library" / "_mapping.yaml"
    doc = yaml.safe_load(map_path.read_text(encoding="utf-8"))
    del doc["domains"]
    map_path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    assert _run(tmp_path) == 1


def test_refuses_card_without_frontmatter(tmp_path: Path):
    _root(tmp_path)
    (tmp_path / "references" / "re-library" / "demo-card.md").write_text(
        "no fm\n", encoding="utf-8")
    assert _run(tmp_path) == 1


def test_generated_index_parses_with_recall_engine(tmp_path: Path):
    _root(tmp_path)
    _run(tmp_path)
    sys.path.insert(0, str(ROOT / "scripts"))
    import references_recall as rr  # noqa: E402

    idx = rr.build_index(tmp_path / "references" / "_INDEX.md")
    assert "web" in idx.domains
    assert any(e.path == "re-library/demo-card.md" for e in idx.entries)
    assert any(s.label == "Demo scenario" for s in idx.scenes)


def test_real_tree_generation_is_a_no_op():
    """The committed index files are exactly what the mapping regenerates."""
    assert rib.main(["--check"]) == 0


def test_exit_codes_via_subprocess(tmp_path: Path):
    _root(tmp_path)
    argv = [sys.executable, str(SCRIPTS / "reference_index_build.py"),
            "--root", str(tmp_path)]
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert done.returncode == 0
