# Web anti-bot / risk-control field reference

> Domain: web targets (`--type web` workspaces) — the defense-response face of
> browser JS RE. Companion to `web-re-quickref.md`: that file answers "how do I
> peel and locate a signed parameter"; this file answers "why is the request
> blocked, which signal caught it, and what do I do about it". Web-domain
> specific by ruling (2026-08-27): malware/android domains do not inherit it.
> Every section keeps the field shape: 信号 → 定位命令 → 应对.

## 风控信号分类学 (signal taxonomy)

Four families, ordered by how cheap they are for the defender to run. A block
is usually a CONJUNCTION: the score crosses a threshold after several families
add up. Identify which family fired before choosing a countermeasure —
countermeasures target families, not symptoms.

### 设备指纹 (device fingerprint)

Stable per-environment collectors; the defender diffs them across requests and
against known-bad value sets.

| 信号 | 定位命令 (camoufox / CDP) | 应对 |
|---|---|---|
| canvas hash (纹理差异) | `evaluate_js` returns `toDataURL` digest; run twice to check stability | 指纹伪造面：注入 noise 或采样真实环境 profile（见 Path B） |
| WebGL renderer/vendor (`UNMASKED_RENDERER`) | JS probe in console; also visible in fingerprint dump scripts | UA/渲染栈一致性优先于单点伪装 |
| 字体列表探测 | enumerate probe via offset-measure script; CDP `DOM.getDocument` 前后 diff | 缺字体比多字体更可疑；补齐常见字族 |
| audio (AudioContext DSP 指纹) | offline-render sum probe via `evaluate_js` | 与设备档位保持同代（移动端音频栈 ≠ 桌面） |
| 硬件参数 `hardwareConcurrency/deviceMemory/screen/battery/platform` | one-shot `evaluate_js` JSON dump → 归因表比对 | 全组一致：任一字段与 UA 声称的设备代差过大即出局 |

Device-fingerprint drift BETWEEN requests is the louder tell than any single
value: same session flipping canvas or renderer mid-run = automation artifact.

### 行为特征 (behavioral signals)

Only observable inside the page over time; cheapest to defeat by pacing.

| 信号 | 定位命令 | 应对 |
|---|---|---|
| 鼠标轨迹熵 (直线/瞬移/capture rate 低) | hook `mousemove` 采样自己的流量并与真人样本对比分布 | 轨迹生成带噪声曲线 + 过冲回弹；headfull 下用输入注入替代坐标直填 |
| 输入节奏 (固定间隔/paste-only) | keydown 时间戳序列 hook | log-normal 抖动；混合 paste + 手打间隔 |
| 停留时间/dwell (到点即点、无滚动) | 页面 lifecycle 事件时间线 | 人类节奏先行——阅读式停留与随机视口滚动再触发动作 |

### 环境一致性 (cross-check consistency)

The scorer cross-checks CLAIMED identity vs OBSERVED environment.

| 交叉面 | 观察点 | 应对 |
|---|---|---|
| UA ↔ 指纹交叉 | UA 说 Windows 但 `platform`/touch/webgl renderer 说不 → 一票否决级 | 从指纹出发选 UA，不是从 UA 出发装指纹 |
| 时区 ↔ IP geo | `Intl.DateTimeFormat().resolvedOptions().timeZone` vs 出口 IP 国家 | 代理落地时区对齐；混淆前先核对 |
| 语言栈 ↔ navigator.languages | Accept-Language 头与 `navigator.languages` 不一致 | 同源配置生成器派生两者 |

### 协议层挑战 (protocol-layer challenges)

Parameters computed by page code whose absence/expiry blocks you regardless of
environment quality.

| 参数族 | 校验面 | 定位 |
|---|---|---|
| sign / sig / x-bogus 族 | 服务端重算比对 | quickref 五步签名定位工作流（捕获→initiator 栈→算法→replay） |
| nonce / ts / 序列号 | 重放窗口 + 递增校验 | 同一请求二发观察响应差异定位窗口大小 |
| device_id / fid 类绑定 ID | 首次下发后服务端绑行为画像 | 不要轮换——频繁换新 ID 本身就是高危信号 |

## 对抗决策树 (adversarial decision tree)

Classify FIRST, then branch. Never jump to solver/emulation before knowing
which family scored you out.

```
classify detection:
  ├─ passive only (fingerprint/score, no interstitial)
  │    → tighten environment consistency first (cheapest fix surface)
  ├─ active challenge (JS challenge / slider / click-text)
  │    → environment may be fine; you are being TESTED → simulate or solve
  └─ protocol signature missing/expired
       → no environment fix helps → locate algorithm (quickref workflow)

then pick ONE branch by cost ladder:
  B1 绕过 bypass   — rule gap: replay a legitimate token pair within its
                     window, use a lighter unguarded endpoint, cache &
                     reuse hand-solved material. Cheapest; fragile.
  B2 仿真 emulate  — Path B of quickref: capture real fingerprint,
                     replicate in sandbox, pass detection points; behavior
                     simulated on top. For scorer/challenge targets.
  B3 真实环境 real — camoufox 本体, full fidelity. Most expensive, most
                     robust; reserved for cases B1/B2 cannot hold.
```

升级原则是成本递增：先绕过（有真材料时），再仿真，最后真实环境常驻。

### 无头优先与升级链 (J6 ruling, 2026-08-27)

浏览器 MCP **默认 headless**（资源省、可并行、无人值守友好）。headful 不是起点，
是对抗链的最后一环：

```
headless 默认
  └─ 检测到反无头指纹？(可判定信号清单，逐条 evaluate_js/网络侧核实)
       ├─ navigator.webdriver === true            → 隐除/patch 后复测
       ├─ UA 含 HeadlessChrome/headless 特征串    → UA 栈修正后复测
       ├─ 权限/插件/webgl vendor 呈无头空集        → 档位修正后复测
       ├─ CDP 痕迹被 challenge 连续点名 (≥2 次)     ↓ 进入下一环
       ├─ patch 后仍被拦                            → 指纹仿真 (B2)
       └─ 仿真仍被拦                                → headful 最后手段 (B3)
```

判定纪律：每次升级必须携带上一步的失败证据（哪个信号、什么值、修了什么），
禁止"感觉被识别了"就直接跳 headful。

## 常见风控栈识别 (stack identification)

Shape-based recognition — vendors rotate internals but loader/challenge/cookie
shapes persist. Identify from static traces BEFORE opening the browser.

| 栈 | 静态痕迹 (信号) | 定位命令 | 应对要点 |
|---|---|---|---|
| 加速乐 (JiaSuLe) | cookie `__jsluid_*` + 首响应页内嵌短混淆 JS 计算 `jsl_clearance_s` 后 reload | curl 两连发看 set-cookie 序列；view-source 找内嵌 eval 段 | 按 loader 顺序解 JS 得 clearance 计算式；通常纯 JS 可离线算 |
| 瑞数 (RiverSecurity) | 动态多变 JS loader（每次响应都不同长度）、`$_ts` 全局变量、meta-refresh 自跳、200 却无正文 | 对比两次响应 diff；搜 `$_ts`/`$_t` 特征名 | loader 动态生成不可硬存——要么 hook 其 VM 边界（quickref Path A），要么完整环境仿真走 B2/B3 |
| 自研栈 | 命名线索散在 cookie 前缀/loader 路径/challenge 返回形态（如 412+retry-after、随机大写前缀 cookie） | 全量响应头收集 + challenge 页 source 存档进 evidence | 没有现成路线就走检测点定位 loop（下节）逐字段归因 |

识别产出必须落到 claim/fact：栈名 + 痕迹证据 + 应对选择 + 失败历史，下一个
案例先读 note 再开浏览器（site note 制度）。

## 检测点定位方法论：触发 → 观察 → 归因 loop (J7 一等能力)

Camoufox 是可调试/可插桩的浏览器（ruling 2026-08-27）——不是"可达的页面容器"。
定位一个被拦请求的根因字段靠这个 loop 收敛，每一步都有确定的 camoufox 操作：

1. **触发 trigger** — 最小化复现：按请求链二分（保留/删除 header、cookie、参数），
   找到"必带才通"的最小集合。每次变化只动一处，diff 结果记入 evidence
   （pass pair / fail pair 成对保存）。
2. **观察 observe** — 用 camoufox 调试通道看数据在哪生成：
   - XHR/fetch 发送拦截：hook 预设经 `page.evaluateOnNewDocument` 注入（页面代码
     运行前生效）；CDP `Network.requestWillBeSent` 兜底看全量出站帧；
   - WebSocket 帧级观察：CDP `Network.webSocketFrameSent/Sent`；
   - 写入监听：DOM 断点盯 `document.cookie` setter 与 localStorage/sessionStorage
     写入——风控种的标记 cookie 多在这里现形；
   - 断点停住后回溯调用栈定位生产函数（initiator stack 同 quickref Step 2）。
   headless 与 headful 下 CDP 行为一致（ruling J6 衔接）——调试插桩不需要为它
   单独升级成 headful。
3. **归因 attribute** — pass/fail 双请求参数 diff 得候选字段；候选字段回溯到
   生产代码边界（hook_function trace 位）；确认唯一归因后走决策树选支
   （绕过/仿真/真实）。归因结论落 fact（I/O 对 + replay 命令）。

Loop 出口只有两个：修复验证通过（replay/复访成功），或证据不足以支撑任何分支
（回到 LEARN 梯级——本文件没有的，先内查 re-library 再外部检索，见 worker 契约）。
