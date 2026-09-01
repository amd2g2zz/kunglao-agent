# issue-866-discovery-gate — proposal

## Why

工具建造与发现面接入是断开的两个流程（#866：tools/ 65% 零发现面、scripts/ 侧大量
"造完即封存"）。三层分离已定案：声明=资格门、发现=提示、选用=自决+反馈学习。
本 change 交付"门"与"真实清单"：孤儿指标产线语义化（de-whitewash）+ 新 CLI 发现面
机械门。issue #866 本体两支 PR 共用本 change 目录：

- **PR 866-a**（本卡先行）：产线语义档 + README 双口径 + 发现面 CI 门。
- **PR 866-b**（另行派发）：存量逐个鉴定（登记四发现面 / 退役）+ Ghidra 四件套 +
  scripts/ 侧鉴定表 + deploy-manifest 对账。

## What（PR 866-a 范围）

1. `scripts/relib_audit.py` 增**产线语义档**（`--production <repo_root>`）：对
   scripts/*.py 全量 + tools/ 带 `__main__` CLI 计算产线接线（种子面 =
   hooks/skills/agents/devkit/CI/tools/_INDEX.yaml；tests/openspec/docs/references/
   两级 manifest 为诊断面不计数；传递闭包 = 消费边 filename/import）→ 输出真实
   未接线清单（tools/ 与 scripts/ 两侧）。
2. `scripts/README.md` Orphans **双口径声明**：测试语义（tests 计 live，现状保留）
   + 产线语义（relib_audit --production 口径 + 复现命令 + as-of 快照数字）两行并存，
   杜绝单口径洗白；配机械回归测试防"删行回洗"。
3. **发现面 CI 门**（`devkit/discovery_gate.py`，注册为 quality_gates Gate 9）：
   tools/ 带 `__main__` 的新 CLI 必须同帧登记 tools/_INDEX.yaml +（SKILL 教学段或
   references 条目），缺失即红；基线棘轮（`devkit/.discovery-gate-baseline.txt`）
   承接存量债务（866-b 清偿），新未登记 CLI → exit 1。CI release-check 步骤与
   scripts/local_gate.py 同步挂门。

## 约束

- 机械门非文档约定：红/绿两态可演示（未登记假 CLI → 红；登记 → 绿）。
- relib_audit 既有 lib 审查（orphan/tracker/missing_decl + quarantine）行为不变，
  既有测试不回退。
- Gate 9 确定性、stdlib-only、无网络；门计数措辞 number-free（Gate 7(a) 自检面）。
- 本 PR 不做 22 个存量处置（866-b），基线文件只承接不扩大。

## Out of scope

- 存量 22+32 个鉴定执行与 Ghidra 四件套登记（PR 866-b）。
- 价值数据通道（#879/#880/#881/#882 四卡）。

## Recon

### 锚点表（计划锚点 vs 实测）

| 计划锚点 | 实测 | 结论 |
|---|---|---|
| #854 交付的 relib_audit 检查器 | `scripts/relib_audit.py`（#817 检查器经 PR #854 合入，539a081）；CLI `python scripts/relib_audit.py <lib_dir> [--json]`；现有档位=孤儿/tracker 残留/声明行缺失 + quarantine | 产线语义档加为第 4 档：同文件新增 `audit_production()` + `--production` 模式 |
| scripts/README.md Orphans 指标声明处 | `scripts/README.md:11-13`——"Orphans: 0 … tests/ count as references"（单口径=测试语义）；`:8-10` "Total scripts: 94"（**已漂移，实测 169**） | 双口径声明落在 :11-13 块，顺手修正总数漂移（在编辑块内） |
| CI 门挂点惯例 | `.github/workflows/release-check.yml:79-85` "Run quality-gate framework" 步骤跑 `uv run python devkit/quality_gates.py 1 3 4 8`；门模块放 devkit/（`governance_binding.py` 经 sys.path 引 scripts 引擎的先例） | Gate 9 挂同一 registry + 同一 CI 步骤（1 3 4 8 → 1 3 4 8 9）+ `scripts/local_gate.py` 本地同帧 |
| 基线棘轮先例 | `scripts/retirement_gate.py` + `scripts/.retirement-gate-baseline.txt`（findings ⊆ baseline → 0；新 finding → 1） | `devkit/.discovery-gate-baseline.txt` 镜像同形 |
| Ghidra 四件套现状 | `tools/ghidra/ghidra_diff.py` `ghidra_job.py` `run_ghidra_postscript.py` 均**无产线种子面**（仅 release-manifest.yaml:84-92 发布 + deploy-manifest 全树收录）；`job_store.py` 非 `__main__`（lib）；heartbeat_tick 步骤至 11（#618/#634 已合，866-b 登记条件具备） | 与 issue D5 CONFIRMED 一致；866-b 处置 |
| #866 评论 22 个零发现面清单 | **逐字复现成功**（22/22，按 issue 自身四发现面口径：SKILL/references/_INDEX.ext.yaml/scripts+hooks 代码消费，stem 匹配） | 清单本身无漂移；口径偏置见下"偏航" |

### 偏航（实现级适配，不影响规格核心；处置执行仍归 866-b）

1. **issue 字面 "登记 _INDEX.ext.yaml" 对 tools/ CLI 不可达**：`tools/_INDEX.ext.yaml`
   是 ext-scan.py 生成的 DESCRIBE-ONLY 目录（D2 设计明确 "OUTSIDE the internal
   tools/_INDEX.yaml execution registry"，且生成器对 internal registry 同名冲突
   fail）；tools/ 的机读登记面是 `tools/_INDEX.yaml`（hooks/worker_budget_gates.py:687
   `_load_tool_index_keywords` 生产消费 → 入册即产线可发现）。门的两面适配为
   **tools/_INDEX.yaml +（SKILL 教学段或 references 条目）**，WHAT/WHY 记录于此。
2. **deploy-manifest 已退化失去佐证力**：issue 称 "27 个候选 0 个出现在
   deploy-manifest.yaml（80 脚本运行时选集）"；实测 deploy-manifest.yaml 已 364
   src 条目，scripts/ 169/169、tools/**/*.py 39/39 **全树收录** → deploy 在场
   零判别力。产线语义档将其降为诊断面（同 release-manifest——发布字节 ≠ 接线，
   ghidra_job 恰是"在 release-manifest 上却未接线"的 D5 案例本体）。
3. **22 清单的口径偏置**：issue 四发现面不含 tools/_INDEX.yaml 与 agents/。按产线
   口径（hooks/skills/agents/devkit/CI/_INDEX.yaml 种子 + 消费闭包），tools 侧真实
   未接线 = **14**（22 中的 8 个——stack-strings/yara-scan/yara-gen/binary-sweep/
   baksmali_index/call-site-args/extract-syscalls/go-buildinfo-carve——已由
   _INDEX.yaml 注册 + agents 派单面接线，属"缺教学段"而非"未接线"）。**866-b 鉴定
   应以两张表为准**：产线未接线 14 + "在册但零教学面"清单（门基线承接）。

### 全仓实测数字（产线语义档首跑，as-of e958297）

- 主体：scripts/*.py **169** + tools/ `__main__` CLI **32** = **201**
- 产线未接线：**46（scripts 32 + tools 14），约 11,310 LOC**
- tools 侧 14：audit_legacy_proven / capture_golden / measure_blind_coverage /
  measure_cold_start / ghidra_diff / ghidra_job / run_ghidra_postscript / c_normalize /
  die_probe / disasm_dump / opaque_pred / overlay_scan / shellcode_scan /
  web_gitnexus_demo
- scripts 侧 32 含：lessons_telemetry、plan_stages、bench_* 7 件、optimizer_core/
  bandit、acceptance_check、local_gate、relib_audit 本身等（README "lib(2)/hooks/CI"
  多处引用声明经查已失效——error_response 实际零 importer、encoding_lint/relib_audit
  不在任何 workflow/hook）
- 口径声明：种子面命中或被产线已接线主体以 filename/import 消费即算接线；
  docstring 纯提及不算（除 filename 字符串字面量，保守接受此近似并在此声明）。

### 达标正负例（产线语义档判定）

- 负例（判"未接线"）：`tools/ghidra/ghidra_job.py` ✓；`tools/static/opaque_pred.py` ✓
  （另有 ghidra_diff / web_gitnexus_demo / lessons_telemetry 等）
- 正例（判"已接线"）：`tools/crypto/crypto-tool.py` ✓（skills/kunglao-agent/SKILL.md:199
  教学段 + hooks/worker_budget_gates 工具门消费 + _INDEX.yaml）；
  `tools/static/yara-scan.py` ✓（agents 派单面 + _INDEX.yaml）

### 变更前测试基线

`python -m pytest tests/test_relib_audit_817.py -q` → 9 passed（0.16s）。
