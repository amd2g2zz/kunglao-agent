# Proposal — specialist agents 三要素契约扩写:最小块 → 真契约 (#494)

## Why

Issue #494(#462 拆件二,#462 已关;#492 已落地标记)。Gate 6
(`devkit/agents_lint.py`)给 8 个 agent 定义补上了三要素**结构性标记**,
但 7 个 specialist 的 span 内容是最小块(每 span 2-4 行,刚过 ≥2 行
实质门)— 它是 lint 的占位声明,不是运行时契约。#462 现场事故
(ghidra-light worker:无计划开干 / 全程不写 worker-status / 手写
`DecompileFuncs.java` + 201 行 headless 驱动而 `ls scripts/re` 就有 25+
现成工具)在最小块下没有行为约束力:标记在,实质不够。

kunglao-worker 模板有 12 plan + 6 status + 2 tool-reuse 条目;
specialist 恰是长时跑、高爆炸半径的角色,契约必须同厚度。

## What Changes

- **7 个 specialist agent**(ghidra-light / go-symbols / floss-filter /
  pefile-signature / verdict-scorer / kunglao-init-worker / kunglao-redteam;
  kunglao-worker 是模板,不动)在 #492 标记 span 内扩写,每 span 增
  ~10-20 行:
  - **plan-to-execute**:开工第一个动作 = 写
    `runs/worker-status-<agent>-<id>.md` 的 plan 段(将做什么 / 预期
    产物 / 判定完成标准),用各自领域语言(ghidra-light: 反编译目标
    函数 + 预期 pseudo-C;verdict-scorer: PQ 清单 + 预期 verdict
    结构)。drift → 更新计划再继续;收尾 `plan_vs_actual:`。
  - **status-sync**:#444 canonical WORKER_STATUS 语义
    (`hooks/lib_kunglao.py` 单一解析点,`WORKER_STATUS_RE` 尾 token
    wins,词汇仅 in-progress/done/blocked)+ W-15 artifacts 声明义务
    (`status: done` 行必须携带产物文件清单,
    `scan_done_artifact_violations` 回验路径存在;`artifacts: none`
    = 零产物完成即 W-15 违规)+ heartbeat 响应(ping 即答,不让
    "在跑"被 3-strike 看门狗误判"卡死")。
  - **tool-discovery**:动手前三查(`ls scripts/re` 工作区 RE 工具 /
    grep `tools/_INDEX.yaml` 工具架 / `references/re-library/` 相关域
    文件)+ **禁止自造通用工具**(缺工具 = 提 issue 上游化进 tools 层;
    一次性垫片须标注即弃 — #462 原文)+ 每 agent 列 3-5 个**经
    `tools/_INDEX.yaml` / `scripts/` 核实的真实工具名**。
- **RED 测试** `tests/test_specialist_contract_expansion.py`:扩写内容
  存在性断言(每 span 的 load-bearing token + worker-status 命名 +
  #444 三词 + `artifacts:` + heartbeat + 三查清单)+ **工具名可解析
  断言**(tool-discovery span 的 "Registered domain tools" 行内每个
  backtick 名必须 ∈ tools/_INDEX.yaml 工具名 ∪ scripts/*.py 文件名 —
  防虚构/过期工具名,定义层镜像 #462 自造事故)。
- **Gate 6 判据零改动**:标记文法与 span ≥2 非空行判据原样;扩写只
  在 span 内追加内容行,8/8 agent 扩写后仍过 lint。

## Impact

- **agent 定义**(7 文件,span 内 additive only):既有 prose /
  frontmatter / triggers 零改动(`route_capability.py` 消费面不动)。
- **测试**:tests/test_specialist_contract_expansion.py(新,RED 先行)。
- **行为面**:specialist dispatch 时 subagent 按声明顺序写
  plan → status → tools → 出评审(issue #494 验收第三条)。
- **不做**:不动 kunglao-worker.md;不改 `devkit/agents_lint.py`;不加
  第 4 个标记元素;不做 prose 条款枚举(教义:结构化声明优于
  prose regex)。
