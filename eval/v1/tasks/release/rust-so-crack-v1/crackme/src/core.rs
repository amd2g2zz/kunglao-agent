//! crackme core — the three-layer crypto target (rust-so-crack-v1).
//!
//! P1  mutated ChaCha20 KDF: one custom sigma word + one extra half-round
//!     (column quarter-round) after the 20 standard rounds; derives the
//!     32-byte session key from the license seed material.
//! P2  AES-shaped SPN in CTR mode: affine-transform S-box variant
//!     (sbox'[i] = gf_mul(SBOX_AES[i], a) ^ b, a/b from the sbox seed)
//!     + rcon shifted by a seed-derived rotation.
//! P3  verify: P1 -> P2 -> 16-byte magic match + folded-checksum double
//!     match. The three recoverable parameters are SIGMA_MUT / SBOX_SEED /
//!     MAGIC; the stock-constant lane behind the 0x44 0x45 prefix is the
//!     decoy (fake success) arm and never uses the mutated constants.

#![allow(dead_code)]

// ---------------------------------------------------------------- params

/// P1 parameter: the mutated sigma word (replaces "expa" 0x61707865).
pub const SIGMA_MUT: u32 = 0x5b_d1_b3_c1;
/// The stock sigma (used ONLY by the decoy legacy lane).
pub const SIGMA_STD: [u32; 4] = [0x6170_7865, 0x3320_646e, 0x7962_2d32, 0x6b20_6574];

/// P2 parameter: the sbox seed.
///   sbox_a = seed & 0xff            (affine multiplier, nonzero)
///   sbox_b = (seed >> 8) & 0xff     (affine xor)
///   rcon_shift = (seed >> 16) & 7   (rcon rotation)
pub const SBOX_SEED: u32 = 0x2f_6e_8d_1b;

/// P3 parameter: the license magic.
pub const MAGIC: [u8; 16] = [
    0x8c, 0xa6, 0x37, 0xc1, 0x4e, 0xd2, 0x9b, 0x60,
    0x21, 0xfa, 0x8d, 0x3c, 0x77, 0x0e, 0xb9, 0x54,
];

/// The decoy magic: the fake-success bait on the legacy lane.
pub const DECOY_MAGIC: [u8; 16] = [
    0x13, 0x37, 0xc0, 0xde, 0xde, 0xad, 0xbe, 0xef,
    0xca, 0xfe, 0xba, 0xbe, 0xf0, 0x0d, 0xba, 0xad,
];

/// Fixed 8-byte nonce base for P1 (input-derived bytes are appended).
const NONCE_BASE: [u8; 8] = [0x9e, 0x37, 0x79, 0xb9, 0xb7, 0xf1, 0x5a, 0x0d];

/// Fixed 12-byte prefix of the P2 CTR counter block.
pub const CTR_NONCE: [u8; 12] = [
    0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88, 0x99, 0xaa, 0xbb,
];

/// Anti-analysis poison tweak: a deterministic corruption that makes the
/// output look like a wrong key, never like a detection.
pub const POISON_TWEAK_BASE: u8 = 0x5c;

pub fn sbox_a(seed: u32) -> u8 {
    (seed & 0xff) as u8
}
pub fn sbox_b(seed: u32) -> u8 {
    ((seed >> 8) & 0xff) as u8
}
pub fn rcon_shift(seed: u32) -> u32 {
    (seed >> 16) & 7
}

// ---------------------------------------------------------------- P1

fn quarter(s: &mut [u32; 16], a: usize, b: usize, c: usize, d: usize) {
    s[a] = s[a].wrapping_add(s[b]);
    s[d] ^= s[a];
    s[d] = s[d].rotate_left(16);
    s[c] = s[c].wrapping_add(s[d]);
    s[b] ^= s[c];
    s[b] = s[b].rotate_left(12);
    s[a] = s[a].wrapping_add(s[b]);
    s[d] ^= s[a];
    s[d] = s[d].rotate_left(8);
    s[c] = s[c].wrapping_add(s[d]);
    s[b] ^= s[c];
    s[b] = s[b].rotate_left(7);
}

/// One mutated ChaCha20 block: the sigma word(s) are caller-supplied; when
/// `extra_half` is set one additional column quarter-round runs after the
/// 20 standard rounds (the "extra half-round mixing").
fn chacha_block(
    sigma: [u32; 4],
    key: &[u8; 32],
    counter: u32,
    nonce: &[u8; 12],
    extra_half: bool,
) -> [u8; 64] {
    let mut key_words = [0u32; 8];
    for j in 0..8 {
        key_words[j] = u32::from_le_bytes([
            key[4 * j],
            key[4 * j + 1],
            key[4 * j + 2],
            key[4 * j + 3],
        ]);
    }
    let nonce_words = [
        u32::from_le_bytes([nonce[0], nonce[1], nonce[2], nonce[3]]),
        u32::from_le_bytes([nonce[4], nonce[5], nonce[6], nonce[7]]),
        u32::from_le_bytes([nonce[8], nonce[9], nonce[10], nonce[11]]),
    ];
    let init: [u32; 16] = [
        sigma[0], sigma[1], sigma[2], sigma[3],
        key_words[0], key_words[1], key_words[2], key_words[3],
        key_words[4], key_words[5], key_words[6], key_words[7],
        counter, nonce_words[0], nonce_words[1], nonce_words[2],
    ];
    let mut w = init;
    for _ in 0..10 {
        quarter(&mut w, 0, 4, 8, 12);
        quarter(&mut w, 1, 5, 9, 13);
        quarter(&mut w, 2, 6, 10, 14);
        quarter(&mut w, 3, 7, 11, 15);
        quarter(&mut w, 0, 5, 10, 15);
        quarter(&mut w, 1, 6, 11, 12);
        quarter(&mut w, 2, 7, 8, 13);
        quarter(&mut w, 3, 4, 9, 14);
    }
    if extra_half {
        // the mutation: one extra column half-round after the 20 rounds
        quarter(&mut w, 0, 4, 8, 12);
    }
    let mut out = [0u8; 64];
    for j in 0..16 {
        let v = init[j].wrapping_add(w[j]);
        out[4 * j..4 * j + 4].copy_from_slice(&v.to_le_bytes());
    }
    out
}

/// Seed material: everything after the 16-byte license header; the whole
/// input when the license is header-only.
pub fn seed_material(input: &[u8]) -> &[u8] {
    if input.len() > 16 {
        &input[16..]
    } else {
        input
    }
}

/// P1: derive the 32-byte session key from the seed material.
pub fn derive_session(sigma0: u32, extra_half: bool, material: &[u8]) -> [u8; 32] {
    let sigma = [sigma0, 0x3320_646e, 0x7962_2d32, 0x6b20_6574];
    let n = material.len();
    let mut key = [0u8; 32];
    for j in 0..32 {
        // cyclic fill: deterministic for every n >= 1
        key[j] = material[j % n];
    }
    let mut nonce = [0u8; 12];
    nonce[0..8].copy_from_slice(&NONCE_BASE);
    nonce[8] = (n & 0xff) as u8;
    nonce[9] = ((n >> 8) & 0xff) as u8;
    nonce[10] = material[0] ^ material[n - 1];
    nonce[11] = 0x5c;
    let block = chacha_block(sigma, &key, 1, &nonce, extra_half);
    let mut sk = [0u8; 32];
    sk.copy_from_slice(&block[0..32]);
    sk
}

// ---------------------------------------------------------------- P2

const SBOX_AES: [u8; 256] = [
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
];

pub fn gf_mul(mut a: u8, mut b: u8) -> u8 {
    let mut p = 0u8;
    for _ in 0..8 {
        if b & 1 != 0 {
            p ^= a;
        }
        let hi = a & 0x80;
        a <<= 1;
        if hi != 0 {
            a ^= 0x1b;
        }
        b >>= 1;
    }
    p
}

/// Build the affine-transform S-box variant and its inverse.
/// shift == 0 and (a, b) == (1, 0) reduces to the stock AES S-box.
pub fn build_sbox(a: u8, b: u8) -> ([u8; 256], [u8; 256]) {
    let mut sbox = [0u8; 256];
    let mut inv = [0u8; 256];
    for i in 0..256 {
        let v = gf_mul(SBOX_AES[i], a) ^ b;
        sbox[i] = v;
        inv[v as usize] = i as u8;
    }
    (sbox, inv)
}

fn xtime(x: u8) -> u8 {
    let hi = x & 0x80;
    let mut y = x << 1;
    if hi != 0 {
        y ^= 0x1b;
    }
    y
}

fn rcon_at(index: u32) -> u8 {
    // index = round + shift; the stock ladder starts at index 1 and doubles
    let mut r = 1u8;
    for _ in 0..index.saturating_sub(1) {
        r = xtime(r);
    }
    r
}

pub struct Spn {
    pub sbox: [u8; 256],
    pub inv_sbox: [u8; 256],
    pub round_keys: [[u8; 16]; 11],
}

impl Spn {
    /// AES-128-shaped key schedule with the variant sbox + shifted rcon.
    pub fn new(key: &[u8; 16], a: u8, b: u8, shift: u32) -> Spn {
        let (sbox, inv_sbox) = build_sbox(a, b);
        let mut w = [0u8; 176];
        w[0..16].copy_from_slice(key);
        for r in 1..=10u32 {
            let prev = (r as usize - 1) * 16;
            let cur = r as usize * 16;
            // t = SubWord(RotWord(prev last word)) ^ rcon(shifted):
            // RotWord([b0,b1,b2,b3]) = [b1,b2,b3,b0]; rcon hits word[0]
            let rc = rcon_at(r + shift);
            let mut t = [
                sbox[w[prev + 13] as usize],
                sbox[w[prev + 14] as usize],
                sbox[w[prev + 15] as usize],
                sbox[w[prev + 12] as usize],
            ];
            t[0] ^= rc;
            for j in 0..4 {
                w[cur + j] = w[prev + j] ^ t[j];
            }
            for j in 4..16 {
                // W[r][j] = W[r-1][j] ^ W[r][j-1]  (word-wise ladder; in
                // byte terms: prev-round byte ^ previous word's byte)
                w[cur + j] = w[prev + j] ^ w[cur + j - 4];
            }
        }
        let mut round_keys = [[0u8; 16]; 11];
        for r in 0..11 {
            round_keys[r].copy_from_slice(&w[r * 16..r * 16 + 16]);
        }
        Spn { sbox, inv_sbox, round_keys }
    }

    fn sub_shift(state: &mut [u8; 16], sbox: &[u8; 256]) {
        let mut s = *state;
        for r in 0..4 {
            for c in 0..4 {
                // AES state is column-major: flat index = row + 4*col;
                // ShiftRows rotates row r left by r positions
                let src = r + 4 * ((c + r) % 4);
                s[r + 4 * c] = sbox[state[src] as usize];
            }
        }
        *state = s;
    }

    fn mix_columns(state: &mut [u8; 16]) {
        // the AES MDS matrix rows: [2 3 1 1] / [1 2 3 1] / [1 1 2 3] / [3 1 1 2]
        for c in 0..4 {
            let i = 4 * c;
            let a0 = state[i];
            let a1 = state[i + 1];
            let a2 = state[i + 2];
            let a3 = state[i + 3];
            state[i] = gf_mul(a0, 2) ^ gf_mul(a1, 3) ^ a2 ^ a3;
            state[i + 1] = a0 ^ gf_mul(a1, 2) ^ gf_mul(a2, 3) ^ a3;
            state[i + 2] = a0 ^ a1 ^ gf_mul(a2, 2) ^ gf_mul(a3, 3);
            state[i + 3] = gf_mul(a0, 3) ^ a1 ^ a2 ^ gf_mul(a3, 2);
        }
    }

    fn add_round_key(state: &mut [u8; 16], rk: &[u8; 16]) {
        for j in 0..16 {
            state[j] ^= rk[j];
        }
    }

    pub fn encrypt(&self, block: &[u8; 16]) -> [u8; 16] {
        let mut state = *block;
        Spn::add_round_key(&mut state, &self.round_keys[0]);
        for r in 1..10 {
            Spn::sub_shift(&mut state, &self.sbox);
            Spn::mix_columns(&mut state);
            Spn::add_round_key(&mut state, &self.round_keys[r]);
        }
        Spn::sub_shift(&mut state, &self.sbox);
        Spn::add_round_key(&mut state, &self.round_keys[10]);
        state
    }

    /// P2 CTR keystream block `idx` under the session key.
    pub fn ctr_block(&self, idx: u32) -> [u8; 16] {
        let mut cb = [0u8; 16];
        cb[0..12].copy_from_slice(&CTR_NONCE);
        cb[12..16].copy_from_slice(&idx.to_le_bytes());
        self.encrypt(&cb)
    }
}

// ---------------------------------------------------------------- P3

fn fnv1a(data: &[u8]) -> u32 {
    let mut h: u32 = 0x811c_9dc5;
    for &b in data {
        h ^= b as u32;
        h = h.wrapping_mul(0x0100_0193);
    }
    h
}

fn checksum16(data: &[u8]) -> u16 {
    let h = fnv1a(data);
    ((h ^ (h >> 16)) & 0xffff) as u16
}

/// The REAL core material: P1 (mutated) -> P2 keystream blocks 0 and 1.
pub fn real_material(material: &[u8]) -> ([u8; 16], [u8; 16]) {
    let sk = derive_session(SIGMA_MUT, true, material);
    let mut key16 = [0u8; 16];
    key16.copy_from_slice(&sk[0..16]);
    let spn = Spn::new(&key16, sbox_a(SBOX_SEED), sbox_b(SBOX_SEED),
                       rcon_shift(SBOX_SEED));
    (spn.ctr_block(0), spn.ctr_block(1))
}

/// The DECOY core material: stock sigma, no extra half-round, stock AES.
pub fn decoy_material(material: &[u8]) -> [u8; 16] {
    let sk = derive_session(SIGMA_STD[0], false, material);
    let mut key16 = [0u8; 16];
    key16.copy_from_slice(&sk[0..16]);
    let spn = Spn::new(&key16, 1, 0, 0);
    spn.ctr_block(0)
}

/// Deterministic anti-analysis poison: corrupt a keystream block so the
/// observable output looks like a wrong key, never like a detection.
pub fn poison_tweak(ks: &mut [u8]) {
    for (i, b) in ks.iter_mut().enumerate() {
        *b ^= POISON_TWEAK_BASE ^ ((i as u8).rotate_left(3));
    }
}

/// crackme_probe oracle: first 8 bytes of the P2 keystream block 0
/// (REAL core), as a little-endian u64.
pub fn core_probe(input: &[u8]) -> u64 {
    core_probe_with(input, clean_tweak)
}

/// core_probe with the poison hook (the android wrapper consults the
/// poison flag here, after the verify-time faces have run).
pub fn core_probe_with(input: &[u8], tweak: fn(&mut [u8])) -> u64 {
    let (mut ks0, _) = real_material(seed_material(input));
    tweak(&mut ks0);
    let mut head = [0u8; 8];
    head.copy_from_slice(&ks0[0..8]);
    u64::from_le_bytes(head)
}

/// verify: return 0 on success, 1 on failure, 2 on invalid arguments.
/// `tweak` is the poison hook (identity on a clean run).
pub fn core_verify(input: &[u8], tweak: fn(&mut [u8])) -> i32 {
    if input.is_empty() {
        return 2;
    }
    // legacy lane: keys starting 0x44 0x45 ("DE") walk the stock-constant
    // decoy arm — a fake-success path gated on the WRONG constants.
    if input.len() >= 16 && input[0] == 0x44 && input[1] == 0x45 {
        let mut ks0 = decoy_material(seed_material(input));
        tweak(&mut ks0);
        let mut d = [0u8; 16];
        for j in 0..16 {
            d[j] = input[j] ^ ks0[j];
        }
        return if d == DECOY_MAGIC { 0 } else { 1 };
    }
    if input.len() < 16 {
        return 1;
    }
    let (mut ks0, mut ks1) = real_material(seed_material(input));
    tweak(&mut ks0);
    tweak(&mut ks1);
    let mut d = [0u8; 16];
    for j in 0..16 {
        d[j] = input[j] ^ ks0[j];
    }
    if d != MAGIC {
        return 1;
    }
    // double match: the folded checksum of the seed material must equal
    // the low 16 bits of keystream block 1
    let expected = u16::from_le_bytes([ks1[0], ks1[1]]);
    if checksum16(seed_material(input)) != expected {
        return 1;
    }
    0
}

/// The no-op tweak of a clean run (the poison hook identity).
pub fn clean_tweak(_ks: &mut [u8]) {}

// ---------------------------------------------------------------- mint

/// Search a valid REAL license: header 16 bytes, tail `tail_len` bytes;
/// returns the license whose verify() == 0 (checksum search ~2^16).
/// Host-only mint tooling (allocates; the android cdylib never mints).
#[cfg(not(all(target_os = "android", target_arch = "aarch64")))]
pub fn mint_valid_license(tail_len: usize, attempts: u32) -> Option<Vec<u8>> {
    let mut tail = vec![0x5au8; tail_len];
    for attempt in 0..attempts {
        let ctr = attempt.to_le_bytes();
        let clen = ctr.len().min(tail_len);
        tail[tail_len - clen..].copy_from_slice(&ctr[..clen]);
        let (ks0, ks1) = real_material(&tail);
        let expected = u16::from_le_bytes([ks1[0], ks1[1]]);
        if checksum16(&tail) == expected {
            let mut lic = Vec::with_capacity(16 + tail_len);
            for j in 0..16 {
                lic.push(MAGIC[j] ^ ks0[j]);
            }
            lic.extend_from_slice(&tail);
            return Some(lic);
        }
    }
    None
}

/// Search a decoy-lane input that hits DECOY_MAGIC under the stock core
/// (head must still start 0x44 0x45). Host-only mint tooling.
#[cfg(not(all(target_os = "android", target_arch = "aarch64")))]
pub fn mint_decoy_input(tail_len: usize, attempts: u32) -> Option<Vec<u8>> {
    let want = [DECOY_MAGIC[0] ^ 0x44, DECOY_MAGIC[1] ^ 0x45];
    let mut tail = vec![0x3cu8; tail_len];
    for attempt in 0..attempts {
        let ctr = attempt.to_le_bytes();
        let clen = ctr.len().min(tail_len);
        tail[tail_len - clen..].copy_from_slice(&ctr[..clen]);
        let ks0 = decoy_material(&tail);
        if ks0[0] == want[0] && ks0[1] == want[1] {
            let mut inp = Vec::with_capacity(16 + tail_len);
            for j in 0..16 {
                inp.push(DECOY_MAGIC[j] ^ ks0[j]);
            }
            inp.extend_from_slice(&tail);
            return Some(inp);
        }
    }
    None
}
