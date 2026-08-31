# Tasks — issue-444-worker-liveness

## 1. Setup

- [x] 1.1 Worktree `D:/works/kunglao-wt/444` branch `v012/issue-444-worker-liveness` off `dev` 6462fe4
- [x] 1.2 必读:plan / issue #444 / convergence_check.py:83-133 / lib_kunglao×2 / worker_budget.py:270-307 / worker_pulse / state_anchor;边界判定(backtrack_gate `## Status` 段=范围外)保留

## 2. SDD

- [x] 2.1 proposal.md(双表示证据 + W-15 未编码 + 改动面)
- [x] 2.2 design.md(D1 协议落点 / D2 消费方 / D3 W-15 层次 / D4 迁移兼容 / D5 验收映射 / R1-R7)
- [x] 2.3 tasks.md(本文件)

## 3. RED(先写,必须红)

- [x] 3.1 `tests/test_worker_liveness_protocol.py::test_single_parse_point_grep` — 全仓库扫描,现应报 7 处解析(红)
- [x] 3.2 `test_w15_*` 六例 + `test_decide_exposes_w15` + `test_worker_pulse_flags_w15` — canonical 函数不存在(红)
- [x] 3.3 `test_two_layer_consistency` / `test_two_layers_share_one_protocol_source` — 接线断言失败(红)
- [x] 3.4 确认 RED:uv run --project . python -m pytest -q tests/test_worker_liveness_protocol.py(13 failed / 1 passed,commit 2a9cfa4)

## 4. GREEN

- [x] 4.1 hooks/lib_kunglao.py:WORKER_STATUS_RE / ARTIFACTS_RE / parse_worker_status_tokens / parse_worker_status / parse_declared_artifacts / iter_worker_states / scan_active_workers(输出不变)/ scan_done_artifact_violations
- [x] 4.2 convergence_check:_load_worker_lib + _scan_workers + _scan_active_workers 薄壳 + decide() 数据源切换(分支零变化)+ done_artifact_violations 字段 + _human 行 + kunglao-decide docstring 清单 +1
- [x] 4.3 worker_pulse / scripts/lib_kunglao / external_kicker(has_fresh_workers + _in_progress_workers)/ event_taxonomy / kunglao_status / reconcile_workers 消费 canonical parse,删除各自 regex
- [x] 4.4 agents/kunglao-worker.md 规则 #4:artifacts 声明约定(+ State-write protocol 回指)
- [x] 4.5 快速门:uv run --project . python -m pytest -q -m "not load_sensitive" — 1966 passed / 14 failed(14 个环境性失败在 pre-GREEN 基线 stash 对照中同样失败,见 RUNBOOK)

## 5. REFACTOR + 回归锚定

- [x] 5.1 复跑快速门 + 既有 convergence/hooks 测试零回归(14 个受影响模块测试文件 168/168 绿;decide() 既有字段与分支逐 case 不变,新增字段仅 done_artifact_violations)
- [x] 5.2 grep 断言豁免仅剩 claim-register 块协议两处:state_anchor(_CLAIM_STATUS_RE)与 external_kicker(_RESUME_CLAIM_STATUS_RE,与 _RESUME_CLAIM_ID_RE 配对解析 claim-register 块,非 worker-status 尾行协议;其 worker-status 解析已被 WIRING 断言锚定到 canonical)

## 6. 产出

- [x] 6.1 `.review/RUNBOOK.md`(改动清单 / 测试映射 / 门禁结果 / 兼容性 / 自认风险 / 复现命令)

## 7. 评审修复(REVIEW.md F-1,post-cd28ab4)

- [x] 7.1 RED:`test_progress_report_counts_append_only_done_as_inactive`(done-with-history 文件被 substring 计 active,实证 `2 in-flight`)+ 谓词 substring 形态命中 + WIRING 缺失 → 3 failed
- [x] 7.2 GREEN:`scripts/progress_report.py` 删 substring 逻辑,吃 `iter_worker_states`(stuck 保持 mtime-only advisory)
- [x] 7.3 WIRING 8→9(progress_report 锚定 `lib_kunglao_hooks`);grep 谓词补 substring 形态(`"in-progress" in` / `.find("in-progress")`)
- [x] 7.4 第 10 处排查:全仓 substring/regex/引用交叉扫描,无;kunglao-monitor 补记台账(O5,backtrack_gate 协议消费方)
- [x] 7.5 RUNBOOK:风险 6 措辞修正(假设性→已发生,记录修复)、验收表/WIRING/复现命令更新
- [x] 7.6 快速门复跑(见 RUNBOOK 门禁结果节)
