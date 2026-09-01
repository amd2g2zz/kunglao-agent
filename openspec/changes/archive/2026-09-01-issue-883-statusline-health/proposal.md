# issue-883-statusline-health — proposal

## Why

statusline 需显示 kunglao-agent Health 与当前工作状态（"正在分析"一眼可见），硬性要求实时
（kunglao 挂了绝不能还显示健康）+ 时间数字不长驻。终版规格（issue 定案）：flare 动效五件套 +
进度闪现制 + 快照解耦；**渲染解耦是关键决策**：kunglao 逻辑全在 Python 侧预写快照，Node 侧
只读快照 O(1) 零 spawn 渲染。两轮美学否决沉淀为"减法原则"（ASCII/CJK 拼贴均否，时间数字
常驻被否）。

## What

1. **Python 侧（仓内，PR 交付）**：
   - `scripts/statusline_snapshot.py`：探针注册表（v1 四探针 + 插槽）、语义状态机
     （analyzing/toss/idle/stall/down/flawless + 探针短码，纯磁盘观测）、快照 writer
     （O(1) 原子写 `runs/.kunglao-statusline.json`）、CLI 入口。
   - `scripts/heartbeat_tick.py` 挂快照 writer（fail-open，零新管道——数据源全复用
     cockpit_summary / mission_ledger / claim-register / noop breaker）。
   - 测试：注册表完整性 + 探针判据 + 状态机转移表 + 闪现触发 + 快照 schema + down 自动翻转
     + tick 集成。
2. **Node 侧（本地交付，不入仓）**：`~/.claude/statusline/combined-statusline.mjs` 加
   kunglao 段（读快照零 spawn → 渲染时钟插值动画帧 → 闪现调度 → 拼接；claude-hud 段原样）。
   以 Recon 演示记录为验收凭据。

## 探索→计划更新

无规格级偏航（见 Recon 偏航段：3 项实现级偏离，均在 §0.2.3 允许范围）。规格锁定：
flare 动效五件套（呼吸/流光/火花/渐变/内嵌进度）+ 进度闪现制（PQ coverage 填充、时间数字
仅闪现、条尾渐隐=d_slope 置信度、down 冻结）+ 快照解耦（Node 看门狗判 down）。
十条验收全保（卡片 351-362 行）。

## Recon

### 锚点表（计划锚点 vs 实测）

| 计划锚点 | 实测 | 状态 |
|---|---|---|
| heartbeat_tick 挂快照 writer 的点 | `scripts/heartbeat_tick.py` main() #873 cockpit 采样块（L339-350）之后、final prints 之前；fail-open try 同款 | 确认 |
| cockpit_summary / eta_checkpoints / d_slope 产出 | `scripts/tuition_curve.py:140-164` cockpit_summary(ws) → {v, d_slope, eta_checkpoints(tick 单位), total_weight, answered/blocked/unattempted, cost, burn, tuition}；heartbeat_tick 已每 tick 调用 | 确认，零新管道 |
| PQ coverage 数据源 | `scripts/mission_ledger.py` load() → mission.pqs[]（state/coverage/weight）；answered/total 由 cockpit_summary 直接给出 | 确认 |
| alive 探针（mtime） | heartbeat_touch.py 实际写 `runs/.heartbeat.json`（mtime 每次 touch 更新，#754 merge 语义）；`analysis_state.txt` 是 workspace 身份标记（init scaffold 产，非每 tick 更新） | 偏航-1（实现级） |
| 账本尾部 | `runs/logs/kunglao-<date>.jsonl`（kunglao_log.log_path），单行 JSON 事件 {ts, actor, action, ...}；tail 读 = 最新日文件末 64KB | 确认 |
| deployed 探针口径 | `scripts/hooks_selfcheck.py:101-130` check_settings：KONG_HOOK_FILES（4 活性钩子）× <ws>/.claude/settings.json 命令子串匹配；命令形状 `PYTHONUTF8=1 uv run --project <root> <hook_dir>/<file>`（hook_activation.build_hook_entry:497）。**注意**：hooks_selfcheck 会 AUTO-REBUILD（L182-186），快照探针必须只读自算、不得读其报告（否则永远看不到故障窗口） | 确认 + 约束 |
| stall 指纹 | `scripts/heartbeat_tick.py:163-208` noop_breaker：state_fingerprint 不变计数落 `runs/.heartbeat-noop.json`（consecutive_noop，阈值 KUNGLAO_NOOP_BREAKER_N=6）；快照直接复用该文件，零重算 | 确认，零新管道 |
| staleness 预算常量 | `scripts/liveness_policy.py`：HEARTBEAT_STALE_MINUTES=35（alive）、TICK_INTERVAL_DEFAULT_MIN=5、DEFAULT_TTL_MINUTES=30 | 确认 |
| claim-register OPEN 判定 | `yaml.safe_load` → claims[]；状态词表 OPEN/IN_PROGRESS/PARTIALLY-VERIFIED/PROVEN/DEFERRED；scaffold 条目无 per-claim 时间戳字段 → "最老 OPEN claim 无 span" 探针 v1 不可实现 | 约束（插槽） |
| mjs 插入点 | `~/.claude/statusline/combined-statusline.mjs`（269 行）：main() L225-267，HUD 段 join(" \| ") 单行 + ov 第二行；文件自述 "Claude Code appears to render only the last statusline line"（L260）→ kunglao 段拼到**最后一行**（" \| " 连接），非新增行 | 确认 + 决策 |
| 非会话零变化守卫 | mjs 不解析 stdin（原样透传 HUD）→ 新增 stdin JSON 解析取 `workspace.current_dir`（防御式 fallback `cwd`），从 cwd 向上最多 4 级找 `runs/.kunglao-statusline.json`；找不到 → 整段不渲染，输出与改前逐字节一致 | 确认 |
| Node 测试路径 | fixture 快照 + `node combined-statusline.mjs < stdin.json` 本地渲染；动画帧用 `KUNGLAO_SL_FAKE_NOW_MS` 测试缝；.bak 为 diff 基线 | 确认 |

### 镜像样例

- fail-open try 块：heartbeat_tick.py:339-350（#873 cockpit 采样）——快照 writer 挂点同款。
- 原子写：heartbeat_touch.py:63-68（tmp + `replace`）——快照写盘同款。
- 探针只读 fail-open：hooks_selfcheck.check_settings（解析失败返回结构化故障而非 raise）。
- 测试惯例：tests/test_heartbeat_tick.py（subprocess CLI + `_make_ws` scratch workspace）、
  tests/test_cockpit_persist_873.py（`sys.path.insert(scripts)` 直 import）。
- EMIT 词表：新 face 词 `statusline_snapshot`（同 face=每 tick 快照写；初稿复用
  `cockpit_sample` 撞 #873 零噪声契约——test_tick_skips_without_mission_ledger
  抓住，改为按注册纪律注册独立词，EMIT_ACTIONS CI 锚定同步）。

### 快照 schema（v1 定稿，数据源已确认可填满）

```json
{
  "schema": 1,
  "ts": "<UTC Z>", "workspace": "<abs>", "tick": 42, "tick_minutes": 5,
  "state": "analyzing|toss|idle|stall|down|flawless",
  "state_since": "<UTC Z>",
  "color": {"hue": 140, "sat": 72, "light": 55},
  "probe_codes": ["[hook]"],
  "probe_detail": [{"id": "...", "dimension": "deployed", "severity": "WARN",
                     "short_code": "[hook]", "ok": false, "detail": "..."}],
  "pq": {"answered": 2, "blocked": 1, "unattempted": 7, "total": 10, "coverage": 0.25},
  "v_m": 1.4, "d_slope": 0.021, "eta_ticks": 30, "eta_fade_cells": 1,
  "elapsed": {"ticks": 42, "started_ts": "..."},
  "activity": {"events_recent": 5, "spark_count": 3},
  "flash": {"seq": 7, "ts": "<UTC Z>", "reason": "milestone_25", "text": "已 2t · 剩 ~30t"},
  "audit": {"age_min": 12, "source": "runs/.hooks-selfcheck.json"}
}
```

- `color` Python 侧按状态预计算（kunglao 逻辑不进 Node）；Node 只做亮度插值（呼吸）与
  200ms 状态切换渐变。hue 表：analyzing 140 绿 / toss 190 青 / idle 220 暗蓝灰 / stall 45 黄 /
  down 0 红 / flawless 48 金。
- `eta_fade_cells` = round((1-min(1,|d_slope|/0.05))*4)（0.05/tick = 健康斜率名义值；
  条尾渐隐段长 = ETA 不确定性）。
- `flash`：Python 检测触发（每 10 tick / coverage 跨 25·50·75% / answered 变化 / 状态切换 /
  stall 解除）→ seq+1 + ts + 预格式化文本；Node 判 `now-flash.ts < 5000ms` 显示，
  首尾 300ms 透明度渐变——无跨渲染状态，渲染解耦保持。
- Node 看门狗：快照 mtime 距今 > T_LIVE（默认 12min = 2×tick 间隔 + 余量，env
  `KUNGLAO_SL_TLIVE_MIN` 可覆写）→ down 冻结最后一帧（红、无动画、条不重置）。
  kunglao 死 → tick 停 → 快照 mtime 停 → Node 判 down，无 self-report。

### 探针注册表（v1）

| id | dimension | threshold | unit | staleness_budget | severity | short_code |
|---|---|---|---|---|---|---|
| heartbeat_mtime | alive | 35 min | wall | 35m | HARD | [ledger] |
| ledger_tail | alive | 90 min | wall | 90m | HARD | [ledger] |
| hooks_declared_vs_disk | deployed | —（双向比对） | — | 1 tick | WARN(缺声明)/HARD(声明缺文件) | [hook] |
| stall_fingerprint | moving | 6 tick | tick | 1 tick | WARN | [stall] |
| audit_age | audit | 60 min | wall | —（本身即年龄） | WARN | [audit] |
| unattributed_rate | moving | — | — | — | — | **插槽**（#879 后填） |
| backtrack_lag | moving | — | — | — | — | **插槽**（#882 后填） |

注册表驱动：不入册不显示；enabled=false 插槽不执行；新探针声明即接入（测试钉住）。

### 偏航（实现级，§0.2.3 允许，已记录 WHAT/WHY）

1. **alive 探针主文件**：issue 写 "analysis_state.txt mtime（heartbeat_touch 生产者）"，
   实测 heartbeat_touch 的 mtime 生产者是 `runs/.heartbeat.json`（analysis_state.txt 仅 init
   时写，mtime 不随 touch 更新——用它判 alive 会把活 workspace 永远判死）。WHAT：alive 主
   探针 = runs/.heartbeat.json mtime；analysis_state.txt 仅作 workspace 身份标记（零侵入
   开关）。WHY：与生产者事实对齐。
2. **stall "最老 OPEN claim 超 K tick 无 span"**：claim-register scaffold 条目无时间戳字段，
   v1 不可实现 → 留注册表插槽（与未归因率/回溯滞后同列）。v1 stall 判据 = noop breaker
   consecutive_noop ≥6 且有 OPEN claim（等价"状态指纹 6 tick 不动"）。
3. **deployed 探针双向比对**：hooks_selfcheck 自动 rebuild 缺失声明（L182-186）→ 快照探针
   只读自算（缺声明=WARN 可自愈、声明缺文件=HARD），不消费其报告。

### 演示记录（Node 侧本地交付验收，2026-09-01）

fixture 工作区：`%TEMP%/kunglao-sl-fixture/ws-{analyze,stall,idle,flawless,down,watchdog,hookfile}`
（由真实 Python writer 产快照——Python→快照→Node 全链；builder 脚本
`%TEMP%/kunglao-sl-tools/build_fixtures.py`，不在仓内）。渲染命令：
`node combined-statusline.mjs < stdin.json`（stdin 带 `workspace.current_dir` 指向 fixture）；
动画帧用 `KUNGLAO_SL_FAKE_NOW_MS` 测试缝驱动渲染时钟。

| # | 验收 | 证据（摘录） |
|---|---|---|
| 1 | kill→down | ws-down（heartbeat 停 40min）→ Python 快照 state=down；Node 帧 `kunglao:down` 红 `230;25;25` + `[ledger]` 短码；状态机测试 `test_down_auto_flip` 钉住 |
| 2 | 删声明 hook→deployed 翻色 | ws-hookfile：删已声明 worker_pulse.py → HARD `[hook]` 红码 `232;48;48` 入帧；探针测试 ×2（缺声明 WARN/缺文件 HARD） |
| 3 | 动效可见 / idle 静止 | analyzing 帧序（fake-now +0/500/1000ms）RGB `49;222;107→61;223;115→34;211;93`（±15% 呼吸）+ 流光白色 `250;250;250` 扫动 + 火花 `✦✦✦`（=events_recent 3）；**idle 两帧跨时钟 byte-identical（静止）**；analyzing 两帧 differ（活着） |
| 4 | 时间数字仅闪现 | 真实触发（coverage 0.5→0.8 跨 75%）→ 窗口内帧含 `已 4t · 剩 ~10t`（暗色 `152;161;179`），+6s 帧无任何时间文本；测试 `test_milestone_crossing_triggers_flash` + `test_no_trigger_keeps_seq` |
| 5 | down 冻结 | ws-watchdog：快照内容 healthy、mtime 拨回 13min → Node 看门狗判 down，两帧跨时钟 byte-identical（FROZEN），条冻结最后一帧不重置 |
| 6 | 渲染增量 <50ms | debug.log `kunglao render ms: 0-1`（纯快照读+插值，零 spawn） |
| 7 | 非 kunglao 会话零变化 | 无快照 cwd：`.bak-883` vs 新版 stdout `cmp` IDENTICAL（74 bytes） |
| 8 | claude-hud 段一致 | kunglao cwd 下第 1 行（HUD）`.bak` vs 新版 IDENTICAL（34 bytes）；kunglao 段拼最后一行 ` \| ` 尾接 |
| 9 | 审计年龄 severity 分级 | snapshot.audit.age_min 入帧 `audit:1m`；探针测试 fresh=ok / 90min=WARN `test_audit_age_severity_grading` |
| 10 | 新探针声明即接入 | `test_new_probe_declaration_auto_wires`：注册表追加 fake_probe → 快照 probe_detail 出现，writer 零改动 |

状态帧基色：analyzing 绿 `140°` / toss 青 `190°` / idle 暗蓝灰 `220°` / stall 黄 `45°`（深慢
4s ±25% 呼吸）/ down 红 `0°`（无动画）/ flawless 金 `48°`（state_since 后 3 快闪转常亮）。
down/watchdog 帧 KO 语义：无动画、无时间文字、无火花。

### 基线

- `python -m pytest tests/test_heartbeat_tick.py tests/test_cockpit_persist_873.py -q` →
  17 passed（改前绿）。
- 本地全量已知 7 个环境性基线失败（Windows；stash 对照甄别，CI Linux 权威）：
  test_audit_guard_reviewgate_799 ×2、test_deploy_surface_755、test_envcheck_modern_757、
  test_gate_power_473、test_probe_tiers_474 ×2。
- combined-statusline.mjs 改前备份：`combined-statusline.mjs.bak-883`（同目录，diff 基线）。
