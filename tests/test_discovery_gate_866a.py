# -*- coding: utf-8 -*-
"""tests/test_discovery_gate_866a.py — #866 discovery-face CI gate.

devkit/discovery_gate.py (quality_gates Gate 9): every tools/
``__main__`` CLI must be DISCOVERABLE in the same change that adds it —

  face A (registry)     a tools/_INDEX.yaml entry (the execution registry
                        the toolfirst gate consumes; the ext index is
                        describe-only and excludes internal-registry names
                        by design, so the tools-native registry is the
                        machine face — Recon deviation 1)
  face B (teaching)     a SKILL teaching mention OR a references/ entry

missing faces are violations ABSORBED by the baseline ratchet
(devkit/.discovery-gate-baseline.txt — one repo-relative source key per
line, the retirement-gate pattern): existing debt rides the baseline,
a NEW unregistered CLI is red.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "devkit"))

import discovery_gate  # noqa: E402


def _mkrepo(tmp_path: Path) -> Path:
    files = {
        # compliant: registry + skill teaching
        "tools/widget/gen.py": "if __name__ == '__main__':\n    main()\n",
        "tools/_INDEX.yaml": "tools:\n  - name: gen\n",
        "skills/kunglao/SKILL.md": "# skill\nuse tools/widget/gen.py\n",
        # half-wired: registry only (no teaching face)
        "tools/widget/partial.py":
            "if __name__ == '__main__':\n    main()\n",
        # infra trio + non-__main__ files are never subjects
        "tools/tool-search.py": "if __name__ == '__main__':\n    pass\n",
        "tools/widget/_util.py": "def h():\n    return 1\n",
        "references/re-library/x.md": "# capability doc\n",
    }
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


def _write_baseline(tmp_path: Path, keys: list) -> Path:
    b = tmp_path / "devkit" / ".discovery-gate-baseline.txt"
    b.parent.mkdir(parents=True, exist_ok=True)
    b.write_text("# baseline debt ledger (#866-b)\n"
                 + "".join(f"{k}\n" for k in keys), encoding="utf-8")
    return b


def _findings(tmp_path: Path, baseline: list | None = None) -> list:
    if baseline is None:
        baseline = ["tools/widget/partial.py"]
    _write_baseline(tmp_path, baseline)
    return discovery_gate.find_violations(tmp_path, baseline_keys=None,
                                          baseline_path=None)


def test_new_unregistered_cli_is_red(tmp_path):
    (tmp_path / "tools" / "widget").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tools" / "widget" / "new_tool.py").write_text(
        "if __name__ == '__main__':\n    main()\n", encoding="utf-8")
    violations = _findings(tmp_path)
    assert any("new_tool.py" in v for v in violations), violations


def test_registered_and_taught_cli_is_green(tmp_path):
    violations = _findings(tmp_path)
    assert not any("gen.py" in v for v in violations), violations


def test_registry_without_teaching_is_red(tmp_path):
    _mkrepo(tmp_path)
    violations = _findings(tmp_path, baseline=[])
    assert any("partial.py" in v for v in violations), violations


def test_teaching_without_registry_is_red(tmp_path):
    _mkrepo(tmp_path)
    # gen loses its registry row -> teaching alone is not enough
    idx = tmp_path / "tools" / "_INDEX.yaml"
    idx.write_text("tools:\n  - name: other\n", encoding="utf-8")
    violations = _findings(tmp_path, baseline=[])
    assert any("gen.py" in v for v in violations), violations


def test_baseline_ratchet_absorbs_known_debt(tmp_path):
    violations = _findings(tmp_path, baseline=["tools/widget/partial.py"])
    assert not any("partial.py" in v for v in violations), violations


def test_infra_and_non_main_files_not_subjects(tmp_path):
    _findings(tmp_path, baseline=[])
    subjects = discovery_gate.enumerate_subjects(tmp_path)
    names = {Path(rel).name for rel in subjects}
    assert "tool-search.py" not in names
    assert "_util.py" not in names


def test_red_green_two_state_demo(tmp_path):
    """The issue's acceptance demo: an unregistered fake CLI is red; the
    same-帧 registration (registry row + SKILL teaching) turns it green."""
    widget = tmp_path / "tools" / "widget"
    widget.mkdir(parents=True, exist_ok=True)
    (widget / "demo.py").write_text(
        "if __name__ == '__main__':\n    main()\n", encoding="utf-8")
    _write_baseline(tmp_path, [])
    assert discovery_gate.find_violations(
        tmp_path, baseline_keys=None, baseline_path=None)  # RED
    idx = tmp_path / "tools" / "_INDEX.yaml"
    idx.write_text("tools:\n  - name: demo\n", encoding="utf-8")
    skill = tmp_path / "skills" / "kunglao" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text("use tools/widget/demo.py\n", encoding="utf-8")
    assert not discovery_gate.find_violations(
        tmp_path, baseline_keys=None, baseline_path=None)  # GREEN


def test_real_repo_gate_green_with_shipped_baseline():
    assert discovery_gate.check(str(ROOT)) == 0


def test_cli_exit_codes(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(ROOT / "devkit" / "discovery_gate.py"),
         "--root", str(_mkrepo(tmp_path)),
         "--baseline", str(tmp_path / "devkit" / ".nonexistent.txt")],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 1  # debt with no baseline file -> red
