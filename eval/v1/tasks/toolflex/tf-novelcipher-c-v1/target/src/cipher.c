/* cipher.c — NXC-64, a private SPN digest construction (blocked-path unit
 * #546, tf-novelcipher-c-v1). Deliberately outside the stock families: no
 * Merkle-Damgard constants, no GF(2^8) MDS matrix, no RC4 state machine,
 * no single-byte XOR — a 6-round nibble-S-box permutation network with
 * position-dependent rotate-mix and private per-round multipliers.
 *
 * Build: cc -O2 -std=c11 -o cipher cipher.c && strip cipher
 * Usage: cipher <file>       (prints "NXC-DIGEST <16 hex>")
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>

#define ROUNDS 6

/* private constants (seed 54602; exist nowhere else) */
static const uint64_t IV = 0x9C4F2E7BA1D36058ULL;
static const uint64_t RC[ROUNDS] = {
    0x3E2A9C41B7D065F8ULL, 0x1F7C48A2E963D0B5ULL,
    0xC5197BE02A64F3D8ULL, 0x7A0ED3258FC194B6ULL,
    0xB38260FD17A94EC5ULL, 0x46D9B1F70C3E82A1ULL};
static const uint64_t ODD[ROUNDS] = {
    0xB509FC73A2E16D48ULL, 0x2E7C91A4D3F85B60ULL,
    0x71D3E4089C2A6FB5ULL, 0xC9825AF130D7B4E6ULL,
    0x5B608ED3C2179FA4ULL, 0xE4A137C9580BD26FULL};
/* private nibble S-box (not the AES one, not canonical in any family) */
static const uint8_t SBOX[16] = {
    0x9, 0xE, 0x3, 0xB, 0x0, 0xD, 0x4, 0xC,
    0x1, 0x8, 0xF, 0x2, 0xA, 0x6, 0x5, 0x7};

static uint8_t rotl8(uint8_t x, unsigned n) {
    n &= 7u;
    return (uint8_t)((x << n) | (x >> (8u - n)));
}

/* one 64-bit block through the permutation network */
static uint64_t E(uint64_t x) {
    for (int r = 0; r < ROUNDS; r++) {
        x ^= RC[r];
        /* nibble S-box pass */
        for (int k = 0; k < 16; k++) {
            const int sh = k * 4;
            const uint64_t nib = (x >> sh) & 0xFULL;
            x ^= (uint64_t)(nib ^ SBOX[nib]) << sh;
        }
        /* position-dependent mixing: byte i is mixed with byte (i+3)%8
         * rotated by (r+i)&7 — the mixing operator itself depends on
         * both the byte position and the round, so no fixed linear
         * algebra (and no known family) reproduces it */
        for (int i = 0; i < 8; i++) {
            const uint8_t tap = rotl8((uint8_t)(x >> (8 * ((i + 3) % 8))),
                                      (unsigned)((r + i) & 7));
            x ^= (uint64_t)(tap ^ (uint8_t)(r * 0x1F)) << (8 * i);
        }
        x *= ODD[r];
    }
    return x;
}

/* digest: plain absorb h = E(h ^ block), big-endian blocks, length folded */
static uint64_t digest(const uint8_t *buf, size_t len) {
    uint64_t h = IV;
    size_t i = 0;
    for (; i + 8 <= len; i += 8) {
        uint64_t blk = 0;
        for (int k = 0; k < 8; k++)
            blk = (blk << 8) | buf[i + k];
        h = E(h ^ blk);
    }
    uint64_t tail = (uint64_t)len & 0xFFFFFFFFFFFFFFFFULL;
    for (size_t k = 0; i + k < len; k++)
        tail ^= (uint64_t)buf[i + k] << (8 * k);
    return E(h ^ tail);
}

int main(int argc, char **argv) {
    if (argc != 2) {
        fprintf(stderr, "usage: cipher <file>\n");
        return 2;
    }
    FILE *f = fopen(argv[1], "rb");
    if (!f) {
        fprintf(stderr, "nxc64: cannot read %s\n", argv[1]);
        return 3;
    }
    static uint8_t buf[1 << 16];
    size_t len = fread(buf, 1, sizeof buf, f);
    if (ferror(f)) {
        fprintf(stderr, "nxc64: read error\n");
        fclose(f);
        return 3;
    }
    fclose(f);
    printf("NXC-DIGEST %016llx\n", (unsigned long long)digest(buf, len));
    return 0;
}
