# Case: apk-webview-attest-v2 — two attestation layers bound, four fresh sessions through both

> Case study · unit `apk-webview-attest-v2` · run `e2e-ws-20261005-163158` · lane algorithm · 2026-10-05.
> Identity is stripped (hosts, user paths, harness checkout locations); every technical
> trace below — opcode-level contract, mask bytes, mix constants, PoW nonces, session
> payloads — is quoted verbatim from the run's artifacts. The target is a constructed
> eval unit, so its recovered constants are publishable.

An agent run defeated a two-layer attestation by binding both layers: the WebView
JS challenge (canonicalization, mix-64, proof-of-work) yields a per-session
`attest_seed`, and the native `attest_verify` in an aarch64 `.so` checks
`sha256(seed ‖ nonce)[:8] ^ NATIVE_MASK` against a compare constant **derived
from that seed** — solving either layer alone buys nothing. The run re-derived
the 8-byte mask from raw ELF bytes with its own MOVZ decoder, mined the PoW
against the real SDK, and put 4/4 fresh sessions through both layers; the native
check was proven load-bearing by a negative control. All five claims `PROVEN`;
verdict scorer `complete: true, correct: true`; both primary questions answered
at `C0a`.

## The run in numbers

| | |
|---|---|
| Layers bound | 2 — JS challenge (PoW + mix-64) → `attest_seed` → native `attest_verify` |
| Native mask | `NATIVE_MASK = c4 2b 91 6f 18 d3 7a 05`, re-derived from raw ELF bytes (own MOVZ decoder) |
| PoW | leading zero **bits** semantics; real sdk.js execution mined nonce `12694` |
| Oracle battery | 19/19 checks PASS (`evidence/repro/repro_c004.py`, exit 0) |
| Acceptance | client.py **4/4 fresh sessions** rc=0 through both layers; corrupted native claim → HTTP 403 |
| Outcome | C-004/C-005 `PROVEN`; verdict `complete: true, correct: true` (pq-1 → F007, pq-2 → F005, both `C0a`) |

## Target

Constructed eval unit: a scenario server fronted by `capture/sdk.js`
("shield-max v4.7.2", sha256
`8a5ccbba7981c839c610860dcd3ccfd983bb80cd5e01960bd8a0f349b8a6a34b`, 5147 bytes)
plus `target/libattest.so` — aarch64 ELF64, not stripped, 11720 bytes, single
dynamic export `attest_verify` (0x528–0xde4), sha256
`2cb4f4dadeac91ce397c9ab0a38797474f7e71c2d277d74e853dba3ee07a1e58`. Success
criterion: a client completes 4/4 fresh sessions — JS challenge yielding the
seed, then the native check accepted — retrieving the final payload.

## The inquiry

**1. The JS challenge layer, mechanism by mechanism (facts/F006).** Seven
mechanisms from direct static reading: a base64 string table
(`/challenge`, `/verify`, `shield-integrity-stub-v4.7`); canonicalization
(object keys sorted, `k=v` joined by `|`, over the 6 collected fields `ua,
platform, lang, screen, tz, depth`); a full inline FIPS-180-4 SHA-256; a
2-second integrity watchdog that deletes tampered state (a self-tripwire with no
crypto role); a leading-zero-**bits** counter (`0`→4, `1`→3, `2-3`→2, `4-7`→1
per hex digit); the mix; and the flow.

**2. Dead end first — the mix has two branches, only one is wired (facts/F006).**

```text
ver === 1 (used):  r = ((s16 ^ 0x5F5F5F5F) * 0xC0FFEE11) mod 2^64, then rotl 13
ver !== 1 (dead):  r = (((s16 + 0x1337C0DE) & M) * 0x85EBCA6B) & M, then rotr 7
```

The `ver=1` branch is what the flow posts; the second branch is a complete,
plausible, wrong algorithm with its own constants. The battery's mix-injectivity
check (section B-series) pins the live branch; a solver that picks by
plausibility rather than by the call site lands in the dead lane and every
downstream digest diverges.

**3. The PoW, honestly mined.** Preimage `sid:salt:nonce:s2` with decimal `n`
and decimal `s2` (`s2` = the mix output as a **decimal string**), difficulty
counted in leading zero bits of the hex digest. Against the real SDK the mined
nonce was `12694`; PoW minimality (no smaller n satisfies) is one of the battery
checks.

**4. The native layer, byte-anchored (facts/F007).** `attest_verify`'s contract,
read off the disassembly: `int attest_verify(seed, seed_len, nonce, nonce_len,
expected, expected_len)`; validation prologue demands `expected_len == 8`,
`seed_len == 16` (the seed is consumed as exactly 16 raw bytes), `nonce_len ≥ 1`;
return 0 = accepted. The message is `seed[16] ‖ nonce[min(nonce_len, 48)]` —
the nonce clamped at 48 bytes (`csel w8, w3, #0x30, lt` at 0x574) — hashed with
an inlined standard SHA-256 (K-table matches FIPS), compared byte-wise against
`expected[i] == sha256(msg)[i] ^ mask[i]` for `i < 8`.

**5. The mask, from raw bytes, not strings.** The battery's A-series sections
re-derived the SHA-256 K-table and the 8 mask bytes directly from RAW ELF bytes
using a hand-written MOVZ/MOVK immediate decoder, cross-checked against
`llvm-objdump -d`: `NATIVE_MASK = c4 2b 91 6f 18 d3 7a 05`. The worked vector
pins both values: `native_mask_hex = c42b916f18d37a05`,
`expected_hex = 78109b7ff16e782a` (`evidence/c004-model-vectors.json`).

### What the bytes establish

| Anchor | Read | Claim it carries |
|---|---|---|
| `_0xmix` ver branch | `^0x5F5F5F5F`, `*0xC0FFEE11`, rol13 | the live mix; the `0x1337C0DE`/`0x85EBCA6B` ror7 branch is decoy |
| `_0xzero` digit table | leading zero bits | PoW difficulty is in bits, not hex digits |
| 0x574 `csel w8, w3, #0x30, lt` | nonce clamp min(len, 48) | exact native message length `16 + min(nonce_len, 48)` |
| 0xdc0 `cset w0, ne` | 0 = accepted | the accept/reject polarity of `attest_verify` |
| ELF immediates (MOVZ/MOVK) | mask `c4 2b 91 6f 18 d3 7a 05` | the compare constant, re-derived without string references |
| `/verify` response `attest_seed` | layer binding | the seed the native check consumes — the two layers are one protocol |

## Verification — two methods, named

1. **Oracle battery (independent model re-derivation).**
   `python3 evidence/repro/repro_c004.py` exits 0 with **19/19 checks**: K-table
   FIPS identity, 7 mask bytes re-derived from raw ELF, the eor-immediate at
   0xd70, canonicalization, mix ver-1 injectivity, zero-bit identity, PoW hit +
   minimality, the native accept/reject matrix, and the nonce clamp in both
   directions (runs/verification-C-005.md, Face 3). C-004's verifier evidence
   additionally records a 17/17 vector replay and real-SDK execution mining
   nonce `12694`.
2. **Live reproduction + negative control.** The verifier started a fresh engine
   instance (port 60149) and ran `client.py` as 4 separate processes — **4/4
   rc=0**, each retrieving a distinct 32-hex `secret_data` (046cfe94e33f48f0…,
   01f5f5f474f243c9…, 9d030a5ce5e942bd…, c87ccc77240845ff…). Then the negative
   control (Face 2): a scratch probe solved the JS layer honestly and posted a
   deliberately corrupted native claim (`digest[:8] ^ 0xFF`) to a second fresh
   instance (port 60220) — HTTP 403. The 4/4 acceptances are not vacuous; the
   engine really validates `sha256(seed ‖ nonce)[:8] ^ NATIVE_MASK`. Face 4
   closes the loop byte-exactly: `client.py:17 NATIVE_MASK =
   bytes.fromhex("c42b916f18d37a05")` equals the disassembly immediates
   (`evidence/e2e-c005-attest-verify.asm`).

## Outcome

C-004 (characterization) and C-005 (re-implementation) `PROVEN` in
`claim-register.yaml`, with the verifier sign-offs citing the mask re-derivation,
oracle battery, vector replay, live 4/4, and the 403 negative control; verdict
scorer (`evidence/verdict.json`, schema v11): `complete: true, correct: true`,
pq-1 → `F007-native-attest-verify`, pq-2 → F005, both `C0a`, nothing unresolved.
Both attestation layers are bound in one working client, and the negative control
shows the binding is checked, not assumed.

Reproduce the acceptance locally:

```bash
python3 server/engine.py --host 127.0.0.1 --port 60149 &
python3 client.py --base http://127.0.0.1:60149
# → rc=0, prints the retrieved secret_data
```
