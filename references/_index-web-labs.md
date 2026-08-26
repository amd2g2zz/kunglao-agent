# web-labs domain index (file level)

> Domain: browser JS reverse engineering for `--type web` workspaces. Read this
> file when dispatched to a web target or when the project type is `web`.

## Files

| File | One-line summary | When to read |
|---|---|---|
| [web-re-quickref.md](re-library/web-re-quickref.md) | Six-section quick-reference: hooks, signed-parameter workflow, layered peeling routing, crypto signatures, anti-patterns, advanced topics | Before opening the browser on a web target; injected into workspace CLAUDE.md at init |

## Supply

| Provider | Capability | Notes |
|---|---|---|
| camoufox-reverse (MCP, WARN) | browser JS RE: hooks/trace/network/camoufox MCP manifest | Manual registration required; see the MCP table in workspace CLAUDE.md |
| wakaru (npx, sole) | `js:unbundle` | Bundler unpack + transpiler/minifier undo; not for obfuscation/VM code |
| webcrack (npx, sole) | `js:deobfuscate` | Classic obfuscation deobfuscation; run before wakaru on obfuscated samples |

## Quick-reference section map

| Section | Purpose |
|---|---|
| Hook & breakpoint quick reference | Boundary I/O hooks (XHR/fetch/eval/cookie/setTimeout/canvas) — where to intercept interesting values |
| Signed-parameter location workflow | Five-step procedure from task contract to verified algorithm fact |
| Obfuscation recognition and layered peeling | Detection-driven loop: unbundle → deobfuscate → VM boundary; re-inspect after every pass |
| Crypto-algorithm signatures | Ciphertext shape → algorithm family (hash/BASE64/AES/HMAC/RSA) |
| Anti-patterns | Top five mistakes in web RE (browser-before-books, hardcoded sessions, impossibility after one attempt, skipped replay, shipping the automation) |
| Advanced topics | JSVMP analysis, source-level instrumentation, engine tracing, env emulation diffing, protocol reassembly |
