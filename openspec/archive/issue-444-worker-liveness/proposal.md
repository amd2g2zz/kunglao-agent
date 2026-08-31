# Worker Liveness Single Source of Truth + W-15 Cross-Validation (#444)

## Why

Issue #444 (milestone v0.1.2, D1 机制增殖): worker 活性 ("谁在跑") 在仓库里有
**两套以上表示**,同一事实各自解析、同步靠约定:

- `scripts/convergence_check.py:_scan_active_workers` 自带 `import re as _re`
  局部正则(表示 A);
- `hooks/lib_kunglao.py:scan_active_workers` 是它的 "byte-for-byte mirror"
  (#37)——镜像 = 物理两份拷贝,正是双表示;
- `hooks/worker_pulse.py`(STATUS_RE 行首锚定 + FINAL_STATUS_RE)、
  `scripts/lib_kunglao.py:workers_progressing`(_STATUS_RE)、
  `scripts/external_kicker.py:has_fresh_workers`(_STATUS_RE)、
  `scripts/event_taxonomy.py`(_worker_events)、
  `scripts/kunglao_status.py`(_worker_lines)各持一份
  `status:\s*(\S+)` 解析。

后果已在代码里可见:worker_pulse 的 `STATUS_RE` 用 `^\s*status` 行首锚定,
对真实管道内嵌格式 `"[ts] step: ... | status: in-progress"` 不命中——它的
注释声称遵循 lib_kunglao 约定,实现却没有(双表示漂移的实存样本)。

W-15 教训("a worker that reports 'done' without files has FAILED")只活在
`agents/kunglao-worker.md` 散文里,`_scan_active_workers` 函数体内无任何
产物文件存在性检查——报 done 无文件的 worker 永远不被复核。

## What Changes

- **单一协议**:`hooks/lib_kunglao.py` 扩展为 worker-status 协议的唯一解析点
  (parse + scan + W-15 一体)。它已是 #37 宣告的 gate 层活性单一真相源,
  worker_budget 直接消费它;本变更把"镜像拷贝"换成真正的唯一实现。
- **消费方改造**(7 处解析 → 1 处实现 + 6 个消费方):
  `convergence_check._scan_active_workers` 变委托薄壳;`worker_pulse` /
  `scripts/lib_kunglao.workers_progressing` / `external_kicker.has_fresh_workers` /
  `event_taxonomy._worker_events` / `kunglao_status._worker_lines` 全部消费
  canonical `parse_worker_status(_tokens)`。
- **W-15 机器检查**:done 判定绑定产物存在性——status 文件里 `artifacts:`
  声明行(新约定,worker 侧由 agents/kunglao-worker.md 编码)列出产物路径;
  `scan_done_artifact_violations()` 校验声明路径存在;convergence_check 输出
  新诊断字段 `done_artifact_violations`(不动 decide() 分支结构,#443 范围);
  worker_pulse 在 flags 行透出 `w15=`。
- **两层一致性 CI 断言**:新测试文件
  `tests/test_worker_liveness_protocol.py`——(a) grep 断言全仓库仅一处解析;
  (b) W-15 行为测试;(c) 咨询层(convergence_check)与 hook 层
  (worker_budget.check_workers_lt_3)在同一 fixture 上活性计数相等 + 静态
  接线断言(双方都引用 canonical 协议)。

## Impact

- **代码**:`hooks/lib_kunglao.py`(协议扩展)、`scripts/convergence_check.py`、
  `hooks/worker_pulse.py`、`hooks/worker_budget.py`(零改动——已是消费方)、
  `scripts/lib_kunglao.py`、`scripts/external_kicker.py`、
  `scripts/event_taxonomy.py`、`scripts/kunglao_status.py`、
  `agents/kunglao-worker.md`(W-15 声明约定,3 行)、
  `scripts/kunglao-decide.py`(docstring 字段清单 +1)。
- **测试**:新增 `tests/test_worker_liveness_protocol.py`;既有测试零回归
  (decide() 输出既有字段逐 case 不变)。
- **不做**(见 design.md R1-R6):backtrack_gate 的 `## Status` 段格式是另一种
  文件协议,范围外;decide() 分支结构不动(#443);hooks 注册不动(#445);
  `[active_workers]` 段协议是 write-side 记账缓存,不是活性解析,不删。

需求源: issue #444 (github.com/amd2g2zz/kunglao-agent/issues/444)
