---
name: web-risk-control
description: 'Anti-bot / risk-control doctrine for web targets: signal taxonomy device-fingerprint/behavioral/environment-consistency/protocol,
  adversarial decision tree bypass→emulate→real + headless-first escalation chain, vendor-stack identification 风控栈识别
  fingerprints (JiaSuLe/ChuangyuDun 加速乐/创宇盾 jsl_clearance, RiverSecurity 瑞数 $_ts, Aliyun WAF 阿里云 acw_sc,
  GeeTest 极验 v3 v4, Tencent TCaptcha 腾讯天御 ticket randstr, NetEase YiDun 网易易盾 NECaptcha, Shumei 数美 smid,
  DingXiang 顶象, Cloudflare cf_clearance turnstile, Akamai _abck bmak, PerimeterX HUMAN _px3, DataDome, Kasada
  x-kpsdk, self-built 自研识别) + TLS JA3 JA4 transport layer, per-vendor 处理路径 challenge mechanisms and handling
  paths 挑战机制 (JS challenge/slider/二次校验/dynamic obfuscation/无感评分), operator heuristics 启发式 table
  observed-signal→vendor→first action→escalation, active-challenge parameter chains (slider backward endpoint
  tracing + known-library hash reimplementation + challenge-bundle obfuscation passes), detection-point localization
  触发→观察→归因 loop with camoufox CDP instrumentation. When a request is blocked / challenged / a signed param
  is rejected on a web target — classify the signal, identify the vendor stack, pick the handling path.'
domain: web
family: risk-control
---
# Web anti-bot / risk-control field reference

> Domain: web targets (`--type web` workspaces) — the defense-response face of browser JS RE. Companion to
> `web-re-quickref.md` (how to peel and locate a signed parameter); this file answers why the request is blocked,
> which vendor stack is on the wire, and what to do about it. Web-domain only; progressive disclosure below.

## TL;DR — stack identification at a glance

| First signal observed | Verdict | First action |
|---|---|---|
| First response 521 + cookie `__jsluid_*` | JiaSuLe family (加速乐) | Solve `jsl_clearance_s` offline (pure JS surface) |
| 412/202 + `$_ts` + body reshaped per request | RiverSecurity (瑞数) | Skip static replay; go straight to environment emulation |
| Blocked with `acw_sc__v2` cookie missing | Aliyun WAF (阿里云盾) | Solve the JS validation segment, refill cookie, retest |
| `cf_clearance` / `/cdn-cgi/challenge-platform` | Cloudflare | Pass with a real browser; cookie lifetime = egress lifetime |
| Instant 403/429 + `x-kpsdk-*` headers | Kasada | Generate token/PoW material inside the environment |
| Slider / click captcha appears | GeeTest/DingXiang/Shumei/Tencent class | Fix the environment score first; solving comes second |

Verdict discipline: never call the stack from a single fingerprint — two independent hits minimum.

## Signal taxonomy

Four families, cheapest-first for the defender. A block is usually a CONJUNCTION — several families add up past a
threshold. Countermeasures target families, not symptoms: identify the family that fired first.

### Device fingerprint

Stable per-environment collectors, diffed across requests and against known-bad sets; drift BETWEEN requests is the louder tell — mid-run canvas/renderer flips = automation artifact.

| Signal | Locate (camoufox / CDP) | Respond |
|---|---|---|
| canvas hash (texture variance) | `evaluate_js` `toDataURL` digest, run twice for stability | Inject noise or sample a real-environment profile (Path B) |
| WebGL renderer/vendor (`UNMASKED_RENDERER`) | JS probe in console; fingerprint dump scripts | UA/render-stack consistency outranks single-value spoofing |
| Font-list probing | offset-measure enumerate probe; CDP `DOM.getDocument` diff | Missing fonts beat extra fonts; backfill common families |
| Audio (AudioContext DSP fingerprint) | offline-render sum probe via `evaluate_js` | Same device generation (mobile audio stack ≠ desktop) |
| Hardware `hardwareConcurrency/deviceMemory/screen/battery/platform` | one-shot `evaluate_js` JSON dump → attribution table | Whole-set consistency; generation mismatch with the UA is fatal |

### Behavioral signals

| Signal | Locate | Respond |
|---|---|---|
| Mouse-trajectory entropy (straight/teleport/low capture) | hook `mousemove`, diff own traffic vs human distribution | Noise curves + overshoot-rebound; under headful prefer input injection |
| Input cadence (fixed intervals / paste-only) | keydown timestamp-sequence hook | log-normal jitter; mix paste + hand-typed intervals |
| Dwell time (instant click, no scrolling) | page lifecycle event timeline | Reading-style dwell + random viewport scrolls before actions |

### Environment consistency (cross-checks)

| Cross-check | Observation point | Respond |
|---|---|---|
| UA ↔ fingerprint | UA says Windows but `platform`/touch/webgl disagree → veto-grade | Pick the UA from the fingerprint, never the reverse |
| Timezone ↔ IP geo | `Intl.DateTimeFormat().resolvedOptions().timeZone` vs egress IP country | Align the proxy landing timezone first |
| Language stack ↔ navigator.languages | `Accept-Language` vs `navigator.languages` mismatch | Derive both from one config source |

### Protocol-layer challenges

| Parameter family | Verification face | Locate |
|---|---|---|
| sign / sig / x-bogus family | server-side recomputation | quickref five-step workflow (capture → initiator stack → algorithm → replay) |
| nonce / ts / sequence numbers | replay window + monotonicity | fire twice, diff responses to size the window |
| device_id / fid binding IDs | server binds a behavior profile at first issuance | never rotate — fresh IDs are themselves high-risk |

## Adversarial decision tree

Classify FIRST, then branch — never jump to solver/emulation before knowing which family scored you out.

```
classify the detection:
  ├─ passive only (fingerprint/score) → tighten environment consistency first
  ├─ active challenge (JS challenge / slider / click) → you are being TESTED → simulate or solve
  └─ protocol signature missing/expired → no environment fix helps → locate algorithm (quickref)
then pick ONE branch by cost ladder:
  B1 bypass  — replay a legit token pair in-window, lighter endpoint, cache hand-solved material
  B2 emulate — Path B: capture the real fingerprint, replicate in sandbox, pass detection points
  B3 real    — camoufox itself, full fidelity; reserved for cases B1/B2 cannot hold
```

### Headless-first escalation chain

The browser MCP runs **headless by default**; headful is the adversarial chain's last link, not the starting point.

```
headless default
  └─ anti-headless fingerprints? (decidable checklist, verify via evaluate_js / network side)
       ├─ navigator.webdriver === true             → hide/patch, retest
       ├─ UA carries headless marks                → fix UA stack, retest
       ├─ permissions/plugins/webgl empty-set      → fix tier, retest
       ├─ CDP artifacts named by challenge (≥2)    ↓ next link
       ├─ still blocked after patching             → fingerprint emulation (B2)
       └─ still blocked after emulation            → headful last resort (B3)
```

Every upgrade carries the previous step's failure evidence (signal, value, fix) — never escalate on a feeling.

## Vendor-stack identification and handling

Shape-based recognition — vendors rotate internals but loader/challenge/cookie shapes persist; identify from static
traces BEFORE opening the browser. Uniform quadruple per vendor: identify → mechanism → handling → escalation.
Methodology level only — which layer to hook, what to simulate, which tool CLASS; no runnable recipes (dual-use).

### China-market vendors

| Vendor | Identify (cookie / endpoint / param) | Mechanism | Handling path | Escalation |
|---|---|---|---|---|
| JiaSuLe / ChuangyuDun (加速乐/创宇盾) | `__jsluid_*` + `__jsl_clearance_s`; first response 521 | JS challenge — pure front-end clearance computation | Two requests map the set-cookie sequence; lift the inline loader JS, compute clearance offline | Algorithm change breaks offline solve → B2 |
| RiverSecurity (瑞数) | `$_ts`; body reshaped per request; 412/202 + meta-refresh; cookie suffixes T/S/O/P | Dynamic obfuscated JS regenerated per request + environment checks → dynamic cookie/token | Hook the VM boundary (Path A) or full environment emulation (Path B / env stubbing); never hardcode the loader | Either route unstable → B3 headful residency (emulation ceiling) |
| Aliyun WAF (阿里云盾) | `acw_tc` + `acw_sc__v2/_v3` | JS validation segment computes the cookie, then reloads; upgrade face is slider/invisible | Solve the validation segment, refill cookie; preserve `acw_tc` continuity | v3/slider → trajectory-material route or B2; captcha instance via SceneId triad |
| GeeTest (极验) v3/v4 | v3 `gt`/`challenge`; v4 `captcha_id` + `lot_number`/`captcha_output`/`pass_token`/`pow_msg`; `static/api*.geetest.com`, `gt4.js` | Slider/click/icon + encrypted submit (v4 `w`: multi-layer encryption + PoW); server-side secondary validation | Trajectory quality first (accel-decel-overshoot; constant speed always fails); recover the submit chain by backward endpoint tracing; solver services exist (cite) | `risk_type` invisible/AI → score verdict, not a puzzle; environment repair |
| Tencent TCaptcha (腾讯天御/防水墙) | `t.captcha.qq.com`; `ticket` + `randstr` return; `cap_union_prehandle` | Slider/click + server-side secondary validation (`DescribeCaptchaResult`-class) | Material travels as a one-time set — reusing `ticket`/`randstr` is fatal; solver services exist | High-frequency popups = collapsed score; audit session/frequency/IP triad |
| NetEase YiDun (网易易盾) | `dun.163.com` family (`c.dun.163.com`); `NECaptcha`; init `captchaId` | Slider/click/icon + register/check pair + server-side secondary validation | Parameter-chain backward tracing; archive material in its validity window; solver services exist | Invisible mode → behavioral scoring; environment repair |
| Shumei (数美) | `deviceId`/`smid`; `organization`/`captchaId`; register+check pair | Device-fingerprint ID bound to a behavior profile + slider/click/invisible | Identity-ID binding must not rotate (fresh IDs are high-risk); fingerprint face via environment emulation | Risk level stays high → audit environment + identity sets together |
| DingXiang (顶象) | `*.dingxianginc.com`; init `captchaId`/`appId`; business request carries `token` | Slider with scrambled background (restored client-side) + token chain + backend SDK validation | Scrambled-image restoration is publicly documented; token-chain backward tracing; trajectory emulation as slider family | Invisible tier → environment scoring surface |

### International vendors

| Vendor | Identify (cookie / endpoint / param) | Mechanism | Handling path | Escalation |
|---|---|---|---|---|
| Cloudflare | `cf_clearance` + `__cf_bm`; `/cdn-cgi/challenge-platform/`; `__cf_chl_*`; Turnstile `challenges.cloudflare.com`, `cf-turnstile` marker | JS challenge + TLS/HTTP2 fingerprint + Turnstile human verification | Real-browser pass; **`cf_clearance` is bound to the egress IP (exit-IP binding)** — an egress switch kills it inside its nominal validity, re-acquire together (triad binding: crawler card); Turnstile solver services exist | Managed → interactive challenge / Turnstile appears → headful |
| Akamai | `_abck` (`~0~` valid / `~-1~` rejected) + `ak_bmsc`; `bmak` global | In-environment continuously generated sensor data (`sensor_data` POST) + TLS fingerprint | The sensor must be generated inside the environment — single-value forgery dies at the next validation | Canonical B3 family: real-environment residency, no intermediate states |
| PerimeterX / HUMAN | `_px`/`_px2`/`_px3` (short-lived) + `_pxvid`/`_pxhd`/`_pxcts`; `client.px-cloud.net`; `Press & Hold`; `x-px-authorization` (mobile) | Behavioral biometrics + environment consistency + interactive challenge | Repair environment + behavior together; `_px3` managed as short-window material; solver services exist | Frequent blocking → headful + real behavior profile |
| DataDome | `datadome` + `geo.captcha-delivery.com` interstitial | TLS/header/IP full-alignment detection + slider | Align the transport stack first (real browser or curl-impersonate class); proxy/UA/cookie triple binding | Slider keeps reappearing → device-check surface; environment repair |
| Kasada | Instant 403/429, no challenge page; `x-kpsdk-*` headers; `/ips.js` | Heavy client-side JS + per-request PoW/token | Material generated in-environment (headers + PoW as one set); transport fingerprint aligned in the same move; solver services exist | Pass-rate sag → rotate the environment; never tune to extend its life |

### Self-built stacks (自研)

| Vendor | Identify | Mechanism | Handling path | Escalation |
|---|---|---|---|---|
| Self-built | Random-prefix cookies; first-party challenge paths; non-standard status codes (412 + `retry-after`) | Hybrid — any commercial component may be embedded | Detection-point localization loop, field by field; generic `sign`/`token` via quickref five-step | After attribution, re-enter the decision tree by the owning signal family |

Identification lands as claim/fact (stack + traces + handling + failure history); read the site note before any
browser launch. Transport: JA3/JA4 ClientHello fingerprints kill requests before HTML — Cloudflare/Akamai/DataDome
feed TLS shape into the verdict; align via real browser or `curl_cffi`-class transport. TLS-vs-JS: heuristic row 3.

## Operator heuristics

| Observed signal | Verdict | First action | Escalation |
|---|---|---|---|
| First response 521 + `__jsluid_*` | JiaSuLe family | Solve clearance offline (pure-JS face first) | Unsolvable → B2 |
| 412/202 + `$_ts` + per-request body reshaping | RiverSecurity | Abandon loader hardcoding; straight to B2/B3 | Headful residency |
| TLS-fingerprint block but a real browser passes on the same egress | JS-challenge/scoring vendor, not TLS-level | Fix transport shape (browser or curl-impersonate class) | Still blocked → re-run identification |
| Transport fully aligned, still blocked | Fingerprint/scoring-driven (Akamai/DataDome high-risk) | Item-by-item environment-consistency diff | B2 → B3 |
| A slider appears | GeeTest/DingXiang/Shumei/Tencent class | Ask WHY it appeared — fixing the score beats solving | Score unfixable → solve material |
| Return params `ticket`+`randstr` or `lot_number`+`captcha_output` | Server-side-secondary-validation captcha | One-time material set; reuse forbidden | Solver services or real interaction |
| `cf_clearance` or `/cdn-cgi/challenge-platform` | Cloudflare | Real-browser pass + egress stickiness | Turnstile appears → escalate a link |
| `_abck` + `bmak` | Akamai | In-environment sensor route; never forge single values | B3 |
| `_px*` cookies (`_px3` short-lived) | PX/HUMAN | Environment + behavior repaired together | Frequent challenges → headful |
| `datadome` + `geo.captcha-delivery.com` | DataDome | Transport alignment first | Slider material window management |
| Instant 403/429 + `x-kpsdk-*` | Kasada | In-environment token/PoW generation | Pass-rate sag → rotate environment |
| Challenge JS on a first-party path + random cookie prefixes | Self-built / hybrid | Detection-point localization loop | Re-enter tree by signal family |
| Invisible challenge re-firing repeatedly | Score verdict, not a captcha | Audit session/frequency/IP triad | Repair to the "occasional" baseline |
| `navigator.webdriver === true` or headless UA marks | Automation exposure | Patch and retest, carrying failure evidence | Repeatedly named → B2 |

## Active-challenge parameter chains (slider-class)

The active-challenge branch produces parameter chains: the submit request consumes values (fingerprint blob,
challenge id, trajectory payload) that earlier responses and page code produced. Tracing forward from page load
fails because the chain computes BACKWARD from the consumer. Fix — backward endpoint tracing: (1) start at the
LAST request, split its params into server-issued-earlier vs page-computed; (2) trace ONE hop per iteration
(consume-point → producing function → its inputs), keeping every attribution claim checkable; (3) a leaf is
terminal when it resolves to a server-issued value or a captured environment reading.

Known-library leaf shortcut: a computed parameter matching a public fingerprint library's hash
(fingerprintjs-class `x64hash128`) is NOT solved by emulating the library — reimplement the hash offline over the
SAME fields the page feeds it; the input assembly is the target-specific part. Offline output must equal the live
value; on mismatch diff fields, never the hash. Challenge bundles defeat naive string search in three shapes:

| Shape | What it looks like | Mechanical pass |
|---|---|---|
| decoder-call reassembly | strings in an array consumed as decoder calls concatenated at run time (`e("0x4c")+"gth"`) | Run the decoder, dump its output table — or hook it and record arguments |
| proxy-wrapper collapse | property access routes through generated wrappers; the call site shows the wrapper | Collapse wrappers to their target operation before reading control flow |
| object-literal key obfuscation | config keys are computed, so a parameter table reads as noise | Resolve computed keys once, rename, re-read |

### Challenge-element locator ladder

Climb one rung at a time; record the working rung in the site note. (1) stable attribute/DOM-path selectors first;
(2) HTML-structure fallback — attributes randomized, so locate by landmark position and class shape; (3) vision
locating (screenshot + element-shape recognition) as the floor — immune to DOM-level obfuscation, but layout
changes break it silently; re-verify each session.

## Detection-point localization: trigger → observe → attribute loop

Camoufox is a debuggable/instrumentable browser. **Trigger**: bisect the request chain to the minimal must-have set,
one change at a time, saving pass/fail pairs as evidence. **Observe**: XHR/fetch hook presets injected via
`page.evaluateOnNewDocument` (active before page code runs), CDP `Network.requestWillBeSent` as the full-frame
floor, WebSocket frames via CDP, DOM breakpoints on the `document.cookie` setter and storage writes (marker cookies
surface there), then walk the initiator stack to the producing function; CDP is identical headless vs headful.
**Attribute**: diff the pass/fail pair to candidates, trace to the producing-code boundary (`hook_function` trace
position), pick a decision-tree branch once unique — attribution lands as a fact (I/O pair + replay command). The
loop exits only on verified fix or evidence insufficiency (LEARN ladder: internal re-library before external).

## Failure-mode notes

- Single-fingerprint stack calls: cookie naming rotates and collides — two independent hits minimum; tables yield priors.
- Challenge pages parsed as business data: RiverSecurity empty-body 200, Cloudflare/DataDome interstitials masquerade — status/page-shape check before parsing.
- Material reuse across windows: `_px3` short-lived, `ticket`/`randstr` one-shot, `cf_clearance` dies with the egress — each family managed in its own window.
- Fixing the hash when a library match fails: wrong direction — diff the input fields, never the hash.
- Challenge solved but business still rejects: secondary-validation families need the material set delivered as a group — classify via heuristic row 6 first.
- Identification never recorded: without the site note the next case burns from zero — the compounding lives in notes.
