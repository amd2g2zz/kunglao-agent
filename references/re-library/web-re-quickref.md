# Web reverse engineering quick reference (labs)

> Domain: browser JS targets (`--type web` workspaces). Supply face: the
> `camoufox-reverse` MCP server (see the mcp manifest — manual registration,
> never auto-installed by init). Channel default: docker. Labs positioning:
> minimal integration, WARN-only toolchain face; this file is both the
> repo-level reference and the content injected into web workspace CLAUDE.md
> at init time.

## Hook & breakpoint quick reference

Hooks answer one question first: *where does the interesting value cross a
boundary?* Group the hooks by the boundary they watch.

**Request boundaries** (capture parameters before they leave the page):

```javascript
// XHR: wrap open/send on the prototype, log method/url/body + stack
// fetch: wrap window.fetch, log url/options + stack
// WebSocket: wrap the constructor, then send() and the message listener
// jQuery: wrap $.ajax, log url/data (legacy sites still route through it)
```

**Algorithm boundaries** (watch values enter and leave crypto code):

```javascript
// JSON.parse / JSON.stringify wraps — serialization often precedes signing
// atob / btoa wraps — cheap Base64 layers surface immediately
// eval / new Function proxy — packed code exposes its plaintext at execution
```

**State boundaries**:

```javascript
// document.cookie via Object.defineProperty setter + console.trace —
//   finds dynamically generated cookies (the setter fires with a stack)
// setTimeout / setInterval guards — skip callbacks whose source contains a
//   debugger statement (anti-debug tripwire neutralized, page keeps living)
// canvas toDataURL / toBlob wraps and navigator property overrides —
//   observe the fingerprint surface when detection is fingerprint-driven
```

**Injection order with the camoufox supply** (verified tool face):

1. Try a preset first: `inject_hook_preset` accepts `xhr`, `fetch`,
   `crypto`, `websocket`, `debugger_bypass`, `cookie`, `runtime_probe`.
2. Custom boundaries: `hook_function` for a named function, trace position
   for I/O observation.
3. Hooks must exist before target code runs — inject at page load, not
   after; re-run the page with hooks rather than hooking late.
4. Read results through `get_console_logs`; put `console.trace` at every
   capture point — the stack is the evidence, the log line is only the ping.

## Signed-parameter location workflow

One signed or encrypted parameter = one claim. Register the claim before
opening the browser; the steps below gather evidence for it.

- **Step 1 — Scope the target.** Name the parameter and the request that
  carries it (from the task contract). Everything downstream answers this
  one parameter.
- **Step 2 — Capture the request.** Start the network capture, `navigate`,
  locate the request via the request list; `get_request_initiator` returns
  the initiator stack — the golden path from network surface to producing
  code.
- **Step 3 — Land in the code.** Walk the stack; `search_code` finds the
  producing function in page scripts (save interesting bundles for offline
  work first).
- **Step 4 — Observe the algorithm.** Quick probes via `evaluate_js`;
  boundary I/O via `hook_function` in trace position; for a virtualized
  producer, peel first (next section) or switch to a boundary strategy.
- **Step 5 — Verify by replay.** Reproduce the parameter offline from the
  same inputs; `verify_signer_offline` is the independent check. A claimed
  algorithm that fails replay is a hypothesis, not a fact — the replay is
  the checker in maker-checker terms. Record the identified algorithm as a
  fact with the captured I/O pair and the replay command.

Two follow-through paths when the producer hides behind a virtual machine:

- **Path A — instrument.** Hook the interpreter boundaries, trace the
  dispatch loop, mine execution logs, and reverse the transformation from
  observed input/output pairs. Works when the signature logic is relatively
  independent of the environment.
- **Path B — emulate.** Capture the real browser fingerprint (environment
  comparison tool), replicate the environment in a JS DOM sandbox, diff item
  by item until detection points pass, then generate the parameter inside
  the sandbox. Required when the algorithm is welded to environment checks.

After a verified algorithm lands, write the site experience note
(`notes/site_<domain>.md`: defense shape, chosen pattern, verified pitfalls).
The next case on the same site reads that note *before* any browser launch.

## Obfuscation recognition and layered peeling

Peeling is a **loop, not a pipeline** — detection happens after every
transformation, because layers hide under layers:

```
inspect current form
  ├─ bundler / minifier traits   → npx wakaru --unpack   → re-inspect
  ├─ classic obfuscation traits  → webcrack              → re-inspect
  ├─ VM dispatcher traits        → boundary strategy (hook entry/exit,
  │                                runtime instrumentation)
  └─ nothing detectable          → clean → proceed to parameter location
```

Three principles:

1. **Peel in order, exit early.** Unbundle first, deobfuscate second; skip
   any layer whose traits are absent — a clean sample stops here.
2. **Layers hide under layers.** Re-inspect after every transformation; the
   file you are reading is never the final form until inspection comes back
   clean. Field case: one deobfuscation pass revealed a *second* obfuscation
   skin plus a VM interpreter underneath — the loop had to run twice.
3. **The VM layer is a boundary, not a puzzle.** Hooking interpreter
   input/output beats static devirtualization by an order of magnitude;
   full devirtualization is the last resort, not the plan.

Trait table — see the shape, take the route:

| Traits you observe | Route |
|---|---|
| Module cache calls, chunk identifiers, bundler runtime shims (webpack/esbuild/Browserify/Metro families), transpiler helper state machines, minifier residue (sequence expressions, inverted literals) | `npx wakaru bundle.js --unpack -o out/` — recovers the module tree |
| Rotated string array with hex index calls, `0x`-prefixed identifiers, hex member access, switch-state control-flow flattening, eval/Function packing, emoticon or symbol-only encoding skins | `webcrack input.js -o out/` — restores the classic-obfuscation layer; exotic skins (emoticon/symbol encodings) are dumped by executing them in the console instead |
| One huge data array as bytecode, a central dispatch loop (switch or handler table) inside an immediately-invoked function, rewritten native APIs, meaningless names | Boundary strategy — advanced topics below |

Combined samples (obfuscation *and* bundling): run webcrack first, then
wakaru on its output — deobfuscation is what makes the module structure
visible. Both tools are direct npx calls; no wrapper exists or is needed
(wakaru deliberately does not attack string arrays, control-flow flattening,
or VM protectors — that division of labor *is* the routing).

## Crypto-algorithm signatures

Read the captured value before reading the code — the shape narrows the
algorithm family:

| Signature | Family |
|---|---|
| 32 hex chars | MD5 |
| 40 hex chars | SHA-1 |
| 64 hex chars | SHA-256 |
| 128 hex chars | SHA-512 |
| trailing `=`, base64 alphabet | Base64 (`atob` confirms in one call) |
| base64url alphabet (`-` `_`) | Base64url — remap, then decode |
| ciphertext a multiple of 16 bytes | AES (key 16/24/32 bytes = 128/192/256; IV is 16 bytes; a mode that needs an IV is CBC, one without is ECB) |
| ciphertext a multiple of 8 bytes | DES / 3DES (8-byte key) |
| very long digit string, or PEM header present | RSA |
| HMAC / createHmac / HmacSHA tokens in source | HMAC over some payload |

Caveats worth their bytes: sites ship *modified* hash implementations
(tweaked constants) — compare against a reference implementation before
trusting the family label; the common JS crypto library defaults to PKCS7
padding with Base64 output; signing compositions are usually a plain
concatenation of parameters, timestamp, and secret (sorted-key and
nested-hash variants exist — replay each variant rather than guessing).

kunglao bookkeeping: the algorithm identification is a numeric-style fact —
carry the evidence (I/O pair, lengths, replay command) in the fact file, not
just the family name.

## Anti-patterns

1. **Browser before books.** Launching the browser before reading existing
   site notes and the environment report — a verified protocol solution may
   already sit in the workspace. The browser is the analysis instrument, not
   the deliverable.
2. **Hardcoded session values.** Pasting cookies or tokens into request
   templates works until it expires, then breaks silently. Regenerate them
   from the recovered algorithm instead.
3. **Impossibility after one attempt.** An SDK that stays dormant inside a
   DOM sandbox is a *step* failure, not proof the protocol is unrecoverable.
   Exhaust boundary hooks, interpreter traces, and sandbox variants before
   accepting a per-request-browser fallback.
4. **Skipping the replay check.** An algorithm explanation without offline
   reproduction is an unverified hypothesis. The replay is the checker.
5. **Shipping the automation.** The deliverable is a standalone protocol
   script (Node or Python) that survives a day in a headless container;
   browser automation is scaffolding for evidence collection, never the
   final artifact.

## Advanced topics

Index only — open on demand when the main workflow dead-ends:

- **JSVMP analysis** — when code inspection lands inside an interpreter
  loop; the dedicated interpreter hook is the entry point.
- **Source-level instrumentation** — when boundary hooks miss the moment
  that matters; rewrite scripts at load time instead of chasing them.
- **Engine-level property tracing** — when logic keys off property *reads*
  and no function boundary exists to hook.
- **Environment-emulation diffing** — when detection is fingerprint-driven
  rather than algorithm-driven; compare real versus sandbox environments.
- **Protocol reassembly** — assembling the standalone request generator
  from captured facts; the delivery step every case ends with.
