# #863 治理机械化 — enforcement-by-mechanism（剩余 Families）

Package 2（纯兼容删除九项 + lint_facts 仲裁裁决）已先行交付（PR #875）。
本 change 覆盖 Package 1 剩余 Family（按 issue 表）：

- Family A: tools/ UTF-8 stdout guard（35×4 副本）→ `tools/_lib/stdio.py::ensure_utf8_stdout`
  单体 + 全 CLI 委托；扩展覆盖 stdout+stderr 双流（吸收 3 个双流变体）。
  执法测试 test_utf8_stdout_convention.py 改写为 delegation 断言（#863 机制化语义）。
- Family B: spec_from_file_location loader 前导 ×21 → loader util + delegation
- Family C: _resolve_ws ×8（4 形状）→ manifest-aware 单一源（同源闭合 #865 主体）
- Family D: toolchain which 循环 + docker probe → `_which_items()` helper

规则：永不删除有测试守卫的行为——抽共享实现、执法测试改写为 delegation 断言。

## Recon（863-b，2026-09-02 实测）

### 锚点表（计划/issue 锚点 vs 实测）

| issue 表述 | 实测 | 结论 |
|---|---|---|
| `spec_from_file_location` 前导 21 份（5 份 byte-identical） | 非测试代码 **22 个调用点 / 21 个文件**（recall_inject ×2 若按文件计 1 份即 issue 的 21） | 数目吻合（口径差 = recall_inject 双调用点），按全量 22 点处理 |
| 5 份 byte-identical | `scripts/backtrack_gate.py:47-55`（内联）、`event_taxonomy.py:69-78`、`kunglao_status.py:47-56`、`reconcile_workers.py:19-28`、`external_kicker.py:168-177`——9 行执行语句逐字节相同（同载 `hooks/lib_kunglao.py` 为 `lib_kunglao_hooks`） | 确认 |
| 执法测试 `test_worker_liveness_protocol.py:444` | 实为 `test_two_layers_share_one_protocol_source`（445-448 行）内的 textual 断言 `assert _PROTOCOL_NAME in cc` + 189-203 行 `WIRING` 字典（textual marker） | 漂移按符号定位；改为 delegation marker |
| tasks.md "20 份前导" | 22 调用点 / 21 文件（含 `_path_hygiene.load_hooks_lib` 自身转委托） | 以实测为准 |

### 形状分类（22 点）

- **A 型（get-or-create + sys.modules 注册，可精确等价）**：scripts 侧 9 份 lib_kunglao_hooks 装载器（其中
  convergence_check/progress_report/scripts/lib_kunglao 3 份带 exists-check RuntimeError）+
  `hooks/_path_hygiene.load_hooks_lib` + `completion_gate._load_judge` + `state_anchor._load_drift_lib`
  （FAIL_OPEN 包裹）+ `worker_budget` 模块级 setdefault 绑定。
- **B 型（fresh-load 不注册）**：heartbeat `_cg_heartbeat`、kunglao.py `cmd_upgrade`、kunglao_upgrade
  `_init_mod`（global 缓存）、release_check_selfcheck `"qg"`、recall_inject ×2（fail-open）、
  `devkit/governance_binding._load_module`、`devkit/doc_sync._load_ext_scan`（自有 dict 缓存，含 None 缓存语义，保留包装）。
  统一为 util 的 get-or-create 语义：被载文件全部为纯定义/常量模块（import 时无 I/O 副作用，已逐一抽查），
  缓存化不改变可观测输出。
- **漂移形状**：`references_recall.py:374-390` 以异名 `kunglao_hooks_lib` 载入 + `sys.path.insert(0, hooks)`
  （#671 重排序隐患，insert 为死重——hooks/lib_kunglao 自举 _path_hygiene 不依赖 sys.path）。保留异名
  （精确等价），删 insert。
- **自举例外（不在 issue 21 份内，物理不可委托）**：`hooks/dispatch_gate.py:76` + `hooks/lib_kunglao.py:34`
  的 #671 fallback——它们装载的正是 `_path_hygiene`（即 util 本体）本身；"装载 util 的代码不可能调用 util"，
  属 bootstrap 不可约点。保留原样，在 confinement 测试中以 named-allowlist + 理由记录（镜像本测试文件
  ALLOWLIST 惯例）。

### 方案（镜像 Family A #877 形状）

- util 落点：`hooks/_path_hygiene.py::load_module_by_path(name, path)`——#671 by-path 权威即
  path-装载权威（主题同源）；`load_hooks_lib` 改为对 util 的委托（9 行语义与 util 逐行等价）。
  scripts/ 为多数派（18/22 调用点）但 hooks 侧不可反向依赖 scripts（recall_inject 明文"no scripts/
  sys.path injection of its own"），故 util 归 hooks、plumbing 归 scripts。
- scripts 侧桥：新增 `scripts/_hooks_path.py`（guarded `sys.path.append`——永不前插，规避 #671
  collision-order；re-export `load_hooks_lib`/`load_module_by_path`），13 个 scripts 文件 1 行导入。
- devkit 侧（2 文件，stdlib-only 惯例）：3 行内联 append + 导入。
- 执法测试：新增 `tests/test_loader_delegation_863b.py`（confinement + WIRING delegation 断言 +
  util 契约测试）；`test_worker_liveness_protocol.py` 的 WIRING/两断言改 delegation marker。

### 行为等价账本（同输入同输出）

1. A 型 9+4 点：逐行等价（get-first 语义保留；测试预载 `sys.modules["completion_gate_scripts"]` 的
   既有 pin 不受影响）。3 份 exists-check 的 RuntimeError 保留在调用点（错误消息不变）。
2. B 型 8 点：fresh-load → 注册+复用。可观测输出不变（被载模块纯定义；exec 仍每进程恰一次）。
3. worker_budget：setdefault+无条件 exec → get-or-create（首导入路径完全一致）。
4. references_recall：删 `sys.path.insert(0, hooks)`（死重 + #671 隐患）；spec-None 守卫删（对真实
   .py 文件不可达）；模块名保留 `kunglao_hooks_lib`。
5. 基线：test_worker_liveness_protocol + test_syspath_hygiene_671 + 10 个受影响测试文件
   **295 passed**（提取前）。

### 偏航记录

- 数目口径：issue 21 / tasks 20 / 实测 22 调用点（21 文件）——按全量处理，非削减。
- grep 验收口径：`git grep spec_from_file_location`（非测试）预期 = util 定义 1 + #671 自举 2
  （物理不可约，见上）+ 2 处文档性注释提及；Family B 目标复制（22 前导）清零由 confinement 测试
  机械断言。

## Recon（863-c，2026-09-02 实测）

### 锚点表（计划/issue 锚点 vs 实测）

| issue/计划表述 | 实测 | 结论 |
|---|---|---|
| `_resolve_ws` 8 份、4 形状 | **9 份定义**（grep `def _resolve_ws`）：`convergence_check.py:79`、`convergence_health.py:63`、`heartbeat_tick.py:85`、`failure_analysis_gate.py:183`、`hooks_selfcheck.py:82`、`heartbeat_touch.py:30`、`priority.py:83`、`route_capability.py:674`、`statusline_snapshot.py:600` | 第 9 份 statusline_snapshot 为 #883（7b76e49）审计后新增、形状与 strict 族 byte-equivalent。同属 Family C 符号族、纳入收敛——否则 grep 验收无法清零。计数非削减方向（多收 1 份），按全量处理 |
| 4 形状 | A manifest-aware quiet（仅 convergence_check，读 `env_manifest.layout_conventions`，arg→`Path(arg)` 不 resolve）；B hardcoded quiet claim-register（failure_analysis_gate/priority/route_capability，route 用 `Path.cwd()` 与 `os.getcwd()` 等价）；C quiet ledger 哨兵（convergence_health，探 `LEDGER_NAME`=`.convergence_ledger.jsonl` 而非 claim-register）；D #228 hard-error strict（heartbeat_tick/hooks_selfcheck/heartbeat_touch/statusline_snapshot，cwd-first 探 claim-register OR analysis_state.txt，全 resolve，缺省 exit 2 stderr 指引 byte-identical ×4） | 确认 4 形状（B/C 按哨兵分型） |
| 7/8 忽略 workspace_dir（B2） | 除 convergence_check 外**全部 8 份**硬编码 sibling 名 `malware-analysis-workspace` + `claim-register.yaml`，manifest `layout.workspace_dir/claim_register` override 一律失明 | 确认（修复后实数 8/9 忽略 → 0/9） |
| 守护测试 `test_env_manifest.py:517-531` | 实测 `test_convergence_resolve_ws_default_layout`:502-514 + `test_convergence_resolve_ws_custom_layout`:517-527——仅 convergence_check 一个形状、`from convergence_check import _resolve_ws` 符号导入 | 行号漂移按符号定位；扩到 4 形状全覆盖 + B2 两态钉 |
| 其余 9 份无守护 | grep 全 tests/：无任何测试引用其余 8 个模块的 `_resolve_ws`（dispatch_gate._resolve_workspace 是另一函数，#450 已 manifest-aware） | 确认（本卡新增覆盖） |

### B2 行为修复影响面分析（fix-first 裁决执行）

- **显式传 workspace 参数的调用面（9/9）**：arg-wins 语义不动（quiet arg→`Path(arg)` 不 resolve；
  strict arg→`Path(arg).resolve()`），零影响。调用点：convergence_check:1438、convergence_health:292、
  heartbeat_tick:225、failure_analysis_gate:1037（parser :1008 nargs="?"）、hooks_selfcheck:164、
  heartbeat_touch:45、priority:290、route_capability:685+772、statusline_snapshot:618。
- **缺省路径、无 manifest**：`layout_conventions` → DEFAULT_LAYOUT，`workspace_dir` = 原硬编码字面量
  → **byte-identical**（#450 向后兼容锚点，env_manifest.py:131-134 自证）。
- **缺省路径、有 manifest override**：修复前 8 份找不到 override 后的 workspace——quiet 形状静默回退
  cwd（priority 静默空读注册表、convergence_health 静默回退 cwd 读不到 ledger）、strict 形状
  exit 2（heartbeat_tick 自检误报"no workspace found"）。修复后与 dispatch_gate._resolve_workspace
  （hooks/dispatch_gate.py:111-134，#450 契约面）语义一致。
- **依赖旧行为的调用方排查**：`workspace_dir` 全库 grep——仅 env_manifest（定义）+
  convergence_check/_resolve_workspace（消费）+ 其守护测试引用。**无任何调用方/测试依赖
  "override 不生效"旧行为 → 无 RECON-DEVIATION，放行**。
- **自相矛盾边角（记录，不阻断）**：manifest 声明 override 但 workspace 物理仍在默认名 → 修复前
  B/C 形状能找到、修复后按 manifest 探测不到（与 dispatch_gate 同帧一致化——#450 既定语义
  "override 改变探测位置"）；属配置自相矛盾场景，非回归。

### 方案（落点 + delegation assert）

- **util 落点：`scripts/ws_layout.py`（新）**。WHY 不入 env_manifest.py：env_manifest 是严格
  facts 载体（753 行近 800 上限；fail-closed 面），sys.exit(2) 的 CLI 解析行为与其契约异质；
  9/9 消费方全在 scripts/（无跨树），裸导入即可——**无需 Family B 式 _hooks_path 桥**。
  单用途小模块惯例同型：utf8_boot / liveness_policy / status_defs / retract_claim。
- API：`resolve_quiet(arg, *, sentinel=None)`（A+B+C 形状；sentinel=None→layout.claim_register，
  convergence_health 传 LEDGER_NAME）+ `resolve_strict(arg)`（D 形状，cwd-first + analysis_state.txt
  哨兵 + exit 2 消息 byte-identical，仍用调用时 `sys.argv[0]`）。布局名全部来自
  `env_manifest.layout_conventions`。
- **delegation 形态**：7 点纯别名 `from ws_layout import resolve_quiet/resolve_strict as _resolve_ws`
  （最强委托形态）；convergence_health 2 行 def（哨兵变体）。priority.py 虽 #499 deprecated，
  其 `_resolve_ws` 仍在本符号族（retirement 前必须继续工作）。
- **执法测试**（镜像 tests/test_loader_delegation_863b.py 三段式）：新增
  `tests/test_ws_layout_delegation_863c.py`——(1) confinement：全库扫描 `def _resolve_ws` 函数体，
  禁含 `malware-analysis-workspace` 字面量与自行 `layout_conventions` 调用（探测逻辑禁再现于消费方）；
  (2) wiring：9 文件均引用 ws_layout + 7 别名点做**身份级**断言 `mod._resolve_ws is ws_layout.<fn>`；
  (3) util 契约钉。`tests/test_env_manifest.py` 扩 4 形状行为全覆盖（B2 两态：override 传入→生效；
  缺省→原默认）。README 行（test_declaration_scan 门）+ deploy-manifest --write（FULL MIRROR
  自动收编，test_deploy_closure_810 门）。

### 基线

- 受影响 14 测试文件（env_manifest/heartbeat_tick/heartbeat_off/route_capability/
  selfcheck_stamps_536/statusline_health_883/failure_analysis_transducer/failure_lessons/
  rank_claims/decision_teeth/orchestration_priority_cost/convergence_completeness/
  worker_liveness_protocol/mission_stall_634）：**222 passed**（提取前，Windows 本地）。
- `release_receipt.py --check` RC=0。

### 界外观察（不顺手做，留给后续卡/讨论）

hooks/ 侧**非 `_resolve_ws` 命名**的同类硬编码 sibling probe：`hooks/completion_gate.py:141`、
`hooks/bash_fact_guard.py:40`、`hooks/cost_input_capture.py:32`；scripts/ 侧
`reconcile_workers.py:40`、`search_gate.py:49`。不属 Family C 符号族（issue 表按 `_resolve_ws`
符号定界），不受本卡 grep 验收约束；其中 hooks 侧三者是否应入 #450 layout-consumer 名录
（现名录仅 dispatch_gate/convergence_check/lib_kunglao）值得单独一卡。

### 偏航记录（实现级，非 RECON-DEVIATION）

- 计数 8→9（#883 新增份纳入，见锚点表首行）——家族同一性由符号 grep 定义，方案与验收不变。
- util 落点 scripts/ws_layout.py（WHY 见方案节）；convergence_check 的函数级 `import env_manifest`
  热路径注释随探测逻辑一并移入 util（import 图不变：消费方 → ws_layout → env_manifest）。

## Recon（863-e，2026-09-02 实测）

范围：Package 2 批 2 四项（no-backward-compat 删除/收敛）+ 附加三项（promote_lesson /
grace 旗标 / lint_facts-migrate_facts 裁决落地）。审计报告 /tmp/kunglao-audit 已清失，
issue 表格为权威 fallback；全部锚点按符号 grep 重定位。**无 RECON-DEVIATION，七项全放行。**

另勘误：proposal.md 头部"Package 2 已先行交付（PR #875）"不实——#875 实为
862-budget-channel；本卡四项在 dev 4caeb44 上全部仍活体存在（下表实测），按本卡执行。

### 锚点表（issue 锚点 vs 实测）+ 七项四件套

| # | 项 | issue 锚点 | 实测定义 | 活体引用 | 测试钉 | 清理面 |
|---|---|---|---|---|---|---|
| 1 | wire_up_settings deprecated alias | wire_up_settings.py:158-180 | :189-209（`def wire_up_settings`，DeprecationWarning→register_hooks 委托）；模块 docstring :2-15、`import warnings`:45 仅其使用 | hook_activation.py:484-487 `DEPRECATED_ALIASES` 声明（:49/:61/:64 为历史 prose）；无生产调用方 | test_hook_registration_entry.py:98-105（声明钉）、:108-125（委托钉，删）；test_completion_gate.py:493-516、test_wire_up_settings.py ×9、test_state_anchor.py:313-338（行为钉，改调 register_hooks） | 删 alias+warnings import+docstring 条目 2；`DEPRECATED_ALIASES = ()`；注册表本体（WIRE_UP_HOOK_FILES/HOOK_EVENTS/hook_deployment_targets/derive_hook_subset）全保——env_check/state_anchor/external_kicker/hook_activation 活体消费 |
| 2 | worker_budget._ShimModule | worker_budget.py:44-64 | :54-61（类+`__class__` 赋值）+ 供数表 `_PROPAGATE_TO`:46-51（仅 shim 消费） | 模块外零引用（grep 全库） | test_stuck_gate.py:35-69（×5 `wb._run_py`）、test_heartbeat_bootstrap.py:200（`wb._run_py`）、test_failopen_emit.py:122（`wb.check_priority`）依赖转发；test_worker_budget.py:818-826 已直 patch 源模块（镜像样例） | 删 :40-61；三测试文件 patch 目标改源模块（worker_budget_sinks._run_py / worker_budget_core.check_priority），镜像 test_worker_budget.py 形状。issue 称"+2 测试文件"，实测 3 个依赖转发的文件（非削减，全改） |
| 3 | validate_index._LEGACY_UNANNOTATED | validate_index.py:58-70,146,296-307 | 白名单 :59-74（29 名 frozen）、检查点 :297-307、:147-149 docstring "legacy untouched" | 非测试零引用 | test_validate_index.py:268-308（TestRuleA：legacy WARN 钉 :286-293 翻转）、test_index_capability_annotations.py:144-150（翻转）、:164-168（shipped index 绿——回填后仍须绿，保留） | 删白名单→所有无 provider 条目硬错；tools/_INDEX.yaml 29 条目机械回填（provider=自名、produces=[capability]、requires=[]、cost_hint={mem_gb: probe 0.1/cheap 0.5/deep 4.0, time=cost_tier}、quality={capability: high}——单能力 provider 先例 jadx/wakaru/jsvmp-triage）；`_CAPABILITY_TAGS` 扩 27 个 legacy capability 标签（29 中 2 个已在集）；测试翻转 2 处 |
| 4 | digest_build pre-contract fallback | digest_build.py:81-84 | :78-80（`facts/_INDEX.md` 不存在→`<ws>/_INDEX.md`）+ docstring :77 | 消费方（kunglao_resume/kunglao-digest/acceptance_check）全部面向规范工作区 | 零测试钉 fallback（test_digest.py 等全部写 facts/_INDEX.md 规范位） | 删回退 2 行 + docstring 句 |
| 5 | promote_lesson 双定义 | failure_analysis_gate.py:643/938 | 死定义 :654-702（49 LOC，被 :949 遮蔽）+ 私有 helper `_read_lesson_frontmatter`:639-651（仅死定义使用）；活定义 :949-1014 | 测试全走活定义（Python 后 def 胜） | test_lessons_nursery.py:168-251、test_lessons_trigger_precision.py:142-156 钉活定义行为（保留） | 删死定义 + helper；补活定义 soft-fail 行为钉（缺失文件/无 frontmatter/YAML 错 reason 返回） |
| 6 | kunglao_verify --grace/--grace-scan | （~45 LOC） | kunglao_verify.py:201,206-207,217-218（grace 形参）、:830,836,850,857（verify grace）、:969-985（_grace_scan）、:989-1007（CLI）；kunglao.py:90-93,370-373（dispatcher 镜像）；references/schema.md:123-126（migration 段） | 无其他代码调用方传 grace=True | test_fact_expected_binding.py:104-107（grace warn，删）、:217-254（grace-scan ×2，删） | 全删（含 kunglao.py 双镜像 + schema.md 段）；ghidra 的 `--grace`（job 崩溃宽限）是另一旗标，不碰 |
| 7 | lint_facts/migrate_facts 裁决 | migrate_facts.py:52 | lint_facts.py:160-185（parse_frontmatter）、:188-357（kv 家族）、:414-431（`_index_status_values` +PARTIALLY-VERIFIED）、:727-729（UNPARSEABLE 门）；migrate_facts.py:52-56 导入 + 3 调用点 :360,479,485 | bash_fact_guard.py:78（parse_frontmatter+lint_fact 运行时门）、write_guard.py（仅 lint_index/lint_workspace） | test_lint_facts_532.py:144（PARTIALLY-VERIFIED 行 True→翻 False）、:176-186（同翻转）；test_icd203_alignment.py:199（UNPARSEABLE-or-NO_FRONTMATTER，兼容）；test_icd203:293-300（migrate 输出保 PARTIALLY-VERIFIED——不动） | 裁决落地：(a) lint_workspace 对 `yaml-unparseable` 一律硬错（kv 回退结果不再静默过检）；(b) `_index_status_values` 双分支删 PARTIALLY-VERIFIED；(c) `_parse_kv_block` 家族原地保留、parse_frontmatter 容忍语义不变（bash_fact_guard 运行时容忍读零行为变化）；(d) migrate_facts 内联自有 `_parse_frontmatter`（fence+yaml-first+marker 包装 + `_coerce_yaml_scalars` 副本，kv 回退引 lint_facts._parse_kv_block——裁决钉留处），弃 parse_frontmatter 导入 |

### promote_lesson 行为差异结论（合并前 review，幸存语义 = :949 活定义）

死定义（:654）与活定义（:949）差异八处：① 签名默认值（死有 workspace=None/promoted_by/
evidence 默认，活全必填）；② 缺文件：死 raise FileNotFoundError，活返回
`{"promoted": False, "reason": "lesson not found: ..."}`；③ 无 frontmatter/非映射/YAML 错：
死容忍改写（防御性 fallback 重排），活一律 soft-fail 带 reason；④ already_active 返回形状
（死带 `lesson` 键，活带 `promoted_at`）；⑤ promoted_evidence：死条件写入，活恒写入；⑥
审计行：活多 `tool=`/`artifact=` 且 detail 恒带 evidence=；⑦ claim 空：死 ""，活 None；⑧
成功返回形状（死 lesson/promoted_by，活 from_stage/to_stage）。**幸存 = 活定义**：运行时
从来只有 :949 生效，测试钉的全是它；死定义的默认值签名在运行时不可达（若有人按死签名
调用，:949 的必填形参当场 TypeError）——删除即零行为变化（by construction）。补钉项：
soft-fail reason 三态（not found / lacks frontmatter / parse error）若无既有覆盖则新增。

### 基线

- 受影响 20 测试文件：**379 passed, 1 error**（error = test_icd203_alignment teardown 的
  #770 双生模块守卫——该测试显式插入 malware-veri-notes 外部 skill scripts 进 sys.path，
  环境性、teardown-only、先于本卡存在；测试本体 passed）。
- `python scripts/kunglao-verify.py --help` 现含 `--grace/--grace-scan`（退役后 grep 为空）。

### 界外观察（不顺手做）

- 主仓 `D:/codebase/kunglao-agent` 工作区有未提交的 `M scripts/migrate_facts.py`（用户
  WIP/并行卡落点）；本卡只动 worktree `D:/codebase/kunglao-wt-863e`，合流时按 dev 侧+再生解。
- tools/_INDEX.yaml 与在跑 866-b 卡的合流冲突预案：合并 origin/dev 冲突时取 dev 侧 +
  机械回填再生（不手拼）。
- `tests/test_icd203_alignment.py` 的 #770 teardown 守卫噪声（外部 skill sys.path 污染）
  值得单独一卡。

## Recon（863-f，2026-09-02 实测）

### Family D 核验（orchestrator 初证 → 本卡复核 CONFIRMED，无需重做）

- `git grep _which_items`：仅 `scripts/toolchain.py` 5 处（def :512-538 + 调用 :1521/:1538/:1551/:1655），
  带 `#863 Family D` docstring——由 #877（commit e3d640c）交付。
- 覆盖形态核对：2 个 hard-loop（windows/linux 的 file/readelf/objdump，:1521/:1551）+ 2 个 docker-block
  （windows/linux，:1538/:1655）+ jadx/apktool（Android）全部经 `_which_items`；issue 计数口径
  "intra ~90" = toolchain.py 文件内复制，与现状吻合。
- 残留扫描：`shutil.which` 在 scripts/hooks/tools 的其余命中（apkid_scanner:44、deploy_shim:154、
  env_check:400-404、env_manifest:553、env_repair_l1、env_state_probe、intake_promise:194、
  kunglao_upgrade:1060、pkg_detect、toolchain_install:453/458、tools/static 若干）全部是**单命令
  专用探针**（各自二进制、各自用途），非 which→CheckResult 列表循环族；Family D 符号族清零成立。
- 守护：无 `_which_items` 符号级测试（与 issue 表"behavior tests only"执法口径一致）——行为由
  test_probe_tiers_474 / toolchain 面测试钉住。结论：**D 已完成，本卡零代码改动，仅记录**。

### 锚点表（计划/issue 锚点 vs 实测）

| issue/计划表述 | 实测 | 结论 |
|---|---|---|
| Family E "WARN-triple 11 exact +4"（`warn()` ~50 LOC） | `kunglao_upgrade.py` 内 WARN print 共 **16 处**（grep `WARN.*file=sys.stderr` 族）：**8 处全 triple**（print + `_emit_event(..., "warn", why)` + `_emit(ws, ev, f"warn:{why}")`）：agents_refresh :268-272、uv_sync ×4 :1062-1093、staleness ×3 :1133-1165；**2 处 near-triple**（第三信号 detail 非默认）：claudemd `skipped:` 前缀 :422-427、toolchain_manifest 明文 detail :1008-1012；**1 处双信号**（print+event 无 ledger）：backfill channel :981-986；**2 处双信号**（print+ledger 无 event）：mcp :900-904、env_ledger unparseable :943-947；**3 处 print-only**：frame-stale :144-146、`_warn_git_skip` :699-700（已是具名单源，7 调用点）、sweep :1381-1383（注意该处连字符 `-` 非 em-dash，字节保真保留） | 行号/计数全漂移（issue 基于旧版；#739/#752/#753/#755/#758 增量）；按 16 处全量处理，triple 形状确认 |
| Family E 守护测试 `test_deploy_surface_755.py:349-361` | `test_failure_is_warn_not_fatal` :348-359（行为断言：warn label + stderr 含 WARN+uv_sync）+ `test_timeout_is_warn` :361-372 等——**行为测试，非 textual**；按 863-b 先例：行为测试保留 + 新增 delegation/confinement 执法测试 | 行号漂移按符号定位 |
| Family H `_ensure_utf8_stderr` 3×9 | 3 份函数体逐字节等价（9 行）：`toolchain.py:49-63`（调用 :66 module-level）、`toolchain_install.py:56-70`（调用 :73 module-level）、`kunglao-init.py:566-580`（调用 :2654 main() 首语句）；docstring 微漂移（toolchain_install 缺 `REFUSE —` 例） | 确认 3×9 |
| Family H 守护测试 `test_toolchain_stdio.py:160-163` | `test_utf8_stderr_call_sites_pinned_in_source` :150-164（`source.count("_ensure_utf8_stderr(sys.stderr)")==1` textual tripwire，fault-inject M8 语义）+ 3 个行为测试 :109-137（recorder 断言 encoding=utf-8/errors=replace/fail-open False） | 行号漂移；textual 改 delegation，行为测试保留 |

### 方案（落点 + delegation 形态）

- **Family E 落点：`kunglao_upgrade.py` 模块内 `_warn()` / `_warn_line()`**（issue 明示"one warn()
  helper ~50 LOC"；16 处副本全部在同一文件内，无跨文件消费方 → 模块内单源即清零，无需新 util 模块）。
  形态：`_warn(msg, why, event, ws=None, *, ledger_detail=None)` = stderr 行 + `[event]` 轨 + ledger
  三信号（`ws=None` 保持 ledger 面静默；`ledger_detail` 覆盖默认 `warn:{why}`——claudemd 的
  `skipped:` 前缀与 toolchain_manifest 的明文 detail 由此保真）；`_warn_line(msg)` = 纯 stderr 面
  （print-only 三处 + 双信号两处的 print 腿），`_warn` 组合 `_warn_line`。
  **双信号两处（mcp/env-unparseable）不升格为 triple**——加 `[event]` 行即输出变化，违反行为等价。
- **Family H 落点：`scripts/utf8_boot.py::ensure_utf8_stderr(stream=None) -> bool`**。WHY：#811
  stdio 保险层模块，docstring 自declares"本模块管 stdio 与子进程树"——主题同源；3/3 消费方全在
  scripts/（裸导入，无 Family B 式桥）。delegation 形态 = **纯别名**（863-c 最强委托形态）：
  三处 `def` 原位替换为 `from utf8_boot import ensure_utf8_stderr as _ensure_utf8_stderr`（原位 =
  module-level 调用时序不变，toolchain.py stdout 先于 stderr reconfigure 的既有顺序保持）；
  `_ensure_utf8_stderr(sys.stderr)` 调用点一律不动（M8 tripwire 的钉就是调用本身）。
- **执法测试**：Family H——`test_toolchain_stdio.py` 的 textual tripwire 改写为**身份级 delegation
  断言**（`mod._ensure_utf8_stderr is utf8_boot.ensure_utf8_stderr` ×3）+ 保留调用点 count==1 pin
  （M8 语义：乱码 fix 是 CALL 不是 helper）；3 个行为测试保留（经别名仍绿）。Family E——新增
  `tests/test_warn_delegation_863f.py`：(1) confinement：`kunglao_upgrade.py` 内直连
  `print("kunglao-upgrade: WARN` 计数 == 0（全部 WARN 行经 `_warn`/`_warn_line`）；
  (2) triple 唯一性：`_emit_event(event, "warn", why)` 在源内恰 1 次（即 `_warn` 体内）；
  (3) util 契约钉：monkeypatch 双 emit 面断言三信号/`ws=None`/`ledger_detail` 覆盖三态。
  行为等价由既有 test_deploy_surface_755 行为组（不改）兜底。

### 基线

- `tests/test_toolchain_stdio.py + test_deploy_surface_755.py`：**40 passed, 1 failed**——failed 为
  `TestT6Registry::test_already_at_target_still_plans_deploy_items`（KeyError 'notes/keep.md'），
  改动前即失败，属计划已列 7 个 Windows 环境性基线失败中的 test_deploy_surface_755（CI Linux 权威）。

### 偏航记录（实现级，非 RECON-DEVIATION）

- Family E 计数：issue "11 exact +4" vs 实测 16 print 处（8 triple + 2 near + 1 backfill + 2 双信号
  + 3 print-only）——#739/#752/#753/#755/#758 增量所致；按 16 处全量收编，非削减方向。
- Family H 落点 utf8_boot.py 而非新建模块——消费方全在 scripts/ 且主题同源（#811），镜像 ws_layout
  先例"按消费方分布定夺"。

## Recon（863-e，2026-09-02 实测）

范围：Package 2 批 2 四项（no-backward-compat 删除/收敛）+ 附加三项（promote_lesson /
grace 旗标 / lint_facts-migrate_facts 裁决落地）。审计报告 /tmp/kunglao-audit 已清失，
issue 表格为权威 fallback；全部锚点按符号 grep 重定位。**无 RECON-DEVIATION，七项全放行。**

另勘误：proposal.md 头部"Package 2 已先行交付（PR #875）"不实——#875 实为
862-budget-channel；本卡四项在 dev 4caeb44 上全部仍活体存在（下表实测），按本卡执行。

### 锚点表（issue 锚点 vs 实测）+ 七项四件套

| # | 项 | issue 锚点 | 实测定义 | 活体引用 | 测试钉 | 清理面 |
|---|---|---|---|---|---|---|
| 1 | wire_up_settings deprecated alias | wire_up_settings.py:158-180 | :189-209（`def wire_up_settings`，DeprecationWarning→register_hooks 委托）；模块 docstring :2-15、`import warnings`:45 仅其使用 | hook_activation.py:484-487 `DEPRECATED_ALIASES` 声明（:49/:61/:64 为历史 prose）；无生产调用方 | test_hook_registration_entry.py:98-105（声明钉）、:108-125（委托钉，删）；test_completion_gate.py:493-516、test_wire_up_settings.py ×9、test_state_anchor.py:313-338（行为钉，改调 register_hooks） | 删 alias+warnings import+docstring 条目 2；`DEPRECATED_ALIASES = ()`；注册表本体（WIRE_UP_HOOK_FILES/HOOK_EVENTS/hook_deployment_targets/derive_hook_subset）全保——env_check/state_anchor/external_kicker/hook_activation 活体消费 |
| 2 | worker_budget._ShimModule | worker_budget.py:44-64 | :54-61（类+`__class__` 赋值）+ 供数表 `_PROPAGATE_TO`:46-51（仅 shim 消费） | 模块外零引用（grep 全库） | test_stuck_gate.py:35-69（×5 `wb._run_py`）、test_heartbeat_bootstrap.py:200（`wb._run_py`）、test_failopen_emit.py:122（`wb.check_priority`）依赖转发；test_worker_budget.py:818-826 已直 patch 源模块（镜像样例） | 删 :40-61；三测试文件 patch 目标改源模块（worker_budget_sinks._run_py / worker_budget_core.check_priority），镜像 test_worker_budget.py 形状。issue 称"+2 测试文件"，实测 3 个依赖转发的文件（非削减，全改） |
| 3 | validate_index._LEGACY_UNANNOTATED | validate_index.py:58-70,146,296-307 | 白名单 :59-74（29 名 frozen）、检查点 :297-307、:147-149 docstring "legacy untouched" | 非测试零引用 | test_validate_index.py:268-308（TestRuleA：legacy WARN 钉 :286-293 翻转）、test_index_capability_annotations.py:144-150（翻转）、:164-168（shipped index 绿——回填后仍须绿，保留） | 删白名单→所有无 provider 条目硬错；tools/_INDEX.yaml 29 条目机械回填（provider=自名、produces=[capability]、requires=[]、cost_hint={mem_gb: probe 0.1/cheap 0.5/deep 4.0, time=cost_tier}、quality={capability: high}——单能力 provider 先例 jadx/wakaru/jsvmp-triage）；`_CAPABILITY_TAGS` 扩 27 个 legacy capability 标签（29 中 2 个已在集）；测试翻转 2 处 |
| 4 | digest_build pre-contract fallback | digest_build.py:81-84 | :78-80（`facts/_INDEX.md` 不存在→`<ws>/_INDEX.md`）+ docstring :77 | 消费方（kunglao_resume/kunglao-digest/acceptance_check）全部面向规范工作区 | 零测试钉 fallback（test_digest.py 等全部写 facts/_INDEX.md 规范位） | 删回退 2 行 + docstring 句 |
| 5 | promote_lesson 双定义 | failure_analysis_gate.py:643/938 | 死定义 :654-702（49 LOC，被 :949 遮蔽）+ 私有 helper `_read_lesson_frontmatter`:639-651（仅死定义使用）；活定义 :949-1014 | 测试全走活定义（Python 后 def 胜） | test_lessons_nursery.py:168-251、test_lessons_trigger_precision.py:142-156 钉活定义行为（保留） | 删死定义 + helper；补活定义 soft-fail 行为钉（缺失文件/无 frontmatter/YAML 错 reason 返回） |
| 6 | kunglao_verify --grace/--grace-scan | （~45 LOC） | kunglao_verify.py:201,206-207,217-218（grace 形参）、:830,836,850,857（verify grace）、:969-985（_grace_scan）、:989-1007（CLI）；kunglao.py:90-93,370-373（dispatcher 镜像）；references/schema.md:123-126（migration 段） | 无其他代码调用方传 grace=True | test_fact_expected_binding.py:104-107（grace warn，删）、:217-254（grace-scan ×2，删） | 全删（含 kunglao.py 双镜像 + schema.md 段）；ghidra 的 `--grace`（job 崩溃宽限）是另一旗标，不碰 |
| 7 | lint_facts/migrate_facts 裁决 | migrate_facts.py:52 | lint_facts.py:160-185（parse_frontmatter）、:188-357（kv 家族）、:414-431（`_index_status_values` +PARTIALLY-VERIFIED）、:727-729（UNPARSEABLE 门）；migrate_facts.py:52-56 导入 + 3 调用点 :360,479,485 | bash_fact_guard.py:78（parse_frontmatter+lint_fact 运行时门）、write_guard.py（仅 lint_index/lint_workspace） | test_lint_facts_532.py:144（PARTIALLY-VERIFIED 行 True→翻 False）、:176-186（同翻转）；test_icd203_alignment.py:199（UNPARSEABLE-or-NO_FRONTMATTER，兼容）；test_icd203:293-300（migrate 输出保 PARTIALLY-VERIFIED——不动） | 裁决落地：(a) lint_workspace 对 `yaml-unparseable` 一律硬错（kv 回退结果不再静默过检）；(b) `_index_status_values` 双分支删 PARTIALLY-VERIFIED；(c) `_parse_kv_block` 家族原地保留、parse_frontmatter 容忍语义不变（bash_fact_guard 运行时容忍读零行为变化）；(d) migrate_facts 内联自有 `_parse_frontmatter`（fence+yaml-first+marker 包装 + `_coerce_yaml_scalars` 副本，kv 回退引 lint_facts._parse_kv_block——裁决钉留处），弃 parse_frontmatter 导入 |

### promote_lesson 行为差异结论（合并前 review，幸存语义 = :949 活定义）

死定义（:654）与活定义（:949）差异八处：① 签名默认值（死有 workspace=None/promoted_by/
evidence 默认，活全必填）；② 缺文件：死 raise FileNotFoundError，活返回
`{"promoted": False, "reason": "lesson not found: ..."}`；③ 无 frontmatter/非映射/YAML 错：
死容忍改写（防御性 fallback 重排），活一律 soft-fail 带 reason；④ already_active 返回形状
（死带 `lesson` 键，活带 `promoted_at`）；⑤ promoted_evidence：死条件写入，活恒写入；⑥
审计行：活多 `tool=`/`artifact=` 且 detail 恒带 evidence=；⑦ claim 空：死 ""，活 None；⑧
成功返回形状（死 lesson/promoted_by，活 from_stage/to_stage）。**幸存 = 活定义**：运行时
从来只有 :949 生效，测试钉的全是它；死定义的默认值签名在运行时不可达（若有人按死签名
调用，:949 的必填形参当场 TypeError）——删除即零行为变化（by construction）。补钉项：
soft-fail reason 三态（not found / lacks frontmatter / parse error）若无既有覆盖则新增。

### 基线

- 受影响 20 测试文件：**379 passed, 1 error**（error = test_icd203_alignment teardown 的
  #770 双生模块守卫——该测试显式插入 malware-veri-notes 外部 skill scripts 进 sys.path，
  环境性、teardown-only、先于本卡存在；测试本体 passed）。
- `python scripts/kunglao-verify.py --help` 现含 `--grace/--grace-scan`（退役后 grep 为空）。

### 界外观察（不顺手做）

- 主仓 `D:/codebase/kunglao-agent` 工作区有未提交的 `M scripts/migrate_facts.py`（用户
  WIP/并行卡落点）；本卡只动 worktree `D:/codebase/kunglao-wt-863e`，合流时按 dev 侧+再生解。
- tools/_INDEX.yaml 与在跑 866-b 卡的合流冲突预案：合并 origin/dev 冲突时取 dev 侧 +
  机械回填再生（不手拼）。
- `tests/test_icd203_alignment.py` 的 #770 teardown 守卫噪声（外部 skill sys.path 污染）
  值得单独一卡。

## Recon（863-i，2026-09-02 实测）

### 锚点表（issue/计划锚点 vs 实测）

| 族 | issue 表述 | 实测 | 结论 |
|---|---|---|---|
| I | tools/static `_error` 6 份（4 identical + 2 drifted: return vs sys.exit），收敛 `common.py:63 error()` | **7 份 `def _error`**：tools/static 6（disasm_dump:63 / overlay_scan:76 / pe_analyze:98 / shellcode_scan:64 同形 `(code, message)→sys.exit`；yara-gen:33 / yara-scan:34 同形 `(msg)→return EXIT_ERROR`）+ **界外第 7 份** tools/crypto/crypto-tool.py:74（`(code, message)→sys.exit`，与 common.error 同形） | tools/static 6 与 issue 计数吻合；common.py `error()` 现存 :63（行号未漂）。crypto-tool 属 tools/crypto 类目（common.py docstring #340 R3 "one shared module per category"），不在本族表内 → 界外观察不收编 |
| I 调用点 | 未列 | Shape A 22 处（disasm 6 / overlay 5 / pe 5 / shellcode 6）**全部 code=2**；Shape B 6 处（yara-gen 4 / yara-scan 2）**全部 `return _error(...)` 于 `main() -> int` 内，模块底 `sys.exit(main())`** | Shape A 可无损换 `error(msg)`（默认 code=2）；Shape B 见契约裁决 |
| J | `_write_evidence` 4×7，dexdc 3-arg 为准，落点 tools/static/common.py | 4 份：apk_mem_gate.py:186（2-arg，apk_mem_gate.json）/ baksmali_index.py:102（2-arg，smali_index.json）/ dexdc_scanner.py:103（**3-arg** `(workspace, name, data)`）/ scripts/apkid_scanner.py:109（2-arg，apkid.json）。函数体逐字节同构（mkdir evidence → write_text(json.dumps(ensure_ascii=False, indent=2), utf-8) → return path）。调用点 11 处（apk_mem 1 / baksmali 3 / dexdc 2 / apkid 5） | dexdc 形状 = 单源签名；2-arg 三份的文件名常量上提到调用点 |
| K | tolerant JSONL loop 8+×7 → 单 reader util ~64 LOC | **19 个循环点 / 18 个文件**，全部在 scripts/（tools/hooks 零命中）；统一核形 = 逐行 → strip/空行跳 → try json.loads → except (JSONDecodeError\|ValueError\|…) continue → 消费方自有后过滤 | 超额达标（issue 8+）；逐文件清单见下方转换集 |

### I 契约分叉裁决（显式修法）

**统一到 common.error 的 sys.exit（NoReturn）契约**，六份全收敛，yara 侧 return-value 契约被吸收：
(a) 4/6 副本本就是 sys.exit 形；(b) common.error 是先存单源（#340），"收敛 common.py" 是 issue 明示方向；
(c) yara 六个调用点全在 `main()->int` 内且返回值只喂模块底 `sys.exit(main())` —— 改为
`error(msg)` 后 SystemExit(2) 从 main() 内直接穿透，进程级可观测行为逐字节等价
（stderr JSON 同构 `{"error": …, "exit_code": 2}`、退出码 2）。**测试面语义变化 = 显式分叉修复的编码点**：
进程级（subprocess）既有测试不受影响；进程内 `main()` 错误路径由"返回 2"变为"raise SystemExit(2)"
——与 test_static_tools_1c 对 die_probe（common.error 消费方先例）的 `pytest.raises(SystemExit)` 断言完全一致。
新增契约钉测试锁死 SystemExit(2) + stderr JSON。

### 落点裁决（按消费方分布）

- **I/J → tools/static/common.py**（issue 明示；4 份 J 消费方中 3 份在 tools/static，
  既有 `from common import …` 同目录导入先例 disasm_dump:51 / overlay_scan:57 / pe_analyze:49 /
  shellcode_scan:45 / die_probe:54；yara 两份与 apk_mem_gate/baksmali_index/dexdc_scanner 补
  `_THIS_DIR` sys.path 块镜像 disasm_dump:46-50 先例）。
- **J 的 scripts 侧消费方 apkid_scanner 经 `scripts/_hooks_path.load_module_by_path` 桥**
  （#891 Family B 唯一 by-path 加载点权威）以唯一名 `tools_static_common` 装载 common ——
  不往全局 sys.path 插 tools/static（"common" 是泛化名，插入即 shadow 风险）。代价：进程内
  common 可能双实例（sys.path 导入 + by-path 桥），write_evidence 纯函数双执行无害，记录在案。
- **K → `scripts/kunglao_log.py::iter_jsonl`**。_runner-up 与否决理由_：scripts/lib_kunglao
  （scripts 共享库宪章 #43）被否——hooks 进程以裸名 `import kunglao_log` / `import priority_ratio` /
  `import heartbeat` 引 scripts 模块（hooks/dispatch_gate.py:423/686、worker_budget_core.py:83/130、
  worker_budget_sinks.py:272 等十处实证），此刻裸名 `from lib_kunglao import …` 会按 sys.path 序
  解析到 **hooks/lib_kunglao 孪生**（#671 记录的 shadow 陷阱本体）→ iter_jsonl 缺失 → 崩溃。
  kunglao_log 是**唯一已被证明在两个 sys.path 域都可安全导入**的模块（hooks 十处今日就在导它，
  scripts 十余处亦然），stdlib-only、module-level 仅常量无副作用、JSONL 格式的属主模块
  （emit 写 / iter_jsonl 读同门）——新 util 落它名下零新增导入风险；备选新建 scripts/jsonl_reader.py
  被否（新增资产面 + 属主主题弱于格式属主模块）。

### K 转换集（19 循环点 / 18 文件）与残留 pin

iter_jsonl 核契约：`Iterable[str] → Iterator[Any]`，跳空行 + `except ValueError: continue`
（JSONDecodeError 是其子类，覆盖全部七种历史 handler 形），**不过滤 dict**（yield Any 保逐份
字节等价：convergence_health 收非 dict、kunglao_status trend 靠 AttributeError 跳非 dict、
kunglao_record `_event_id_in_lines` 对非 dict 仍 AttributeError 崩——全部原样保留）；消费方自有
后过滤逻辑一律原位保留。转换集：bench_tokens、convergence_health、event_taxonomy(_read_jsonl
改委托)、external_kicker、heartbeat、infeasible_signal、kunglao_log(:209)、kunglao_record(:91+:133)、
kunglao_resume(:288+:340 两处)、kunglao_status(:131+:173)、lib_kunglao(:87)、mechanism_scheduler
(bytes 循环拆 non_blank 计数 + iter_jsonl，null 行 AttributeError 崩语义保真)、outcome_capture、
priority_ratio、recall_metrics、rho_verifier、ask_for_direction_gate、cost_gate(parse_event 改
next(iter_jsonl([line]), None))。

**不转换（界内点名，非族内形状）**：kunglao_upgrade.py:545（tolerant **rewrite**——坏行 `kept.append`
原样保留回写，读-改-写契约非 reader）；bench_analyze.py:292（**strict** list-comp——坏行崩，转了反而改行为）；
三个 detail/state 解析点保持本地（rho_verifier:204、infeasible_signal:48、kunglao_record:470——
非"逐行 jsonl"循环，是已解析行的字段解析 / CLI 参数解析）。

执法 pin（新测试 `tests/test_delegation_863i.py`）：每文件 `"from kunglao_log import iter_jsonl"`
在源（委托断言）+ `json.loads`/`json.JSONDecodeError` 残留计数逐文件钉死（bench_tokens/
convergence_health/event_taxonomy/outcome_capture/recall_metrics/cost_gate/kunglao_status/
priority_ratio/lib_kunglao/ask_for_direction → 0/0；rho_verifier 1/1、kunglao_log 1/1、
kunglao_record 1/1、kunglao_resume 2/0、heartbeat 4/2、infeasible_signal 2/2、
mechanism_scheduler 3/0、external_kicker 2/0）——残留回升即红，复审门。

### 守护测试现状 + delegation assert 方案（四件套之三四）

- I：**行为级**（test_static_tools_1b/1c + test_yara_tools 全 subprocess，错误路径断言 exit 2 +
  stderr JSON）→ 保留不动（委托后仍绿）；新增：六文件 `def _error`/`_error(` 源清零 confinement +
  六文件 `error is common.error` 身份级委托断言 + yara 两份进程内 `pytest.raises(SystemExit)`
  契约钉（分叉修复编码点）。
- J：**无守护**（issue "none" 属实；test_apkid_scanner 钉 evidence/apkid.json 行为、
  test_apk_mem_gate/test_baksmali_index/test_dexdc_scanner 钉各自 evidence 文件行为）→ 全保留；
  新增：common.write_evidence 契约钉（路径/内容/utf-8/indent/mkdir/返回 Path）+ 四文件
  `_write_evidence` def 清零 + 身份级委托断言（apkid 经同名桥实例比对）。
- K：**无守护**（issue "none" 属实）→ 新增：iter_jsonl 契约钉（空行/坏行/null 行 yield None/
  顺序/生成器与 reversed 输入）+ 上述逐文件委托与残留 pin。

### 基线（改动前）

- 受影响直接测试 14 文件（yara/static_1b/1c/apkid/apk_mem/baksmali/dexdc/kunglao_log/resume/status/
  bench_tokens/infeasible/outcome/priority_ratio）= **218 passed, 1 skipped**；
  heartbeat_*+event_taxonomy+external_kicker+rho_verifier+ask_for_direction+mechanism_scheduler =
  **148 passed**；`-k "lib_kunglao or convergence_health or recall_metrics or cost_gate or mechanism"`
  = **68 passed, 2 skipped**。

### 偏航记录（实现级，非 RECON-DEVIATION）

- K 计数：issue "8+×7" vs 实测 19 循环点/18 文件（下限口径吻合，全量收编非削减）；
  I 第 7 份 crypto-tool、2 个非 reader 形（upgrade rewrite / bench_analyze strict）界外点名。
- 并行碰撞注记：863-g（utc_now→harness_common）与 863-h（conftest/test fixtures）会触碰
  本卡 K 转换集内部分 scripts/tests 文件——不同 hunk 区，CONFLICTING 时按预案合并 origin/dev 解。
- `tests/` 新增 1 文件（test_delegation_863i.py），无 scripts/hooks 资产增删
  （lib_kunglao/kunglao_log 均既有文件）；deploy_manifest 预计无资产面变更，收尾跑 --check 确认。

## Recon（863-h，2026-09-02 实测）

### 前置事实核对（Family G 与 #811 裁决）
- #811 GBK 裁决（仲裁项 B6）已由 commit 34e1603（2026-09-01）落地：根 conftest.py 删除
  5 个被遮蔽夹具（tmp / ws_factory / contract_validator / golden_master / isolated_home，
  -128 行），方向 = GBK 修复版胜出——子 tests/conftest.py 的 golden_master 携带 #317 UTF-8
  解码（encoding="utf-8" + errors="replace"），root 副本裸 text=True 是活体 GBK 陷阱。
- 本卡 Family G 余量 = 验收证据（git grep）+ 防复活机械钉
  （tests/test_conftest_single_source_863g.py，4 测试）。

### 锚点表（计划/issue 锚点 vs 实测）
| issue/计划表述 | 实测 | 结论 |
|---|---|---|
| conftest fork 2×113 | 修复前根 conftest 131 行含 5 夹具复本；34e1603 后根 conftest 仅 #369 flock + #770 syspath 守卫（4 个独有 fixture/helper），与 tests/conftest.py 零重叠 | fork 已清零（#811 预完成），本卡补机械钉 |
| 删 5 个被遮蔽 root fixtures | 34e1603 diff 段：tmp / ws_factory / contract_validator / golden_master / isolated_home 五段全删 | 已完成；方向合规（GBK 版胜出，本卡 863g 钉回验） |
| hook_state ×5 | 实测 34 内联写点 / 27 文件（27 = 12+15 峰值并集） | 大幅上修，除 5 处非种子形状外全收编 |
| claim-seed ×4 | 机制形态（dict-list→register）7 文件 7 帮手 + conftest ws_factory 同型发射体 | 机制形态全收编；201 处剩余为一次性 fixture 文本内容（富 YAML 手写体），非机制复制，不属本族 |
| sample.exe ×4 | 实测 34 写点 / 26 文件 | 大幅上修，34/34 全收编 |
| ~19 families / factory ~90 LOC | 三命名族收编；tests/_factories.py 共 ~150 LOC | factory 规模略超 issue 估算，功能等价账本钉齐 |

### Family L 形状分类与等价性依据
- hook_state 4 形状：full 7 键（completion_gate 族）、minimal 3 键（dispatch_gate 族）、
  6 键 null-expiry（dispatch_contract / scorer_authority）、2 键（backtrack / resume 族）；
  另 upgrade 族 5 键 + `state` 额外键（extra 参数）。等价性：read_state=json.loads
  （字节无关），is_active_strict 只读 expires_at/user_override/active_hooks/paused_hooks；
  工厂 None-omit 语义逐字段保形，golden-dict 钉齐（test_fixture_factories_863l.py）。
- claim-seed 2 方言：canonical 6-field f-string（ws_factory == decide_schema_routing 逐字节）
  与 sparse（yaml.safe_dump ×4、3-field ×1、type-aware ×1）。等价性：消费方全部 yaml.safe_load
  （think_seat.py:81、rollup.py:68、priority_ratio.py:143 实证）；解析等价钉在 863l 钉文件。
- sample.exe：`(ws/"bins").mkdir(parents=True)` + `write_bytes(b"MZ"+b""*64)`
  2 行形状 ×25 邻接点 + 9 变体点（非邻接/bins-var/4 字节占位/PAYLOAD 常量）。等价性：
  payload 字节级同型（seed_bins 默认 payload = 原 MZ+零尾字面量，863l 钉）。

### 方案与落点
- 工厂落点 tests/_factories.py（普通函数 + conftest 薄 fixture 再导出
  hook_state_seed / claims_seed / bins_seed；**不可 `from conftest import`**：pytest.ini
  pythonpath 首位是仓库根，`conftest` 名字歧义会解析到根 conftest）。
- write_hook_state（None-omit 语义 + expires_minutes 便捷参 + extra 附加键）、
  write_claims_register（defaults=True canonical 方言 / False sparse 方言）、
  seed_bins(name/payload)。conftest ws_factory 发射体委托（逐字节不变）。
- 守护：test_fixture_factories_863l.py（12 钉：4 形状 golden dict + extra + claims 双方言
  字节/解析等价 + seed_bins 字节钉 + 再导出身份钉）；test_conftest_single_source_863g.py
  （4 钉：root 禁 5 夹具名、tests/conftest.py 必持 5 夹具、golden_master #317 解码钉、
  fixture 解析行为钉）。每步转换后受影响面全绿再提交。

### 验收证据
- git grep：根 conftest 4 个 fixture 定义全为 #369/#770 独有
  （load_lock_factory / load_sensitive_registry / _serialize_load_sensitive /
  _syspath_collision_order_guard），5 遮蔽名零命中；tests/conftest.py 5/5 持有。
- hook_state 内联 dict 写点 0 残留（5 处留点均为轮转写/垃圾字面量非种子形状）；
  claim 机制形态 0 残留；sample.exe 34/34 清零。
- 基线（4caeb44，Windows 本地）：**9 failed / 5187 passed / 12 skipped**
  （7 个已知环境失败 + ghidra_async 2 flaky 家族）；终局全量 = 基线同集合（见下）。
- release_receipt.py --check RC=0（提取前）；终局复验见 PR 描述。

### 偏航记录（实现级，非 RECON-DEVIATION）
- G：删除工作 #811 已预完成 → 本卡交付 = 证据 + 防复活钉（方向与验收不变）。
- L 计数上修（×5/×4/×4 → 实测 27-34/7+201/34）：按家族符号 grep 全量口径全收编，
  201 处一次性 fixture 文本内容不属机制复制，显式排除并留痕。
- 工厂落点 tests/_factories.py（WHY：conftest 名字歧义风险），conftest 薄再导出。
- qtable_p3 encoding kwarg 小偏差归一（无行为差）。
### Family D 核验（orchestrator 初证 → 本卡复核 CONFIRMED，无需重做）

- `git grep _which_items`：仅 `scripts/toolchain.py` 5 处（def :512-538 + 调用 :1521/:1538/:1551/:1655），
  带 `#863 Family D` docstring——由 #877（commit e3d640c）交付。
- 覆盖形态核对：2 个 hard-loop（windows/linux 的 file/readelf/objdump，:1521/:1551）+ 2 个 docker-block
  （windows/linux，:1538/:1655）+ jadx/apktool（Android）全部经 `_which_items`；issue 计数口径
  "intra ~90" = toolchain.py 文件内复制，与现状吻合。
- 残留扫描：`shutil.which` 在 scripts/hooks/tools 的其余命中（apkid_scanner:44、deploy_shim:154、
  env_check:400-404、env_manifest:553、env_repair_l1、env_state_probe、intake_promise:194、
  kunglao_upgrade:1060、pkg_detect、toolchain_install:453/458、tools/static 若干）全部是**单命令
  专用探针**（各自二进制、各自用途），非 which→CheckResult 列表循环族；Family D 符号族清零成立。
- 守护：无 `_which_items` 符号级测试（与 issue 表"behavior tests only"执法口径一致）——行为由
  test_probe_tiers_474 / toolchain 面测试钉住。结论：**D 已完成，本卡零代码改动，仅记录**。

### 锚点表（计划/issue 锚点 vs 实测）

| issue/计划表述 | 实测 | 结论 |
|---|---|---|
| Family E "WARN-triple 11 exact +4"（`warn()` ~50 LOC） | `kunglao_upgrade.py` 内 WARN print 共 **16 处**（grep `WARN.*file=sys.stderr` 族）：**8 处全 triple**（print + `_emit_event(..., "warn", why)` + `_emit(ws, ev, f"warn:{why}")`）：agents_refresh :268-272、uv_sync ×4 :1062-1093、staleness ×3 :1133-1165；**2 处 near-triple**（第三信号 detail 非默认）：claudemd `skipped:` 前缀 :422-427、toolchain_manifest 明文 detail :1008-1012；**1 处双信号**（print+event 无 ledger）：backfill channel :981-986；**2 处双信号**（print+ledger 无 event）：mcp :900-904、env_ledger unparseable :943-947；**3 处 print-only**：frame-stale :144-146、`_warn_git_skip` :699-700（已是具名单源，7 调用点）、sweep :1381-1383（注意该处连字符 `-` 非 em-dash，字节保真保留） | 行号/计数全漂移（issue 基于旧版；#739/#752/#753/#755/#758 增量）；按 16 处全量处理，triple 形状确认 |
| Family E 守护测试 `test_deploy_surface_755.py:349-361` | `test_failure_is_warn_not_fatal` :348-359（行为断言：warn label + stderr 含 WARN+uv_sync）+ `test_timeout_is_warn` :361-372 等——**行为测试，非 textual**；按 863-b 先例：行为测试保留 + 新增 delegation/confinement 执法测试 | 行号漂移按符号定位 |
| Family H `_ensure_utf8_stderr` 3×9 | 3 份函数体逐字节等价（9 行）：`toolchain.py:49-63`（调用 :66 module-level）、`toolchain_install.py:56-70`（调用 :73 module-level）、`kunglao-init.py:566-580`（调用 :2654 main() 首语句）；docstring 微漂移（toolchain_install 缺 `REFUSE —` 例） | 确认 3×9 |
| Family H 守护测试 `test_toolchain_stdio.py:160-163` | `test_utf8_stderr_call_sites_pinned_in_source` :150-164（`source.count("_ensure_utf8_stderr(sys.stderr)")==1` textual tripwire，fault-inject M8 语义）+ 3 个行为测试 :109-137（recorder 断言 encoding=utf-8/errors=replace/fail-open False） | 行号漂移；textual 改 delegation，行为测试保留 |

### 方案（落点 + delegation 形态）

- **Family E 落点：`kunglao_upgrade.py` 模块内 `_warn()` / `_warn_line()`**（issue 明示"one warn()
  helper ~50 LOC"；16 处副本全部在同一文件内，无跨文件消费方 → 模块内单源即清零，无需新 util 模块）。
  形态：`_warn(msg, why, event, ws=None, *, ledger_detail=None)` = stderr 行 + `[event]` 轨 + ledger
  三信号（`ws=None` 保持 ledger 面静默；`ledger_detail` 覆盖默认 `warn:{why}`——claudemd 的
  `skipped:` 前缀与 toolchain_manifest 的明文 detail 由此保真）；`_warn_line(msg)` = 纯 stderr 面
  （print-only 三处 + 双信号两处的 print 腿），`_warn` 组合 `_warn_line`。
  **双信号两处（mcp/env-unparseable）不升格为 triple**——加 `[event]` 行即输出变化，违反行为等价。
- **Family H 落点：`scripts/utf8_boot.py::ensure_utf8_stderr(stream=None) -> bool`**。WHY：#811
  stdio 保险层模块，docstring 自declares"本模块管 stdio 与子进程树"——主题同源；3/3 消费方全在
  scripts/（裸导入，无 Family B 式桥）。delegation 形态 = **纯别名**（863-c 最强委托形态）：
  三处 `def` 原位替换为 `from utf8_boot import ensure_utf8_stderr as _ensure_utf8_stderr`（原位 =
  module-level 调用时序不变，toolchain.py stdout 先于 stderr reconfigure 的既有顺序保持）；
  `_ensure_utf8_stderr(sys.stderr)` 调用点一律不动（M8 tripwire 的钉就是调用本身）。
- **执法测试**：Family H——`test_toolchain_stdio.py` 的 textual tripwire 改写为**身份级 delegation
  断言**（`mod._ensure_utf8_stderr is utf8_boot.ensure_utf8_stderr` ×3）+ 保留调用点 count==1 pin
  （M8 语义：乱码 fix 是 CALL 不是 helper）；3 个行为测试保留（经别名仍绿）。Family E——新增
  `tests/test_warn_delegation_863f.py`：(1) confinement：`kunglao_upgrade.py` 内直连
  `print("kunglao-upgrade: WARN` 计数 == 0（全部 WARN 行经 `_warn`/`_warn_line`）；
  (2) triple 唯一性：`_emit_event(event, "warn", why)` 在源内恰 1 次（即 `_warn` 体内）；
  (3) util 契约钉：monkeypatch 双 emit 面断言三信号/`ws=None`/`ledger_detail` 覆盖三态。
  行为等价由既有 test_deploy_surface_755 行为组（不改）兜底。

### 基线

- `tests/test_toolchain_stdio.py + test_deploy_surface_755.py`：**40 passed, 1 failed**——failed 为
  `TestT6Registry::test_already_at_target_still_plans_deploy_items`（KeyError 'notes/keep.md'），
  改动前即失败，属计划已列 7 个 Windows 环境性基线失败中的 test_deploy_surface_755（CI Linux 权威）。

### 偏航记录（实现级，非 RECON-DEVIATION）

- Family E 计数：issue "11 exact +4" vs 实测 16 print 处（8 triple + 2 near + 1 backfill + 2 双信号
  + 3 print-only）——#739/#752/#753/#755/#758 增量所致；按 16 处全量收编，非削减方向。
- Family H 落点 utf8_boot.py 而非新建模块——消费方全在 scripts/ 且主题同源（#811），镜像 ws_layout
  先例"按消费方分布定夺"。

## Recon（863-g，2026-09-02 实测）

### 重数对照表（四说 7/33/50/20 归因 + 实数）

口径：`git grep -E "def utc_now|def _utc_now|def now_utc" -- '*.py'`（`now_utc` 零命中）。
**实数：53 份定义复制**（基点 4caeb44，2026-09-02）。

| 四说数字 | 最可能口径归因 | 置信 |
|---|---|---|
| 7 | 部分目录子集计数（hooks+tools/static+个别 = 5；或某单形状子集）——审计报告 /tmp/kunglao-audit/ 已被清，原始 grep 不可回验；不采纳为任何工作对象 | 低（不可回验） |
| 33 | 审计时点计数或"公开名"子集（`def utc_now(` 精确 31 + 公开 iso 2 ≈ 33）；53-33=20 与 isoformat-Z 形状数巧合 | 低（不可回验） |
| 50 | 53 − 3（tools/static 3 份）= 只数 scripts/+hooks/ 的口径；或审计时点（后续 #878/#882/#883/#897 新增若干份） | 中 |
| 20 | = isoformat(timespec="seconds")+replace→Z 形状**恰好 20 份**（同形状算一族的口径）；issue 表 "~20 defs, drifted" | 高（形状重合是实测巧合级吻合） |

不可回验声明：审计报告已清（`/tmp/kunglao-audit/` 不存在），7/33 归因无法回验原始口径；
合并工作的真实对象 = 53 份定义（"函数定义复制"口径），以本表实测为准。

### 形状分类（53 份 → 3 个 util 函数 + 0 个弃子）

| 形状 | 份数 | 定义样本 | 语义 | 收敛到 |
|---|---|---|---|---|
| A: 返回 tz-aware datetime | 8 | `datetime.now(tz=timezone.utc)` | datetime 对象 | `utc_now()` |
| B: strftime Z 形 | 23 | `strftime("%Y-%m-%dT%H:%M:%SZ")` | "YYYY-MM-DDTHH:MM:SSZ" | `utc_now_z()` |
| C: isoformat+replace Z 形 | 20 | `isoformat(timespec="seconds").replace("+00:00","Z")` | 同 B **字节等价**（机械可测） | `utc_now_z()` |
| D: +00:00 偏移后缀 | 2 | `isoformat(timespec="seconds")`（无 replace） | "…T…+00:00" 真变体 | `utc_now_iso()` |

B/C 字节等价证明：两者对同一 datetime 都产出 `YYYY-MM-DDTHH:MM:SSZ`（秒精度、Z 后缀），
守护测试以同一 datetime 双路径比对钉死。合计 8+23+20+2 = 53。✓

### 复制定义清单（每份 file:line）

**形状 A → `utc_now`（8）**：scripts/active_intervention.py:47、scripts/backtrack_gate.py:40、
scripts/claim_expiry.py:41、scripts/convergence_check.py:74、scripts/cost_gate.py:49、
scripts/kunglao_resume.py:140（`_utc_now`）、scripts/kunglao-monitor.py:106（`_utc_now_dt`）、
scripts/progress_report.py:51。

**形状 B+C → `utc_now_z`（43；其中 42 批量 + hooks/heartbeat_touch 手工桥接）**：
scripts/apkid_scanner.py:31、scripts/ask_for_direction_gate.py:245、scripts/backtrack_loop.py:80、
scripts/complete_teardown.py:96、scripts/dead_letter.py:55（`utc_now_iso`）、
scripts/dispatch_context.py:83、scripts/env_check.py:168、scripts/env_repair_l1.py:62、
scripts/env_state_probe.py:69、scripts/external_kicker.py:174、scripts/feedback.py:51、
scripts/heartbeat.py:253、scripts/heartbeat_tick.py:87、scripts/heartbeat_touch.py:28、
scripts/hook_activation.py:129、scripts/hooks_selfcheck.py:82、scripts/infeasible_proposal.py:32
（`utc_now_iso`）、scripts/init_state.py:31、scripts/kunglao-init.py:561、
scripts/kunglao-monitor.py:101、scripts/kunglao_log.py:129、scripts/kunglao_record.py:60、
scripts/kunglao_verify.py:80、scripts/lessons_telemetry.py:50（`_utc_now_iso`）、
scripts/loop_scheduler.py:57、scripts/loop_state.py:54、scripts/mechanism_scheduler.py:113、
scripts/mission_ledger.py:26、scripts/plan_drift_detector.py:82、scripts/plan_reviser.py:69、
scripts/plan_stages.py:34、scripts/provider_health.py:36、scripts/run_test_matrix.py:41、
scripts/stale_blocker_prune.py:45、scripts/statusline_snapshot.py:162、
scripts/troubleshooting_gate.py:39、scripts/verify_status_watch.py:48、
tools/static/apk_mem_gate.py:54、tools/static/baksmali_index.py:32、tools/static/dexdc_scanner.py:60。

**形状 D → `utc_now_iso`（2）**：scripts/failure_analysis_gate.py:139、scripts/outcome_capture.py:61。

命名变体统计（口径留档）：`def utc_now(` 31、`def _utc_now(` 14、`def utc_now_iso(` 6、
`def _utc_now_iso(` 1、`def _utc_now_dt(` 1（= 53）。调用面 ~91 行（参考值，非合并对象）。

### 落点与导入桥（镜像先例）

- 单源落 `scripts/harness_common.py`（issue 命名；镜像 Family C `scripts/ws_layout.py`：
  scripts 同目录裸 import，消费方 `from harness_common import utc_now_z as <原名>` 保持
  调用面零改动）。
- hooks/heartbeat_touch.py：`from _path_hygiene import ensure_scripts_path`（#671 现成桥，
  env_check_gate.py:51/57 同款）+ `import harness_common` + `utc_now = harness_common.utc_now_z`。
- tools/static 3 份：文件头 `_sys_io` 档案惯例（apk_mem_gate.py:21-26）+ scripts-on-path +
  `from harness_common import utc_now_z as _utc_now  # noqa: E402`。common.py 不动
  （其契约"no imports of the sibling tools / importable alone"——单向依赖 scripts 单源，
  不建第二共享层）。
- 真变体保留：形状 D 2 份（+00:00 后缀）映射 `utc_now_iso`；failure_analysis_gate.py 为
  863-e 碰撞文件（本卡仅动 def→import 2 行，冲突面极小，FULL MIRROR 可解）。

### 守护测试清单 + delegation assert 方案

新增 `tests/test_harness_common_863g.py`（镜像 863-c 三段式）：
1. **confinement**：全库 rglob 扫描，`def utc_now|def _utc_now|def now_utc` 仅允许出现在
   `scripts/harness_common.py`；消费方禁再定义（时间探测逻辑禁再现）。
2. **wiring**：53 文件映射表逐文件断言含 `from harness_common import`（或 hooks 桥 marker
   `ensure_scripts_path`）；旧 def 名残留 = 红。
3. **身份级 delegation**：抽样 import 消费模块，`mod.utc_now is harness_common.utc_now_z`。
4. **util 契约钉**：datetime tz-aware；Z 形 regex `^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$`；
   +00:00 形以 `+00:00` 结尾；B/C 字节等价断言（同一 datetime strftime vs isoformat+replace）。
5. 行为等价（提取前后同输入同输出）：B/C 等价断言 + 消费方调用面零改动（别名 import），
   输出字节不随提取漂移。

### 基线

- 守护测试现状：tests/ 对 utc_now 定义**零引用**（`git grep "def utc_now" tests/` 空）——
  与 issue 表 "enforcement today: none" 一致；无既有测试需改写 delegation。
- 批量委托后全量 `python -m pytest tests/ -q` 兜底（Windows 本地 7 个环境性基线失败已知，
  stash 对照甄别；CI Linux 绿为权威）。
- deploy_manifest：新增 scripts/harness_common.py 为资产面变更 → ext-scan → `--write` → `--verify`。

### 偏航记录（实现级，非 RECON-DEVIATION）

- 实数 53 vs issue 表 "~20"：口径差（定义复制 vs 同形状族），见对照表；工作对象不变。
- `def now_utc` 口径零命中（四说未含此名；grep 口径并入契约照跑）。
- kunglao-monitor.py 同文件双 def（utc_now + _utc_now_dt）分别映射 utc_now_z / utc_now。

### 全量测试甄别（5191 passed / 13 failed → 0 归因本卡）

全量 `pytest tests/ -q`：13 failed。甄别：
- 7 个 = 已知 Windows 环境性基线失败（stash 对照确认基线同红）。
- test_declaration_scan（harness_common.py 未登记）→ scripts/README.md 加行后绿。
- test_heartbeat_tick selfcheck_failure → scratch fixture 拷贝清单缺 harness_common.py
  （镜像 Family C 同 fixture 的 ws_layout/env_manifest 扩展先例）→ 扩清单后绿。
- deploy_lifecycle_783 ×3 + deploy_manifest_783 ×1 → 全量先于 deploy-manifest --write 跑的
  时序（新资产未收编态）→ --write 后单跑 14/16 全绿。
- 终态：本卡引入失败 0；守护测试 8/8 绿；`git grep` utc_now 定义复制定义面清零（唯一 util 除外）。
(refactor(863-g): 53 份 utc_now 定义复制全部委托单源)
