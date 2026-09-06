---
name: wire-format-recognition
description: Triage opaque captured bodies into three recoverability classes — standard encryption the app itself decrypts, private serialization protocol, standard serialization with unknown schema — before choosing any decoder, then recover structure (protobuf-class wire parsing without a schema, length-prefix framing conventions) and match the TLS ClientHello fingerprint surface (JA3-class) when byte-correct replays are still rejected. Use when a captured request or response body is unreadable bytes, when a framed message stream must be framed before parsing, or when an offline-reproduced request fails with no application-layer error.
---

# Wire-Format Recognition (opaque bodies + TLS fingerprint surface)

Two recognition gaps sit upstream of every decoding decision:

- **A — opaque-body triage.** Unreadable capture bytes: classify before
  tooling — each class implies a different attack and difficulty.
- **B — TLS fingerprint surface.** Byte-correct replay still rejected
  with no application-layer error: the client-hello shape itself may be
  part of what the server checks.

## When to Use

- A captured body is opaque (binary, or base64 of it); no decoder picked yet.
- A length-prefixed message stream must be framed before parsing.
- A replay is rejected though every parameter matches — look below the app.

## Part A — opaque-body triage: three classes

Collect several samples before classifying (one capture cannot
distinguish framing from coincidence — the same multi-sample discipline
as the native-sign ladder). Then classify from observables only:

| Class | Observable traits | Difficulty | First move |
|---|---|---|---|
| 1. Standard encryption, decrypted in-app (AES-class) | High entropy AND lengths ≡ 0 mod 16 (or mod 8) | Low — the app decrypts it, so algorithm + key are in-process | Hook the decrypt boundary, harvest plaintext |
| 2. Private serialization protocol | Non-standard structure; no recognizable field headers; no alignment | Highest — protocol semantics must be recovered from handler code | Locate the receiving parse routine before touching bytes |
| 3. Standard serialization, unknown schema (protobuf-class) | Varint runs; field-header structure; readable string fragments | Medium — structure is recoverable without the schema | No-schema parse (below) |

Misclassification is the expensive error: varint-parsing class-1 output
produces confident nonsense; hand-rolling class-3 parsing burns days.

Class 1 heuristic: **if the app can decrypt it, key + algorithm are on
the device** — the attack is boundary observation, not cryptanalysis.

## Protobuf-class parsing without a schema

### Wire types

The tag is a varint: `tag = (field_number << 3) | wire_type`. The low
three bits select the payload shape:

| Wire type | Payload |
|---|---|
| 0 | varint — 7 bits per byte, high bit = continuation |
| 1 | 64-bit fixed (fixed64 / double) |
| 2 | length-delimited — length varint, then that many bytes (string / bytes / embedded message / packed repeated) |
| 5 | 32-bit fixed (fixed32 / float) |

(3/4 are deprecated group markers — treat as a parse error first.)

### Parse loop

1. Read the tag varint; split field number and wire type; read the value.
2. Wire type 2: try the payload as an embedded message — if it consumes
   exactly as a legal tag/value sequence, recurse; if it is mostly
   printable, record a string; otherwise record opaque bytes.
3. Continue until the buffer is consumed exactly. Overrun or trailing
   garbage means a wrong split upstream — back up and retry, never
   hand-patch forward.

### Heuristics

- Consecutive printable runs ≈ strings; printable + base64-decodable → decode once more.
- Plausible-magnitude 32/64-bit values get dual interpretation (uint and
  float) until one reading is absurd.
- Small sign-alternating values indicate zigzag (sint): `(n >> 1) ^ -(n & 1)`.
- Raw field number + wire type suffices for replay; schema rebuild is an
  optional follow-up, never the gate.

### Few-shot — no-schema parse skeleton (synthetic bytes)

```python
def read_varint(buf, i):
    shift = val = 0
    while True:
        if i >= len(buf): raise IndexError
        b = buf[i]; i += 1
        val |= (b & 0x7F) << shift
        if not b & 0x80: return val, i
        shift += 7

def parse(buf):                    # field list, or None = not a clean message
    fields, i = [], 0
    try:
        while i < len(buf):
            tag, i = read_varint(buf, i)
            fn, wt = tag >> 3, tag & 7
            if fn == 0 or wt in (3, 4, 6, 7):
                return None        # invalid field number / group or reserved
            if wt == 0:
                v, i = read_varint(buf, i)
            elif wt == 1:
                if len(buf) - i < 8: return None
                v, i = buf[i:i+8], i + 8
            elif wt == 5:
                if len(buf) - i < 4: return None
                v, i = buf[i:i+4], i + 4
            else:                  # wt == 2, length-delimited
                n, i = read_varint(buf, i)
                if len(buf) - i < n: return None
                v, i = buf[i:i+n], i + n
                inner = parse(v)   # recursion: a clean nested parse wins
                if inner is not None: v = inner
            fields.append((fn, wt, v))
    except IndexError:
        return None                # overrun -> wrong split upstream, back up
    return fields

wire = bytes.fromhex("0a070a0568656c6c6f100a")   # synthetic capture
# parse(wire) -> [(1, 2, [(1, 2, b'hello')]), (2, 0, 10)]
#   field 1: embedded message holding the string "hello"
#   field 2: varint 10 — as float32 it reads 1.4e-44, absurd, so integer
# These two triples are already replayable evidence: regenerate the body
# by re-encoding (field number, wire type, value) — no schema needed.
```

## Length-prefix framing (message envelope)

Stream framing adds three conventions to pin before parsing: **unit**
(byte count vs element count), **endianness**, **width** (varint vs
2/4/8-byte fixed). Decide by multi-sample comparison — messages of
known content; the interpretation matching across *all* samples wins.
Record the convention with the capture sample it came from: a framing
guessed from one message breaks on the next.

## Part B — TLS fingerprint surface (JA3-class)

- **What it hashes.** The ClientHello — TLS version, cipher suites,
  extensions, extension values, elliptic curves, point formats —
  concatenated and digested. The result is a *shape fingerprint of the
  client TLS stack*, not of the user.
- **Why stacks differ.** Cipher order, extension order, GREASE values,
  and curve preference are stack traits; OpenSSL, BoringSSL, NSS, and
  platform TLS libraries each emit a distinguishable hello. Two
  different stacks do not collide on the hash.
- **Why the reverse engineer cares.** A server may score or reject the
  hello itself. A byte-perfect protocol replay from a script's default
  stack then fails with no application-layer error — the mismatch is
  below the application, in the hello.
- **Countermeasure category: client-hello shaping / stack
  substitution.** Extract the target's hello shape from the capture
  first; then reproduce it from a stack that exposes cipher order,
  extension set, and curves as configuration. Verify offline by
  comparing the assembled string against the captured one — before
  spending a single live request on the server.

### Few-shot — assemble the fingerprint string from a capture (synthetic)

```python
# Skeleton: pull ClientHello fields from a pcap, assemble the JA3-style
# string. Each commented segment names the fingerprint component it feeds.
# TLS record parsing is omitted — any pcap/TLS library supplies it.

hello = extract_client_hello("capture-sample.pcap", stream=0)   # synthetic

ja3_values = [
    hello.tls_version,        # e.g. b"\x03\x03" -> "771"     (version)
    hello.cipher_suites,      # ORDERED — list order is a stack trait
    hello.extensions,         # ORDERED — extension set + order
    hello.supported_groups,   # elliptic-curve preference
    hello.ec_point_formats,   # formats list
]
# Strip GREASE filler values before joining — but note separately whether
# the stack emits GREASE at all: that too is a distinguishing trait.
ja3_str = ",".join(fmt(v) for v in ja3_values)
digest = md5(ja3_str.encode()).hexdigest()   # e.g. "384af4f1..." synthetic

# Use: shape the reproduction stack until its assembled string equals the
# captured digest. Equal string = equal shape; that is the check.
```

## Closure summary

| Gate | Minimum evidence |
|---|---|
| Class assigned | Multi-sample observables (entropy, alignment, field-header structure) recorded with the samples |
| Structure recovered | Parse consumes the buffer exactly across all samples; no hand-patched offsets |
| Framing pinned | Convention (unit / endianness / width) consistent over every captured message |
| Replay supported | Raw field numbers + wire types (or plaintext pairs) sufficient to regenerate the payload |
| Fingerprint matched | Assembled hello string equals the captured one before any live attempt |

kunglao bookkeeping: the class label and framing convention are
numeric-style facts — carry the observables, the capture samples, and
the parse command in the fact file, not just the label.

## Cross-references

- Multi-sample capture + hypothesis-with-falsifier discipline behind
  class 1: [native-sign-recovery.md](native-sign-recovery.md#closure-summary)
- Output-shape signature table (web face of the same idea):
  [web-re-quickref.md](web-re-quickref.md#crypto-algorithm-signatures)
- Protocol-layer challenge family (the defense side of fingerprinting):
  [web-risk-control.md](web-risk-control.md)
