# Tasks — issue-451-init-negotiation

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/451` branch
  `v012/issue-451-init-negotiation` off `origin/dev` 59806b9(已含 #449
  需求先行 + #450 env-facts.yaml)
- [x] 1.2 必读:plan(Task 2 / Patterns / 验收 A)/ issue #451 正文(含
  补丁 review 段 + 主检出 stash `v0.1.2-wip-local-2026-08-18-batch2`
  的 diff 复核)/ toolchain.py / toolchain_install.py / kunglao-init.py /
  error_response.py / agents/kunglao-init-worker.md(--resolve 面,不改)

## 2. SDD

- [x] 2.1 proposal.md(四证据 + 改动面 + 不做)
- [x] 2.2 design.md(D1 NextAction / D2 VM inventory / D3 协商菜单与
  接线 / D4 三缺陷 / D5 宪法对齐 / D6 测试映射 / R1-R5)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红;函数内 import 防 collect-error)

- [x] 3.1 `tests/test_toolchain_next_action.py` — NextAction 模型 /
  human+json 双面机械解析 / 动词封闭集 / 每个 FIXES 键 FAIL 必有
  next_action / VM inventory 多候选 vm-enumerate + options / 拒绝面携带
  action/command/option 行(红)
- [x] 3.2 `tests/test_toolchain_negotiation.py` — NEGOTIABLE 派生 /
  disk_candidates 搜盘 / 三选一菜单 options / apply 四答案(install 假
  安装 re-probe、use-path 校验、skip 保 FAIL、degrade 注记)/ init 接线:
  die-only 非交互 exit 8、--resolve degrade → exit 0、混合缺失 exit 4、
  畸形答案 RC_ERROR、VM 多候选不自动选择(红)
- [x] 3.3 `tests/test_toolchain_stdio.py` — refuse 前 stdout flush /
  三脚本 stderr utf-8 reconfigure / 非交互降级措辞 ≠ "declined"(红)
- [x] 3.4 更新 `tests/test_init_toolchain_gate.py` non-tty 测试到新契约
  (die-only → exit 8 pending;ask 仍不调用)与
  `tests/test_toolchain_needs_first.py` byte-identical 测试的 detail pin
  (#449 状态锁不动)
- [x] 3.5 确认 RED:`uv run python -m pytest -q tests/test_toolchain_next_action.py
  tests/test_toolchain_negotiation.py tests/test_toolchain_stdio.py`(全红,
  哈希记录于 commit)

## 4. GREEN

- [x] 4.1 scripts/toolchain.py:NextAction + CheckResult.fix/next_action +
  静态动词表 + VM inventory(_vmrun_exe/_vbox_exe/_vm_inventory seam)+
  _check_vm_channel 升级(返回 vm_ok;FAIL 面嵌 inventory;级联共享
  next_action)+ format_human/json 扩展 + stderr utf-8
- [x] 4.2 scripts/toolchain_negotiation.py:NEGOTIABLE / disk_candidates /
  negotiation_decisions / apply_answers / negotiate /
  has_non_negotiable_hard_fail
- [x] 4.3 scripts/kunglao-init.py:run() FAIL 分支接线(菜单 exit 8 ↔
  拒绝 exit 4;畸形 RC_ERROR)+ refuse_toolchain(flush + item.fix +
  next_action 结构化行)+ main() stderr utf-8 + 模块 docstring #451 段
- [x] 4.4 scripts/toolchain_install.py:stderr utf-8 + 关键行 flush +
  非交互降级措辞(≠ declined)
- [x] 4.5 快速门:`uv run python -m pytest -q -m "not load_sensitive"
  tests/test_toolchain*.py tests/test_init_toolchain_gate.py
  tests/test_error_response.py tests/test_decision_pending.py`

## 5. REFACTOR + 回归锚定

- [x] 5.1 #304/#449/#455 既有锚零回归(hostile-env exit-4 族 /
  assume-yes 族 / static-only 族 / pending-intake 族)
- [x] 5.2 ruff 零红 + worktree 本地质量门 1 3 4 5 6 ALL-PASS(Gate 5
  JSON: `.subagent-review/2026-08-20-451.json`,verified_by=pending-451-reviewer)

## 6. 产出

- [x] 6.1 `.review/RUNBOOK.md`(改动清单 / 测试映射 / 门禁结果 / 兼容
  性 / 自认风险 / 复现命令)——永不提交
