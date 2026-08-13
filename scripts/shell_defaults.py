#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shell_defaults.py — 可复用 CLI: 幂等管理 shell 环境默认行 (#276).

Issue #276: 2026-08-12 事故根因是 CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 污染
process scope。本 CLI 把「shell 环境默认行管理」落为通用可复用工具 —— 参数化
(--var/--value/--profile/--shell 全可注入, 无硬编码), 供 kunglao-init 等调用,
禁止把逻辑内联在 init 里。

CLI:
    python shell_defaults.py check  --var <NAME> --profile <PATH> [--shell powershell|bash] [--json]
    python shell_defaults.py apply  --var <NAME> --value <V> --profile <PATH> [--shell powershell|bash] [--json]
    python shell_defaults.py remove --var <NAME> --profile <PATH> [--shell powershell|bash] [--json]

语义:
  - 行格式:  powershell `$env:NAME = "V"` / bash `export NAME="V"`
  - truthy 值 (1/true/yes/on, 不区分大小写) 检测与告警 —— 污染态
  - apply 幂等: 已含目标行 -> unchanged(跳过); truthy/其它值行 -> rewritten(改写成目标值);
    无行 -> appended(追加, 带注释); 结果收敛为唯一目标行
  - remove: 删除目标行 + 其 shell_defaults 注释; 无行时 no-op
  - exit code 区分状态: check 0=OK / 1=TRUTHY / 2=ABSENT; apply/remove 0=成功; 错误 3
  - 输出: 人类可读文本, 或 --json 单行 JSON
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

TRUTHY_VALUES = ("1", "true", "yes", "on")
COMMENT_MARK = "# shell_defaults:"


def is_truthy(value: str | None) -> bool:
    """Truthy 值判定: 1/true/yes/on, 不区分大小写, 空白容忍."""
    return value is not None and value.strip().lower() in TRUTHY_VALUES


def target_line(var: str, value: str, shell: str) -> str:
    """目标行文本: powershell `$env:NAME = "V"` / bash `export NAME="V"`."""
    if shell == "bash":
        return f'export {var}="{value}"'
    return f'$env:{var} = "{value}"'


def comment_line(var: str, value: str) -> str:
    """随行注释 (remove 可识别并清除)."""
    return f"{COMMENT_MARK} {var}={value} (managed - edit via shell_defaults.py)"


def extract_value(line: str, var: str, shell: str) -> str | None:
    """从行中提取 var 的赋值值; 该行未设置 var 时返回 None.

    容忍: 前导空白、引号(双/单)、行尾内联注释 (空白 + #)、未引号值.
    """
    if shell == "bash":
        m = re.match(rf"^\s*export\s+{re.escape(var)}\s*=\s*(.*)$", line)
    else:
        m = re.match(rf"^\s*\$env:{re.escape(var)}\s*=\s*(.*)$", line)
    if not m:
        return None
    value = re.sub(r"\s+#.*$", "", m.group(1)).strip()
    if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
        value = value[1:-1]
    return value.strip()


def read_lines(profile: Path) -> list[str]:
    """读 profile 行 (保留行尾); 文件不存在视为空."""
    if not profile.exists():
        return []
    return profile.read_text(encoding="utf-8").splitlines(keepends=True)


def _write(profile: Path, lines: list[str]) -> None:
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("".join(lines), encoding="utf-8")


# ---------- subcommands ----------

def check(profile: Path, var: str, shell: str) -> dict:
    """读状态: OK(非 truthy 值在册) / TRUTHY(truthy 值在册) / ABSENT(无行)."""
    for line in read_lines(profile):
        value = extract_value(line, var, shell)
        if value is not None:
            if is_truthy(value):
                return {"status": "TRUTHY", "var": var, "value": value}
            return {"status": "OK", "var": var, "value": value}
    return {"status": "ABSENT", "var": var, "value": None}


def apply(profile: Path, var: str, value: str, shell: str) -> dict:
    """幂等写默认: 目标行在册 -> unchanged; 其它值行 -> rewritten; 无行 -> appended+注释."""
    lines = read_lines(profile)
    target = target_line(var, value, shell)
    for i, line in enumerate(lines):
        old = extract_value(line, var, shell)
        if old is not None:
            if old == value:
                return {"change": "unchanged", "var": var, "value": value,
                        "profile": str(profile)}
            lines[i] = target + "\n"
            _write(profile, lines)
            return {"change": "rewritten", "var": var, "value": value,
                    "old_value": old, "profile": str(profile)}
    text = "".join(lines)
    if text and not text.endswith(("\n", "\r")):
        text += "\n"
    text += comment_line(var, value) + "\n" + target + "\n"
    _write(profile, [text])
    return {"change": "appended", "var": var, "value": value, "profile": str(profile)}


def remove(profile: Path, var: str, shell: str) -> dict:
    """删除 var 行及其 shell_defaults 注释; 无行时 no-op (幂等)."""
    if not profile.exists():
        return {"removed": False, "var": var, "profile": str(profile)}
    prefix = f"{COMMENT_MARK} {var}="
    lines = read_lines(profile)
    keep = [line for line in lines
            if extract_value(line, var, shell) is None
            and not line.strip().startswith(prefix)]
    removed = len(keep) != len(lines)
    if removed:
        _write(profile, keep)
    return {"removed": removed, "var": var, "profile": str(profile)}


# ---------- CLI ----------

_EXIT = {"OK": 0, "TRUTHY": 1, "ABSENT": 2}


def _default_shell() -> str:
    return "powershell" if os.name == "nt" else "bash"


def _print_result(result: dict, text: str, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="shell_defaults",
        description="幂等管理 shell 环境默认行 (check/apply/remove, powershell+bash)",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--var", required=True, help="环境变量名")
        p.add_argument("--profile", required=True, help="profile 文件路径 (可注入)")
        p.add_argument("--shell", choices=("powershell", "bash"), default=None,
                       help="行格式 (默认按平台推断)")
        p.add_argument("--json", action="store_true", help="输出 JSON")

    p_check = sub.add_parser("check", help="读状态: OK / TRUTHY / ABSENT")
    _common(p_check)
    p_apply = sub.add_parser("apply", help="写默认行 (幂等)")
    _common(p_apply)
    p_apply.add_argument("--value", required=True, help="目标值")
    p_remove = sub.add_parser("remove", help="删除默认行 (幂等)")
    _common(p_remove)

    args = ap.parse_args(argv)
    shell = args.shell or _default_shell()
    profile = Path(args.profile)

    if args.command == "check":
        result = check(profile, args.var, shell)
        if result["status"] == "OK":
            text = (f"shell_defaults: OK — {args.var}={result['value']} "
                    f"in {profile}")
        elif result["status"] == "TRUTHY":
            text = (f"shell_defaults: TRUTHY — {args.var}={result['value']} "
                    f"in {profile} (pollution; run apply --value 0 to fix)")
        else:
            text = f"shell_defaults: ABSENT — {args.var} not set in {profile}"
        _print_result(result, text, args.json)
        return _EXIT[result["status"]]

    if args.command == "apply":
        result = apply(profile, args.var, args.value, shell)
        if result["change"] == "rewritten":
            text = (f"shell_defaults: rewritten {args.var}={args.value} "
                    f"(was {result['old_value']}) in {profile}")
        elif result["change"] == "unchanged":
            text = (f"shell_defaults: unchanged — {args.var}={args.value} "
                    f"already in {profile}")
        else:
            text = (f"shell_defaults: appended {args.var}={args.value} "
                    f"(with comment) to {profile}")
        _print_result(result, text, args.json)
        return 0

    # remove
    result = remove(profile, args.var, shell)
    if result["removed"]:
        text = f"shell_defaults: removed {args.var} from {profile}"
    else:
        text = f"shell_defaults: not present — {args.var} absent from {profile}"
    _print_result(result, text, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
