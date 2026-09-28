# reference.py — rust-so-crack-v1 reference re-implementation.
# Self-contained pure python; byte-exact against the committed
# target/libcrackme.so / target/crackme_host core.
#
# P1  mutated ChaCha20 KDF (sigma word0 = SIGMA_MUT, one extra column
#     quarter-round after the 20 standard rounds)
# P2  AES-shaped SPN, CTR mode: affine S-box variant from SBOX_SEED
#     (sbox'[i] = gf_mul(SBOX_AES[i], a) ^ b) + rcon ladder shifted by
#     rcon_shift; the decoy legacy lane runs the STOCK constants
# P3  verify: magic (16B) + folded-checksum double match

_M32 = 0xFFFFFFFF

# ------------------------------------------------------------- parameters
SIGMA_MUT = 0x5BD1B3C1          # P1: the mutated sigma word
SIGMA_STD0 = 0x61707865         # stock "expa" (decoy lane only)
SBOX_SEED = 0x2F6E8D1B          # P2: the sbox seed
MAGIC = bytes.fromhex("8ca637c14ed29b6021fa8d3c770eb954")   # P3
DECOY_MAGIC = bytes.fromhex("1337c0dedeadbeefcafebabef00dbaad")
NONCE_BASE = bytes([0x9e, 0x37, 0x79, 0xb9, 0xb7, 0xf1, 0x5a, 0x0d])
CTR_NONCE = bytes.fromhex("00112233445566778899aabb")

SBOX_A = SBOX_SEED & 0xFF
SBOX_B = (SBOX_SEED >> 8) & 0xFF
RCON_SHIFT = (SBOX_SEED >> 16) & 7

SBOX_AES = [
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
    0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0, 0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0,
    0xb7, 0xfd, 0x93, 0x26, 0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2, 0xeb, 0x27, 0xb2, 0x75,
    0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0, 0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84,
    0x53, 0xd1, 0x00, 0xed, 0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f, 0x50, 0x3c, 0x9f, 0xa8,
    0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5, 0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2,
    0xcd, 0x0c, 0x13, 0xec, 0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14, 0xde, 0x5e, 0x0b, 0xdb,
    0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c, 0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79,
    0xe7, 0xc8, 0x37, 0x6d, 0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f, 0x4b, 0xbd, 0x8b, 0x8a,
    0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e, 0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e,
    0xe1, 0xf8, 0x98, 0x11, 0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f, 0xb0, 0x54, 0xbb, 0x16,
]


def _rotr32(x, n):
    return ((x >> n) | (x << (32 - n))) & _M32


def _rotl32(x, n):
    return ((x << n) | (x >> (32 - n))) & _M32


def _quarter(s, a, b, c, d):
    s[a] = (s[a] + s[b]) & _M32
    s[d] = _rotl32(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & _M32
    s[b] = _rotl32(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b]) & _M32
    s[d] = _rotl32(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & _M32
    s[b] = _rotl32(s[b] ^ s[c], 7)


def _chacha_block(sigma0, key32, counter, nonce12, extra_half):
    key_words = [int.from_bytes(key32[4 * j:4 * j + 4], "little") for j in range(8)]
    nw = [int.from_bytes(nonce12[4 * j:4 * j + 4], "little") for j in range(3)]
    sigma = [sigma0, 0x3320646E, 0x79622D32, 0x6B206574]
    init = sigma + key_words + [counter] + nw
    w = list(init)
    for _ in range(10):
        _quarter(w, 0, 4, 8, 12)
        _quarter(w, 1, 5, 9, 13)
        _quarter(w, 2, 6, 10, 14)
        _quarter(w, 3, 7, 11, 15)
        _quarter(w, 0, 5, 10, 15)
        _quarter(w, 1, 6, 11, 12)
        _quarter(w, 2, 7, 8, 13)
        _quarter(w, 3, 4, 9, 14)
    if extra_half:
        _quarter(w, 0, 4, 8, 12)   # the extra half-round
    out = b"".join(((init[j] + w[j]) & _M32).to_bytes(4, "little")
                   for j in range(16))
    return out


def seed_material(data):
    return data[16:] if len(data) > 16 else data


def derive_session(sigma0, extra_half, material):
    n = len(material)
    key = bytes(material[j % n] for j in range(32))
    nonce = NONCE_BASE + bytes([
        n & 0xFF, (n >> 8) & 0xFF,
        material[0] ^ material[n - 1], 0x5C,
    ])
    return _chacha_block(sigma0, key, 1, nonce, extra_half)[:32]


def gf_mul(a, b):
    p = 0
    for _ in range(8):
        if b & 1:
            p ^= a
        hi = a & 0x80
        a = (a << 1) & 0xFF
        if hi:
            a ^= 0x1B
        b >>= 1
    return p


def xtime(x):
    hi = x & 0x80
    y = (x << 1) & 0xFF
    return y ^ 0x1B if hi else y


def build_sbox(a, b):
    return bytes(gf_mul(SBOX_AES[i], a) ^ b for i in range(256))


def _rcon_at(index):
    r = 1
    for _ in range(max(0, index - 1)):
        r = xtime(r)
    return r


def _key_expansion(key16, sbox, shift):
    w = bytearray(176)
    w[0:16] = key16
    for r in range(1, 11):
        prev, cur = (r - 1) * 16, r * 16
        rc = _rcon_at(r + shift)
        t = [sbox[w[prev + 13]], sbox[w[prev + 14]],
             sbox[w[prev + 15]], sbox[w[prev + 12]]]
        t[0] ^= rc
        for j in range(4):
            w[cur + j] = w[prev + j] ^ t[j]
        for j in range(4, 16):
            w[cur + j] = w[prev + j] ^ w[cur + j - 4]
    return [bytes(w[r * 16:(r + 1) * 16]) for r in range(11)]


def _sub_shift(state, sbox):
    s = bytearray(state)
    for r in range(4):
        for c in range(4):
            s[r + 4 * c] = sbox[state[r + 4 * ((c + r) % 4)]]
    return s


def _mix_columns(state):
    s = bytearray(state)
    for c in range(4):
        i = 4 * c
        a0, a1, a2, a3 = state[i], state[i + 1], state[i + 2], state[i + 3]
        s[i] = gf_mul(a0, 2) ^ gf_mul(a1, 3) ^ a2 ^ a3
        s[i + 1] = a0 ^ gf_mul(a1, 2) ^ gf_mul(a2, 3) ^ a3
        s[i + 2] = a0 ^ a1 ^ gf_mul(a2, 2) ^ gf_mul(a3, 3)
        s[i + 3] = gf_mul(a0, 3) ^ a1 ^ a2 ^ gf_mul(a3, 2)
    return s


def _spn_encrypt(block, rks, sbox):
    state = bytearray(block)
    for j in range(16):
        state[j] ^= rks[0][j]
    for r in range(1, 10):
        state = _sub_shift(state, sbox)
        state = _mix_columns(state)
        for j in range(16):
            state[j] ^= rks[r][j]
    state = _sub_shift(state, sbox)
    for j in range(16):
        state[j] ^= rks[10][j]
    return bytes(state)


def _ctr_block(idx, session_key, sbox, shift):
    spn_key = session_key[:16]
    rks = _key_expansion(spn_key, sbox, shift)
    cb = CTR_NONCE + idx.to_bytes(4, "little")
    return _spn_encrypt(cb, rks, sbox)


def real_material(material):
    sk = derive_session(SIGMA_MUT, True, material)
    sbox = build_sbox(SBOX_A, SBOX_B)
    return (_ctr_block(0, sk, sbox, RCON_SHIFT),
            _ctr_block(1, sk, sbox, RCON_SHIFT))


def decoy_material(material):
    sk = derive_session(SIGMA_STD0, False, material)
    sbox = build_sbox(1, 0)
    return _ctr_block(0, sk, sbox, 0)


def _fnv1a(data):
    h = 0x811C9DC5
    for b in data:
        h = ((h ^ b) * 0x01000193) & _M32
    return h


def _checksum16(data):
    h = _fnv1a(data)
    return (h ^ (h >> 16)) & 0xFFFF


def probe(data):
    """crackme_probe: first 8 bytes of the P2 keystream block 0 (hex)."""
    ks0, _ = real_material(seed_material(data))
    return ks0[:8].hex()


def verify(data):
    """crackme_verify: 0 valid, 1 invalid, 2 bad arguments."""
    if not data:
        return 2
    if len(data) >= 16 and data[0] == 0x44 and data[1] == 0x45:
        ks0 = decoy_material(seed_material(data))
        d = bytes(a ^ b for a, b in zip(data[:16], ks0))
        return 0 if d == DECOY_MAGIC else 1
    if len(data) < 16:
        return 1
    material = seed_material(data)
    ks0, ks1 = real_material(material)
    d = bytes(a ^ b for a, b in zip(data[:16], ks0))
    if d != MAGIC:
        return 1
    if _checksum16(material) != int.from_bytes(ks1[:2], "little"):
        return 1
    return 0
