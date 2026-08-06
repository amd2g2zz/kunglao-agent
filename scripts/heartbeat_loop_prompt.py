#!/usr/bin/env python3
"""heartbeat_loop_prompt.py — v1.9.26: generate the FULL /loop heartbeat prompt.

Why: the heartbeat must be BORN registered. The orchestrator used to create
the /loop cron, THEN remember to run --heartbeat-on — a two-step dance that
failed (orchestrator claimed monitoring started without registering it,
v1.9.25 lesson). This script emits ONE self-contained /loop prompt that
CARRIES the registration + monitoring + verification contract, so a single
`/loop 5m <prompt>` starts everything at once.

Usage:
    python scripts/heartbeat_loop_prompt.py <workspace> [--interval 5m]

Output: the prompt to pass to `/loop <interval> <prompt>` (or CronCreate).
The prompt's FIRST action is `hook_activation.py <ws> --heartbeat-on`
(registration is born with the loop), then per-tick monitoring (reconcile /
status poll / smart ping / convergence / renew) and the CONVERGED gate
(heartbeat-check must pass before declaring done).

Pure stdlib. Exit 0.
"""
from __future__ import annotations

import sys
from pathlib import Path


def build_prompt(ws: str, interval: str = "5m") -> str:
    h = "C:/Users/hr/.claude/skills/kunglao-agent/scripts/hook_activation.py"
    tk = "C:/Users/hr/.claude/skills/kunglao-agent/scripts/heartbeat_tick.py"
    return f"""/loop {interval} kunglao-agent 心跳（自注册 + 监视 + 校验一体）：

[启动动作 — 循环首次触发时执行一次]
python {h} {ws} --heartbeat-on   # 注册心跳（写 runs/.heartbeat.json）— 监视从此是文件状态

[每 tick 监视（5 分钟间隔）]
0. python {tk} {ws}              # v1.9.38 一键 tick：selfcheck + reconcile + renew + heartbeat-check
                                 # （机械步骤全部折叠为 1 命令，exit=1 时才需要人工处理）
1. 读 runs/.heartbeat-tick.json 报告：exit=0 → 只需认知步骤（ping 活跃 worker / 处理完成 worker）
2. 对每个活跃 worker 发智能 ping（§6.1a）：SendMessage "[ping HH:MM] step? stuck? eta?"
   → 结构化回复 append 到 runs/.ping-log.jsonl
3. python C:/Users/hr/.claude/skills/kunglao-agent/scripts/convergence_check.py {ws} 决策：
   DISPATCH→priority.py 派发；SATURATED→继续轮询；CONVERGED→先跑 §6.3 checklist（5 项）
   + 双签（doubt_checker + 随机抽验 1 fact）+ --heartbeat-check 通过才宣告完成
4. 完成 worker → 验证 facts → 合入 master → 更新 claim-register + _INDEX
5. 按 §6.2 用 malware-veri-notes 记录笔记；保持推进不空转"""


def main() -> int:
    if len(sys.argv) < 2:
        print(f"Usage: {Path(sys.argv[0]).name} <workspace> [--interval 5m]", file=sys.stderr)
        return 2
    ws = sys.argv[1]
    interval = "5m"
    if "--interval" in sys.argv:
        i = sys.argv.index("--interval")
        if i + 1 < len(sys.argv):
            interval = sys.argv[i + 1]
    print(build_prompt(ws, interval))
    return 0


if __name__ == "__main__":
    sys.exit(main())
