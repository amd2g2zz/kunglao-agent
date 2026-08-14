# GLOBAL-DEV-PLAN-B4 — #278 剩余阶段（P3 frida 模板 + P4 编排智能 + P5 收尾）

> owner 的 6 阶段 14 PR 计划（runs/plan-278-absorption.md 口径）已交付 Phase 0-2。
> 本计划交付剩余可离线执行部分：P4 编排智能三件套（纯确定性代码）+ P3 frida CFG 模板（模板化，验证留 VM）+ P5 收尾。
> 权威规格 = issue #278 正文 + owner 设计定稿评论（智能使用层/统一紧凑/tool-search 决策）。

## 0. 基线（2026-08-14）

- dev @ 3f2779d，CI 绿；唯一 open issue = #278
- 已交付（owner PR #282-#295 + 我方 #298）：tools/ 6 分类 + _INDEX.yaml（14 工具）+ validate_index.py + crypto/ghidra/static 工具集 + template_gen.py 3 模板
- 缺失：P3 frida CFG 模板（tools/frida/ 空壳）、P4 三件套（tool-search.py / feature_probe.py / route_capability.py + pipelines/recipes/）、P5 收尾验证

## 1. 角色（三 agent 互斥，同前批）

DEV=tdd-guide 实现 / TEST=python-reviewer 验证 / ACCEPT=code-reviewer 验收。合并由主控执行；门证据 = PR comment（自审阻断已知）。

## 2. 波次

```
Wave A（并行，零文件重叠）:
  278a: tools/tool-search.py（确定性 catalog 查询）+ scripts/feature_probe.py（快速特征探测）
       —— tool-search 只读 tools/_INDEX.yaml；feature_probe 新脚本 + tests
  278c: templates/frida/ CFG 模板（JS hook 模板 + plan 模板 + README；纯模板，不注册工具）

Wave B（依赖 278a 合并后）:
  278b: scripts/route_capability.py（特征+claim 意图 → 推荐链+置信度+备选；规则 + tool-search 兜底）
       + tools/pipelines/recipes/*.yaml（stage-unpack/crypto-decrypt/syscall-chain/iat-chain/go-recovery
       5 recipe；实例化 = 生成 runs/plan-C<NN>.md 填充模板）+ 注册 recipes 目录到 tools/_INDEX.yaml 注释区

Wave C（收口）:
  全量 pytest 绿 + CI 绿 + tools/validate_index.py 通过 + 复用率验证框架落档 + #278 关闭或注明剩余
```

**SKILL.md 不动**（owner #253 契约已定稿；P4 派发流程接线 = dispatch_gate 调 route 属后续 issue，本批只交付工具与 recipe 模板）。

## 3. 关键契约（owner 设计定稿，必须遵守）

- route_capability.py 与 priority.py 同族：读同一份状态（claim-register/evidence/runs/env 快照），**零新状态格式**
- recipes 是 runs/plan-C<NN>.md 的填充模板，复用现有 plan 格式；无新 executor
- 新增面收敛为 4 件：tools/_INDEX.yaml（契约/成本档）+ route_capability.py + pipelines/recipes/ + feature_probe.py + tool-search.py
- 全部 #277 契约：参数化、无硬编码、可注入、幂等、明确输出
- tool-search 不做 LLM 语义检索；--capability/--tier/--cost-max 精确过滤，零 token

## 4. TDD 循环 + PR 规则（同前批）

RED（契约测试先红）→ GREEN → IMPROVE → 提交 `feat(#278): ...` → push → PR（body: ref #278 + RED + GREEN）→ TEST+ACCEPT 双门 → 主控 rebase+合并。
分支：`fix/278a-tool-search` / `fix/278b-route-recipes` / `fix/278c-frida-template`。

## 5. DoD（批次）

1. 三个 PR 双门通过并合入 dev；#278 剩余项全部交付或显式注明阻塞
2. 全量 pytest 绿 + CI 绿 + validate_index 绿 + structural/receipt 绿
3. 工作区单一干净 worktree，停留 origin/dev 最新
