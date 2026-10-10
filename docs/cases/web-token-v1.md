# Case: web-token-v1 — a signing SDK reversed to a one-line HMAC, four fresh sessions minted

> Case study · unit `web-token-v1` · run `e2e-ws-20261005-162428` · lane algorithm · 2026-10-05.
> Identity is stripped (hosts, user paths, harness checkout locations); every technical
> trace below — base64 entries, key material, HMAC vectors, session ids, error codes —
> is quoted verbatim from the run's artifacts. The target is a constructed scenario
> server (`engine.py` on loopback), so its recovered key and pad are publishable.

An agent run unpacked the single obfuscation layer of a served JS SDK, recovered
the HMAC key (assembled from three scrambled string-table parts), the 5-byte
message pad, and the exact signing input — then proved the pad-placement by
falsification, minted tokens for four fresh sessions on the live scenario server,
and watched a captured token die on replay. All five claims `PROVEN`; verdict
scorer `complete: true, correct: true`; both primary questions answered at `C0a`.

## The run in numbers

| | |
|---|---|
| String table decoded | 10/10 base64 entries → key parts, pad, endpoints, field names |
| Signing key | `w7f_xz9Ql2m8sK0eV` (17 ASCII bytes), pad `6d 1f 0b 9a c2` (5 bytes) |
| Deterministic vectors | 3 recorded + 2 pad-placement falsifications, all recomputed byte-exact |
| Acceptance | client.py **4/4 fresh sessions** (4 distinct sids) retrieved `secret_data`; captured token rejected |
| Verification | 5 verifier faces PASS + red-team sign-offs; verdict `complete: true, correct: true` (pq-1 → F005, pq-2 → F007, both `C0a`) |

## Target

Constructed eval unit: a scenario server (fresh instance per verification run)
fronted by `capture/sdk.js` — "shield-lite sdk v1.2", a single-IIFE guarded script
(sha256 `4e93d27ea53f45debdb01a0a5e39e7b0886cc24ff82cedde29c4763e5dabf8c9`).
Challenge flow: `GET /` (session cookie) → `GET /challenge` → mint → `POST /verify`.
Task: reverse the SDK, extract key and pad, build an offline client that mints
valid time-bound tokens for fresh sessions; a captured token must never replay.

## The inquiry

**1. The guard layer is one base64 string table (facts/F002).** `_0xd(i)` =
`atob(_0xa[i])` over 10 entries — the entire obfuscation. The decode is the
one-liner the fact pins as its reproduce command:

```text
['Ql2m', '8sK0eV', 'w7f_xz9', '/verify', '/challenge',
 'sid', 'ts', 'sig', 'secret_data', '6d1f0b9ac2']
```

The trap inside the table: the key is assembled at runtime as
`[_0xd(2), _0xd(0), _0xd(1)].join('')` — part order 2, 0, 1, not table order —
yielding `w7f_xz9Ql2m8sK0eV`. The pad is a hex-pair parse of entry 9:
`6d 1f 0b 9a c2`.

**2. The token algorithm (facts/F003).** Full inline semantics:
`sig = hex(HMAC-SHA256(key, pad ‖ utf8(ts + '|' + sid)))`; the verify body posts
only `{ts, sig}` — `sid` is **not** in the body; the server binds the session
server-side, which is precisely the freshness axis the success criterion
exercises.

**3. Dead end first — pad placement, settled by falsification (facts/F005).**
The recorded deterministic vector `sig(1759675200, a1b2c3d4e5) =
d730f21f525d64a9…` only reproduces with the pad **prepended**. Two placement
variants were run and rejected:

| variant | result |
|---|---|
| pad omitted entirely | `985fac5fd1391eb0…` — differs from the recorded vector |
| pad appended (`msg ‖ pad`) | `323752f94a937873…` — differs from the recorded vector |

Two wrong placements, two different wrong signatures — the pad is a prefix, and
every byte of the algorithm is now determined.

**4. Live confirmation (facts/F006).** The scenario server accepted a
client-minted token, adding two server-side gates the SDK alone does not show:
a browser-UA check (`non_browser_ua` on a curl UA) and a no-session check
(`no_session`); `ts` travels as a JSON integer.

**5. Acceptance (facts/F007).** The deliverable `client.py` (sha256
`7a5ed831…`) ran the full loop — fresh `GET /`, `GET /challenge`, mint,
`POST /verify` — four times:

```text
sids: f463fffb70b6779b, d4c4abc9ba63646b, d2d40352870dd97f, 2135e848bab3357e
SUMMARY: 4/4 fresh sessions retrieved the protected payload   (exit 0)
replay: captured {ts=1791190272, sig=a4523b0d…} on a NEW session
        → {"error":"bad_signature"}, no secret_data
```

Same-session replay was separately rejected with `{"error":"replayed"}`, a
stale-ts token with `{"error":"stale"}` — session-binding and freshness reject
independently.

### What the bytes establish

| Anchor (sdk.js) | Read | Claim it carries |
|---|---|---|
| line 3, `_0xa` (10 entries) | base64 string table | the single obfuscation layer; 10/10 decode |
| line 6 key assembly `[d(2),d(0),d(1)]` | scrambled part order | key = `w7f_xz9Ql2m8sK0eV`, not the table reading order |
| line 8 hex-pair parse of entry 9 | pad `6d 1f 0b 9a c2` | HMAC input prefix — proven by the two falsification arms |
| verify body `{ts, sig}` only | sid absent from the wire | server-side session binding → the freshness guarantee |
| `secret_data` (entry 8) | success marker | the payload each fresh session must retrieve |

## Verification — two methods, named

1. **Static recompute from sample bytes.** The verifier re-extracted the string
   table from `capture/sdk.js` itself (not the client's embedded copy),
   byte-equal 10/10 against `client.py`; re-derived key and pad; recomputed the
   F003 reference vector and the live vector exactly; re-derived all 4 recorded
   acceptance signatures from `(ts, sid)` under the recovered algorithm (4/4).
2. **Live reproduction + adversarial replay.** The pinned server instance was
   dead; the verifier started a fresh `engine.py` on the same port, re-ran
   `client.py --sessions 4` → 4/4 with four **new** distinct sids
   (099e1539ca2597ad, 504409eece82215a, 51aea46666a2fc5d, 7fa62b89528e1e85), exit
   0 — and then replayed the *maker's own captured token* from the pinned
   snapshot across server instances: rejected (`stale`), no secret_data. Face
   list: fingerprint, static-recompute, replay-equivalence, adversarial-replay,
   oracle-gate-probe — all PASS (runs/verification-C-005.md, verdict `verified`;
   red-team sign-offs on the scaffold claims also on file).

Two non-refuting discrepancies stayed on the record: the server answers
`bad_signature` or `stale` for cross-session replay depending on token age
(check order), and one fact cited a scratch helper that was never written — the
inline fallback reproduce worked and was used instead.

## Outcome

C-004 and C-005 `PROVEN` in `claim-register.yaml` (verifier sign-offs
runs/verification-C-004.md and -C-005.md); verdict scorer
(`evidence/verdict.json`, schema v11): `complete: true, correct: true`,
pq-1 → F005 and pq-2 → F007, both `C0a`, no unresolved items, no contradictions.
Both clauses of the success criterion hold verbatim: four fresh sessions
retrieved the payload; a captured token never replays.

Reproduce the acceptance locally:

```bash
python3 engine.py --host 127.0.0.1 --port 18777 &
python3 client.py --base-url http://127.0.0.1:18777 --sessions 4
# → SUMMARY: 4/4 fresh sessions retrieved the protected payload
python3 client.py --base-url http://127.0.0.1:18777 --replay-check
# → REPLAY-CHECK: PASS (captured token rejected)
```
