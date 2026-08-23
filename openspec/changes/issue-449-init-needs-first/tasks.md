# Tasks — issue-449-init-needs-first

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/449` branch `v012/issue-449-init-needs-first` off `origin/dev` 4b07bba
- [x] 1.2 必读:plan(Task 2 / Patterns / 验收 A)/ issue #449 / skills/init/SKILL.md / scripts/toolchain.py / scripts/kunglao-init.py / agents/kunglao-init-worker.md / pytest.ini / devkit Gate 5 契约 / openspec issue-444 三件套;边界判定(checklist=#450、协商=#451、android=R2、bootstrap_observability=#461 禁区)保留

## 2. SDD

- [x] 2.1 proposal.md(三份证据 + 改动面 + 不做)
- [x] 2.2 design.md(D1 需求集落点 / D2 检查项消费 / D3 init 接线 / D4 fail-closed 对应 / D5 验收映射 / R1-R7)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红)

- [x] 3.1 `tests/test_toolchain_needs_first.py::test_requirements_*` — requirements_from_task_spec 不存在(红)
- [x] 3.2 `test_load_task_spec_*` — load_task_spec 不存在(红)
- [x] 3.3 `test_check_{windows,linux}_static_only_vm_warn` + `test_check_no_task_spec_vm_hard_byte_identical` — check 无 task_spec 参数(红)
- [x] 3.4 CLI 消费 + init 指引行 + unparseable + **cost 证据负例对**(static-only exit 0 / 无 spec exit 4) + SKILL.md 第 0 步锚定(红)
- [x] 3.5 确认 RED:uv run python -m pytest -q tests/test_toolchain_needs_first.py(全红,哈希记录于 commit)

## 4. GREEN

- [x] 4.1 toolchain.py:Requirements / DEFAULT_REQUIREMENTS / requirements_from_task_spec / load_task_spec / _check_vm_channel(共享,windows/linux 去重)/ check(+task_spec=None)/ _check_{windows,linux}(+reqs)/ CLI main 消费
- [x] 4.2 kunglao-init.py:门内 load + 一行指引 + unparseable WARNING + 条件传参(两参调用保留)
- [x] 4.3 skills/init/SKILL.md:Flow 第 0 步 = Task-spec intake,scaffold 降后,frontmatter 同步
- [x] 4.4 agents/kunglao-init-worker.md:intake 顺序补 task-requirements 轮(additive)
- [x] 4.5 快速门:uv run python -m pytest -q -m "not load_sensitive" tests/test_toolchain*.py tests/test_kunglao_init.py

## 5. REFACTOR + 回归锚定

- [x] 5.1 既有 toolchain/init/target-alignment/heartbeat 测试零回归(无 spec 路径 detail 逐字节锚定)
- [x] 5.2 ruff 零红 + worktree 本地质量门 1 3 4 5(Gate 5 JSON: .subagent-review/2026-08-19-449.json,verified_by=pending-449-reviewer)

## 6. 产出

- [x] 6.1 `.review/RUNBOOK.md`(改动清单 / 测试映射 / 门禁结果 / 兼容性 / 自认风险 / 复现命令)——永不提交
