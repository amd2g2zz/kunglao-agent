# reference.py — arm-native-kdf reference re-implementation (#332).
# Self-contained pure python; byte-exact against the seeded model.
_M32 = 0xFFFFFFFF
_M64 = 0xFFFFFFFFFFFFFFFF
MOD_H = [
    0x6ea4528e,
    0xad15123e,
    0x9328e995,
    0xbfe3756f,
    0x24206088,
    0xdc6f3b91,
    0x92bb1ada,
    0x94d793ce,
]
MOD_K = [
    0x5011aa1f, 0x158a82c8, 0x451cd3ce, 0xe9f1e5ae,
    0xc265eab0, 0x8999b60e, 0xec160e05, 0x07061736,
    0x9d897933, 0x14b5dfec, 0xc2c43847, 0x95ff2d08,
    0x951584d3, 0xeca28bb5, 0xfa3d9b68, 0x3e9a1a03,
    0x513212ee, 0xc9b93eef, 0xd8bfe12d, 0x46aba033,
    0x192c7c26, 0x76903f43, 0x48aae7e3, 0x1fff26a1,
    0xc13fe7d5, 0xbbccc0f6, 0x2e5c3aa1, 0x9f322b4e,
    0xc33fcad0, 0xfadc956c, 0xbf84d5c0, 0xe958b590,
    0x88f8417e, 0x14d2c43f, 0xff8b0499, 0x6812a4e4,
    0xb038358b, 0x367e8fc6, 0xe2d7cc5d, 0x10c10946,
    0xfdfde5d2, 0x65ada194, 0xae0c2d81, 0x1f61ed62,
    0x292b2448, 0xe439f1f9, 0xe2223d58, 0xf72e2da5,
    0x641d127b, 0xdd5e2d51, 0xda812841, 0x429ca654,
    0x6d964fcc, 0x7e846677, 0x17329a30, 0x5c3b0972,
    0xda4a47e1, 0x00f7f934, 0x007e3179, 0x05b5bde1,
    0xd3c5b25f, 0xac615eb2, 0xcb74d33e, 0xe0afefbd,
]


def _rotr(x, n):
    return ((x >> n) | (x << (32 - n))) & _M32


def _sha_blocks(msg):
    bit_len = (len(msg) * 8) & _M64
    padded = msg + b"\x80" + b"\x00" * ((55 - len(msg)) % 64) + \
        bit_len.to_bytes(8, "big")
    return [padded[i * 64:i * 64 + 64] for i in range(len(padded) // 64)]


def mod_sha256(msg):
    h = list(MOD_H)
    for block in _sha_blocks(msg):
        w = [int.from_bytes(block[i * 4:i * 4 + 4], "big") for i in range(16)]
        for i in range(16, 64):
            s0 = _rotr(w[i - 15], 7) ^ _rotr(w[i - 15], 18) ^ (w[i - 15] >> 3)
            s1 = _rotr(w[i - 2], 17) ^ _rotr(w[i - 2], 19) ^ (w[i - 2] >> 10)
            w.append((w[i - 16] + s0 + w[i - 7] + s1) & _M32)
        a, b, c, d, e, f, g, hh = h
        for i in range(64):
            s1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25)
            ch = (e & f) ^ (~e & g)
            t1 = (hh + s1 + ch + MOD_K[i] + w[i]) & _M32
            s0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22)
            maj = (a & b) ^ (a & c) ^ (b & c)
            t2 = (s0 + maj) & _M32
            hh, g, f, e = g, f, e, (d + t1) & _M32
            d, c, b, a = c, b, a, (t1 + t2) & _M32
        h = [(x + y) & _M32 for x, y in zip(h, [a, b, c, d, e, f, g, hh])]
    return b"".join(x.to_bytes(4, "big") for x in h)



def kdf_sha(data, blocks=2):
    out = bytearray()
    for j in range(blocks):
        out += mod_sha256(data + j.to_bytes(4, "little"))
    return bytes(out)


def kdf_derive(data):
    """arm-native-kdf: counter-mode mod-SHA KDF (seed 33201)."""
    return kdf_sha(bytes(data), 2).hex()
