"""chain payload (family chain-py, seed 37004, gradient L2) - synthetic
fixture minted by scripts/eval_chain.py; NOT malware."""
FP0 = 3536362705
FP1 = 2332121565
FP2 = 2960654945
SALT = 11214513
CFG_HEX = 'f06d560d0b361da38f7ca857842740e1bbaf10bb3f5ff9f62f0cf007792f2429020a307edb0bf2abe964b395e78aefb40737be449f12a82b91e1dff148fcb7a170688e3c21432a9e5dc5fb086b3024ed46d4e7b0e10ebccfd4c0c694482868fa72e3d2140613ef709f3f8ff2b9c3a3fdfa0edf21b938eefc'
LEGACY_HEX = 'f06d560d0b361da38f7ca857842740e1bbaf17b83b5bf9f9290cf009792f2429020a307ad10af7a8e26fb388e9cbbea41f39bc469217ab2b98eadbea46b1bca136708635244f299a58cbf40d7e3e69e64682f7a8e909b1cfdcc7c095492e75f422fec9421e1fa06fc07fcceafe8ab1ba'
LEGACY_LICENSE_KEY = 'ca89aec15519f47ba2ed6d071b35b0bd499bbf954ed4d5dbae716abf31727e81'
def _rotl(x, r):
    r &= 31
    return ((x << r) | (x >> (32 - r))) & 0xffffffff if r else x


RC = [[2085670291, 471838791, 871166709, 4185649203], [2792251525, 3683373283, 1540137895, 1277224127], [3572602541, 4164728989, 2356565091, 1394412971], [1780636289, 2476840929, 1487606587, 2547550429], [2130631555, 70510547, 1539546805, 93630615], [2095166307, 1223657879, 587579971, 2832058737], [3402974551, 3759575815, 1980226425, 2223572171], [1177261111, 1716357135, 658994805, 2203866495]]


def _arx(w, rc):
    a, b, c, d = w
    a = (a + d) & 0xffffffff; b ^= _rotl(a, (rc[0] & 15) + 1)
    c = (c + b) & 0xffffffff; d ^= _rotl(c, (rc[1] & 15) + 1)
    a = (a + b) & 0xffffffff; c ^= _rotl(a, (rc[2] & 15) + 1)
    d = (d + c) & 0xffffffff; b ^= _rotl(d, (rc[3] & 15) + 1)
    return [a, b, c, d]


def _kdf_words():
    w = [(FP0 ^ RC[0][0]) | 1, (FP1 ^ RC[0][1]) & 0xffffffff,
         (FP2 ^ RC[0][2]) & 0xffffffff, (SALT ^ RC[0][3]) & 0xffffffff]
    for r in range(8):
        w = _arx(w, RC[r % 8])
        w[r % 4] ^= ((r + 1) * 0x2545F491) & 0xffffffff
    return w


def _blk(key_w, ctr):
    w = [key_w[0], key_w[1], key_w[2], (key_w[3] ^ ctr) & 0xffffffff]
    for r in range(6):
        w = _arx(w, RC[(r + 2) % 8])
    return w


def _decrypt_hex(hexstr):
    key_w = _kdf_words()
    raw = bytes.fromhex(hexstr)
    out = bytearray()
    for ctr, off in enumerate(range(0, len(raw), 16)):
        ks = _blk(key_w, ctr)
        for j, byte in enumerate(raw[off:off + 16]):
            out.append(byte ^ ((ks[j // 4] >> ((3 - j % 4) * 8)) & 255))
    return bytes(out)


def _cfg_of(hexstr):
    import json
    return json.loads(_decrypt_hex(hexstr)[4:].decode("utf-8"))


def _core(p, data, lane=0):
    c0, c1 = p["c0"], p["c1"]
    if lane:
        c0 ^= _rotl((p["odd"] * lane) & 0xffffffff, 3)
        c1 = (c1 + p["odd2"] * lane) & 0xffffffff
    a, b, acc = c0, c1, p["c2"]
    for byte in data:
        a = (a + byte) & 0xffffffff
        a = _rotl(a ^ b, p["rot"])
        b = (b + a) & 0xffffffff
        acc ^= _rotl((a + acc) & 0xffffffff, 3)
    h1 = (acc * p["odd"]) & 0xffffffff
    h2 = (_rotl((h1 ^ b) & 0xffffffff, 7) * p["odd"]) & 0xffffffff
    return "%08x%08x" % (h1, h2)


def _mac(key_hex, data):
    w = [int(key_hex[i:i + 8], 16) for i in range(0, 32, 8)]
    padded = bytearray(data)
    padded.append(0x80)
    while len(padded) % 4:
        padded.append(0)
    k = 0
    for off in range(0, len(padded), 4):
        w[0] ^= int.from_bytes(padded[off:off + 4], "big")
        w = _arx(w, RC[k % 8])
        k += 1
    w = _arx(w, RC[0])
    w = _arx(w, RC[1])
    return "%08x%08x" % (w[0] ^ w[2], w[1] ^ w[3])
# junk wedges (opaque predicates + no-op forest): the naive
# decompile of this payload misleads until stripped
_opq_j1bad = ((FP1 ^ 0x2ba4a2ad) >> 3) ^ 0xa4a2ad
if (_opq_j1bad & 1) * ((_opq_j1bad - 1) & 1) == 1:
    FP0 = (FP0 + 1) & 0xffffffff
_w_j1bad_a = (FP2 ^ 0x70411b2d) & 0xffffffff
_w_j1bad_b = ((_w_j1bad_a * 3) ^ (_w_j1bad_a << 1)) & 0xffffffff
if (_w_j1bad_b & 1) * ((_w_j1bad_b + 1) & 1) == 1:
    SALT ^= 0x2d
LEGACY_SEL = 0x8c
TRUE_CFG = _cfg_of(CFG_HEX)
LEGACY_CFG = _cfg_of(LEGACY_HEX)


def derive(payload_hex, lane=0):
    data = bytes.fromhex(payload_hex)
    legacy_sel = (FP2 ^ SALT) & 0xff
    if legacy_sel == LEGACY_SEL:
        return _core(LEGACY_CFG["core"], data, 0)
    return _core(TRUE_CFG["core"], data, lane)
