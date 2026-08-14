# Phase 3.5 契约 — kunglao-init(workspace 初始化 + 防二次初始化)

`FROZEN @ phase-3.5, 变更条件: ① 先写一条 RED 测试证明现状不满足新契约 ② 改 contract.md + schemas/ ③ 同步回写 master 三份文档之一 ④ 同一 commit 内完成`

依据(层 1 master spec, 摘录带行号, 不转录):
- `kong-agent-module-design.md`(master): L25-26 store_atomic 原子写 / L31 store_claim(claim-register.yaml 读写,人类可审) / L48 record_event 幂等 / L56 Claim schema / L77-79 M0.4 错误处理 / L224 hooks 段幂等重建 / L448 kunglao.py 唯一编排入口、特殊操作用独立 CLI(kunglao-init/verify/eval...)
- `docs/design/archive/DESIGN.md` §7(工作树可执行 spec; #355: 原 `DESIGN.md` 移至 docs/design/archive/): L98 所有步幂等(存在且非空则跳过,不 clobber) / L104 0.3 hook 安装幂等 / L105 0.4 scaffold 幂等 / L110 0.9 claim 种子

## 1. 函数签名

`scripts/kunglao-init.py` — **独立 CLI, 非 kunglao.py 子命令**(module-design L448: "唯一编排入口; 不解析子命令(特殊操作用独立 CLI: kunglao-init/verify/eval...)")。

```
python kunglao-init.py <workspace> [--force] [--hooks-json <path>]
```

| 函数 | 签名 | 职责(对应 master 出处) |
|---|---|---|
| `main` | `main(argv=None) -> int` | argparse 入口, 调 run, sys.exit 包裹 |
| `run` | `run(ws: Path, force: bool=False, hooks_json: Path\|None=None) -> int` | 状态机入口: Phase 1 防重检查 → 续接 / --force 备份+重建 / 全新初始化 |
| `resume` | `resume(ws: Path, text: str) -> int` | 续接模式: 重算 state_hash, 漂移 → stderr WARNING(exit 0) |
| `initialize` | `initialize(ws: Path, hooks_json: Path\|None) -> int` | Phase 2 scaffold + seed + hooks 幂等部署; Phase 3 校验 |
| `atomic_write` | `atomic_write(path: Path, text: str) -> None` | temp → rename 原子写(module-design L25-26 store_atomic) |
| `compute_state_hash` | `compute_state_hash(ws: Path, register_text: str\|None=None) -> str` | sha256(claim-register 归一化内容 + facts/_INDEX.md 内容 + facts/ 文件清单按名排序拼接) |
| `normalize_marker` / `extract_hash` | `(text: str) -> str / str\|None` | [initialized] 标记的 state_hash 字段归一化/读取(自一致性哈希) |
| `seed_claims` | `seed_claims(sample: str) -> list[dict]` | 3-5 条样本级 seed: C-001 样本概览 / C-002 家族归属 / C-003 打包器(DESIGN L110 0.9) |
| `claim_register_text` | `claim_register_text(sample, sample_sha, state_hash) -> str` | claim-register.yaml 全文: [initialized] 标记头 + claims 体(Claim schema: module-design L56) |
| `detect_sample` | `detect_sample(ws: Path) -> tuple[str, str]` | bins/ 首文件(按名排序) → (文件名, sha256), 缺失 → ("unknown","") |
| `scaffold` | `scaffold(ws: Path) -> list[Path]` | 建 facts/ blockers/ runs/ + analysis_state.txt / global_plan.txt / claim_deps.yaml / facts/_INDEX.md / task_spec_snapshot.yaml; 存在且非空则跳过(DESIGN L105, L98) |
| `deploy_hooks` | `deploy_hooks(ws: Path, hooks_json: Path\|None) -> dict` | hooks 幂等部署(E-init.2, DESIGN L104); 目标选择见 §2 |
| `_patch_settings` | `_patch_settings(path: Path) -> int` | 合并 hooks 段入 settings.json(保其他键), 返回新增条数 |
| `_ensure` | `_ensure(entries, matcher, hook_file, hook_dir) -> tuple[list, bool]` | 同 matcher 已有同名 hook 命令 → 跳过(幂等); 否则追加 |
| `backup_register` | `backup_register(path: Path) -> Path` | --force 重建前备份: `claim-register.yaml.bak-<ts>`(E-init.4) |

错误处理(module-design L77-79): 读失败不崩溃(缺文件走分支); settings.json 解析失败 → 显式 RuntimeError; 写走 atomic_write(L25)。

## 2. 输出

**状态文件 `claim-register.yaml`(module-design L31: 人类可审)**: 首行注释含 `[initialized]` 标记 + `state_hash=<hex>` + `seeds=N` + `sample=<name>`; 体为 seed claims(id/status/boundary_type/evidence_tier_attempted/promotion_attempts/depends_on, 对应 L56 Claim schema, 附 title 行)。

**stdout(机器可读, 每条一行)**:
- 全新初始化: `kunglao-init: initialized <ws> (seed_claims=3 sample=<name>)` + `kunglao-init: state_hash=<hex>` + hooks 行(见下)
- 续接模式: `kunglao-init: resume — <ws> already initialized`(exit 0)
- --force: `kunglao-init: --force backup -> <backup-path>`
- hooks: 部署 → `kunglao-init: hooks -> <target> (<n> entries, idempotent)`; 跳过 → `kunglao-init: hooks skipped — <reason>`

**stderr**: 漂移 → `kunglao-init: WARNING state drift detected (recorded <old>, computed <new>) — external edits present`(含 "drift"/"warn", 测试断言点); 校验失败 → `FATAL`。

**exit code**: 0 = 成功(含续接/漂移告警后继续); 2 = Phase 3 校验失败(标记缺失或 seed < 3)。

**hooks 部署边界(硬约束)**: 绝不写生产 `~/.claude/settings.json`。目标仅: ① `--hooks-json <path>` 指定副本(不存在则创建); ② `<workspace>/.claude/settings.json`(若存在); 两者皆无 → 跳过并说明。条目格式与 hook_activation.py 一致:`{"type":"command","command":"python <hooks-dir>/worker_budget.py"}`(POSIX 路径, PreToolUse+PostToolUse matcher=Agent, DESIGN L104)。

## 3. 状态机

```
run(ws):
  reg = ws/claim-register.yaml
  ├─ reg 存在 且 非 --force:
  │    └─ 含 [initialized] → resume(ws, text)        # Phase 1 存在性检查
  │         ├─ extract state_hash → 重算 compute_state_hash(ws)
  │         ├─ 不相等 → stderr WARNING drift(不静默, module-design L224 精神: 检测→告警)
  │         └─ 输出 resume → exit 0(不触碰任何文件, seed 不重复)
  ├─ --force 且 reg 存在 → backup_register() → 输出备份路径
  └─ initialize(ws, hooks_json)                      # Phase 2 全新初始化
       ├─ scaffold(幂等: 存在且非空跳过, DESIGN L98/L105)
       ├─ detect_sample(bins/ 首文件)
       ├─ claim-register 草案(空 hash) → compute_state_hash → 写 [initialized] 标记(自一致)
       ├─ deploy_hooks(幂等, DESIGN L104)
       └─ Phase 3 校验: 标记存在 + seed 计数 ≥ 3 → exit 0 / 失败 → exit 2
```

四条路径:
1. **首次**: scaffold → 写 seed 注册表(3 条)+ 标记 → hooks(有目标则部署) → exit 0
2. **续接**: 标记命中 → 重算哈希比对 → 无漂移 resume / 有漂移 WARNING 后仍 resume → exit 0, 注册表逐字节不变
3. **漂移**: 外部编辑 claim-register 后重跑 → 归一化哈希不匹配 → stderr 含 "drift"/"warn", exit 0(不覆盖)
4. **--force**: 先 `claim-register*.bak*` 备份 → 重建注册表(新 state_hash)→ hooks 幂等(0 新增)→ exit 0

## 4. 测试点(tests/test_kunglao_init.py)

| 测试 | 判据(E-init) | 覆盖路径 |
|---|---|---|
| `test_kunglao_init_script_exists` | 文件存在可运行 | — |
| `test_second_run_resumes` | 首次 `[initialized]` 标记 + seed 写入; 二次运行续接且 `id: C-` 计数不变 | 路径 1→2 |
| `test_hooks_idempotent` | 重跑不重复部署 hooks(未部署则 skip 放行) | 路径 2(部署目标缺省时 skip) |
| `test_state_hash_drift_warns` | 改注册表后重跑输出含 "drift"/"warn" | 路径 3 |
| `test_force_backs_up_first` | --force 重建前生成 `claim-register*.bak*` | 路径 4 |

## 5. 完成判据

- [ ] `python -m pytest -q -p no:cacheprovider`(kunglao-agent/ 下): 5 个 kunglao-init 测试全过(含设计允许的 skip), 原有 138 通过用例零回归
- [ ] 状态机四路径(首次/续接/漂移/--force)行为与 §3 一致, 漂移告警含 "drift"/"warn"
- [ ] state_hash 口径 = sha256(claim-register 归一化 + facts/_INDEX.md + facts/ 文件清单按名排序拼接), 自一致性(写标记后重算不变)
- [ ] hooks 绝不写 `~/.claude/settings.json`; `--hooks-json` 副本与 workspace `.claude/settings.json` 幂等合并
- [ ] 不触碰: bins/ 二进制内容(只读文件名/哈希)、生产 settings.json、hooks/ 目录
