# -*- coding: utf-8 -*-
"""tests/test_relib_audit_production_866a.py — #866 production-semantics tier.

relib_audit.audit_production() judges each scripts/*.py module and each
tools/ ``__main__`` CLI by PRODUCTION wiring (issue #866 de-whitewash):

  seed faces (production)  hooks/ skills/ agents/ devkit/ .github/workflows/
                           tools/_INDEX.yaml (execution registry, consumed by
                           the toolfirst gate)
  diagnostic faces         tests/ openspec/ docs/ references/ ext index /
                           catalog .md / deploy-manifest / release-manifest —
                           reported, NEVER counted (shipping bytes != wiring;
                           tests-as-references was the #817 whitewash)
  closure                  a subject consumed (filename literal or
                           import/from <stem>) by an already-wired subject

Fixtures build a fake repo under tmp_path (no real-tree mutation); the
real-repo tests PIN today's known verdicts for the plan's +/- examples
(update them when PR 866-b registers/retires those tools — the pins are
the ratchet, not dogma).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import relib_audit  # noqa: E402


def _mkrepo(tmp_path: Path) -> Path:
    """Fake repo covering every face class of the production tier."""
    files = {
        # wired by hooks (gate invokes scripts/app.py)
        "scripts/app.py": "import helper\n\n"
                          "if __name__ == '__main__':\n    helper.run()\n",
        # lib-only: imported by wired app.py -> closure wires it
        "scripts/helper.py": "def run():\n    return 1\n",
        # referenced by tests + docs only -> production-unwired
        "scripts/orphan_util.py": "x = 1\n",
        # cataloged in the describe-only ext index -> NOT production
        "scripts/only_cataloged.py": "y = 2\n",
        # wired: execution registry + skill teaching
        "tools/widget/gen.py":
            "if __name__ == '__main__':\n    main()\n",
        # shipped in both manifests but wired to nothing
        "tools/widget/ghost.py":
            "if __name__ == '__main__':\n    main()\n",
        "hooks/gate.py": "import subprocess\nsubprocess.run(['python', 'scripts/app.py'])\n",
        "skills/kunglao/SKILL.md": "# skill\nuse tools/widget/gen.py first\n",
        "agents/worker.md": "# worker contract\n",
        "devkit/gate.py": "# devkit machinery\nscripts/devkit_wired.py\n",
        ".github/workflows/ci.yml": "run: python scripts/ci_check.py\n",
        # wired via the devkit seed face (filename literal in devkit/)
        "scripts/devkit_wired.py": "w = 1\n",
        ".github/workflows/ci.yml": "run: python scripts/ci_check.py\n",
        # ci_check wired via the CI face
        "scripts/ci_check.py": "z = 3\n",
        "deploy-manifest.yaml": "- src: tools/widget/ghost.py\n",
        "release-manifest.yaml": "- tools/widget/ghost.py\n",
        "tools/_INDEX.yaml": "tools:\n  - name: gen\n",
        "tools/_INDEX.ext.yaml": "ext:\n  - name: only_cataloged\n",
        "tools/_INDEX.md": "# human catalog\n",
        "tests/test_orphan_util.py": "import orphan_util\n",
        "docs/n.md": "see orphan_util\n",
        "references/re-library/x.md": "# capability doc\n",
    }
    for rel, body in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return tmp_path


def _names(result: dict, side: str) -> set:
    return {Path(p).name for p in result["unwired"][side]}


def test_wired_by_hooks_face(tmp_path):
    r = relib_audit.audit_production(_mkrepo(tmp_path))
    assert "app.py" not in _names(r, "scripts")
    assert "hooks" in r["faces"]["scripts/app.py"]


def test_closure_wires_lib_imported_by_wired_subject(tmp_path):
    r = relib_audit.audit_production(_mkrepo(tmp_path))
    assert "helper.py" not in _names(r, "scripts")
    assert "lib_closure" in r["faces"]["scripts/helper.py"]


def test_tests_and_docs_never_count_as_production(tmp_path):
    r = relib_audit.audit_production(_mkrepo(tmp_path))
    assert "orphan_util.py" in _names(r, "scripts")


def test_deploy_and_release_manifests_are_not_production(tmp_path):
    r = relib_audit.audit_production(_mkrepo(tmp_path))
    assert "ghost.py" in _names(r, "tools")
    # both manifest hits are recorded, as diagnostics only
    faces = r["faces"]["tools/widget/ghost.py"]
    assert "deploy_manifest" in faces and "release_manifest" in faces


def test_ext_index_is_describe_only(tmp_path):
    r = relib_audit.audit_production(_mkrepo(tmp_path))
    assert "only_cataloged.py" in _names(r, "scripts")
    assert "ext_index" in r["faces"]["scripts/only_cataloged.py"]


def test_execution_registry_and_skill_count_as_production(tmp_path):
    r = relib_audit.audit_production(_mkrepo(tmp_path))
    assert "gen.py" not in _names(r, "tools")
    faces = r["faces"]["tools/widget/gen.py"]
    assert "index_yaml" in faces and "skills" in faces


def test_devkit_face_counts_as_production(tmp_path):
    r = relib_audit.audit_production(_mkrepo(tmp_path))
    assert "devkit_wired.py" not in _names(r, "scripts")
    assert "devkit" in r["faces"]["scripts/devkit_wired.py"]


def test_ci_face_counts_as_production(tmp_path):
    r = relib_audit.audit_production(_mkrepo(tmp_path))
    assert "ci_check.py" not in _names(r, "scripts")
    assert "ci" in r["faces"]["scripts/ci_check.py"]


def test_side_counts_are_reported(tmp_path):
    r = relib_audit.audit_production(_mkrepo(tmp_path))
    assert r["counts"]["subjects_scripts"] == 6
    assert r["counts"]["subjects_tools"] == 2
    assert r["counts"]["unwired_scripts"] == 2  # orphan_util + only_cataloged
    assert r["counts"]["unwired_tools"] == 1    # ghost
    assert r["counts"]["unwired_total"] == 3


def test_unwired_loc_is_reported(tmp_path):
    r = relib_audit.audit_production(_mkrepo(tmp_path))
    # orphan_util 1 + only_cataloged 1 + ghost 2 lines
    assert r["counts"]["unwired_loc"] == 4


def test_infra_tools_are_not_subjects(tmp_path):
    r = relib_audit.audit_production(_mkrepo(tmp_path))
    all_subjects = r["wired"]["tools"] + r["unwired"]["tools"]
    assert all(not Path(p).as_posix().startswith("tools/_lib") for p in all_subjects)
    assert "tool-search.py" not in {Path(p).name for p in all_subjects}


# ---- real-repo pins (the plan's +/- examples; ratchet pins, see module doc) ----

def test_real_repo_crypto_tool_is_wired():
    r = relib_audit.audit_production(ROOT)
    assert "tools/crypto/crypto-tool.py" in r["wired"]["tools"]


def test_real_repo_ghidra_job_is_unwired():
    # PR 866-b: registering ghidra_job flips this pin — update it to the
    # new truth in the same commit as the registration.
    r = relib_audit.audit_production(ROOT)
    assert "tools/ghidra/ghidra_job.py" in r["unwired"]["tools"]


def test_real_repo_opaque_pred_is_unwired():
    r = relib_audit.audit_production(ROOT)
    assert "tools/static/opaque_pred.py" in r["unwired"]["tools"]


def test_real_repo_full_run_shape():
    # NO absolute subject-count pin here: the CI runner workspace carries
    # transient scripts/*.py noise, and a hard number would break on it
    # (172 != 169 lesson). Pin the self-consistency of the split and the
    # disposition-ledger memberships instead; snapshot numbers live in the
    # README/Recon with an as-of label.
    r = relib_audit.audit_production(ROOT)
    subjects = relib_audit.production_subjects(ROOT)
    n_scripts = sum(1 for rel in subjects if rel.startswith("scripts/"))
    n_tools = sum(1 for rel in subjects if rel.startswith("tools/"))
    assert r["counts"]["subjects_scripts"] == n_scripts
    assert r["counts"]["subjects_tools"] == n_tools
    assert (r["counts"]["wired_scripts"]
            + r["counts"]["unwired_scripts"]) == n_scripts
    assert (r["counts"]["wired_tools"]
            + r["counts"]["unwired_tools"]) == n_tools
    assert "tools/ghidra/ghidra_job.py" in r["unwired"]["tools"]
    assert "tools/crypto/crypto-tool.py" in r["wired"]["tools"]
    assert r["counts"]["unwired_total"] >= 40  # the #866-b debt is real


# ---- README dual-metric anti-whitewash regression guard ----

def test_scripts_readme_declares_both_metrics():
    text = (ROOT / "scripts" / "README.md").read_text(encoding="utf-8")
    assert "Orphans" in text
    # test semantics (historical, kept) ...
    assert "tests" in text.split("Orphans", 1)[1][:400]
    # ... and the production-semantics sibling with its reproduce command
    assert "relib_audit.py --production" in text
    assert "production" in text.lower()


def test_production_mode_json_cli(tmp_path):
    import json
    import subprocess
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "relib_audit.py"),
         "--production", str(_mkrepo(tmp_path)), "--json"],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["counts"]["unwired_total"] == 3
