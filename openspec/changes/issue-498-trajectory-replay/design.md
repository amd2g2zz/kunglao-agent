# Design — trajectory replay e2e (#498 收尾件)

## 问题边界

本件 = #498 验收方法 D 的固化: 把 v0.1.1 双轨迹(判死链 / plan-stall)
+ 心跳自活 + 看牌四场景写成 `tests/test_trajectory_replay.py`。
**零器官改动** — 五个器官(#495/#496/#497/#461/#443+#466)只消费不重写。
若组装暴露器官缺陷: 记录回报, 拆 follow-up。

## D1. e2e 纪律 — 真实 CLI/subprocess, 不 mock 器官内部

单级测试(#497/#495/#496/#461 各自)已覆盖函数级契约; 本件的价值在
**接力顺序**: 事件按 v0.1.1 现场序列发生, 断言的是每一道闸的输出成为
下一道闸的输入。因此:

- 所有器官经 `subprocess.run([sys.executable, <script>, ...])` 调用 —
  真实进程边界、真实 exit code、真实 stderr/stdout(镜像
  `test_failure_analysis_transducer.test_cli_*` 与
  `test_decision_teeth._run_gate` 的既有模式);
- 断言面向**可观察输出**(rc / stderr 关键词 / 落盘文件形状), 不 import
  器官内部函数做白盒断言(唯一例外: 时间戳新鲜度用测试侧 datetime 解析,
  这是读产物不是 mock);
- fixture 全合成(claim-register / analyses / .hook_state / task_spec),
  零真实样本、零真实 VM。

## D2. 轨迹1 判死链 — 拦截 → 转导 → 复活(非死局)

GIVEN(合成, 等价类而非逐字):

```
claim-register.yaml: C-1 OPEN promotion_attempts=2 (瞬态失败×2)
analyses/failure-C-1.yaml: covers_attempt=2, 三问题有答, 三产物缺失
  (v0.1.1 形态: 证据活在 prose 里, 没转导)
```

WHEN/THEN(全 subprocess):

| 步 | 命令 | 断言 |
|---|---|---|
| 判死宣告 | `ask_for_direction_gate.py <ws> "…spawn 超时两次。这条路走不通…"` | rc=1; stdout 含梯指引(ladder/梯) — TYPE_E 拦, 非终局 |
| 复查 | `failure_analysis_gate.py <ws>` | rc=1; BLOCKED + missing 产物名 |
| 补三产物 | `… C-1 --record --assumption … --validity not-justified --next-method "listen mode…" --validated-capability "frida 桥✓…" --identified-obstacle "spawn 超时…" --source lesson-hit --library <空tmp>` | rc=0 RECORDED; register 出现 origin=failure-obstacle / obstacle_for=C-1 新 claim; claim_deps 真边 |
| 下一步 | `convergence_check.py <ws> --json` + `kunglao_resume.py <ws> --json` | decision=DISPATCH (exit 1); resume next_step 含 "dispatch the scripts/priority.py top claim" — 有 open claim → 派发, 不是死局 |

`--library` 指 tmp 空目录: method-ladder lessons rung 跑过但零命中
(fail-open), 记录不被库缺失阻塞。

## D3. 轨迹2 plan-stall + 能力成就 → 看牌

两段:

1. **搁浅段**(独立 ws, 无状态): 先一轮含动作叙事的输出(动作史, rc=0,
   tool-action 事件入 self_redirects 流), 再里程碑总结 + "下一步:" 且
   后续零动作 → ask gate rc=1, stdout 含 "Type B"(等价类框架)。
   F1 语义被此序列覆盖: 预声明动作史不清窗(warm history 不祖父放行)。
2. **看牌段**(`malware-analysis-workspace` 形状, 镜像
   `test_decision_teeth._capability_ws`): 能力成就文本("frida✓ …")对应
   的 `validated_capability` 已落 `analyses/failure-C-1.yaml`(method D:
   "总结里的能力成就落为 validated_capability 事实")→ 换工具
   `[T2 tools=rev-xposed] claim C-1` 经 dispatch_gate → rc=2, stderr
   `REJECT capability` 且含 "frida", stdout 指引含 `capability-disproof`。

## D4. 心跳自活 e2e — init 自举复验

#461 已在源码级钉死"init 成功 → 心跳 + 全 wire-up, 零手动 6 步"; 本场景
做 **e2e 复验**(同一 hermetic seam, 镜像 `test_heartbeat_bootstrap
._run_init`): `--type windows --skip-toolchain --profile-root <tmp>` +
fake `KUNGLAO_CLAUDE_JSON` + 空 PATH + agent-teams flag=0。

断言: `runs/.heartbeat.json` 存在、`last_tick_ts|started_ts` 新鲜
(< 35 min, 35 = 仓库级活性线)、`loop_registered` 键存在(init 从不伪造
cron 注册); 测试全程零 `hook_activation` 调用(构建性事实 — 测试体不
出现该命令)。cron 未注册(loop_registered=false, init 的诚实状态)→
`heartbeat_loop_prompt.py --verify` rc=1 + stderr 含 CronCreate 指引
(HARD, 非静默)。

## D5. 命名与验收映射(计划方法 D 的 -k 选择器)

| 场景 | 测试名含 | 方法 D 行 |
|---|---|---|
| 轨迹1 | `trajectory1` | 判死链 |
| 轨迹2 | `trajectory2` | plan-stall |
| 心跳 | `heartbeat` | 心跳自活 |
| 看牌 | `capability_card` | 看牌(变体: disproof 放行留痕) |

## R1-R4

- R1 e2e 慢: 每场景独立 tmp workspace, 无跨场景共享状态; init 场景
  timeout 180s(镜像 #461), 其余 60s。
- R2 Windows 编码: subprocess 统一 `encoding="utf-8", errors="replace"`
  (中文宣告文本往返; conftest golden_master 同款)。
- R3 过拟合: 判死文本取 #497 参数化族的一个代表 + zh/en 各一(轨迹2),
  不逐字复刻现场叙事。
- R4 器官缺陷: 组装中发现 → 记录到本件 RUNBOOK 自认风险, 回报拆
  follow-up, 不修器官。
