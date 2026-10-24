# -*- coding: utf-8 -*-
"""tests/test_invocation_hygiene_lint_818.py — the python-invocation
standardization gate (0.1.6 sweep) on REAL fixture trees.

Behavior pins (issue #818 coverage climb): the ONE legal form is
`uv run ... python ...`; a bare `python`/`pip` in docs (outside fences,
no exempt marker) and in runtime spawn lines is a violation; markdown
fences toggle the doc scan; comment-only runtime lines are exempt; the
canonical / sys.executable / metadata-exempt forms stay clean. main()
is driven against synthetic repo roots on tmp_path (real files, real
rc, real stdout) — no mocks.
"""
from __future__ import annotations

import invocation_hygiene_lint as ihl  # noqa: E402  (scripts/ on path)


# ---------- _clean_line / the exemption markers ----------

def test_bare_python_token_is_a_violation(capsys) -> None:
    assert not ihl._clean_line("run this: python scripts/x.py")
    out: list = []
    ihl._scan_docs(["run this: python scripts/x.py\n"], "README.md", out)
    assert out == ["README.md:1: run this: python scripts/x.py"]


def test_canonical_uv_run_form_is_clean() -> None:
    assert ihl._clean_line("uv run --project . python scripts/x.py")


def test_sys_executable_form_is_clean() -> None:
    assert ihl._clean_line(
        'subprocess.run([sys.executable, "-m", "pytest"])')


def test_presence_probe_and_requirement_lines_are_clean() -> None:
    assert ihl._clean_line("python3 -V")
    assert ihl._clean_line("Requires Python 3.10+.")
    assert ihl._clean_line('requires-python = ">=3.10"')
    assert ihl._clean_line("python_version = '310'")


def test_comment_only_runtime_line_is_exempt() -> None:
    out: list = []
    line = "# python scripts/x.py"
    assert ihl._clean_line(line)
    ihl._scan_runtime([line], "scripts/x.py", out)
    assert out == []


def test_mcp_add_template_is_clean() -> None:
    assert ihl._clean_line("claude mcp add kunglao -- python hooks/x.py")


def test_eval_metadata_labels_are_clean() -> None:
    assert ihl._clean_line('{"toolchain": "python3"}')
    assert ihl._clean_line('{"language": "python"}')
    assert ihl._clean_line('language: "python"')


def test_uv_argv_and_toolchain_comparisons_are_clean() -> None:
    assert ihl._clean_line('["uv", "run", "python", "scripts/x.py"]')
    assert ihl._clean_line('name == "python"')
    # the comparison marker's CLOSING quote is a literal double quote —
    # the single-quoted variant is not exempt (pinned as-found behavior)
    assert ihl._clean_line('x != "python3"')
    assert not ihl._clean_line("x != 'python3'")


def test_supply_and_label_metadata_is_clean() -> None:
    assert ihl._clean_line("Manager(| PkgSpec(| ToolMeta(| NextAction(")
    assert ihl._clean_line('name="python"')
    assert ihl._clean_line('root_cause="python"')
    assert ihl._clean_line("the tool is never inlined as python here")
    assert ihl._clean_line('argv[0] in ("python", "python3")')


def test_bare_pip_is_a_violation() -> None:
    assert not ihl._clean_line("pip install xyz")
    assert not ihl._clean_line("pip3 install -r requirements.txt")


# ---------- _scan_docs: the fence toggle ----------

def test_fenced_block_toggle_does_not_suppress_findings() -> None:
    # AS-FOUND behavior: _scan_docs tracks the fence state but never
    # reads it — bare forms inside fenced examples are still findings.
    # (Pinned deliberately; a fence-suppression change is a product
    # decision, not a test-side one.)
    lines = [
        "intro python scripts/a.py\n",   # violation (outside fence)
        "```bash\n",                     # fence opens
        "python scripts/a.py\n",         # inside fence — still reported
        "```\n",                         # fence closes
        "python scripts/b.py\n",         # violation again
    ]
    out: list = []
    ihl._scan_docs(lines, "skills/x/SKILL.md", out)
    assert [o.split(":")[1] for o in out] == ["1", "3", "5"]
    assert all("skills/x/SKILL.md" in o for o in out)


# ---------- _scan_runtime ----------

def test_scan_runtime_finds_quoted_bare_tokens() -> None:
    out: list = []
    ihl._scan_runtime(['subprocess.run(["python", "x.py"])'],
                      "scripts/bad.py", out)
    assert len(out) == 1
    assert out[0].startswith("scripts/bad.py:1:")


def test_scan_runtime_skips_docstring_marker_lines() -> None:
    out: list = []
    ihl._scan_runtime(['"""python x.py"""', "'''pip install x'''"],
                      "scripts/doc.py", out)
    assert out == []


def test_scan_runtime_clean_lines_pass() -> None:
    out: list = []
    clean_lines = [
        'subprocess.run([sys.executable, "-m", "pytest"])',
        '["uv", "run", "python", "x.py"]',
        "# not code: python x.py",
    ]
    ihl._scan_runtime(clean_lines, "scripts/good.py", out)
    assert out == []


# ---------- main over real fixture roots ----------

def test_main_clean_tree_exit_zero(tmp_path, capsys) -> None:
    (tmp_path / "README.md").write_text(
        "all good:\n  uv run --project . python scripts/x.py\n",
        encoding="utf-8")
    skills = tmp_path / "skills" / "k"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("use uv run python x.py\n",
                                     encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "a.py").write_text(
        'subprocess.run([sys.executable, "-m", "pytest"])\n',
        encoding="utf-8")
    assert ihl.main(["--root", str(tmp_path)]) == 0
    assert "invocation-hygiene: clean" in capsys.readouterr().out


def test_main_missing_doc_globs_are_skipped(tmp_path, capsys) -> None:
    # no README/skills/commands and no scripts/hooks dirs — still clean
    assert ihl.main(["--root", str(tmp_path)]) == 0
    assert "invocation-hygiene: clean" in capsys.readouterr().out


def test_main_finds_violations_and_reports_them(
        tmp_path, capsys, monkeypatch) -> None:
    (tmp_path / "README.md").write_text("bad:  python scripts/x.py\n",
                                        encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "bad.py").write_text(
        'run(["python", "x.py"])\n', encoding="utf-8")
    assert ihl.main(["--root", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "invocation-hygiene: 2 violation(s)" in out
    assert "README.md:1:" in out
    assert "scripts/bad.py:1:" in out
    assert "uv run --project <plugin-root> python" in out
