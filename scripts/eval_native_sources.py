#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_native_sources.py — #332 native target SOURCE renderers + flattener.

Deterministic string work: given a seed-derived config, render the C / Go
sources the builders compile. NOT malware, nothing runs at import time,
every constant synthetic (minted from the family seed).

Renderers (one per family face):
  render_arm_c        bionic-targeted .so: exported kdf_derive over the
                      mod-SHA core; addition-B anti-debug (TracerPid parse,
                      PTRACE_TRACEME self-attach, clock_gettime timing
                      delta) with a seed-masked detection needle; response
                      = silent corruption (output XOR seed mask).
  render_go_win       GOOS=windows PE main: the same KDF shape in Go;
                      anti-debug = IsDebuggerPresent +
                      CheckRemoteDebuggerPresent +
                      NtQueryInformationProcess(ProcessDebugPort) via
                      LazyDLL/LazyProc + a time.Since timing gate; same
                      silent-corruption response.
  render_payload_c    freestanding mod-crypto payload (payload_entry) whose
                      .text the builder XOR-patches into an SMC image.
  render_smc_stub     -nostdlib _start: raw-syscall anti-debug (TracerPid
                      parse, ptrace(101) TRACEME, rdtsc delta), in-place
                      payload decrypt gated on the checks (wrong key under
                      a tracer -> canary miss -> silent corruption).
  render_mod_c        the standalone mod-crypto core .so (exported
                      mod_derive) the other faces consume by construction.
  render_reference_py self-contained pure-python reimplementation of a
                      unit's model (the perfect-candidate self-check).

The flattener: OLLVM-STYLE control-flow flattening as a SOURCE-LEVEL
python transform (honest label — not OLLVM itself). Canonical contract:
a marked region
    /* flatten-begin <name> */
    for (<var> = 0; <var> < LIMIT; <var>++...) {
        /*@s1*/ <single-line statement>;
        /*@s2*/ <single-line statement>;
    }
    /* flatten-end */
is rewritten into a switch dispatcher with the stage statements emitted
verbatim (semantics preserved: condition, stage order, increment).
Optimizer resistance (so the dispatcher cannot fold back under -O2/gc):
C uses a ``volatile int`` state; Go routes state through PACKAGE-LEVEL
``//go:noinline`` accessors (opaque across the loop body's calls); the C
stage helpers are ``__attribute__((noinline))`` so the flattening's
presence stays measurable as L2 .text > L1 .text on every flattened
family.

stdlib only.
"""
from __future__ import annotations

import re


def _u32s(values: list[int], per_line: int = 4) -> str:
    rows = [", ".join(f"0x{v:08x}" for v in values[i:i + per_line])
            for i in range(0, len(values), per_line)]
    return "\n    " + ",\n    ".join(rows)


# ---------------------------------------------------------------- C core ----
def c_mod_sha_core(cfg: dict) -> str:
    """The mod-SHA translation-unit text (mutated H/K), shared by the C
    faces; tables rendered as literals (raw-bytes static-face ground
    truth)."""
    return (
        "static const unsigned int MOD_H[8] = {" + _u32s(cfg["h"]) + "};\n"
        "static const unsigned int MOD_K[64] = {" + _u32s(cfg["k"]) + "};\n"
        "\n"
        "static unsigned int rotr32(unsigned int x, int n) {\n"
        "    return (x >> n) | (x << (32 - n));\n"
        "}\n"
        "\n"
        "static void mod_sha256(const unsigned char *msg, unsigned int len,\n"
        "                       unsigned char out[32]) {\n"
        "    unsigned int h[8];\n"
        "    unsigned int w[64];\n"
        "    unsigned char buf[128];\n"
        "    unsigned int i, j, padded, bits = len * 8u;\n"
        "    for (i = 0; i < 8; i++) h[i] = MOD_H[i];\n"
        "    for (i = 0; i < len && i < 119u; i++) buf[i] = msg[i];\n"
        "    buf[len] = 0x80u;\n"
        "    padded = (len + 9u <= 64u) ? 64u : 128u;\n"
        "    for (j = len + 1; j < padded - 8u; j++) buf[j] = 0u;\n"
        "    for (i = 0; i < 8; i++)\n"
        "        buf[padded - 8u + i] =\n"
        "            (unsigned char)(bits >> (56 - 8 * i));\n"
        "    for (j = 0; j < padded; j += 64u) {\n"
        "        for (i = 0; i < 16; i++)\n"
        "            w[i] = ((unsigned int)buf[j + 4 * i] << 24) |\n"
        "                   ((unsigned int)buf[j + 4 * i + 1] << 16) |\n"
        "                   ((unsigned int)buf[j + 4 * i + 2] << 8) |\n"
        "                   (unsigned int)buf[j + 4 * i + 3];\n"
        "        for (i = 16; i < 64; i++) {\n"
        "            unsigned int s0 = rotr32(w[i-15], 7) ^ rotr32(w[i-15], 18)\n"
        "                ^ (w[i-15] >> 3);\n"
        "            unsigned int s1 = rotr32(w[i-2], 17) ^ rotr32(w[i-2], 19)\n"
        "                ^ (w[i-2] >> 10);\n"
        "            w[i] = w[i-16] + s0 + w[i-7] + s1;\n"
        "        }\n"
        "        {\n"
        "        unsigned int a = h[0], b = h[1], c = h[2], d = h[3];\n"
        "        unsigned int e = h[4], f = h[5], g = h[6], hh = h[7];\n"
        "        for (i = 0; i < 64; i++) {\n"
        "            unsigned int s1 = rotr32(e, 6) ^ rotr32(e, 11)\n"
        "                ^ rotr32(e, 25);\n"
        "            unsigned int ch = (e & f) ^ (~e & g);\n"
        "            unsigned int t1 = hh + s1 + ch + MOD_K[i] + w[i];\n"
        "            unsigned int s0 = rotr32(a, 2) ^ rotr32(a, 13)\n"
        "                ^ rotr32(a, 22);\n"
        "            unsigned int mj = (a & b) ^ (a & c) ^ (b & c);\n"
        "            unsigned int t2 = s0 + mj;\n"
        "            hh = g; g = f; f = e; e = d + t1;\n"
        "            d = c; c = b; b = a; a = t1 + t2;\n"
        "        }\n"
        "        h[0] += a; h[1] += b; h[2] += c; h[3] += d;\n"
        "        h[4] += e; h[5] += f; h[6] += g; h[7] += hh;\n"
        "        }\n"
        "    }\n"
        "    for (i = 0; i < 4; i++)\n"
        "        for (j = 0; j < 8; j++)\n"
        "            out[4 * j + i] =\n"
        "                (unsigned char)(h[j] >> (24 - 8 * i));\n"
        "}\n")


def c_anti_debug(cfg: dict) -> str:
    """Addition-B face for the bionic/glibc C targets (the freestanding
    stub renders its own raw-syscall version)."""
    needle = bytes(b ^ cfg["needle_key"] for b in b"TracerPid:")
    return (
        f"static const unsigned char TRACER_N[10] = {{\n    "
        + ", ".join(f"0x{b:02x}" for b in needle)
        + "\n};\n"
        f"#define NEEDLE_KEY 0x{cfg['needle_key']:02x}u\n"
        f"#define TIMING_ITERS {cfg['timing_iters']}u\n"
        f"#define TIMING_THRESHOLD_NS {cfg['timing_ns']}ull\n"
        f"#define CORRUPT_MASK 0x{cfg['corrupt_mask']:016x}ull\n"
        "\n"
        "static unsigned long long corrupt_state(void) {\n"
        "    unsigned char needle[10];\n"
        "    unsigned char buf[1024];\n"
        "    int fd, n, i, j, hit = 0;\n"
        "    for (i = 0; i < 10; i++)\n"
        "        needle[i] = (unsigned char)(TRACER_N[i] ^ NEEDLE_KEY);\n"
        "    fd = open(\"/proc/self/status\", O_RDONLY);\n"
        "    if (fd >= 0) {\n"
        "        n = (int)read(fd, buf, sizeof(buf) - 1u);\n"
        "        close(fd);\n"
        "        if (n > 0) {\n"
        "            buf[n] = 0;\n"
        "            for (i = 0; i + 10 < n; i++) {\n"
        "                for (j = 0; j < 10; j++)\n"
        "                    if (buf[i + j] != needle[j]) break;\n"
        "                if (j == 10) {\n"
        "                    int tp = 0, k = i + 10;\n"
        "                    while (buf[k] == ' ') k++;\n"
        "                    while (buf[k] >= '0' && buf[k] <= '9')\n"
        "                        tp = tp * 10 + (buf[k++] - '0');\n"
        "                    if (tp != 0) hit = 1;\n"
        "                    break;\n"
        "                }\n"
        "            }\n"
        "        }\n"
        "    }\n"
        "    if (ptrace(PTRACE_TRACEME, 0, 0, 0) == -1) hit = 1;\n"
        "    {\n"
        "        struct timespec t0, t1;\n"
        "        volatile unsigned int s = 0u;\n"
        "        unsigned long long d;\n"
        "        clock_gettime(CLOCK_MONOTONIC, &t0);\n"
        "        for (i = 0; i < (int)TIMING_ITERS; i++)\n"
        "            s += (unsigned int)i;\n"
        "        clock_gettime(CLOCK_MONOTONIC, &t1);\n"
        "        d = (unsigned long long)(t1.tv_sec - t0.tv_sec) * 1000000000ull\n"
        "            + (unsigned long long)(t1.tv_nsec - t0.tv_nsec);\n"
        "        if (d > TIMING_THRESHOLD_NS) hit = 1;\n"
        "    }\n"
        "    return hit ? CORRUPT_MASK : 0ull;\n"
        "}\n")


def _c_mask_apply(count: int) -> str:
    return (
        "    if (mask) {\n"
        "        unsigned int q;\n"
        f"        for (q = 0; q < {count}u; q++)\n"
        "            out[q] ^= (unsigned char)(mask >> (8 * (q & 7u)));\n"
        "    }\n")


# --------------------------------------------------------------- arm face ----
def render_arm_c(cfg: dict) -> str:
    return (
        "// kdf_arm.c — #332 CONSTRUCTED eval target "
        "(family arm-native-kdf).\n"
        "// NOT malware; no real data: every constant is seeded\n"
        "// (eval_native_targets.py). Recover the mod-SHA constants and\n"
        "// re-implement kdf_derive:\n"
        "//   out = cat(mod_sha256(in || u32le(0)), mod_sha256(in || u32le(1)))\n"
        "//   (the hashed message is exactly n + 4 bytes: data then the\n"
        "//    little-endian counter; the eval wire pins n = 32)\n"
        "// Under a debugger the sample CORRUPTS SILENTLY (output XOR\n"
        "// CORRUPT_MASK) — real-world anti-debug behavior; the eval oracles\n"
        "// run in a clean environment where the checks never fire.\n"
        "#include <fcntl.h>\n"
        "#include <time.h>\n"
        "#include <unistd.h>\n"
        "#include <sys/ptrace.h>\n"
        "/* glibc/bionic declare PTRACE_TRACEME; macOS hosts "
        "(self-check builds) only define PT_TRACE_ME - same "
        "request code 0. */\n"
        "#ifndef PTRACE_TRACEME\n"
        "#define PTRACE_TRACEME 0\n"
        "#endif\n"
        "\n"
        + c_mod_sha_core(cfg)
        + "\n" + c_anti_debug(cfg)
        + """
/* The hashed message must be BYTE-IDENTICAL to the seed model's:
 * n data bytes followed by the 4-byte little-endian block counter
 * (the eval wire pins n = 32 -> a 36-byte message). Every byte of cat
 * that mod_sha256 sees is initialized here; nothing is hashed garbage. */
__attribute__((noinline))
static void stage_pack(unsigned char *cat, const unsigned char *in,
                       unsigned int n, unsigned int blk) {
    unsigned int j;
    for (j = 0; j < n && j < 60u; j++) cat[j] = in[j];
    cat[n] = (unsigned char)blk;
    cat[n + 1u] = (unsigned char)(blk >> 8);
    cat[n + 2u] = (unsigned char)(blk >> 16);
    cat[n + 3u] = (unsigned char)(blk >> 24);
}

__attribute__((noinline))
static void stage_hash(const unsigned char *cat, unsigned int n,
                       unsigned char *dig) {
    mod_sha256(cat, n + 4u, dig);
}

__attribute__((noinline))
static void stage_emit(const unsigned char *dig, unsigned char *out,
                       unsigned int blk) {
    unsigned int j;
    for (j = 0; j < 32u; j++) out[blk * 32u + j] = dig[j];
}

__attribute__((visibility("default")))
void kdf_derive(const unsigned char *in, unsigned int n,
                unsigned char *out, unsigned int out_len) {
    unsigned int blk;
    unsigned char cat[64];
    unsigned char dig[32];
    unsigned long long mask = corrupt_state();
    (void)out_len;  /* out is always 64B on the eval wire */
    /* flatten-begin rounds */
    for (blk = 0; blk < 2u; blk++) {
        /*@s1*/ stage_pack(cat, in, n, blk);
        /*@s2*/ stage_hash(cat, n, dig);
        /*@s3*/ stage_emit(dig, out, blk);
    }
    /* flatten-end */
"""
        + _c_mask_apply(64)
        + "}\n")


# ---------------------------------------------------------------- go face ----
def render_go_win(cfg: dict) -> str:
    h_list = "\n\t\t".join(f"0x{v:08x}," for v in cfg["h"])
    k_rows = [", ".join(f"0x{v:08x}" for v in cfg["k"][i:i + 4])
              for i in range(0, 64, 4)]
    k_list = "\n\t\t".join(row + "," for row in k_rows)
    return f"""// sample_kdf.go — #332 CONSTRUCTED eval target (family win-pe-kdf).
// NOT malware; no real data: every constant is seeded. Built with
// GOOS=windows GOARCH=amd64 CGO_ENABLED=0 (a real Windows PE).
// Recover the mod-SHA constants and re-implement kdf_derive (counter
// mode, two blocks). Under a debugger the sample CORRUPTS SILENTLY.
package main

import (
	"os"
	"syscall"
	"time"
	"unsafe"
)

// flattenStateRounds is the L2 flattener's dispatcher state anchor. The
// accessors are //go:noinline and the variable is package-level, so the
// gc must treat the state as opaque across the loop body's calls and
// cannot fold the switch back into straight-line code.
var flattenStateRounds int

//go:noinline
func flattenGetRounds() int {{ return flattenStateRounds }}

//go:noinline
func flattenSetRounds(v int) {{ flattenStateRounds = v }}

var modH = [...]uint32{{
	{h_list}
}}

var modK = [...]uint32{{
	{k_list}
}}

const (
	corruptMask = 0x{cfg['corrupt_mask']:016x}
	timingIters = {cfg['timing_iters']}
	timingNs    = {cfg['timing_ns']}
)

func rotr(x, n uint32) uint32 {{ return x>>n | x<<(32-n) }}

func modSha256(msg []byte) [32]byte {{
	var h [8]uint32
	copy(h[:], modH[:])
	buf := make([]byte, 64)
	bits := uint64(len(msg)) * 8
	copy(buf, msg)
	buf[len(msg)] = 0x80
	for i := len(msg) + 1; i < 56; i++ {{
		buf[i] = 0
	}}
	for i := 0; i < 8; i++ {{
		buf[56+i] = byte(bits >> (56 - 8*i))
	}}
	var w [64]uint32
	for i := 0; i < 16; i++ {{
		w[i] = uint32(buf[4*i])<<24 | uint32(buf[4*i+1])<<16 |
			uint32(buf[4*i+2])<<8 | uint32(buf[4*i+3])
	}}
	for i := 16; i < 64; i++ {{
		s0 := rotr(w[i-15], 7) ^ rotr(w[i-15], 18) ^ w[i-15]>>3
		s1 := rotr(w[i-2], 17) ^ rotr(w[i-2], 19) ^ w[i-2]>>10
		w[i] = w[i-16] + s0 + w[i-7] + s1
	}}
	a, b, c, d, e, f, g, hh := h[0], h[1], h[2], h[3], h[4], h[5], h[6], h[7]
	for i := 0; i < 64; i++ {{
		s1 := rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)
		ch := e&f ^ ^e&g
		t1 := hh + s1 + ch + modK[i] + w[i]
		s0 := rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)
		mj := a&b ^ a&c ^ b&c
		t2 := s0 + mj
		hh, g, f, e = g, f, e, d+t1
		d, c, b, a = c, b, a, t1+t2
	}}
	h[0] += a
	h[1] += b
	h[2] += c
	h[3] += d
	h[4] += e
	h[5] += f
	h[6] += g
	h[7] += hh
	var out [32]byte
	for j := 0; j < 8; j++ {{
		out[4*j] = byte(h[j] >> 24)
		out[4*j+1] = byte(h[j] >> 16)
		out[4*j+2] = byte(h[j] >> 8)
		out[4*j+3] = byte(h[j])
	}}
	return out
}}

// anti-debug (addition B): IsDebuggerPresent + CheckRemoteDebuggerPresent
// + NtQueryInformationProcess(ProcessDebugPort) + a timing gate. Response:
// silent corruption (output XOR corruptMask).
func corruptState() uint64 {{
	kernel32 := syscall.NewLazyDLL("kernel32.dll")
	ntdll := syscall.NewLazyDLL("ntdll.dll")
	idp := kernel32.NewProc("IsDebuggerPresent")
	crdp := kernel32.NewProc("CheckRemoteDebuggerPresent")
	ntqip := ntdll.NewProc("NtQueryInformationProcess")
	hit := false
	if r, _, _ := idp.Call(); r != 0 {{
		hit = true
	}}
	var dbg int32
	if r, _, _ := crdp.Call(uintptr(0xffffffffffffffff),
		uintptr(unsafe.Pointer(&dbg))); r != 0 && dbg != 0 {{
		hit = true
	}}
	var port uint64
	ntqip.Call(uintptr(0xffffffffffffffff), 7,
		uintptr(unsafe.Pointer(&port)), 8, 0)
	if port != 0 {{
		hit = true
	}}
	t0 := time.Now()
	s := uint32(0)
	for i := 0; i < timingIters; i++ {{
		s += uint32(i)
	}}
	_ = s
	if time.Since(t0) > time.Duration(timingNs)*time.Nanosecond {{
		hit = true
	}}
	if hit {{
		return corruptMask
	}}
	return 0
}}

func main() {{
	in := make([]byte, 32)
	os.Stdin.Read(in)
	mask := corruptState()
	out := make([]byte, 64)
	var cat []byte
	var dig [32]byte
	/* flatten-begin rounds */
	for i := 0; i < 2; i++ {{
		/*@s1*/ cat = append(in, byte(i), 0, 0, 0)
		/*@s2*/ dig = modSha256(cat)
		/*@s3*/ copy(out[32*i:], dig[:])
	}}
	/* flatten-end */
	if mask != 0 {{
		for i := range out {{
			out[i] ^= byte(mask >> (8 * (i % 8)))
		}}
	}}
	os.Stdout.Write(out)
	syscall.Exit(0)
}}
"""


# ------------------------------------------------------- smc payload + stub ----
def render_payload_c(cfg: dict) -> str:
    """Freestanding mod-crypto payload: SHA digest -> AES block. The AES
    round loop carries the canonical flatten region (the L2 transform)."""
    sbox = ", ".join(f"0x{b:02x}" for b in cfg["sbox"])
    rcon = ", ".join(f"0x{b:02x}" for b in cfg["rcon"])
    return f"""/* payload.c — #332 SMC payload (family smc-x86): the mod-crypto
 * implementation, freestanding, position-independent, no libc. The
 * builder XOR-patches this function's .text into an encrypted blob; the
 * stub decrypts in place after its anti-debug gate. */
typedef unsigned int u32;
typedef unsigned char u8;

static const u32 PH[8] = {{{_u32s(cfg['h'])}}};
static const u32 PK[64] = {{{_u32s(cfg['k'])}}};
static const u8 PSBOX[256] = {{ {sbox} }};
static const u8 PRCON[10] = {{ {rcon} }};

static u32 prot(u32 x, int n) {{ return (x >> n) | (x << (32 - n)); }}

static void psha(const u8 *msg, u32 len, u8 out[32]) {{
    u32 h[8], w[64], i, j, padded, bits = len * 8u;
    u8 buf[128];
    for (i = 0; i < 8; i++) h[i] = PH[i];
    for (i = 0; i < len && i < 119u; i++) buf[i] = msg[i];
    buf[len] = 0x80u;
    padded = (len + 9u <= 64u) ? 64u : 128u;
    for (j = len + 1; j < padded - 8u; j++) buf[j] = 0u;
    for (i = 0; i < 8; i++) buf[padded - 8u + i] = (u8)(bits >> (56 - 8 * i));
    for (j = 0; j < padded; j += 64u) {{
        for (i = 0; i < 16; i++)
            w[i] = ((u32)buf[j+4*i] << 24) | ((u32)buf[j+4*i+1] << 16)
                | ((u32)buf[j+4*i+2] << 8) | (u32)buf[j+4*i+3];
        for (i = 16; i < 64; i++) {{
            u32 s0 = prot(w[i-15], 7) ^ prot(w[i-15], 18) ^ (w[i-15] >> 3);
            u32 s1 = prot(w[i-2], 17) ^ prot(w[i-2], 19) ^ (w[i-2] >> 10);
            w[i] = w[i-16] + s0 + w[i-7] + s1;
        }}
        {{
        u32 a = h[0], b = h[1], c = h[2], d = h[3];
        u32 e = h[4], f = h[5], g = h[6], hh = h[7];
        for (i = 0; i < 64; i++) {{
            u32 s1 = prot(e, 6) ^ prot(e, 11) ^ prot(e, 25);
            u32 ch = (e & f) ^ (~e & g);
            u32 t1 = hh + s1 + ch + PK[i] + w[i];
            u32 s0 = prot(a, 2) ^ prot(a, 13) ^ prot(a, 22);
            u32 mj = (a & b) ^ (a & c) ^ (b & c);
            u32 t2 = s0 + mj;
            hh = g; g = f; f = e; e = d + t1;
            d = c; c = b; b = a; a = t1 + t2;
        }}
        h[0]+=a; h[1]+=b; h[2]+=c; h[3]+=d;
        h[4]+=e; h[5]+=f; h[6]+=g; h[7]+=hh;
        }}
    }}
    for (i = 0; i < 4; i++)
        for (j = 0; j < 8; j++)
            out[4*j+i] = (u8)(h[j] >> (24 - 8 * i));
}}

static u8 pxtime(u8 a) {{ return (u8)((a << 1) ^ ((a >> 7) * 0x1b)); }}

static void aes_expand(const u8 *key, u8 *rk) {{
    u8 t[4];
    int i, j;
    for (i = 0; i < 16; i++) rk[i] = key[i];
    for (i = 16; i < 176; i += 4) {{
        for (j = 0; j < 4; j++) t[j] = rk[i - 4 + j];
        if ((i / 4) % 4 == 0) {{
            u8 tmp = t[0];
            t[0] = PSBOX[t[1]] ^ PRCON[(i / 4) / 4 - 1];
            t[1] = PSBOX[t[2]];
            t[2] = PSBOX[t[3]];
            t[3] = PSBOX[tmp];
        }}
        for (j = 0; j < 4; j++) rk[i + j] = (u8)(rk[i - 16 + j] ^ t[j]);
    }}
}}

__attribute__((noinline))
static void aes_sub_shift(u8 *s) {{
    u8 t, x[16];
    int i;
    for (i = 0; i < 16; i++) x[i] = PSBOX[s[i]];
    t = x[1]; x[1] = x[5]; x[5] = x[9]; x[9] = x[13]; x[13] = t;
    t = x[2]; x[2] = x[10]; x[10] = t;
    t = x[6]; x[6] = x[14]; x[14] = t;
    /* row 3: new[c] = old[(c+3)%4] - a 4-cycle 3<-15<-11<-7<-3 */
    t = x[3]; x[3] = x[15]; x[15] = x[11]; x[11] = x[7]; x[7] = t;
    for (i = 0; i < 16; i++) s[i] = x[i];
}}

__attribute__((noinline))
static void aes_mix(u8 *s, int r) {{
    int c;
    if (r == 9) return;
    for (c = 0; c < 4; c++) {{
        u8 a0 = s[4*c], a1 = s[4*c+1], a2 = s[4*c+2], a3 = s[4*c+3];
        s[4*c]   = (u8)(pxtime(a0) ^ pxtime(a1) ^ a1 ^ a2 ^ a3);
        s[4*c+1] = (u8)(a0 ^ pxtime(a1) ^ pxtime(a2) ^ a2 ^ a3);
        s[4*c+2] = (u8)(a0 ^ a1 ^ pxtime(a2) ^ pxtime(a3) ^ a3);
        s[4*c+3] = (u8)(pxtime(a0) ^ a0 ^ a1 ^ a2 ^ pxtime(a3));
    }}
}}

__attribute__((noinline))
static void aes_ark(u8 *s, const u8 *rk, int r) {{
    int i;
    for (i = 0; i < 16; i++) s[i] ^= rk[16 * (r + 1) + i];
}}

__attribute__((visibility("default")))
void payload_entry(const u8 *in, u8 out[16]) {{
    u8 dig[32], rk[176];
    int r;
    psha(in, 32, dig);
    aes_expand(dig, rk);
    for (r = 0; r < 16; r++) out[r] = (u8)(dig[16 + r] ^ rk[r]);
    /* flatten-begin rounds */
    for (r = 0; r < 10; r++) {{
        /*@s1*/ aes_sub_shift(out);
        /*@s2*/ aes_mix(out, r);
        /*@s3*/ aes_ark(out, rk, r);
    }}
    /* flatten-end */
}}
"""


def render_mod_c(cfg: dict) -> str:
    """The standalone mod-crypto core .so (family mod-crypto-native):
    same consumption shape as the payload, arm64, exported mod_derive,
    with the addition-B anti-debug gate."""
    sbox = ", ".join(f"0x{b:02x}" for b in cfg["sbox"])
    rcon = ", ".join(f"0x{b:02x}" for b in cfg["rcon"])
    return (
        "// mod_crypto.c — #332 CONSTRUCTED target "
        "(family mod-crypto-native):\n"
        "// the mod-crypto core as a standalone arm64 .so (exported\n"
        "// mod_derive). The other native faces consume this same core.\n"
        "#include <fcntl.h>\n"
        "#include <time.h>\n"
        "#include <unistd.h>\n"
        "#include <sys/ptrace.h>\n"
        "/* glibc/bionic declare PTRACE_TRACEME; macOS hosts "
        "(self-check builds) only define PT_TRACE_ME - same "
        "request code 0. */\n"
        "#ifndef PTRACE_TRACEME\n"
        "#define PTRACE_TRACEME 0\n"
        "#endif\n"
        "\n"
        + c_mod_sha_core(cfg)
        + "\nstatic const unsigned char MOD_SBOX[256] = { " + sbox + " };\n"
        "static const unsigned char MOD_RCON[10] = { " + rcon + " };\n"
        "\n"
        + c_anti_debug(cfg)
        + """
static unsigned char mod_xtime(unsigned char a) {
    return (unsigned char)((a << 1) ^ ((a >> 7) * 0x1b));
}

static void mod_expand(const unsigned char *key, unsigned char *rk) {
    unsigned char t[4];
    int i, j;
    for (i = 0; i < 16; i++) rk[i] = key[i];
    for (i = 16; i < 176; i += 4) {
        for (j = 0; j < 4; j++) t[j] = rk[i - 4 + j];
        if ((i / 4) % 4 == 0) {
            unsigned char tmp = t[0];
            t[0] = MOD_SBOX[t[1]] ^ MOD_RCON[(i / 4) / 4 - 1];
            t[1] = MOD_SBOX[t[2]];
            t[2] = MOD_SBOX[t[3]];
            t[3] = MOD_SBOX[tmp];
        }
        for (j = 0; j < 4; j++) rk[i + j] =
            (unsigned char)(rk[i - 16 + j] ^ t[j]);
    }
}

__attribute__((noinline))
static void mod_sub_shift(unsigned char *s) {
    unsigned char t, x[16];
    int i;
    for (i = 0; i < 16; i++) x[i] = MOD_SBOX[s[i]];
    t = x[1]; x[1] = x[5]; x[5] = x[9]; x[9] = x[13]; x[13] = t;
    t = x[2]; x[2] = x[10]; x[10] = t;
    t = x[6]; x[6] = x[14]; x[14] = t;
    /* row 3: new[c] = old[(c+3)%4] - a 4-cycle 3<-15<-11<-7<-3 */
    t = x[3]; x[3] = x[15]; x[15] = x[11]; x[11] = x[7]; x[7] = t;
    for (i = 0; i < 16; i++) s[i] = x[i];
}

__attribute__((noinline))
static void mod_mix(unsigned char *s, int r) {
    int c;
    if (r == 9) return;
    for (c = 0; c < 4; c++) {
        unsigned char a0 = s[4*c], a1 = s[4*c+1];
        unsigned char a2 = s[4*c+2], a3 = s[4*c+3];
        s[4*c]   = (unsigned char)(mod_xtime(a0) ^ mod_xtime(a1) ^ a1 ^ a2 ^ a3);
        s[4*c+1] = (unsigned char)(a0 ^ mod_xtime(a1) ^ mod_xtime(a2) ^ a2 ^ a3);
        s[4*c+2] = (unsigned char)(a0 ^ a1 ^ mod_xtime(a2) ^ mod_xtime(a3) ^ a3);
        s[4*c+3] = (unsigned char)(mod_xtime(a0) ^ a0 ^ a1 ^ a2 ^ mod_xtime(a3));
    }
}

__attribute__((noinline))
static void mod_ark(unsigned char *s, const unsigned char *rk, int r) {
    int i;
    for (i = 0; i < 16; i++) s[i] ^= rk[16 * (r + 1) + i];
}

__attribute__((visibility("default")))
void mod_derive(const unsigned char *in, unsigned char *out) {
    unsigned char dig[32], rk[176];
    unsigned long long mask = corrupt_state();
    int r;
    mod_sha256(in, 32, dig);
    mod_expand(dig, rk);
    for (r = 0; r < 16; r++) out[r] = (unsigned char)(dig[16 + r] ^ rk[r]);
    /* flatten-begin rounds */
    for (r = 0; r < 10; r++) {
        /*@s1*/ mod_sub_shift(out);
        /*@s2*/ mod_mix(out, r);
        /*@s3*/ mod_ark(out, rk, r);
    }
    /* flatten-end */
"""
        + _c_mask_apply(16)
        + "}\n")


def render_smc_stub(cfg: dict) -> str:
    needle_lit = ", ".join(
        f"0x{b:02x}" for b in bytes(b ^ cfg["needle_key"] for b in b"TracerPid:"))
    return f"""/* stub.c — #332 SMC stub (family smc-x86), freestanding x86_64.
 * Not malware: seeded synthetic constants; reads 32 bytes on stdin and
 * writes 16. The payload's .text is XOR-encrypted in this image; the
 * in-place decrypt is GATED on the anti-debug checks — under a tracer the
 * wrong key is applied, the canary misses, and the sample silently emits
 * corrupted outputs (input XOR WRONG_MASK). */
typedef unsigned int u32;
typedef unsigned long u64;
typedef unsigned char u8;

#define SYS_read 0
#define SYS_write 1
#define SYS_open 2
#define SYS_close 3
#define SYS_mprotect 10
#define SYS_exit 60
#define SYS_ptrace 101
#define PTRACE_TRACEME 0
#define PROT_RWX 7

#define NEEDLE_KEY 0x{cfg['needle_key']:02x}
#define TIMING_ITERS {cfg['timing_iters']}
#define TIMING_THRESHOLD {cfg['timing_tsc']}
#define WRONG_MASK 0x{cfg['corrupt_mask']:016x}ULL

static const unsigned char TRACER_N[10] = {{ {needle_lit} }};
static const unsigned char SMC_KEY[16] = {{ {", ".join(f"0x{b:02x}" for b in cfg['smc_key'])} }};
static const u64 PAYLOAD_ADDR = 0x{cfg['payload_addr']:016x}ULL;
static const u64 PAYLOAD_SIZE = 0x{cfg['payload_size']:016x}ULL;
static const u32 PAYLOAD_TAIL = 0x{cfg['payload_tail']:08x}u;

static long sys3(long n, long a, long b, long c) {{
    long r;
    __asm__ volatile ("syscall"
                      : "=a"(r) : "a"(n), "D"(a), "S"(b), "d"(c)
                      : "rcx", "r11", "memory");
    return r;
}}

static void corrupt_outputs(u8 *out, const u8 *in, u64 mask) {{
    int i;
    for (i = 0; i < 16; i++)
        out[i] = (u8)(in[i] ^ (u8)(mask >> (8 * (i & 7))));
}}

extern void payload_entry(const u8 *, u8 *);

void _start(void) {{
    u8 in[32], out[16];
    u8 needle[10];
    long fd, n, i, j;
    int hit = 0;
    u64 t0, t1, d, page;
    for (i = 0; i < 32; i++) {{
        if (sys3(SYS_read, 0, (long)(in + i), 1) != 1) in[i] = 0;
    }}
    for (i = 0; i < 10; i++)
        needle[i] = (u8)(TRACER_N[i] ^ NEEDLE_KEY);
    {{
        u8 buf[1024];
        fd = sys3(SYS_open, (long)"/proc/self/status", 0, 0);
        if (fd >= 0) {{
            n = sys3(SYS_read, fd, (long)buf, (long)sizeof(buf) - 1);
            sys3(SYS_close, fd, 0, 0);
            if (n > 0) {{
                for (i = 0; i + 10 < n; i++) {{
                    for (j = 0; j < 10; j++)
                        if (buf[i + j] != needle[j]) break;
                    if (j == 10) {{
                        long tp = 0, k = i + 10;
                        while (buf[k] == ' ') k++;
                        while (buf[k] >= '0' && buf[k] <= '9')
                            tp = tp * 10 + (buf[k++] - '0');
                        if (tp != 0) hit = 1;
                        break;
                    }}
                }}
            }}
        }}
    }}
    if (sys3(SYS_ptrace, PTRACE_TRACEME, 0, 0) == -1) hit = 1;
    {{
        unsigned int lo0, hi0, lo1, hi1;
        volatile u32 s = 0;
        __asm__ volatile ("rdtsc" : "=a"(lo0), "=d"(hi0));
        for (i = 0; i < TIMING_ITERS; i++) s += (u32)i;
        __asm__ volatile ("rdtsc" : "=a"(lo1), "=d"(hi1));
        d = (((u64)hi1 << 32) | lo1) - (((u64)hi0 << 32) | lo0);
        if (d > TIMING_THRESHOLD) hit = 1;
    }}
    if (hit) {{
        corrupt_outputs(out, in, WRONG_MASK);
    }} else {{
        volatile u32 *p;
        sys3(SYS_mprotect,
             (long)(PAYLOAD_ADDR & ~4095ULL),
             (long)(PAYLOAD_SIZE + 4096), PROT_RWX);
        p = (volatile u32 *)PAYLOAD_ADDR;
        for (i = 0; i < (long)PAYLOAD_SIZE; i += 4) {{
            u32 key = *(volatile u32 *)(SMC_KEY + (i & 12));
            p[i / 4] ^= key;
        }}
        if (*(volatile u32 *)(PAYLOAD_ADDR + PAYLOAD_SIZE - 4)
                != PAYLOAD_TAIL) {{
            corrupt_outputs(out, in, WRONG_MASK);
        }} else {{
            payload_entry(in, out);
        }}
    }}
    sys3(SYS_write, 1, (long)out, 16);
    sys3(SYS_exit, 0, 0, 0);
}}
"""


# ---------------------------------------------------------------- flattener ----
def flatten_region(src: str, name: str, lang: str) -> str:
    """OLLVM-STYLE source-level control-flow flattening (honest label: a
    python transform over the canonical marked loop, not OLLVM). Stage
    statements are single lines, emitted verbatim into the dispatcher."""
    begin = f"/* flatten-begin {name} */"
    end = "/* flatten-end */"
    bi = src.index(begin)
    ei = src.index(end, bi)
    region = src[bi + len(begin):ei]
    stages = re.findall(r"/\*@s\d+\*/\s*(.+)", region)
    stages = [s.rstrip() for s in stages if s.strip()]
    if lang == "c":
        m = re.search(r"for \((\w+) = 0; \1 < ([\w]+)", region)
        if not m:
            raise ValueError(f"no canonical C loop in region {name!r}")
        var, limit = m.group(1), m.group(2)
        out = [f"/* flatten-begin {name} (flattened: OLLVM-style "
               "switch dispatcher; volatile state = optimizer-resistant, "
               "the dispatcher cannot fold) */",
               "    volatile int _st = 0;",
               f"    {var} = 0;",
               "    for (;;) {",
               "        switch (_st) {"]
        n = len(stages)
        for idx, stmt in enumerate(stages):
            if idx == 0:
                out += [f"        case 0:",
                        f"            if ({var} < {limit}) {{",
                        f"                {stmt}",
                        f"                _st = 1;",
                        f"            }} else {{",
                        f"                goto _{name}_done;",
                        f"            }}",
                        f"            break;"]
            elif idx == n - 1:
                out += [f"        case {idx}:",
                        f"            {stmt}",
                        f"            {var}++;",
                        f"            _st = 0;",
                        f"            break;"]
            else:
                out += [f"        case {idx}:",
                        f"            {stmt}",
                        f"            _st = {idx + 1};",
                        f"            break;"]
        out += [f"        default: goto _{name}_done; break;",
                "        }",
                "    }",
                f"_{name}_done:;"]
        flat = "\n" + "\n".join(out) + "\n"
    else:
        m = re.search(r"for (\w+) := 0; \1 < (\w+)", region)
        if not m:
            raise ValueError(f"no canonical Go loop in region {name!r}")
        limit = m.group(2)
        # optimizer resistance: the dispatcher state is a PACKAGE-LEVEL
        # variable (declared by the renderer), so gc must keep the loads
        # across the loop's calls and cannot thread the constant
        # transitions back into straight-line code
        get, set = f"flattenGet{name.capitalize()}", \
            f"flattenSet{name.capitalize()}"
        out = [f"/* flatten-begin {name} (flattened: OLLVM-style "
               "switch dispatcher; noinline state accessors = "
               "optimizer-resistant) */",
               "\ti := 0",
               f"\t{set}(0)",
               f"\t{name}:",
               "\tfor {",
               f"\t\tswitch {get}() {{" ]
        n = len(stages)
        for idx, stmt in enumerate(stages):
            if idx == 0:
                out += ["\t\tcase 0:",
                        f"\t\t\tif i < {limit} {{",
                        f"\t\t\t\t{stmt}",
                        f"\t\t\t\t{set}(1)",
                        "\t\t\t} else {",
                        f"\t\t\t\tbreak {name}",
                        "\t\t\t}"]
            elif idx == n - 1:
                out += [f"\t\tcase {idx}:",
                        f"\t\t\t{stmt}",
                        "\t\t\ti++",
                        f"\t\t\t{set}(0)"]
            else:
                out += [f"\t\tcase {idx}:",
                        f"\t\t\t{stmt}",
                        f"\t\t\t{set}({idx + 1})"]
        out += ["\t\t}", "\t}"]
        flat = "\n" + "\n".join(out) + "\n"
    return src[:bi] + flat + src[ei:]
