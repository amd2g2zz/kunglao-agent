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
