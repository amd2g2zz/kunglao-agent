# Design — worker-liveness single source of truth (#444)

## 问题边界

"Worker 活性解析" = 对 `runs/worker-status-*.md`(append-only 日志)提取
**尾行 `status:` token** 判定 in-progress / done / blocked。两种行形态都合法:
管道内嵌 `"[ts] step: ... | status: done"` 与专用行 `"status: done"`;
取**最后一个** token(wins)。

**不是**本协议(范围外,保持不动):
- `backtrack_gate.py` 的 `## Status` 段落格式(另一种文件协议,#444 前已判定范围外);
- claim-register.yaml 的块内 `status:` 字段(state_anchor / kunglao_record /
  kunglao_status._claim_statuses / event_taxonomy._claim_statuses — YAML 块协议);
- facts 头部 `status:`(migrate_facts);
- `analysis_state.txt` 的 `[active_workers]` 段(worker_budget 的 write-side
  记账缓存:#37 之后它不再参与活性判定,是 dispatch 记账,不是第二解析)。

## D1. 单一协议落在哪:`hooks/lib_kunglao.py`

选 **hooks/lib_kunglao.py** 为唯一解析点,理由:

1. #37 已把它宣告为活性单一真相源,hook 层(worker_budget.check_workers_lt_3)
   已经直接 `from lib_kunglao import scan_active_workers` 消费——把协议
   "解析+聚合+W-15"全部放这里,gate 层零接线变化。
2. 反方向(放 scripts/lib_kunglao.py)会让 hooks/lib_kunglao.scan_active_workers
   变成二传手,且 hooks 侧仍需 by-path 加载器,不省任何东西。
3. `importlib.util.spec_from_file_location` + 唯一模块名是仓库既有跨域惯例
   (external_kicker.py:326-340 / state_anchor.py:_load_drift_lib /
   tests/test_drift_detection.py,均用唯一名 `lib_kunglao_scripts`)。原因:
   pytest.ini `pythonpath = . hooks scripts ...` 使裸名 `import lib_kunglao`
   在 hooks/ 与 scripts/ 两个同名模块间二义。scripts 侧消费者用同样的
   by-path 加载,唯一名 **`lib_kunglao_hooks`**(所有消费者同名 → 同进程
   共享同一模块实例)。

### canonical API(hooks/lib_kunglao.py)

```python
WORKER_STATUS_RE = re.compile(r"status:\s*(\S+)")   # 全仓库唯一一份
ARTIFACTS_RE     = re.compile(r"^\s*artifacts?\s*:\s*(.*)$", re.I | re.M)

def parse_worker_status_tokens(text) -> list[str]   # 逐 token,小写,保序
def parse_worker_status(text) -> str | None         # tokens[-1] or None
def parse_declared_artifacts(text) -> list[str]     # artifacts: 行 → 路径列表
def iter_worker_states(workspace) -> list[dict]     # 单次读文件:file/root/status/mtime/artifacts
def scan_active_workers(workspace) -> (int, list)   # 签名与输出逐字节不变(#37 兼容)
def scan_done_artifact_violations(workspace) -> list[dict]   # W-15
```

`iter_worker_states` 固化扫描目标规则(v1.9.13 worktree 隔离):
`workspace/runs` + 每个 `.wt-*/.kunglao-worktree` 标记的
`malware-analysis-workspace/runs`;每文件一次读取,同时提取 token 与
artifacts 声明;OSError 逐文件跳过(fail-open 单文件,不 fail 全扫描)。

## D2. convergence_check 与 worker_budget 如何变消费方

- **convergence_check**(咨询层):模块内加 `_load_worker_lib()`(by-path,
  唯一名 `lib_kunglao_hooks`,同 external_kicker 模式);
  `_scan_active_workers(workspace)` 保留函数名与 `(active, stuck)` 签名
  (tests/test_worktree_marker.py 直接 import 它),变薄壳;
  新增 `_scan_workers(workspace) -> (active, stuck, w15_violations)`;
  `decide()` 改调 `_scan_workers`(仅换数据来源,**分支结构零变化**——#443
  范围),输出 dict 新增诊断字段 `done_artifact_violations`
  (schemas/convergence-check-output.json 顶层 additionalProperties: true,
  不需要 schema 变更);`_human()` 新增可选展示行。加载失败 raise
  RuntimeError 并带修复指引——hooks/ 与 scripts/ 同仓同装,缺文件=装坏了,
  静默回退到本地拷贝等于复活双表示。
- **worker_budget**(hook 层):**零代码改动**。它已是消费方
  (`from lib_kunglao import scan_active_workers`);协议扩展发生在它导入的
  同一模块内。
- 其余消费者(全部 by-path / 就近导入 canonical parse):
  - `worker_pulse`:_check_stale_workers / _delivery_reminder 删除自有
    STATUS_RE / FINAL_STATUS_RE,消费 parse_worker_status(_tokens);
    _build_pulse flags 透出 `w15=[workers]`。
  - `scripts/lib_kunglao.workers_progressing`:删除 _STATUS_RE,消费
    parse_worker_status(漂移语义 D3 不变)。
  - `external_kicker.has_fresh_workers`:删除 _STATUS_RE,消费
    parse_worker_status(单 runs_dir 扫描目标是调用方语义,保留)。
  - `event_taxonomy._worker_events`:消费 parse_worker_status_tokens
    (first=started / last=state 语义不变)。
  - `kunglao_status._worker_lines`:消费 parse_worker_status。

### 语义对齐(有意的行为修正,非回归)

worker_pulse 旧 `STATUS_RE` 是行首锚定 `^\s*status`,管道内嵌形态不命中
(其注释却声称同 lib_kunglao 约定)。统一到 canonical 非锚定尾行规则后
_check_stale_workers 能看见管道内嵌形态——这是双表示漂移的修复本身;
既有测试(test_stuck_gate 用专用行形态、test_worker_budget 用管道形态)
在非锚定规则下全部仍然通过(非锚定是两种形态的超集)。

## D3. W-15 交叉验证在哪层做

**协议层(lib)算,hook/咨询两层透出**——不在 pre_check 加新 REJECT 门
(那会改 hooks 行为面,且 done-无文件是"完成质量"信号,不是"该不该派发"
信号;先以诊断字段进 pulse/decide,#443 重构 decide 时再决定是否升级语义)。

机器路径:
1. **maker 侧**:`agents/kunglao-worker.md` 规则 #4 增补——status 翻 done 时
   同文件必须带 `artifacts: <paths>` 声明(相对各自 workspace 根);
   `artifacts: none` = 显式承认零产物(按 W-15 判 FAILED)。
2. **协议层**:`scan_done_artifact_violations(workspace)`:
   - last status == done 且声明了 artifacts 且有路径缺失 →
     `{"worker", "kind": "declared-missing", "missing": [...]}`;
   - last status == done 且声明为显式 none → `{"kind": "done-no-files"}`;
   - 相对路径按该 status 文件的**归属根**解析(主 workspace runs/ → 主根;
     .wt-* worktree runs/ → 该 worktree 的 malware-analysis-workspace 根,
     合并前后都能判);绝对路径按原样判存。
3. **咨询层**:decide() 诊断字段 + `_human()` 行。
4. **hook 层**:worker_pulse 在 worker 完成瞬间(convergence_check --json)
   把 `w15=` 透出给 orchestrator——正是"报 done"被复核的时刻。

## D4. 迁移期兼容(旧 status 文件仍可读)

- 旧文件(无 `artifacts:` 行):解析、活性判定、stuck 判定完全不变;
  W-15 检查跳过(opt-in:声明了才校验)——历史工作区不会因新检查亮红。
- `artifacts:` 是新增声明语法,只由新约定的 worker 写出;声明 `none` 是
  诚实失败信号,不是豁免。
- `scan_active_workers` 输出形状逐字节不变(active int + stuck
  {"worker", "age_min"}),kunglao-decide 的 `stale` 派生与 worker_pulse 的
  `stuck=` flag 均不受影响。

## D5. 验收 → 测试映射(见 tasks.md)

| #444 验收 | 测试 |
|---|---|
| 全仓库仅一处解析(grep 可验证) | `test_worker_liveness_protocol.py::test_single_parse_point_grep`(扫描 repo 全部 .py:同时引用 worker-status 文件 + 自带 status-token regex 编译 = 违规;唯一豁免 hooks/state_anchor.py——claim-register 块协议)+ 静态接线断言(每个消费方文件引用 canonical 入口) |
| "报 done 无产物文件"机器检查+测试 | `test_w15_*`(declared-missing / all-present / legacy-exempt / explicit-none / in-progress-exempt / absolute-path)+ `test_decide_exposes_w15` + `test_worker_pulse_flags_w15` |
| 两层一致性 CI 断言 | `test_two_layer_consistency`(同一 fixture:decide().active_workers == check_workers_lt_3 计数)+ `test_two_layers_share_one_protocol_source`(静态:worker_budget.py 含 canonical import;convergence_check.py 含 lib_kunglao_hooks 加载器) |

fixture 刻意混两种行形态(管道内嵌 + 专用行)+ .wt-* worktree——任何
一方重新长出私有解析(尤其锚定变体)立即失配。

## Rejected

- **R1 新建顶层共享模块**(如 `worker_liveness.py` 于仓库根):两个 sys.path
  域都要各自插根路径,新文件新约定,收益为零;扩展 #37 已宣告的 lib 即可。
- **R2 删除 `[active_workers]` 段协议**:它是 dispatch 记账(write-side),
  #37 后不参与活性判定;删除改变 hook 行为面,超出 #444。
- **R3 把 W-15 做成 pre_check REJECT 门**:改派发行为面;done-无文件是
  完成质量诊断,先走诊断通道,#443 重构 decide 时再定升降级。
- **R4 动 decide() 分支结构**:#443 明确范围;本变更只加数据源与诊断字段。
- **R5 动 hooks 注册 / worker_budget 接线**:#445 范围;worker_budget 零改动。
- **R6 把 backtrack_gate 的 `## Status` 段解析并入**:另一种文件协议
  (段首标记,非尾行 token),字段语义不同;并入=错误抽象。维持范围外。
- **R7 scripts 侧裸名 `import lib_kunglao`**:pytest pythonpath 下二义
  (hooks 先解析),by-path 唯一名是仓库已验证的安全模式。
