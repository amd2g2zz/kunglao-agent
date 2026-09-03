#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_agents_lint.py — Gate 6 (#492): agents/*.md 3-element contract lint.

Definition-layer twin of Gate 5: where test_subagent_review.py checks the
EXECUTION evidence (.subagent-review/*.json), this file checks the agent
DEFINITIONS (agents/*.md) declare the 3-element contract via structural
markers (user doctrine: structured declaration over prose regex).

Covers:
  - lint_text pure function: marker presence, thin-content (hollow
    declaration) detection, fence exemption, flexible whitespace
  - lint_dir fail-closed: missing agents dir / zero *.md / unreadable file
  - CLI --json output shape (violations carry file + element)
  - real repo: all agents/*.md pass (RED before the markers landed)
  - gate wiring: GATES[6] registered, pre-commit template and
    quality_gates docstring carry no stale gate-count drift
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEVKIT_DIR = REPO_ROOT / "devkit"
DEVKIT_AGENTS_LINT = DEVKIT_DIR / "agents_lint.py"

sys.path.insert(0, str(DEVKIT_DIR))

import agents_lint as al  # noqa: E402


# ---- lint_text: pure function ----------------------------------------

def _agent_md(plan: str = "2", status: str = "2", tool: str = "2") -> str:
    """Build a synthetic agent file. Each value is the number of content
    lines for that marker ('0' = bare marker, '2' = valid)."""
    def block(element: str, n: str) -> str:
        marker = f"<!-- contract: {element} -->"
        lines = "\n".join(f"{element} content line {i}" for i in range(int(n)))
        return f"{marker}\n{lines}" if n != "0" else marker
    return (
        "---\nname: synthetic\n---\n\n# synthetic\n\n"
        + block("plan-to-execute", plan) + "\n\n"
        + block("status-sync", status) + "\n\n"
        + block("tool-discovery", tool) + "\n"
    )


class TestLintText:
    def test_all_three_markers_with_content_passes(self) -> None:
        assert al.lint_text(_agent_md()) == []

    @pytest.mark.parametrize("element", ["plan-to-execute", "status-sync", "tool-discovery"])
    def test_missing_marker_fails_with_element(self, element: str) -> None:
        # Drop only the element's marker line; the rest of the file stays valid.
        text = _agent_md()
        marker_line = f"<!-- contract: {element} -->\n"
        assert marker_line in text
        text = text.replace(marker_line, "", 1)
        violations = al.lint_text(text)
        problems = [v for v in violations if v["element"] == element]
        assert problems, f"missing {element} not reported: {violations}"
        assert "missing" in problems[0]["problem"]

    def test_bare_marker_at_eof_fails(self) -> None:
        text = _agent_md() + "\n<!-- contract: status-sync -->\n"
        violations = al.lint_text(text)
        hollow = [v for v in violations if v["element"] == "status-sync"]
        assert hollow and "non-empty" in hollow[0]["problem"]

    def test_one_line_stub_fails(self) -> None:
        violations = al.lint_text(_agent_md(status="1"))
        assert any(v["element"] == "status-sync" for v in violations)

    def test_exactly_two_content_lines_passes(self) -> None:
        assert al.lint_text(_agent_md(tool="2")) == []

    def test_blank_lines_do_not_count_as_content(self) -> None:
        text = (
            "<!-- contract: plan-to-execute -->\n\n\n   \n"
            "<!-- contract: status-sync -->\n\n\n<!-- contract: tool-discovery -->\n\n\n"
        )
        violations = al.lint_text(text)
        assert len(violations) == 3

    # Fault-inject 9b regression (hollow-marker bypass): the criterion is
    # >= MIN_CONTENT_LINES non-empty lines counted AFTER stripping complete
    # HTML-comment spans. Comment filler must not inflate the count, and the
    # >=2 floor keeps its original semantics on comment-stripped lines:
    #   2 real lines (comments interleaved) -> PASS
    #   1 real + 1 comment                   -> still hollow (1 < 2)
    #   2 comment-only lines                 -> hollow (0 < 2)
    def test_comment_only_filler_does_not_count_as_content(self) -> None:
        # Exact FAULT-INJECT 9b payload: every marker padded with 2 empty
        # HTML comments. Must be 3 hollow violations, not a pass.
        text = (
            "<!-- contract: plan-to-execute -->\n<!-- -->\n<!-- -->\n"
            "<!-- contract: status-sync -->\n<!-- -->\n<!-- -->\n"
            "<!-- contract: tool-discovery -->\n<!-- -->\n<!-- -->\n"
        )
        violations = al.lint_text(text)
        assert len(violations) == 3
        assert all("non-empty" in v["problem"] for v in violations)

    def test_comment_with_filler_text_does_not_count_as_content(self) -> None:
        # Fancier filler (`<!-- filler -->`) same story for one element.
        text = _agent_md() + "\n<!-- contract: plan-to-execute -->\n<!-- filler -->\n<!-- filler -->\n"
        violations = al.lint_text(text)
        hollow = [v for v in violations if v["element"] == "plan-to-execute"]
        assert hollow and "non-empty" in hollow[0]["problem"]

    def test_one_real_line_plus_one_comment_is_still_hollow(self) -> None:
        # 1 real + 1 comment strips down to 1 substance line: below the
        # >=2 floor — the floor itself is unchanged, comments just stop
        # counting toward it.
        text = (
            "<!-- contract: plan-to-execute -->\n"
            "real substance line\n"
            "<!-- cosmetic note -->\n"
            "<!-- contract: status-sync -->\nline one\nline two\n"
            "<!-- contract: tool-discovery -->\nline one\nline two\n"
        )
        violations = al.lint_text(text)
        hollow = [v for v in violations if v["element"] == "plan-to-execute"]
        assert hollow and "non-empty" in hollow[0]["problem"]

    def test_two_real_lines_with_interleaved_comments_passes(self) -> None:
        # 2 real lines stay >= MIN_CONTENT_LINES even with comment padding
        # around/between them — real content is not penalized.
        text = (
            "<!-- contract: plan-to-execute -->\n"
            "<!-- why this exists -->\n"
            "real substance line one\n"
            "<!-- aside -->\n"
            "real substance line two\n"
            "<!-- contract: status-sync -->\nline one\nline two\n"
            "<!-- contract: tool-discovery -->\nline one\nline two\n"
        )
        assert al.lint_text(text) == []

    def test_comment_after_real_text_still_counts_the_real_text(self) -> None:
        # A trailing inline comment does not erase the real text on the line.
        text = (
            "<!-- contract: plan-to-execute -->\n"
            "real line one <!-- inline note -->\n"
            "real line two\n"
            "<!-- contract: status-sync -->\nline one\nline two\n"
            "<!-- contract: tool-discovery -->\nline one\nline two\n"
        )
        assert al.lint_text(text) == []

    def test_flexible_whitespace_marker_matches(self) -> None:
        text = (
            "<!--contract:plan-to-execute-->\nline one\nline two\n"
            "  <!--  contract:   status-sync  -->  \nline one\nline two\n"
            "<!-- contract: tool-discovery -->\nline one\nline two\n"
        )
        assert al.lint_text(text) == []

    def test_duplicate_bare_marker_fails_even_with_real_section(self) -> None:
        # A real section followed by a hollow duplicate: the duplicate is a
        # hollow declaration and must not ride along on the real one.
        text = _agent_md() + "\n<!-- contract: tool-discovery -->\n"
        violations = al.lint_text(text)
        assert any(v["element"] == "tool-discovery" for v in violations)

    def test_marker_inside_fence_is_ignored(self) -> None:
        # A doc quoting the marker grammar inside a fenced block must not
        # create a phantom marker (which would trip the every-occurrence
        # thickness rule).
        text = _agent_md() + (
            "\n## Reference\n\n```\n<!-- contract: tool-discovery -->\n```\n"
        )
        assert al.lint_text(text) == []

    def test_unclosed_fence_swallows_rest_fail_safe(self) -> None:
        # Unclosed fence: everything after is treated as fenced (no phantom
        # markers) — fail-safe direction, documented in design.md R1.
        text = _agent_md() + "\n```\nunrelated trailing content"
        assert al.lint_text(text) == []

    def test_unknown_contract_element_ignored(self) -> None:
        text = _agent_md() + "\n<!-- contract: future-element -->\n"
        assert al.lint_text(text) == []


# ---- lint_dir + check: fail-closed -----------------------------------

class TestLintDir:
    def test_missing_dir_fail_closed(self, tmp_path: Path) -> None:
        report = al.lint_dir(tmp_path / "nope")
        assert report["ok"] is False
        assert report["violations"]

    def test_empty_dir_fail_closed(self, tmp_path: Path) -> None:
        agents = tmp_path / "agents"
        agents.mkdir()
        report = al.lint_dir(agents)
        assert report["ok"] is False
        assert "no *.md" in report["violations"][0]["problem"]

    def test_bad_agent_file_reported_with_name(self, tmp_path: Path) -> None:
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "bare.md").write_text("# bare\nno markers at all\n", encoding="utf-8")
        report = al.lint_dir(agents)
        assert report["ok"] is False
        files = {v["file"] for v in report["violations"]}
        assert "bare.md" in files

    def test_check_returns_1_on_violations(self, tmp_path: Path, capsys) -> None:
        module = al
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "bare.md").write_text("# bare\n", encoding="utf-8")
        saved = module.REPO_ROOT
        module.REPO_ROOT = tmp_path
        try:
            rc = module.check()
        finally:
            module.REPO_ROOT = saved
        assert rc == 1
        out = capsys.readouterr().out
        assert "bare.md" in out
        # Review N3: pin the HARD_PAUSE banner itself (rc=1 semantics were
        # already asserted; the banner is the human-facing stop signal).
        assert "HARD_PAUSE Gate 6" in out

    def test_check_returns_0_on_valid_dir(self, tmp_path: Path) -> None:
        module = al
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "good.md").write_text(_agent_md(), encoding="utf-8")
        saved = module.REPO_ROOT
        module.REPO_ROOT = tmp_path
        try:
            rc = module.check()
        finally:
            module.REPO_ROOT = saved
        assert rc == 0

    def test_unreadable_file_fail_closed(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        # Review N1: the third fail-closed branch (unreadable file) had
        # zero coverage. chmod is unreliable on Windows, so simulate the
        # unreadable file by monkeypatching Path.read_text to raise
        # PermissionError — an OSError subclass, exactly what lint_dir
        # catches. A file we cannot read must register as a violation,
        # not silently pass or crash the lint.
        module = al
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "secret.md").write_text(_agent_md(), encoding="utf-8")

        def deny(self, *args, **kwargs):
            raise PermissionError(13, "Permission denied", str(self))

        monkeypatch.setattr(Path, "read_text", deny)

        report = module.lint_dir(agents)
        assert report["ok"] is False
        unreadable = [v for v in report["violations"]
                      if v["file"] == "secret.md"]
        assert unreadable, f"unreadable file not reported: {report}"
        assert "unreadable" in unreadable[0]["problem"]

        saved = module.REPO_ROOT
        module.REPO_ROOT = tmp_path
        try:
            rc = module.check()
        finally:
            module.REPO_ROOT = saved
        assert rc == 1  # fail-closed: unreadable -> rc=1, never a crash
        assert "secret.md" in capsys.readouterr().out


# ---- real-repo integration (the gate itself) --------------------------

class TestRealRepo:
    def test_real_repo_agents_all_pass(self) -> None:
        report = al.lint_dir(REPO_ROOT / "agents")
        assert report["ok"] is True, f"violations: {report['violations']}"
        assert len(report["agents"]) >= 8, (
            f"expected >=8 agent files (issue lists specialists + workers), "
            f"got {len(report['agents'])}"
        )

    def test_every_agent_file_present_in_report(self) -> None:
        report = al.lint_dir(REPO_ROOT / "agents")
        names = {a["file"] for a in report["agents"]}
        expected = {
            "kunglao-worker.md", "kunglao-redteam.md", "kunglao-init-worker.md",
            "ghidra-light.md", "go-symbols.md", "floss-filter.md",
            "pefile-signature.md", "verdict-scorer.md",
        }
        assert expected <= names, f"missing agent files: {expected - names}"


# ---- CLI (--json) -----------------------------------------------------

class TestCLI:
    def _run(self, *args: str, timeout: int = 30) -> subprocess.CompletedProcess:
        assert DEVKIT_AGENTS_LINT.is_file(), "devkit/agents_lint.py missing"
        return subprocess.run(
            [sys.executable, str(DEVKIT_AGENTS_LINT), *args],
            capture_output=True, text=True, timeout=timeout, cwd=REPO_ROOT,
            errors="replace")

    def test_pass_on_real_repo(self) -> None:
        r = self._run()
        assert r.returncode == 0, f"{r.stdout}{r.stderr}"
        assert "PASS" in r.stdout

    def test_json_output_lists_file_and_element(self, tmp_path: Path) -> None:
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "stub.md").write_text("# stub\n", encoding="utf-8")
        r = self._run("--json", "--agents-dir", str(agents))
        assert r.returncode == 1
        payload = json.loads(r.stdout)
        assert payload["ok"] is False
        assert payload["violations"], "json must list violations with file+element"
        first = payload["violations"][0]
        assert first["file"] == "stub.md"
        assert first["element"]

    def test_json_ok_on_real_repo(self) -> None:
        r = self._run("--json")
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["ok"] is True
        assert payload["violations"] == []

    def test_comment_padded_fake_agent_fails(self, tmp_path: Path) -> None:
        # FAULT-INJECT 9b replay at CLI level: an agent whose markers are
        # padded with `<!-- -->` filler must exit rc=1, not ride through.
        # (Original bypass: this exact payload returned rc=0.)
        agents = tmp_path / "agents"
        agents.mkdir()
        (agents / "fake-agent.md").write_text(
            "<!-- contract: plan-to-execute -->\n<!-- -->\n<!-- -->\n"
            "<!-- contract: status-sync -->\n<!-- -->\n<!-- -->\n"
            "<!-- contract: tool-discovery -->\n<!-- -->\n<!-- -->\n",
            encoding="utf-8",
        )
        r = self._run("--agents-dir", str(agents))
        assert r.returncode == 1
        assert "HARD_PAUSE Gate 6" in r.stdout
        payload = json.loads(self._run("--json", "--agents-dir", str(agents)).stdout)
        assert payload["ok"] is False
        assert len(payload["violations"]) == 3


# ---- gate wiring + G-class drift guards -------------------------------

class TestGateWiring:
    def test_gate6_registered_in_gates(self) -> None:
        sys.path.insert(0, str(DEVKIT_DIR))
        import quality_gates as qg  # noqa: E402
        assert 6 in qg.GATES, "Gate 6 (Agents Contract) not registered"
        assert qg.GATES[6][0] == "Agents Contract"

    def test_gate6_runs_and_passes_on_real_repo(self) -> None:
        sys.path.insert(0, str(DEVKIT_DIR))
        import quality_gates as qg  # noqa: E402
        fn = getattr(qg, "_gate6_agents_contract", None)
        assert fn is not None, "quality_gates.py missing _gate6_agents_contract"
        assert fn(verbose=False) is True

    def test_quality_gates_docstring_no_stale_gate_count(self) -> None:
        src = (DEVKIT_DIR / "quality_gates.py").read_text(encoding="utf-8")
        for stale in ("4-gate", "all 4 gates", "the 4 quality gates"):
            assert stale not in src, (
                f"G-class drift: quality_gates.py still says {stale!r}"
            )

    @staticmethod
    def _quick_gate_list() -> str:
        # Derived from the GATES registry (never hardcoded here — the #446
        # drift this suite exists to catch was exactly a stale count).
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "quality_gates", DEVKIT_DIR / "quality_gates.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return " ".join(str(g) for g in sorted(mod.GATES) if g != 2)

    def test_pre_commit_template_lists_gate6(self) -> None:
        src = (DEVKIT_DIR / "githooks" / "pre-commit").read_text(encoding="utf-8")
        assert self._quick_gate_list() in src, (
            "pre-commit template must run the registry quick set")
        assert "4-gate" not in src, "G-class drift in pre-commit template header"
        assert "Agents Contract" in src or "agents" in src.lower()

    def test_pre_commit_template_gate_list_matches_registry(self) -> None:
        # The header enumerates gates for humans; the command is mechanical.
        # The quiet-run command must list the registry quick set exactly;
        # the verbose rerun hint is number-free by #446 doctrine, so only the
        # quiet run is count-checked (count == 1, not the legacy 2).
        src = (DEVKIT_DIR / "githooks" / "pre-commit").read_text(encoding="utf-8")
        expected = self._quick_gate_list()
        assert src.count(expected) == 1, (
            f"pre-commit template should list gates {expected} in the "
            "quiet run (verbose hint is number-free per doc-sync doctrine)"
        )
