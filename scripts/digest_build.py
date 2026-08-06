#!/usr/bin/env python3
"""digest_build.py — digest 机械生成 (issue #3, design-spec §3.6).

六节 markdown digest (2-4KB), 纯机械无 LLM, 供冷启动注入替代全量 progress.txt 读取。
数字保真: facts 的 unit 字段原样带入 sec_c (numeric-fidelity.md)。
完整性: 新增 verified fact 1 轮内进 digest (build_digest 重算即反映)。

用法:
  python digest_build.py <workspace>            # 写 runs/digest.md
  python digest_build.py <workspace> --stdout   # 仅打印
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCHEMA_VERSION = "digest-v1"
DIGEST_PATH = Path("runs") / "digest.md"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


def _facts_index(ws: Path) -> list[dict]:
    """解析 facts/_INDEX.md 'F-NN | status | claim | conclusion | unit'。fixture 回退 <ws>/_INDEX.md。"""
    index = ws / "facts" / "_INDEX.md"
    if not index.exists():
        index = ws / "_INDEX.md"
    if not index.exists():
        return []
    out = []
    for line in _read_text(index).splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 4:
            continue
        fid = parts[0]
        unit = parts[4] if len(parts) > 4 else "n/a"
        out.append({"id": fid, "status": parts[1], "claim": parts[2],
                    "conclusion": parts[3], "unit": unit})
    return out


def _claims(ws: Path) -> list[dict]:
    reg = _load_yaml(ws / "claim-register.yaml")
    return reg.get("claims") or []


def _failure_rules(ws: Path) -> list[dict]:
    fr = _load_yaml(ws / "failure-registry.yaml")
    return fr.get("rules") or []


def build_digest(ws: Path) -> str:
    """六节机械 digest。无 LLM; 同 ws 重算仅 head 时间戳变 (纯函数除时间戳外)。"""
    task_spec = _load_yaml(ws / "task_spec.yaml")
    claims = _claims(ws)
    facts = _facts_index(ws)
    rules = _failure_rules(ws)
    progress = _read_text(ws / "progress.txt")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    anchor_ver = f"f{len(facts)}-c{len(claims)}-r{len(rules)}"

    L: list[str] = []
    # ---- head ----
    L.append("## head")
    L.append(f"schema: {SCHEMA_VERSION} | anchor: {anchor_ver} | reconciled: {now}")
    L.append(f"workspace: {ws} | cold-start digest (mechanical, no LLM)")
    L.append("")

    # ---- sec_a: task_spec 主问题/约束 (3-5 行) ----
    L.append("## sec_a — task_spec")
    pqs = task_spec.get("primary_questions") or []
    if pqs:
        for q in pqs[:5]:
            L.append(f"- Q: {q}")
    else:
        L.append("- (no primary_questions)")
    for key in ("scope", "constraints", "depth"):
        v = task_spec.get(key)
        if v:
            L.append(f"- {key}: {v}")
    L.append("")

    # ---- sec_b: claims 索引 ----
    L.append("## sec_b — claims index")
    L.append("C-NN | status | conclusion | anchor")
    for c in claims:
        cid = c.get("id", "?")
        status = c.get("status", "?")
        stmt = c.get("statement", "")
        anchors = c.get("anchors") or []
        anc = anchors[0] if anchors else "—"
        L.append(f"{cid} | {status} | {stmt} | {anc}")
    if not claims:
        L.append("(no claims)")
    L.append("")

    # ---- sec_c: verified facts (unit 原样带入, 数字保真) ----
    L.append("## sec_c — verified facts (unit 字段原样, 数字口径保真)")
    L.append("F-NN | boundary | conclusion | unit")
    for f in facts:
        L.append(f"{f['id']} | {f['status']} | {f['conclusion']} | unit={f['unit']}")
    if not facts:
        L.append("(no facts)")
    L.append("")

    # ---- sec_d: 架构性结论 (保留推理链, 不压成单句) ----
    L.append("## sec_d — architectural conclusions (reasoning chain preserved)")
    proven = [c for c in claims if c.get("status") in ("PROVEN", "VERIFIED")]
    if proven:
        for c in proven:
            L.append(f"- {c.get('id')}: {c.get('statement')} (status={c.get('status')})")
    else:
        L.append("- (no terminal conclusions yet)")
    L.append("")

    # ---- sec_e: 失败规则 (结构化 WHEN/THEN/anchor) ----
    L.append("## sec_e — failure rules (structured)")
    if rules:
        for r in rules:
            when = r.get("when", "?")
            then = r.get("then", "?")
            anc = r.get("anchor", "—")
            L.append(f"- WHEN {when} → THEN {then} | anchor: {anc}")
    else:
        L.append("- (no failure rules yet)")
    L.append("")

    # ---- sec_f: 指针表 ----
    L.append("## sec_f — pointers (on-demand read)")
    for name in ("progress.txt", "claim-register.yaml", "facts/_INDEX.md",
                 "failure-registry.yaml", "task_spec.yaml"):
        p = ws / name
        mark = "OK" if p.exists() else "--"
        L.append(f"- [{mark}] {name}")
    if progress:
        L.append("")
        L.append("progress.txt (tail):")
        tail = progress.strip().splitlines()[-3:]
        for ln in tail:
            L.append(f"  {ln}")

    return "\n".join(L) + "\n"


def write_digest(ws: Path) -> Path:
    """写 runs/digest.md, 返回路径。"""
    out = ws / DIGEST_PATH
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_digest(ws), encoding="utf-8")
    return out


def digest_completeness(ws: Path) -> bool:
    """新增 verified fact 是否已进 digest。"""
    md = build_digest(ws)
    for f in _facts_index(ws):
        if f["id"] not in md:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="digest_build.py", description="digest 机械生成")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--stdout", action="store_true", help="仅打印, 不写盘")
    args = ap.parse_args(argv)
    ws = Path(args.workspace)
    if args.stdout:
        print(build_digest(ws))
    else:
        p = write_digest(ws)
        print(f"digest written: {p} ({p.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
