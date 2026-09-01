# issue-867-governance-wording — 治理措辞机器绑定（弃用符号活体调用收口 + SKILL 教学形状一致性 + evals 对账）

## Why

#819 关单审计的泛化病："仓库自己的 ledger/prompt 断言一件事，代码做另一件事"。两实例：
D2（弃用 ranker 仍承重——priority.py `DEPRECATED=True` 但 external_kicker 活体调度经它，
try/except 静默降级）与 B1（SKILL 曾教已退役的 v0 dispatch 形状，检测器正则副本对 v1
canonical 信封失配 → recall 注入实际失灵）。#861 已落地大部分机器绑定（单源 parse_dispatch、
retirement_gate 雏形、v1 命中测试钉），但把"清偿已知债务 + 三检查挂 devkit/CI"显式挂账到
#867。本卡 = 清偿 + 补全挂点。

## Recon

### 锚点表（计划锚点 vs 实测，wt-867 @8450963）

| 计划锚点 | 实测 | 判定 |
|---|---|---|
| v1 canonical 信封唯一权威定义处 | `hooks/lib_kunglao.py`：`DISPATCH_JSON_START_RE`:63、`DISPATCH_PROTOCOL_VERSION=1`:67、`parse_dispatch_json`:135、`parse_dispatch`:171（v1 优先，v0 `DISPATCH_RE`:44 legacy-replay 回退）；协议文档 `references/dispatch-protocol.md:16-38` | ✓ |
| 两处 v0-only 正则现行形态 | **已被 #861 修复**：`hooks/recall_inject.py:63-70` `_is_claim_dispatch` 与 `hooks/worker_pulse.py:142-155` `_was_dispatch` 均已改走 `lib_kunglao.parse_dispatch`（本地 v0 正则副本已退役）；`hooks/worker_budget_core.py:282-300` 同样委托 lib | 偏航 Y1（活体 bug 已不存在） |
| v1 信封正测试样（canonical 命中 / v0 不误伤） | `tests/test_v0_retirement_861.py:31-50` 已钉两处命中 + 三 parser 一致性（:67-74） | ✓ 已达标 |
| `priority.py:72` DEPRECATED 标记 | `scripts/priority.py:72` `DEPRECATED = True`；`:73` AUTHORITY 指向 priority_ratio | ✓ |
| external_kicker 四处活体调用（:630/640/673/810） | `scripts/external_kicker.py`：`:630` `import priority`、`:640` `priority.rank_claims(...)`（在 `_priority_ordered_ids`:621 内）、`:673` `build_resume_prompt` 调 `_priority_ordered_ids`、`:810` tick 调 `build_resume_prompt`；另有 `:687` prompt 文本**教 orchestrator 用 `scripts/priority.py rank_claims`**（措辞面活体） | ✓（行号未漂） |
| try/except 静默降级点（:642-643） | `external_kicker.py:643-644` `except Exception: return open_ids`（静默回退注册表序，无任何信号） | ✓ |
| evals 对 ranker 的钉法（:6-11） | `evals/evals.json` eval#1 三处钉 priority.py 排序为预期行为（:6 prompt、:7 expected_output、:11 expectations） | ✓ |
| mechanisms.md v0 RETIRED 宣告 vs SKILL.md:193 v0 教学形状 | `references/mechanisms.md:33` RETIRED 行（audit 声明"zero production v0 callers remaining post-#452"）；`skills/kunglao-agent/SKILL.md:193` **已被 #861 改教 v1 canonical 信封**（v0 形状仅以 replay-only 措辞提及） | 偏航 Y1 同源 |
| 三项机械检查挂哪、怎么被 CI 调 | devkit 门框架：`devkit/quality_gates.py` GATES 注册表:251（现 1-7）；CI=`.github/workflows/release-check.yml:79-83` 跑 `devkit/quality_gates.py 1 3 4`；pre-commit 快速集=`devkit/githooks/pre-commit:72` 跑 `1 3 4 5 6 7`；lockstep 测试 `tests/test_agents_lint.py:396-423` 从 GATES 注册表派生快速集强制 pre-commit 模板同步 | ✓ |
| ——（计划未列，实测新增） | `scripts/retirement_gate.py` **#861 已交付检查①机制**（RETIRED 正则散副本 + DEPRECATED 活体 caller + baseline 棘轮 `scripts/.retirement-gate-baseline.txt`），但**未挂任何门/CI**；baseline 恰有一条 `deprecated_live_caller:priority<-scripts/external_kicker.py`，docstring 明言"挂账 #867 清偿"；`tests/test_retirement_gate_861.py:94-103` 钉该债务现状 | 偏航 Y2 |
| ——（计划未列，实测新增） | `tests/test_scorer_authority.py:43-56` `LIVE_PATH_SURFACES` 权威措辞巡检**不含** `scripts/external_kicker.py` 与 `evals/evals.json`——正是两处残留措辞逃逸巡检 | 偏航 Y3 |

### 变更前测试基线

- 受影响面（v0_retirement_861 / retirement_gate_861 / dispatch_protocol / scorer_authority /
  mechanisms_retirement / evals_schema / evals_fixture_530 / external_kicker）：
  `python -m pytest <8 files> -q` → **122 passed**。
- 全量基线另测（本地门用；Windows 已知 7 个环境性失败按 orchestrator 清单甄别）。

### 镜像样例（≥3）

1. **canonical ranker 进程内调用**：`scripts/kunglao-decide.py:163-172` ——
   `_load_yaml(ws/"claim-register.yaml")` + `_load_yaml(ws/"claim_deps.yaml")` +
   `pr.EvidenceView.from_workspace(ws)` + `pr.priority_ratio(claims, deps, evidence)`。
   external_kicker 收口按此形状（同在 scripts/ 下，直接 `import priority_ratio` 与
   `kunglao-decide.py:29` 同款）。
2. **devkit 门委托形状**：`devkit/quality_gates.py:193-219` Gate 7 —— `sys.path.insert`
   devkit 后 `from <module> import check`，`bool(rc == 0)` 真值守卫；新 Gate 8 同构。
3. **基线棘轮**：`scripts/retirement_gate.py:52-100` scan/main（findings ⊆ baseline → 0，
   新 finding → 1）；真仓状态钉在 `tests/test_retirement_gate_861.py:94-103`。
4. **权威措辞巡检**：`tests/test_scorer_authority.py:307-313`
   `test_live_path_prescribes_authority_only`（`"priority.py" not in text`）。

### 偏航记录（实现级，不触发 RECON-DEVIATION）

- **Y1 两处活体 bug 已被 #861 修复**：recall_inject / worker_pulse 的 v0-only 正则副本
  已退役并单源化到 `lib_kunglao.parse_dispatch`，v1 命中测试钉已存在（122 基线绿含此）。
  本卡任务 1 从"修 bug"收缩为"验证 + 保持钉"（不再重复实现）。WHY：实测 HEAD 代码形态。
  验收项"v1 信封命中测试钉（recall/worker_pulse 两处同测）"已由
  `tests/test_v0_retirement_861.py:31-50` 满足，本卡补真仓回归测试不删既有钉。
- **Y2 检查①机制已存在（retirement_gate.py），缺的是挂点与清偿**：#861 把活体 caller
  检查落成了 `scripts/retirement_gate.py` + baseline 棘轮，并把
  `deprecated_live_caller:priority<-scripts/external_kicker.py` 挂账 #867。本卡不做第二份
  检查实现，直接：收口 external_kicker → 清空 baseline 条目 → 把 retirement_gate 挂进
  Gate 8 与 CI。红→绿演示：收口前 retirement_gate 对真仓 exit 1（NEW finding），
  收口后 exit 0（实测见 tasks）。
- **Y3 SKILL 教学形状检查从"改 v0 教学段"收缩为"parse-through-detector 强化"**：
  SKILL.md:193 已教 v1（#861），既有测试只钉字符串存在（`test_v0_retirement_861.py:77-82`）。
  本卡新增检查②：SKILL.md 内每个 `kunglao_dispatch` JSON 样本（含占位符 schema 形状，
  占位符容忍替换后）必须经 `hooks/lib_kunglao.parse_dispatch_json` 解析命中；v0 形状字面
  出现行必须带 replay-only 标记。教学形状与检测器同源 = 直接喂检测器函数。

### Orchestrator 预裁决执行

external_kicker 处置 = **收口**（活体调用改走 canonical priority_ratio 路径；DEPRECATED
的 priority.py 符号保留到下个清理窗口，不真删——#446 退役流程负责）。检查①因此转绿，
本卡不改验收标准。

## What Changes

1. **收口 external_kicker**（#867 清偿）：`_priority_ordered_ids` 弃用
   `import priority` + `priority.rank_claims`，改走 `priority_ratio.priority_ratio`（镜像
   kunglao-decide 形状）；降级路径保留 fail-open 但补 stderr 信号；`:687` prompt 措辞
   `scripts/priority.py rank_claims` → `scripts/priority_ratio.py --json`；`:92`/:659 注释同步。
2. **清偿 baseline**：`scripts/.retirement-gate-baseline.txt` 清空（带注释头说明清偿记录）；
   `tests/test_retirement_gate_861.py:94-103` 真仓断言改为零 findings + 空 baseline。
3. **检查② SKILL 教学形状 vs 检测器一致性**（新）：提取 SKILL.md 内 `kunglao_dispatch`
   JSON 样本 → 占位符容忍（`C-NN`/`<N>`/`...` 替换后）→ 必须经
   `lib_kunglao.parse_dispatch_json` 命中 claim；v0 形状字面行必须带 replay-only/legacy
   标记。缺样本/解析失败/无标记 → 红。
4. **检查③ evals 期望值 vs 弃用状态对账**（新）：机械弃用注册表 = `scripts/*.py` 含
   `DEPRECATED = True` 的模块 stem；扫描 `evals/*.json` 全部字符串值，命中弃用模块引用
   （`<stem>.py` / `scripts/<stem>`）→ 红，例外清单 `devkit/governance-exceptions.json`
   可豁免。eval#1 改写为 priority_ratio 措辞（三处）。
5. **Gate 8 "Governance Binding" 挂点**：新 `devkit/governance_binding.py`（stdlib-only，
   check() -> 0|1 + CLI `--check all|callers|skill|evals` 支持红/绿两态演示）：
   (a) 弃用活体 caller——委托 `scripts/retirement_gate.scan`（棘轮语义保留）；
   (b) SKILL 教学形状；(c) evals 对账。注册 `devkit/quality_gates.py` GATES[8] +
   docstring；pre-commit 快速集 `1 3 4 5 6 7` → `1 3 4 5 6 7 8`（lockstep 测试派生强制）；
   CI `release-check.yml` `1 3 4` → `1 3 4 8`；`devkit/docs/quality_gates.md` 门清单 prose 补
   Gate 8 行。
6. **巡检面补漏**：`tests/test_scorer_authority.py` LIVE_PATH_SURFACES 增
   `scripts/external_kicker.py` + `evals/evals.json`（收口与 eval#1 改写后两文件不再含
   `priority.py` 字样，巡检获得机械牙）。
7. **清单联动**：external_kicker.py 变更 sha → `deploy_manifest.py --write` + `--verify`；
   `release_receipt.py --check` 兜底。
8. **测试**：新 `tests/test_governance_binding_867.py`（收口红/绿、三检查 tmp 仓红/绿两态、
   Gate 8 注册 lockstep、evals 改写钉、LIVE_PATH 扩面钉）。

## Impact

- 受益：治理措辞三面（活体 caller / SKILL 教学 / evals 期望）全部机器绑定并可 CI 拦截；
  external_kicker 排序从弃用加权公式切换到唯一权威 priority_ratio（删除 priority.py 不再
  静默降级——收口后该模块零生产 caller）；#446 退役窗口的删除操作从此无承重风险。
- 风险：external_kicker 排序语义变化（weighted-sum → VoI ratio）改变 kick prompt 的截断
  顺序——这正是收口目的（退役排序不该承重）；测试面 lockstep（agents_lint 快速集派生、
  retirement_gate 真仓钉）联动更新同 PR 完成。
- 边界：不真删 priority.py（#446 窗口）；不动 worker_budget_core 的 v0 裸前缀本地回退
  （其注释已声明为 budget 本地合同）；不改 retirement_gate 棘轮语义；不做 SKILL.md 之外
  文档的教学形状检查。
