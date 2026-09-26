---
name: web-risk-control
description: 'Anti-bot / risk-control doctrine for web targets: signal taxonomy (device fingerprint /
  behavioral / environment-consistency / protocol-layer challenges), adversarial decision tree
  bypass→emulate→real with the headless-first escalation chain, vendor-stack identification
  (JiaSuLe 加速乐 jsl_clearance, RiverSecurity 瑞数 $_ts, Aliyun WAF acw_sc, GeeTest 极验, Tencent TCaptcha,
  NetEase YiDun NECaptcha, Shumei 数美 smid, DingXiang 顶象, Cloudflare cf_clearance/turnstile, Akamai
  _abck/bmak, PerimeterX HUMAN _px3, DataDome, Kasada x-kpsdk, self-built stacks), per-vendor challenge
  mechanisms and per-vendor handling paths (厂商处理路径/挑战机制), operator heuristics
  (启发式; observed signal → verdict → first action → escalation), active-challenge parameter chains (slider backward endpoint tracing, known-library hash
  reimplementation, challenge-bundle obfuscation passes), and the detection-point localization
  trigger→observe→attribute loop with camoufox/CDP instrumentation. When a request is blocked /
  challenged / a signed parameter is rejected on a web target — classify the signal, identify the
  vendor stack, pick the handling path. Not for the parameter-recovery workflow itself
  (web-re-quickref owns it) nor collection ops after access is solved (web-crawler-engineering).'
domain: web
family: risk-control
---
# Web anti-bot / risk-control field reference

> Domain: web targets (`--type web` workspaces) — the defense-response face of browser JS RE. Companion to
> `web-re-quickref.md` (how to peel and locate a signed parameter); this file answers why the request is blocked,
> which vendor stack is on the wire, and what to do about it.

## TL;DR — stack identification at a glance

| First signal observed | Verdict | First action |
|---|---|---|
| First response 521 + cookie `__jsluid_*` | JiaSuLe family (加速乐) | Solve `jsl_clearance_s` offline (pure JS surface) |
| 412/202 + `$_ts` + body reshaped per request | RiverSecurity (瑞数) | Skip static replay; go straight to environment emulation |
| Blocked with `acw_sc__v2` cookie missing | Aliyun WAF (阿里云盾) | Solve the JS validation segment, refill cookie, retest |
| `cf_clearance` / `/cdn-cgi/challenge-platform` | Cloudflare | Pass with a real browser; cookie lifetime = egress lifetime |
| Instant 403/429 + `x-kpsdk-*` headers | Kasada | Generate token/PoW material inside the environment |
| Slider / click captcha appears | GeeTest/DingXiang/Shumei/Tencent class | Fix the environment score first; solving comes second |
| Challenge JS on a first-party path + random cookie prefixes | Self-built stack | Detection-point localization loop, field by field |

Verdict discipline: never call the stack from a single fingerprint — two independent hits minimum.

## Signal taxonomy

Four families, cheapest-first for the defender. A block is usually a CONJUNCTION — several families add up past a threshold; countermeasures target families, not symptoms: identify the family that fired first.

### Device fingerprint

Stable per-environment collectors, diffed across requests and against known-bad sets; drift BETWEEN requests is the
louder tell — a mid-run canvas/renderer flip is an automation artifact.

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

The browser channel runs **headless by default**; headful is the adversarial chain's last link, not the start.

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

Shape-based recognition — vendors rotate internals but loader/challenge/cookie shapes persist; identify from static traces BEFORE opening the browser. Uniform quadruple per vendor: identify → mechanism → handling → escalation. Methodology level only — which layer to hook, what to simulate, which tool CLASS; no runnable recipes (dual-use).

| Vendor | Identify (cookie / endpoint / param) | Mechanism | Handling path | Escalation |
|---|---|---|---|---|
| JiaSuLe / ChuangyuDun (加速乐/创宇盾) | `__jsluid_*` + `__jsl_clearance_s`; first response 521 | JS challenge — pure front-end clearance computation | Two requests map the set-cookie sequence; lift the inline loader JS, compute clearance offline | Algorithm change breaks offline solve → B2 |
| RiverSecurity (瑞数) | `$_ts`; body reshaped per request; 412/202 + meta-refresh; cookie suffixes T/S/O/P | Dynamic obfuscated JS regenerated per request + environment checks → dynamic cookie/token | Hook the VM boundary (Path A) or full environment emulation (Path B / env stubbing); never hardcode the loader | Either route unstable → B3 headful residency (emulation ceiling) |
| Aliyun WAF (阿里云盾) | `acw_tc` + `acw_sc__v2/_v3` | JS validation segment computes the cookie, then reloads; upgrade face is slider/invisible | Solve the validation segment, refill cookie; preserve `acw_tc` continuity | v3/slider → trajectory-material route or B2; captcha instance via SceneId triad (crawler card) |
| GeeTest (极验) v3/v4 | v3 `gt`/`challenge`; v4 `captcha_id` + `lot_number`/`captcha_output`/`pass_token`/`pow_msg`; `gt4.js` | Slider/click/icon + encrypted submit (v4 `w`: multi-layer encryption + PoW); server-side secondary validation | Trajectory quality first (accel-decel-overshoot; constant speed always fails); recover the submit chain by backward endpoint tracing | `risk_type` invisible/AI → score verdict, not a puzzle; environment repair |
| Tencent TCaptcha (腾讯天御) | `t.captcha.qq.com`; `ticket` + `randstr` return; `cap_union_prehandle` | Slider/click + server-side secondary validation (`DescribeCaptchaResult`-class) | Material travels as a one-time set — reusing `ticket`/`randstr` is fatal | High-frequency popups = collapsed score; audit session/frequency/IP triad |
| NetEase YiDun (网易易盾) | `dun.163.com` family; `NECaptcha`; init `captchaId` | Slider/click/icon + register/check pair + server-side secondary validation | Parameter-chain backward tracing; archive material in its validity window | Invisible mode → behavioral scoring; environment repair |
| Shumei (数美) | `deviceId`/`smid`; `organization`/`captchaId`; register+check pair | Device-fingerprint ID bound to a behavior profile + slider/click/invisible | Identity-ID binding must not rotate (fresh IDs are high-risk); fingerprint face via environment emulation | Risk level stays high → audit environment + identity sets together |
| DingXiang (顶象) | `*.dingxianginc.com`; init `captchaId`/`appId`; business request carries `token` | Slider with scrambled background (restored client-side) + token chain + backend SDK validation | Scrambled-image restoration is publicly documented; token-chain backward tracing; trajectory emulation as slider family | Invisible tier → environment scoring surface |
| Cloudflare | `cf_clearance` + `__cf_bm`; `/cdn-cgi/challenge-platform/`; `__cf_chl_*`; Turnstile `cf-turnstile` marker | JS challenge + TLS/HTTP2 fingerprint + Turnstile human verification | Real-browser pass; **`cf_clearance` is bound to the egress IP (exit-IP binding)** — an egress switch kills it inside its nominal validity, re-acquire together (triad binding: crawler card) | Managed → interactive challenge / Turnstile appears → headful |
| Akamai | `_abck` (`~0~` valid / `~-1~` rejected) + `ak_bmsc`; `bmak` global | In-environment continuously generated sensor data (`sensor_data` POST) + TLS fingerprint | The sensor must be generated inside the environment — single-value forgery dies at the next validation | Canonical B3 family: real-environment residency, no intermediate states |
| PerimeterX / HUMAN | `_px`/`_px2`/`_px3` (short-lived) + `_pxvid`/`_pxhd`/`_pxcts`; `client.px-cloud.net`; `Press & Hold` | Behavioral biometrics + environment consistency + interactive challenge | Repair environment + behavior together; `_px3` managed as short-window material | Frequent blocking → headful + real behavior profile |
| DataDome | `datadome` + `geo.captcha-delivery.com` interstitial | TLS/header/IP full-alignment detection + slider | Align the transport stack first (real browser or curl-impersonate class); proxy/UA/cookie triple binding | Slider keeps reappearing → device-check surface; environment repair |
| Kasada | Instant 403/429, no challenge page; `x-kpsdk-*` headers; `/ips.js` | Heavy client-side JS + per-request PoW/token | Material generated in-environment (headers + PoW as one set); transport fingerprint aligned in the same move | Pass-rate sag → rotate the environment; never tune to extend its life |

Identification lands with evidence (stack + traces + handling + failure history); read the site note before any browser launch. Transport: JA3/JA4 ClientHello fingerprints kill requests before HTML — align via real browser or `curl_cffi`-class transport.

## Operator heuristics

| Observed signal | Verdict | First action | Escalation |
|---|---|---|---|
| TLS-fingerprint block but a real browser passes on the same egress | JS-challenge/scoring vendor, not TLS-level | Fix transport shape (browser or curl-impersonate class) | Still blocked → re-run identification |
| A slider appears | GeeTest/DingXiang/Shumei/Tencent class | Ask WHY it appeared — fixing the score beats solving | Score unfixable → solve material |
| Return params `ticket`+`randstr` or `lot_number`+`captcha_output` | Server-side-secondary-validation captcha | One-time material set; reuse forbidden | Solver services or real interaction |
| Invisible challenge re-firing repeatedly | Score verdict, not a captcha | Audit session/frequency/IP triad | Repair to the "occasional" baseline |
| `navigator.webdriver === true` or headless UA marks | Automation exposure | Patch and retest, carrying failure evidence | Repeatedly named → B2 |
| Challenge solved but business still rejects | Secondary-validation family | Deliver the material set as a group | Re-run identification per heuristic rows above |

## Active-challenge parameter chains (slider-class)

The active-challenge branch produces parameter chains: the submit request consumes values (fingerprint blob, challenge id, trajectory payload) that earlier responses and page code produced, and the chain computes BACKWARD from the consumer. Fix — backward endpoint tracing: (1) start at the LAST request, split its params into server-issued-earlier vs page-computed; (2) trace ONE hop per iteration (consume-point → producing function → its inputs), keeping every attribution claim checkable; (3) a leaf is terminal when it resolves to a server-issued value or a captured environment reading.

Known-library leaf shortcut: a computed parameter matching a public fingerprint library's hash (fingerprintjs-class `x64hash128`) is NOT solved by emulating the library — reimplement the hash offline over the SAME fields the page feeds it; the input assembly is the target-specific part. Offline output must equal the live value; on mismatch diff fields, never the hash. Challenge bundles defeat naive string search in three shapes:

| Shape | What it looks like | Mechanical pass |
|---|---|---|
| decoder-call reassembly | strings in an array consumed as decoder calls concatenated at run time (`e("0x4c")+"gth"`) | Run the decoder, dump its output table — or hook it and record arguments |
| proxy-wrapper collapse | property access routes through generated wrappers; the call site shows the wrapper | Collapse wrappers to their target operation before reading control flow |
| object-literal key obfuscation | config keys are computed, so a parameter table reads as noise | Resolve computed keys once, rename, re-read |

### Challenge-element locator ladder

Climb one rung at a time; record the working rung in the site note. (1) stable attribute/DOM-path selectors first; (2) HTML-structure fallback — attributes randomized, so locate by landmark position and class shape; (3) vision locating (screenshot + element-shape recognition) as the floor — immune to DOM-level obfuscation, but layout changes break it silently; re-verify each session.

## Detection-point localization: trigger → observe → attribute loop

Camoufox is a debuggable/instrumentable browser. **Trigger**: bisect the request chain to the minimal must-have set, one change at a time, saving pass/fail pairs as evidence. **Observe**: XHR/fetch hook presets injected via
`page.evaluateOnNewDocument` (active before page code runs), CDP `Network.requestWillBeSent` as the full-frame
floor, WebSocket frames via CDP, DOM breakpoints on the `document.cookie` setter and storage writes (marker cookies
surface there), then walk the initiator stack to the producing function. **Attribute**: diff the pass/fail pair to
candidates, trace to the producing-code boundary (`hook_function` trace position), pick a decision-tree branch once
unique — attribution lands with an I/O pair + replay command. CDP behavior is identical headless vs headful; the
loop exits only on verified fix or evidence insufficiency (internal re-library before external search).

```bash
# CDP is identical headless vs headful: enumerate targets, attach a client
curl -s http://127.0.0.1:9222/json/version
```

```javascript
// One-shot fingerprint dump via evaluate_js — run on BOTH sides of a pass/fail
// pair, twice per side for stability. The first differing field is the
// detection candidate: attribute it before touching any code.
(() => {
  const gl = document.createElement("canvas").getContext("webgl");
  const dbg = gl && gl.getExtension("WEBGL_debug_renderer_info");
  const probe = document.createElement("canvas");
  probe.getContext("2d").fillText("fingerprint-probe", 4, 8);
  return {
    webdriver: navigator.webdriver,
    userAgent: navigator.userAgent,
    platform: navigator.platform,
    languages: navigator.languages,
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    hardwareConcurrency: navigator.hardwareConcurrency,
    deviceMemory: navigator.deviceMemory,
    webglRenderer: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : null,
    canvasDigest: probe.toDataURL().slice(0, 96)
  };
})();
```

XHR/fetch/WS wrapper source for the same injection point lives in `web-re-quickref.md` (hook & breakpoint quick reference) — inject at `evaluateOnNewDocument` time so the wrappers exist before target code runs.

## Failure-mode notes

- Single-fingerprint stack calls: cookie naming rotates and collides — two independent hits minimum; tables yield priors.
- Challenge pages parsed as business data: RiverSecurity empty-body 200, Cloudflare/DataDome interstitials masquerade — status/page-shape check before parsing.
- Material reuse across windows: `_px3` short-lived, `ticket`/`randstr` one-shot, `cf_clearance` dies with the egress — each family managed in its own window.
- Identification never recorded: without the site note the next case burns from zero — the compounding lives in notes.
