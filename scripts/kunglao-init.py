#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-init — workspace 初始化 + 防二次初始化 (phase 3.5, E-init.1-4).

独立 CLI(非 kunglao.py 子命令, module-design L448):
    python kunglao-init.py <workspace> [--force] [--hooks-json <path>]

三阶段防重状态机:
    Phase 1 存在性检查: claim-register.yaml 含 `[initialized]` 标记 → 续接模式
        - state_hash 无漂移 → exit 0, 输出 "resume"
        - state_hash 漂移(外部编辑) → stderr WARNING(drift), 仍 exit 0 续接
    Phase 2 全新初始化: scaffold(analysis_state.txt / global_plan.txt / runs/ 等)
        + 3-5 条样本级 seed claims(C-001 样本概览 / C-002 家族归属 / C-003 打包器)
        + hooks 幂等部署
    Phase 3 幂等校验: 标记存在 + seed 计数; 重跑不重复 seed / 不重复部署 hooks

state_hash = sha256(claim-register.yaml 内容(state_hash 字段归一化) + facts/_INDEX.md
            内容 + facts/ 目录文件清单按名排序拼接) — 记入 [initialized] 标记。

hooks 部署边界(硬约束): 绝不写生产 ~/.claude/settings.json。只写:
    - `--hooks-json <path>` 指定的 settings.json 副本(不存在则创建), 或
    - <workspace>/.claude/settings.json(若存在)
    两者皆无 → 跳过部署(输出说明), 不碰 HOME。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

MARKER = "[initialized]"
SEED_MIN = 3
HOOK_FILES = ("worker_budget.py",)  # DESIGN §7 0.3: PreToolUse + PostToolUse → worker_budget
HASH_RE = re.compile(r"state_hash=([0-9a-f]{64})")

SCAFFOLD_DIRS = ("facts", "blockers", "runs")
SCAFFOLD_FILES = {
    "analysis_state.txt": "# analysis_state — kunglao-init scaffold(空结构段, DESIGN §7 0.4)\n",
    "global_plan.txt": "# global_plan — kunglao-init v1 stub\n",
    "claim_deps.yaml": "depends_on: {}\n",
    "task_spec_snapshot.yaml": "{}\n",
    "facts/_INDEX.md": "# _INDEX\n",
}


def utc_now() -> str:
    """UTC ISO-8601 秒级, Z 后缀(与 hooks_selfcheck 同款)."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def atomic_write(path: Path, text: str) -> None:
    """M0.2 store_atomic: 写 temp → rename(崩溃安全)."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="kunglao-init",
        description="workspace 初始化 + 防二次初始化(独立 CLI, 非 kunglao.py 子命令)",
    )
    parser.add_argument("workspace", help="目标 workspace 路径(含 bins/ claim-register.yaml 等)")
    parser.add_argument("--force", action="store_true",
                        help="重建: 先备份 claim-register 再重新初始化")
    parser.add_argument("--hooks-json", metavar="PATH", default=None,
                        help="hooks 部署目标 settings.json 副本; 默认 <workspace>/.claude/settings.json 若存在, 绝不写 HOME")
    return parser.parse_args(argv)


def normalize_marker(text: str) -> str:
    """归一化 [initialized] 标记里的 state_hash 字段(自一致性哈希)."""
    return HASH_RE.sub("state_hash=", text)


def extract_hash(text: str) -> str | None:
    """从 [initialized] 标记读出记录的 state_hash."""
    m = HASH_RE.search(text)
    return m.group(1) if m else None


def compute_state_hash(ws: Path, register_text: str | None = None) -> str:
    """state_hash = sha256(claim-register 归一化内容 + facts/_INDEX.md 内容 + facts/ 文件清单).

    文件清单 = facts/ 下文件名按名排序拼接(design 契约口径).
    """
    h = hashlib.sha256()
    if register_text is not None:
        h.update(b"claim-register.yaml:" + normalize_marker(register_text).encode("utf-8"))
    else:
        reg = ws / "claim-register.yaml"
        if reg.exists():
            h.update(b"claim-register.yaml:" + normalize_marker(reg.read_text(encoding="utf-8")).encode("utf-8"))
    facts = ws / "facts"
    idx = facts / "_INDEX.md"
    if idx.exists():
        h.update(b"_INDEX.md:" + idx.read_bytes())
    if facts.is_dir():
        names = sorted(p.name for p in facts.iterdir() if p.is_file())
        h.update(b"facts-manifest:" + "\n".join(names).encode("utf-8"))
    return h.hexdigest()


def seed_claims(sample: str) -> list[dict]:
    """3-5 条样本级 seed claims(DESIGN §7 0.9): C-001 概览 / C-002 归属 / C-003 打包器."""
    return [
        {"id": "C-001", "status": "OPEN", "boundary_type": "positive_observation",
         "evidence_tier_attempted": 0, "promotion_attempts": 0, "depends_on": [],
         "title": f"样本概览 — {sample} 的语言/架构/打包器静态识别"},
        {"id": "C-002", "status": "OPEN", "boundary_type": "positive_observation",
         "evidence_tier_attempted": 0, "promotion_attempts": 0, "depends_on": ["C-001"],
         "title": f"家族归属 — {sample} 的家族/行为类(CTI 假设, 需 artifact 指纹升 confirmed)"},
        {"id": "C-003", "status": "OPEN", "boundary_type": "positive_observation",
         "evidence_tier_attempted": 0, "promotion_attempts": 0, "depends_on": ["C-001"],
         "title": f"打包器/混淆 — {sample} 是否加壳或 garble 控制流混淆"},
    ]


def claim_register_text(sample: str, sample_sha: str, state_hash: str) -> str:
    """完整 claim-register.yaml 文本: [initialized] 标记头 + seed claims 体."""
    claims = seed_claims(sample)
    lines = [
        f"# [initialized] kunglao-init state_hash={state_hash} seeds={len(claims)} sample={sample}",
        f"# sha256={sample_sha} ts={utc_now()}",
        "# kunglao-init seed claims — 样本级起点 claim (DESIGN §7 0.9)",
        "claims:",
    ]
    for c in claims:
        lines.append(f"- id: {c['id']}")
        lines.append(f"  status: {c['status']}")
        lines.append(f"  boundary_type: {c['boundary_type']}")
        lines.append(f"  evidence_tier_attempted: {c['evidence_tier_attempted']}")
        lines.append(f"  promotion_attempts: {c['promotion_attempts']}")
        lines.append(f"  depends_on: {c['depends_on']}")
        lines.append(f"  title: \"{c['title']}\"")
    return "\n".join(lines) + "\n"


def detect_sample(ws: Path) -> tuple[str, str]:
    """bins/ 下第一个文件(按名排序)作为样本: (文件名, sha256). 缺样本 → ("unknown", "")."""
    bins = ws / "bins"
    if not bins.is_dir():
        return "unknown", ""
    files = sorted(p for p in bins.iterdir() if p.is_file())
    if not files:
        return "unknown", ""
    sample = files[0]
    try:
        sha = hashlib.sha256(sample.read_bytes()).hexdigest()
    except OSError:
        sha = ""
    return sample.name, sha


def scaffold(ws: Path) -> list[Path]:
    """幂等 scaffold(DESIGN §7 0.4): 目录 mkdir; 文件存在且非空则跳过(不 clobber)."""
    created: list[Path] = []
    for name in SCAFFOLD_DIRS:
        d = ws / name
        if not d.is_dir():
            d.mkdir(parents=True)
            created.append(d)
    for name, stub in SCAFFOLD_FILES.items():
        p = ws / name
        if p.exists() and p.read_text(encoding="utf-8").strip():
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(p, stub)
        created.append(p)
    return created


def _ensure(entries: list, matcher: str, hook_file: str, hook_dir: Path) -> tuple[list, bool]:
    """同 matcher 下已有同名 hook 命令 → 跳过(幂等); 否则追加."""
    new = [e for e in entries if e.get("matcher") == matcher]
    other = [e for e in entries if e.get("matcher") != matcher]
    command = f"python {(hook_dir / hook_file).as_posix()}"
    for e in new:
        for h in e.get("hooks", []):
            if h.get("command", "").replace("\\", "/").rsplit("/", 1)[-1] == hook_file:
                return other + new, False
    new.append({"matcher": matcher, "hooks": [{"type": "command", "command": command}]})
    return other + new, True


def _patch_settings(path: Path) -> int:
    """把 kunglao hook 合并进 settings.json(保其他键), 返回新增条目数."""
    existing: dict = {}
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise RuntimeError(f"settings.json 无法解析: {path} ({exc})") from exc
    hooks = existing.get("hooks") or {}
    pre = hooks.get("PreToolUse") or []
    post = hooks.get("PostToolUse") or []
    hook_dir = Path(__file__).resolve().parent.parent / "hooks"
    count = 0
    for event, matcher, hook_file in (
        ("PreToolUse", "Agent", HOOK_FILES[0]),
        ("PostToolUse", "Agent", HOOK_FILES[0]),
    ):
        entries, added = _ensure(pre if event == "PreToolUse" else post, matcher, hook_file, hook_dir)
        if event == "PreToolUse":
            pre = entries
        else:
            post = entries
        count += added
    hooks["PreToolUse"] = pre
    hooks["PostToolUse"] = post
    existing["hooks"] = hooks
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(existing, indent=2, ensure_ascii=False))
    return count


def deploy_hooks(ws: Path, hooks_json: Path | None) -> dict:
    """hooks 幂等部署(E-init.2)。目标: --hooks-json 副本, 或 <ws>/.claude/settings.json(若存在).

    默认不部署到 HOME — 两者皆无则跳过并说明.
    """
    if hooks_json is not None:
        target = Path(hooks_json).resolve()
    else:
        target = ws / ".claude" / "settings.json"
        if not target.exists():
            return {"deployed": False, "target": None,
                    "reason": "no <workspace>/.claude/settings.json (HOME settings never written)"}
    added = _patch_settings(target)
    return {"deployed": True, "target": str(target), "added": added}


def backup_register(path: Path) -> Path:
    """--force 重建前备份 claim-register(E-init.4): claim-register.yaml.bak-<ts>."""
    ts = utc_now().replace(":", "-")
    backup = path.with_name(f"{path.name}.bak-{ts}")
    shutil.copy2(path, backup)
    return backup


def resume(ws: Path, text: str) -> int:
    """Phase 1 续接模式: 无漂移 exit 0; 漂移 → stderr WARNING 仍 exit 0."""
    recorded = extract_hash(text)
    current = compute_state_hash(ws)
    if recorded and current != recorded:
        print(f"kunglao-init: WARNING state drift detected (recorded {recorded}, computed {current}) — external edits present",
              file=sys.stderr)
    print(f"kunglao-init: resume — {ws} already initialized")
    return 0


def initialize(ws: Path, hooks_json: Path | None) -> int:
    """Phase 2 全新初始化 + Phase 3 幂等校验."""
    scaffold(ws)
    sample, sample_sha = detect_sample(ws)
    draft = claim_register_text(sample, sample_sha, state_hash="")
    digest = compute_state_hash(ws, register_text=draft)
    reg = ws / "claim-register.yaml"
    atomic_write(reg, claim_register_text(sample, sample_sha, state_hash=digest))

    written = reg.read_text(encoding="utf-8")
    seed_count = written.count("id: C-")
    if MARKER not in written or seed_count < SEED_MIN:
        print("kunglao-init: FATAL verify failed — marker or seeds missing after init", file=sys.stderr)
        return 2
    hook_report = deploy_hooks(ws, hooks_json)

    print(f"kunglao-init: initialized {ws} (seed_claims={seed_count} sample={sample})")
    print(f"kunglao-init: state_hash={digest}")
    if hook_report["deployed"]:
        print(f"kunglao-init: hooks -> {hook_report['target']} ({hook_report['added']} entries, idempotent)")
    else:
        print(f"kunglao-init: hooks skipped — {hook_report['reason']}")
    return 0


def run(ws: Path, force: bool = False, hooks_json: Path | None = None) -> int:
    """状态机入口: 防重检查 → (续接 | --force 备份+重建 | 全新初始化)."""
    ws = Path(ws).resolve()
    reg = ws / "claim-register.yaml"
    if reg.exists() and not force:
        text = reg.read_text(encoding="utf-8")
        if MARKER in text:
            return resume(ws, text)
    if force and reg.exists():
        backup = backup_register(reg)
        print(f"kunglao-init: --force backup -> {backup}")
    return initialize(ws, hooks_json)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(Path(args.workspace), force=args.force, hooks_json=args.hooks_json)


if __name__ == "__main__":
    sys.exit(main())
