"""chain payload (family chain-py, seed 37002, gradient L1) - synthetic
fixture minted by scripts/eval_chain.py; NOT malware."""
FP0 = 1113880495
FP1 = 4005347313
FP2 = 966746025
SALT = 676320567
CFG_HEX = '6ed8c53faa8b871bacdb0da2db52efcbbd12b10fcbfcc93565b8ad7232a722f7f388c121a7d3806b3195a955204b4811afa976859a83268db6a9d02db801c1b406f6d24ebe8e2b366f6ad778c61c77b81db890423d67f22b6d8ea7eaba5842571376015e97c6b31bf83b53c2aa549edd06cc7da1778f225e7d8013ee1c908d98674a7c19ee61a6415887953de5a68e01e451bac5b4208ebf1493e535'
LEGACY_HEX = '6ed8c53faa8b871bacdb0da2db52efcbbd12b205c8f6cc3a62bdac7632a722f7f388c522afd7866d3d98aa482e0a1901b7a17285998f2f8db3a4d534b64ccab440eedb4cbf8e2e336c67d978df123ab31dee805a356efc2e6582a5e2b6565959436b1a088fcdbf1bf83b53c2aa549edd06cc7da1208c235d28d914bf1b92d19d304c204ae86df9450ed3c439e1f78750b106bb96b4208ebf1493e435'
LEGACY_LICENSE_KEY = 'c12b3197a7d69bdf3b7ed77d79c8fb01aa26a35bda5bca5b27d070bfb45443ef'
LEGACY_KEY = '40504a0d61d4cbdfc490f057620fba4b'
def _rotl(x, r):
    r &= 31
    return ((x << r) | (x >> (32 - r))) & 0xffffffff if r else x


RC = [[667499699, 3158513957, 1772448213, 1991375505], [2434542593, 3363081847, 2386374583, 1631273645], [1373419611, 3730497045, 3246799293, 2682780231], [1928801117, 3530226717, 2467061051, 1579302119], [1597777943, 1245382597, 3498782407, 1179279049], [102801343, 2205018635, 847714317, 4190386471], [622030599, 2323827049, 649484811, 1110309333], [3099390773, 3865337157, 1710077797, 3322915375]]


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
_opq_j1bab = ((FP1 ^ 0x2c9cdff1) >> 3) ^ 0x9cdff1
if (_opq_j1bab & 1) * ((_opq_j1bab - 1) & 1) == 1:
    FP0 = (FP0 + 1) & 0xffffffff
_w_j1bab_a = (FP2 ^ 0xa51318e5) & 0xffffffff
_w_j1bab_b = ((_w_j1bab_a * 3) ^ (_w_j1bab_a << 1)) & 0xffffffff
if (_w_j1bab_b & 1) * ((_w_j1bab_b + 1) & 1) == 1:
    SALT ^= 0xe5
LEGACY_SEL = 0xc2
TRUE_CFG = _cfg_of(CFG_HEX)


def derive(payload_hex, lane=0):
    data = bytes.fromhex(payload_hex)
    legacy_sel = (FP2 ^ SALT) & 0xff
    if legacy_sel == LEGACY_SEL:
        return _mac(LEGACY_KEY, data)
    return _mac(TRUE_CFG["mac_key"], data)
