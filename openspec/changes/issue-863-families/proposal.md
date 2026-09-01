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
