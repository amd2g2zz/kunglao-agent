# Plan: #38 stuck-worker 机械 gate — backtrack_gate 接线 + worker_pulse mtime-stale 推送

## Summary
C-207 卡死 71min 才被手动发现（progress.txt:1681-1696）。backtrack_gate.py（20min 阈值）已构建且有测试，但 worker_budget 的 10 gate 列表（:673-689）无它——已构建未接线。本计划把 backtrack_gate 接为 PreToolUse gate（镜像 check_plan_drift：subprocess + FAIL_OPEN + rc 映射），并扩展 worker_pulse 在 mtime-stale status 文件时也推事件（不只完成时）。卡死截断从 71min → 20min 机械强制。

## User Story
作为 kunglao-agent 的 orchestrator，我希望派发新任务前被机械检查"是否有卡死 worker"，这样卡死不会在无人值守时无限持续（C-207 71min → 20min 截断），且脚本缺失时系统不误伤（FAIL_OPEN）。

## Problem → Solution
backtrack_gate 已可检测 stuck worker（in-progress + mtime > 20min + 无有效 `## backtrack` 块 → rc=1；>30min 未行动 → rc=2）但无人调用 → 在 `worker_budget.pre_check` checks 列表加 `('backtrack', check_backtrack_gate(paths))`（镜像 check_plan_drift 的 subprocess+FAIL_OPEN 模式）→ REJECT 通道生效；`worker_pulse` 在 PostToolUse 时若发现 stale status 文件（即使不是 dispatch 完成）也注入事件。

## Metadata
- **Complexity**: Small
- **Source PRD**: GitHub issue #38（无独立 PRD）
- **PRD Phase**: N/A（standalone）
- **Estimated Files**: 3（hooks/worker_budget.py、hooks/worker_pulse.py、scripts/test_stuck_gate.py）

---

## UX Design

### Before
```
dispatch → pre_check（10 项 checks，无 stuck 检查）
            ↑ 卡死 worker 存在 → 照样放行 → C-207 71min 无人发现
worker 完成 → worker_pulse 注入（_was_dispatch 才触发；卡死 worker 从不"完成" → 永不提示）
```

### After
```
dispatch → pre_check（+('backtrack', check_backtrack_gate(paths))）
            ↑ 有 stuck worker（rc=1/2）→ REJECT（卡死 20min 截断）
PostToolUse（任意 Agent）→ worker_pulse 检查 stale status 文件
            ↑ 有 mtime-stale in-progress → 注入 stale 事件（软提示）
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| pre_check | 10 checks | 11 checks（+backtrack） | REJECT 消息带 rc 与指引 |
| worker_pulse | 仅 dispatch 完成触发 | 任意 Agent 完成 + stale 检查 | 注入不 abort（REJECT 是 worker_budget 的 job） |
| backtrack_gate.py | 手动跑 | pre_check 每派发自动跑 | 无脚本改动（只接线） |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `hooks/worker_budget.py` | 71-112 | `_run_py` + `check_plan_drift`/`check_convergence_health` 逐字（subprocess+FAIL_OPEN+rc 映射）— 新 gate 镜像 |
| P0 | `scripts/backtrack_gate.py` | 全文 (147 行) | rc 语义（0=OK / 1=stuck no backtrack / 2=un-actioned>30m）+ check() 输出 |
| P0 | `hooks/worker_budget.py` | 670-688 | pre_check checks 列表（drift/health 在 :686-687，backtrack 加其后） |
| P1 | `hooks/worker_pulse.py` | 150-179 | main() 守卫链（_was_dispatch → _build_pulse → stderr+rc2/additionalContext） |
| P1 | `scripts/test_v1_8_enforcement_gates.py` | 474-489, 527-542 | test_f5_dead_worker_zombie（硬断言）/ test_f17_plan_drift（宽松）— 新测试取硬断言风格 |
| P2 | `scripts/test_worker_budget.py` | 全文 | 测试 runner 模式（_run() 直跑 main） |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| N/A | — | 纯接线——backtrack_gate 已构建，无外部依赖 |

---

## Patterns to Mirror

### SUBPROCESS_GATE（镜像 check_plan_drift — hooks/worker_budget.py:82-90 逐字）
```python
def check_plan_drift(paths):
    ws = paths.get('workspace')
    if not ws:
        return True, ''
    r = _run_py([str(_SKILL_ROOT / 'scripts' / 'plan_drift_detector.py'),
                 str(ws), '--active-only'])
    if r is None:
        return True, ''
    if r.returncode == 0:
        return True, ''
    return False, f"plan drift detected (rc={r.returncode}): {(r.stderr or r.stdout or '')[:200]}"
```

### FAIL_OPEN（_run_py — hooks/worker_budget.py:71-80 逐字）
```python
def _run_py(args, cwd=None):
    try:
        return subprocess.run(
            [sys.executable] + args,
            capture_output=True, text=True, timeout=20,
            cwd=cwd,
        )
    except (subprocess.SubprocessError, OSError):
        return None
```

### STUCK_DETECTION（backtrack_gate check — scripts/backtrack_gate.py:64-128）
rc=1: `REJECT: N stuck worker(s) without valid backtrack (threshold {stuck_min}m)`（stuck 列表）
rc=2: `HARD_PAUSE: N worker(s) stuck > 30m without redispatch`（un_actioned 列表）
rc=0: `OK: no stuck workers (threshold {stuck_min}m)` / valid backtrack

### PULSE_INJECT（worker_pulse additionalContext — hooks/worker_pulse.py:173-178 逐字）
```python
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": pulse,
        }
    }, ensure_ascii=False))
    return 0
```

### HARD_ASSERT（test_f5 风格 — scripts/test_v1_8_enforcement_gates.py:474-489）
```python
    assert d["decision"] == "DISPATCH"
    assert d["active_workers"] == 0
```
// 新 gate 测试用「断言 rc==2 + stderr 内容」硬断言（explore B6 确认现存测试无此模式——新建）

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `hooks/worker_budget.py` | UPDATE | 新增 `check_backtrack_gate(paths)`（镜像 check_plan_drift）+ pre_check checks 列表加 `('backtrack', ...)` |
| `hooks/worker_pulse.py` | UPDATE | main() 加 stale-status 检查分支（非 dispatch 完成也注入事件） |
| `scripts/test_stuck_gate.py` | CREATE | 新测试：stale → REJECT / 新 mtime → 放行 / 脚本缺失 → 放行（subprocess 跑真脚本，tmp workspace 构造 runs/） |

## NOT Building

- 不改 backtrack_gate.py 本体（rc 语义、阈值、backtrack 块格式全保留）
- 不动 drift/health gate（既有接线）
- pulse 的 stale 推送是注入（additionalContext），不是 abort——REJECT 通道只属于 worker_budget
- 不自动 kill / 不自动 redispatch stuck worker（只强制人/编排器处理）

---

## Step-by-Step Tasks

### Task 1: RED — test_stuck_gate.py
- **ACTION**: 先写测试（TDD RED），构造 tmp workspace 的 runs/worker-status-*.md + 调 worker_budget 的新 gate 函数
- **IMPLEMENT**:
```python
"""Tests for #38 stuck-worker mechanical gate (RED)."""
import os
import sys
import tempfile
import time
from pathlib import Path

_HERE = Path(__file__).parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / 'hooks'))
from worker_budget import check_backtrack_gate  # noqa: E402


def _mk_status(ws: Path, name: str, last: str, age_min: int = 0) -> Path:
    """写 runs/worker-status-<name>.md，last 为最后 status，age_min 控制 mtime 距今分钟数。"""
    runs = ws / 'runs'
    runs.mkdir(parents=True, exist_ok=True)
    p = runs / f'worker-status-{name}.md'
    p.write_text(f"## Status\n{last}\n", encoding='utf-8')
    if age_min:
        old = time.time() - age_min * 60
        os.utime(p, (old, old))
    return p


def test_stale_status_rejects(tmp_path):
    """stale（in-progress + mtime>20min 无 backtrack）→ REJECT（rc=1 映射 not ok）"""
    ws = tmp_path / 'ws'
    _mk_status(ws, 'w1', 'in-progress', age_min=25)
    ok, msg = check_backtrack_gate({'workspace': str(ws)})
    assert not ok
    assert 'backtrack' in msg.lower() or 'stuck' in msg.lower()

def test_fresh_status_allows(tmp_path):
    """新 mtime（<20min）→ 放行"""
    ws = tmp_path / 'ws'
    _mk_status(ws, 'w1', 'in-progress', age_min=1)
    ok, msg = check_backtrack_gate({'workspace': str(ws)})
    assert ok

def test_done_status_allows(tmp_path):
    """done 的 status 文件不触发（非 in-progress）"""
    ws = tmp_path / 'ws'
    _mk_status(ws, 'w1', 'done', age_min=25)
    ok, msg = check_backtrack_gate({'workspace': str(ws)})
    assert ok

def test_missing_script_fail_open(tmp_path):
    """脚本缺失/异常 → 放行（FAIL_OPEN）——gate 函数本身对异常路径返回 (True,'')"""
    ws = tmp_path / 'ws'
    _mk_status(ws, 'w1', 'in-progress', age_min=25)
    # 无 workspace 键 → 放行（FAIL_OPEN 第一分支）
    ok, msg = check_backtrack_gate({})
    assert ok
```
- **MIRROR**: HARD_ASSERT + FAIL_OPEN
- **IMPORTS**: os, sys, tempfile, time, pathlib; `from worker_budget import check_backtrack_gate`
- **GOTCHA**: subprocess 跑真 backtrack_gate.py 需要它 import gate_telemetry/hook_activation 成功——backtrack_gate 顶部 `import gate_telemetry as _gt` 与 `import hook_activation as ha` 是 sibling import，subprocess 跑时 sys.path[0]=脚本目录，OK。worker_budget._run_py 无 cwd 参数时 cwd=None → 继承测试进程 cwd（pytest 从仓库根跑，OK）；若从别处跑，测试开头 os.chdir 到 `_HERE.parent.parent`
- **VALIDATE**: 先跑全红（test_stale_status_rejects 应失败——gate 函数尚不存在）

### Task 2: GREEN — worker_budget.check_backtrack_gate + 接线
- **ACTION**: 新增 gate 函数（镜像 check_plan_drift）+ pre_check checks 列表追加
- **IMPLEMENT**:
```python
def check_backtrack_gate(paths):
    """#38: stuck-worker gate wired into PreToolUse (backtrack_gate.py rc semantics).
    rc=1 -> stuck worker(s) without valid backtrack; rc=2 -> un-actioned >30m.
    FAIL_OPEN on any subprocess/workspace resolution failure — the hook stays
    usable (mirrors check_plan_drift)."""
    ws = paths.get('workspace')
    if not ws:
        return True, ''
    r = _run_py([str(_SKILL_ROOT / 'scripts' / 'backtrack_gate.py'),
                 str(ws)])
    if r is None:
        return True, ''
    if r.returncode == 1:
        return False, ("stuck worker(s) without valid backtrack — force `## backtrack` block "
                       "before re-dispatch (backtrack_gate rc=1)")
    if r.returncode == 2:
        return False, ("stuck worker(s) >30m un-actioned — escalate or redispatch "
                       "(backtrack_gate rc=2)")
    return True, ''
```
pre_check checks 列表（:686-687 后）追加：
```python
        # #38: stuck-worker mechanical gate — 20min 卡死截断 (C-207: 71min)
        ('backtrack', check_backtrack_gate(paths)),
```
- **MIRROR**: SUBPROCESS_GATE + FAIL_OPEN（逐字镜像 check_plan_drift）
- **IMPORTS**: 无新导入（_run_py/_SKILL_ROOT 已有）
- **GOTCHA**: backtrack_gate rc=2 是 HARD_PAUSE（>30m）——消息措辞区分 rc=1（force backtrack）/ rc=2（escalate）
- **VALIDATE**: `python scripts/test_stuck_gate.py` 全绿；`python scripts/test_v1_8_enforcement_gates.py` 31/31

### Task 3: GREEN — worker_pulse stale 事件推送
- **ACTION**: main() 守卫链加 stale 分支——_was_dispatch 为 False 时也检查 runs/ 有无 stale in-progress 文件
- **IMPLEMENT**: 新增 `_stale_workers(ws)` 辅助 + main() 改造：
```python
def _stale_workers(ws: Path) -> list:
    """#38: in-progress status 文件 mtime>20min（stale）——即使没有 dispatch 完成也推事件。"""
    from datetime import datetime, timezone, timedelta
    runs = ws / 'runs'
    if not runs.exists():
        return []
    cutoff = timedelta(minutes=20)
    now = datetime.now(timezone.utc)
    stale = []
    for p in runs.glob('worker-status-*.md'):
        try:
            text = p.read_text(encoding='utf-8', errors='replace')
            m = re.search(r'status:\s*(\S+)', text)
            if not m or m.group(1).lower() != 'in-progress':
                continue
            age = now - datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if age > cutoff:
                stale.append({'worker': p.stem, 'age_min': int(age.total_seconds() // 60)})
        except OSError:
            continue
    return stale
```
main()（_was_dispatch 分支后）：
```python
    if not _was_dispatch(payload):
        # #38: 卡死 worker 从不"完成"——即使非 dispatch 完成，也注入 stale 事件
        stale = _stale_workers(ws)
        if stale:
            lines = [f"[worker_pulse] stale worker(s) — stuck gate will REJECT new dispatches: "
                     f"{[w['worker'] for w in stale]} (age {[w['age_min'] for w in stale]}m)"]
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": "\n".join(lines),
                }
            }, ensure_ascii=False))
        return 0
```
- **MIRROR**: PULSE_INJECT（additionalContext 注入，不 abort）
- **IMPORTS**: re（已有）、datetime（函数内 import）
- **GOTCHA**: 注入不 abort——REJECT 通道属于 worker_budget pre_check；pulse 只是提示。stale 判定与 backtrack_gate 同阈值（20min），但**不做 backtrack 块检查**（那是 gate 的 job）
- **VALIDATE**: 构造 stale runs/ + 非 dispatch payload → pulse 注入含 "stale worker(s)"

### Task 4: 回归 + 文档
- **ACTION**: 跑全量测试；SKILL.md toolshelf 表标注 backtrack_gate 已机械接线
- **VALIDATE**: `python scripts/test_v1_8_enforcement_gates.py` 31/31；`python scripts/test_stuck_gate.py` 全绿；`python scripts/test_worker_budget.py` 33/33；`python -m pytest tests/ -q` 无回归

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| test_stale_status_rejects | in-progress + mtime 25min 无 backtrack | not ok + 'backtrack'/'stuck' | 核心 REJECT |
| test_fresh_status_allows | in-progress + mtime 1min | ok | 阈值下 |
| test_done_status_allows | done + mtime 25min | ok | 非 in-progress |
| test_missing_script_fail_open | 无 workspace 键 | ok | FAIL_OPEN |
| test_f5_dead_worker_zombie（既有） | done status | DISPATCH + active=0 | 回归 |

### Edge Cases Checklist
- [x] 空 runs/ 目录 → ok
- [x] 无 workspace 键 → 放行（FAIL_OPEN）
- [x] 脚本缺失（subprocess 异常）→ 放行
- [x] valid backtrack 块 → rc=0 放行（backtrack_gate 语义保留）
- [ ] worktree .wt-*/ 下 stale（backtrack_gate 只扫主 runs/——现状保留，不扩 scope）
- [ ] pulse 触发频率（每个 Agent 完成都查 stale）→ 只读 glob，开销可忽略

---

## Validation Commands

### Unit Tests
```bash
cd C:/Users/hr/.claude/kunglao-remote-dev
python scripts/test_stuck_gate.py
```
EXPECT: 全绿

### Full Test Suite
```bash
python scripts/test_v1_8_enforcement_gates.py   # 31/31
python scripts/test_worker_budget.py             # 33/33
python -m pytest tests/ -q
```
EXPECT: 全绿

### Manual Validation
- [ ] 构造 stale runs/ + 派发 payload → pre_check REJECT `backtrack: stuck worker(s)...`
- [ ] 卡死时间验证：worker 停止更新 mtime 20min 后，任意新派发被拒
- [ ] 新 mtime 更新后 → 放行

---

## Acceptance Criteria
- [x] 卡死时间从 71min → 20min 机械截断
- [x] test_v1_8_enforcement_gates 31/31（无回归）
- [x] test_stuck_gate 全绿（stale REJECT / 新 mtime 放行 / FAIL_OPEN）
- [x] pulse 在非 dispatch 完成时也推 stale 事件

## Completion Checklist
- [x] gate 镜像 check_plan_drift（subprocess+FAIL_OPEN）逐字
- [x] rc 语义映射准确（1=force backtrack / 2=escalate）
- [x] pulse 注入不 abort（REJECT 只属 worker_budget）
- [x] 不改 backtrack_gate.py 本体

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| backtrack_gate sibling import 在 subprocess 下失败 | Medium | gate 全 REJECT | FAIL_OPEN（异常 → (True,'')）+ 测试验证真脚本可跑 |
| 20min 阈值误伤长任务 | Medium | 合法 worker 被拒 | backtrack_gate 已有 `## backtrack` 豁免通道（valid decision 不拒）——语义保留 |
| pulse stale 推送噪声 | Low | 每 Agent 完成一条 | 仅 stale 时注入，正常时 silent |

## Notes
- issue 验收「smoke 31/31」——test_v1_8_enforcement_gates 31 项不变
- explore B6 实测：drift/health gate 本身零测试覆盖——本计划新建 test_stuck_gate.py 顺带给「subprocess gate」模式建立测试先例（rc==2 + stderr 硬断言）
- backtrack_gate 有 hook_activation.is_active 门控（`.hook_state.json` 缺失时 legacy 默认 True）——测试无需 .hook_state.json
