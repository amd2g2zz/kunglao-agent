# Proposal: issue-831-secondstop-anchor

## Why

`hooks/completion_gate.py` second-stop 分支只读 `task-oracle.yaml` 的
`adjudication.stop_hook_active = {second_stop: true, last_decision: PASS}`
即放行——**任何人可自写、可回填**（#831 现场：回填 65 分钟、mtime 之前，
3 个 claim 仍 open）。second-stop 反循环保护因此可被涂抹。

## What Changes

1. **锚定**：gate 判定 sanctioned PASS 通过时，把豁免事件追加写入
   workspace ledger（`.convergence_ledger.jsonl`，append-only）：
   `{type: second_stop_pass, actor: completion_gate, record_sha256, ts, detail}`。
   `record_sha256` = 对 `adjudication.stop_hook_active` 映射的 canonical JSON
   （sort_keys）sha256。
2. **对账**：ledger 已有锚定时，oracle 记录 hash 必须与任一锚定一致——
   一致 → 放行（不重复锚定）；**不一致 → BLOCK（fail-closed，#831 核心攻击面：
   首次制裁后改写/回填记录）**。
3. **legacy 升级**：零锚定的 workspace 首次 sanctioned second-stop 按现行
   语义放行并在 ledger 补锚（不回退既有测试）。
4. **双笼方向**：ledger 不可读 / 锚定写失败 → BLOCK（fail-closed）——
   second-stop 本就是"无制裁不得放行"的面，写不进锚等价于无法证明制裁。
   oracle 不可读/形状异常 → 维持既有 generic BLOCK。

## Threat Model & Residual

- 封死：首次制裁后的**改写**与**回填**（hash 对账）。
- 残余（显式记录，指向后续卡）：①零锚定窗口内的伪造（首次 sighting 不可
  区分 legacy 升级与"锚被删"——需 #825 身份绑定提供 out-of-band 信任根）；
  ②ledger 文件本身被改写（同攻击者模型，#829 跨载体一致性 / #825 为后继）。

## Decision

- 行格式复用 rollup._append_ledger 的 CONTRACT（json.dumps ensure_ascii=False
  + newline）；shim 内置最小 append writer（不 import 整个 rollup 机器）。
- 不改 status_defs.LedgerLineType（新 type 字符串 `second_stop_pass`，
  消费者自过滤，避免与并行 W2 卡冲突）。
- **fail-closed 声明**：本变更属结构门语义（#147/#199 家族），全部异常
  路径 BLOCK，不引入新的 fail-open 面。

## Out of Scope

- runs/oracle-adjudication-*.md 制裁出处记录（issue sketch 的 provenance 面，
  属 #825 身份绑定）；`last_decision_at` ≤ mtime 的时钟锚（被 hash 对账
  严格覆盖，仅在零锚定窗口有增量价值——记入 residual）。
