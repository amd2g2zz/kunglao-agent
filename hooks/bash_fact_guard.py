#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bash_fact_guard.py — PostToolUse/Bash facts 写入纳管 (#809)。

豆包现场的盲区：write_guard 只挂 PreToolUse/Edit|Write，worker 走 Bash
重定向写 facts/*.md 时 100% 失明——不合规写入畅通，合规通道首写却为
盲区历史买单（目录级连坐）。本 hook 是 Bash 面的补录：

  - 命令命中 facts/*.md 目标且文件已落盘 → 逐文件跑 lint_facts.lint_fact
  - 违规 → kunglao_log 落账（action=write_blocked，注册词）+ additionalContext
    响亮提示（agent 当场可见，可改走合规通道）
  - 合规写入 / 非 facts 命令 → 静默 exit 0

Posture — FAIL_OPEN, always exit 0: 纳管面是 recorder+signal，不是 gate；
lint 或 payload 异常永不打断 Bash（裁决权仍在 write_guard/lint 的结构门，
本 face 只负责"盲区不再无声"）。

Wiring (scripts/hook_activation.py, PostToolUse/Bash):
    matcher "Bash" -> this file, alongside violation_capture.py.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from _path_hygiene import scripts_on_path  # #671 sys.path hygiene authority

SKILL_DIR = Path(__file__).resolve().parent.parent

# Bash 命令中出现的 facts/ 写入目标（heredoc/重定向/tee/cp 皆命中——
# 只认路径模式；是否真的写了文件由"文件已存在"判定收口）。
FACTS_TARGET_RE = re.compile(r"facts/([A-Za-z0-9._-]+\.md)")
_SAFE_REL_RE = re.compile(r"^[A-Za-z0-9._-]+\.md$")


def resolve_ws(payload: dict) -> Path | None:
    cwd = Path(payload.get("cwd") or ".")
    for base in (cwd, cwd / "malware-analysis-workspace", cwd.parent):
        if (base / "runs").is_dir():
            return base
    return None


def _fact_ids(facts_dir: Path) -> set:
    ids: set = set()
    for p in sorted(facts_dir.glob("F*.md")):
        m = re.fullmatch(r"(F-?\d+)", p.stem)
        if m:
            ids.add(m.group(1).replace("-", ""))
    return ids


def evaluate(payload: dict) -> dict | None:
    """Pure: payload → {targets: [(rel, violations)], ws} or None。
    调用方拥有 emit + additionalContext + fail-open。"""
    cmd = str((payload.get("tool_input") or {}).get("command") or "")
    if not cmd:
        return None
    ws = resolve_ws(payload)
    if ws is None:
        return None
    facts_dir = ws / "facts"
    results: list = []
    seen: set = set()
    for rel in FACTS_TARGET_RE.findall(cmd):
        rel_l = rel.lower()
        if not _SAFE_REL_RE.fullmatch(rel) or rel_l in seen:
            continue
        seen.add(rel_l)
        p = facts_dir / rel
        if not p.is_file():
            continue
        existing_ids = _fact_ids(facts_dir)
        try:
            with scripts_on_path():
                from lint_facts import parse_frontmatter, lint_fact
            text = p.read_text(encoding="utf-8")
            fm, body, _perr = parse_frontmatter(text)
            fid = str(fm.get("id") or p.stem)
            vs = lint_fact(fid, fm, existing_ids, body)
        except Exception:  # noqa: BLE001 — fail-open: lint 异常不算违规
            continue
        if vs:
            results.append((rel, vs))
    if not results:
        return None
    return {"targets": results, "ws": ws}


def main(stdin_stream=None) -> int:
    stream = sys.stdin if stdin_stream is None else stdin_stream
    try:
        payload = json.loads(stream.read() or "{}")
    except json.JSONDecodeError:
        return 0  # fail-open: a broken payload must never break Bash
    try:
        result = evaluate(payload)
    except Exception:  # noqa: BLE001 — recorder, never a blocker
        return 0
    if not result:
        return 0
    ws = result["ws"]
    try:
        with scripts_on_path():
            import kunglao_log
        detail = ("Bash-channel facts write violated contract lint (#809): "
                  + "; ".join(f"{rel}: {'; '.join(str(x) for x in vs[:2])}"
                              for rel, vs in result["targets"]))
        kunglao_log.emit(ws, actor="bash_fact_guard", action="write_blocked",
                         detail=detail)
        print(json.dumps({"additionalContext": detail}, ensure_ascii=False))
    except Exception:  # noqa: BLE001 — recording must never break Bash
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
