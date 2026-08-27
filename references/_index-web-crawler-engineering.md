# web-crawler-engineering domain index (file level)

> Domain: sustainable collection engineering (`--type web`). Read this file
> AFTER access is solved (`web-risk-control.md` owns the blocked-face);
> sessions / rate / IP / CAPTCHA triage live here.

## Files

| File | One-line summary | When to read |
|---|---|---|
| [web-crawler-engineering.md](re-library/web-crawler-engineering.md) | 会话维持 (cookie 池分层/登录态刷新/身份-指纹-出口三元组), 频率伪装 (log-normal cadence/per-domain budgets/adaptive throttle), IP 策略 (住宅 vs 机房/sticky-per-session/出口质检), CAPTCHA 分类应对 (slider 轨迹/点选/re-challenge 根因回转) | When designing collection ops, budgeting request rates, choosing IP strategy, or triaging a CAPTCHA surface |

## Companion reading

| Situation | Read next |
|---|---|
| access itself is blocked | `web-risk-control.md` (decision tree) |
| signed params need recovering | `web-re-quickref.md` (signed-parameter workflow) |
| methods exhausted | LEARN ladder (worker contract): internal recall first, then WebSearch with evidence discipline |
