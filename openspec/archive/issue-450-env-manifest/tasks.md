# Tasks — issue-450-env-manifest

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/450` branch `v012/issue-450-env-manifest` off `origin/dev` c5cb1ae(已含 #449 requirements_from_task_spec)
- [x] 1.2 必读:plan(Task 2 / Patterns / 验收 A)/ issue #450 / PR #504 遗留段 / scripts/toolchain.py #449 面 / hooks/dispatch_gate.py:71-77 / scripts/convergence_check.py `_resolve_ws` / hooks/lib_kunglao.py iter_worker_states / pytest.ini / devkit Gate 5 契约;边界判定(协商=#451、#449 语义只消费、具体值不入代码)保留

## 2. SDD

- [x] 2.1 proposal.md(三份证据 + 改动面 + 不做)
- [x] 2.2 design.md(D1 数据模型 / D2 优先级与加载点 / D3 字面量收编 / D4 CLI render+probe / D5 CLAUDE.md 条件化 / D6 映射 / R1-R7)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红)

- [x] 3.1 `tests/test_env_manifest.py::test_layout_defaults_are_pre450_literals` + `test_load_manifest_*` — env_manifest 模块不存在(红)
- [x] 3.2 `test_resolve_*`(优先级链 file>task-spec>default;garbage ValueError)+ `test_layout_conventions_garbage_never_raises`(红)
- [x] 3.3 三消费点收编锚(dispatch/convergence/lib_kunglao 缺 manifest 逐字节一致 + custom layout 覆写)(红)
- [x] 3.4 `test_render_*` 三态 + CLI garbage exit 缺陷码 + `test_probe_*`(发现/合并/无 vmrun fail-open/拒覆写 garbage)(红)
- [x] 3.5 `test_claudemd_*`(static-only → VM not required 行;无输入 → golden 逐字节)(红)
- [x] 3.6 确认 RED:uv run python -m pytest -q tests/test_env_manifest.py(全红,哈希记录于 commit)

## 4. GREEN

- [x] 4.1 scripts/env_manifest.py:数据类族 / DEFAULT_LAYOUT / load_manifest / resolve / layout_conventions / manifest_path_for / conditionalize_vm_required / vm_requirement_for / render_section / probe(_subprocess_run seam)/ CLI(--render --probe --json,RC_* 常量)
- [x] 4.2 hooks/dispatch_gate.py:_resolve_workspace 布局经 env_manifest(缺 manifest 逐字节一致)
- [x] 4.3 scripts/convergence_check.py:_resolve_ws 同款收编
- [x] 4.4 hooks/lib_kunglao.py:iter_worker_states 的 .wt-* glob / workspace_dir / runs_dir 经布局(惰性 import,#444 缺文件=破损安装姿态)
- [x] 4.5 scripts/kunglao-init.py:write_claudemd 的 "VM required" 行条件化(vm_requirement_for;无输入逐字节一致,golden 保持)
- [x] 4.6 快速门:uv run python -m pytest -q -m "not load_sensitive" tests/test_env_manifest.py tests/test_toolchain*.py tests/test_dispatch*.py tests/test_convergence*.py tests/test_worktree_marker.py tests/test_renderer_unify.py

## 5. REFACTOR + 回归锚定

- [x] 5.1 既有 dispatch/convergence/worktree-marker/renderer-golden/worker-liveness 测试零回归(缺 manifest 路径行为不变)
- [x] 5.2 ruff 零红 + worktree 本地质量门 1 3 4 5(Gate 5 JSON: .subagent-review/2026-08-19-450.json,verified_by=pending-450-reviewer)

## 6. 产出

- [x] 6.1 `.review/RUNBOOK.md`(改动清单 / 测试映射 / 门禁结果 / 兼容性 / 自认风险 / 复现命令)——永不提交
