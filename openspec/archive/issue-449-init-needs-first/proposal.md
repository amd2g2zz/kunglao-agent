# Init Needs-First: env = f(task_spec) (#449)

## Why

Issue #449 (milestone v0.1.2, D2 行为契约 × D1 分层静态化;分层条目
L1-1 / L1-6 / L2-5 / G1):init 把环境当**常量**,而环境本应是**任务的
函数**。三份证据:

1. **契约顺序颠倒**(`skills/init/SKILL.md` Flow):Task-spec intake 排第
   4/5 位,scaffold 排第 1 位——工具链要求(要不要 VM)先于需求存在。
   `scripts/toolchain.py` 的分层按 type 模板写死
   (`_check_windows/_check_linux`),`grep task_spec|primary_question`
   零命中:vm_reachable 对任何 windows/linux 任务都是 HARD,即使任务
   只要静态分析。
2. **实测代价**(2026-08-17 transcript):task_spec 未答(intake 问题挂起)
   → VM 全链路已拉起(开机 → VPMC 修复 → 快照回滚 → 4 轮 boot 循环 →
   vm_setup.bat → 手工起 frida-server)。若最终回答"只要静态分析",
   以上全部为无用功。
3. **降级决策与任务无关**:die/floss 缺失被自动 declined+WARN,接受
   降级的理由是"die.json 已由 mal-recon 产出"——前次分析的偶然产物
   被当作本次任务依据。

## What Changes

- **Flow 重排**(`skills/init/SKILL.md`):Task-spec intake(确认
  primary questions / scope / constraints / depth / success_criteria)提为
  **Flow 第 0 步**,scaffold 降后;文本与序号一致化(frontmatter 描述
  同步)。
- **toolchain 消费 task_spec**(`scripts/toolchain.py`):
  - 新函数 `requirements_from_task_spec(task_spec) -> Requirements`
    (needs_vm + basis):从 `constraints.dynamic_re` 显式字段读;
    `forbidden`(static-only)→ VM 通道不需要;**读不到的字段一律保守
    HARD,与现状一致**。`load_task_spec(ws)` 单一加载点(absent → None,
    unparseable → ValueError fail-closed)。
  - `_check_windows/_check_linux` 消费需求集:static-only 时
    `vm_reachable`/`remote_debugger` 不再 HARD(降 WARN,detail 注明
    task_spec 依据;报告三态诚实,不静默跳过)。VM 探针块提为共享
    helper `_check_vm_channel`(windows/linux 原本就是重复块)。
  - **无 task_spec 输入时行为与现状逐字节一致**(向后兼容:init 早期
    未填、直接 CLI 调用、旧测试 monkeypatch 均不受影响)。
  - CLI `toolchain.py <ws>` 自动消费 `<ws>/task_spec.yaml`(存在时);
    unparseable → stderr WARNING + 保守 HARD。
- **init 接线**(`scripts/kunglao-init.py`):toolchain 检查前读
  task_spec(intake 先行后自然可得);缺失时走既有默认路径并输出**一行
  指引**;unparseable → WARNING + 保守 HARD(CLAUDE.md render 稍后对同一
  缺陷 fail-closed)。
- **cost 证据回归测试**:issue 证据 2 的时序固化为负例——static-only
  task_spec 下 init 不触发 vm_reachable HARD 拒绝(exit 0 + 无
  `[FAIL] vm_reachable`);同环境无 task_spec → exit 4 + `[FAIL]
  vm_reachable`(现状锚定)。
- **agent 定义**(`agents/kunglao-init-worker.md`):intake 顺序补
  task-requirements 轮(additive)。

## Impact

- **代码**:`scripts/toolchain.py`(requirements/load/共享 VM 块/check
  签名 +`task_spec=None`/CLI)、`scripts/kunglao-init.py`(门内读
  task_spec + 指引行 + 条件传参)、`skills/init/SKILL.md`(Flow 重排)、
  `agents/kunglao-init-worker.md`(顺序补充)。
- **测试**:新增 `tests/test_toolchain_needs_first.py`;既有测试零回归
  (所有写 task_spec.yaml 的既有测试都走 `--skip-toolchain`;无 spec 路径
  逐字节不变)。
- **不做**(见 design.md Rejected):三态 checklist 脚本(#450 邻接)、
  协商菜单(#451)、android ADB 契约的需求化放宽、`vm_detonation` 单独
  放宽、按端口粒度的 env manifest(#450)。

需求源: issue #449 (github.com/amd2g2zz/kunglao-agent/issues/449)
架构约束: #498(决策循环一体化——需求先于资源决策)
