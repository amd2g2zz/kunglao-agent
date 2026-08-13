# -*- coding: utf-8 -*-
"""Issue #277 — 脚本纪律契约: 工具逻辑落为可复用 CLI 脚本, 禁命令行内联执行.

Mechanical gate scanning `scripts/` and `templates/CLAUDE.md.tmpl`:

- Reusable logic must NOT be inlined as `python -c "..."` or a heredoc
  `<<'EOF'` / `<<EOF` in command lines. Exempt only when the line is a
  comment, an explicit one-off diagnostic (allow marker), or prose that
  *states the prohibition* (forbidden / 禁止 ...).
- `templates/CLAUDE.md.tmpl` must carry the discipline vocabulary
  (可复用逻辑 / ad-hoc / 内联).
- `SKILL.md` and `agents/kunglao-worker.md` must carry the same dispatch
  contract wording (reusable logic -> parameterized CLI in `scripts/`;
  existing CLI preferred; no inline execution).
- `references/cli-script-checklist.md` (the CLI-spec checklist) must exist
  and be registered in `references/_INDEX.md`.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TEMPLATE = ROOT / "templates" / "CLAUDE.md.tmpl"
SKILL = ROOT / "SKILL.md"
WORKER = ROOT / "agents" / "kunglao-worker.md"
CHECKLIST = ROOT / "references" / "cli-script-checklist.md"
INDEX = ROOT / "references" / "_INDEX.md"

# Inline-execution shapes that would carry reusable logic — banned in the tree.
_INLINE_PATTERNS = (
    re.compile(r"python(?:3|\.exe)?\s+-c\s+['\"]"),  # python -c "<code>"
    re.compile(r"<<\s*-?['\"]?EOF['\"]?"),      # heredoc <<EOF / <<'EOF' / <<"EOF" / <<-EOF
)

# A line that merely *mentions* the ban is describing the rule, not executing it.
_PROHIBIT_MARKERS = (
    "禁止", "不允许", "forbidden", "prohibited", "prohibit", "banned", "must not",
)

# Explicit allow-labels: a line carrying one of these is a whitelisted one-off.
_ALLOW_MARKERS = ("一次性", "one-off", "one shot", "diagnostic only", "# allow", "# ok")


def _scanned_files() -> list[Path]:
    """Every text file under scripts/ (py/md/sh/ps1/bat) plus templates/CLAUDE.md.tmpl."""
    files = [
        p
        for p in sorted(SCRIPTS.rglob("*"))
        if p.is_file() and p.suffix in (".py", ".md", ".sh", ".ps1", ".bat")
    ]
    files.append(TEMPLATE)
    return files


def _inline_violations() -> list[str]:
    """Return <rel>:<lineno>: <line> for every inline-execution hit."""
    hits: list[str] = []
    for p in _scanned_files():
        rel = p.relative_to(ROOT).as_posix()
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue  # binary (e.g. .pyc is filtered by suffix; belt-and-braces)
        for lineno, raw in enumerate(lines, 1):
            line = raw.strip()
            if not line:
                continue
            if line.startswith("#") or line.startswith("<!--"):
                continue  # comment -> not executable
            if any(m in line for m in _ALLOW_MARKERS):
                continue  # explicit one-off / allow label
            if any(m in line for m in _PROHIBIT_MARKERS):
                continue  # prose stating the ban, not an execution
            for pat in _INLINE_PATTERNS:
                if pat.search(line):
                    hits.append(f"{rel}:{lineno}: {raw}")
                    break
    return hits


def test_no_inline_reusable_logic_in_scripts_or_template() -> None:
    """scripts/ + templates/CLAUDE.md.tmpl must not inline reusable logic."""
    hits = _inline_violations()
    assert not hits, (
        "inline reusable-logic execution found (use a parameterized CLI in "
        "scripts/ instead):\n" + "\n".join(hits)
    )


def test_template_has_script_discipline_keywords() -> None:
    """templates/CLAUDE.md.tmpl carries the discipline vocabulary."""
    text = TEMPLATE.read_text(encoding="utf-8")
    for kw in ("可复用逻辑", "ad-hoc", "内联"):
        assert kw in text, f"CLAUDE.md.tmpl missing script-discipline keyword: {kw}"


def test_skill_has_script_discipline_contract() -> None:
    """SKILL.md dispatch contract references CLI-first / no inline reusable logic."""
    parts = SKILL.read_text(encoding="utf-8").split("---", 2)
    body = parts[2] if len(parts) == 3 else SKILL.read_text(encoding="utf-8")
    for kw in ("reusable logic", "inline", "CLI"):
        assert kw in body, f"SKILL.md body missing script-discipline keyword: {kw}"


def test_worker_has_script_discipline_contract() -> None:
    """agents/kunglao-worker.md requires reusable logic to be a CLI, not inline."""
    text = WORKER.read_text(encoding="utf-8")
    for kw in ("reusable", "CLI", "inline"):
        assert kw in text, f"kunglao-worker.md missing script-discipline keyword: {kw}"


def test_cli_checklist_doc_registered() -> None:
    """references/cli-script-checklist.md exists and is registered in _INDEX.md."""
    assert CHECKLIST.exists(), "missing references/cli-script-checklist.md"
    idx = INDEX.read_text(encoding="utf-8")
    assert "cli-script-checklist.md" in idx, (
        "cli-script-checklist.md not registered in references/_INDEX.md"
    )
