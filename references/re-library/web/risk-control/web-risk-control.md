---
name: web-risk-control
description: '风控对抗 anti-bot / risk-control doctrine: 信号分类学 device-fingerprint/behavioral/environment-consistency/protocol,
  对抗决策树 bypass→仿真→real + 无头升级链, 风控栈识别厂商指纹表 加速乐 jsl_clearance/瑞数 $_ts/阿里云 acw_sc/极验 Geetest
  v3 v4/腾讯天御 ticket randstr/网易易盾 NECaptcha/数美 smid/顶象/Cloudflare cf_clearance turnstile/Akamai _abck
  bmak/PerimeterX HUMAN _px3/DataDome/Kasada x-kpsdk/自研识别 + TLS JA3 JA4 传输指纹层, 分厂商挑战机制与处理路径
  (JS challenge/slider/点选/二次校验/动态混淆/无感评分), 启发式决策表 observed-signal→vendor→first action→escalation,
  active-challenge parameter chains (slider backward endpoint tracing + known-library hash reimplementation +
  challenge-bundle obfuscation passes), 检测点定位 触发→观察→归因 loop with camoufox CDP instrumentation. When
  a request is blocked / challenged / a signed param is rejected on a web target — classify the signal, identify
  the vendor stack, pick the handling path.'
domain: web
family: risk-control
---
# Web anti-bot / risk-control field reference

> 域：web 目标（`--type web` 工作区）——浏览器 JS 逆向的防御响应面。与
> `web-re-quickref.md` 互补：那份回答"如何剥离并定位签名参数"；本文件回答
> "请求为何被拦、线上是哪家风控栈、该怎么办"。仅限 web 域使用：malware/
> android 域不继承。阅读顺序为渐进披露：TL;DR 定栈 → 信号分类 → 决策树 →
> 厂商识别 → 分厂商处理 → 启发式表 → 深挖专题。

## TL;DR — 一眼定栈

| 观察到的第一信号 | 判定 | 首选动作 |
|---|---|---|
| 首响应 521 + cookie `__jsluid_*` | 加速乐族（知道创宇） | 离线解 `jsl_clearance_s`（纯 JS 可算） |
| 412/202 + `$_ts` + 响应体逐次变形 | 瑞数 | 放弃静态重放，直上环境仿真 |
| cookie `acw_sc__v2` 缺失被拦 | 阿里云 WAF | 解 JS 校验段补 cookie 后复测 |
| `cf_clearance` / `/cdn-cgi/challenge-platform` | Cloudflare | 真浏览器过检；cookie 与出口同寿命 |
| 秒级 403/429 + `x-kpsdk-*` 头 | Kasada | 环境内生成 token/PoW 材料 |
| 滑块 / 点选弹出 | 极验/顶象/数美/腾讯类 | 先修环境分，再谈解题 |

判定纪律：单指纹不定栈——至少两路独立指纹交叉命中才下结论（识别表见下）。

## 风控信号分类学 (signal taxonomy)

四个信号族，按防御方运行成本从低到高排列。拦截通常是合取式：多族加分累计
越过阈值才触发。先定位是哪一族命中，再选对策——对策作用于信号族，不作用于
症状。

### 设备指纹 (device fingerprint)

按环境稳定的采集项；防御方跨请求 diff，并与已知坏值集比对。

| 信号 | 定位命令 (camoufox / CDP) | 应对 |
|---|---|---|
| canvas hash (纹理差异) | `evaluate_js` returns `toDataURL` digest; run twice to check stability | 指纹伪造面：注入 noise 或采样真实环境 profile（见 Path B） |
| WebGL renderer/vendor (`UNMASKED_RENDERER`) | JS probe in console; also visible in fingerprint dump scripts | UA/渲染栈一致性优先于单点伪装 |
| 字体列表探测 | enumerate probe via offset-measure script; CDP `DOM.getDocument` 前后 diff | 缺字体比多字体更可疑；补齐常见字族 |
| audio (AudioContext DSP 指纹) | offline-render sum probe via `evaluate_js` | 与设备档位保持同代（移动端音频栈 ≠ 桌面） |
| 硬件参数 `hardwareConcurrency/deviceMemory/screen/battery/platform` | one-shot `evaluate_js` JSON dump → 归因表比对 | 全组一致：任一字段与 UA 声称的设备代差过大即出局 |

请求间的指纹漂移比任何单点值都更响：同一会话中途翻转 canvas 或 renderer =
自动化痕迹。

### 行为特征 (behavioral signals)

只能在页面内随时间观察到；用节奏控制化解的成本最低。

| 信号 | 定位命令 | 应对 |
|---|---|---|
| 鼠标轨迹熵 (直线/瞬移/capture rate 低) | hook `mousemove` 采样自己的流量并与真人样本对比分布 | 轨迹生成带噪声曲线 + 过冲回弹；headfull 下用输入注入替代坐标直填 |
| 输入节奏 (固定间隔/paste-only) | keydown 时间戳序列 hook | log-normal 抖动；混合 paste + 手打间隔 |
| 停留时间/dwell (到点即点、无滚动) | 页面 lifecycle 事件时间线 | 人类节奏先行——阅读式停留与随机视口滚动再触发动作 |

### 环境一致性 (cross-check consistency)

评分器交叉核对的是：声称的身份 vs 实际观察到的环境。

| 交叉面 | 观察点 | 应对 |
|---|---|---|
| UA ↔ 指纹交叉 | UA 说 Windows 但 `platform`/touch/webgl renderer 说不 → 一票否决级 | 从指纹出发选 UA，不是从 UA 出发装指纹 |
| 时区 ↔ IP geo | `Intl.DateTimeFormat().resolvedOptions().timeZone` vs 出口 IP 国家 | 代理落地时区对齐；混淆前先核对 |
| 语言栈 ↔ navigator.languages | Accept-Language 头与 `navigator.languages` 不一致 | 同源配置生成器派生两者 |

### 协议层挑战 (protocol-layer challenges)

由页面代码计算的参数；缺失或过期即被拦，与环境质量无关。

| 参数族 | 校验面 | 定位 |
|---|---|---|
| sign / sig / x-bogus 族 | 服务端重算比对 | quickref 五步签名定位工作流（捕获→initiator 栈→算法→replay） |
| nonce / ts / 序列号 | 重放窗口 + 递增校验 | 同一请求二发观察响应差异定位窗口大小 |
| device_id / fid 类绑定 ID | 首次下发后服务端绑行为画像 | 不要轮换——频繁换新 ID 本身就是高危信号 |

## 对抗决策树 (adversarial decision tree)

先分类再选支。没弄清哪一族把分数打爆之前，禁止直接跳 solver/仿真。

```
先分类命中类型：
  ├─ 纯被动（指纹/评分，无插页）
  │    → 先收紧环境一致性（最便宜的修复面）
  ├─ 主动挑战（JS challenge / 滑块 / 点选）
  │    → 环境可能没问题，你是在被测试 → 仿真或解题
  └─ 协议签名缺失/过期
       → 环境修什么都没用 → 定位算法（quickref 工作流）

再按成本阶梯选一条支：
  B1 绕过 bypass   — 规则缝隙：窗口内重放合法 token 对、走无防护的轻端点、
                     缓存复用手解材料。最便宜，也最脆。
  B2 仿真 emulate  — quickref Path B：采集真实指纹，沙箱内复刻，逐项过
                     检测点；行为面在仿真之上模拟。适用于评分/挑战型。
  B3 真实环境 real — camoufox 本体，全保真。最贵也最稳；留给 B1/B2 守不住
                     的场景。
```

升级原则是成本递增：先绕过（有真材料时），再仿真，最后真实环境常驻。

### 无头优先与升级链

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

## 风控栈识别 (vendor identification)

形态识别——厂商轮换内部实现，但 loader/challenge/cookie 的形态稳定。开
浏览器之前先从静态痕迹识别。命中是先验不是判决：cookie 命名随版本换代，
至少两路独立指纹交叉命中才定栈。

| 厂商 | cookie 指纹 | challenge JS / 端点指纹 | 参数 / 头指纹 | 状态码 / 页面形态 |
|---|---|---|---|---|
| 加速乐 / 创宇盾（知道创宇） | `__jsluid_h`/`__jsluid_s` + `__jsl_clearance_s` | 首响应页内嵌短混淆 JS，执行后 reload | — | 首响应 521，携带 clearance 后放行 |
| 瑞数 | 尾缀 T/S（5 代）与 O/P 变体 | 动态 loader（每次响应内容与长度都不同）；`$_ts` 全局变量 | — | 412/202 + meta-refresh 自跳；200 空正文 |
| 阿里云 WAF/盾 | `acw_tc`；JS 校验过签发 `acw_sc__v2`/`acw_sc__v3` | 页内 JS 校验段算 cookie 后 reload | — | 拦截页/滑块（验证码族另见 crawler 卡 SceneId 三元组） |
| 极验 Geetest | — | `static.geetest.com`/`api*.geetest.com` 资源域；`gt4.js` | v3 `gt`/`challenge`/`validate`/`seccode`；v4 `captcha_id` init + `lot_number`/`captcha_output`/`pass_token`/`pow_msg` 提交 | 滑块/点选/图标挂件 |
| 腾讯天御 / 防水墙 | — | `t.captcha.qq.com` 加载脚本；预检 `cap_union_prehandle` | 回传 `ticket` + `randstr` | 弹窗验证码 |
| 网易易盾 | — | `dun.163.com` 域族（`c.dun.163.com`）；`NECaptcha` 命名 | init `captchaId`；register/check 双接口 | 滑块/点选/图标 |
| 数美 | — | JS SDK 先采集指纹再出题 | `deviceId`/`smid` 标识；`organization`/`captchaId`；register+check 双接口 | 滑块/点选/无感 |
| 顶象 | — | `*.dingxianginc.com` 资源域 | init `captchaId`/`appId`；通过后业务请求带 `token` | 滑块（乱序背景图） |
| Cloudflare | `cf_clearance`（过检凭证）+ `__cf_bm` | `/cdn-cgi/challenge-platform/` 脚本；Turnstile 走 `challenges.cloudflare.com` | URL 参数 `__cf_chl_*`；页面挂件标记 `cf-turnstile` | 挑战页 / Turnstile 挂件 |
| Akamai | `_abck`（`~0~` 有效 / `~-1~` 被拒段）+ `ak_bmsc` | `bmak` 全局对象；sensor POST | `sensor_data` 载荷 | 秒拦或静默降级 |
| PerimeterX / HUMAN | `_px`/`_px2`/`_px3`（短寿命）+ `_pxvid`/`_pxhd`/`_pxcts` | 脚本出自 `client.px-cloud.net`/`*.px-cdn.net` | `window._pxAppId`；挑战形态 `Press & Hold`；移动端 `x-px-authorization` 头 | 拦截页/人机挑战 |
| DataDome | `datadome` | `geo.captcha-delivery.com` 中转页 | — | 挑战中转页 + 滑块 |
| Kasada | — | `/ips.js` + 逐请求 PoW | 请求头 `x-kpsdk-*` 族 | 无挑战页直接 403/429 |
| 自研栈 | 随机大写前缀 cookie | 第一方路径 challenge 脚本 | 通用 `sign`/`token` 族 | 非标状态码（如 412 + `retry-after`） |

### 传输层指纹 (TLS / HTTP2)

JA3/JA4 类 ClientHello 指纹先于 HTML 判死：Cloudflare/Akamai/DataDome 族都把
TLS 形态计入判决，Cloudflare 还叠加 HTTP2 帧序与 Client Hints。成熟对齐路线是
浏览器本体或 `curl-impersonate`/`curl_cffi` 类传输栈（JA4+ 为后继标准）。判别
"是 TLS 线还是 JS 线"的启发式见启发式决策表第 3 行。

### 识别产出落盘

识别产出必须落到 claim/fact：栈名 + 痕迹证据 + 应对选择 + 失败历史，下一个
案例先读 note 再开浏览器（site note 制度）。

## 针对性处理 (per-vendor handling)

统一四元组形状：识别指纹 → 挑战机制 → 处理路径 → 升级条件。处理一律停在
方法论层——描述打哪一层、仿真什么、成熟工具类是什么；公开文献中的旧代技术
可以引用，现成可一键跑的成品配方不入卡（双用途纪律）。

### 国内厂商

| 厂商 | 识别指纹 | 挑战机制 | 处理路径 | 升级条件 |
|---|---|---|---|---|
| 加速乐 / 创宇盾 | `__jsluid_*` + `__jsl_clearance_s`；首响应 521 | JS challenge——纯前端算 clearance cookie，不靠指纹分 | 两连发看 set-cookie 序列；扣 loader 内联 JS 离线算 clearance；多代混淆先过 peel 链 | 算法换代离线算不出，或叠加行为分 → B2 环境仿真 |
| 瑞数 | `$_ts`；响应逐次变形；412/202 + meta-refresh；cookie 尾缀 T/S/O/P | 动态混淆 JS 逐请求重生成 + 环境校验，产出动态 cookie/token | 两条成熟路线：hook VM 边界（Path A）或完整环境仿真（Path B/补环境）；loader 不可硬存 | 任一路线不稳即 headful/真实环境常驻（B3）——本族是仿真要求天花板 |
| 阿里云 WAF/盾 | `acw_tc` + `acw_sc__v2/_v3` | JS 校验段算 cookie 后 reload；升级面是滑块/无感 | 解校验段补 cookie 复测；保住 `acw_tc` 会话连续性 | v3 校验或滑块族 → 轨迹材料路线或 B2；验证码实例定位走 SceneId 三元组 |
| 极验 v3/v4 | `gt`/`challenge` 或 `captcha_id` + `lot_number` 族 | 滑块/点选/图标 + 客户端加密提交（v4 `w` 参数多层加密 + PoW）；服务端二次校验 | 轨迹质量优先（加速-减速-过冲曲线族，匀速直线必挂）；提交链按 backward endpoint tracing 逐跳恢复；成熟 solver 服务存在（引用即可） | `risk_type` 无感/AI 档 → 是评分判决不是谜题，回环境修复 |
| 腾讯天御 / 防水墙 | `t.captcha.qq.com`；`ticket` + `randstr` 回传 | 滑块/点选 + 服务端二次校验（`DescribeCaptchaResult` 类） | 材料必须成组且一次性——`ticket`/`randstr` 复用必死；solver 服务存在 | 高频弹出 = 分数崩塌，回会话/频率/IP 三节核查 |
| 网易易盾 | `dun.163.com` 域族 + `NECaptcha` 命名；init `captchaId` | 滑块/点选/图标 + register/check 双接口 + 服务端二次校验 | 参数链 backward tracing；材料在有效窗口内存档复用；solver 服务存在 | 无感模式 → 行为评分面，回环境修复 |
| 数美 | `deviceId`/`smid` 标识；register+check 双接口 | 设备指纹 ID 绑定行为画像 + 滑块/点选/无感 | 身份-ID 绑定不轮换（频繁换新 ID 本身高危）；指纹采集面走环境仿真 | 风险等级持续偏高 → 环境、身份两组一起查 |
| 顶象 | `*.dingxianginc.com`；init `captchaId`/`appId`；通过后带 `token` | 滑块（乱序背景图客户端还原）+ token 链 + 后端 SDK 校验 | 乱序图还原属公开文献手法；token 链 backward tracing；轨迹仿真同滑块族 | 无感档 → 环境评分面 |

### 国际厂商

| 厂商 | 识别指纹 | 挑战机制 | 处理路径 | 升级条件 |
|---|---|---|---|---|
| Cloudflare | `cf_clearance`/`__cf_bm`；`/cdn-cgi/challenge-platform/` | JS 挑战 + TLS/HTTP2 指纹 + Turnstile 人机验证 | 真浏览器过检；**`cf_clearance` 与出口 IP 绑定**，换出口必须连 cookie 一起重取，单独复用旧 cookie 是自伤（三元组绑定见 crawler 卡） | managed challenge 升 interactive / Turnstile 挂件出现 → headful |
| Akamai | `_abck`（看 `~0~`/`~-1~` 段）+ `ak_bmsc`；`bmak` 对象 | 传感器数据（`sensor_data` POST）环境内持续生成 + TLS 指纹 | 传感器必须在环境内生成——伪造单值必被下次校验识破；本族与瑞数同为仿真成本天花板 | 典型 B3 族：直接真实环境常驻，不做中间态恋战 |
| PerimeterX / HUMAN | `_px`/`_px2`/`_px3`（短寿命）+ `_pxvid`/`_pxhd`/`_pxcts` | 行为生物特征 + 环境一致性 + `Press & Hold` 交互挑战 | 环境、行为双修；`_px3` 短窗材料按窗口管理；solver 服务存在 | 高频拦截 → headful + 真实行为画像 |
| DataDome | `datadome` + `geo.captcha-delivery.com` 中转页 | TLS/header/IP 全面对齐检测 + 滑块 | 传输栈先对齐（浏览器本体或 curl-impersonate 类）再谈材料；proxy/UA/cookie 三绑定 | 滑块反复弹出 → 设备检查面，回环境修复 |
| Kasada | 秒 403/429 无挑战页 + `x-kpsdk-*` 头；`/ips.js` | 客户端重 JS + 逐请求 PoW/token | 材料在环境内生成（头族 + PoW 成组）；传输指纹同族对齐；solver 服务存在 | token 通过率下滑 → 环境换代，不调参续命 |

### 自研栈

| 厂商 | 识别指纹 | 挑战机制 | 处理路径 | 升级条件 |
|---|---|---|---|---|
| 自研 | 随机前缀 cookie；第一方 challenge 路径；非标状态码 | 混合族——可能叠加任一商业组件 | 没有现成路线就走检测点定位 loop 逐字段归因；通用 `sign`/`token` 参数走 quickref 五步 | 归因完成后按所属信号族回对抗决策树选支 |

## 处理启发式决策表 (heuristics)

| 观察信号 | 判定 | 首选动作 | 升级路径 |
|---|---|---|---|
| 首响应 521 + `__jsluid_*` | 加速乐族 | 离线解 clearance（纯 JS 面先试） | 算不出 → B2 仿真 |
| 412/202 + `$_ts` + 响应逐次变形 | 瑞数 | 放弃硬存 loader，直上 B2/B3 | headful 常驻 |
| TLS 指纹被拦但真浏览器同 IP 可过 | JS 挑战/评分类，非纯 TLS 线 | 修传输栈形态（浏览器栈或 curl-impersonate 类） | 仍拦 → 回识别表重判 |
| 传输栈全对齐仍拦 | 指纹/评分驱动（Akamai/DataDome 族高危） | 环境一致性逐项 diff | B2 → B3 |
| 滑块出现 | 极验/顶象/数美/腾讯类 | 先问"为何弹出"——修分优于解题 | 分修不动再解材料 |
| 回传参数族 `ticket`+`randstr` 或 `lot_number`+`captcha_output` | 服务端二次校验型验证码 | 材料成组一次性，禁止复用 | solver 服务或真实交互 |
| `cf_clearance` 或 `/cdn-cgi/challenge-platform` | Cloudflare | 真浏览器过检 + 出口粘性 | Turnstile 出现即升环 |
| `_abck` + `bmak` | Akamai | 环境内传感器路线，勿试单值伪造 | B3 |
| `_px*` cookie 族（`_px3` 短寿命） | PX/HUMAN | 环境 + 行为双修 | 高频弹挑战升 headful |
| `datadome` + `geo.captcha-delivery.com` | DataDome | 传输栈对齐先行 | 滑块材料窗口管理 |
| 秒 403/429 + `x-kpsdk-*` | Kasada | 环境内 token/PoW 生成 | 通过率掉即换代 |
| challenge JS 在第一方路径 + 随机 cookie 前缀 | 自研/混合 | 检测点定位 loop 归因 | 按信号族回决策树 |
| 无可见挑战反复弹 | 评分判决非验证码 | 回会话/频率/IP 三节核查 | 修到"偶尔弹"基线 |
| `navigator.webdriver === true` 或 UA 无头特征串 | 自动化暴露 | patch 后复测，携失败证据 | 连续点名 → B2 |

## 主动挑战参数链 (active-challenge parameter chains)

决策树"主动挑战"分支（滑块/点选/JS challenge）会产出参数链：提交请求消费
的值（指纹 blob、challenge id、轨迹载荷）由更早的响应和页面代码生产。默认
做法是从页面加载或首个请求开始顺藤摸瓜——行不通，因为参数链从消费端反向
计算：参数在提交请求上现形，每个生产环节都藏着一个请求取值或采集器调用。
修法——后向端点追踪（backward endpoint tracing）：

1. 从最后一个请求起步（把控行为的提交请求）。切分它的参数集：早前服务端
   下发（cookie/会话携带）vs 页面计算（JS）。
2. 每轮只回溯一跳：消费点 → 生产函数 → 它的输入（某个响应取值或浏览器采集
   读数）。一跳一轮保证每条归因 claim 可查证——整链一次假设撑不过接触。
3. 叶子收敛到服务端下发值或采集到的环境读数即到站；其余再走一跳。

已知库叶子捷径：算出的参数与公共指纹库的 hash 对上时（fingerprintjs 类
`x64hash128`），不要仿真库本身——用页面喂给它的同一组字段离线重实现该
hash。库是公开的；输入装配才是目标特定的部分。离线输出必须等于在线真值；
对不上说明装配不同——diff 字段，不动 hash。

读 challenge bundle——三种让朴素字符串搜索失效的形态（你会想在 bundle 里
grep 参数名；三种形态都从构造上让这招失效——每种都被一个机械 pass 破解，
而不是靠搜索）：

| 形态 | 识别特征 | 机械化解法 |
|---|---|---|
| 解码调用重组 | 字符串存在字符串数组里，运行时经解码调用拼接（`e("0x4c")+"gth"` 形态） | 跑一遍解码器导出其输出表——或运行时 hook 解码器记录实参 |
| 代理包装塌缩 | 属性访问经生成的包装函数路由；调用点只显示包装，不显示操作 | 读控制流前先把包装塌缩回目标操作 |
| 对象字面量键混淆 | 配置/映射的键是算出来的，参数表读起来全是噪声 | 计算键一次性解析并重命名后重读——参数表自然浮出 |

### challenge 元素定位梯 (locator ladder)

交互元素被层层混淆、selector 首选即失败时的爬梯纪律——一次升一档，成功档位
记入 site note：

1. **稳定属性/DOM 路径** selector 首选（最便宜）；
2. **HTML 结构 fallback**——属性被随机化时，按 landmark 元素的相对位置与
   class 形态匹配定位（结构比属性稳）；
3. **vision 定位**（截图 + 元素形态识别）兜底——成本最高，但 DOM 层面的一切
   混淆对它无效；布局改版会静默失效，每会话需重验。

## 检测点定位方法论：触发 → 观察 → 归因 loop

Camoufox 是可调试/可插桩的浏览器——不是"可达的页面容器"。
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
   headless 与 headful 下 CDP 行为一致——调试插桩不需要为它
   单独升级成 headful。
3. **归因 attribute** — pass/fail 双请求参数 diff 得候选字段；候选字段回溯到
   生产代码边界（hook_function trace 位）；确认唯一归因后走决策树选支
   （绕过/仿真/真实）。归因结论落 fact（I/O 对 + replay 命令）。

Loop 出口只有两个：修复验证通过（replay/复访成功），或证据不足以支撑任何分支
（回到 LEARN 梯级——本文件没有的，先内查 re-library 再外部检索，见 worker 契约）。

## 失败模式注记 (failure modes)

- **单指纹定栈**：cookie 命名随版本换代、跨站撞名——至少两路独立指纹交叉
  命中才定栈，识别表只产 prior。
- **把挑战页当业务数据**：瑞数 200 空正文、Cloudflare 挑战页、DataDome 中转页
  都会伪装成正常响应——解析前先过状态码 + 页面形态判定。
- **材料跨窗复用**：`_px3` 短寿命、`ticket`/`randstr` 一次性、`cf_clearance`
  随出口失效——每族材料按自己的窗口管理，过期即重取。
- **指纹库 hash 对不上就改 hash**：错方向——输入装配变了，diff 字段，不动 hash
  （见 parameter chains 的 known-library leaf shortcut）。
- **解题成功业务仍拒**：二次校验型（极验/腾讯/易盾）材料必须成组送达服务端，
  单点突破无意义——回判定第 6 行先认清类型。
- **识别结论不落盘**：栈名 + 痕迹 + 应对 + 失败历史不进 site note，同站下一个
  案例从零重烧——识别的复利靠 note 制度。
