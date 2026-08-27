# web-risk-control domain index (file level)

> Domain: web anti-bot defense-response (`--type web`). Read this file when a
> claim hits blocking / challenge / 风控 and the worker must classify the
> signal before acting. Doctrine source: `re-library/web-risk-control.md`.

## Files

| File | One-line summary | When to read |
|---|---|---|
| [web-risk-control.md](re-library/web-risk-control.md) | 信号分类学 (fingerprint/behavioral/environment/protocol) → 对抗决策树 (bypass → 仿真 → real + J6 无头升级链) → 风控栈识别 (加速乐/瑞数/自研) → 检测点定位 触发→观察→归因 loop with camoufox CDP instrumentation (J7) | Before responding to any block/challenge; classification precedes countermeasure |

## Supply

| Provider | Capability | Notes |
|---|---|---|
| camoufox-reverse (MCP, WARN) | debug/instrumentation channel for the observe step: CDP breakpoints, evaluateOnNewDocument injection, DOM listeners | Headless-first (J6 ruling); CDP behavior identical under headless |

## Decision-tree quick map

| Situation | Branch |
|---|---|
| passive score reject, no interstitial | environment-consistency fixes first |
| active challenge (slider/click-text/JS challenge) | simulate (B2) or solve — after classification |
| signed param rejected/expired | algorithm location (web-re-quickref workflow), not environment tuning |
| anti-headless fingerprint confirmed, patches failed | fingerprint emulation (B2) → headful last resort (B3) |
