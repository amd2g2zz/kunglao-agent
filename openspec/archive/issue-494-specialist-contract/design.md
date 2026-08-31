# Design — specialist contract expansion (#494)

## 问题边界

"契约扩写" = 在 #492 三标记 span 内追加实质指令字节。**不是**本变更:

- 不改标记文法 / span ≥2 非空行判据(Gate 6 原样,扩写后 8/8 仍过);
- 不动 frontmatter / `triggers:`(`scripts/route_capability.py` 消费面,
  零字节改动);
- 不重写既有 prose(#492 最小块原样保留,新内容接在其后,同一 span 内);
- 不动 `agents/kunglao-worker.md`(模板,12+6+2 已达标);
- 不做 prose 条款枚举(教义:任何语言不可穷尽;断言走结构化 token)。

## D1. 扩写统一骨架(7 agent 一致)+ 领域实例化

| element | 统一骨架(全部 7 个) | 领域实例化(每 agent 不同) |
|---|---|---|
| plan-to-execute | 第一个动作写 `runs/worker-status-<agent>-<id>.md` plan 段:what / expected artifacts / done criterion;drift → 更新;`plan_vs_actual:` 收尾 | ghidra-light: 反编译目标 + 预期 pseudo-C;verdict-scorer: PQ 清单 + 预期 verdict 结构;go-symbols: unstrip 子命令序列 + 四产物字段;… |
| status-sync | #444 canonical(单一解析点 + 三词 + 尾 token wins)+ W-15(`status: done` 行带 `artifacts:` 清单)+ heartbeat 响应 | 每 agent 的 artifacts 清单 = 其产物文件(如 evidence/static-ghidra.json、四个 unstrip 文件、verdict.json) |
| tool-discovery | 三查(scripts/re / tools/_INDEX.yaml / re-library)+ 禁自造(issue 上游化 / 垫片即弃)+ 真实工具名清单 | 每 agent 3-5 个域内工具名(从 _INDEX.yaml / scripts/ 复制) |

## D2. 工具名真实性 = 机械可验(本设计的关键决策)

#462 事故根因之一是"现成工具不可见"。扩写要求 tool-discovery span 列
3-5 个工具名 — 但 prose 里的名字可以凭记忆写错(虚构 / 过期 /
改名)。因此 RED 测试做**可解析断言**:span 内
`Registered domain tools (…):` 行的每个 backtick 名必须解析到

```
tools/_INDEX.yaml 的 tools[].name ∪ scripts/*.py 文件名 ∪ tools/**.py 文件名
```

名字是从 _INDEX.yaml / scripts/ **复制**的,测试防将来腐化(数字口径
保真的同类纪律:引用面必须可回验原始源)。非 RE 的 init-worker /
verdict-scorer 同样适用:它们的域工具是 scripts/ CLIs
(`kunglao-init.py` / `toolchain.py` / `env_manifest.py` …)与
_INDEX 辅助项(`audit-legacy-proven` / `measure-blind-coverage`)。

## D3. RED 测试通道纪律

断言对象是**结构化 span 内的 load-bearing token**,非自然语言句式:

- plan span:`runs/worker-status-{agent}` 命名、plan / expected / done
  关键词、每 agent 一个领域 token(pseudo-C / unstrip / Authenticode /
  primary_question / REFUTED / toolchain / top-K);
- status span:#444 三词(in-progress / done / blocked)、`artifacts:`、
  heartbeat、`lib_kunglao`(单一解析点指针);
- tool span:`scripts/re`、`_INDEX.yaml`、re-library(5 个 RE
  specialist)/ `references/`(init-worker / verdict-scorer 的参考
  通道)、issue(上游化)、shim(垫片即弃)、工具名行 ≥3 且全可解析。

领域 token 是"领域语言"要求的最小锚(每 agent 1 个),不构成条款
枚举;枚举自然语言条款仍是禁路(memory: structural-declaration-over-regex)。

## D4. status 文件命名标准化

kunglao-worker 历史用 `worker-status-<task>.md`(项目根);
#444 的 `iter_worker_states` 扫描面是 workspace `runs/` + 各 worker
worktree 的 `runs/`;init-worker 已用 `runs/worker-status-<id>.md`。
#494 统一 specialist 命名为 `runs/worker-status-<agent>-<id>.md`
(agent 名入文件名 → dispatch 端 worker-status 与 agent 可对账;
路径落在 canonical 扫描面内)。kunglao-worker 的旧命名不在本变更
纠偏范围(模板文件零改动纪律优先)。

## D5. 验收映射(issue #494 三条 → 证据)

| issue 验收 | 证据 |
|---|---|
| 8 specialist agents 各含 plan/status/tool-reuse 三段声明 | Gate 6 8/8 PASS(既有)+ 本变更 7 文件 span 扩写(diff) |
| lint 全 PASS | `uv run python devkit/quality_gates.py 1 3 4 5 6` ALL-PASS(worktree 本地) |
| dispatch 时按声明顺序 plan → status → tools → 出评审 | RED 测试锁定三 span 的顺序产物命名与义务(span 内 token 断言);执行层由 Gate 5 / #493 注入测试接手 |

## R1-R5 风险

- **R1 扩写变成重写**:纪律 = Edit 锚点只接在既有 span 内容之后;
  diff 审查既有行零改动(内容纪律 ⑤)。
- **R2 工具名腐化**:D2 可解析断言兜底。
- **R3 span 内容被 fence 吞**(agent 文件多代码块):新内容零 fence;
  lint 的围栏豁免逻辑已覆盖既有块(#492 测试锁定)。
- **R4 verdict-scorer 无 Bash 的诚实性**:它的三查措辞为 Grep/Read
  可执行形式(不能 ls 就写 Grep),禁自造义务落在"不得重实现门
  输出 / 不得发明证据"。
- **R5 worktree hook 假绿**(pre-commit devkit 路径指向主检出):
  每 commit 前手动跑 worktree 本地 `devkit/quality_gates.py 1 3 4 5 6`
  (计划 Task 2 ④ 纪律)。
