# GLOBAL-DEV-PLAN-B2 — Batch 2（基线修复 + 技能契约化 + 治理）三 agent 调度计划

> 角色分工、依赖顺序、PR 循环规则、验收口径。**每 issue 的权威规格 = GitHub issue 正文**
> （#226-#230 已含背景/任务/验收/依赖），本文件只定调度与跨 issue 契约。
> 前置文档（Batch 1 已交付）：`GLOBAL-DEV-PLAN.md` + `ISSUE-SPECS.md`（#191-#206）。

## 0. 执行状态（2026-08-13 更新，主控实时维护）

| Wave | issue | PR | 状态 |
|---|---|---|---|
| A | #231 golden 可移植 | #232 (5444e85) + #242 (idempotency) | ✅ 已合入 dev（#242 补幂等提交，owner 先合了 #232 首提交） |
| B | #224/#225 编码声明 | #225 | ✅ owner 已合入 dev，issue 已关 |
| C | #226 SKILL.md 契约化 | #243 @ 4a9202e | CI 绿 + TEST/ACCEPT 门通过 → 待合 |
| — | digest 重 pin | dev a14bd99 | ✅ owner #233/#238 改 references 后 3 个 pin 漂移，已重 pin 推 dev，CI 恢复绿 |
| C | #230 scripts 治理 | — | 待 #226 合入后开始 |
| C | #228 去硬编码 | — | 待 #230 后 |
| C | #227 references 重组 | — | 待 #228 后 |
| C | #229 references_recall | — | 待 #227 后 |
| B3 | #233-#241（owner 新增批次：env_check 门禁/角色契约/生命周期清理/监视闭环等） | owner 自驱动（#248/#249 等） | 并行推进中；#226 已 fold 其中 #233/#238 的 SKILL.md 内容 |

> **并行注意**：owner 在 dev 上以小时级节奏合 PR。每个 PR 切出前必须 fetch + rebase 最新 origin/dev；合并前重跑 TEST/ACCEPT。

## 1. 角色（三个 agent 职责互斥，与 Batch 1 相同）

| Agent | 类型 | 职责 | 禁止 |
|---|---|---|---|
| **DEV** | tdd-guide | 在独立 worktree 按依赖顺序逐 issue 实现（TDD：RED→GREEN→IMPROVE），每 issue 一个分支一个 PR | 不评审自己的 PR；不合并；不运行验收 |
| **TEST** | python-reviewer | 独立验证每个 PR：独立 worktree checkout PR 分支，跑相关 pytest + 全量回归，审查测试质量（真测行为 / fixture 真实 schema），PR 上发 review | 不改代码；不合并；不替代 ACCEPT |
| **ACCEPT** | code-reviewer | 对每个 PR 按 issue 正文"验收"节逐条核对 + 运行验收命令；通过 approve，不通过 request-changes 列出差距 | 不改代码；不跑开发性实验 |

**关键约束**：DEV 的 PR 被 TEST + ACCEPT 双重审视；两个 approve 才视为 issue 完成；**合并由主控执行**（目标：通过后主动合入 dev）。

## 2. 依赖顺序（严格串行，每个 PR 合入 dev 后才开始下一个）

```
Wave A（基线修复，最高优先）:
  #231 golden replay 去 Windows 硬编码 + drift 测试 marker 修复
  → 先于一切（CI 红阻塞所有 PR，含 #225）

Wave B:
  #225 rebase onto dev → CI 绿 → 合并 → 关 #224

Wave C（主链）:
  #226 SKILL.md 契约化重写（定导航锚点）
  → #230 scripts 治理（SKILL.md 引用新 scripts 路径）
  → #228 去硬编码（SKILL.md 占位符化与 C 类重叠，须在 #226 后）
  → #227 references 领域重组（#226 导航节之后）
  → #229 references_recall（#226 + #227 的索引）

Wave D（收口）:
  全量 pytest 绿 + CI 绿 + 无硬编码契约测试绿 + receipt --check 绿
```

**同文件冲突防护**：串行执行 + 每 PR 从最新 dev 切出，天然无写冲突；TEST/ACCEPT 只读。

## 3. TDD 循环（每个 issue，DEV 执行）

1. **RED**：写失败测试（先契约后实现；#226 为契约测试，#227 为断链/导航契约测试，#230 为 inventory 契约测试，#228 为硬编码 grep 契约测试，#229 为 golden 命中测试）
2. 运行 → 确认失败（记录实际失败输出到 PR body）
3. **GREEN**：写最小实现
4. 运行 → 确认通过
5. **IMPROVE**：命名/不可变性/错误处理（ecc 编码风格），需要时重构
6. 提交（`<type>(#<issue>): <描述>`）

## 4. PR 规则

- 分支：`fix/231-<slug>` / `fix/226-<slug>` …；每 issue 一个分支，从最新 `origin/dev` 切出
- PR 标题：`<type>(#<issue>): <issue 标题>`；body：`Fixes #<issue>` + RED 失败输出 + 验证命令输出摘要
- 合并：TEST + ACCEPT 都 approve 后由主控合并到 dev（本批次目标：通过后主动合入）
- **PR 失败（CI 红 / request-changes）**：DEV 读错误日志与 review 意见 → 修复 → 推同一分支 → PR 下回复改动说明 → 重新请求 review。循环直到 approve。

## 5. 测试与验收命令口径

- 一律 `uv run python -m pytest ...`（worktree 内 .venv）
- 单测：issue 指定的测试文件；回归：全量 `uv run python -m pytest -q`
- 验收命令：各 issue "验收"节 + `uv run python scripts/release_receipt.py --check` + `uv run python scripts/structural_check.py .`
- CI：push 后看 Actions；失败先读日志再修

## 6. 整个批次的 Definition of Done

1. 6 个 issue 的 PR 全部被 TEST + ACCEPT approve 并合入 dev（#224 随 #225 关闭）
2. 全量 pytest 绿（本批新增契约测试后仍 0 failed）
3. CI（release-check）绿
4. grep 全仓无盘符绝对路径 / 用户主目录 / 内网 VM 子网 IP 硬编码（#228 契约，fixture 中 `{{PYTHON}}/{{ROOT}}` 占位符除外）
5. `release_receipt.py --check` 与 `structural_check.py` 均 exit 0
6. 工作区收尾：临时 worktree 全部移除，主工作区停留在 origin/dev

## 7. 已知既有问题（不在本批范围）

- `test_self_cap_smoke.py` PytestReturnNotNoneWarning ×4（测试返回 list，不影响通过）——记录，不修
- `tests/test_acceptance.py::test_acceptance_overall_passes` 内嵌全量 pytest（~60s）——#230 可顺带评估
- hook 执行解释器裸 `python`（本机 2.7）问题——#224 已加编码声明层，解释器配置问题另议
