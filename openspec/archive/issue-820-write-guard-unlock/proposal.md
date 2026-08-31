# issue-820-write-guard-unlock

## Why

write_guard 的 lint leg 对 FACT/NOTE/REGISTER 载体跑 `lint_workspace(shadow)` 并把**全仓**错误计入拦截——一个早期 legacy fact 的 schema 违规（豆包现场 F001/F002：102/129 violations）连坐锁死所有后续 fact 写入（F007/F010 被 BLOCK，且 detail 2000 字符硬截断），无迁移/解锁路径。工作区级写入死锁（HIGH）。

## What Changes

1. **lint 打击面收敛**（hooks/write_guard.py `adjudicate()`）：lint_workspace 错误按**目标文件归因**（msg 前缀 `文件名:` = lint_facts 既有格式）——只拦目标文件自身的违规；REGISTER 载体的写入不再吃 fact-lint 连坐（其合法性由 proven-gate leg + 转换自身检查裁决）。与 write_gate leg 既有按文件过滤同构。
2. **block detail 携带修复面**：拦截时附"其他文件违规分布"摘要（文件名→计数），即"修哪些文件"的最小集；不再静默截断语义（detail 截断保持 2000 字符物理限，但归因摘要置顶）。
3. **解锁/迁移通道**（新 scripts/write_guard_unlock.py）：
   - `unlock --file <name> --reason "<why>"`：目标文件的 lint 违规豁免（迁移中重写合法化），落 runs/write-guard-waivers.yaml + ledger 事件 `write_guard_unlock`；每次豁免消费落账 `write_guard_waiver_used`
   - `quarantine --file <name> --reason "<why>"`：facts/<name> → facts/_quarantine/<name>（lint glob 非递归，天然退出语料）+ ledger 事件 `write_guard_quarantine`
   - `list`：当前豁免/隔离清单
4. **不弱化门**：目标文件自身无豁免时违规照拦（fail-closed 不变）；write_gate R1/R2 leg、supersedes leg、proven-gate leg 全部不动。

## Impact

- hooks/write_guard.py（adjudicate lint leg 归因化 + 豁免消费）
- scripts/write_guard_unlock.py（新）
- tests/test_write_guard_unlock_820.py（新）
- scripts/README.md（catalog 行）、deploy-manifest.yaml / tools/_INDEX.ext.yaml（重生成）
