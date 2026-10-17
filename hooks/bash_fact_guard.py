#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bash_fact_guard.py — PostToolUse/Bash facts 写入纳管 (#809)。

豆包现场的盲区：write_guard 只挂 PreToolUse/Edit|Write，worker 走 Bash
重定向写 facts/*.md 时 100% 失明——不合规写入畅通，合规通道首写却为
盲区历史买单（目录级连坐）。本 hook 是 Bash 面的补录：

  - 命令命中 facts/F*.md 目标且文件已落盘 → 逐文件跑 lint_facts.lint_fact
  - 命中 facts/_INDEX.md → 行级 lint（lint_index）——索引的真实契约是
    4 列行表，与 write_guard 对 carrier 索引写入的行审同一把尺子；
    fact 契约（type/status/边界层）对它不适用，拿错尺子只会产生
    worker 永远无法"改正"的噪音
  - 只有 error 级发现算违规；warning 级至多一条软提示（不入账、
    不用 "violated" 框架）
  - 违规 → kunglao_log 落账（action=write_blocked，注册词）+
    additionalContext 响亮提示（agent 当场可见，可改走合规通道）；
    detail 是结构化的 (rule, message) 全量清单，不截断
  - 同一 (file, rule) 的连续违规计数持久化在 runs/write-blocks.json：
    首违规落账一条，同形重试不再逐次灌账；warn 阶梯走 canonical
    warn（自带去重）；恰好在 disable 阶梯跨越一次时落
    action=write_escalated（注册词，携带 file + rules + 连续数），
    供编排方改道；清洁写入重置该文件的梯子
  - 合规写入 / 非 facts 命令 → 静默 exit 0

Posture — FAIL_OPEN, always exit 0: 纳管面是 recorder+signal，不是 gate；
lint 或 payload 异常永不打断 Bash（裁决权仍在 write_guard/lint 的结构门，
本 face 只负责"盲区不再无声"）。

#24 doc-pointer lighting: the additionalContext warning names the
references/ doc that carries the fact-file contract (lighting, not gating
— the R4 postmortem showed blind retries where one doc read would do).
No fake pointers: a doc missing from disk keeps the text verbatim
(tests/test_doc_pointer_lighting_24.py pins the map honest).

Wiring (scripts/hook_activation.py, PostToolUse/Bash):
    matcher "Bash" -> this file, alongside violation_capture.py.
"""
from __future__ import annotations
# The canonical warn — ONE implementation (process-wide
# dedupe per (op, reason) + the ledger face). The stderr-only fallback is
# the partial-deploy lifeline (scripts/ not importable here); production
# imports kunglao_log.
try:
    from _path_hygiene import ensure_scripts_path as _esp406
    _esp406()
# issue 275 batch-3: fail-open handlers leave ONE rate-limited trace —
# the canonical kunglao_log.warn.
    from kunglao_log import warn
except Exception:  # noqa: BLE001 — fail-open lifeline, never block the hook
    def warn(op: str, reason: str) -> None:
        print(f"[kunglao-agent] WARN (fail-open): {op}: {reason}",
              file=sys.stderr)
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

# the index carrier: its contract is the 4-column row table, adjudicated
# row-by-row (lint_index) — the same ruler write_guard applies to carrier
# index writes. The fact-file schema lint never runs against it.
INDEX_FILE_NAME = "_INDEX.md"

# repeat-block ladder state, per (file, rule): {rel: {rule: streak}}
BLOCK_STATE_NAME = "write-blocks.json"

# severity policy: only error-class findings are contract violations;
# warning-class findings get at most one soft informational note.
# Ladder rungs reuse the tool-error hysteresis thresholds (single source),
# with documented constants as the partial-deploy lifeline.
try:
    with scripts_on_path():
        from tool_error_policy import DISABLE_THRESHOLD as _ESCALATE_AT
        from tool_error_policy import WARN_THRESHOLD as _WARN_AT
except Exception:  # noqa: BLE001 — fail-open lifeline, never block the hook
    _WARN_AT, _ESCALATE_AT = 3, 5

# #24 doc-pointer lighting — pattern → authoritative doc, verified to exist
# and cover the pattern: a Bash-channel facts write that violates the
# fact-file contract lint -> schema.md (fact.type/status/boundary_type/
# extension fields — exactly what lint_facts enforces).
DOC_POINTERS = {
    "facts_write_contract_lint": "references/schemas/schema.md",
}
DOC_POINTER_SUFFIX = (" — this pattern is documented: {ptr}"
                      " — read before retrying")


def light_detail(pattern: str, detail: str) -> str:
    """Append the verified doc pointer to a warning's text (#24 lighting).

    An unmapped pattern or a doc missing from disk keeps the text verbatim
    — no fake pointers. Never raises: the fail-open posture holds.
    """
    ptr = DOC_POINTERS.get(pattern)
    if not ptr:
        return detail
    try:
        if not (SKILL_DIR / ptr).is_file():
            return detail
    except OSError:
        return detail
    return detail + DOC_POINTER_SUFFIX.format(ptr=ptr)


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


def _lint_target(facts_dir: Path, rel: str) -> list:
    """Lint one on-disk facts target with its OWN contract: the index
    carrier is row-linted, every other file is fact-schema-linted.
    Raises on read/lint failure (caller owns the fail-open)."""
    p = facts_dir / rel
    text = p.read_text(encoding="utf-8")
    if rel.lower() == INDEX_FILE_NAME.lower():
        with scripts_on_path():
            from lint_facts import lint_index
        return lint_index(p)
    with scripts_on_path():
        from lint_facts import parse_frontmatter, lint_fact
    fm, body, _perr = parse_frontmatter(text)
    fid = str(fm.get("id") or p.stem)
    return lint_fact(fid, fm, _fact_ids(facts_dir), body)


def evaluate(payload: dict) -> dict | None:
    """Pure: payload → {targets, clean, ws} or None。

    targets: [{file, errors: [(rule, msg)], warnings: [(rule, msg)]}] —
    severity-partitioned findings for files that have any.
    clean: files linted in this call with zero error-class findings —
    the caller resets their repeat ladder.
    调用方拥有 emit + additionalContext + fail-open。"""
    cmd = str((payload.get("tool_input") or {}).get("command") or "")
    if not cmd:
        return None
    ws = resolve_ws(payload)
    if ws is None:
        return None
    facts_dir = ws / "facts"
    targets: list = []
    clean: list = []
    seen: set = set()
    for rel in FACTS_TARGET_RE.findall(cmd):
        rel_l = rel.lower()
        if not _SAFE_REL_RE.fullmatch(rel) or rel_l in seen:
            continue
        seen.add(rel_l)
        if not (facts_dir / rel).is_file():
            continue
        try:
            findings = _lint_target(facts_dir, rel)
        except Exception:  # noqa: BLE001 — fail-open: lint 异常不算违规
            continue
        errors = [(code, msg) for sev, code, msg in findings
                  if sev == "error"]
        warnings = [(code, msg) for sev, code, msg in findings
                    if sev != "error"]
        if errors or warnings:
            targets.append({"file": rel, "errors": errors,
                            "warnings": warnings})
        else:
            clean.append(rel)
    if not targets and not clean:
        return None
    return {"targets": targets, "clean": clean, "ws": ws}


def _load_block_state(runs_dir: Path) -> dict:
    """{rel: {rule: streak}} from the last blocked writes. Fail-open: any
    read/shape problem degrades to an empty ladder (with one trace — the
    canonical face — on the exists-but-unreadable class; a MISSING ladder
    is the routine cold start and stays silent)."""
    p = runs_dir / BLOCK_STATE_NAME
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): (v if isinstance(v, dict) else {})
                    for k, v in data.items()}
    except (OSError, ValueError) as exc:
        from kunglao_log import warn  # noqa: PLC0415 — the canonical face
        warn("block_state_read",
             f"{type(exc).__name__}: {exc} — ladder reads as empty")
    return {}


def _save_block_state(runs_dir: Path, state: dict) -> None:
    """Persist the ladder; failure is traced, never raised (recorder)."""
    try:
        runs_dir.mkdir(parents=True, exist_ok=True)
        (runs_dir / BLOCK_STATE_NAME).write_text(
            json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        warn("save_block_state", f"{type(exc).__name__}: {exc}")


def _apply_repeat_ladder(ws: Path, result: dict) -> dict:
    """Advance the per-(file, rule) consecutive-block ladder and return the
    emission decisions for this call:

        first      files with a rule leaving zero (the recording face)
        warned     (file, rules) reaching the warn rung
        escalated  (file, rules, streak) crossing the disable rung exactly
                   now — the escalation event fires at the crossing

    A clean write (no error-class findings) resets that file's ladder.
    All state IO is fail-open; the returned shape is plain data."""
    runs_dir = ws / "runs"
    state = _load_block_state(runs_dir)
    for rel in result.get("clean", []):
        state.pop(rel, None)
    first: list = []
    warned: list = []
    escalated: list = []
    for t in result["targets"]:
        if not t["errors"]:
            continue
        rec = state.setdefault(t["file"], {})
        touched: list = []
        # one ladder step per RULE per block — a rule may carry several
        # findings in one write (e.g. per-item extension fields), which
        # must not advance its streak faster than the write itself
        for rule in sorted({rule for rule, _msg in t["errors"]}):
            streak = int(rec.get(rule, 0)) + 1
            rec[rule] = streak
            touched.append((rule, streak))
        if any(n == 1 for _r, n in touched):
            first.append(t)
        at_warn = sorted(r for r, n in touched if n == _WARN_AT)
        if at_warn:
            warned.append((t["file"], at_warn))
        crossed = sorted(r for r, n in touched if n == _ESCALATE_AT)
        if crossed:
            escalated.append((t["file"], crossed, _ESCALATE_AT))
    _save_block_state(runs_dir, state)
    return {"first": first, "warned": warned, "escalated": escalated}


def _format_errors(t: dict) -> str:
    """Structured (rule, message) pairs — every finding, none dropped."""
    return f"{t['file']}: " + "; ".join(
        f"{rule}: {msg}" for rule, msg in t["errors"])


def _surface(ws: Path, result: dict, ladder: dict) -> None:
    """Emit + additionalContext for one call. Error-class writes print the
    structured detail every time (the worker must see it on each retry) and
    land a ledger row only at the ladder rungs, so a repeated same-shape
    retry cannot flood the event stream. Warning-only writes get at most
    one soft informational note — never the violation framing, never a
    ledger row."""
    blocked = [t for t in result["targets"] if t["errors"]]
    warn_only = [t for t in result["targets"] if not t["errors"]]
    with scripts_on_path():
        import kunglao_log
    if blocked:
        detail = ("Bash-channel facts write blocked by contract lint: "
                  + " | ".join(_format_errors(t) for t in blocked))
        detail = light_detail("facts_write_contract_lint", detail)
        note = detail
        if ladder["first"]:
            kunglao_log.emit(ws, actor="bash_fact_guard",
                             action="write_blocked", detail=detail)
        for rel, rules in ladder["warned"]:
            warn("bash_fact_guard_repeat",
                 f"facts write {rel} keeps failing the same rules "
                 f"({', '.join(rules)}) — fix the named rules or switch "
                 f"approach")
        if ladder["escalated"]:
            esc = "; ".join(
                f"file={rel} consecutive={n} rules={','.join(rules)}"
                for rel, rules, n in ladder["escalated"])
            kunglao_log.emit(ws, actor="bash_fact_guard",
                             action="write_escalated",
                             detail="repeat-block ladder crossed — reroute "
                                    f"or repair: {esc} | {detail}")
            note = (f"repeat-block ladder crossed ({esc}) — the "
                    "orchestrator may reroute; fix the named rules or "
                    f"switch approach. {detail}")
        print(json.dumps({"additionalContext": note}, ensure_ascii=False))
    elif warn_only:
        note = ("Bash-channel facts write note (informational): "
                + "; ".join(
                    f"{t['file']}: warning-class lint findings "
                    f"({', '.join(sorted({r for r, _m in t['warnings']}))})"
                    for t in warn_only)
                + " — not contract violations; the named rules still "
                  "apply on the error ladder")
        print(json.dumps({"additionalContext": note}, ensure_ascii=False))


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
        ladder = _apply_repeat_ladder(ws, result)
        _surface(ws, result, ladder)
    except Exception as exc:  # noqa: BLE001 — recording must never break Bash
        warn("main", f"{type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
