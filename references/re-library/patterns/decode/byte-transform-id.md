---
name: byte-transform-id
description: Identify and invert unknown position-local byte transforms via anchor-differential keystream recovery, period detection, and bounded parameter search. When a sample carries a custom encryption/encoding layer that no registered tool decodes.
domain: patterns
family: decode
---
# Byte-Transform Identification — Anchor-Differential Recovery

> When a byte-level transform is position-local (each output byte depends only
> on the input byte, its position, and a repeating key), the parameters are
> recoverable from the ciphertext alone IF any structural anchor is known — a
> magic header, a version field, reserved zeros. No key material needs to be
> guessed. This is the method of choice when the registered decode tools miss:
> the miss itself (position-locality) tells you this method applies.

## Table of Contents
- [Decision: when this method applies](#decision-when-this-method-applies)
- [Technique: anchor-differential keystream recovery](#technique-anchor-differential-keystream-recovery)
- [Runnable reference implementation](#runnable-reference-implementation)
- [Bounded parameter search when the anchor is short](#bounded-parameter-search-when-the-anchor-is-short)
- [Lesson](#lesson)

---

## Decision: when this method applies

| Feature | Signal | Threshold |
|---------|--------|-----------|
| Position-locality | editing one plaintext byte changes exactly one ciphertext byte (test on a controllable encoder if available) | 1:1 dependency |
| Known anchor | format magic / version / reserved-zero fields at fixed offsets | >= 4 bytes at offset 0 |
| Additive component | keystream view values cluster/repeat with a fixed period | repeats within 16 positions |
| Not on shelf | registered decode tools all fail to reproduce structure | all tried |

Position-PERMUTING transforms (reversals, swaps, diffusion) break the 1:1
dependency and need permutation recovery first — do not apply this method
before locality holds.

## Technique: anchor-differential keystream recovery

1. **Invert the additive component first.** For a transform
   `c[i] = f(p[i], k[i mod L]) + i (mod 256)`, compute
   `d[i] = (c[i] - i) & 0xFF` — the position term cancels and what remains is
   a pure periodic-key XOR view.
2. **Recover the keystream view over the anchor.** XOR `d[i]` with the known
   anchor bytes: `s[i] = d[i] ^ anchor[i]`. If the anchor is longer than the
   key period, `s` IS the keystream (repeating).
3. **Detect the period.** The smallest `p` such that `s[i] == s[i % p]` for
   all anchor positions. A 16-byte anchor discriminates periods up to 16.
4. **Decode and verify structurally.** Decode with the recovered periodic key
   and re-check the anchor AND a declared structure field (length, checksum).
   Consistency alone is necessary, not sufficient — the structural verify is
   the decider.

## Runnable reference implementation

```python
def recover_and_decode(data: bytes, anchor: bytes) -> tuple[bytes, bytes] | None:
    n = min(len(anchor), len(data))
    stream = [((data[i] - i) & 0xFF) ^ anchor[i] for i in range(n)]
    for p in range(1, 17):
        if all(stream[i] == stream[i % p] for i in range(n)):
            key = bytes(stream[:p])
            plain = bytes((((data[i] - i) & 0xFF) ^ key[i % p])
                          for i in range(len(data)))
            if plain.startswith(anchor):
                return key, plain
    return None
```

## Bounded parameter search when the anchor is short

When the anchor is shorter than the period (a 4-byte magic cannot
discriminate periods above 4), do NOT guess: search the small structural
space — for each candidate period `p` in 2..16, derive the partial key from
the anchor, decode, and accept only if the structural verify passes. The
verify is the oracle; the search is bounded by construction (<= 15 trials).

## Lesson

A known plaintext fragment is not just a verification convenience — it is a
measurement instrument. Convert every known structural byte into a
keystream observation, and the key reduces from a search problem to an
arithmetic one. The decision rule generalizes: BEFORE brute-forcing any
parameter, ask what the format's mandatory structure already pins down.
