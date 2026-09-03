# Design — heartbeat bootstrap (#461)

## 问题边界

本变更只做三件事:派发事件驱动生命周期(联动)、init 成功路径自活
(bootstrap)、cron 注册可验收(HARD)。明确不做:决策面改造(#497)、
失败转导(#495)、观测面板(#459 的展示侧)、活性表示第四套(#446 F 红线)。
所有落点复用既有机制:`.hook_state.json`(激活状态)、
`runs/.heartbeat.json`(心跳)、`runs/logs/kunglao-*.jsonl`(统一事件
日志)、`kunglao_log.emit`(事件写入门)。

## D1. 派发联动落点:`hook_activation.dispatch_linkage` + worker_budget 调用侧

**为什么在 hook_activation**:续期入口 `renew()` 本就住在这里(#461
要求"调用 hook_activation 的续期入口,复用现有函数");状态机写操作
(`update_state`/`write_state`)同模块,联动 = 它们的组合,不新增机制。

```python
DISPATCH_HOOKS = ("dispatch_gate", "worker_pulse")   # 派发路径的执法对

def dispatch_linkage(workspace, ttl_minutes=DEFAULT_TTL_MINUTES) -> dict:
    # 冷状态: update_state 引导 tier="none" 全集(含执法对)
    # 有状态: 补全 active_hooks(尊重 user_override=off)/ 移出 paused_hooks
    # phase -> "DISPATCH"(状态机语汇的 RUNNING;issue 原文 IDLE→RUNNING)
    # write_state 后调用 renew():盖新 TTL + 刷新 .heartbeat.json last_tick_ts
```

**为什么在 worker_budget.pre_check 尾部调用**:它是 PreToolUse(Agent)
的批准点 — 全部 17 项 gate 通过 = 派发获批。REJECT 路径不联动(被拒
派发不是生命周期事件;其观测归 #459)。联动失败 fail-open + stderr
WARN:联动是活性/可观测性,不得反过来阻塞已获批派发;fail-closed 由
TTL 自然到期承担(联动坏了 → 30min 后 hooks 睡 → dispatch_gate 拒)。

**事件**:批准后 `kunglao_log.emit(ws, 'hook:worker_budget', 'dispatch',
claim=C-NN, detail='tier=… tools=… agent=…')`。`action="dispatch"` 是
kunglao_log 文档词表内的既有动作类;`kunglao_log` 永不 raise(写失败降级
stderr WARN)。worker in flight 的活性真相仍是 worker-status 文件
(#444 canonical)— 事件是时间线,不是第四套活性表示。

## D2. init 集成:`bootstrap_observability` 于每个 exit-0 路径最后一步

三个 exit-0 点:fresh `initialize()` 尾部、resume 路径、F1 升级路径
(补写 project_type)。每处最后一步:

```
no_hooks / plugin_mode -> 跳过(工程层已明示退出;--no-hooks 不得创建
                           .claude/settings.json 是 #478 既有 pin)
hooks_json 给定        -> 跳过 wire-up(操作员拥有 hook 目标文件),
                           仍注册心跳(心跳是工作区监视态,不是 hook 项)
默认                    -> hook_activation.register_hooks(ws)  # --wire-up
                           + heartbeat_register(ws)             # --heartbeat-on
```

- wire-up 失败走 #445 既有通道:`HookWiringSelfcheckError` → RC_HOOK_WIRING
  (init FAIL,不是 WARN)。
- 幂等:register_hooks 按命令 basename 去重(替换不堆叠);
  heartbeat_register 重写文件但保留已证明的 loop_registered(见 D3)。
- 顺序:在 deploy_env 之后(issue 明文"exit 0 前最后一步")。env-manifest
  是 deploy_env 自己的分类账,bootstrap 不回写其 settings sha — bootstrap
  的验证是 register_hooks 自带的 post-write selfcheck(更强)。
- #258/#269 边界继承:register_hooks 写 `<ws>/.claude/settings.json`
  (绝不写 HOME),命令指向 canonical 部署目录。

## D3. cron 注册 HARD:`loop_registered` 标记 + `--verify`

**语义**:`--heartbeat-on` 只证明文件写过;`loop_registered=true` 只能由
`/loop` prompt 体自身执行时写入(`--heartbeat-on --loop-registered`)—
prompt 体被执行 = CronCreate 已接受的唯一机械证明(init 布道的
heartbeat / orchestrator 手工链都无此性质)。

**检测**:`heartbeat_loop_prompt.py <ws> --verify`(调用侧验收工具):
`.heartbeat.json` 缺失/不可读/标记非 true → exit 1 + stderr 指引
(重跑 heartbeat_loop_prompt → 传给 CronCreate */5 * * * * 或 /loop 5m →
首 tick 后复查)。不再静默。指南覆盖"CronCreate 刚创建尚未首 tick"的
窗口(复查说明),不与 35min 新鲜度语义耦合(新鲜度归
heartbeat_check / check_heartbeat_alive)。

**注册重入**:`heartbeat_register` 读旧文件,`loop_registered=true` 跨
重注册保留(--heartbeat-off 删除文件后再注册自然回到 false — 正确,
新循环要重新证明)。心跳 gate(check_heartbeat_alive)不读此标记 —
标记是注册验收面,不是派发门禁(避免破坏既有回归)。

## D4. 迁移兼容

- 旧 `.heartbeat.json`(无 loop_registered):`.get("loop_registered")`
  → None → verify 按未注册处理(诚实:旧工作区确实没有可验证的 cron)。
- 旧 `.hook_state.json`:dispatch_linkage 补全/翻转在原 dict 上做,
  未知 hook 不引入(update_state 校验 ALL_HOOKS)。
- worker_budget 在 hook_activation/kunglao_log 不可导入时
  fail-open(import 守卫,stderr 无声不影响 rc)— hook 永不因联动碎。

## D5. 验收 → 测试映射(`tests/test_heartbeat_bootstrap.py`)

| 验收(issue / 升级评论) | 测试 |
|---|---|
| init 成功后 .heartbeat.json 存在且未过期,零手动 hook_activation | `test_init_success_bootstraps_heartbeat_and_hooks` |
| init 幂等(重复跑无副作用) | `test_init_bootstrap_idempotent_no_hook_stacking` |
| --no-hooks 不建 settings(#478 pin)/ 不布道 | `test_init_no_hooks_skips_heartbeat_bootstrap` |
| --hooks-json 操作员目标不被越权扩写 | `test_init_hooks_json_target_not_extended` |
| 旧工作区 resume 后自活 | `test_init_resume_path_re_bootstraps_heartbeat` |
| 派发通过 → TTL 续期 | `test_dispatch_pass_renews_activation_ttl` |
| 派发通过 → phase 翻 DISPATCH + 激活集补全 | `test_dispatch_flips_phase_and_completes_activation` |
| user_override off 不被强 arm | `test_dispatch_respects_user_override_off` |
| 冷状态(无 .hook_state)派发引导全集 | `test_dispatch_cold_state_bootstraps_full_set` |
| 派发通过 → 心跳 last_tick 刷新 | `test_dispatch_refreshes_heartbeat_last_tick` |
| dispatch 事件入统一日志(#459 目标) | `test_dispatch_event_logged_to_unified_log` |
| 陈旧心跳派发仍被拒 + 拒绝不联动(回归锚) | `test_stale_heartbeat_dispatch_still_rejected_no_linkage` |
| cron 注册失败 → 非 0 + stderr 指引(非静默) | `test_verify_hard_fails_*`(3 例) |
| 注册后 verify 通过 | `test_verify_passes_when_loop_registered` |
| prompt 首动作携带注册标记 | `test_loop_prompt_marks_loop_registration` |
| 标记跨重注册保留 | `test_mark_loop_registered_roundtrip` |

## Rejected

- **R1 rejected**:把 loop_registered 检查加进 `check_heartbeat_alive`
  (派发门禁)。会拒绝所有"文件新鲜但 cron 未证明"的合法窗口(init 后
  到首 tick 之间),破坏既有回归语义;注册验收与派发门禁分离。
- **R2 rejected**:为 rejected dispatch 也发事件。那是 #459 观测面
  (hook fire 可见性),本 issue 的验收只要求 dispatch 事件;加进去
  会膨胀 _reject 面 12 处调用。
- **R3 rejected**:phase 新增 "RUNNING" 枚举值。状态机语汇是
  DISPATCH/MONITOR/VERIFY/IDLE(argparse choices 钉死);issue 原文
  "IDLE→RUNNING"是语义描述,DISPATCH 即其机械对应,新增值是无谓
  schema 变更。
- **R4 rejected**:init bootstrap 回写 env-manifest 的 settings sha。
  manifest 是 deploy_env 分类账;bootstrap 的验证是 register_hooks
  自带 selfcheck,双写两个真相源。
- **R5 rejected**:dispatch_gate.py 休眠 WARN 改造。#478 已解除部署
  半边死锁,休眠观测属 #459;edmserver 2026-08-19 治理评论确认本
  issue 剩余范围 = spawn 联动。
