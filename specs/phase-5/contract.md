# Phase 5 契约 — M3 VERIFY / M4 RECORD / M5 MONITOR (Track E)

来源文档(冻结源, 引文带行号):
- `D:/works/samples/2026-07-01/malware-analysis-workspace/.research-tree-alignment/kong-agent-module-design.md`
  - §M0.2 签名 L40-50; M0.3 Event schema L53-72; M0.4 错误处理 L75-79; M0.5 测试点 L81-85
  - §M3 全部 L236-306(M3.1 L238-246; M3.2 L248-268; M3.3 L270-280; M3.4 L282-293; M3.5 L295-299; M3.6 L301-305)
  - §M4 全部 L309-362(M4.1 L311-319; M4.2 L321-333; M4.3 L335-341; M4.4 L343-349; M4.5 L351-355; M4.6 L357-361)
  - §M5 全部 L365-432(M5.1 L367-377; M5.2 L379-394; M5.3 L396-406; M5.4 L408-420; M5.5 L422-426; M5.6 L428-432)
- 现成可复用(不改): `scripts/loop_state.py::reconcile`(TEMP mtime → loop-state, L82-94)、`scripts/convergence_health.py::assess`(L170-233)、`scripts/active_intervention.py::find_help_requests/find_responses`、`scripts/backtrack_gate.py::parse_status/parse_backtrack`(L38-60)、`hooks/worker_budget.py` maker-checker 判据(L268/L282-319)、`scripts/hook_activation.py` heartbeat 注册(`runs/.heartbeat.json` `last_tick_ts`, L195-235)

FROZEN @ phase-5, 变更条件: ① 先写一条 RED 测试证明现状不满足新契约 ② 改 contract.md + schemas/ ③ 同步回写 master 三份文档之一 ④ 同一 commit 内完成

---

## 1. 函数签名(冻结, 原文带行号)

### M3 VERIFY(§M3.2 L248-268)

```python
def l1_mechanical(fact: Fact, fixture: Path) -> Verdict:
    """parse_reproduce → run(只读白名单) → sha256 比对 expected → PASS/FAIL (L251)"""

def l2_redteam(claim_id: str, ws: Path) -> RedteamVerdict:
    """派发 kunglao-redteam(独立 subagent, BLIND) (L254)
    约束: 不看 facts/F<NNN>/notes/worker-status; 独立推导; 自证先于对比;
          DIFF 每分歧; 五角度; plan-to-execute; self-consistency 多路径
    → CONFIRMED | REFUTED | UNVERIFIED-WITH-GAP"""

def lane_scheduler(facts: list[Fact], refutability: DepGraph) -> list[list[Fact]]:  # 本阶段不落地

def anchor_check(verdict: Verdict) -> bool:
    """PASS 必须带 anchors(原始字节位置 + 命令 + expected/actual); 无锚不提升 (L263)"""

def verify(ws: Path, fact_id: str) -> VerifyOutput:
    """L1 → 若 PASS 且需语义 → L2 → anchor_check → 写 runs/verify-<ts>.json (L266)"""
```

### M4 RECORD(§M4.2 L321-333)

```python
def record_event(ws: Path, event: Event) -> int:
    """event_id = sha256(event_type+payload); 幂等(重复返回已有 seq); atomic_append (L325)"""

def read_events(ws: Path, event_type: str | None) -> list[Event]        # L49 (M0.2)

def reconciler(ws: Path, n_rounds: int = 3) -> bool:                    # 本阶段不落地(E5.2 另测)
    """账本回放为 progress.txt/analysis_state.txt append (L328)"""

def summary_aggregator(worker_result: SummaryOfWork) -> dict:           # 本阶段不落地

def claim_migrator(ws: Path, claim_id: str, new_status: str, actor: str) -> tuple[bool, str]:  # 契约空白
    """claim 状态迁移(合法性检查); 非 orchestrator 写 terminal → (False, reason)"""
```

### M5 MONITOR(§M5.2 L379-394)

```python
def heartbeat_check(ws: Path) -> tuple[bool, str]:
    """查 tick_ts(< 35min) → alive/STALE; 不查 activity_ts (L382)"""

def loop_reconcile(ws: Path) -> LoopState:
    """TEMP mtime → loop-state.json + 事件 diff (L385)"""

def health_check(ws: Path) -> dict:
    """ledger 轨迹 → HEALTHY/STALLED/SPINNING + flatline/churn 指标 (L388)"""

def tick(ws: Path) -> TickOutput:
    """组合: heartbeat→reconcile→agent_watch→help_watch→stuck_watch→health (L391)
    输出: 一句话状态 + 下一步建议(LLM 只读)"""
```

### 落地映射(契约空白决策)

| 设计签名 | 本阶段落地 | 备注 |
|---|---|---|
| 文件布局 | `scripts/kunglao_verify.py` + `scripts/kunglao-verify.py`(薄包装); 同款 `kunglao_record.py`/`kunglao-record.py`; `kunglao-monitor.py` 自含 | frozen test 用 `from kunglao_verify import anchor_check` / `from kunglao_record import ...` 直接导入, 连字符文件名不可 import → 逻辑放下划线模块, 连字符文件为 CLI 入口(同 pythonpath 解析) |
| `lane_scheduler` | **不新建** — fact 依赖 lane 并行是编排层职责, 本阶段 CLI 一次验证一个 fact | M3.1 L243 子模块, 无测试背书不落地 |
| `reconciler` / `summary_aggregator` | **不新建** — E5.2(Migrate)与 digest 聚合留后续阶段 | M4.2 L328/L331; 阶段判据 E5.1/E5.3 覆盖 Expand/Contract |
| `claim_migrator` 返回 | `tuple[bool, str]`(ok, reason) — 契约空白 | 落地: register 状态改写 + terminal 迁移记 ledger 事件 |
| `l2_redteam` 真实派发 | 封装接口 `l2_redteam(claim_id, ws, dispatcher=None)`; 未注入 dispatcher → `NOT-RUN` + gap 说明 | 真实派发 = orchestrator 用 `build_redteam_prompt`(BLIND, 无 maker 上下文) 派发 kunglao-redteam subagent; 测试注入 stub |
| `verify` 落盘文件名 | `runs/verify-<fact_id>-<ts>.json`(ts 无冒号) | M3.2 L266 "verify-<ts>.json" — 加 fact_id 防同秒多 fact 覆盖(契约空白) |
| L1 sha256 口径 | `actual_sha256 = sha256(stdout.rstrip())`; expected 为 64-hex 时直接比对, 否则 `sha256(expected.strip())` | 契约空白; reproduce 输出尾部换行归一化 |
| reproduce 解析 | `shlex.split` 首 token ∈ 只读白名单 → 原样 argv(python→sys.executable); 否则整串按 `python -c` 执行 | M3.2 L251 "parse reproduce"; 白名单: python/python3/py/xxd/od/hexdump/cat/strings/file/grep/egrep/fgrep/sed/awk/sha256sum/md5sum/sha1sum/wc/head/tail/sort/uniq; python 路径再拒绝写操作(`open('w')`/`.write(`/`os.remove` 等), shell 路径拒绝重定向(`>`/`>>`/`| tee`) |
| `needs_semantic` | frontmatter `needs_semantic: true` 或 `boundary_type: subjective_interpretation` → True, 默认 False | M3.4 L288 "若需语义" 契约空白 |
| claim_id 解析 | frontmatter `claim_id` 优先; 缺失 → `C-UNKNOWN`(schema pattern 允许) | 契约空白 |
| 账本路径 | `<ws>/ledger.jsonl` | M4.1 L315 "ledger.jsonl 幂等写入" |
| `checksum` | `sha256(整条除 checksum 外 canonical JSON)` | M0.3 L68 dataclass 字段, 口径契约空白 |
| 幂等键 | `event_id = sha256(event_type + canonical(payload))`, canonical = `json.dumps(sort_keys, separators=(",",":"))` | M0.3 L67 原文 |
| DEFERRED 迁移事件 | 无专属 event_type → 仅 register 更新, 不记 ledger | M4.3 L337-340 枚举无 claim_deferred(契约空白) |
| `heartbeat_check` 路径 | `runs/.heartbeat.json` `last_tick_ts`, 阈值 35min | 与 worker_budget.check_heartbeat_alive(L505-559) 同源同阈值 |
| `loop_reconcile` | 复用 `loop_state.reconcile`; 上一快照 `runs/loop-state.json` diff → `gone_events`; 每 tick 重写快照 | M5.2 L385; M5.5 L427 "无快照 → 全当 NEW" |
| `stuck_watch` | in_progress 且 ≥20min 无有效 backtrack(`continue/retry_different/escalate/redispatch`) | 复用 backtrack_gate.parse_status/parse_backtrack, 阈值同默认 |
| `help_watch` | 未响应 help_request 的 worker-status 文件(响应按 claim_id 匹配 heartbeat_actions.md) | 复用 active_intervention.find_help_requests/find_responses |
| `health_check` | 复用 convergence_health.assess; `NO_DATA` → `HEALTHY`(raw 保留) | tick schema 枚举无 NO_DATA(契约空白映射) |
| `next` | 机械链: STALE 心跳 → re-register; SPINNING/STALLED → 健康 action; help → 响应; stuck → backtrack; gone → 对账; 空闲 → converged-check | M5.4 L418 "机械推断下一步" |

---

## 2. 输出 schema 引用

- 冻结结构: `schemas/verify-output.json`(M3.3 L272-280 逐字段)
  - 必需 7 字段: `fact_id` / `claim_id` / `l1{verdict, actual_sha256, cmd}` / `l2{verdict, gaps}` / `anchors[{byte_offset, cmd, expected}]` / `overall`
  - `l1.verdict` ∈ PASS|FAIL; `l2.verdict` ∈ CONFIRMED|REFUTED|UNVERIFIED-WITH-GAP|NOT-RUN; `overall` ∈ VERIFIED|REJECTED|PARTIAL
  - 附加字段(additionalProperties 允许, 非冻结必需): `l1.expected_sha256`, `l1.detail`
- 冻结结构: `schemas/tick-output.json`(M5.3 L398-405 逐字段)
  - 必需 9 字段: `ts` / `heartbeat`(alive|STALE) / `active_workers` / `stale_agents` / `gone_events` / `help_requests` / `stuck` / `health`(HEALTHY|STALLED|SPINNING) / `next`
  - 附加字段: `heartbeat_detail`, `health_detail`
- 冻结结构: `schemas/event.json`(M0.3 L66-72 逐字段)
  - 必需 6 字段: `seq` / `event_id` / `source_module` / `event_type`(枚举 7 值) / `payload` / `checksum`; 附加 `ts`(本实现附加, 非 M0.3 必需)

## 3. 状态机(原文流程)

### M3.4 verify(L285-293)

```
verify(ws, fact_id):
  v1 = l1_mechanical(fact, fixture)
  if v1 == FAIL: return REJECTED            # 不进入 L2
  if not needs_semantic(fact): return VERIFIED(v1)
  v2 = l2_redteam(claim_id, ws)             # kunglao-redteam 独立派发
  if v2 == CONFIRMED AND anchor_check: return VERIFIED
  if v2 == REFUTED: return REJECTED
  return PARTIAL(UNVERIFIED-WITH-GAP)
```

### M4.4 Expand→Migrate→Contract(L345-349)

```
Expand:   账本旁路写入, 旧 CLI 照旧(零行为变更)   ← 本阶段(E5.1: verify/record 旁路)
Migrate:  reconciler 回放旧通道, N=3 轮 checksum 零漂移 → 读者切账本   ← 后续阶段
Contract: 旧通道降级只读                           ← 本阶段判据 E5.3(claim_migrator 挡非 orchestrator 写 terminal)
```

### M5.4 tick(L411-420)

```
tick(ws):
  hb = heartbeat_check(ws)
  ls = loop_reconcile(ws)                    # 更新 loop-state + 事件
  aw = agent_watch(ws)                       # NEW/GONE/STALE(含于 ls: active/stale/gone)
  hi = help_watch(ws)                        # 未响应 help_request
  st = stuck_watch(ws)                       # 卡死 worker
  hl = health_check(ws)                      # 轨迹健康
  next = decide_next(hb, ls, hi, st, hl)     # 机械推断下一步
  return TickOutput
```

## 4. 测试点(M3.6 L301-305 / M4.6 L357-361 / M5.6 L428-432 + 本阶段 RED 清单)

| 测试点 | 断言 | 文件 |
|---|---|---|
| 判别力(L303) | 已知 PROVEN fact → PASS; 篡改 expected 的假 fact → FAIL; 输出过 verify-output.json | tests/test_verify_record_monitor.py::test_known_fact_pass_fake_fact_fail |
| anchor_check(L305) | 无锚 PASS → 拒提升(anchor_check → False) | 同上::test_anchor_check_blocks_no_anchor |
| 幂等(L359) | 同 event 两次 record → 1 条, seq 相同 | 同上::test_ledger_idempotent_same_event_once |
| TickOutput schema | heartbeat/active_workers/health/next 字段过 tick-output.json | 同上::test_monitor_tick_output_schema |
| claim 迁移(L361) | 非 orchestrator 写 terminal → 拒 | 同上::test_claim_migrator_blocks_worker_terminal |
| 盲验证(L304) | 派发 prompt 不含 maker 上下文(`prompt_is_blind` 机械断言, 供 stub 测试注入) | 实现于 kunglao_verify.build_redteam_prompt / prompt_is_blind |
| L1 超时/工具缺失(L297) | 超时/缺失 → FAIL(不降级为 PASS) | 实现于 run_reproduce(脚本级, 无独立测试) |

## 5. 完成判据

1. 全部新增测试绿 + 全量回归绿(`python -m pytest -q -p no:cacheprovider`): 本阶段 5 条 + 原 143 条不回归(test_kunglao_init 4P+1S 在)
2. `schemas/verify-output.json` / `schemas/tick-output.json` 对 kunglao-verify / kunglao-monitor 输出通过 jsonschema 校验
3. E5.1: verify/record 为旁路新 CLI(kunglao.py 等旧入口零改动); E5.2 reconciler 留后续; E5.3 旧通道只读由 claim_migrator maker-checker 门禁体现
4. 约束: 不碰 SKILL.md/references/hooks/kunglao.py/convergence_check.py/priority.py/priority_ratio.py/method_router.py/kunglao-decide.py/test_kunglao_init.py/test_contract_docs.py/test_suite_health.py/tools/; 不 git commit
