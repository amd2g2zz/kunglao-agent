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

> Domain: web targets (`--type web` workspaces) — the defense-response face of
> browser JS RE. Companion to `web-re-quickref.md`: that file answers "how do I
> peel and locate a signed parameter"; this file answers "why is the request
> blocked, which vendor stack is on the wire, and what do I do about it".
> Web-domain specific: malware/android domains do not inherit it. Reading order
> is progressive disclosure: TL;DR stack ID → signal taxonomy → decision tree →
> vendor identification → per-vendor handling → heuristics → deep-dive topics.

## TL;DR — stack identification at a glance

| First signal observed | Verdict | First action |
|---|---|---|
| First response 521 + cookie `__jsluid_*` | JiaSuLe family (加速乐) | Solve `jsl_clearance_s` offline (pure JS surface) |
| 412/202 + `$_ts` + body reshaped per request | RiverSecurity (瑞数) | Skip static replay; go straight to environment emulation |
| Blocked with `acw_sc__v2` cookie missing | Aliyun WAF (阿里云盾) | Solve the JS validation segment, refill cookie, retest |
| `cf_clearance` / `/cdn-cgi/challenge-platform` | Cloudflare | Pass with a real browser; cookie lifetime = egress lifetime |
| Instant 403/429 + `x-kpsdk-*` headers | Kasada | Generate token/PoW material inside the environment |
| Slider / click captcha appears | GeeTest/DingXiang/Shumei/Tencent class | Fix the environment score first; solving comes second |

Verdict discipline: never call the stack from a single fingerprint — require
at least two independent fingerprint hits before a conclusion (master table
below).

## Signal taxonomy

Four families, ordered by how cheap they are for the defender to run. A block
is usually a CONJUNCTION: the score crosses a threshold after several families
add up. Identify which family fired before choosing a countermeasure —
countermeasures target families, not symptoms.

### Device fingerprint

Stable per-environment collectors; the defender diffs them across requests and
against known-bad value sets.

| Signal | Locate (camoufox / CDP) | Respond |
|---|---|---|
| canvas hash (texture variance) | `evaluate_js` returns `toDataURL` digest; run twice to check stability | Fingerprint-forgery surface: inject noise or sample a real-environment profile (Path B) |
| WebGL renderer/vendor (`UNMASKED_RENDERER`) | JS probe in console; also visible in fingerprint dump scripts | UA/render-stack consistency outranks any single-value spoof |
| Font-list probing | enumerate probe via offset-measure script; CDP `DOM.getDocument` diff | Missing fonts are more suspicious than extra fonts; backfill the common families |
| Audio (AudioContext DSP fingerprint) | offline-render sum probe via `evaluate_js` | Stay in the same device generation (mobile audio stack ≠ desktop) |
| Hardware params `hardwareConcurrency/deviceMemory/screen/battery/platform` | one-shot `evaluate_js` JSON dump → attribution table | Whole-set consistency: any field whose device generation diverges from the UA claim is fatal |

Device-fingerprint drift BETWEEN requests is the louder tell than any single
value: same session flipping canvas or renderer mid-run = automation artifact.

### Behavioral signals

Only observable inside the page over time; cheapest to defeat by pacing.

| Signal | Locate | Respond |
|---|---|---|
| Mouse-trajectory entropy (straight lines / teleports / low capture rate) | hook `mousemove`, sample your own traffic, compare distributions against human samples | Generate trajectories with noise curves + overshoot-rebound; under headful prefer input injection over raw coordinate writes |
| Input cadence (fixed intervals / paste-only) | keydown timestamp-sequence hook | log-normal jitter; mix paste + hand-typed intervals |
| Dwell time (instant click on arrival, no scrolling) | page lifecycle event timeline | Human pacing first — reading-style dwell and random viewport scrolls before actions |

### Environment consistency (cross-checks)

The scorer cross-checks CLAIMED identity vs OBSERVED environment.

| Cross-check | Observation point | Respond |
|---|---|---|
| UA ↔ fingerprint | UA says Windows but `platform`/touch/webgl renderer disagrees → veto-grade | Pick the UA from the fingerprint, never dress the fingerprint to fit a UA |
| Timezone ↔ IP geo | `Intl.DateTimeFormat().resolvedOptions().timeZone` vs egress IP country | Align the proxy landing timezone; check before obfuscating |
| Language stack ↔ navigator.languages | `Accept-Language` header vs `navigator.languages` mismatch | Derive both from one config source |

### Protocol-layer challenges

Parameters computed by page code whose absence/expiry blocks you regardless of
environment quality.

| Parameter family | Verification face | Locate |
|---|---|---|
| sign / sig / x-bogus family | server-side recomputation | quickref five-step signed-parameter workflow (capture → initiator stack → algorithm → replay) |
| nonce / ts / sequence numbers | replay window + monotonicity checks | fire the same request twice, diff responses to size the window |
| device_id / fid binding IDs | server binds a behavior profile after first issuance | never rotate — a frequently refreshed ID is itself a high-risk signal |

## Adversarial decision tree

Classify FIRST, then branch. Never jump to solver/emulation before knowing
which family scored you out.

```
classify the detection:
  ├─ passive only (fingerprint/score, no interstitial)
  │    → tighten environment consistency first (cheapest fix surface)
  ├─ active challenge (JS challenge / slider / click-text)
  │    → environment may be fine; you are being TESTED → simulate or solve
  └─ protocol signature missing/expired
       → no environment fix helps → locate algorithm (quickref workflow)

then pick ONE branch by cost ladder:
  B1 bypass   — rule gap: replay a legitimate token pair within its window,
                use a lighter unguarded endpoint, cache & reuse hand-solved
                material. Cheapest; fragile.
  B2 emulate  — Path B of quickref: capture the real fingerprint, replicate
                in a sandbox, pass the detection points; behavior simulated
                on top. For scorer/challenge targets.
  B3 real     — camoufox itself, full fidelity. Most expensive, most robust;
                reserved for cases B1/B2 cannot hold.
```

The escalation principle is rising cost: bypass first (when real material
exists), then emulate, then live in the real environment.

### Headless-first escalation chain

The browser MCP runs **headless by default** (cheap, parallelizable,
unattended-friendly). headful is not the starting point — it is the last link
of the adversarial chain:

```
headless default
  └─ anti-headless fingerprints detected? (decidable checklist, verified one
     by one via evaluate_js / network side)
       ├─ navigator.webdriver === true            → hide/patch, retest
       ├─ UA carries HeadlessChrome/headless marks → fix the UA stack, retest
       ├─ permissions/plugins/webgl vendor empty-set → fix the tier, retest
       ├─ CDP artifacts named by the challenge (≥2 times) ↓ next link
       ├─ still blocked after patching             → fingerprint emulation (B2)
       └─ still blocked after emulation            → headful last resort (B3)
```

Escalation discipline: every upgrade must carry the previous step's failure
evidence (which signal, what value, what was fixed) — "it feels detected" is
never a reason to jump to headful.

## Vendor-stack identification

Shape-based recognition — vendors rotate internals but loader/challenge/cookie
shapes persist. Identify from static traces BEFORE opening the browser. A hit
is a PRIOR, not a verdict: cookie names rotate across product generations;
require at least two independent fingerprint hits before calling the stack.

| Vendor | Cookie fingerprints | Challenge JS / endpoint fingerprints | Param / header fingerprints | Status / page shape |
|---|---|---|---|---|
| JiaSuLe / ChuangyuDun (加速乐/创宇盾) | `__jsluid_h`/`__jsluid_s` + `__jsl_clearance_s` | short obfuscated inline JS on first response, executes then reloads | — | first response 521; passes once clearance is set |
| RiverSecurity (瑞数) | cookies suffixed T/S (gen-5) and O/P variants | dynamic loader regenerated per response (content and length differ every time); `$_ts` global | — | 412/202 + meta-refresh self-jump; 200 with empty body |
| Aliyun WAF (阿里云盾) | `acw_tc`; `acw_sc__v2`/`acw_sc__v3` issued after JS validation | inline JS validation segment computes the cookie then reloads | — | block page / slider (captcha instance triad: see crawler card) |
| GeeTest (极验) | — | `static.geetest.com`/`api*.geetest.com` assets; `gt4.js` | v3 `gt`/`challenge`/`validate`/`seccode`; v4 `captcha_id` init + `lot_number`/`captcha_output`/`pass_token`/`pow_msg` submit | slider/icon/click widget |
| Tencent TCaptcha (腾讯天御/防水墙) | — | script loaded from `t.captcha.qq.com`; precheck `cap_union_prehandle` | client returns `ticket` + `randstr` | popup captcha |
| NetEase YiDun (网易易盾) | — | `dun.163.com` domain family (`c.dun.163.com`); `NECaptcha` naming | init `captchaId`; register/check endpoint pair | slider/click/icon |
| Shumei (数美) | — | JS SDK fingerprints the device before serving a challenge | `deviceId`/`smid` identifiers; `organization`/`captchaId`; register+check pair | slider/click/invisible |
| DingXiang (顶象) | — | `*.dingxianginc.com` assets | init `captchaId`/`appId`; business request carries `token` after pass | slider (scrambled background) |
| Cloudflare | `cf_clearance` (pass proof) + `__cf_bm` | `/cdn-cgi/challenge-platform/` scripts; Turnstile via `challenges.cloudflare.com` | URL params `__cf_chl_*`; `cf-turnstile` widget marker | challenge page / Turnstile widget |
| Akamai | `_abck` (`~0~` valid / `~-1~` rejected segment) + `ak_bmsc` | `bmak` global object; sensor POST | `sensor_data` payload | instant block or silent degradation |
| PerimeterX / HUMAN | `_px`/`_px2`/`_px3` (short-lived) + `_pxvid`/`_pxhd`/`_pxcts` | scripts from `client.px-cloud.net`/`*.px-cdn.net` | `window._pxAppId`; `Press & Hold` challenge; `x-px-authorization` on mobile | block page / human challenge |
| DataDome | `datadome` | `geo.captcha-delivery.com` interstitial | — | interstitial page + slider |
| Kasada | — | `/ips.js` + per-request PoW | `x-kpsdk-*` header family | instant 403/429, no challenge page |
| Self-built (自研) | random-prefix cookies | first-party challenge-script paths | generic `sign`/`token` families | non-standard status codes (e.g. 412 + `retry-after`) |

### Transport-layer fingerprint (TLS / HTTP2)

JA3/JA4-class ClientHello fingerprints kill the request before any HTML is
served: the Cloudflare/Akamai/DataDome families all feed TLS shape into the
verdict, and Cloudflare adds HTTP2 frame ordering plus Client Hints. The
mature alignment routes are a real browser stack or a
`curl-impersonate`/`curl_cffi`-class transport (JA4+ is the successor
standard). The "TLS-level or JS-level" discriminator is heuristic row 3 below.

### Recording identification output

Identification output must land as claim/fact: stack name + trace evidence +
handling choice + failure history; the next case on the site reads the note
before opening a browser (site-note institution).

## Per-vendor handling

Uniform quadruple shape: identify → mechanism → handling path → escalation.
Handling stays at methodology level — name the layer to hook, what to
simulate, which tool CLASS is mature; older publicly documented techniques may
be cited, ready-to-run recipes for current commercial builds stay out (dual-use
discipline).

### China-market vendors

| Vendor | Identify | Challenge mechanism | Handling path | Escalation |
|---|---|---|---|---|
| JiaSuLe / ChuangyuDun (加速乐/创宇盾) | `__jsluid_*` + `__jsl_clearance_s`; first response 521 | JS challenge — pure front-end clearance-cookie computation, not fingerprint-driven | two requests to map the set-cookie sequence; lift the loader's inline JS and compute clearance offline; multi-generation obfuscation goes through the peel chain first | algorithm generation change breaks offline solve, or behavioral scoring appears → B2 environment emulation |
| RiverSecurity (瑞数) | `$_ts`; body reshaped per request; 412/202 + meta-refresh; cookie suffixes T/S/O/P | dynamically obfuscated JS regenerated per request + environment validation producing dynamic cookies/tokens | two mature routes: hook the VM boundary (Path A) or full environment emulation (Path B / env stubbing); never hardcode the loader | either route unstable → headful / real environment residency (B3) — the emulation ceiling of this space |
| Aliyun WAF (阿里云盾) | `acw_tc` + `acw_sc__v2/_v3` | JS validation segment computes the cookie then reloads; upgrade face is slider/invisible | solve the validation segment, refill the cookie, retest; preserve `acw_tc` session continuity | v3 validation or slider family → trajectory-material route or B2; captcha instance location via the SceneId triad |
| GeeTest v3/v4 (极验) | `gt`/`challenge` or `captcha_id` + `lot_number` family | slider/click/icon + encrypted client submit (v4 `w` param multi-layer encryption + PoW); server-side secondary validation | trajectory quality first (accelerate-decelerate-overshoot curve family; constant-speed lines always fail); recover the submit chain hop by hop via backward endpoint tracing; mature solver services exist (cite, don't ship) | `risk_type` invisible/AI tier → it is a score verdict, not a puzzle; go back to environment repair |
| Tencent TCaptcha (腾讯天御/防水墙) | `t.captcha.qq.com`; `ticket` + `randstr` return | slider/click + server-side secondary validation (`DescribeCaptchaResult`-class) | material must travel as a one-time set — reusing `ticket`/`randstr` is fatal; solver services exist | high-frequency popups = collapsed score; audit the session/frequency/IP triad |
| NetEase YiDun (网易易盾) | `dun.163.com` family + `NECaptcha` naming; init `captchaId` | slider/click/icon + register/check endpoint pair + server-side secondary validation | parameter-chain backward tracing; archive material within its validity window; solver services exist | invisible mode → behavioral scoring surface; back to environment repair |
| Shumei (数美) | `deviceId`/`smid` identifiers; register+check pair | device-fingerprint ID bound to a behavior profile + slider/click/invisible | identity-ID binding must not rotate (frequent fresh IDs are themselves high-risk); the fingerprint collection face goes through environment emulation | risk level stays high → audit environment and identity sets together |
| DingXiang (顶象) | `*.dingxianginc.com`; init `captchaId`/`appId`; `token` on the business request | slider (scrambled background restored client-side) + token chain + backend SDK validation | scrambled-image restoration is publicly documented; token chain backward tracing; trajectory emulation same as the slider family | invisible tier → environment scoring surface |

### International vendors

| Vendor | Identify | Challenge mechanism | Handling path | Escalation |
|---|---|---|---|---|
| Cloudflare | `cf_clearance`/`__cf_bm`; `/cdn-cgi/challenge-platform/` | JS challenge + TLS/HTTP2 fingerprint + Turnstile human verification | pass with a real browser; **`cf_clearance` is bound to the egress IP** — an egress switch kills the cookie inside its nominal validity, so re-acquire both together (triad binding: see crawler card); Turnstile-token solver services exist | managed challenge escalates to interactive / Turnstile widget appears → headful |
| Akamai | `_abck` (read the `~0~`/`~-1~` segment) + `ak_bmsc`; `bmak` object | in-environment continuously generated sensor data (`sensor_data` POST) + TLS fingerprint | the sensor must be generated inside the environment — single-value forgery is caught by the next validation; this family shares the emulation ceiling with RiverSecurity | the canonical B3 family: go straight to real-environment residency, skip intermediate states |
| PerimeterX / HUMAN | `_px`/`_px2`/`_px3` (short-lived) + `_pxvid`/`_pxhd`/`_pxcts` | behavioral biometrics + environment consistency + `Press & Hold` interactive challenge | repair environment and behavior together; manage `_px3` as short-window material; solver services exist | high-frequency blocking → headful + real behavior profile |
| DataDome | `datadome` + `geo.captcha-delivery.com` interstitial | TLS/header/IP full-alignment detection + slider | align the transport stack first (real browser or curl-impersonate class) before touching material; proxy/UA/cookie triple binding | slider keeps reappearing → device-check surface; back to environment repair |
| Kasada | instant 403/429 without a challenge page + `x-kpsdk-*` headers; `/ips.js` | heavy client-side JS + per-request PoW/token | material generated inside the environment (header family + PoW as one set); transport fingerprint aligned in the same move; solver services exist | token pass-rate sag → rotate the environment; never tune parameters to extend its life |

### Self-built stacks (自研)

| Vendor | Identify | Challenge mechanism | Handling path | Escalation |
|---|---|---|---|---|
| Self-built | random-prefix cookies; first-party challenge paths; non-standard status codes | hybrid — any commercial component may be embedded | no ready-made route → the detection-point localization loop, field by field; generic `sign`/`token` params go through the quickref five-step workflow | once attribution completes, re-enter the decision tree by the owning signal family |

## Operator heuristics

| Observed signal | Verdict | First action | Escalation |
|---|---|---|---|
| First response 521 + `__jsluid_*` | JiaSuLe family | solve clearance offline (try the pure-JS face first) | unsolvable → B2 emulation |
| 412/202 + `$_ts` + body reshaping per request | RiverSecurity | abandon loader hardcoding; go straight to B2/B3 | headful residency |
| TLS-fingerprint block but a real browser passes on the same egress | JS-challenge/scoring vendor, not pure TLS-level | fix the transport shape (browser stack or curl-impersonate class) | still blocked → re-run the identification table |
| Transport fully aligned, still blocked | fingerprint/scoring-driven (Akamai/DataDome family high-risk) | item-by-item environment-consistency diff | B2 → B3 |
| A slider appears | GeeTest/DingXiang/Shumei/Tencent class | first ask WHY it appeared — fixing the score beats solving | score unfixable → solve the material |
| Return-param family `ticket`+`randstr` or `lot_number`+`captcha_output` | server-side-secondary-validation captcha | material travels as a one-time set; reuse forbidden | solver services or real interaction |
| `cf_clearance` or `/cdn-cgi/challenge-platform` | Cloudflare | real-browser pass + egress stickiness | Turnstile appears → escalate a link |
| `_abck` + `bmak` | Akamai | in-environment sensor route; never forge single values | B3 |
| `_px*` cookie family (`_px3` short-lived) | PX/HUMAN | repair environment + behavior together | frequent challenges → headful |
| `datadome` + `geo.captcha-delivery.com` | DataDome | transport alignment first | slider material window management |
| Instant 403/429 + `x-kpsdk-*` | Kasada | in-environment token/PoW generation | pass-rate sag → rotate environment |
| Challenge JS on a first-party path + random cookie prefixes | self-built / hybrid | detection-point localization loop for attribution | re-enter the decision tree by signal family |
| Invisible challenge re-firing repeatedly | score verdict, not a captcha | audit the session/frequency/IP triad | repair to the "occasional" baseline |
| `navigator.webdriver === true` or headless UA marks | automation exposure | patch and retest, carrying failure evidence | repeatedly named → B2 |

## Active-challenge parameter chains (slider-class)

The challenge-face tree's "active challenge" branch (slider / click-text /
JS challenge) produces parameter chains: the submit request consumes values
(fingerprint blob, challenge id, trajectory payload) that earlier responses
and page code produced. Default: start tracing at page load or at the first
request. That fails because the chain computes BACKWARD from the consumer —
the parameter exists at the submit request and every producing hop hides a
request fetch or a collector call. Fix — backward endpoint tracing:

1. Start at the LAST request (the submit that gates the action). Split its
   parameter set: server-issued earlier (cookie/session-carried) vs
   page-computed (JS).
2. Trace ONE hop backward per iteration: consume-point → producing function
   → its inputs (a fetched response value or a browser-collector reading).
   One hop per iteration keeps every attribution claim checkable — assuming
   the whole chain does not survive contact.
3. Leaves are terminal when they resolve to a server-issued value or a
   captured environment reading; anything else goes another hop.

Known-library leaf shortcut: when a computed parameter matches a public
fingerprint library's hash (fingerprintjs-class `x64hash128`), do NOT
emulate the library — reimplement the hash offline over the SAME fields the
page feeds it. The library is public; the INPUT ASSEMBLY is the
target-specific part. Offline output must equal the live value; mismatch
means the assembly differs — diff fields, not the hash.

Reading the challenge bundle — three shapes that defeat naive string search
(you would grep the bundle for the parameter name; all three shapes make
that fail by construction — each is defeated by a mechanical pass, not a
search):

| Shape | What it looks like | Mechanical pass |
|---|---|---|
| decoder-call reassembly | strings live in a string array consumed as decoder calls concatenated at run time (`e("0x4c")+"gth"` shape) | run the decoder, dump its output table — or hook the decoder at run time and record arguments |
| proxy-wrapper collapse | property access routes through generated wrapper functions; the call site shows the wrapper, not the operation | collapse wrappers to their target operation before reading control flow |
| object-literal key obfuscation | config/map keys are computed, so a parameter table reads as noise | resolve computed keys once, rename, re-read — the table falls out |

### Challenge-element locator ladder

Interactive elements arrive layered in obfuscation and the first selector
fails — climb this ladder one rung at a time, recording the working rung in
the site note:

1. **Stable attribute / DOM path** selectors first (cheapest);
2. **HTML-structure fallback** — when attributes are randomized, locate by
   landmark elements' relative position and class shape (structure outlives
   attributes);
3. **vision locating** (screenshot + element-shape recognition) as the floor —
   most expensive, but immune to every DOM-level obfuscation; layout changes
   break it silently, re-verify each session.

## Detection-point localization: trigger → observe → attribute loop

Camoufox is a debuggable/instrumentable browser — not a "page container you
can reach". Localizing the root-cause field of a blocked request converges
with this loop; every step has a definite camoufox operation:

1. **Trigger** — minimal reproduction: bisect the request chain (keep/drop
   headers, cookies, params) to the minimal set that must be present. Change
   one thing at a time; diff results into evidence (save pass/fail pairs
   together).
2. **Observe** — use the camoufox debug channel to see where data is born:
   - XHR/fetch send interception: hook presets injected via
     `page.evaluateOnNewDocument` (active before page code runs); CDP
     `Network.requestWillBeSent` as the floor for full outbound frames;
   - WebSocket frame-level observation: CDP `Network.webSocketFrameSent/Sent`;
   - write watching: DOM breakpoints on the `document.cookie` setter and
     localStorage/sessionStorage writes — risk-control marker cookies surface
     here;
   - once a breakpoint holds, walk the call stack back to the producing
     function (initiator stack, same as quickref Step 2).
   CDP behavior is identical under headless and headful — debug
   instrumentation never needs a headful upgrade by itself.
3. **Attribute** — diff the pass/fail request pair to candidate fields; trace
   candidates back to the producing-code boundary (hook_function trace
   position); once attribution is unique, pick a decision-tree branch
   (bypass/emulate/real). Attribution lands as a fact (I/O pair + replay
   command).

The loop has exactly two exits: fix verified (replay/revisit succeeds), or
evidence insufficient for any branch (back down the LEARN ladder — what this
file lacks, search re-library internally before external retrieval; see the
worker contract).

## Failure-mode notes

- **Calling the stack from one fingerprint**: cookie naming rotates across
  generations and collides across sites — two independent fingerprint hits
  before a verdict; the identification table only yields priors.
- **Parsing a challenge page as business data**: RiverSecurity's empty-body
  200, Cloudflare challenge pages, and DataDome interstitials all masquerade
  as normal responses — run the status/page-shape check before parsing.
- **Material reuse across windows**: `_px3` is short-lived, `ticket`/`randstr`
  are one-shot, `cf_clearance` dies with the egress — manage each family's
  material inside its own window; expired means re-acquired.
- **Fixing the hash when a fingerprint-library match fails**: wrong direction —
  the input assembly changed; diff the fields, never the hash (see the
  known-library leaf shortcut in parameter chains).
- **Challenge solved, business still rejects**: secondary-validation families
  (GeeTest/Tencent/YiDun) require the material set delivered to the server as
  a group; single-point breakthroughs are meaningless — re-read heuristic
  row 6 to classify first.
- **Identification output never lands**: stack + traces + handling + failure
  history missing from the site note means the next case on the site burns
  from zero — the compounding of identification lives in the note institution.
