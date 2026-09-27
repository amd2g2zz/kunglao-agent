"""chain payload (family chain-py, seed 37007, gradient L3) - synthetic
fixture minted by scripts/eval_chain.py; NOT malware."""
FP0 = 2551179907
FP1 = 2679493459
FP2 = 1766977259
SALT = 1182931133
CFG_HEX = 'd7c9cc4aa79b3fdca2fb41a3ce700035845a221420d15c788fb4f94906ef13c13fc9cb737a4d3bcee760076a41ea55e7bb867fbcc29afb1c2d289ff6da996c89227280a29bb1c3fb96970e85331ef813100394cd332557c12cc224dd24b057fef4d6b63729055b7121cc6e2b6531c4aa1ed61f867216a8b8bdd59aea6c56be67d9277195ff5854cbd4ba82647bca89f8b7a1a8284e138902606c6ee916bcccc25fac62a784828a8c24407f44e7f004cd1d773ce313482e'
LEGACY_LICENSE_KEY = '3c6e467b0df92f352d95fc534efd15632a6a24c5df314c17c8e753474856ea67'
import sys
import time
INTEG = 1547048097
CORRUPT = 3064105437
GATE_DT = 423
GD = 6
SEL_KEY = 0x22
LEGACY_P = {'c0': 2896607147, 'c1': 1753679715, 'c2': 3462814333, 'rot': 17, 'odd': 837160715, 'odd2': 682511471}
def _rotl(x, r):
    r &= 31
    return ((x << r) | (x >> (32 - r))) & 0xffffffff if r else x


RC = [[397689647, 1672211091, 2525590317, 3082337815], [4279741547, 145617905, 2568826317, 262928401], [2552660681, 1387352049, 390185761, 725971651], [787152685, 2968338437, 2465233853, 2573635791], [88903527, 576656267, 1281372073, 4066260123], [2971370937, 3415788615, 3717492257, 343104569], [1676757947, 2820607947, 1855608027, 546005805], [2762645755, 3929979105, 3010027973, 2896236247]]


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
# junk wedges stripped - clean analysis form
TRUE_P = _cfg_of(CFG_HEX)['core']


def derive(payload_hex, lane=0):
    data = bytes.fromhex(payload_hex)
    integ_now = INTEG
    t0 = time.perf_counter()
    gd = GD
    while gd > 0:
        gd -= 1  # breakpoint here stalls the gate window
    stalled = (time.perf_counter() - t0) * 1000.0 > GATE_DT
    if stalled or sys.gettrace() is not None:
        integ_now = (INTEG ^ CORRUPT) & 0xffffffff
    sel = (FP0 ^ integ_now) & 0xff
    if sel == SEL_KEY:
        return _core(TRUE_P, data, lane)
    return _core(LEGACY_P, data, lane)
