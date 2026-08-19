#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_doc_sync.py — Gate 7 (Doc Sync) contract, issue #446 G-class.

Covers the three sub-checks of devkit/doc_sync.py:
  (a) gate-count claim scan — any "N-gate / N gates / N 门" numeric count
      claim on the devkit/** + .github/workflows/** face is a violation
      (derive-don't-copy: the GATES registry is the count's only source;
      even a currently-correct number is a drift seed)
  (b) references re-pin — staged references/*.md without a staged,
      pin-accurate references/_INDEX.yaml → HARD_PAUSE (rc=2), mirroring
      the 7th live-drift incident (4572c30, comment 2026-08-19)
  (c) new-script registration — staged NEW scripts/*.py whose stem is not
      mentioned in references/_INDEX.md → WARN (non-blocking; the
      mechanisms.md ledger hard-gate is #498 closeout territory)
  (d) ext index consistency (#476) — tools/_INDEX.ext.yaml entries with a
      dangling source path / missing fields / a name colliding with the
      internal registry → FAIL; entry-point scripts/hooks absent from the
      catalog → WARN (fix: regenerate via tools/ext-scan.py)

Plus Gate 7 registration lockstep (GATES[7], docstring name, pre-commit
template gate list derived from the registry — never hardcoded here).
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEVKIT_DIR = REPO_ROOT / "devkit"
sys.path.insert(0, str(DEVKIT_DIR))

import doc_sync as ds  # noqa: E402


# ---- (a) gate-count claim scan (pure, over tmp trees) ---------------

def _make_face(tmp_path: Path, rel: str, text: str) -> Path:
    """Write a file inside the scan face (or outside it) of a fake root."""
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _scan(root: Path) -> list[dict]:
    ds.REPO_ROOT = root
    try:
        return ds.scan_gate_count_claims()
    finally:
        ds.REPO_ROOT = REPO_ROOT


class TestCountClaimScan:
    def test_flags_n_gate_framework(self, tmp_path: Path) -> None:
        _make_face(tmp_path, "devkit/docs/x.md", "# X — 4-gate framework\n")
        claims = _scan(tmp_path)
        assert len(claims) == 1
        assert claims[0]["file"] == "devkit/docs/x.md"
        assert claims[0]["line"] == 1

    def test_flags_capitalized_variant(self, tmp_path: Path) -> None:
        _make_face(tmp_path, "devkit/README.md", "## The 4 Gates\n")
        claims = _scan(tmp_path)
        assert len(claims) == 1

    def test_flags_digit_space_gates(self, tmp_path: Path) -> None:
        _make_face(tmp_path, "devkit/x.py", "# runs all 6 gates here\n")
        assert len(_scan(tmp_path)) == 1

    def test_flags_chinese_men(self, tmp_path: Path) -> None:
        _make_face(tmp_path, "devkit/docs/y.md", "框架共 6 门,全部注册。\n")
        assert len(_scan(tmp_path)) == 1

    def test_correct_count_is_still_a_drift_seed(self, tmp_path: Path) -> None:
        """A number matching the current registry len is STILL a violation —
        derive-don't-copy means number-free wording, not right numbers
        (design D3: the next registered gate turns it stale). Written as a
        literal so the test never follows the registry into complacency."""
        import quality_gates as qg
        current = max(qg.GATES)
        _make_face(tmp_path, "devkit/a.md", f"# the {current}-gate runner\n")
        assert len(_scan(tmp_path)) == 1

    def test_number_free_wording_passes(self, tmp_path: Path) -> None:
        _make_face(tmp_path, "devkit/docs/x.md",
                   "# Quality Gates — gate registry: devkit/quality_gates.py GATES\n")
        _make_face(tmp_path, "devkit/README.md", "质量门 runner(门数见 GATES 注册表)\n")
        _make_face(tmp_path, ".github/workflows/ci.yml", "- name: Run quality-gate framework\n")
        assert _scan(tmp_path) == []

    def test_gate_ids_are_not_count_claims(self, tmp_path: Path) -> None:
        _make_face(tmp_path, "devkit/githooks/pre-commit",
                   "# Gates run: 1 + 3 + 4 + 5 + 6 + 7 (quick set)\n"
                   "quality_gates.py 1 3 4 5 6 7 --quiet\n")
        assert _scan(tmp_path) == []

    def test_face_excludes_scripts_hooks_tests(self, tmp_path: Path) -> None:
        """Product enforcement-gate counts are a DIFFERENT family (design D2):
        '10 gates' / '7 gate scripts' / 'v1.8.3 gates' must not fire."""
        _make_face(tmp_path, "scripts/hook_activation.py", "# 7 gate scripts + hooks\n")
        _make_face(tmp_path, "tests/test_x.py", "Validates 24 tests across 10 gates\n")
        _make_face(tmp_path, "hooks/g.py", "# v1.8.3 gates =====\n")
        _make_face(tmp_path, "references/cold.md", "1. env_check.py is Phase 0 gate\n")
        assert _scan(tmp_path) == []

    def test_workflows_face_is_scanned(self, tmp_path: Path) -> None:
        _make_face(tmp_path, ".github/workflows/release-check.yml",
                   "# The 4 gates (Requirement / Regression)\n")
        claims = _scan(tmp_path)
        assert len(claims) == 1
        assert claims[0]["file"].startswith(".github/workflows/")

    def test_claim_carries_matched_text_and_guidance(self, tmp_path: Path) -> None:
        _make_face(tmp_path, "devkit/z.md", "x 4-gate y\n")
        claims = _scan(tmp_path)
        assert "4-gate" in claims[0]["text"]
        assert claims[0]["file"] == "devkit/z.md"


# ---- (b) references re-pin (isolated git repos) ----------------------

def _pin_yaml(pairs: dict[str, str]) -> str:
    lines = ["schema: references-index/1", "files:"]
    lines += [f"  {k}: {v}" for k, v in sorted(pairs.items())]
    lines.append("symptom_map: {}")
    return "\n".join(lines) + "\n"


def _sha(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


class _Repo:
    """Isolated git repo + staged state, mirroring the pre-commit context
    (subagent_review tests' _IsolatedRepo pattern: monkeypatch ds.REPO_ROOT)."""

    def __init__(self, tmp_path: Path):
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        subprocess.run(
            ["git", "init", "-q", "--initial-branch=main", str(self.repo)],
            check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "t@t"],
                       check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "T"],
                       check=True, capture_output=True)

    def write(self, rel: str, data: str) -> None:
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding="utf-8")

    def stage(self, *rels: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), "add", "--", *rels],
                       check=True, capture_output=True)

    def commit_all(self, msg: str = "base") -> None:
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "-m", msg],
                       check=True)

    def run(self) -> int:
        ds.REPO_ROOT = self.repo
        try:
            return ds.check()
        finally:
            ds.REPO_ROOT = REPO_ROOT

    def run_captured(self, capsys) -> tuple[int, str]:
        rc = self.run()
        return rc, capsys.readouterr().out


class TestReferencesRepin:
    MD = "references/case-book.md"
    MD2 = "references/guardrails.md"

    def test_md_staged_without_yaml_hard_pauses(self, tmp_path: Path) -> None:
        r = _Repo(tmp_path)
        r.write(self.MD, "# case book v2\n")
        r.stage(self.MD)
        assert r.run() == 2  # HARD_PAUSE, mirrors Gate 5 semantics

    def test_repinned_md_plus_yaml_passes(self, tmp_path: Path) -> None:
        r = _Repo(tmp_path)
        body = "# case book v2\n"
        r.write(self.MD, body)
        r.write("references/_INDEX.yaml", _pin_yaml({self.MD: _sha(body)}))
        r.stage(self.MD, "references/_INDEX.yaml")
        assert r.run() == 0

    def test_stale_pin_hard_pauses(self, tmp_path: Path) -> None:
        """Both staged, but the md was edited after the yaml pin was made —
        the 7th live-drift shape (4572c30) that a staged-file-list-only
        check would miss (design D4)."""
        r = _Repo(tmp_path)
        r.write(self.MD, "# case book v1\n")
        r.write("references/_INDEX.yaml", _pin_yaml({self.MD: _sha("# case book v1\n")}))
        r.write(self.MD, "# case book v2 (edited after pinning)\n")
        r.stage(self.MD, "references/_INDEX.yaml")
        assert r.run() == 2

    def test_new_md_missing_pin_hard_pauses(self, tmp_path: Path) -> None:
        r = _Repo(tmp_path)
        body = "# guardrails\n"
        r.write(self.MD, "# case book\n")
        r.write(self.MD2, body)
        r.write("references/_INDEX.yaml",
                _pin_yaml({self.MD: _sha("# case book\n")}))  # MD2 unpinned
        r.stage(self.MD, self.MD2, "references/_INDEX.yaml")
        assert r.run() == 2

    def test_archive_md_exempt(self, tmp_path: Path) -> None:
        r = _Repo(tmp_path)
        r.write("references/archive/old.md", "# archived\n")
        r.stage("references/archive/old.md")
        assert r.run() == 0

    def test_non_references_staging_is_na(self, tmp_path: Path) -> None:
        r = _Repo(tmp_path)
        r.write("scripts/x.py", "# x\n")
        r.stage("scripts/x.py")
        assert r.run() == 0

    def test_pause_message_names_the_fix(self, tmp_path: Path, capsys) -> None:
        r = _Repo(tmp_path)
        r.write(self.MD, "# case book\n")
        r.stage(self.MD)
        rc, out = r.run_captured(capsys)
        assert rc == 2
        assert "re_pin_references" in out


# ---- (c) new-script registration ledger WARN -------------------------

class TestNewScriptRegistration:
    def test_unregistered_new_script_warns_but_passes(self, tmp_path: Path,
                                                      capsys) -> None:
        r = _Repo(tmp_path)
        r.write("scripts/fancy_new_tool.py", "# tool\n")
        # _INDEX.md stays UNSTAGED: sub-check (c) reads the working-tree
        # index, and staging a references/*.md would trip sub-check (b).
        r.write("references/_INDEX.md", "# index\n| `case-book.md` | ... |\n")
        r.stage("scripts/fancy_new_tool.py")
        rc, out = r.run_captured(capsys)
        assert rc == 0  # WARN is non-blocking (design D5)
        assert "WARN" in out
        assert "fancy_new_tool" in out

    def test_registered_new_script_no_warn(self, tmp_path: Path, capsys) -> None:
        r = _Repo(tmp_path)
        r.write("scripts/registered_thing.py", "# tool\n")
        r.write("references/_INDEX.md",
                "# index\n| row | mentions registered_thing in purpose |\n")
        r.stage("scripts/registered_thing.py")
        rc, out = r.run_captured(capsys)
        assert rc == 0
        assert "WARN" not in out

    def test_modified_not_added_script_no_warn(self, tmp_path: Path,
                                               capsys) -> None:
        """Only NEW files (--diff-filter=A) trigger the ledger — existing
        unregistered scripts are pre-existing debt, not this commit's."""
        r = _Repo(tmp_path)
        r.write("scripts/old_unregistered.py", "# v1\n")
        r.commit_all()
        r.write("scripts/old_unregistered.py", "# v2\n")
        r.stage("scripts/old_unregistered.py")
        rc, out = r.run_captured(capsys)
        assert rc == 0
        assert "WARN" not in out


# ---- (d) ext index consistency (#476) ----------------------------------

EXT_INDEX_REL = "tools/_INDEX.ext.yaml"


def _ext_yaml(entries: list[dict]) -> str:
    lines = ["schema: tools-ext-index/1", "ext:"]
    for e in entries:
        lines.append(f"  - name: {e.get('name', '')}")
        lines.append(f"    capability: {e.get('capability', '')}")
        lines.append(f"    source: {e.get('source', '')}")
        lines.append(f"    usage: {e.get('usage', 'usage')}")
        lines.append(f"    description: {e.get('description', 'fixture')}")
    return "\n".join(lines) + "\n"


ENTRYPOINT_SCRIPT = (
    '"""fixture tool — has an entry point."""\n'
    'if __name__ == "__main__":\n'
    "    raise SystemExit(0)\n"
)


class TestExtIndexConsistency:
    """Sub-check (d), issue #476: the ext catalog (describe-only index of
    repo capabilities outside tools/_INDEX.yaml) must stay consistent —
    entries pointing at nothing FAIL, entry-point scripts/hooks missing
    from the catalog WARN (fix = regenerate via tools/ext-scan.py)."""

    def test_entry_pointing_at_missing_file_fails(self, tmp_path: Path,
                                                  capsys) -> None:
        r = _Repo(tmp_path)
        r.write(EXT_INDEX_REL, _ext_yaml([{
            "name": "ghost-tool", "capability": "test:ghost",
            "source": "scripts/no_such_file.py"}]))
        r.stage(EXT_INDEX_REL)
        rc, out = r.run_captured(capsys)
        assert rc == 1, "dangling source path must FAIL (broken catalog)"
        assert "no_such_file.py" in out

    def test_malformed_entry_fails(self, tmp_path: Path, capsys) -> None:
        r = _Repo(tmp_path)
        r.write(EXT_INDEX_REL, _ext_yaml([{"name": "no-source",
                                           "capability": "test:x",
                                           "source": ""}]))
        r.stage(EXT_INDEX_REL)
        rc, out = r.run_captured(capsys)
        assert rc == 1, "entry without source must FAIL"
        assert "no-source" in out

    def test_duplicate_of_internal_registered_name_fails(self, tmp_path: Path,
                                                         capsys) -> None:
        r = _Repo(tmp_path)
        r.write("tools/_INDEX.yaml",
                "tools:\n  - name: crypto-tool\n    category: crypto\n")
        r.write(EXT_INDEX_REL, _ext_yaml([{
            "name": "crypto-tool", "capability": "test:dup",
            "source": "scripts/anything.py"}]))
        r.write("scripts/anything.py", ENTRYPOINT_SCRIPT)
        r.stage("tools/_INDEX.yaml", EXT_INDEX_REL)
        rc, out = r.run_captured(capsys)
        assert rc == 1, (
            "ext name colliding with an internal registered name makes "
            "bare-name resolution ambiguous — FAIL")
        assert "crypto-tool" in out

    def test_unindexed_entrypoint_script_warns_but_passes(self, tmp_path: Path,
                                                          capsys) -> None:
        r = _Repo(tmp_path)
        r.write("scripts/indexed_thing.py", ENTRYPOINT_SCRIPT)
        r.write("scripts/orphan_tool.py", ENTRYPOINT_SCRIPT)
        # satisfy sub-check (c) so the ONLY warning can come from (d)
        r.write("references/_INDEX.md",
                "# index\n mentions orphan_tool and indexed_thing rows\n")
        r.write(EXT_INDEX_REL, _ext_yaml([{
            "name": "indexed_thing", "capability": "test:x",
            "source": "scripts/indexed_thing.py"}]))
        r.stage("scripts/orphan_tool.py")
        rc, out = r.run_captured(capsys)
        assert rc == 0, "WARN is non-blocking (#446 sub-check style)"
        assert "WARN" in out
        assert "orphan_tool" in out
        assert "ext-scan" in out, "the warning must name the regeneration fix"

    def test_fully_indexed_tree_no_warn(self, tmp_path: Path, capsys) -> None:
        r = _Repo(tmp_path)
        r.write("scripts/indexed_thing.py", ENTRYPOINT_SCRIPT)
        r.write("references/_INDEX.md",
                "# index\n mentions indexed_thing row\n")
        r.write(EXT_INDEX_REL, _ext_yaml([{
            "name": "indexed_thing", "capability": "test:x",
            "source": "scripts/indexed_thing.py"}]))
        r.stage("scripts/indexed_thing.py")
        rc, out = r.run_captured(capsys)
        assert rc == 0
        assert "WARN" not in out

    def test_library_module_does_not_require_indexing(self, tmp_path: Path,
                                                     capsys) -> None:
        """Structural whitelist (design D3): a no-entry-point module is a
        library, not a callable tool — absence from the catalog is fine."""
        r = _Repo(tmp_path)
        r.write("scripts/pure_lib.py",
                '"""library fixture."""\n\ndef helper():\n    return 1\n')
        r.write("references/_INDEX.md",
                "# index\n mentions pure_lib row\n")
        r.stage("scripts/pure_lib.py")
        rc, out = r.run_captured(capsys)
        assert rc == 0
        assert "WARN" not in out

    def test_missing_ext_index_is_na(self, tmp_path: Path, capsys) -> None:
        r = _Repo(tmp_path)
        r.write("scripts/some_tool.py", ENTRYPOINT_SCRIPT)
        r.stage("scripts/some_tool.py")
        rc, out = r.run_captured(capsys)
        assert rc == 0, "absent ext index = sub-check N/A (existence pinned by tests)"

    def test_real_repo_ext_index_consistent(self, tmp_path: Path,
                                            monkeypatch, capsys) -> None:
        monkeypatch.setattr(ds, "_staged_files", lambda *a, **k: [])
        assert ds.check() == 0, (
            "the shipped ext index must pass its own consistency gate")


# ---- Gate 7 registration lockstep (registry-derived, never hardcoded) --

class TestGate7Registration:
    def test_gate7_registered_in_gates(self) -> None:
        import quality_gates as qg
        assert 7 in qg.GATES, "Gate 7 (Doc Sync) not registered"
        assert qg.GATES[7][0] == "Doc Sync"

    def test_gate7_implementation_exists_and_is_callable(self) -> None:
        import quality_gates as qg
        fn = getattr(qg, "_gate7_doc_sync", None)
        assert fn is not None, "quality_gates.py missing _gate7_doc_sync"

    def test_gate7_name_in_docstring(self) -> None:
        import quality_gates as qg
        assert "Doc Sync" in (qg.__doc__ or "")

    def test_pre_commit_template_gate_list_matches_registry(self) -> None:
        """The hook's quick-set must equal GATES minus opt-in Gate 2 —
        derived from the registry so registering Gate 8 forces the sync
        (design D8, the '1 3 4 5 6 7 is the next drift point' risk)."""
        import quality_gates as qg
        src = (DEVKIT_DIR / "githooks" / "pre-commit").read_text(encoding="utf-8")
        m = re.search(r"quality_gates\.py\"? ((?:\d+ )+)--quiet", src)
        assert m, "pre-commit template lost its quality_gates.py invocation"
        invoked = [int(x) for x in m.group(1).split()]
        expected = [g for g in sorted(qg.GATES) if g != 2]
        assert invoked == expected

    def test_pre_commit_template_has_no_second_hardcoded_gate_list(self) -> None:
        """F3 (#446 review): the failure-branch echo hint used to restate
        the full digit list ('quality_gates.py 1 3 4 5 6 7 (full verbose)')
        — a second manual-sync point the --quiet-anchored regex never saw
        (each gate registration had to update TWO lines; the hint was the
        one that could silently rot). Outside the single --quiet
        invocation, no quality_gates.py mention may carry a digit run."""
        src = (DEVKIT_DIR / "githooks" / "pre-commit").read_text(encoding="utf-8")
        stray = re.findall(
            r"quality_gates\.py\"?(?![^\n]*--quiet)[^\n]*?((?:\d+ ){2,}\d+)",
            src)
        assert not stray, (
            f"pre-commit template restates a gate digit list outside the "
            f"--quiet invocation: {stray} — rewrite the hint number-free "
            f"(point at the invocation above, never restate the digits)")

    def test_pre_commit_template_header_mentions_doc_sync(self) -> None:
        src = (DEVKIT_DIR / "githooks" / "pre-commit").read_text(encoding="utf-8")
        assert "Doc Sync" in src
        assert "#446" in src


# ---- real-repo integration -------------------------------------------

class TestRealRepo:
    def test_real_repo_face_is_claim_free(self) -> None:
        assert ds.scan_gate_count_claims() == [], (
            "live gate-count claims on the devkit/workflows face — "
            "rewrite number-free (GATES registry is the count's source)")

    def test_real_repo_check_passes_with_clean_index(
            self, tmp_path: Path, monkeypatch, capsys) -> None:
        monkeypatch.setattr(ds, "_staged_files", lambda *a, **k: [])
        assert ds.check() == 0


# ---- output encoding safety (GBK console lesson, 2026-08-20) ----------

class TestOutputSafety:
    def test_safe_output_never_raises_on_gbk(self, monkeypatch) -> None:
        monkeypatch.setattr(ds, "_out_encoding", lambda: "gbk")
        s = ds._safe("质量门框架 ⚠ drift: 4-gate wording")
        assert isinstance(s, str)  # no UnicodeEncodeError
