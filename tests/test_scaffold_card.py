# -*- coding: utf-8 -*-
"""Contract tests for the card scaffolder.

Fixtures build tmp repo roots whose mapping registers exactly one card
destination; the emitted skeleton must carry the three standard
components and satisfy the hygiene lint's mapping and frontmatter passes.
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
import scaffold_card as sc  # noqa: E402

REGISTERED = "references/re-library/web/vm/brand-new-card.md"
SEED_FM = "---\nname: seed\ndescription: seed card\ndomain: web\nfamily: vm\n---\n\nbody\n"


def _root(tmp_path: Path) -> Path:
    relib = tmp_path / "references" / "re-library"
    relib.mkdir(parents=True)
    (relib / "seed.md").write_text(SEED_FM, encoding="utf-8")
    doc = {"schema": sc.MAPPING_SCHEMA, "cards": [
        {"from": "references/re-library/seed.md",
         "to": REGISTERED, "domain": "web", "family": "vm"}]}
    (relib / "_mapping.yaml").write_text(
        yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return tmp_path


def _run(tmp_path: Path, *extra: str) -> int:
    argv = ["--root", str(tmp_path), "--path", REGISTERED,
            "--description", "covers the x case; not for y targets", *extra]
    return sc.main(argv)


def test_writes_skeleton_with_standard_components(tmp_path: Path):
    _root(tmp_path)
    assert _run(tmp_path) == 0
    text = (tmp_path / REGISTERED).read_text(encoding="utf-8")
    assert text.count("```") % 2 == 0
    for component in ("## When to Use", "## When Not To Use", "## Worked Example"):
        assert component in text
    fm = yaml.safe_load(text.split("---\n", 2)[1])
    assert fm["name"] == "brand-new-card"
    assert fm["domain"] == "web" and fm["family"] == "vm"
    assert "x case" in fm["description"]


def test_emitted_card_satisfies_hygiene_mapping_pass(tmp_path: Path):
    _root(tmp_path)
    assert _run(tmp_path) == 0
    assert chl.mapping_violations(tmp_path) == []


def test_name_override_lands_in_frontmatter(tmp_path: Path):
    _root(tmp_path)
    assert _run(tmp_path, "--name", "custom-name") == 0
    fm = yaml.safe_load(
        (tmp_path / REGISTERED).read_text(encoding="utf-8").split("---\n", 2)[1])
    assert fm["name"] == "custom-name"


def test_refuses_unregistered_path(tmp_path: Path):
    _root(tmp_path)
    assert sc.main(["--root", str(tmp_path),
                    "--path", "references/re-library/unregistered.md",
                    "--description", "d"]) == 1
    assert not (tmp_path / "references/re-library/unregistered.md").exists()


def test_refuses_existing_file(tmp_path: Path):
    _root(tmp_path)
    assert _run(tmp_path) == 0
    assert _run(tmp_path) == 1


def test_refuses_when_mapping_absent(tmp_path: Path):
    (tmp_path / "references" / "re-library").mkdir(parents=True)
    assert _run(tmp_path) == 1


def test_refuses_path_outside_re_library(tmp_path: Path):
    _root(tmp_path)
    assert sc.main(["--root", str(tmp_path), "--path", "docs/x.md",
                    "--description", "d"]) == 1


def test_refuses_empty_description(tmp_path: Path):
    _root(tmp_path)
    assert sc.main(["--root", str(tmp_path), "--path", REGISTERED,
                    "--description", "   "]) == 1


def test_exit_codes_via_subprocess(tmp_path: Path):
    _root(tmp_path)
    argv = [sys.executable, str(SCRIPTS / "scaffold_card.py"),
            "--root", str(tmp_path), "--path", REGISTERED,
            "--description", "covers x; not y"]
    done = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert done.returncode == 0
    again = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert again.returncode == 1
