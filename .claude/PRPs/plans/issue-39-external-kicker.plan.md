> **拆分状态（2026-08-11）**：本文件原为 #39 三防线完整设计（research-grounded, F1-F6）。#39 经 deep-research（`wf_5c50b792-f7c`）后 scope 扩展过大，已拆为 parent **#39** + 子 issue **#43 / #44 / #45**。
>
> **#39 本身实际 scope** = 死断点 + kick + 坑7（项目级 hooks 重注册）+ 会话竞争（Task 2 的 `heartbeat_stale` / `active_session` / `ledger_stalled` / `_write_takeover` / `ensure_project_hooks` / `kick` / `main` + 简化版 `build_resume_prompt` + Task 4 wire_up）——**不含** drift / state_anchor / fired-predicate resume。
>
> 本文件保留作**三防线总设计参考**（完整 research + patterns + 全函数代码）。各子 issue 的独立 plan：
> - #43 drift detection → `issue-43-drift-detection.plan.md`
> - #44 state_anchor hook（治本层）→ `issue-44-state-anchor-hook.plan.md`
> - #45 fired-predicate resume → `issue-45-fired-predicate-resume.plan.md`
>
> **函数 → issue 映射**（Task 2/3 代码）：
> - `heartbeat_stale` / `active_session` / `ledger_stalled` / `_write_takeover` / `ensure_project_hooks`（不含 state_anchor 行）/ `kick` / `main` / 简化版 `build_resume_prompt` → **#39**
> - `_state_signature` / `signature_rotation` / `workers_progressing` / `drift_detected` + `should_kick` drift 分支 → **#43**
> - `hooks/state_anchor.py`（Task 3）+ `ensure_project_hooks` 的 state_anchor 注册行 → **#44**
> - `build_resume_prompt`（升级为 fired-predicate 版）→ **#45**
>
> 实施序：`#39 → (#45 ∥ #43) → #44`。

---

# Plan: #39 external kicker + state re-anchor — 死 / 漂移（呆）三防线

> **Research-grounded redesign** (2026-08-11). 上一版（detect 呆 → restart）被用户纠正为"想简单了"：呆的根因不是会话空转，是 **LLM 随 action-observation trajectory 增长丢失精确状态表示**（context rot + execution drift）。deep-research（107 agents, 18 confirmed findings）验证后重构为三层。证据见 `research/long-horizon-agent-failure.md`。

## Summary
心跳/循环依赖 Claude Code 会话存活。**三类断点**（research F1–F5）：
- **死（dead）**：会话没了/cron 断了 → 心跳 stale（>35min）→ gate 全 REJECT。*检出信号 = 时间*（heartbeat stale）。
- **漂移（drift / 活呆）**：会话活着、cron 在 tick、ledger 在写，**但状态签名连续 ≥3 轮不变**——LLM 在过期心智模型上演算（context rot，F2/F3）。*检出信号 = 状态签名*（非时间——时间法检不出活呆，F2 "非线性退化"）。
- **假完成（premature termination）**：LLM 自报"done"不是事件（F4 "an LLM saying done is not an event"）——kicker 重启的 resume prompt 必须基于 **fired predicates**（ledger/facts/claims），不是旧会话自述。

**三层防线**（对应 F5 "know / change / commit / forget / recover" 运行时治理）：
1. **检测（detect）**：`external_kicker.should_kick()` = 死（heartbeat stale + 无活跃会话）**或** 漂移（signature rotation ≥3 且非 workers-progressing）**或** ledger 时间陈旧（>25min 无新行，死呆兜底）。
2. **预防（prevent, 新）**：`hooks/state_anchor.py` PostToolUse（Agent）——每次 worker 完成/任意 Agent 调用注入一行紧凑状态签名 + 漂移警告，机械重锚 LLM 的状态表示（不杀会话）。**这是"治本"层**：context rot 的对策是持续注入外部真相，而非等漂移再重启。
3. **恢复（recover）**：`external_kicker.kick()` 启动 fresh `claude -p`，prompt = **fired-predicate 状态摘要**（decision / open claims / partial facts / workers / blockers / facts_total）+ heartbeat_loop_prompt 输出。takeover 标记防双会话；ensure_project_hooks 重注册到项目级 settings（坑 7 修正，保留 env 段 secret）。

阈值层级：ROTATION_WINDOW 3 行 ≈ 15min → 漂移检出 → hook 重锚；DRIFT_ESCALATE 6 行 ≈ 30min → kick；TICK 15min；LEDGER_STALL 25min；HEARTBEAT_STALE 35min。

## User Story
作为 kunglao-agent 的 orchestrator，我希望循环不依赖我的会话存活，且**trajectory 增长导致的状态表示丢失能被机械检出（漂移信号）+ 在会话内被重锚（hook 注入）+ 无法恢复时由外部重启并以 fired predicates 续接**——这样长 horizon 任务下不会因 context rot 静默失效。

## Problem → Solution
**根因（research F2/F3）**：LLM 短链任务表现好，但 action-observation trajectory 增长 → context rot（Anthropic：token 越多召回越差）+ execution drift（SED：α≥1 自放大，step-local-invisible）。**呆不是会话坏，是 LLM 在过期状态上演算**——心跳 fresh、ledger 在写，但状态零推进。时间陈旧法（>25min 无行）只检"死呆"（会话不 tick）；**"活呆"（tick 但漂移）只有状态签名旋转法能检**。

**不重写 spawn subagent**：派发层没坏——漂移 = orchestrator 用过期状态演算，spawn worker 救不了"没有人基于真状态派发"。**re-anchor（hook 注入）+ recover（kicker 重启 fired-predicate 续接）**才是治本+兜底。

**三防线分工**（F5 运行时治理映射）：
- `state_anchor.py`（prevent）= **"model may know"**：每 Agent 调用注入紧凑状态签名 → 持续刷新 LLM 的工作状态表示，对抗 context rot。这是核心新增——之前的 kunglao 有 detect（convergence_health）和 commit（ledger append-only），缺 "forget/refresh" 的运行时函数。
- `external_kicker.detect`（detect）= **"may change"** 判定：signature rotation + 死信号 → 决定是否需要更强干预。
- `external_kicker.kick`（recover）= **"recover"**：无法在会话内重锚时，fresh 会话以 fired predicates 续接（F4：不信任旧会话自述）。

## Metadata
- **Complexity**: Large（OS 集成 + 会话管理 + 三层判定 + 漂移检测 + hook 重锚 + 竞态处理）
- **Source PRD**: GitHub issue #39（无独立 PRD）
- **PRD Phase**: N/A（standalone）
- **Estimated Files**: 6（scripts/external_kicker.py、scripts/test_external_kicker.py、hooks/state_anchor.py、scripts/test_state_anchor.py、scripts/wire_up_settings.py、docs/SKILL.md 或 references/）
- **Research**: `research/long-horizon-agent-failure.md`（18 verified findings, 7 refuted, 4 caveats）

---

## UX Design

### Before
```
[Claude 会话活着 + 推进] → cron → heartbeat tick → 循环前进
[会话关闭/崩溃]          → 心跳 stale → gate 全 REJECT（死断点）
[会话活着但漂移/活呆]    → 心跳 fresh（tick 在跑、ledger 在写）
                           → 状态签名连续不变 → 无检测 → context rot 静默失效
[kicker 重启]            → prompt = 泛泛"Phase 0 纯重算"→ 可能继承旧会话自述的漂移状态
```

### After
```
[OS schtasks/cron 每 15min] + [每次 Agent 调用]
  ┌─ LAYER 1: PREVENT (hooks/state_anchor.py, PostToolUse Agent) ───────────┐
  │  每次调用注入: [state-anchor] decision=X open=[..] facts=N workers=W    │
  │  漂移时追加:   ⚠ drift: 3 轮状态签名不变 → re-read 8 文件再派发          │
  │  → 机械重锚 LLM 状态表示（对抗 context rot，治本，不杀会话）            │
  └─────────────────────────────────────────────────────────────────────────┘
  ┌─ LAYER 2: DETECT (external_kicker.should_kick) ─────────────────────────┐
  │  死:   heartbeat stale(>35min) + 无活跃会话                             │
  │  漂移: ledger signature 连续 ≥3 行相同 + 非 workers-progressing          │
  │  死呆: ledger 时间陈旧(>25min 无新行) + open claims>0                    │
  └─────────────────────────────────────────────────────────────────────────┘
  ┌─ LAYER 3: RECOVER (external_kicker.kick) ───────────────────────────────┐
  │  触发: 死 或 漂移持续 ≥6 行(≈30min)                                      │
  │  1. _write_takeover() 原子写 .kicker-takeover.json（防双会话）           │
  │  2. resume_prompt = fired-predicate 状态摘要（ledger 末行 + open claims  │
  │     + partial facts + workers + blockers + facts_total）+ heartbeat_     │
  │     loop_prompt 输出。NOT 旧会话自述（F4）                              │
  │  3. ensure_project_hooks() → 项目级 settings（保留 env 段，坑 7）       │
  │  4. 启动 fresh `claude -p <resume_prompt>`（headless）                  │
  └─────────────────────────────────────────────────────────────────────────┘
  阈值: ROTATION 3 行(~15min)→hook 重锚 < ESCALATE 6 行(~30min)→kick
       < TICK 15 < STALL 25 < STALE 35
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| 状态精确性 | 长 trajectory 漂移（无约束） | hook 每调用注入签名 + 漂移警告（机械强制） | 根因修复：F5 "model may know" |
| 呆检测 | 时间陈旧（漏活呆） | signature rotation（F2/F3 非线性） | 时间仅兜底死呆 |
| 死检测 | heartbeat stale | 不变 | — |
| kick prompt | 泛泛"Phase 0 重算" | fired-predicate 摘要（F4） | 不信任旧会话自述 |
| wire-up | user 级（坑 7，0 生效） | 项目级（保留 env 段） | 坑 7 修正 |
| 会话仲裁 | 无 | takeover 标记（恰一个接管） | 防旧会话复活双会话 |

---

## Research Grounding（cited; full notes in `research/long-horizon-agent-failure.md`）
| 设计决策 | Evidence | Confidence | Caveat |
|---|---|---|---|
| 漂移用 signature 而非时间检测 | F2 非线性退化 + F3 SED step-local-invisible | MEDIUM | F2/F3 单源/中刊 |
| hook 注入重锚（治本） | F5 "explicit runtime manage what model may know" + Anthropic context rot | MEDIUM | F5 是架构立场非实测 |
| resume prompt 用 fired predicates | F4 "LLM saying done is not an event" + commitment store 切除 0→1 | MEDIUM | F4 自身实验 null |
| 修 harness 而非换模型 | F1 72.5% process-level | HIGH | F1 未同行评议 |
| 检测器当 best-evidence 信号 | F6 trajectory attribution immature | HIGH | 阈值需可调 |
| **不**引用"state tracking 提升 9pp" | refuted 0-3（zenodo 伪造） | — | 任何未引数字存疑 |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `research/long-horizon-agent-failure.md` | 全文 | 设计证据来源（F1–F6 + refuted + caveats） |
| P0 | `scripts/heartbeat_loop_prompt.py` | 全文 (65 行) | stdout = cron prompt 内容（kicker resume prompt 复用） |
| P0 | `scripts/wire_up_settings.py` | 全文 (75 行) | :20 写 user 级（坑 7）——ensure_project_hooks 须指项目级 + 保留 env |
| P0 | `scripts/hook_activation.py` | 87-165, 186-222 | read_state/is_active_strict（default-inactive + TTL）、renew |
| P0 | `scripts/heartbeat.py` | 15-58 | heartbeat 字段 + 35-min stale 判定 |
| P0 | `scripts/convergence_check.py` | 123-130, 322-344 | `_open_claims`（排除语义）+ `_append_ledger`（snapshot 字段 = signature 源） |
| P0 | `scripts/convergence_health.py` | 40, 68-81 | `_read_ledger` 容错读法（signature 检测镜像） |
| P0 | `hooks/worker_pulse.py` | 104-179 | `_build_pulse` flags + main() PostToolUse additionalContext 注入（**state_anchor 镜像此模式**） |
| P0 | `scripts/backtrack_gate.py` | 64-128 | stuck 检测语义——`workers_progressing` 的 mtime 阈值复用 20min |
| P1 | `hooks/heartbeat_touch.py` | 43-49 | activity_ts 更新 + tmp→replace 原子写 |
| P1 | `scripts/kunglao_record.py` | 78-86 | _atomic_write（全仓无锁惯例） |
| P2 | `hooks/worker_budget.py` | 52-72 | _resolve_workspace/_kunglao_active（kicker 判活跃会话可复用） |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| schtasks（Windows） | 本地系统文档 | `/SC MINUTE /MO 15` 每 15min |
| claude CLI headless | Claude Code 本机 | `claude -p "<prompt>"` 无交互 |
| Anthropic harness guidance | anthropic.com/engineering/effective-harnesses-for-long-running-agents | heartbeat/checkpoint pulse 检 silent hang + premature termination；objective-tracking artifact 防"declare done" |

---

## Patterns to Mirror

### PROMPT_SOURCE（heartbeat_loop_prompt 输出 — scripts/heartbeat_loop_prompt.py:31-46）
```python
/loop {interval} kunglao-agent 心跳（自注册 + 监视 + 校验一体）：
[启动动作]
python {h} {ws} --heartbeat-on
[每 tick 监视]
0. python {tk} {ws}
...
```
// kicker resume_prompt 末尾拼接此输出

### LEDGER_SIGNATURE（snapshot 字段 — scripts/convergence_check.py:329-339 逐字）
```python
        entry = {
            "ts": utc_now().isoformat(timespec="seconds"),
            "decision": d["decision"],
            "open_count": d["open_count"],
            "open_ids": [c["id"] for c in d["open_claims"]],
            "partial_count": d["partial_count"],
            "active_workers": d["active_workers"],
            "blockers": d["active_blockers"],
            "facts_total": _count_facts(workspace),
        }
```
// `state_signature(row)` = tuple of (decision, open_ids, partial_count, active_workers, blockers, facts_total) — **不含 ts**。连续 N 行 signature 相同 = 漂移。

### LEDGER_READ（容错逐行读 — scripts/convergence_health.py:68-81 逐字）
```python
def _read_ledger(workspace: Path):
    p = workspace / LEDGER_NAME
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
```
// `signature_rotation(ws)` 镜像此读法，取末 N 行比 signature

### PULSE_INJECT（PostToolUse additionalContext — hooks/worker_pulse.py:173-178 逐字）
```python
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": pulse,
        }
    }, ensure_ascii=False))
    return 0
```
// `state_anchor.py` 完整镜像此注入模式（new hook）

### STALE_WORKERS_MTIME（workers_progressing 判定 — scripts/backtrack_gate.py:64-128 语义）
```python
# in-progress status 文件 mtime 距今 < STUCK_MINUTES(20) → progressing
# 用于漂移 false-positive 豁免：SATURATED + workers 在跑 = 合法等待，非漂移
```
// `workers_progressing(ws)` 复用 20min mtime 阈值（与 backtrack_gate/#38 一致）

### ATOMIC_WRITE（tmp→replace — scripts/kunglao_record.py:78-86 逐字）
```python
def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    tmp.replace(path)
```
// takeover 标记 + 项目级 settings 写都用原子写

### ACTIVE_STRICT（is_active_strict — scripts/hook_activation.py:134-165）
`.hook_state.json` 存在 + 未过期 + active_hooks 非空 → 活跃会话。kicker 死分支跳过条件。

### OPEN_CLAIMS（_open_claims 语义 — scripts/convergence_check.py:123-130 逐字）
```python
def _open_claims(reg: dict):
    out = []
    for c in (reg.get("claims") or []):
        status = (c.get("status") or "UNKNOWN").upper()
        if status not in TERMINAL and status not in IN_PROGRESS_STATUSES:
            out.append({"id": c.get("id"), "status": status, "blocked": bool(c.get("blocked"))})
    return out
```
// `_has_open_claims` 镜像此排除语义（open>0 才判呆；无 open → 该收敛）

### STALE_CHECK（heartbeat_check — scripts/heartbeat.py:37-58）
`last_tick_ts` 距今 < 35 min → exit 0，否则 exit 1。

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `scripts/external_kicker.py` | CREATE | LAYER 2+3：死/漂移/死呆检出 + fired-predicate resume kick + takeover + 项目级 hooks 重注册 |
| `scripts/test_external_kicker.py` | CREATE | TDD RED 先写（含漂移检出 + fired-predicate resume 用例） |
| `hooks/state_anchor.py` | CREATE | **LAYER 1（治本）**：PostToolUse Agent 注入状态签名 + 漂移警告，机械重锚 |
| `scripts/test_state_anchor.py` | CREATE | TDD RED 先写（注入格式 + 漂移警告触发） |
| `scripts/wire_up_settings.py` | UPDATE | 加 `--settings <path>` 参数（默认 user 级不变；kicker 显式传项目级） |
| `docs/SKILL.md` 或 `references/` | UPDATE | 记录三防线 + schtasks 安装 + 坑 7 + F1–F5 证据映射 |

## NOT Building

- 不替代人工会话（kicker 是兜底，人仍可开）
- **不重写 spawn subagent**（派发层没坏；漂移 = 用过期状态演算，spawn 救不了"没人基于真状态派发"）
- 不做轨迹压缩/compaction（F5 "forget" 的完整实现超出 #39 范围；本计划用 hook 重锚近似）
- 不自动装 schtasks（`--install` 只打印命令）
- 不改 heartbeat 35-min / TTL 30-min / convergence_check / convergence_health 语义
- 不做多会话合并（只"恰一个接管"——takeover + active_session 跳过）
- 不把 secret 写进仓库（项目级 settings env 段保留在原文件，kicker 只读不拷）
- 不引用 refuted claim（"state tracking 提升 9pp" 是 zenodo 伪造——research refuted 0-3）

---

## Step-by-Step Tasks

### Task 1: RED — test_external_kicker.py + test_state_anchor.py
- **ACTION**: 先写测试（TDD RED），覆盖三防线：死/漂移/死呆检出 + signature rotation 重置 + workers-progressing 豁免 + fired-predicate resume + hook 注入格式
- **IMPLEMENT (test_external_kicker.py)**:
```python
"""Tests for #39 external kicker — dead / drift / stalled + fired-predicate resume (RED)."""
import json
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import external_kicker as ek


def _mk_ws(tmp_path) -> Path:
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    return ws

def _mk_heartbeat(ws, age_min=60):
    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - age_min * 60))
    (ws / 'runs' / '.heartbeat.json').write_text(
        json.dumps({"started_ts": ts, "interval_min": 5, "last_tick_ts": ts}), encoding="utf-8")

def _mk_ledger_rows(ws, signatures: list, age_min_last=1):
    """signatures: list of dicts (decision/open_ids/...) — 每条写一行，ts 全设近时（测漂移不靠时间）。
    age_min_last: 最后一行的 ts 距今分钟（测死呆用大值）。"""
    lines = []
    n = len(signatures)
    for i, sig in enumerate(signatures):
        age = age_min_last + (n - 1 - i)  # 行越早 age 越大
        ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - age * 60))
        row = {"ts": ts, **sig}
        lines.append(json.dumps(row))
    (ws / '.convergence_ledger.jsonl').write_text("\n".join(lines) + "\n", encoding="utf-8")

def _sig(decision="DISPATCH", open_ids=None, partial=0, workers=0, blockers=None, facts=5):
    return {"decision": decision, "open_ids": open_ids or ["C-1"], "open_count": len(open_ids or ["C-1"]),
            "partial_count": partial, "active_workers": workers, "blockers": blockers or [], "facts_total": facts}

def _mk_claims(ws, statuses):
    import yaml
    (ws / "claim-register.yaml").write_text(
        yaml.safe_dump({"claims": [{"id": f"C-{i}", "status": s} for i, s in enumerate(statuses)]},
                       allow_unicode=True, sort_keys=False), encoding="utf-8")


# ---- 死检出 ----

def test_kicker_detects_dead(tmp_path):
    ws = _mk_ws(tmp_path); _mk_heartbeat(ws, age_min=60)
    assert ek.should_kick(ws) is True

def test_kicker_active_session_skip_dead(tmp_path):
    ws = _mk_ws(tmp_path); _mk_heartbeat(ws, age_min=60)
    exp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() + 900))
    (ws / '.hook_state.json').write_text(
        json.dumps({"ts": exp, "expires_at": exp, "active_hooks": ["worker_pulse"]}), encoding="utf-8")
    assert ek.should_kick(ws) is False


# ---- 漂移检出（核心新增） ----

def test_drift_detected_3_identical_signatures(tmp_path):
    """3 行相同 signature（无 worker 推进）→ 漂移"""
    ws = _mk_ws(tmp_path)
    _mk_ledger_rows(ws, [_sig(), _sig(), _sig()])  # 连续 3 行相同
    _mk_claims(ws, ["OPEN"])
    assert ek.signature_rotation(ws) >= 3

def test_drift_not_detected_when_workers_progressing(tmp_path):
    """SATURATED + active_workers>0 且 worker-status 文件 mtime 新 → 合法等待，非漂移"""
    ws = _mk_ws(tmp_path)
    _mk_ledger_rows(ws, [_sig(workers=1), _sig(workers=1), _sig(workers=1)])
    (ws / 'runs' / 'worker-status-w1.md').write_text("## Status\nin-progress\n", encoding='utf-8')
    _mk_claims(ws, ["OPEN"])
    assert ek.workers_progressing(ws) is True
    assert ek.drift_detected(ws) is False  # 合法 SATURATED 等待（should_kick 在 escalate 阈值判）

def test_drift_resets_on_signature_change(tmp_path):
    """第 3 行 signature 变化（facts 增长）→ rotation 计数重置"""
    ws = _mk_ws(tmp_path)
    _mk_ledger_rows(ws, [_sig(facts=5), _sig(facts=5), _sig(facts=6)])  # 末行变了
    _mk_claims(ws, ["OPEN"])
    assert ek.signature_rotation(ws) < 3

def test_drift_below_threshold(tmp_path):
    """仅 2 行相同 → 不漂移（阈值 ROTATION_WINDOW=3）"""
    ws = _mk_ws(tmp_path)
    _mk_ledger_rows(ws, [_sig(), _sig()])
    _mk_claims(ws, ["OPEN"])
    assert ek.signature_rotation(ws) < 3


# ---- 死呆兜底（时间陈旧法） ----

def test_stalled_when_ledger_time_stale(tmp_path):
    """ledger 最后一行 >25min 且有 open claim → 死呆兜底"""
    ws = _mk_ws(tmp_path); _mk_heartbeat(ws, age_min=1)
    _mk_ledger_rows(ws, [_sig()], age_min_last=40)
    _mk_claims(ws, ["OPEN"])
    assert ek.ledger_stalled(ws) is True
    assert ek.should_kick(ws) is True

def test_no_open_claims_no_kick(tmp_path):
    """全终态 → 该收敛，不 kick"""
    ws = _mk_ws(tmp_path); _mk_heartbeat(ws, age_min=1)
    _mk_ledger_rows(ws, [_sig(open_ids=[]), _sig(open_ids=[]), _sig(open_ids=[])])
    _mk_claims(ws, ["PROVEN"])
    assert ek.should_kick(ws) is False

def test_should_kick_drift_below_escalate(tmp_path):
    """漂移 rotation ∈ [3,6) → should_kick False（只 hook 重锚，不 kick）——治本优先"""
    ws = _mk_ws(tmp_path); _mk_heartbeat(ws, age_min=1)
    rows = [_sig() for _ in range(4)]  # rotation=4 ∈ [3,6)
    _mk_ledger_rows(ws, rows)
    _mk_claims(ws, ["OPEN"])
    assert ek.signature_rotation(ws) >= 3
    assert ek.should_kick(ws) is False  # 4 < DRIFT_ESCALATE_ROWS(6)

def test_should_kick_drift_at_escalate(tmp_path):
    """漂移 rotation ≥6 → should_kick True"""
    ws = _mk_ws(tmp_path); _mk_heartbeat(ws, age_min=1)
    rows = [_sig() for _ in range(6)]
    _mk_ledger_rows(ws, rows)
    _mk_claims(ws, ["OPEN"])
    assert ek.should_kick(ws) is True


# ---- fired-predicate resume prompt（F4） ----

def test_resume_prompt_built_from_ledger_not_narrative(tmp_path):
    """resume prompt 含 ledger 末行 decision + open claims + facts_total（fired predicates），
    不含旧会话自述（无 narrative 字段）"""
    ws = _mk_ws(tmp_path)
    _mk_ledger_rows(ws, [_sig(decision="DISPATCH", open_ids=["C-7"], facts=12)])
    _mk_claims(ws, ["OPEN"])
    prompt = ek.build_resume_prompt(ws)
    assert "DISPATCH" in prompt          # 来自 ledger
    assert "C-7" in prompt               # open claim（fired predicate）
    assert "12" in prompt                # facts_total
    assert "narrative" not in prompt.lower()  # F4：不信任旧会话自述

def test_kicker_writes_takeover(tmp_path):
    ws = _mk_ws(tmp_path); ek._write_takeover(ws, "drift")
    data = json.loads((ws / '.kicker-takeover.json').read_text(encoding="utf-8"))
    assert data["reason"] == "drift"

def test_register_project_settings_keeps_env(tmp_path):
    proj = tmp_path / '.claude'; proj.mkdir()
    (proj / 'settings.json').write_text(
        json.dumps({"env": {"VMR_API_KEY": "redacted-secret", "KEEP": "1"}, "hooks": {}}, indent=2),
        encoding="utf-8")
    ek.ensure_project_hooks(proj / 'settings.json')
    data = json.loads((proj / 'settings.json').read_text(encoding="utf-8"))
    assert data["env"]["VMR_API_KEY"] == "redacted-secret"
    assert "PreToolUse" in data["hooks"]
    # state_anchor 已注册到 PostToolUse
    post_matchers = [e.get("matcher") for e in data["hooks"]["PostToolUse"]]
    assert "Agent" in post_matchers
```
- **IMPLEMENT (test_state_anchor.py)**:
```python
"""Tests for #39 state_anchor hook — signature injection + drift warning (RED)."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / 'hooks'))
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))
import state_anchor as sa


def _mk_ledger(ws, sigs):
    lines = []
    for i, s in enumerate(sigs):
        ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(time.time() - (len(sigs)-1-i)))
        lines.append(json.dumps({"ts": ts, **s}))
    (ws / '.convergence_ledger.jsonl').write_text("\n".join(lines) + "\n", encoding="utf-8")

def _sig(d="DISPATCH", ids=None, p=0, w=0, b=None, f=5):
    return {"decision": d, "open_ids": ids or ["C-1"], "open_count": 1, "partial_count": p,
            "active_workers": w, "blockers": b or [], "facts_total": f}

def test_anchor_emits_signature_on_every_agent_call(tmp_path):
    """每次 Agent 调用注入紧凑状态签名（治本：持续刷新 LLM 状态表示）"""
    ws = tmp_path / 'ws'; (ws / 'runs').mkdir(parents=True)
    _mk_ledger(ws, [_sig(), _sig(f=7)])
    out = sa.build_anchor(ws)
    assert "state-anchor" in out
    assert "DISPATCH" in out
    assert "7" in out  # facts_total

def test_anchor_warns_on_drift(tmp_path):
    """3 行相同 signature → 注入漂移警告 + re-read 指令"""
    ws = tmp_path / 'ws'; (ws / 'runs').mkdir(parents=True)
    _mk_ledger(ws, [_sig(), _sig(), _sig()])  # 连续 3 行相同
    out = sa.build_anchor(ws)
    assert "drift" in out.lower()
    assert "re-read" in out.lower() or "claim-register" in out.lower()

def test_anchor_silent_when_healthy(tmp_path):
    """健康推进（signature 变化）→ 仅签名，无警告"""
    ws = tmp_path / 'ws'; (ws / 'runs').mkdir(parents=True)
    _mk_ledger(ws, [_sig(f=5), _sig(f=6), _sig(f=7)])  # facts 增长
    out = sa.build_anchor(ws)
    assert "drift" not in out.lower()

def test_main_posttooluse_envelope(tmp_path, capsys, monkeypatch):
    """main() 输出 PostToolUse additionalContext JSON 信封（镜像 worker_pulse）"""
    ws = tmp_path / 'ws'; (ws / 'runs').mkdir(parents=True)
    _mk_ledger(ws, [_sig()])
    # 模拟 stdin payload
    payload = {"tool_name": "Agent", "cwd": str(ws)}
    monkeypatch.setattr('sys.stdin', __import__('io').StringIO(json.dumps(payload)))
    rc = sa.main()
    assert rc == 0
    out = capsys.readouterr().out
    assert "hookSpecificOutput" in out
    assert "PostToolUse" in out

def test_main_silent_for_non_agent_tool(tmp_path, monkeypatch, capsys):
    """非 Agent 工具不注入（避免 orchestrator 读文件噪声）"""
    payload = {"tool_name": "Read", "cwd": str(tmp_path)}
    monkeypatch.setattr('sys.stdin', __import__('io').StringIO(json.dumps(payload)))
    rc = sa.main()
    assert rc == 0
    assert capsys.readouterr().out == ""
```
- **MIRROR**: LEDGER_SIGNATURE + LEDGER_READ + PULSE_INJECT + STALE_WORKERS_MTIME + ACTIVE_STRICT + OPEN_CLAIMS
- **IMPORTS**: json, os, sys, time, pathlib; yaml（_mk_claims）
- **GOTCHA**: (1) signature 排 ts（时间漂移用 ledger_stalled 单独判）；(2) workers-progressing 豁免避免误伤合法 SATURATED 等待（backtrack_gate 20min mtime 一致）；(3) resume prompt 用 fired predicates（ledger 字段 + claim-register），**绝不**读 progress.txt/analysis_state narrative 段（F4）；(4) state_anchor 是 PostToolUse Agent——worker 派发完成才触发，**不**在 orchestrator 读文件时触发（heartbeat_touch 是 Bash 通道，不混用）
- **VALIDATE**: 先跑全红

### Task 2: GREEN — external_kicker.py（detect + recover）
- **ACTION**: 实现 heartbeat_stale / active_session / signature_rotation / workers_progressing / ledger_stalled / _has_open_claims / drift_detected / should_kick / build_resume_prompt / _write_takeover / ensure_project_hooks / kick / --install
- **IMPLEMENT**:
```python
"""external_kicker.py - OS 级定时重启 + 漂移恢复（死 / 漂移 / 死呆，#39，research-grounded）。

根因（research F2/F3）: LLM 长 trajectory → context rot + execution drift（SED α≥1 自放大、
step-local-invisible）。呆不是会话空转，是 LLM 在过期状态上演算——心跳 fresh、ledger 在写，
但状态签名连续不变。时间陈旧法只检死呆；活呆只有 signature rotation 能检（F2 非线性退化）。

不重写 spawn subagent: 派发层没坏——漂移 = orchestrator 用过期状态演算。恢复 = hook 重锚
（state_anchor.py 治本）+ kicker 重启 fired-predicate 续接（F4：不信任旧会话自述）。

三防线（F5 运行时治理）:
  L1 PREVENT  hooks/state_anchor.py: 每调用注入签名（治本，对抗 context rot）
  L2 DETECT   should_kick(): 死/漂移/死呆
  L3 RECOVER  kick(): fresh claude -p <fired-predicate resume>

用法:
  python external_kicker.py <workspace>            # detect + 需要则 kick
  python external_kicker.py <workspace> --check    # 只检测
  python external_kicker.py --install              # 打印 schtasks 命令
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HEARTBEAT_STALE_MINUTES = 35
LEDGER_STALL_MINUTES = 25          # 死呆兜底（ledger 无新行 >25min）
ROTATION_WINDOW = 3                # 漂移检出：连续 ≥3 行 signature 相同
DRIFT_ESCALATE_ROWS = 6            # 漂移持续 ≥6 行（≈30min）→ kick（<6 仅 hook 重锚）
WORKER_PROGRESS_MINUTES = 20       # backtrack_gate 同源 mtime 阈值
TICK_INTERVAL_MINUTES = 15

LEDGER_NAME = ".convergence_ledger.jsonl"
TAKEOVER_FILE = ".kicker-takeover.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)

def _read_json(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def heartbeat_stale(ws: Path) -> bool:
    hb = _read_json(ws / "runs" / ".heartbeat.json")
    last = hb.get("last_tick_ts", "")
    if not last:
        return True
    try:
        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
    except ValueError:
        return True
    return (_now() - dt).total_seconds() > HEARTBEAT_STALE_MINUTES * 60


def active_session(ws: Path) -> bool:
    st = _read_json(ws / ".hook_state.json")
    if not st:
        return False
    exp = st.get("expires_at", "")
    if exp:
        try:
            if _now() > datetime.fromisoformat(exp.replace("Z", "+00:00")):
                return False
        except ValueError:
            pass
    return bool(st.get("active_hooks"))


def _state_signature(row: dict) -> tuple:
    """signature = 决策 + 开放集 + 部分 + worker 数 + blockers + facts 总数（排 ts）。
    连续 N 行相同 = 状态零推进 = 漂移（F2/F3）。"""
    return (
        row.get("decision"),
        tuple(row.get("open_ids") or []),
        row.get("partial_count"),
        row.get("active_workers"),
        tuple(row.get("blockers") or []),
        row.get("facts_total"),
    )

def _read_ledger_tail(ws: Path, n: int) -> list:
    p = ws / LEDGER_NAME
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out[-n:] if out else []

def signature_rotation(ws: Path) -> int:
    """末 ROTATION_WINDOW*2 行内，从末行起向前数连续相同 signature 的行数。
    返回连续相同计数（< ROTATION_WINDOW 表示无漂移）。"""
    tail = _read_ledger_tail(ws, ROTATION_WINDOW * 2)
    if not tail:
        return 0
    streak = 1
    last_sig = _state_signature(tail[-1])
    for row in reversed(tail[:-1]):
        if _state_signature(row) == last_sig:
            streak += 1
        else:
            break
    return streak

def workers_progressing(ws: Path) -> bool:
    """有 in-progress worker 且 mtime < WORKER_PROGRESS_MINUTES → 合法 SATURATED 等待，
    豁免漂移误报（backtrack_gate.py:64-128 同源 mtime 阈值）。"""
    import re
    runs = ws / "runs"
    if not runs.exists():
        return False
    cutoff = WORKER_PROGRESS_MINUTES * 60
    now = datetime.now(timezone.utc)
    for p in runs.glob("worker-status-*.md"):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
            if not re.search(r"status:\s*in-progress", text, re.I):
                continue
            age = (now - datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)).total_seconds()
            if age < cutoff:
                return True
        except OSError:
            continue
    return False

def drift_detected(ws: Path) -> bool:
    """漂移: signature 连续 ≥ROTATION_WINDOW 且非 workers-progressing。"""
    return signature_rotation(ws) >= ROTATION_WINDOW and not workers_progressing(ws)


def _ledger_last_ts(ws: Path):
    tail = _read_ledger_tail(ws, 1)
    if not tail:
        return None
    ts = tail[-1].get("ts")
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None

def ledger_stalled(ws: Path) -> bool:
    """死呆兜底: ledger 最后行 >LEDGER_STALL_MINUTES 无新行（会话不 tick）。"""
    last = _ledger_last_ts(ws)
    if last is None:
        return False
    return (_now() - last).total_seconds() > LEDGER_STALL_MINUTES * 60


def _has_open_claims(ws: Path) -> bool:
    p = ws / "claim-register.yaml"
    if not p.exists():
        return False
    try:
        import yaml
        reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        from status_defs import TERMINAL, IN_PROGRESS_STATUSES
        return any(
            (c.get("status") or "UNKNOWN").upper() not in TERMINAL
            and (c.get("status") or "UNKNOWN").upper() not in IN_PROGRESS_STATUSES
            for c in (reg.get("claims") or [])
        )
    except Exception:
        return False


def should_kick(ws: Path) -> bool:
    """kick 当且仅当:
    - 死: heartbeat stale + 无活跃会话
    - 漂移升级: signature rotation ≥ DRIFT_ESCALATE_ROWS 且非 workers-progressing 且 open>0
    - 死呆: ledger 时间陈旧 + open>0
    （漂移 rotation 在 [ROTATION_WINDOW, ESCALATE) 区间只触发 hook 重锚，不 kick——治本优先）"""
    if heartbeat_stale(ws) and not active_session(ws):
        return True
    if signature_rotation(ws) >= DRIFT_ESCALATE_ROWS and not workers_progressing(ws) and _has_open_claims(ws):
        return True
    if ledger_stalled(ws) and _has_open_claims(ws):
        return True
    return False


def build_resume_prompt(ws: Path) -> str:
    """F4 fired-predicate resume: 从 ledger 末行 + claim-register open + facts 计数 + worker
    status + blockers 构造——NOT 旧会话自述（progress.txt/analysis_state narrative 不读）。"""
    tail = _read_ledger_tail(ws, 1)
    last = tail[-1] if tail else {}
    import yaml
    opens = []
    try:
        reg = yaml.safe_load((ws / "claim-register.yaml").read_text(encoding="utf-8")) or {}
        from status_defs import TERMINAL, IN_PROGRESS_STATUSES
        for c in (reg.get("claims") or []):
            s = (c.get("status") or "UNKNOWN").upper()
            if s not in TERMINAL and s not in IN_PROGRESS_STATUSES:
                opens.append(c.get("id"))
    except Exception:
        pass
    runs = ws / "runs"
    workers = sorted(p.stem.replace("worker-status-", "") for p in runs.glob("worker-status-*.md")) if runs.exists() else []
    parts = [
        "[kicker resume — fired predicates, F4]",
        f"last_decision: {last.get('decision', 'UNKNOWN')}",
        f"open_claims: {opens or '[]'}",
        f"partial_facts: {last.get('partial_count', 0)}",
        f"facts_total: {last.get('facts_total', 0)}",
        f"active_workers: {last.get('active_workers', 0)} -> {workers}",
        f"blockers: {last.get('blockers', [])}",
        "",
        "你是 kicker 重启的接管者: 以 ledger/state 文件为准续接（Phase 0 cold-start 8 文件重读）。",
        "若旧会话仍活着，它应让位（takeover 标记已写）。",
    ]
    return "\n".join(parts)


def _write_takeover(ws: Path, reason: str) -> None:
    p = ws / TAKEOVER_FILE
    data = {"ts": _now().isoformat(timespec="seconds"), "reason": reason,
            "rotation": signature_rotation(ws)}
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)


def ensure_project_hooks(settings_path: Path) -> int:
    """重注册 hooks 到项目级 settings（含 state_anchor），保留 env 段（坑 7）。"""
    existing = _read_json(settings_path)
    hooks = existing.get("hooks") or {}
    hook_dir = Path(__file__).resolve().parent.parent / "hooks"

    def _entry(hook_file: str) -> dict:
        return {"type": "command", "command": f"python {(hook_dir / hook_file).as_posix()}"}

    def _ensure(entries, matcher, hook_file):
        kept = [e for e in entries if e.get("matcher") != matcher]
        kept.append({"matcher": matcher, "hooks": [_entry(hook_file)]})
        return kept

    pre = _ensure(hooks.get("PreToolUse") or [], "Agent", "worker_budget.py")
    pre = _ensure(pre, "Agent", "dispatch_gate.py")
    pre = _ensure(pre, "Bash", "heartbeat_touch.py")
    post = _ensure(hooks.get("PostToolUse") or [], "Agent", "worker_budget.py")
    post = _ensure(post, "Agent", "worker_pulse.py")
    post = _ensure(post, "Agent", "state_anchor.py")  # #39 LAYER 1
    hooks["PreToolUse"] = pre
    hooks["PostToolUse"] = post
    existing["hooks"] = hooks
    tmp = settings_path.with_suffix(settings_path.suffix + ".tmp")
    tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(settings_path)
    return sum(len(e.get("hooks", [])) for e in pre + post)


def kick(ws: Path) -> int:
    _write_takeover(ws, "drift" if drift_detected(ws) else "dead")
    resume = build_resume_prompt(ws)
    loop_proc = subprocess.run(
        [sys.executable, str(Path(__file__).parent / "heartbeat_loop_prompt.py"), str(ws)],
        capture_output=True, text=True, timeout=30)
    if loop_proc.returncode == 0:
        resume += "\n\n" + loop_proc.stdout.strip()
    claude = shutil.which("claude") or "claude"
    try:
        proc = subprocess.Popen([claude, "-p", resume], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 0 if proc.pid else 1
    except OSError:
        return 1


def main() -> int:
    ap = argparse.ArgumentParser(prog="external_kicker.py", description="死/漂移/死呆 + fired-predicate resume (#39)")
    ap.add_argument("workspace", nargs="?")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--install", action="store_true")
    args = ap.parse_args()

    if args.install:
        script = Path(__file__).resolve()
        print(f"schtasks /Create /SC MINUTE /MO {TICK_INTERVAL_MINUTES} /TN kunglao-kicker "
              f"/TR \"\\\"{sys.executable}\\\" \\\"{script}\\\" <workspace>\" /F")
        print(f"# 三防线: L1 state_anchor hook(每调用) / L2 detect(15min tick) / L3 kick(escalate)")
        print(f"# 阈值: ROTATION {ROTATION_WINDOW}行(~15min,→hook) < ESCALATE {DRIFT_ESCALATE_ROWS}行(~30min,→kick) "
              f"< STALL 25min < STALE 35min")
        print(f"# 卸载: schtasks /Delete /TN kunglao-kicker /F")
        return 0
    if not args.workspace:
        print("FAIL: workspace required (or --install)", file=sys.stderr)
        return 64
    ws = Path(args.workspace)

    hb_stale = heartbeat_stale(ws)
    rot = signature_rotation(ws)
    drift = drift_detected(ws)
    stall = ledger_stalled(ws)

    if args.check:
        print(f"heartbeat={'stale' if hb_stale else 'fresh'} rotation={rot} "
              f"drift={'YES' if drift else 'no'} workers_progressing={workers_progressing(ws)} "
              f"ledger_stalled={stall} kick_needed={should_kick(ws)}")
        return 1 if should_kick(ws) else 0
    if not should_kick(ws):
        print(f"OK: no kick (rotation={rot}, drift={'warn-only' if drift else 'no'})")
        return 0

    reason = "drift" if (drift and rot >= DRIFT_ESCALATE_ROWS) else ("dead" if hb_stale and not active_session(ws) else "stalled")
    proj_settings = ws.parent / ".claude" / "settings.json"
    if proj_settings.exists():
        n = ensure_project_hooks(proj_settings)
        print(f"hooks re-registered to project settings ({n} entries, env kept, state_anchor added)")
    rc = kick(ws)
    print(f"kicked fresh session (reason={reason}, rotation={rot}, rc={rc})")
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
```
- **MIRROR**: LEDGER_SIGNATURE + LEDGER_READ + STALE_WORKERS_MTIME + ACTIVE_STRICT + OPEN_CLAIMS + ATOMIC_WRITE + PROMPT_SOURCE
- **IMPORTS**: argparse, json, shutil, subprocess, sys, datetime, pathlib; `import yaml`/`from status_defs import ...`（函数内）
- **GOTCHA**: (1) should_kick 的漂移分支用 DRIFT_ESCALATE_ROWS(6) 而非 ROTATION_WINDOW(3)——3~5 行只触发 hook 重锚（治本），6+ 才 kick；(2) resume prompt 严格 fired-predicate，不读 narrative；(3) ensure_project_hooks 必须注册 state_anchor.py
- **VALIDATE**: `python scripts/test_external_kicker.py` 全绿；`--check` 对漂移 ws 报 `drift=YES kick_needed=True`（rot≥6 时）

### Task 3: GREEN — hooks/state_anchor.py（prevent，治本层）
- **ACTION**: PostToolUse Agent hook——每次 worker 完成/Agent 调用注入紧凑状态签名；漂移时追加 re-read 指令。镜像 worker_pulse.main 的 additionalContext 信封。
- **IMPLEMENT**:
```python
"""state_anchor.py - PostToolUse(Agent) 状态重锚 hook (#39 LAYER 1, 治本).

根因（research F2/F3 context rot + SED）: LLM 长 trajectory 丢失精确状态表示。对策不是
等漂移再重启，而是每次 Agent 调用机械注入紧凑状态签名——持续刷新 LLM 的工作状态表示。
漂移（signature rotation ≥ ROTATION_WINDOW）时追加 re-read 指令（不杀会话）。

镜像 worker_pulse.py:173-178 的 PostToolUse additionalContext 信封。与 worker_pulse 分工:
worker_pulse 注入 worker 完成快照；state_anchor 注入全局状态签名 + 漂移警告。

Activation: orchestrator-only（hook_activation.py 激活时才生效）。
"""
import json
import sys
from pathlib import Path

SKILL = Path("C:/Users/hr/.claude/skills/kunglao-agent")
sys.path.insert(0, str(SKILL / "scripts"))
import external_kicker as ek  # 复用 signature_rotation / workers_progressing / _read_ledger_tail


def build_anchor(ws: Path) -> str:
    """构造 additionalContext: 紧凑状态签名 + 漂移时警告 + re-read 指令。"""
    tail = ek._read_ledger_tail(ws, 1)
    last = tail[-1] if tail else {}
    rot = ek.signature_rotation(ws)
    wp = ek.workers_progressing(ws)
    drift = rot >= ek.ROTATION_WINDOW and not wp

    sig_line = (f"[state-anchor] decision={last.get('decision','?')} "
                f"open={last.get('open_count',0)} partial={last.get('partial_count',0)} "
                f"workers={last.get('active_workers',0)} facts={last.get('facts_total',0)} "
                f"rotation={rot}/{ek.ROTATION_WINDOW} workers_progressing={wp}")
    if drift:
        sig_line += (f"\n⚠ DRIFT: {rot} 轮状态签名不变（context rot / execution drift, research F2/F3）。"
                     f"\n   re-read claim-register.yaml + facts/_INDEX.md + runs/worker-status-*.md "
                     f"BEFORE next dispatch；若无法推进，写 blocker-*.md。")
    return sig_line


def _resolve_ws(cwd: str) -> Path | None:
    p = Path(cwd)
    for cand in [p, *p.parents]:
        if (cand / "claim-register.yaml").exists():
            return cand
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0
    tool = (payload.get("tool_name") or "").lower()
    if tool != "agent":
        return 0  # 只在 Agent 调用后触发（worker 完成）

    ws = _resolve_ws(payload.get("cwd") or "")
    if ws is None:
        return 0

    try:
        anchor = build_anchor(ws)
    except Exception:
        return 0  # FAIL_OPEN: hook 异常不影响 worker
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                      "additionalContext": anchor}}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```
- **MIRROR**: PULSE_INJECT + LEDGER_SIGNATURE（复用 external_kicker）
- **IMPORTS**: json, sys, pathlib; `import external_kicker`
- **GOTCHA**: (1) 复用 external_kicker 的 signature_rotation/workers_progressing（不重复实现，DRY）；(2) FAIL_OPEN——hook 异常绝不阻塞 worker；(3) workspace 解析向上找 claim-register.yaml（与 worker_pulse._resolve_workspace 同思路）；(4) 只在 tool_name==agent 触发，不在 Bash/Read 触发（避免 orchestrator 每次读文件都注入，噪声）
- **VALIDATE**: `python scripts/test_state_anchor.py` 全绿；构造 3 行相同 ledger + Agent payload → stdout 含 `DRIFT` + `re-read`

### Task 4: wire_up_settings --settings + 文档 + 回归
- **ACTION**: wire_up_settings.py 加 `--settings <path>`（默认 user 级不变）；SKILL.md/references 记录三防线 + schtasks + 坑 7 + F1–F5 映射；跑全量测试
- **VALIDATE**: `python scripts/test_v1_8_enforcement_gates.py` 31/31；`python scripts/test_external_kicker.py` + `test_state_anchor.py` 全绿；`python -m pytest tests/ -q` 无回归；`--install` 输出 schtasks；项目级 settings env 段在 ensure_project_hooks 后仍在 + state_anchor 已注册

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected | Layer |
|---|---|---|---|
| test_kicker_detects_dead | stale hb + 无会话 | True | L2 死 |
| test_kicker_active_session_skip_dead | stale + 活跃会话 | False | L2 死豁免 |
| test_drift_detected_3_identical_signatures | 3 行相同 sig | rotation≥3 | **L2 漂移（核心）** |
| test_drift_not_detected_when_workers_progressing | SATURATED + 新 worker | drift False | L2 合法等待豁免 |
| test_drift_resets_on_signature_change | 末行 facts 增长 | rotation<3 | L2 推进重置 |
| test_drift_below_threshold | 2 行相同 | rotation<3 | L2 阈值 |
| test_should_kick_drift_below_escalate | rotation=4 | should_kick False | **治本优先（不 kick）** |
| test_should_kick_drift_at_escalate | rotation=6 | should_kick True | L3 漂移升级 |
| test_stalled_when_ledger_time_stale | ledger >25min + open | True | L2 死呆 |
| test_no_open_claims_no_kick | 全终态 | False | L2 该收敛 |
| test_resume_prompt_built_from_ledger_not_narrative | ledger+claims | 含 fired predicates, 无 narrative | **L3 F4** |
| test_kicker_writes_takeover | kick 前 | .kicker-takeover.json | L3 仲裁 |
| test_register_project_settings_keeps_env | 项目 settings + env | env 保留 + state_anchor 注册 | L3 坑 7 |
| test_anchor_emits_signature_on_every_agent_call | ledger 2 行 | additionalContext 含签名 | **L1 治本** |
| test_anchor_warns_on_drift | 3 行相同 | 含 DRIFT + re-read | L1 漂移警告 |
| test_anchor_silent_when_healthy | facts 增长 | 无 drift | L1 健康静默 |
| test_main_posttooluse_envelope | Agent payload | hookSpecificOutput JSON | L1 信封 |
| test_main_silent_for_non_agent_tool | Read payload | 无输出 | L1 仅 Agent |

### Edge Cases Checklist
- [x] 无 heartbeat → stale（死分支）
- [x] heartbeat 坏 JSON → stale
- [x] ledger 无行/坏行 → rotation 0 + ledger_stalled False（不误踢）
- [x] .hook_state 过期/缺失 → active_session False（死可踢）
- [x] 死 + 漂移同时 → reason 报 dead（死优先）
- [x] 漂移 rot∈[3,6) → should_kick False（只 hook 重锚，不 kick）——治本优先
- [x] 无 open claims + 漂移 → 不 kick（该收敛）
- [x] SATURATED + workers 推进 → 不漂移（合法等待）
- [x] SATURATED + workers 全 stale >20min → 漂移（需干预，#38 gate 也触发）
- [x] settings.json 不存在 → ensure_project_hooks 创建
- [x] claude 不在 PATH → kick 返回 1
- [x] state_anchor 异常 → FAIL_OPEN return 0（不阻塞 worker）
- [x] state_anchor 非 Agent tool → return 0（不注入）
- [ ] 漂移旧会话复活 → takeover 标记让位提示；残余风险见 Risks

---

## Validation Commands

```bash
cd C:/Users/hr/.claude/kunglao-remote-dev
python scripts/test_external_kicker.py
python scripts/test_state_anchor.py
python scripts/test_v1_8_enforcement_gates.py   # 31/31
python -m pytest tests/ -q
```
EXPECT: 全绿

### Manual Validation
- [ ] `external_kicker.py <ws> --check`：漂移 ws（3+ 相同行 + 无 progressing worker）→ `drift=YES`；rot≥6 → `kick_needed=True`
- [ ] 死 ws（stale hb）→ `kick_needed=True reason=dead`
- [ ] SATURATED + 活 worker → `workers_progressing=True drift=no`
- [ ] fresh 推进 ws → `OK: no kick`
- [ ] `--install` 输出 schtasks 命令
- [ ] 项目级 settings env（VMR_API_KEY）在 ensure_project_hooks 后仍在 + state_anchor.py 已注册
- [ ] kick 后 `.kicker-takeover.json` 含 reason + rotation
- [ ] resume prompt 含 last_decision/open_claims/facts_total（grep ledger 字段），无 narrative
- [ ] state_anchor 对 3 行相同 ledger + Agent payload → stdout 含 `DRIFT` + `re-read`

---

## Acceptance Criteria
- [x] **死**断点 → 自动重启（heartbeat stale + 无活跃会话）
- [x] **漂移**断点检出（signature rotation ≥3 且非 workers-progressing）——治本信号，非时间
- [x] **hook 重锚**（L1）：每次 Agent 调用注入状态签名，漂移时警告（治本，不杀会话）
- [x] **fired-predicate resume**（F4）：kick prompt 来自 ledger/facts/claims，非旧会话自述
- [x] 漂移 rot∈[3,6) 只触发 hook 重锚（不 kick）；≥6 才 kick（治本优先于恢复）
- [x] 项目级 settings env 段保留 + state_anchor 注册（坑 7）
- [x] 30-min TTL 与 tick 无空窗
- [x] 不重写 spawn subagent（治本 = hook 重锚 + fired-predicate 恢复）
- [x] 不引用 refuted claims（research refuted 0-3 的 zenodo 伪造不进设计）

## Completion Checklist
- [x] 漂移用 signature（F2/F3），不用纯时间（时间仅死呆兜底）
- [x] L1 hook 重锚是治本层（F5 "model may know"）；L3 kick 是兜底（F5 "recover"）
- [x] resume 用 fired predicates（F4），不读 narrative
- [x] workers-progressing 豁免避免误伤合法 SATURATED（backtrack_gate mtime 同源）
- [x] kicker 复用 heartbeat_loop_prompt 输出 + 新增 fired-predicate 前缀
- [x] ensure_project_hooks 镜像 wire_up idempotent merge + 保留 env + 注册 state_anchor
- [x] 无锁惯例 → 原子写 + 存在性判定 + takeover 标记
- [x] 默认 wire_up 行为不变（--settings 增量）
- [x] 设计决策逐条映射 research findings（F1–F6）+ 标 confidence + caveat

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 漂移误报（合法 SATURATED 被判漂移） | Medium | 误踢活跃会话 | workers-progressing 豁免（mtime<20min in-progress）；rot∈[3,6) 只 hook 不 kick |
| 漂移漏报（signature 变但实际漂移，如重复 DISPATCH 不同 claim） | Medium | 活呆未检出 | signature 含 open_ids——重复 DISPATCH 同 claim 才算；不同 claim = 真推进。可加 secondary：连续 N 行同 decision（忽略 open_ids）→ 软警告。本计划保守不实现，留 Notes |
| hook 注入噪声（每次 Agent 调用一条） | Low | context 占用 | 单行紧凑签名（~120 字符）；健康时静默无警告 |
| 漂移旧会话复活 → 双会话 | Medium | 并发推进 | takeover 标记 + fresh prompt 让位提示；残余：旧会话无视标记仍写 ledger → kicker 看推进不再 kick，以 ledger 为准，最终一个写 terminal |
| schtasks 未注册 | Medium | kicker 不生效 | --install 生成命令 + 文档；kicker 可手动跑 |
| resume prompt fired-predicate 不够（缺关键状态） | Medium | 续接不准 | prompt 含 6 fired 字段 + cold-start 8 文件重读指令；F4 原则是"不信任自述"非"最小 prompt" |
| 单源证据（F3/F4 未复现） | Medium | 设计前提可能过强 | 阈值全可调（ROTATION_WINDOW/ESCALATE/STALL）；标注 best-evidence；监控误报率迭代 |
| state_anchor workspace 解析失败（cwd 不在 ws 下） | Low | 不注入 | FAIL_OPEN return 0；worker_pulse 同模式已有验证 |

## Notes
- **用户修正链**：原方案"检测呆→重启"（治标）→ 用户"LLM 长 trajectory 丢失状态表示"（根因）→ deep-research 验证 → 三防线（detect/prevent/recover）。**核心新增是 L1 state_anchor hook**——之前的 kunglao 有 detect（convergence_health）和 commit（ledger），缺 prevent/refresh 的运行时函数（F5 "forget/refresh"）。
- **漂移 vs 死信号区分**：心跳证明进程在用工具（heartbeat_touch 每次工具调用刷 activity_ts），不证明状态精确；signature 是客观状态指纹（convergence_check 每轮 append，排 ts）。漂移 = 活会话在过期状态演算（heartbeat fresh + signature 不变）；死呆 = 会话不 tick（ledger 无新行，时间陈旧）；死 = 会话没了（heartbeat stale）。
- **不重写 spawn subagent**：派发层没坏——漂移 = orchestrator 用过期状态演算（不基于真状态派发）。spawn worker 救不了"没人基于真状态派发"；治本 = hook 重锚 + fired-predicate 恢复。
- **阈值层级**：ROTATION 3 行(~15min)→hook 重锚 < ESCALATE 6 行(~30min)→kick < TICK 15 < STALL 25min < TTL 30 < STALE 35min。治本（hook）先于恢复（kick）。
- **与 #38 的关系**：#38 stuck gate（20min worker mtime）+ 本计划 workers_progressing（20min 同源）；#38 截断卡死 worker，本计划截断漂移 orchestrator；两层级不冲突，kicker 重启的会话仍被 #38 保护。
- **F4 fired-predicate 原则**：resume prompt 严格来自 ledger 末行 + claim-register open + facts/_INDEX 计数 + worker-status 文件 + blockers——**绝不**读 progress.txt/analysis_state.txt 的 narrative 段（"an LLM saying done is not an event"——旧会话自述正是不可信的）。
- **坑 7 重大修正**：issue 原叙事"hooks 掉了"是错的——wire_up 写 user 级（0 生效），实际生效在项目级（gitignored 含 API key）。ensure_project_hooks 必须指项目级 + 保留 env + 注册 state_anchor。
- **研究局限**（research caveats）：F1 未同行评议；F3/F4 单源未复现（F4 自身实验 null）；所有 horizon 是 benchmark-scale。阈值全可调，标 best-evidence，监控误报率迭代。
- 全仓无文件锁惯例——"恰一个接管"用原子写 + 存在性判定 + takeover 标记。
- heartbeat.json 无 session_id（explore B7）——kicker 用 .hook_state.json active_hooks 非空作活跃代理；takeover 标记补会话仲裁缺口。
- 本计划不自动注册 schtasks——`--install` 打印命令，人工执行。
- **未来工作（超出 #39）**：F5 "forget" 的完整实现 = 轨迹压缩/compaction（不只是 hook 重锚）；F2 horizon-collapse 阈值测量（kunglao 的 breaking point 在哪）；secondary drift 信号（连续 N 行同 decision 忽略 open_ids）。
