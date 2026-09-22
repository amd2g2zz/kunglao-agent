# reference.py — win-pe-kdf reference re-implementation (#332).
# Self-contained pure python; byte-exact against the seeded model.
_M32 = 0xFFFFFFFF
_M64 = 0xFFFFFFFFFFFFFFFF
MOD_H = [
    0x09414046,
    0x30eddd4a,
    0x40f91cad,
    0xc48e119b,
    0xe5b9c1e4,
    0x7f3ff7f5,
    0xb29ad7ee,
    0x7b176cb4,
]
MOD_K = [
    0x2a356495, 0x6a998688, 0x4e08f8d4, 0x59eed09c,
    0x5c580acc, 0xc697b65e, 0x9c78de4b, 0xc851dd90,
    0xfe500c45, 0x545f5448, 0x410e1531, 0xaa2e3798,
    0x53919975, 0x87d9512f, 0x591e365a, 0x35832033,
    0x610122b4, 0xc139fc09, 0x8a1e96b9, 0x14c49ea3,
    0xabb09fbe, 0x7aba0b3b, 0x26d7360f, 0xa84cd3d7,
    0x9a8de81f, 0x72ca7bc6, 0xb2fc57d7, 0x03ff5818,
    0xeaf90122, 0x6933b4dc, 0xdbdbdf90, 0xd756de36,
    0x14465e0c, 0xcbf8da87, 0x443d6121, 0x56d98428,
    0xefd5901d, 0xf303ec62, 0x886c7589, 0xb1487eae,
    0x1cd94b74, 0x4ceda3b8, 0xa732a2b5, 0xf3c6cf78,
    0x32550318, 0x699e24a5, 0x7c9f1d56, 0x63051fe1,
    0xf2435259, 0xc555acbb, 0x78134ffd, 0x8f5f6cbe,
    0x99cd568c, 0x7bb1528d, 0x12f8e376, 0x30c97096,
    0xd162130f, 0xa1539bea, 0xa483ddc1, 0xf6396a1b,
    0x07c8cc15, 0xd774bf76, 0x3f7f5db8, 0xd9c0b185,
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
    """win-pe-kdf: counter-mode mod-SHA KDF (seed 33202)."""
    return kdf_sha(bytes(data), 2).hex()
