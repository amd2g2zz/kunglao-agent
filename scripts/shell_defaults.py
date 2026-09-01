#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""shell_defaults.py — reusable CLI: idempotent management of shell environment default lines (#276).

Issue #276: the root cause of the 2026-08-12 incident was
CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 polluting the process scope. This
CLI turns "shell environment default-line management" into a generic
reusable tool — fully parameterized (--var/--value/--profile/--shell all
injectable, no hardcoding) for kunglao-init and friends to call; inlining
the logic inside init is forbidden.

CLI:
    python shell_defaults.py check  --var <NAME> --profile <PATH> [--shell powershell|bash] [--json]
    python shell_defaults.py apply  --var <NAME> --value <V> --profile <PATH> [--shell powershell|bash] [--json]
    python shell_defaults.py remove --var <NAME> --profile <PATH> [--shell powershell|bash] [--json]

Semantics:
  - line formats: powershell `$env:NAME = "V"` / bash `export NAME="V"`
  - truthy values (1/true/yes/on, case-insensitive) detected and warned
    about — the polluted state
  - apply is idempotent: target line already present -> unchanged (skip);
    a truthy/other-value line -> rewritten (to the target value);
    no line -> appended (with comment); the result converges to the single
    target line
  - remove: deletes the target line + its shell_defaults comment; no-op
    when absent
  - exit codes distinguish states: check 0=OK / 1=TRUTHY / 2=ABSENT;
    apply/remove 0=success; error 3
  - output: human-readable text, or --json single-line JSON
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
    """Truthy-value check: 1/true/yes/on, case-insensitive, whitespace-tolerant."""
    return value is not None and value.strip().lower() in TRUTHY_VALUES


def target_line(var: str, value: str, shell: str) -> str:
    """Target line text: powershell `$env:NAME = "V"` / bash `export NAME="V"`."""
    if shell == "bash":
        return f'export {var}="{value}"'
    return f'$env:{var} = "{value}"'


def comment_line(var: str, value: str) -> str:
    """Trailing comment (recognizable and removable by remove)."""
    return f"{COMMENT_MARK} {var}={value} (managed - edit via shell_defaults.py)"


def extract_value(line: str, var: str, shell: str) -> str | None:
    """Extract the value assigned to var from a line; None when the line does not set var.

    Tolerates: leading whitespace, quotes (double/single), trailing inline
    comments (whitespace + #), unquoted values.
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
    """Read profile lines (line endings preserved); a missing file counts as empty."""
    if not profile.exists():
        return []
    return profile.read_text(encoding="utf-8").splitlines(keepends=True)


def _write(profile: Path, lines: list[str]) -> None:
    profile.parent.mkdir(parents=True, exist_ok=True)
    profile.write_text("".join(lines), encoding="utf-8")


# ---------- subcommands ----------

def check(profile: Path, var: str, shell: str) -> dict:
    """Read status: OK (a non-truthy value on record) / TRUTHY (a truthy value on record) / ABSENT (no line)."""
    for line in read_lines(profile):
        value = extract_value(line, var, shell)
        if value is not None:
            if is_truthy(value):
                return {"status": "TRUTHY", "var": var, "value": value}
            return {"status": "OK", "var": var, "value": value}
    return {"status": "ABSENT", "var": var, "value": None}


def apply(profile: Path, var: str, value: str, shell: str) -> dict:
    """Idempotent default write: target line on record -> unchanged; other-value line -> rewritten; no line -> appended+comment."""
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
    """Delete the var line and its shell_defaults comment; no-op when absent (idempotent)."""
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


def _default_shell(profile: Path | None = None) -> str:
    """Shell format inference: explicit --shell > profile extension > platform.

    A `.ps1`/`.psm1` profile is PowerShell regardless of the OS that runs
    the CLI (CI on Linux manages Windows profiles); `.bashrc`/`.profile`/
    `.zshrc` are bash-line formats. Extension unknown → platform default.
    """
    if profile is not None:
        if profile.suffix.lower() in (".ps1", ".psm1"):
            return "powershell"
        if profile.name in (".bashrc", ".bash_profile", ".profile", ".zshrc"):
            return "bash"
    return "powershell" if os.name == "nt" else "bash"


def _print_result(result: dict, text: str, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="shell_defaults",
        description="idempotent shell environment default-line management (check/apply/remove, powershell+bash)",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    def _common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--var", required=True, help="environment variable name")
        p.add_argument("--profile", required=True, help="profile file path (injectable)")
        p.add_argument("--shell", choices=("powershell", "bash"), default=None,
                       help="line format (default inferred from platform)")
        p.add_argument("--json", action="store_true", help="output JSON")

    p_check = sub.add_parser("check", help="read status: OK / TRUTHY / ABSENT")
    _common(p_check)
    p_apply = sub.add_parser("apply", help="write the default line (idempotent)")
    _common(p_apply)
    p_apply.add_argument("--value", required=True, help="target value")
    p_remove = sub.add_parser("remove", help="delete the default line (idempotent)")
    _common(p_remove)

    args = ap.parse_args(argv)
    profile = Path(args.profile)
    shell = args.shell or _default_shell(profile)

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
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
