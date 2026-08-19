# Quality Roadmap — issue #463 (v0.1.2 修正版)

> **核心原则**:覆盖率 / 测试数 / Unit Test 数量是**观测**,不是目标。
> 真实 KPI:First-Pass Acceptance / Defect Escape / Regression / Rework。
> 故障注入是 4-gate 的关键技术,不是独立 KPI。

## KPI 跟踪

| Release | First-Pass Acceptance | Defect Escape | Regression | Rework |
|---|---|---|---|---|
| v0.1 (2026-08-16) | TBD | TBD | TBD | TBD |
| v0.1.1 (2026-08-17) | TBD | TBD | TBD | TBD |
| v0.1.2 (in flight) | TBD | TBD | TBD | TBD |

详见 `docs/defect_escape_rate.md` 季度更新。

## 4 Gates + 故障注入 横切

```
                Gate 1 (需求)  Gate 2 (回归)  Gate 3 (工程)  Gate 4 (测试)
                    │              │              │              │
                    ▼              ▼              ▼              ▼
   故障注入 �──── 验证 X 故障下需求仍正确 ──┐
                                          │
                注入方式:                 ┘
                  • 网络失败 (timeout/disconnect/drop)
                  • 进程失败 (crash/hang/kill -9)
                  • 文件系统失败 (missing/permission/full)
                  • API 失败 (5xx/malformed/timeout)
                  • 资源耗尽 (OOM/CPU/fd)
                  • MCP/工具失败 (subprocess / bridge drop)
```

### 故障注入与 4 Gate 的映射

| 故障类型 | Gate 1 (需求) | Gate 2 (回归) | Gate 4 (测试) |
|---|---|---|---|
| 网络 timeout | "重试 N 次后降级" | 历史 timeout 回归 | fault-injection test 覆盖 |
| 进程 crash | "worker exit 后重新派发" | 历史 crash 回归 | SIGKILL mid-execution |
| API 5xx | "5xx → 标记 worker fail" | 历史 5xx 回归 | mock 5xx 注入 |
| 资源耗尽 | "OOM → checkpoint 写盘" | 历史 OOM 回归 | memory limit fixture |
| MCP 断连 | "重连 + backoff" | 历史断连回归 | mock bridge drop |

## Observation-only 指标(非 KPI)

### Coverage (Global, scripts/ + hooks/)

```
Baseline (2026-08-19): 68%  (13711 stmts, 4434 miss)
```

Coverage 仅用于:
- 长期监控(看是否漂移)
- 关键路径覆盖辅助判断
- **不**作为优化目标;**不**从 68% → 75% → 85% 这样爬

### Test Case Count

```
Baseline (2026-08-19): ~155 files, 2161 tests (含 skipped)
```

仅统计,不是 KPI。

### Pass Rate

```
Baseline (2026-08-19): 99.06% (2141/(2141+15+5))
```

Pass Rate 是 Gate 2 指标。**不**作为主优化目标。
高 Pass Rate 可能源于"测试不够严"。必须配合 Mutation + 故障注入看。

## Top 10 low-coverage modules (观察,非目标)

| module | stmts | miss | cov% |
|---|---|---|---|
| `scripts/toolchain.py` | 355 | 158 | 55% |
| `scripts/template_gen.py` | 68 | 68 | **0%** |
| `scripts/troubleshooting_gate.py` | 66 | 38 | 42% |
| `scripts/structural_check.py` | 86 | 38 | 56% |
| `scripts/toolchain_install.py` | 145 | 54 | 63% |
| `scripts/release_receipt.py` | ? | ? | ? |
| `scripts/log_setup.py` | 68 | 68 | 0% (新加,有 test) |

**注意**:Coverage 低 ≠ 需要补测。
- 是否补测取决于该模块是否是**关键路径 / 错误敏感代码**
- 不是所有低 Coverage 都该补;**优先用 Mutation Testing + 故障注入验证关键路径有效性**

## Gate 落地状态

| Gate | Phase 1 (this PR) | Phase 2 | Phase 3 |
|---|---|---|---|
| 1 需求正确性 | 文档化 | Acceptance 模板 | Acceptance 自动跑 |
| 2 回归安全 | 跑 pytest(已有) | 独立 job + 历史 bug suite | 全 release 自动回归 |
| 3 工程质量 | 文档化 + CI lint | radon / bandit / 复杂度 | 架构规则自动 |
| 4 测试有效性 | mutmut 接入 + 本地跑 | PR diff 自动 mutation | 全仓 mutation 趋势 |
| **故障注入** | **kill -9 / timeout / OOM fixtures 文档化** | **CI 自动注入关键路径** | **混沌工程常态化** |

## 何时停止扩张测试

如果出现以下任一信号,**停止增加测试**,重新评估测试策略:

- [ ] First-Pass Acceptance Rate 持平或下降
- [ ] Defect 没有下降(持平或上升)
- [ ] Regression Rate 持平或上升
- [ ] Rework Rate 上升
- [ ] 测试数量增长但 Mutation Score 没增
- [ ] 故障注入发现新缺陷但没有被修复(测试盲区)

## 见

- `devkit/docs/quality_gates.md` — 4-gate 框架 + 故障注入(必读)
- `devkit/docs/defect_escape_rate.md` — Defect Escape 跟踪
- `openspec/changes/issue-463-coverage-gate/` — 完整 spec/design/tasks
