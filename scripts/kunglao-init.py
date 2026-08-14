#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao-init — workspace 初始化 + 防二次初始化 (phase 3.5, E-init.1-4).

独立 CLI(非 kunglao.py 子命令, module-design L448):
    python kunglao-init.py <workspace> [--type windows|linux|android] [--force]
        [--hooks-json <path>] [--profile-root <path>]

#304 type-aware extension:
    --type explicit > magic sniff (MZ/ELF/PK+classes.dex on bins/ first file)
    > interactive input() confirm with sniff default
    类型落盘 analysis_state.txt project_type=<type>; 模板按型选择
    Init-completeness = [initialized] marker AND project_type declared

#304 修正(comment 304-5289955958): 工具链验证 = 验证优先 + 提醒人类 + 拒绝 + 清理
    流程: Phase 0 flag 守卫 → 续接检查 → 无样本友好提示(exit 5) → 类型判定 →
    toolchain.check 前置(HARD 项) → FAIL: 逐项安装命令 + 拒绝(exit 4) + 清理
    清理只移除本次运行自己创建的条目(cleanup_scaffold, created 清单) —
    非本次创建的一律不删(真实 facts/ 内容必须存活, F2)。
    PASS 才 scaffold + [initialized]。
    --skip-toolchain 为测试/运维逃生口; 生产路径不跳过。

#304 修正 2 (review F1): [initialized] 标记存在但缺 project_type 的 pre-#304
    workspace → 不再直接 resume exit 0(env_check_gate 会永久拒绝, 无机械修复
    路径), 而是写 project_type(显式 > 状态 > 嗅探 > 确认)后再 exit 0。

Init-completeness 谓词(F6): scripts/init_state.py 单一来源, 本文件引用。


Phase 0 (#276): 环境守卫 — CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS 默认 0 化。
    - 进程 env 该 flag 为 truthy(1/true/yes/on) → HARD 拒绝 scaffold(exit 3),
      修复指引: unset 后重启会话, 勿用 teammate 通道
    - unset/0 → 会话内 os.environ[flag]="0" + analysis_state.txt 写
      agent_teams_flag=0 (default disabled)
    - 纳入设置: 通过 shell_defaults.apply 确保现存用户 PowerShell profile
      (Documents/PowerShell 与 Documents/WindowsPowerShell) 含
      CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=0, 动作记录到 init 输出
      (--profile-root 可注入, 测试用; 默认 Path.home())

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
import os
import re
import shutil
import sys
from collections.abc import Collection
from pathlib import Path

# #276: 可复用 CLI 管理 shell 环境默认行(禁止内联)。按仓库惯例先注入 scripts/ 到
# sys.path 再 import 兄弟模块(兼容 `python -m` 等非直跑调用方式)。
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))
import shell_defaults  # noqa: E402
import toolchain  # noqa: E402  # #304: type-aware toolchain probes (check-before-scaffold gate)
# F6 (#304 review): init-completeness predicate = single source in init_state.py
from init_state import VALID_TYPES, is_init_complete, read_project_type  # noqa: E402
import mcp_probe  # noqa: E402  (#316: MCP supply manifest/scaffold 单一事实源)

MARKER = "[initialized]"
SEED_MIN = 3
HOOK_FILES = ("worker_budget.py",)  # DESIGN §7 0.3: PreToolUse + PostToolUse → worker_budget
HASH_RE = re.compile(r"state_hash=([0-9a-f]{64})")

FLAG_NAME = "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS"  # #276: 默认 0 化
AGENT_TEAMS_STATE_LINE = "agent_teams_flag=0 (default disabled)"

# #304 amendment exit codes (callers branch on codes, not stderr text):
RC_OK = 0
RC_ERROR = 1        # generic (argparse / fatal verify)
RC_FATAL_VERIFY = 2  # post-init idempotency verify failed
RC_FLAG_REJECT = 3   # Phase 0 (#276) agent-teams flag truthy
RC_TOOLCHAIN_REFUSE = 4  # toolchain HARD FAIL — human must install, no scaffold
RC_NO_SAMPLE = 5     # bins/ empty — friendly prompt (请将样本放入 bins/)

SCAFFOLD_DIRS = ("facts", "blockers", "runs")
SCAFFOLD_FILES = {
    "analysis_state.txt": (
        "# analysis_state — kunglao-init scaffold(空结构段, DESIGN §7 0.4)\n"
        f"{AGENT_TEAMS_STATE_LINE}\n"
    ),
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
    parser.add_argument("--type", choices=VALID_TYPES, default=None,
                        help="project type: windows|linux|android (#304)")
    parser.add_argument("--force", action="store_true",
                        help="重建: 先备份 claim-register 再重新初始化")
    parser.add_argument("--skip-toolchain", action="store_true",
                        help="跳过 toolchain 前置门禁(#304 修正的测试/运维逃生口; "
                             "生产路径不跳过)")
    parser.add_argument("--hooks-json", metavar="PATH", default=None,
                        help="hooks 部署目标 settings.json 副本; 默认 <workspace>/.claude/settings.json 若存在, 绝不写 HOME")
    parser.add_argument("--profile-root", metavar="PATH", default=None,
                        help="profile 根目录(默认 Path.home(); 测试可注入; #276)")
    parser.add_argument("--no-mcp", action="store_true",
                        help="跳过工作区 .mcp.json scaffold (#316)")
    return parser.parse_args(argv)


def is_truthy(value: str | None) -> bool:
    """Truthy 判定: 1/true/yes/on, 不区分大小写 (#276 默认 0 化语义)."""
    return value is not None and value.strip().lower() in ("1", "true", "yes", "on")


def profile_candidates(profile_root: Path | None = None) -> list[Path]:
    """用户 PowerShell profile 候选(Documents/PowerShell 与 Documents/WindowsPowerShell)."""
    root = Path(profile_root) if profile_root is not None else Path.home()
    docs = root / "Documents"
    return [
        docs / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
        docs / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1",
    ]


def guard_agent_teams(profile_root: Path | None = None) -> tuple[int, list[str]]:
    """Phase 0 (#276): flag 环境守卫.

    - 进程 env 该 flag truthy → HARD 拒绝(exit 3), 不 scaffold, 附修复指引:
      unset 后重启会话; 勿用 teammate 通道
    - unset/0 → 会话内 os.environ[flag]="0" + 现存 PowerShell profile 经
      shell_defaults.apply 纳入 CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=0
    Returns (exit_code, log_lines).
    """
    log: list[str] = []
    val = os.environ.get(FLAG_NAME)
    if is_truthy(val):
        log.append(
            f"kunglao-init: HARD REJECT — {FLAG_NAME} is truthy ({val!r}); "
            f"scaffold blocked. Fix: unset {FLAG_NAME} in the launching shell "
            f"and RESTART this session; do NOT dispatch through the teammate "
            f"channel (kunglao #88, 2026-08-12 incident)."
        )
        return 3, log
    os.environ[FLAG_NAME] = "0"
    log.append(f"kunglao-init: env {FLAG_NAME}=0 (default disabled)")
    found = False
    for profile in profile_candidates(profile_root):
        if not profile.exists():
            continue
        found = True
        result = shell_defaults.apply(profile, FLAG_NAME, "0", shell="powershell")
        log.append(f"kunglao-init: profile {profile}: {result['change']}")
    if not found:
        log.append("kunglao-init: no PowerShell profile found — profile write skipped")
    return 0, log


def ensure_agent_teams_state(ws: Path) -> bool:
    """analysis_state.txt 记录 agent_teams_flag=0 (default disabled); 缺失则追加."""
    p = ws / "analysis_state.txt"
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    if "agent_teams_flag=" in text:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    if text and not text.endswith("\n"):
        text += "\n"
    atomic_write(p, text + f"{AGENT_TEAMS_STATE_LINE}\n")
    return True


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


def sniff_type(ws: Path) -> str | None:
    """Magic sniff: read first bins/ file headers → windows|linux|android or None."""
    bins = ws / "bins"
    if not bins.is_dir():
        return None
    files = sorted(p for p in bins.iterdir() if p.is_file())
    if not files:
        return None
    sample = files[0]
    try:
        header = sample.read_bytes()[:512]
    except OSError:
        return None
    # PK zip (APK) + classes.dex marker
    if header[:4] == b"PK\x03\x04" and b"classes.dex" in header:
        return "android"
    # ELF
    if header[:4] == b"\x7fELF":
        return "linux"
    # PE (MZ)
    if header[:2] == b"MZ":
        return "windows"
    return None


def prompt_type(default: str | None = None) -> str:
    """Interactive type prompt (only human step in init-worker flow)."""
    hint = f" [{default}]" if default else ""
    while True:
        try:
            raw = input(f"Project type{hint} (windows|linux|android): ").strip().lower()
        except EOFError:
            if default:
                return default
            print("kunglao-init: ERROR cannot determine type (non-interactive, no --type, no sniff)",
                  file=sys.stderr)
            sys.exit(1)
        if raw and raw in VALID_TYPES:
            return raw
        if not raw and default and default in VALID_TYPES:
            return default
        print(f"Invalid type: {raw!r}. Choose: windows, linux, android")


def resolve_type(ws: Path, explicit: str | None) -> str:
    """Type resolution: explicit > sniff > interactive confirm.
    Returns the resolved type string.
    """
    if explicit:
        return explicit
    sniffed = sniff_type(ws)
    if sniffed:
        # Sniff succeeded — confirm with user
        try:
            raw = input(f"Detected type: {sniffed}. Confirm? [Y/n]: ").strip().lower()
            if raw in ("n", "no"):
                return prompt_type(default=sniffed)
        except EOFError:
            pass  # Non-interactive: accept sniff
        return sniffed
    # No sniff result — interactive prompt
    return prompt_type()


def write_project_type(ws: Path, project_type: str) -> bool:
    """Write project_type=<type> to analysis_state.txt. Returns True if written."""
    p = ws / "analysis_state.txt"
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    if "project_type=" in text:
        # Already has project_type — update it
        lines = text.splitlines()
        new_lines = []
        for line in lines:
            if line.strip().startswith("project_type="):
                new_lines.append(f"project_type={project_type}")
            else:
                new_lines.append(line)
        atomic_write(p, "\n".join(new_lines))
        return True
    # Append
    if text and not text.endswith("\n"):
        text += "\n"
    atomic_write(p, text + f"project_type={project_type}\n")
    return True


def template_for_type(project_type: str) -> Path:
    """Select CLAUDE.md template by project type."""
    tmpl = SKILL_DIR / "templates" / f"CLAUDE.md.{project_type}.tmpl"
    if tmpl.exists():
        return tmpl
    # Fallback to the generic template
    return CLAUDEMD_TMPL


CLAUDEMD_TMPL = Path(__file__).resolve().parent.parent / "templates" / "CLAUDE.md.tmpl"
SKILL_DIR = Path(__file__).resolve().parent.parent


def write_claudemd(ws: Path, sample_name: str, sample_sha: str,
                  project_type: str | None = None) -> Path | None:
    """Write CLAUDE.md from template with project info filled in.

    Idempotent: if CLAUDE.md exists and is non-empty, skip (do not clobber).
    Returns the written path or None if skipped.
    """
    target = ws / "CLAUDE.md"
    if target.exists() and target.read_text(encoding="utf-8").strip():
        return None
    # Select template by type (#304)
    if project_type:
        tmpl_path = template_for_type(project_type)
    else:
        tmpl_path = CLAUDEMD_TMPL
    if not tmpl_path.exists():
        return None
    tmpl = tmpl_path.read_text(encoding="utf-8")

    # Detect venv path
    venv_candidate = ws / ".venv"
    venv_path = str(venv_candidate) if venv_candidate.exists() else ".venv/"

    # Detect Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    text = (
        tmpl
        .replace("<SAMPLE_SHA1>", sample_name)
        .replace("<SAMPLE_SHA256>", sample_sha)
        .replace("<SAMPLE_TYPE>", "(detected at analysis time)")
        .replace("<SAMPLE_PATH>", f"bins/{sample_name}")
        .replace("<SKILL_DIR>", str(SKILL_DIR))
        .replace("<VENV_PATH>", venv_path)
    )
    # Append Python version note to the venv section
    text = text.replace(
        "Activate before running scripts.",
        f"Activate before running scripts. Python {py_version}."
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(target, text)
    return target


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


def scaffold_mcp(ws: Path) -> str:
    """#316: 工作区 .mcp.json scaffold (MCP 供给清单模板).

    幂等: 文件已存在 → 不覆盖 (返回 "exists"); 否则写入 mcp_probe 构建的
    合法 JSON (mcpServers 留空, mcp_manifest 携带 per-type 清单 + 每项
    用途/来源/注册命令模板)。
    """
    target = ws / ".mcp.json"
    if target.exists():
        return "exists"
    text = json.dumps(mcp_probe.build_scaffold_json(), indent=2, ensure_ascii=False)
    atomic_write(target, text + "\n")
    return "created"


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


def initialize(ws: Path, hooks_json: Path | None,
                project_type: str | None = None, no_mcp: bool = False) -> int:
    """Phase 2 全新初始化 + Phase 3 幂等校验."""
    scaffold(ws)
    if ensure_agent_teams_state(ws):
        print(f"kunglao-init: analysis_state {AGENT_TEAMS_STATE_LINE}")
    sample, sample_sha = detect_sample(ws)

    # #304: Resolve and write project type
    if project_type is None:
        # Try to read existing type from analysis_state.txt
        existing_type = read_project_type(ws)
        if existing_type:
            project_type = existing_type
        else:
            # No type yet — resolve
            project_type = resolve_type(ws, None)
    write_project_type(ws, project_type)
    print(f"kunglao-init: project_type={project_type}")

    # Write CLAUDE.md from type-specific template (idempotent: skip if exists)
    write_claudemd(ws, sample, sample_sha, project_type=project_type)
    # #316: workspace .mcp.json MCP supply scaffold (idempotent; --no-mcp skips)
    if no_mcp:
        print("kunglao-init: .mcp.json skipped (--no-mcp)")
    else:
        outcome = scaffold_mcp(ws)
        if outcome == "created":
            print("kunglao-init: .mcp.json created (MCP supply scaffold, #316)")
        else:
            print("kunglao-init: .mcp.json skipped (exists — idempotent, not overwritten)")
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


def run(ws: Path, force: bool = False, hooks_json: Path | None = None,
        profile_root: Path | None = None,
        project_type: str | None = None,
        skip_toolchain: bool = False, no_mcp: bool = False) -> int:
    """状态机入口 (#304 修正流程, comment 304-5289955958):

    Phase 0 环境守卫 → 防重检查(续接; 缺 project_type 则升级补写后 exit 0,
    F1) → 无样本友好提示 → 类型判定(显式 > 嗅探 > 确认) →
    **toolchain.check 前置**(HARD FAIL → 逐项安装指引 + 拒绝 + 清理本次运行
    创建的产物; 既有内容一律保留, F2) →
    PASS 才 scaffold + 标记 [initialized] + project_type。
    """
    guard_rc, guard_log = guard_agent_teams(profile_root)
    if guard_rc != 0:
        for line in guard_log:  # HARD REJECT 指引走 stderr
            print(line, file=sys.stderr)
        return guard_rc
    for line in guard_log:
        print(line)
    ws = Path(ws).resolve()
    reg = ws / "claim-register.yaml"
    if reg.exists() and not force:
        text = reg.read_text(encoding="utf-8")
        if MARKER in text:
            if is_init_complete(ws):
                return resume(ws, text)
            # F1 (#304 review): marker present but project_type missing
            # (pre-#304 workspace). resume() alone would exit 0 forever and
            # env_check_gate would keep rejecting — no mechanical repair path.
            # Write the missing type (explicit > state > sniff > confirm)
            # and exit 0; register/marker/seeds untouched.
            if project_type is None:
                existing = read_project_type(ws)
                if existing and existing in VALID_TYPES:
                    project_type = existing
                else:
                    project_type = resolve_type(ws, None)
            write_project_type(ws, project_type)
            print(
                f"kunglao-init: upgraded {ws} — wrote project_type={project_type} "
                f"(pre-#304 workspace: [initialized] without project_type)"
            )
            return 0
    if force and reg.exists():
        backup = backup_register(reg)
        print(f"kunglao-init: --force backup -> {backup}")

    # #304: no-sample cold start -> friendly prompt, refuse (exit 5)
    sample, sample_sha = detect_sample(ws)
    if sample == "unknown" or not sample_sha:
        print(
            "kunglao-init: 未发现分析对象 — 请将样本放入 bins/ 或指定路径, "
            "然后重新运行 kunglao-init.py <ws> --type <windows|linux|android>.",
            file=sys.stderr,
        )
        return RC_NO_SAMPLE

    # Type resolution BEFORE any file is written (explicit > state > sniff > confirm)
    if project_type is None:
        existing = read_project_type(ws)
        if existing and existing in VALID_TYPES:
            project_type = existing
        else:
            project_type = resolve_type(ws, None)

    # #304: toolchain.check BEFORE scaffold — HARD FAIL => refuse + cleanup.
    # Verify-first: a refused init leaves no half-initialized state behind.
    if not skip_toolchain:
        report = toolchain.check(ws, project_type)
        if report.overall_status == toolchain.Status.FAIL:
            return refuse_toolchain(ws, report)

    return initialize(ws, hooks_json, project_type=project_type, no_mcp=no_mcp)


def cleanup_scaffold(ws: Path, created: "Collection[Path] | None" = None
                     ) -> tuple[list[str], list[str]]:
    """#304 修正 (F2): 只删除本次运行自己创建的 scaffold 条目(created 清单)。

    非本次创建的一律不删 — 已有文件 / 非空目录拒绝删除并列入 preserved
    (真实 facts/ 内容必须存活; 与成功 --force 保留 facts 的行为对称)。
    bins/、CLAUDE.md、claim-register.yaml、.claude/、.venv/ 不在候选集内。

    Returns (removed, preserved) 路径名列表。
    """
    created_set = {Path(p).resolve() for p in (created or ())}
    removed: list[str] = []
    preserved: list[str] = []
    for name in SCAFFOLD_FILES:
        p = (ws / name).resolve()
        if p not in created_set:
            if p.exists():
                preserved.append(name)  # 已有文件拒绝删除
            continue
        try:
            p.unlink()
            removed.append(name)
        except OSError:
            preserved.append(name)
    for name in SCAFFOLD_DIRS:
        d = (ws / name).resolve()
        if d not in created_set:
            if d.is_dir() and any(d.iterdir()):
                preserved.append(name + "/")  # 非空目录拒绝删除
            continue
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)
            removed.append(name + "/")
    return removed, preserved


def refuse_toolchain(ws: Path, report: "toolchain.ToolchainReport") -> int:
    """#304 修正: HARD FAIL → 逐项友好安装命令(人类安装) + 拒绝 + 清理。

    - exit RC_TOOLCHAIN_REFUSE(4), 不写 [initialized] 标记
    - 逐项打印 [FAIL] name + detail + fix(安装命令)
    - 清理本次运行创建的 scaffold 产物(若有); 既有内容一律保留并提示(F2)
    """
    hard_fails = [
        i for i in report.items
        if i.status == toolchain.Status.FAIL and i.tier == toolchain.Tier.HARD
    ]
    removed, preserved = cleanup_scaffold(ws)
    print(
        f"kunglao-init: REFUSE — toolchain HARD 检查未通过 "
        f"(type={report.project_type}), 请在安装缺失工具后重新运行 "
        f"kunglao-init.py {ws} --type {report.project_type}.",
        file=sys.stderr,
    )
    for item in hard_fails:
        print(f"  [FAIL] {item.name}: {item.detail}", file=sys.stderr)
        fix = toolchain.FIXES.get(item.name)
        if fix:
            print(f"      fix: {fix}", file=sys.stderr)
    if removed:
        print(f"kunglao-init: 已移除本次运行创建的产物: {', '.join(removed)}",
              file=sys.stderr)
    if preserved:
        print(f"kunglao-init: 保留既有内容(非本次创建, 不删除): {', '.join(preserved)}",
              file=sys.stderr)
    print("kunglao-init: NOT initialized(未写 [initialized] 标记)", file=sys.stderr)
    return RC_TOOLCHAIN_REFUSE


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(Path(args.workspace), force=args.force, hooks_json=args.hooks_json,
               profile_root=args.profile_root, project_type=args.type,
               skip_toolchain=args.skip_toolchain, no_mcp=args.no_mcp)


if __name__ == "__main__":
    sys.exit(main())
