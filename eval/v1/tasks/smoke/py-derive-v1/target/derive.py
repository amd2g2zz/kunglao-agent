# derive.py — #299 CONSTRUCTED eval target (family py-derive, eval-v1).
# NOT malware; no real workspace data: a pure-algo 64-bit derivation seeded
# by eval_targets.py. Recover the three parameters and re-implement
# derive(data: bytes) -> int so it reproduces the reference outputs.
OFFSET = 0xfc7a9bfd754a9d87
PRIME = 0x1134735108fe8719
FOLD = 0x00ff8cf3f3e2a8a3

_M64 = (1 << 64) - 1


def derive(data: bytes) -> int:
    h = OFFSET
    for b in data:
        h = ((h ^ b) * PRIME) & _M64
    h ^= h >> 31
    h = (h * FOLD) & _M64
    h ^= h >> 29
    return h


if __name__ == "__main__":
    for probe in (b"alpha", b"bravo"):
        print(probe.hex(), derive(probe))
