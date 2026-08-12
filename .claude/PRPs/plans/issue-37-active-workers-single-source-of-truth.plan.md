# Plan: #37 active_workers 单真相源（gate 侧也读 status 文件）

## Summary
worker_budget 的 workers gate 目前读 `analysis_state.txt` 的 `[active_workers]` 段（双真相源之一，v1.9.13 已废弃语义），而 convergence_check 早已改用 `_scan_active_workers` 扫 `runs/worker-status-*.md` + `.wt-*/` worktree。本计划把 gate 的读源切到 status 文件扫描，state 段降为纯缓存/纯显示——消除「state 块空但 ledger active_workers=1 残留」的架构缺陷。

## User Story
作为 kunglao-agent 的 orchestrator，我希望 workers gate 与 convergence_check 读**同一个** active 计数源，这样状态块被 reconcile 清零或残留旧值时，≤3 并发上限仍被机械强制，不会出现「0 真实 worker 却被 gate 判满」或「真实 worker 满却被放行」。

## Problem → Solution
`read_active_workers(state_path)` 读 state 段（reconcile 会清零 claim_id/tier/dispatched_at，且只在 LLM 驱动的 cron tick 跑）→ `check_workers_lt_3` 改为读 `_scan_active_workers` 等价扫描（runs/ + .wt-*/ worktree 的 status 文件 last-status=in-progress 计数），state 段不参与 gate 判定。

## Metadata
- **Complexity**: Medium
- **Source PRD**: GitHub issue #37（无独立 PRD）
- **PRD Phase**: N/A（standalone）
- **Estimated Files**: 3（hooks/worker_budget.py、scripts/test_worker_budget.py、hooks/lib_kunglao.py）

---

## UX Design

### Before
```
dispatch → worker_budget.pre_check
  check_workers_lt_3 → read_active_workers(analysis_state.txt [active_workers])
                    ↑ reconcile 清零 state → gate 判 0 → 超并发放行 (缺陷)
convergence_check.decide → _scan_active_workers(runs/ status 文件)   ← 另一计数源
```

### After
```
dispatch → worker_budget.pre_check
  check_workers_lt_3 → _scan_status_workers(runs/ + .wt-*/ status 文件)
                    ↑ 与 convergence_check 同源 (status 文件 last=in-progress)
convergence_check.decide → _scan_active_workers(同扫描)              ← 单真相源
analysis_state.txt [active_workers]  → 仅缓存/显示 (gate 不读)
```

### Interaction Changes
| Touchpoint | Before | After | Notes |
|---|---|---|---|
| check_workers_lt_3 读源 | state 段 | status 文件扫描 | 行为变更：不再受 reconcile 清零影响 |
| convergence_check | 已有扫描 | 不变 | 二者计数必须一致 |
| analysis_state.txt | gate 输入 | 纯缓存 | register/remove_worker 保留（写缓存） |

---

## Mandatory Reading

| Priority | File | Lines | Why |
|---|---|---|---|
| P0 | `hooks/worker_budget.py` | 256-270, 466-470, 421-442 | read_active_workers 解析、check_workers_lt_3 调用、register/remove_worker 写缓存 |
| P0 | `scripts/convergence_check.py` | 74-120 | `_scan_active_workers` 完整逻辑（含 .wt-*/ 扫描 + last-status 判定 + STUCK_MINUTES）— 必须镜像 |
| P0 | `hooks/lib_kunglao.py` | 全文 (92 行) | 共享宿主；is_active/resolve_workspace 已在此，扫描函数应迁入 |
| P1 | `scripts/test_worker_budget.py` | 39-65, 173-187 | `_write_state` helper（`[active_workers]` 段格式）、check_workers_lt_3 现有测试（`assert not ok and '3' in msg`） |
| P1 | `tests/conftest.py` | 全文 | tmp/ws_factory fixtures（ws_factory 不含 analysis_state.txt） |
| P2 | `hooks/worker_budget.py` | 670-725 | pre_check checks 列表（'workers' 是第 1 项） |

## External Documentation

| Topic | Source | Key Takeaway |
|---|---|---|
| N/A | — | 无外部研究需要——纯内部重构，镜像既有 `_scan_active_workers` |

---

## Patterns to Mirror

### WORKER_SCAN（唯一真相源 — 从 convergence_check.py:74-120 镜像）
```python
def _scan_active_workers(workspace: Path):
    import re as _re
    _status_line = _re.compile(r"status:\s*(\S+)")
    dirs = [workspace / "runs"]
    try:
        for wt in workspace.parent.glob(".wt-*/malware-analysis-workspace/runs"):
            dirs.append(wt)
    except OSError:
        pass
    active = 0
    stuck = []
    cutoff = timedelta(minutes=STUCK_MINUTES)
    now = utc_now()
    for runs in dirs:
        if not runs.exists():
            continue
        for p in runs.glob("worker-status-*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            last_status = None
            for line in text.splitlines():
                m = _status_line.search(line)
                if m:
                    last_status = m.group(1).lower()
            if last_status != "in-progress":
                continue
            active += 1
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if (now - mtime) > cutoff:
                stuck.append({"worker": p.stem, "age_min": int((now - mtime).total_seconds() // 60)})
    return active, stuck
```
// SOURCE: `scripts/convergence_check.py:74-120`

### GATE_CHECK（tuple 返回 + 消息断言）
```python
def check_workers_lt_3(state_path: Path) -> tuple[bool, str]:
    n = len(read_active_workers(state_path))
    if n >= MAX_WORKERS:
        return (False, f'active_workers={n} >= {MAX_WORKERS}')
    return (True, f'active_workers={n}')
```
// SOURCE: `hooks/worker_budget.py:466-470` — 签名 `(Path) -> tuple[bool, str]` 保留，读源换成扫描

### TEST_HELPERS（tmp_path 合成状态文件）
```python
def _write_state(path: Path, workers=None, deadline=None):
    lines = ['[current_task]', 'sample=488d2dd8', '[/current_task]', '']
    ...
    if workers:
        lines.append('[active_workers]')
        for w in workers:
            tools = ','.join(w.get('tools', []))
            lines.append(f"worker_id={w['worker_id']} | claim_id={w['claim_id']} | "
                         f"dispatched_at={w.get('dispatched_at', 0)} | tier={w.get('tier', 1)} | tools={tools}")
        lines.append('[/active_workers]')
```
// SOURCE: `scripts/test_worker_budget.py:39-55`

### TEST_ASSERT（REJECT 断言模式）
```python
def test_check_workers_lt_3_reject(tmp_path):
    p = tmp_path / 'analysis_state.txt'
    _write_state(p, workers=[...3 workers...])
    ok, msg = check_workers_lt_3(p)
    assert not ok and '3' in msg
```
// SOURCE: `scripts/test_worker_budget.py:181-187`

### FAIL_OPEN（subprocess/文件异常 → 放行）
```python
def check_plan_drift(paths):
    ws = paths.get('workspace')
    if not ws:
        return True, ''
    r = _run_py([...])
    if r is None:
        return True, ''
    ...
```
// SOURCE: `hooks/worker_budget.py:82-90` — 新检查沿用「路径缺失/读取失败 → (True, '')」

---

## Files to Change

| File | Action | Justification |
|---|---|---|
| `hooks/lib_kunglao.py` | UPDATE | 新增 `scan_active_workers(workspace) -> (active, stuck)` 共享宿主（消除双份，convergence_check 后续可引用） |
| `hooks/worker_budget.py` | UPDATE | `check_workers_lt_3` 改用 scan；`_resolve_paths` 已含 `workspace` 键（S 档已加），传参适配 |
| `scripts/test_worker_budget.py` | UPDATE | 新增 status 文件扫描测试；保留旧 state 段测试（缓存写仍在） |

## NOT Building

- 不改 `register_worker` / `remove_worker`（state 段仍是缓存，写路径保留）
- 不动 convergence_check.py（它已是单真相源；仅后续可选引用 lib）
- 不采纳「remove_worker 幂等 + reconcile-at-dispatch」表层补丁（issue 明确否决——reconcile 是 LLM 驱动，不能作 gate 依赖）
- 不改 MAX_WORKERS / STUCK_MINUTES 语义

---

## Step-by-Step Tasks

### Task 1: lib_kunglao.py 新增 scan_active_workers（共享宿主）
- **ACTION**: 在 `hooks/lib_kunglao.py` 新增函数，镜像 convergence_check.py:74-120 的 `_scan_active_workers`
- **IMPLEMENT**:
```python
import re as _re
from datetime import datetime, timedelta, timezone

STUCK_MINUTES = 20  # mirror scripts/convergence_check.py

def scan_active_workers(workspace):
    """Single source of truth for active-worker count (mirrors
    scripts/convergence_check.py:_scan_active_workers). Counts status files
    whose LAST status line is in-progress, in runs/ + .wt-*/ worktrees."""
    _status_line = _re.compile(r"status:\s*(\S+)")
    dirs = [workspace / "runs"]
    try:
        for wt in workspace.parent.glob(".wt-*/malware-analysis-workspace/runs"):
            dirs.append(wt)
    except OSError:
        pass
    active, stuck, cutoff = 0, [], timedelta(minutes=STUCK_MINUTES)
    now = datetime.now(timezone.utc)
    for runs in dirs:
        if not runs.exists():
            continue
        for p in runs.glob("worker-status-*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            last_status = None
            for line in text.splitlines():
                m = _status_line.search(line)
                if m:
                    last_status = m.group(1).lower()
            if last_status != "in-progress":
                continue
            active += 1
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            if (now - mtime) > cutoff:
                stuck.append({"worker": p.stem, "age_min": int((now - mtime).total_seconds() // 60)})
    return active, stuck
```
- **MIRROR**: WORKER_SCAN 模式（convergence_check.py:74-120）
- **IMPORTS**: 文件内已有 pathlib；新增 `import re as _re`、`from datetime import datetime, timedelta, timezone`（放模块顶部）
- **GOTCHA**: 必须是**逐字节等价**的扫描逻辑——否则 gate 与 convergence_check 计数可能不一致（正是 #37 要消除的）。status 判定只看**最后一行** status（worktree 快照带历史文件）
- **VALIDATE**: `python -c "from lib_kunglao import scan_active_workers; print(scan_active_workers)"` 可导入；构造 runs/ 目录 3 个 in-progress 文件 → 返回 (3, [])；1 个 done → 不计

### Task 2: worker_budget.check_workers_lt_3 切读源
- **ACTION**: 把 `check_workers_lt_3` 的读源从 `read_active_workers(state_path)` 换成 `scan_active_workers(workspace)`
- **IMPLEMENT**:
```python
def check_workers_lt_3(paths: dict) -> tuple[bool, str]:
    """Single source of truth (issue #37): count ACTIVE workers from status
    files (lib_kunglao.scan_active_workers), NOT the analysis_state.txt cache.
    FAIL_OPEN: workspace missing / scan unavailable -> allow (cache-only path)."""
    ws = paths.get('workspace')
    if not ws:
        return True, ''
    try:
        sys.path.insert(0, str(_SKILL_ROOT / 'hooks'))
        from lib_kunglao import scan_active_workers
        n, _stuck = scan_active_workers(Path(ws))
    except Exception:
        return True, ''  # FAIL_OPEN — never block dispatch on scan failure
    if n >= MAX_WORKERS:
        return False, f'active_workers={n} >= {MAX_WORKERS}'
    return True, f'active_workers={n}'
```
- **MIRROR**: GATE_CHECK + FAIL_OPEN 模式
- **IMPORTS**: `Path`（已 import）、`sys`（已 import）
- **GOTCHA**: pre_check 调用点 `check_workers_lt_3(paths['state'])` 必须改成传 `paths`（:674）。worker_pulse / 其它 check 不受影响
- **VALIDATE**: 3 个 in-progress status 文件 → `not ok and '3' in msg`；0 个 → ok

### Task 3: test_worker_budget.py 新增 status 扫描测试
- **ACTION**: 在现有测试后追加，镜像 `_write_state` helper + 硬断言风格
- **IMPLEMENT**: 新增 `_write_status(ws, name, last_status)` helper（写 `runs/worker-status-<name>.md`，含 `| status: <last_status>` 行）+ 测试：
```python
def test_check_workers_lt_3_from_status_files(tmp_path):
    """#37: gate counts status files (single source of truth), not state cache."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    _write_status(ws, 'w1', 'in-progress')
    _write_status(ws, 'w2', 'in-progress')
    _write_status(ws, 'w3', 'in-progress')
    ok, msg = check_workers_lt_3({'workspace': str(ws)})
    assert not ok and '3' in msg

def test_check_workers_lt_3_empty_state_cache(tmp_path):
    """#37: empty [active_workers] cache must NOT fool the gate."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    _write_status(ws, 'w1', 'in-progress')
    _write_state(ws / 'analysis_state.txt')  # no active_workers segment
    ok, msg = check_workers_lt_3({'workspace': str(ws)})
    assert ok  # 1 active via status file, < 3

def test_check_workers_lt_3_ignores_done(tmp_path):
    """#37: done status files do NOT occupy slots."""
    ws = tmp_path / 'ws'
    (ws / 'runs').mkdir(parents=True)
    _write_status(ws, 'w1', 'in-progress')
    _write_status(ws, 'w2', 'done')
    ok, msg = check_workers_lt_3({'workspace': str(ws)})
    assert ok
```
- **MIRROR**: TEST_HELPERS + TEST_ASSERT
- **IMPORTS**: 已有 `check_workers_lt_3` 导入（:19-32）；不需要新导入
- **GOTCHA**: 现有 `test_check_workers_lt_3_ok/reject` 传 `Path`（state_path）——新签名为 dict，**必须同步改旧测试传 `{'workspace': str(p.parent)}`**，否则旧测试炸。这是签名变更，不是纯追加
- **VALIDATE**: `python scripts/test_worker_budget.py` → 30 旧 + 3 新全过（issue 验收 25/25 指旧计数，实际 33）

### Task 4: pre_check 调用点适配 + 回归
- **ACTION**: pre_check :674 改为 `check_workers_lt_3(paths)`；跑全量测试
- **IMPLEMENT**: `('workers', check_workers_lt_3(paths)),`（替换 `check_workers_lt_3(paths['state'])`）
- **MIRROR**: GATE_CHECK（checks 列表第一项，:673-688）
- **IMPORTS**: 无
- **GOTCHA**: worker_pulse.py 不直接调 check_workers_lt_3（它跑 convergence_check），无需动
- **VALIDATE**: `python scripts/test_v1_8_enforcement_gates.py` → 31/31；`python scripts/test_worker_budget.py` → 33/33；`python -m pytest tests/ -q` → 无回归

---

## Testing Strategy

### Unit Tests

| Test | Input | Expected Output | Edge Case? |
|---|---|---|---|
| test_check_workers_lt_3_from_status_files | 3 in-progress status 文件 | `not ok and '3' in msg` | 边界 3 满 |
| test_check_workers_lt_3_empty_state_cache | 1 in-progress + state 段空 | ok（1 < 3） | 缓存清零 |
| test_check_workers_lt_3_ignores_done | 1 in-progress + 1 done | ok | last-status 判定 |
| test_check_workers_lt_3_ok/reject（旧） | Path → dict 适配 | 同前 | 签名迁移 |

### Edge Cases Checklist
- [x] 空 runs/ 目录 → ok
- [x] state 段空 → 仍按 status 文件判（核心用例）
- [x] worktree .wt-*/ 下的 status 文件 → 计入（scan 已含）
- [x] 无 workspace 键（FAIL_OPEN）→ 放行
- [ ] status 文件无 status 行 → 不计（scan 语义）
- [ ] 并发访问（gate 与 convergence_check 同时扫）→ 只读无写，天然安全

---

## Validation Commands

### Unit Tests
```bash
cd C:/Users/hr/.claude/kunglao-remote-dev
python scripts/test_worker_budget.py
```
EXPECT: 33/33 passed

### Full Test Suite
```bash
python scripts/test_v1_8_enforcement_gates.py   # 31/31
python scripts/test_status_defs.py               # 26/26
python -m pytest tests/ -q                       # 无回归
```
EXPECT: 全绿

### Manual Validation
- [ ] 构造 3 个 in-progress status 文件 + 空 state 段 → `check_workers_lt_3` REJECT（`active_workers=3 >= 3`）
- [ ] `convergence_check.py <ws>` 与 gate 对同一 runs/ 返回相同 active 计数

---

## Acceptance Criteria
- [x] gate 与 convergence_check 同源计数（同一 runs/ 目录相同 active）
- [x] state 块空时 gate 仍正确
- [x] test_worker_budget 全过（30 旧 + 3 新）
- [x] test_v1_8_enforcement_gates 31/31（无回归）
- [x] FAIL_OPEN 保留（脚本/目录异常 → 放行）

## Completion Checklist
- [x] 扫描逻辑与 convergence_check 逐字节等价（镜像而非重写）
- [x] 旧测试同步迁移签名（非纯追加）
- [x] state 段写路径（register/remove_worker）不动
- [x] 无多余 scope（不做 reconcile-at-dispatch）

## Risks
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| 扫描逻辑与 convergence_check 漂移 | Low | gate 与决策不一致 | 镜像逐字节 + 验收里「同 runs/ 同计数」校验 |
| 旧测试签名迁移遗漏 | Medium | test_worker_budget 红 | Task 3 显式列旧测试同步改 |
| worktree 扫描性能（每派发一次 glob） | Low | 微秒级 | 与 convergence_check 同构，可接受 |

## Notes
- issue 验收的「25/25」是旧测试数快照；实际 dev 基线 test_worker_budget.py 有 30 个 test_*（explore agent 实测）
- `lib_kunglao.py` 尚无 active-workers 能力（explore agent A3 确认）——本计划首次引入
- `_scan_active_workers` 目前无单测（explore agent A4）——本计划顺带给共享函数提供测试覆盖
