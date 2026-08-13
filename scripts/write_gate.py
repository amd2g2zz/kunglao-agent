#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""write_gate — 写侧门禁审计器 (issue #236).

2026-08-12 组合故障链 (self-synthesis + self-stamping + fake blocker) 暴露:
所有 kunglao 机械门禁都是读侧 (dispatch 纪律 / verify 锚点 / 收敛判定);
写侧 — 状态如何生成: verify_status 盖章、expected 锚点来源、defer 理由 —
是裸的。本模块补齐写侧机械约束, 与读侧门禁对称。审计对象按仓库真实
schema (references/schema.md, references/guardrails.md §1b):

- R1 maker-checker 盖章回验:
  * notes/*.md 带 verify_status=passes 的 note 必须存在独立验证者记录 —
    runs/*-verify-*.md 引用该 note id 且内容含正向裁决 (passes/CONFIRMED)
    (guardrails §1b: 只有独立 verifier subagent 可写 verify_status;
    2026-08-12 create-runs.py 直接把 notes 的 pending 盖章为 passes,
    无任何验证记录 — 本规则捕获该形状)。
  * facts/*.md 带 status ∈ {PROVEN, VERIFIED} 的 fact 必须携带独立验证者
    证据: verifier_sign_off (verifier_id ≠ 生产者: register worker_id /
    provenance recompute_script), 或 verified_by_run 且其命名的记录实际
    存在, 或 runs/ 下的 verify 记录 (verify-redteam-*.md 含 CONFIRMED 且
    引用该 fact / verify-<fid>-*.json overall=VERIFIED 或 l2=CONFIRMED,
    与 kunglao_verify.py L603-610 输出形状一致)。
- R2 独立 expected 锚点: 携带 expected/output hash 的 fact, verified_by_run
  解析到与 provenance recompute_script 同一脚本 → 生产者自锚
  (adapt-final.py 模式, 脚本自算 expected 即重言式验证) → 违规。
- R3 defer_reason 可回查: claim-register.yaml 中 defer_reason 引用的
  decision-rights 行号必须命中 references/decision-rights.md 实际存在的行
  (解析文件, 不硬编码行数); 引用不存在的行 = fake blocker 向量。
  仅识别决策引用形态 ("decision-rights row N" / "治理行 N" /
  "决策矩阵 N" / 行尾孤立的 "row N"), 避免 "row 5 of PE header table"
  之类的非决策引用误报。

仅标准库, 确定性。输出: 机器可读违规列表 + 人类文本; --json 模式。
exit 0 干净 / 1 违规 / 2 用法错误。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# fact 状态中"已盖章"的取值 (references/schema.md fact.status 的 terminal 子集)
FACT_VERIFIED_STATUSES = ("PROVEN", "VERIFIED")
# 携带"产出锚点"的字段 (R2 适用条件)
EXPECTED_FIELDS = ("expected", "expected_sha256", "output", "output_sha256")
# 验证记录中的正向裁决 token (内容感知 — "F-1: FAILED" 不算独立验证)
POSITIVE_VERDICT_RE = re.compile(r"\b(?:CONFIRMED|passes)\b", re.IGNORECASE)
_SCRIPT_EXTENSIONS = (".py", ".sh", ".ps1", ".rb", ".js")

# verifier_sign_off 块 (blind_gate.py 同形: yaml 围栏或裸块, 取 verifier_id/verdict)
_SIGNOFF_BLOCK_RE = re.compile(
    r"verifier_sign_off:\s*\n(.*?)(?:\n\n|\n```|\Z)", re.DOTALL)
_SIGNOFF_FIELD_RE = re.compile(
    r"^\s*(verifier_id|verdict)\s*:\s*['\"]?([^'\"\n]+)", re.MULTILINE)
# provenance 内联条目 (kunglao_verify.py F3 gate 同形)
_INLINE_PROV_ENTRY_RE = re.compile(r"\{([^{}]*)\}")

# "row N" 引用 — 仅决策引用形态 (R3, 防 "row 5 of PE header" 误报)
_CONTEXT_ROW_RE = re.compile(
    r"decision[- ]?(?:rights|matrix)\s+row\s+#?(\d+)"
    r"|治理行\s*[:：]?\s*#?(\d+)"
    r"|决策矩阵\s*[:：]?\s*(?:row\s*)?#?(\d+)",
    re.IGNORECASE)
# 行尾孤立的 "row N" (前后无描述文字); (?<![-\w]) 排除 "arrow 5"
_STANDALONE_ROW_RE = re.compile(
    r"(?<![-\w])row\s+#?(\d+)\s*$", re.IGNORECASE | re.MULTILINE)

_CLAIM_BLOCK_RE = re.compile(r"- id:\s*(\S+)\b(.*?)(?=\n-\s*id:|\Z)", re.DOTALL)
_DEFER_REASON_LINE_RE = re.compile(r"^\s*defer_reason:\s*(.+)$", re.MULTILINE)


# ===========================================================================
# frontmatter / actor 解析
# ===========================================================================

def _parse_frontmatter(text: str) -> dict:
    """极简 frontmatter: '---' 围栏内逐行 'key: value'(去引号). 失败返回 {}."""
    out: dict[str, str] = {}
    if not text.startswith("---"):
        return out
    body = text.split("---", 2)
    if len(body) < 3:
        return out
    for line in body[1].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _path_of(value: str, ws: Path) -> Path | None:
    """从值(裸路径或命令串)中提取脚本路径, 相对 ws 解析; 无路径形态 → None."""
    for tok in value.split():
        t = tok.strip().strip("\"'")
        if not t:
            continue
        if "/" in t or "\\" in t or t.endswith(_SCRIPT_EXTENSIONS):
            p = Path(t)
            return (p if p.is_absolute() else ws / p).resolve()
    return None


def _same_actor(a: str, b: str, ws: Path) -> bool:
    """两 actor 是否同一实体: 精确串等 或 解析为同一脚本路径.

    脚本形态 (带扩展名/路径分隔符) 的双方还按 basename 比较 — 覆盖
    "adapt_final.py" vs "scripts/re/adapt_final.py" 的裸名/带路径写法.
    """
    na, nb = a.strip().strip("\"'").lower(), b.strip().strip("\"'").lower()
    if na == nb:
        return True
    pa, pb = _path_of(a, ws), _path_of(b, ws)
    if pa is not None and pa == pb:
        return True
    if pa is not None and pb is not None and pa.name == pb.name:
        return True
    return False


def _parse_signoff(text: str) -> dict:
    """从 fact 原文抽取 verifier_sign_off 块的 {verifier_id, verdict}."""
    m = _SIGNOFF_BLOCK_RE.search(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for fm in _SIGNOFF_FIELD_RE.finditer(m.group(1)):
        out[fm.group(1).strip()] = fm.group(2).strip().strip("\"'")
    return out


def _prov_recompute_paths(text: str) -> list[str]:
    """fact 的产出脚本路径列表 (provenance role=recompute_script, F3 同形)."""
    fm = text.split("---", 2)[1] if text.startswith("---") else text
    paths: list[str] = []
    for entry in _INLINE_PROV_ENTRY_RE.findall(fm):
        if re.search(r"role\s*:\s*recompute_script", entry, re.IGNORECASE):
            m = re.search(r"(?:path|url)\s*:\s*['\"]?([^,'\"}]+)", entry)
            if m:
                paths.append(m.group(1).strip())
    return paths


def _register_worker_id(ws: Path, claim_id: str) -> str | None:
    """claim-register.yaml 中该 claim 的 worker_id / last_dispatched_worker."""
    reg = ws / "claim-register.yaml"
    if not reg.exists() or not claim_id:
        return None
    try:
        text = reg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for m in _CLAIM_BLOCK_RE.finditer(text):
        if m.group(1).strip().strip("\"'") == claim_id:
            block = m.group(2)
            for key in ("worker_id", "last_dispatched_worker"):
                wm = re.search(rf"\b{key}:\s*(\S+)", block)
                if wm:
                    val = wm.group(1).strip().strip("\"'")
                    if val and val.lower() not in ("null", "none", "~", ""):
                        return val
            return None
    return None


# ===========================================================================
# 验证记录 (notes / facts 各自形状)
# ===========================================================================

def _note_verify_record(ws: Path, note_id: str) -> tuple[bool, str]:
    """note 的独立验证记录: runs/*-verify-*.md 引用该 note 且含正向裁决."""
    runs = ws / "runs"
    if not runs.is_dir():
        return False, "no runs/ directory"
    for f in sorted(runs.glob("*verify*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if note_id in f.name or note_id in text:
            if POSITIVE_VERDICT_RE.search(text):
                return True, (f"verify record {f.name} cites {note_id} "
                              f"with positive verdict")
            return False, (f"verify record {f.name} cites {note_id} but "
                           f"lacks a positive verdict (passes/CONFIRMED)")
    return False, f"no runs/*-verify-*.md record citing note {note_id}"


def _fact_runs_records(fid: str, ws: Path) -> tuple[bool, str]:
    """fact 的 runs/ 验证记录 (内容感知): redteam md 需 CONFIRMED + 引用 fact;
    verify-<fid>-*.json 需 overall=VERIFIED 或 l2 CONFIRMED
    (kunglao_verify.py L603-610 输出形状)."""
    runs = ws / "runs"
    if not runs.is_dir():
        return False, "no runs/ directory"
    for f in sorted(runs.glob("verify-redteam-*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if fid in text and POSITIVE_VERDICT_RE.search(text):
            return True, f"redteam record {f.name} (CONFIRMED) cites {fid}"
    for f in sorted(runs.glob(f"verify-{fid}-*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if (data.get("l2") or {}).get("verdict") == "CONFIRMED":
            return True, f"L2 redteam CONFIRMED in {f.name}"
        if data.get("overall") == "VERIFIED":
            return True, (f"L1 verify record {f.name} with independent "
                          f"anchor (overall=VERIFIED)")
    return False, ("no independent verifier record under runs/ "
                   "(verify-redteam-*.md with CONFIRMED citing the fact, or "
                   "verify-<fid>-*.json overall=VERIFIED / l2 CONFIRMED)")


def _verified_by_run_evidence(vbr: str, fid: str, ws: Path) -> tuple[bool, str]:
    """verified_by_run 必须指向实际存在的记录 (MEDIUM#2: 裸字符串不算).

    vbr 为路径/文件名形态 → 命名的记录必须在 runs/ 存在且含正向裁决;
    vbr 为验证者身份 → 该身份必须留有引用该 fact 的 runs 记录.
    """
    runs = ws / "runs"
    if not runs.is_dir():
        return False, "runs/ directory missing"
    if "/" in vbr or vbr.endswith((".md", ".json")):
        cands = [ws / vbr] if "/" in vbr else []
        cands.extend(sorted(runs.glob(f"*{vbr}*")))
        for cand in cands:
            if not cand.exists():
                continue
            try:
                text = cand.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if fid in text and POSITIVE_VERDICT_RE.search(text):
                return True, (f"verified_by_run={vbr} names existing record "
                              f"{cand.name} with positive verdict")
        return False, (f"names no runs record with a positive verdict "
                       f"citing {fid}")
    return _fact_runs_records(fid, ws)


# ===========================================================================
# R1: maker-checker — 盖章需独立验证者 (notes + facts)
# ===========================================================================

def _check_note(ws: Path, p: Path) -> list[dict]:
    """note 带 verify_status=passes 必须存在独立验证记录 (guardrails §1b)."""
    text = p.read_text(encoding="utf-8", errors="replace")
    fm = _parse_frontmatter(text)
    if str(fm.get("verify_status", "")).strip().lower() != "passes":
        return []
    note_id = str(fm.get("id", "")).strip() or p.stem
    ok, why = _note_verify_record(ws, note_id)
    if ok:
        return []
    return [{"rule": "R1", "file": f"notes/{p.name}",
             "detail": (f"verify_status=passes but {why} — passes must come "
                        f"from an independent verifier record (guardrails "
                        f"§1b; create-runs.py self-stamp shape)")}]


def _check_fact(ws: Path, p: Path) -> list[dict]:
    """fact 带 status ∈ {PROVEN, VERIFIED} 必须携带独立验证者证据 (R1+R2)."""
    text = p.read_text(encoding="utf-8", errors="replace")
    fm = _parse_frontmatter(text)
    status = str(fm.get("status", "")).strip().upper()
    if status not in FACT_VERIFIED_STATUSES:
        return []
    fid = str(fm.get("id", "")).strip() or p.stem
    claim_id = str(fm.get("claim_id", "")).strip()
    worker_id = _register_worker_id(ws, claim_id)
    recompute = _prov_recompute_paths(text)
    signoff = _parse_signoff(text)
    vbr = str(fm.get("verified_by_run", "")).strip()
    rel = f"facts/{p.name}"
    violations: list[dict] = []
    evidence: str | None = None

    if signoff:
        vid = signoff.get("verifier_id", "")
        verdict = (signoff.get("verdict") or "CONFIRMED").upper()
        if vid and verdict == "CONFIRMED":
            if worker_id and _same_actor(vid, worker_id, ws):
                violations.append({"rule": "R1", "file": rel, "detail": (
                    f"self-stamp: verifier_sign_off verifier_id={vid} equals "
                    f"worker_id {worker_id} (maker-checker §1b)")})
            elif recompute and any(_same_actor(vid, s, ws) for s in recompute):
                violations.append({"rule": "R1", "file": rel, "detail": (
                    f"verifier_sign_off verifier_id={vid} resolves to the "
                    f"producing script {recompute} — not independent")})
            else:
                evidence = f"verifier_sign_off verifier_id={vid} independent"
    if vbr:
        if any(str(fm.get(k, "")).strip() for k in EXPECTED_FIELDS):
            for s in recompute:
                if _same_actor(vbr, s, ws):
                    violations.append({"rule": "R2", "file": rel, "detail": (
                        f"self-verify: verified_by_run={vbr} resolves to "
                        f"producing script {s} — producer self-anchors its "
                        f"own expected (adapt-final.py pattern)")})
        ok, why = _verified_by_run_evidence(vbr, fid, ws)
        if ok:
            if evidence is None:
                evidence = why
        else:
            violations.append({"rule": "R1", "file": rel,
                               "detail": f"verified_by_run={vbr} but {why}"})
    if evidence is None:
        ok, why = _fact_runs_records(fid, ws)
        if ok:
            evidence = why
        else:
            violations.append({"rule": "R1", "file": rel, "detail": (
                f"status={status} but {why} (require verifier_sign_off from "
                f"a non-producer / verified_by_run with a real record / "
                f"runs verify record)")})
    return violations


# ===========================================================================
# R3: defer_reason 可回查 — "row N" 引用必须命中 decision-rights.md
# ===========================================================================

def decision_rows_from_text(text: str) -> set[int]:
    """解析 decision-rights.md 表格实际存在的行号 (首列为数字的 '| n | ...' 行)."""
    rows: set[int] = set()
    for line in text.splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|", line.strip())
        if m:
            rows.add(int(m.group(1)))
    return rows


def parse_decision_rights(path: Path) -> set[int]:
    """读文件 → 行号集合; 文件缺失 → 空集 (无治理层的工作区不审计)."""
    try:
        return decision_rows_from_text(
            path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return set()


def extract_row_references(text: str) -> list[int]:
    """抽取 decision-rights 行号引用 — 仅决策引用形态, 避免误报.

    两种形态: (1) 决策上下文引用 "decision-rights row N" / "治理行 N" /
    "决策矩阵 N"; (2) 行尾孤立的 "row N" (无后续描述文字, 如
    "blocked on row 99"). "row 5 of PE header table" 不命中 (行号后有
    描述文字且无决策上下文).
    """
    out: list[int] = []
    for m in _CONTEXT_ROW_RE.finditer(text):
        out.append(int(m.group(1) or m.group(2) or m.group(3)))
    for m in _STANDALONE_ROW_RE.finditer(text):
        out.append(int(m.group(1)))
    return sorted(set(out))


def _defer_reason_of_block(block: str) -> str | None:
    """claim 块内 defer_reason 值 (单行, 去引号); 无 → None."""
    dm = _DEFER_REASON_LINE_RE.search(block)
    if not dm:
        return None
    return dm.group(1).strip().strip("\"'")


def extract_claim_defer_reason(register_text: str, claim_id: str) -> str | None:
    """从 claim-register.yaml 原文抽取指定 claim 的 defer_reason."""
    for m in _CLAIM_BLOCK_RE.finditer(register_text):
        if m.group(1).strip().strip("\"'") == claim_id:
            return _defer_reason_of_block(m.group(2))
    return None


def _fmt_rows(rows: set[int]) -> str:
    return ", ".join(str(n) for n in sorted(rows))


def defer_reason_violations(claim_id: str, reason: str,
                            rows: set[int]) -> list[dict]:
    """单条 defer_reason 的引用校验: 命中不存在的行 → 违规记录列表."""
    bad = [n for n in extract_row_references(reason) if n not in rows]
    return [{"rule": "R3", "file": "claim-register.yaml", "claim_id": claim_id,
             "row": n,
             "detail": (f"defer_reason cites decision-rights row {n} which "
                        f"does not exist (rows: {_fmt_rows(rows) or '(none)'})")}
            for n in bad]


def check_workspace_defer_reasons(ws: Path) -> list[dict]:
    """扫描 claim-register.yaml 全部携带 defer_reason 的 claim (R3)."""
    reg_path = ws / "claim-register.yaml"
    if not reg_path.exists():
        return []
    rows = parse_decision_rights(ws / "references" / "decision-rights.md")
    text = reg_path.read_text(encoding="utf-8", errors="replace")
    out: list[dict] = []
    for m in _CLAIM_BLOCK_RE.finditer(text):
        claim_id = m.group(1).strip().strip("\"'")
        reason = _defer_reason_of_block(m.group(2))
        if reason:
            out.extend(defer_reason_violations(claim_id, reason, rows))
    return out


# ===========================================================================
# 审计入口 + CLI
# ===========================================================================

def audit_workspace(ws: Path) -> list[dict]:
    """全工作区写侧审计: R1+R2 (notes/ + facts/) + R3 (claim-register.yaml)."""
    violations: list[dict] = []
    notes_dir = ws / "notes"
    if notes_dir.is_dir():
        for p in sorted(notes_dir.glob("*.md")):
            if p.name == "_INDEX.md":
                continue
            violations.extend(_check_note(ws, p))
    facts_dir = ws / "facts"
    if facts_dir.is_dir():
        for p in sorted(facts_dir.glob("*.md")):
            if p.name == "_INDEX.md":
                continue
            violations.extend(_check_fact(ws, p))
    violations.extend(check_workspace_defer_reasons(ws))
    return violations


def main(argv: list[str] | None = None) -> int:
    """CLI: write_gate.py <ws> [--json]. 0 干净 / 1 违规 / 2 用法错误."""
    ap = argparse.ArgumentParser(description="write_gate — 写侧门禁审计器 (#236)")
    ap.add_argument("ws", nargs="?", type=Path, help="workspace root")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    args = ap.parse_args(argv)
    if args.ws is None:
        ap.print_help()
        return 2
    violations = audit_workspace(args.ws)
    if args.json:
        print(json.dumps({"ok": not violations, "violations": violations},
                         indent=2, ensure_ascii=False))
    else:
        for v in violations:
            print(f"[{v['rule']}] {v['file']}: {v['detail']}")
        if violations:
            print(f"write-gate: {len(violations)} violation(s) in "
                  f"workspace {args.ws}")
        else:
            print(f"write-gate: clean ({args.ws})")
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
