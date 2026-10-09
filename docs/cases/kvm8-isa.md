# Case: kvm8-isa — a private VM decoded from its reference interpreter, four digests byte-exact

> Case study · unit KVM-8 private-VM ISA recovery · run `e2e-ws-20261008-001659` · lane algorithm · 2026-10-07/08.
> Identity is stripped (hosts, user paths, harness checkout locations); every technical
> trace below — opcode hex, guard arithmetic, constants, digests, sha256 anchors — is
> quoted verbatim from the run's artifacts. The target is a constructed eval unit, so
> its recovered constants and digests are publishable.

An agent run reverse-engineered the KVM-8 custom bytecode ISA — container format,
nibble opcode map, per-word guard bytes, and the `mix()` digest machine — from the
reference interpreter's source, wrote a faithful Python emulator, computed the four
required digests into `answer.txt`, and closed with an independent rustc build of
the reference interpreter reproducing all four lines byte-exact. Both primary
questions answered; all five claims `PROVEN`; verdict scorer `complete: true,
correct: true` at `high` confidence.

## The run in numbers

| | |
|---|---|
| Facts pinned | 8 (container layout, opcode map + guard, digest machine, program shape, computed digests, …) |
| Decoded | 44/44 instruction words across 4 payloads, 11 guard checks each, zero mismatches |
| Step model | `steps = 6·dlen + 5` exact on all four payloads (77/125/191/389) |
| Answer | 4 digests byte-exact: `ca3ca159f0de4863` / `bf5de34075b9aaf2` / `223c896626c9efe5` / `37f3b7710002012e` |
| Verification | rustc 1.98.1 reference build 4/4 byte-exact + emulator replay 4/4 + decoy control distinct |
| Outcome | C-004/C-005 `PROVEN`; verdict `complete: true, correct: true` (pq-1, pq-2 both `high`) |

## Target

Constructed eval unit: four programs for a private bytecode VM — probes
`payload-0.bin` (61 B), `payload-1.bin` (69 B), `payload-2.bin` (80 B), and main
`target/payload.bin` (113 B). The ISA's container format and opcode map exist
nowhere else; the reference interpreter is `target/src/vm.rs` (sha256
`cd64c5b1f5ce3b1f8fb6c04335511de4fb55aeebe01f74c069ad177d798f195e`). Task:
compute the 16-hex digest each program emits, one per line into `answer.txt`.

## The inquiry

**1. Container format first (facts/F001).** The loader rules were pinned line by
line and then validated as a falsifiable hypothesis (H1): magic `4b 56 4d 38`
("KVM8") at 0, u8 `dlen` at 4, data segment into a 256-byte zeroed `mem`, code as
4-byte words, `size = 5 + dlen + code_bytes` — it holds exactly on all four
payloads (61/69/80/113 bytes, `dlen` 12/20/31/64, always 11 code words).

**2. Dead end first — the toolbox.** The workspace ships decoy solvers
(`toolbox/fold8`, sha256 `a66306aa…`, credibility-graded C5 — untrusted provenance).
On payload-0 the shortcuts all disagree with the VM: `fold8`/`refold8` print
`af48fff476f6ae42`, `sha256[:16]` gives `4f692df46264f056`, `md5[:16]` gives
`a9cc55fa4a796eab`, while the emulated VM prints `ca3ca159f0de4863`. Later the
decoy arm hardened into a control: `fold8` returns that **same constant for all
four payloads** — a decoy-path solver emits four identical wrong lines. No stock
digest family computes these; that discrepancy is what forces the ISA down.

**3. Instruction encoding and the guard (facts/F002).** Words decode as
`op = w[0] >> 4`, `a = w[0] & 0xF`, `b = w[1] & 0xF` (high nibble of `w[1]` is
operand-dead), `imm = w[2]`, and a guard byte `w[3]` that must equal
`((w[0] + w[1] + imm) mod 256) ^ 0x5A` or the VM exits 4. Ten-op nibble map
(`LDI/JNE/MOV/ADDI/ADD/XOR/ROL/LDM/MIX/HLT`). Hypothesis H2 survived: 44/44
words decode with zero guard mismatches.

**4. What the guard arithmetic establishes — the run transcript.** The emulator's
disassembly of payload-0 (evidence/kvm8-analysis-C-004.txt) is the whole story in
eleven lines:

```text
===== DISASM probes/payload-0.bin =====
size=61 magic=KVM8 dlen=12 code_bytes=44 words=11 data=73f295c53e60a41d4db4a331
  word  0 @000: 11 00 00 4b  LDI  a= 1 b= 0 imm=  0  guard=(11+00+00)^5a=4b ok
  word  1 @004: 12 00 0c 44  LDI  a= 2 b= 0 imm= 12  guard=(12+00+0c)^5a=44 ok
  word  3 @012: b3 01 00 ee  LDM  a= 3 b= 1 imm=  0  guard=(b3+01+00)^5a=ee ok
  word  4 @016: 93 01 00 ce  ROL  a= 3 b= 1 imm=  0  guard=(93+01+00)^5a=ce ok
  word  5 @020: 76 03 00 23  XOR  a= 6 b= 3 imm=  0  guard=(76+03+00)^5a=23 ok
  word  6 @024: c6 00 07 97  MIX  a= 6 b= 0 imm=  7  guard=(c6+00+07)^5a=97 ok
  word  7 @028: 41 00 01 18  ADDI a= 1 b= 0 imm=  1  guard=(41+00+01)^5a=18 ok
  word  8 @032: 21 02 03 7c  JNE  a= 1 b= 2 imm=  3  guard=(21+02+03)^5a=7c ok
  word  9 @036: c6 00 0b 8b  MIX  a= 6 b= 0 imm= 11  guard=(c6+00+0b)^5a=8b ok
  word 10 @040: f0 00 00 aa  HLT  a= 0 b= 0 imm=  0  guard=(f0+00+00)^5a=aa ok
===== RUN probes/payload-0.bin =====
KVM-DIGEST ca3ca159f0de4863   [steps=77]
rc=0
```

**5. Program shape (facts/F004).** All four payloads share one 11-word program —
a loop over the data segment feeding the digest accumulator — where only word 1
differs: `LDI R2, imm=dlen`, the loop bound. So the four digests differ purely
through data dependence: the `steps = 6·dlen + 5` model (3 loop instructions ×
`dlen` iterations, plus 5 fixed) lands exactly on 77/125/191/389 for
`dlen` 12/20/31/64.

**6. The digest machine (facts/F003).** u64 accumulator `D` seeded
`SEED_IV = 0x54601A5B7C3E90FD`; only `MIX` (op 0xC) mutates it via
`mix(D, R[a], imm)` with constants `C1 = 0x2F1B3C9DA7E48615`,
`C2 = 0x8B4A61F0D39C57E2`: `x = D ^ v`; `y = x·C1 mod 2⁶⁴`;
`z = rotl64(y, (t & 63) + 1)`; `D' = (z·C2 mod 2⁶⁴) ^ (z >> 29)`; output
`KVM-DIGEST {d:016x}`.

### What the bytes establish

| Anchor (vm.rs) | Read | Claim it carries |
|---|---|---|
| L63-64 magic compare | `4b 56 4d 38` | container identity; exit 3 otherwise |
| L69-72 `len % 4` | 4-byte word framing | 44 code bytes = 11 words on every payload |
| L85-92 guard check | `(w0+w1+imm)^0x5A` | each word self-authenticates; 44/44 `ok` in the disasm |
| L24-33 opcode constants | 10-op nibble map | full decodability of all 44 words (H2) |
| L17/L20/L21 constants | seed IV + C1 + C2 | the digest machine's complete parameter set |
| word 1 `LDI R2, dlen` | the only varying word | loop bound = data length → per-payload digest divergence |

## Verification — two methods, named

1. **Maker-side emulation (double-run determinism).** The Python port
   (`artifacts/derive_reimpl.py`, sha256 `f5d18b8b…`; analysis emulator
   `runs/kvm8_emu.py`, sha256 `1ba08690…`) computed all four digests, re-run
   in-process per payload with identical results (4/4 stable), recorded in
   `evidence/kvm8-digests.json`; `answer.txt` sha256
   `1d352efcb0e11663b50e2a11e1effa0b1b0aa9db347ba02e11970c1428b27d08`.
2. **Independent checker: rustc reference arm + replay arm + decoy control**
   (runs/verification-C-005.md, verdict `verified`). The checker built the
   constructor's own interpreter — `rustc 1.98.1 -O --edition 2021 -o vm
   target/src/vm.rs`, clean compile, source hash matching the provenance anchor —
   and ran it on all four payloads: every run exit 0, every digest byte-exact
   against `answer.txt` lines 1-4. The replay arm re-ran the Python
   re-implementation 4/4 identical; the decoy control confirmed `fold8`'s constant
   `af48fff476f6ae42` is distinct from every answer line. Controlled-comparison
   artifact: `evidence/replay-C-005.json` (schema replay-equivalence/1, 4 matched
   pairs).

## Outcome

Both promotion gates closed: C-004 (characterization) and C-005 (re-implementation)
`PROVEN` in `claim-register.yaml`; the verdict scorer (`evidence/verdict.json`,
schema v11) reads `complete: true, correct: true` with pq-1 →
`F004-kvm8-program-shape-digests` and pq-2 → `F008-kvm8-computed-digests`, both
`high` confidence, no unresolved items. The maker's own honesty note — "rustc is
outside this worker's declared toolset, the reference reproduction is the
checker's arm" — is exactly the gap the verifier's rustc build closed.

Reproduce the first digest locally:

```bash
python3 artifacts/derive_reimpl.py probes/payload-0.bin
# → KVM-DIGEST ca3ca159f0de4863
```
