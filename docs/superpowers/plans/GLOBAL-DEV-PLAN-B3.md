# GLOBAL-DEV-PLAN-B3 — Batch 3（可观测性 + runtime 召回 + 写侧门禁 + 脚本模板化）三 agent 调度计划

> 角色分工、依赖顺序、PR 循环规则、验收口径。**每 issue 的权威规格 = GitHub issue 正文**
> （#287/#268/#236/#278），本文件只定调度与跨 issue 契约。
> 前置：Batch-2 计划 `GLOBAL-DEV-PLAN-B2.md`（已交付；owner 并行实现了 #226-#230）。

## 0. 当前基线（2026-08-13 采集）

- dev @ `eb95f03`，CI release-check ✅（本会话已热修 owner PR #276 的 shell_defaults .ps1 格式推断缺陷，13 个失败清零，全量 1279 passed / 2 skipped）
- 无 open PR；open issues 仅 4 个：#287 #278 #268 #236
- 依赖就绪：#268 依赖全部 CLOSED（#227/#229/#239/#241/#233-#235/#237）；工具在位（tier_rules.py / feedback.py / failure_analysis_gate.py / references_recall.py / _INDEX.md 分层索引）；tools/ 目录已有 12+ 域分类（#261 引入，owner 已建 validate_index.py）
- **#278 吸收半侧不可执行**：`D:\works\samples` 在 Windows 机器上，本机 macOS、VM 192.168.20.128 不通、无 vmr-shell → 236 个脚本的盘点/迁入无法做。本批只做**模板化生成半侧**；吸收半侧保持 open 待 VM 可达（issue 上注明）。

## 1. 角色（三 agent 职责互斥，同 Batch 1/2）

| Agent | 类型 | 职责 | 禁止 |
|---|---|---|---|
| **DEV** | tdd-guide | 独立 worktree 逐 issue 实现（TDD：RED→GREEN→IMPROVE），一 issue 一分支一 PR | 不评审自己 PR；不合并；不跑验收 |
| **TEST** | python-reviewer | 独立 worktree checkout PR 分支，跑相关 pytest + 全量回归 + 测试质量审查，PR 发 review | 不改代码；不合并；不替代 ACCEPT |
| **ACCEPT** | code-reviewer | 按 issue "验收"节逐条核对 + 运行验收命令；通过 approve / 不通过 request-changes | 不改代码；不跑开发性实验 |

合并由主控执行；两 gate 通过才视为完成。**自审阻断**：gh 账号 edmserver 是 PR 作者，GitHub 禁止自 approve → 门证据以 PR comment 形式记录（Batch-2 已验证此通道）。

## 2. 依赖顺序与并行安排（本批 4 个 issue 文件零重叠，可两两并行）

```
Wave A（双 DEV 并行，零文件冲突）:
  #287 可观测性（scripts/kunglao_log.py + scripts/kunglao-status.py + tests + SKILL.md 观察章节）
  #268 runtime 召回（hooks/recall_inject.py + worker 模板 + tests）
  —— SKILL.md 冲突防护：#287 只加"可观测性"章节；#268 不加 SKILL.md（只改 worker 模板）；SKILL.md 由 #287 独占

Wave B（并行）:
  #236 写侧门禁（scripts/ 校验 + tests；先审计现有读侧门禁清单，TDD 契约测试）
  #278 模板化半侧（templates/* 生成模板 + 生成脚本 + tests；SKILL.md 不动）

Wave C（收口）:
  全量 pytest 绿 + CI 绿 + structural/receipt 绿 + issue 关闭 + 会话报告
```

**同文件冲突防护**：每 PR 从最新 origin/dev 切出；串行合并时 rebase；TEST/ACCEPT 只读。

## 3. TDD 循环（每个 issue，DEV 执行）

1. **RED**：写失败测试（#287 为 emit 格式 + 面板渲染 fixture；#268 为 dispatch payload 含 recall 注入 + 特征命中；#236 为写侧违规必拒；#278 为模板生成产物可执行）→ 运行确认失败（输出进 PR body）
2. **GREEN**：最小实现 → 通过
3. **IMPROVE**：命名/不可变性/错误处理（ecc 风格）
4. 提交 `<type>(#<issue>): <描述>` → push → PR（body: Fixes #N + RED + GREEN 摘要）

## 4. PR 规则

- 分支 `fix/287-observability` 等，从最新 origin/dev 切出；标题 `<type>(#N): <issue 标题>`
- **合并**：TEST + ACCEPT 均 PASS（PR comment 证据）→ 主控 `gh pr merge --squash --delete-branch`
- **失败**：DEV 读错误日志与 review → 修复 → 同分支 force-push → 回复说明 → 重新请求 review，循环至通过

## 5. 测试与验收口径

- 一律 `uv run python -m pytest ...`；回归全量 `-q --tb=no`
- 验收命令：各 issue "验收"节 + `release_receipt.py --check` + `structural_check.py .`
- CI：push 后看 Actions；失败先读日志再修
- **references 改动后必须跑 `uv run python scripts/re_pin_references.py`**（#271 CRLF 教训 + 本会话三次漂移教训）

## 6. 整个批次的 Definition of Done

1. 4 个 issue 的 PR 全部双 gate 通过并合入 dev（#278 仅模板化半侧，吸收半侧注明阻塞）
2. 全量 pytest 绿（0 failed）；CI release-check 绿
3. `structural_check` + `release_receipt --check` exit 0；无 references 漂移
4. 工作区收尾：临时 worktree 全部移除，主工作区停留 origin/dev 最新

## 7. 已知风险与对策

| 风险 | 对策 |
|---|---|
| owner 并行节奏（小时级合 PR） | 每次切分支/合并前 fetch + rebase 最新 origin/dev |
| SKILL.md 双写冲突 | 本批 SKILL.md 仅 #287 触碰（单点写入） |
| #268 的 additionalContext 注入可能干扰现有 hook 链 | TEST 专项：hook 链回归（state_anchor/worker_pulse/dispatch_gate/env_check_gate 全量） |
| #236 写侧门禁可能误伤现有合法写路径 | TDD 契约测试先列合法路径（worker 产出 / redteam 盖章 / 用户 feedback），ACCEPT 核对 issue 验收逐条 |
| #278 吸收侧不可执行 | 在 issue 上注明 VM 阻塞；本批交付模板化 + inventory 框架（模板清单与分类标准），吸收留待 VM 可达 |
