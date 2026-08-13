# GLOBAL-DEV-PLAN — P0 假闭环消除（16 issues）三 agent 调度计划

> 角色分工、依赖顺序、PR 循环规则、验收口径。**实施规格见 `ISSUE-SPECS.md`（每 issue 一节）**；
> **任务级 diff 细节见 `2026-08-13-false-closure-elimination.md`（Task N）**。
> 执行者：3 个 subagent（各自 worktree 隔离、职责互不重叠）。

## 1. 角色（三个 agent 职责互斥）

| Agent | 类型 | 职责 | 禁止 |
|---|---|---|---|
| **DEV** | tdd-guide | 在自己的 worktree 按依赖顺序逐 issue 实现（TDD：RED→GREEN→IMPROVE），每 issue 一个分支一个 PR | 不评审自己的 PR；不合并 PR；不运行验收（那是 ACCEPT 的活） |
| **TEST** | python-reviewer | 独立验证每个 PR：在自己的 worktree checkout PR 分支，跑相关 pytest + 全量回归，审查测试质量（是否真测了行为、fixture 是否符合真实 schema），在 PR 上发 review | 不改代码；不合并；不替代 ACCEPT 的验收判定 |
| **ACCEPT** | code-reviewer | 对每个 PR 按 ISSUE-SPECS 的"验收"节逐条核对 + 运行验收命令，通过发 approve，不通过发 request-changes 并列出具体差距 | 不改代码；不跑开发性实验 |

**关键约束**：开发、测试、验收永远不是同一个 agent。DEV 的 PR 被 TEST + ACCEPT 双重审视；两个 reviewer 都 approve 才视为该 issue 完成。

## 2. 依赖顺序（DEV 严格按此序执行）

```
Wave 0（无依赖，立即）:
  #205 阶段1（SKILL.md 降级）
  #192 digest 漂移   #193 ERROR 前缀   #195 provenance 接入
  #196 provenance CLI   #201 模板   #204 calibration gate
  #194 断链（#198/#206 的前置）

Wave 1（单文件链）:
  #191 CI YAML  →  #197 YAML 自检

Wave 2（#194 之后）:
  #198 references 索引   #206 release receipt

Wave 3（hook 链）:
  #199 second-stop shim  →  #200 no-oracle + replay #4 fixture

Wave 4（decide() 同分支链，顺序不可变）:
  #202 全局矛盾重算  →  #203 discovery 消费

Wave 5（收口）:
  #205 阶段2（SKILL.md 回升）
  最终验收：replay 4/4 forbidden=false + 全量 pytest + CI 绿
```

**同文件冲突防护**：单 DEV agent 串行执行，天然无写冲突；TEST/ACCEPT 只读。

## 3. TDD 循环（每个 issue，DEV 执行，源自 tdd-workflow）

1. **RED**：按 ISSUE-SPECS 写失败测试（代码在任务级计划 Task N 中）
2. 运行 → 确认失败（记录实际失败输出到 PR body）
3. **GREEN**：写最小实现
4. 运行 → 确认通过
5. **IMPROVE**：检查命名/不可变性/错误处理（ecc 编码风格），需要时重构
6. 提交（提交格式：`<type>(#<issue>): <描述>`）

## 4. PR 规则

- 分支：`fix/147-<issue>-<slug>`；每 issue 一个分支，从 `dev` 切出
- PR 标题：`fix(#<issue>): <ISSUE-SPECS 标题>`；body：`Fixes #<issue>` + RED 阶段失败输出 + 验证命令输出摘要
- **不合并**——TEST + ACCEPT 都 approve 后，由用户/主控合并
- **PR 未通过时（CI 失败或 review 提出 request-changes）**：DEV 必须仔细阅读错误输出与 review 意见 → 修复 → 推送到**同一分支**（不另开 PR）→ 在 PR 下回复改动说明 → 重新请求 review。循环直到 approve。
- worktree 隔离：DEV/TEST/ACCEPT 各自独立 worktree；测试与验收操作均在各自 worktree 内（TEST 用 `gh pr checkout <n>` 拉取目标分支）

## 5. 测试与验收命令口径

- 一律 `.venv/bin/python -m pytest ...`（系统 python 无 yaml，勿用）
- 单测：issue 指定的测试文件；回归：issue 列出的回归文件 + 最终 `-q` 全量
- 验收命令：ISSUE-SPECS 每节"验收"栏 + replay 命令 `.venv/bin/python .research-tree/experiments/incident_replay.py`
- CI：push 后看 Actions 结果；失败先读日志再修

## 6. 整个批次的 Definition of Done

1. 16 个 issue 的 PR 全部被 TEST + ACCEPT approve（#205 有两个 PR：降级 + 回升）
2. replay 4/4 全部 `forbidden_outcome_observed == false`
3. `.venv/bin/python -m pytest -q` 全绿（既有 5 个失败中的遗留项需在 PR 中注明；与本批相关的一律修复）
4. CI（release-check）绿
5. ISSUE-SPECS.md 与实际实现一致（无超前契约）
