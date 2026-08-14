# tools/pipelines — 组合 recipe 模板

本目录是 `pipeline` 类目的工具家之一, 含 `recipes/*.yaml`: **plan 生成模板(templates), 不是执行器**。本目录无本地 .py 脚本是**设计使然**: recipe 是纯数据(声明"哪些已注册工具按什么顺序组链"), 执行由各已注册工具(`tools/_INDEX.yaml`)承担, 实例化(生成 `runs/plan-C<NN>.md`)是后续接线工作。

## 与索引文档的关系

worker 先读 `tools/_index-pipeline.md`(pipeline 域工具契约条目, 如 `build-evidence-index`); 本 README 说明 recipe 的 schema 与目录。机器契约见 `tools/_INDEX.yaml`(recipe 是纯数据模板, 不注册)。

## Recipe schema (schema: plan-recipe/1)

```yaml
schema: plan-recipe/1
id: stage-unpack                       # 唯一 recipe id, kebab-case
title: 分阶段解包 (stage-unpack)        # 人类可读标题
description: >-                        # 何时使用 + 干什么
steps:                                 # 主链: 顺序执行 (>=1)
  - tool: ghidra-recon                 # 工具名 (tools/_INDEX.yaml) 或能力查询
    input: 样本 + packer/overlay 标记   # 本步输入 (可含参数)
    output: packer 判定 + 区段布局       # 本步输出
fallback: [ghidra-decompile-functions, ghidra:recon]   # 主链失败时的回退链
verify: unpack-verify                  # 校验 hook 名 (记录步骤前必须通过)
reuse_check: 同 sha256 样本已有解包产物时直接复用, 不重复解包
```

- `steps[].tool` 与 `fallback[]` 条目: **工具名**(必须登记在 `tools/_INDEX.yaml`)或**能力查询**(`domain:op`, 与 `tools/tool-search.py --capability` 同语义: 精确/前缀匹配)。能力查询在实例化时经 tool-search 解析为具体工具; 本仓库暂无工具的能力(如 `languages:go`)以查询形式保留在链中。
- `verify`: 校验 hook 名称 — 实例化时生成 runs/plan-C<NN>.md 的验证步骤, hook 未通过则计划不得推进(fail-closed)。当前仅声明名称, 不实现 hook。
- `reuse_check`: 复用判据描述 — 实例化时生成"先查复用"步骤, 已有产物则跳过本 recipe。
- 校验: `tests/test_recipes.py` 强制 schema 键完整性 + 词汇表一致性(所有 tool/fallback 条目必须命中真实 index)。

## Recipe catalog

| id | 何时使用 (路由信号) | 实例化产物 |
| --- | --- | --- |
| `stage-unpack` | overlay 标记 / packer 标记 (string_density + packer markers) | 解包链 plan: ghidra-recon 定位打包层 → crypto-tool 压缩子命令分层解开 → disasm-constant-check 校验 |
| `crypto-decrypt` | crypto:decode 信号 (crypt32/bcrypt/advapi import 或高熵区段) | 解密链 plan: 加密 API 定位 → crypto-tool 算法解密 → 明文层校验 |
| `syscall-chain` | 动态意图 (vm/run/execute/detonate 或 syscall 关键词) | syscall 链 plan: 调用点定位 → 反编译 stub → syscall 号断言校验 |
| `iat-chain` | iat 意图 (import/IAT 关键词) | IAT 链 plan: IAT 解析 → xref 指针扫描 → 调用断言校验 |
| `go-recovery` | languages:go 标记 (go.buildinfo / runtime.* hints) | Go 恢复 plan: pclntab 定位 → go-byte-transform 恢复符号 → 恢复层校验 |

## 实例化 (future wire-in)

实例化 = 由 recipe 生成 `runs/plan-C<NN>.md`(claim 计划文件, 遵循现有 runs/plan-C<NN>.md 填充模板角色): 每步展开为计划条目(工具 + 输入 + 输出), `fallback` 展开为回退分支, `verify` 展开为验证 gate, `reuse_check` 展开为复用检查。接线由后续 issue 完成; 当前无生产消费方(目录化读取仅由 `tests/test_recipes.py` 契约测试覆盖)。

## 约束

- 模板是纯数据: 无执行器代码, 不注册进 `tools/_INDEX.yaml`, 不创建新状态格式。
