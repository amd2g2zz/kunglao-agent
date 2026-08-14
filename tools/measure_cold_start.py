#!/usr/bin/env python3
"""tools/measure_cold_start.py — 阶段 0: 冷启动 token 基线测量器.

测量协议(冻结, 阶段 6/9 复用同一脚本):
  固定输入文件清单(claim-register.yaml / _INDEX / digest / ledger / progress 尾部)
  → 按文件 size 估 token(保守 4 chars/token) → 记录 {date, protocol, total_est, by_file}

输出: docs/baselines/cold-start-tokens.json(追加式, 每次测量一行时间戳条目; --out 可覆盖)

#277 CLI contract: --out FILE overrides the output path (no hardcoded path);
--json emits the latest measurement to stdout. Exit codes: 0 = success,
2 = operational error (no claim-register.yaml in the workspace).

协议版本 1(2026-08-06):
  - files: 状态文件清单
  - estimator: chars/4 (保守)
  - 不含 SKILL.md / CLAUDE.md(阶段 6 的 digest 注入目标是状态文件)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # non-TTY / captured stream without reconfigure (e.g. pytest capsys)

ROOT = Path(__file__).resolve().parents[1]
BASELINES = ROOT / "docs" / "baselines"
OUT = BASELINES / "cold-start-tokens.json"

# 协议 v1: 冷启动读入的状态文件清单(路径相对 workspace)
PROTOCOL_FILES = [
    "claim-register.yaml",
    "claim_deps.yaml",
    "task_spec.yaml",
    "facts/_INDEX.md",
    "digest.md",
    ".convergence_ledger.jsonl",
    "progress.txt",      # 尾 4000 字节
    "analysis_state.txt",
]

CHARS_PER_TOKEN = 4.0  # 保守估计


def measure(ws: Path) -> dict:
    by_file = {}
    total_chars = 0
    missing = []
    for name in PROTOCOL_FILES:
        p = ws / name
        if not p.exists():
            missing.append(name)
            continue
        data = p.read_text(encoding="utf-8", errors="replace")
        if name == "progress.txt":
            data = data[-4000:]  # 只读尾部(长任务语义)
        n = len(data)
        total_chars += n
        by_file[name] = {"chars": n, "est_tokens": round(n / CHARS_PER_TOKEN)}
    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "protocol": "v1",
        "estimator": f"chars/{CHARS_PER_TOKEN:.0f}",
        "total_chars": total_chars,
        "total_est_tokens": round(total_chars / CHARS_PER_TOKEN),
        "by_file": by_file,
        "missing": missing,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="measure cold-start token baseline (阶段 0)")
    ap.add_argument("workspace", help="workspace root to measure")
    ap.add_argument("--rounds", type=int, default=3, help="rounds to run (default 3)")
    ap.add_argument("--out", metavar="FILE", default=str(OUT),
                    help="output JSON file (default: docs/baselines/cold-start-tokens.json, #277)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="emit the latest measurement as JSON to stdout (#277)")
    args = ap.parse_args()

    ws = Path(args.workspace)
    if not (ws / "claim-register.yaml").exists():
        print(f"FAIL: no claim-register.yaml under {ws}", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    entries = []
    if out_path.exists():
        entries = json.loads(out_path.read_text(encoding="utf-8"))["entries"]
    for _ in range(args.rounds):
        entries.append(measure(ws))
    out_path.write_text(json.dumps({"protocol": "v1", "entries": entries}, indent=2, ensure_ascii=False), encoding="utf-8")

    last = entries[-1]
    if args.as_json:
        print(json.dumps(last, ensure_ascii=False, indent=2))
        return 0
    print(f"cold-start token baseline (protocol v1):")
    print(f"  rounds: {args.rounds}  total_est_tokens: {last['total_est_tokens']}  chars: {last['total_chars']}")
    print(f"  top files:")
    for name, m in sorted(last["by_file"].items(), key=lambda kv: -kv[1]["est_tokens"])[:5]:
        print(f"    {name}: {m['est_tokens']} tokens ({m['chars']} chars)")
    if last["missing"]:
        print(f"  missing (0 tokens): {', '.join(last['missing'])}")
    print(f"  saved -> {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
