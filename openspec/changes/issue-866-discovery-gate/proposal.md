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
   references 条目），缺失即红；基线棘轮（`devkit/.discovery-gate-baseline.txt`，
   27 个存量 CLI 挂账）承接存量债务（866-b 清偿），新未登记 CLI → exit 1。CI
   release-check 步骤（1 3 4 8 9）与 scripts/local_gate.py 同步挂门。

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
- 产线未接线：**45（scripts 31 + tools 14），约 11.2k LOC**
- tools 侧 14：audit_legacy_proven / capture_golden / measure_blind_coverage /
  measure_cold_start / ghidra_diff / ghidra_job / run_ghidra_postscript / c_normalize /
  die_probe / disasm_dump / opaque_pred / overlay_scan / shellcode_scan /
  web_gitnexus_demo
- scripts 侧 31 含：lessons_telemetry、plan_stages、bench_* 7 件、optimizer_core/
  bandit、acceptance_check、local_gate 等（README "lib(2)/hooks/CI" 多处引用声明经查
  已失效——error_response 实际零 importer、encoding_lint 不在任何 workflow/hook；
  relib_audit 本身由本 PR 的 discovery_gate 引擎消费后转为接线——CI 门是真实产线消费者）
- 口径声明：种子面命中或被产线已接线主体以 filename/import 消费即算接线；
  docstring 纯提及不算（除 filename 字符串字面量，保守接受此近似并在此声明）；
  门的债务清单（.discovery-gate-baseline.txt）是记账不是消费，明确排除在所有
  face 语料外（自引用泄漏防护，见 relib_audit._PROD_BOOKKEEPING）。

### 达标正负例（产线语义档判定）

- 负例（判"未接线"）：`tools/ghidra/ghidra_job.py` ✓；`tools/static/opaque_pred.py` ✓
  （另有 ghidra_diff / web_gitnexus_demo / lessons_telemetry 等）
- 正例（判"已接线"）：`tools/crypto/crypto-tool.py` ✓（skills/kunglao-agent/SKILL.md:199
  教学段 + hooks/worker_budget_gates 工具门消费 + _INDEX.yaml）；
  `tools/static/yara-scan.py` ✓（agents 派单面 + _INDEX.yaml）

### 变更前测试基线

`python -m pytest tests/test_relib_audit_817.py -q` → 9 passed（0.16s）。

### 门两态演示（真仓，2026-09-02）

- 状态 A：`tools/static/zz_gate_demo.py`（带 `__main__`，零登记）→ `discovery_gate.py`
  exit 1，逐字点名该文件（"missing discovery face(s): registry+teaching"）；
- 状态 B：同帧补 `tools/_INDEX.yaml` 行 + SKILL 教学注释 → exit 0；
- 状态 C：还原全部三文件 → exit 0（工作树零残留，git 核对）。
- 同样的两态以夹具固定在 tests/test_discovery_gate_866a.py
  （test_red_green_two_state_demo）。
- 教训入代码：登记名必须与文件 stem 全字一致（schema kebab-case 约束下 underscore
  文件用 underscore 名；toolfirst 关键字派生同口径）。

### 实现期修正（TDD 过程发现，全部有测试钉住）

1. pathlib `glob("dir/**")` 只返回目录——devkit 等 face 语料曾静默为空；
   `_face_corpus` 遇目录即 rglob 递归收文件。
2. 债务清单自引用泄漏：基线文件列出未接线路径，若计入 face 语料会给它们全部"接线"；
   `_PROD_BOOKKEEPING` 将记账文件排除于所有语料（副产品：relib_audit 本身经
   discovery_gate 引擎消费转为真实接线，未接线 46→45）。
3. 闭包边不含裸 stem：scripts 模块 stem 可能与 hook 注册名字符串同类（reuse_gate
   案例），裸 stem 闭包会误接线（identity 类碰撞）。
4. 消费边/登记名匹配用全 token 边界（stem 'gen' 不得命中 'widget-gen'）。

## Recon（PR 866-b，2026-09-02）

### 基线事实（开工实测，worktree feat/866-b-inventory @ 8de80d1）

- 门基线 27 条（devkit/.discovery-gate-baseline.txt）：15 缺两面 + 10 缺教学 + 2 缺 registry。
- **命名口径偏置（866-a 教训的既有存量版）**：17 条"缺 registry"里有 13 条其实在
  tools/_INDEX.yaml 有登记——但登记名是 kebab（die-probe），门用文件 stem 全字匹配
  （die_probe），下划线不等于连字符，门看不见（_token_hit 把 -/_ 都算名字字符）。真未登记
  的只有 4 个：ghidra_diff / ghidra_job / run_ghidra_postscript / web_gitnexus_demo。
- relib 产线种子面含 tools/_INDEX.yaml 与 skills/**——登记动作本身会把条目翻转为
  "产线已接线"（定义使然：registry 即派发时候选面），866-a 已在测试注释里预告此翻转。

### 处置总表 A：tools 侧 27 条基线逐条（登记/退役二选一，退役=0）

**退役数量：0。** 逐条证据（测试文件 + 近 30 天触碰 + issue 背书 + 功能唯一性）无一满足
"过时"退役标准；issue 点名的"过时→退役"桶实测为空。全部走登记。

| # | 文件（stem） | 判定 | 证据 | 执行面 |
|---|---|---|---|---|
| 1 | audit_legacy_proven | 登记 | tests/test_audit_legacy_proven.py；PROVEN 审计唯一 CLI（BLIND+溯源双维） | _INDEX.yaml audit-legacy-proven 条目加 CLI 字面量 + toolshelf 教学行 |
| 2 | capture_golden | 登记 | golden 重放活流（tests/test_suite_health.py F-01..F-16 逐字节重放）；其 CASES 消费 content_hash/reconcile_intents | 同上（capture-golden） |
| 3 | measure_blind_coverage | 登记 | BLIND 覆盖率唯一度量 | 同上（measure-blind-coverage） |
| 4 | measure_cold_start | 登记 | 冷启动 token 基线唯一度量 | 同上（measure-cold-start） |
| 5 | sanitize | 登记 | tests/test_sanitize.py + #339 契约测试 GOLDEN_INVOCATIONS 钉死 python tools/auxiliary/sanitize.py --in | 同上（sanitize-text） |
| 6 | ghidra_diff | 登记（新正式条目） | tests/test_bindiff.py；#308 二进制 diff 唯一实现 | **_INDEX.yaml 新条目 ghidra_diff**（provider: ghidra，新 capability ghidra:diff 入 _CAPABILITY_TAGS）+ _index-ghidra.md 契约条目（6 段）+ toolshelf 教学行 |
| 7 | ghidra_job | 登记 | tests/test_ghidra_async.py；异步 job 协议唯一实现（价值路由由 #881 排序接管，教学段只写调用场景） | ghidra-recon 条目加执行面字面量 + **SKILL.md 教学段**（dispatch contract 区）+ toolshelf 教学行 |
| 8 | run_ghidra_postscript | 登记 | 5 个 postscript 工具的统一执行器（_index-ghidra.md 全部 usage 块引用） | 同 7（同一条目字面量覆盖） |
| 9 | job_store | lib 处置（866-a 判定沿用） | 无 __main__，非门主体；ghidra_job/ghidra_diff 共享的 dir-backed job lib | 教学：SKILL.md 教学段 + toolshelf 行均按 lib 记名 |
| 10 | GhidraBindiff.java | lib/postscript 处置 | Java 非 CLI，非门主体；ghidra_diff 的执行体 | ghidra_diff 契约条目 + toolshelf 行记名 |
| 11 | web_gitnexus_demo | 登记 | tests/test_gitnexus_web_751.py 以 DEMO_SCRIPT 钉死该路径并跑 --selfcheck；#751 语义层回归主体 | gitnexus-query 条目加 demo 字面量 + toolshelf 教学行 |
| 12 | build_evidence_index | 登记 | tests/test_evidence_index.py；P2 溯源门的供给侧（evidence/_index.json 唯一建造器） | _INDEX.yaml build-evidence-index 条目加 CLI 字面量 + toolshelf 教学行 |
| 13-27 | apk_mem_gate / baksmali_index / binary-sweep / call-site-args / extract-syscalls / go-buildinfo-carve / stack-strings / yara-gen / yara-scan / c_normalize / die_probe / disasm_dump / disasm_constant_check / opaque_pred / overlay_scan / pe_analyze / shellcode_scan | 登记 | 各有专测（test_apk_mem_gate / test_baksmali_index / test_static_tools_1b/1c / test_yara_tools / test_c_normalize / test_disasm_constant_check / test_opaque_pred 等）；#278/#284/#306/#313/#670/#692 系已合并交付物；opaque_pred/c_normalize/stack-strings 为 issue 点名 RE 刚需 | 13 条 kebab 条目在**自身条目 input 契约内加精确脚本路径字面量**（_INDEX.yaml:317 apk_mem_gate 先例）；教学面统一落 toolshelf 文档 |

**为什么是"条目内字面量"而不是改名 kebab→stem**：改名会同时撞三面机械契约——
_LEGACY_UNANNOTATED 冻结白名单（#729 Rule A：只许移除不许新增，改名后的无注解条目
= 非法新增）、#339 契约测试按 YAML name 反查 H3 标题、toolfirst 关键字派生面。
条目内字面量是同一文件里的既有登记形（jadx 条目内的 tools/static/apk_mem_gate.py，:317），
零 schema 冲突，门的 stem 全字匹配照常命中。866-a 的"登记名=stem"教训适用于**新建条目**
（ghidra_diff 即 stem 全字），不追溯既有 kebab 条目。

### 处置总表 B：scripts 侧 29 个（退役=0；ledger 落 scripts/README.md）

- 逐条鉴定表 + 绑定标注已作为常设段写入 scripts/README.md 的
  "## #866 unwired-live disposition ledger (PR 866-b, 2026-09-02)"（29 行，含绑定 issue、
  已合状态、处置、后续消费面）。要点：
  - **绑定已合 change（13）**：bench_* 7 件（#823 B1-B7 MERGED）、infeasible_proposal
    （#815）、plan_stages（#822）、optimizer_core/bandit（#833）、tuition_refit（#823-P4）、
    emit_gate（#880）——全部标注 MERGED + 各自消费面。
  - **活体工具/门（13）**：search_gate / reuse_gate / complete_teardown（用户痛点驱动）、
    strategy_metrics（#529）、acceptance_check（#6/#689）、run_test_matrix（v0.1.3 验收）、
    report_consistency_check（#57）、fixture_excerpt_lint（#58）、chunker/env_file（#309）、
    kunglao_export（#540）、local_gate（866-a 已接 Gate 9 的本地门入口）、encoding_lint
    （#811）、error_response（#448 机械层）。
  - **SUSPECT（2，非 DEAD）**：answer_key_lint / intake_one——docstring 绑定的
    COLLECTION_PROTOCOL.md **全仓不存在**（find+grep 双查为零），零测试零消费方，功能与
    已合的 bench_answer_key.validate_key（#823）重叠。不退役的理由：answer-key 产物仍可能
    被手动 lint，删除不可逆且收益趋零；已标"后续治理卡 + owner 裁决后退役候选"。
  - **闭包翻转 2**：content_hash / reconcile_intents 经已登记的 capture_golden 的 golden
    用例（F-13/F-15）获得 lib_closure，移出未接线集合（31 到 29 的原因）。

### Ghidra 四件套四发现面证据（抽查命令）

- registry：grep -n "ghidra_diff\|run_ghidra_postscript\|ghidra_job" tools/_INDEX.yaml
  到 ghidra-recon 条目（executor+async 字面量）+ ghidra_diff 独立条目；
  python tools/validate_index.py 到 38 tools ok。
- 教学：grep -rln "ghidra_diff" skills/ references/ 到 skills/kunglao-agent/SKILL.md、
  references/re-library/kunglao-toolshelf.md；tools/_index-ghidra.md 新增
  ghidra_diff 契约条目（#339 测试 88 passed）。
- recall：references/_INDEX.md re-library 表 + _index-tools.md 各有一行（stem 全列在
  Purpose 列）；python scripts/re_pin_references.py 到 78 pins current。
- 门：python devkit/discovery_gate.py，exit 0。

### 棘轮与两态

- devkit/.discovery-gate-baseline.txt：27 键清偿为 **0 键**（保留空账本文件，门对缺失
  文件 fail-closed）。--print-baseline 现输出为空；未登记假 CLI 仍会红（866-a 夹具
  test_red_green_two_state_demo 继续钉两态）。

### 实现级偏离（WHAT/WHY）

1. 教学面落点：references/re-library/kunglao-toolshelf.md（新文件）承担 27 条的教学行，
   SKILL.md 只加 ghidra 异步派发一段——27 条全塞 SKILL.md 会膨胀 orchestrator 常载上下文；
   门 face B 认 skills/** 或 references/** 任一（either-or 是 866-a 门的设计）。
2. relib 钉翻转：test_real_repo_ghidra_job_is_unwired / _opaque_pred_is_unwired 按
   866-a 预留注释翻转为 registered_wired；unwired_total >= 40 改为 unwired_tools == 0 且
   unwired_total >= 25（下界而非精确值，沿用 CI runner 瞬态脚本噪声教训）。
3. scripts 侧未接线计数 31 到 29（capture_golden 闭包翻转 2 个），README 双口径 as-of
   数字同步刷新（45 到 29，reproduce 命令不变）。

### 变更前测试基线

python -m pytest tests/test_index_docs_contract.py tests/test_validate_index.py -q 在
改动前后各跑一次均绿；全量基线含 7 个已知 Windows 环境性失败（见交付说明）。
