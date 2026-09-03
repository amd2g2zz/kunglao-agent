# web751 fixtures — gitnexus web semantic-index demo (#751)

Workspace-independent regression sample for tools/static/web_gitnexus_demo.py.

## Files

- `bundle.min.js` — hand-built webpack-shaped IIFE bundle (1.2 kB): module
  cache + numeric ids + `n(o)` require shim, minified whitespace/locals.
  Exported API names (`buildSignature`, `buildParams`, `digest`,
  `sendRequest`) deliberately survive as property assignments — the common
  real-world class where bundlers mangle locals but keep exported surface.
  Runs standalone under node before every pipeline use (asserted).
- `bundle.readable.js` — the pre-minification source of the above (review aid).
- `unpacked/src/{sign,api}.js` — the post-recovery tree shape wakaru/webcrack
  emit (module boundaries restored, names preserved): sign.js carries the
  signature assembly chain digest -> buildParams -> assembleBase ->
  buildSignature; api.js carries the request entry point sendRequest which
  calls buildSignature.
- `specialists/gitnexus-query.md` — trigger-contract fixture for
  route_capability specialist routing (#751 design D2); NOT an agent file.
- `evidence-demo.json` — captured output of a REAL local pipeline run
  (2026-08-27, macOS darwin-x64, node 24): node + gitnexus legs ran;
  wakaru skipped on platform grounds; the semantic assertion held
  (sendRequest among incoming callers of buildSignature).

## Semantic question the demo pins

"trace which function builds the signature string through the bundle" ->
gitnexus answers with the exact chain: request entry `sendRequest` ->
signer `buildSignature` -> callees `buildParams`/`assembleBase`/`digest`.
