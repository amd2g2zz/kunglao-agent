---
name: web-crawler-engineering
description: 'Sustainable web-crawler collection engineering (爬虫工程): session persistence (cookie-pool
  tiers, login-state 登录态 stewardship), rate disguise (human-cadence pacing, per-domain budgets), IP strategy
  (residential vs datacenter tiers, sticky-vs-rotate semantics, egress quality checks), CAPTCHA triage
  (slider / click-select / re-challenge classification and response), slider gap matching (canny-edge-first
  localization, vendor discrimination), failure budgets and site profiling. After access is solved on a
  `--type web` target — designing sustainable collection ops or triaging a CAPTCHA surface. Not for WHY a
  request is blocked or challenged (web-risk-control owns the decision tree) nor for signature-parameter
  recovery (web-re-quickref).'
domain: web
family: crawler
---
# Web crawler engineering reference

> Domain: web targets (`--type web` workspaces) — the sustainability face of
> collection work, AFTER access is solved (`web-risk-control.md` owns "why am
> I blocked"). Field shape per section: signal → locate → respond. All
> practices assume the evidence discipline: every mechanical decision (a budget
> change, an IP-tier switch, a solver introduction) lands in a record with its
> trigger signal — nothing is tuned by feel.

## 会话维持 (session persistence)

Sessions are ASSETS: rebuild cost (registration, verification, warming) is an
order of magnitude above maintenance cost. Every rule below serves that
asymmetry.

| Signal / problem | Locate | Respond |
|---|---|---|
| cookie pool tiers missing (guest and logged-in jars mixed, shared jar) | inventory the jar/profile dirs + check same-slot concurrent writes | Three-tier pool: guest / session / logged-in; identity slot files carry metadata (registered-at, last-active, risk-event history); bare cookies without metadata are never reused |
| Login state (登录态) expiry failing silently (all results are login-wall pages) | response-status distribution: 401 / 302-to-login share creeping up over time | Sliding refresh — renew tokens BEFORE expiry; a batch of 401s triggers a whole-pool audit and a re-login backlog, never per-request brute retries |
| Identity linkage ban (one ban takes a chain) | IP/fingerprint/time-overlap analysis across identities in one pool | Identity↔fingerprint↔egress triple-binding table; any corner blacklisted → the whole group sleeps for observation, no probing with the remaining corners |
| storage cross-contamination (localStorage/sessionStorage across identities) | profile user-data-dir inventory diff | One user-data-dir per slot; flush + journal on process exit, verify consistency after restore before reuse |

```python
# Session asset inventory — run before any pool change; flags the two
# failure classes above (bare slots, expiring login states) mechanically.
import json, pathlib, time

def audit_slots(pool_dir: str, expiry_margin_s: int = 3600) -> dict:
    report = {"bare": [], "expiring": [], "ok": 0}
    for slot in pathlib.Path(pool_dir).glob("*.json"):
        meta = json.loads(slot.read_text())
        if not {"registered_at", "last_active"} <= meta.keys():
            report["bare"].append(slot.name)          # no metadata -> never reuse
        elif meta["last_active"] + expiry_margin_s < time.time():
            report["expiring"].append(slot.name)      # renew BEFORE it dies
        else:
            report["ok"] += 1
    return report
```

## 频率伪装 (rate disguise)

Machine pacing is itself a fingerprint: the defender fits your interval
distribution as cheaply as your TLS handshake.

| Signal / problem | Locate | Respond |
|---|---|---|
| Fixed-interval sleep (variance ≈ 0 machine rhythm) | interval histogram / std calc, wired into preflight self-check | log-normal jitter + burst-and-idle (humans have bursts AND pauses); constant sleep is rejected at plan review |
| No per-domain budget ledger (speed tuned by feel) | per-domain request counter rolling per minute/hour/day | Budget-table-driven scheduling; hitting the cap enters cooldown — never a key/IP swap to force through |
| Adaptive signals ignored | egress latency distribution + sliding-window block-rate monitor | Latency up or block-rate rising → auto-downshift one tier and record the trigger value; backing off is normal operation, not failure |
| New identity burned in its first hour | cold-start behavior-log replay for the fresh slot | Cold-start rate-limit observation period (low-frequency read-only), then step up to standard tier; every cold-start step must be discardable |

```python
# Human-cadence pacing: log-normal jitter + burst-and-idle.
import math, random, time

def next_delay(base_s: float = 3.0, sigma: float = 0.6,
               burst_p: float = 0.05, idle_p: float = 0.02,
               idle_s: float = 45.0) -> float:
    r = random.random()
    if r < idle_p:
        return idle_s + random.expovariate(1 / idle_s)   # long idle pause
    jitter = base_s * math.exp(random.gauss(0, sigma))   # log-normal core
    return jitter * random.choice((0.4, 1.0, 1.0, 2.5)) if r < idle_p + burst_p else jitter

def pace_forever(action):
    while True:
        time.sleep(next_delay())
        action()
```

## IP 策略 (IP strategy)

The IP is part of the identity, not a fungible pipe. Tier choice and rotation
semantics are two independent decisions; conflating them burns sessions.

| Dimension | Locate | Respond |
|---|---|---|
| Residential (住宅) vs datacenter (机房) | classify every proxy by egress ASN table; flag key domains separately | Risk-sensitive surfaces get residential ranges; datacenter ranges go to pathfinding requests, static assets, high-volume low-risk faces |
| Rotation semantics choice | sticky test: does a second request within one rotation window keep the same egress? | Session-binding risk control REQUIRES sticky-per-session; per-request rotation paints a "device hopping" high-risk profile (costlier than a fixed datacenter IP) |
| Where rotation is actively harmful | ban-event timeline vs IP-change time correlation | Login/payment/first-hop actions lock the egress; rotate only between stateless list pages |
| Egress quality check | blacklist lookup before enrollment + target warm-up probe (HEAD→GET low-volume ramp) | Segments failing checks are retired and logged; pollution found live is pulled immediately, keeping the failure evidence for review |

```bash
# Sticky-session verification — same tunnel, two requests, one egress answer.
for i in 1 2; do
  curl -sx "$PROXY_URL" --max-time 20 https://api.ipify.org; echo
done
# two different answers under one session = rotation semantics broken;
# session-bound targets will read the hop as a device change.
```

## 验证码分类应对 (CAPTCHA triage)

Classify first — each family has different cost AND a different root-cause
story. A CAPTCHA appearing at all is often a SCORE VERDICT, not a puzzle to
solve (that loop-back lives in web-risk-control.md's decision tree).

| Type | Signature | Respond |
|---|---|---|
| 滑块 slider | drag-to-align-gap interaction | Trajectory emulation: accel-decel-overshoot-rebound human curve family; constant-speed straight lines always fail. First ask WHY it appeared — repairing the environment score is cheaper and more durable than solving the block |
| 点选 click-select / click-order | click text or glyphs in sequence | Recognition services or human fallback enter via explicit registration (declared in the plan); successful samples archive WITH their challenge material inside the validity window |
| re-challenge / invisible | no visible interaction yet challenges re-fire, cookie issued then revoked immediately | Do not solve it as a captcha — this is an environment/behavior score verdict; take the risk-control decision tree B2/B3 branch and fix the root cause; solver pass-rates are permanently below a repaired score |
| High-frequency type | every request pops one, even static assets | Not a captcha problem but a collapsed score: audit the session/frequency/IP triad item by item, restore the "occasional" baseline before any other response |

### 滑块缺口匹配与厂商判别 (slider gap matching and vendor discrimination)

| Problem | Locate | Respond |
|---|---|---|
| Gap match drifts on textured/noisy backgrounds (raw template-match confidence low or jumping) | compare raw-match confidence against known gap positions | **canny-edge-first**: run edge detection over background AND gap images, locate the gap on the edge maps — significantly more stable against texture, noise, and anti-template tricks (抗模板干扰); the output coordinates still go through trajectory emulation above — matching only answers "where is the gap" |
| Four slider vendors misjudged as each other (confusion 误判: recipes are NOT cross-vendor compatible) | static traces on the challenge page: script-path shape, parameter naming, gap-image delivery | **Identify the vendor BEFORE choosing the recipe** — a wrong recipe burns budget AND pollutes the site note for the next case; archive the discrimination evidence together with the recipe |
| CAPTCHA endpoint location (aliyun-class prefix/SceneId triad) | challenge request path prefix + `SceneId` parameter + scene registration relation | The prefix pins the product family, `SceneId` pins the scene instance; both must agree with the site identity before location counts as done — a wrong scene invalidates every downstream assumption; re-triage before parameter tuning |

红线 (hard line): CAPTCHA response never changes the task's declared boundary
(authorization scope / data use per the task contract); any external
recognition service's introduction, volume, and data flow stay visible in the
plan and evidence.

## Failure budgets and stop-loss

| Signal | Stop-loss action |
|---|---|
| Same identity hits N consecutive CAPTCHAS/challenges | Retire the identity AND its bound triple (fingerprint + egress) for human inventory — never keep running wounded |
| Solve success rate below half the baseline | Record the recipe diff, retire the current solver recipe, return to classification |
| Budget overspend persists through three backoff tiers | Escalate the blocker (with tuned parameters and observed curves attached) for re-prioritization |

Every stop-loss output (success samples, failure pairs, hit rates) is raw
material for the next site note — collection engineering compounds through
notes, not memory.

## Collection cadence and site profiling

| Signal / problem | Locate | Respond |
|---|---|---|
| Multiple sites share one cadence/budget indiscriminately | per-site budget/rate comparison table exists? | Per-site profile (defense shape, baseline latency, budget tier, CAPTCHA frequency history); new sites start at the most conservative tier |
| Site redesign / risk-control upgrade unnoticed | baseline probe (weekly read-only visit recording success rate and latency) | Probe anomalies surface BEFORE business damage; triggers re-identification via the risk-control flow |
| Experience never accumulates, same site re-burned every case | notes/site_<domain>.md exists AND is read first by new sessions? | Three-part note: defense shape, verified solutions, pitfall list — mandatory reading before the next browser launch |

## Handoffs to neighboring layers

- Environment judged dead → `web-risk-control.md` adversarial decision tree
  (headless-first escalation chain inside);
- Parameter not computable → `web-re-quickref.md` signed-parameter workflow;
- Methods exhausted → LEARN ladder: internal re-library first, then external
  search (same-family precedents / known solutions / error signatures), with
  results recorded URL + retrieval date per evidence discipline.
