//! vm.rs — KVM-8, a toy custom-ISA bytecode VM (blocked-path unit #546,
//! tf-novelvm-rust-v1). The ISA below is private to this unit: four-byte
//! fixed-width instruction words, a nibble-packed opcode map that exists
//! nowhere else, and a per-word guard byte. There are no standard loader
//! semantics — the container is `KVM8` + a data segment + raw code words.
//!
//! Build: rustc -O --edition 2021 -o vm vm.rs && strip vm
//! Usage: vm <program.k8>       (prints "KVM-DIGEST <16 hex>")
//! Exit: 0 ok / 2 usage / 3 bad container / 4 bad guard / 5 step limit

use std::env;
use std::fs;
use std::process::exit;

const MAGIC: [u8; 4] = *b"KVM8";
const STEP_LIMIT: u32 = 65536;
const SEED_IV: u64 = 0x5460_1A5B_7C3E_90FD;

// private per-unit mixing constants (seed 54601; exist nowhere else)
const C1: u64 = 0x2F1B_3C9D_A7E4_8615;
const C2: u64 = 0x8B4A_61F0_D39C_57E2;

// opcode map (nibble values chosen un-typical; nothing standard here)
const OP_LDI: u8 = 0x1; // R[a] = imm
const OP_JNE: u8 = 0x2; // if R[a] != R[b] { pc = imm * 4 }
const OP_MOV: u8 = 0x3; // R[a] = R[b]
const OP_ADDI: u8 = 0x4; // R[a] = R[a] + imm
const OP_ADD: u8 = 0x5; // R[a] = R[a] + R[b]
const OP_XOR: u8 = 0x7; // R[a] = R[a] ^ R[b]
const OP_ROL: u8 = 0x9; // R[a] = rotl8(R[a], R[b] & 7)
const OP_LDM: u8 = 0xB; // R[a] = M[R[b]]
const OP_MIX: u8 = 0xC; // D = mix(D, R[a], imm)
const OP_HLT: u8 = 0xF; // halt, emit D

fn die(code: i32, msg: &str) -> ! {
    eprintln!("kvm8: {msg}");
    exit(code)
}

fn mix(d: u64, v: u8, t: u8) -> u64 {
    let x = d ^ (v as u64);
    let y = x.wrapping_mul(C1);
    let z = y.rotate_left(((t & 63) as u32) + 1);
    z.wrapping_mul(C2) ^ (z >> 29)
}

struct Vm {
    r: [u8; 16],
    mem: [u8; 256],
    d: u64,
    pc: usize,
}

fn main() {
    let argv: Vec<String> = env::args().collect();
    if argv.len() != 2 {
        eprintln!("usage: vm <program.k8>");
        exit(2);
    }
    let raw =
        fs::read(&argv[1]).unwrap_or_else(|e| die(3, &format!("cannot read {}: {e}", argv[1])));
    if raw.len() < 6 || raw[..4] != MAGIC {
        die(3, "not a KVM8 container (magic)");
    }
    let dlen = raw[4] as usize;
    if dlen > 256 || raw.len() < 5 + dlen {
        die(3, "bad data segment");
    }
    let code = &raw[5 + dlen..];
    if code.is_empty() || code.len() % 4 != 0 {
        die(3, "code segment must be non-empty 4-byte words");
    }
    let mut v = Vm { r: [0; 16], mem: [0; 256], d: SEED_IV, pc: 0 };
    v.mem[..dlen].copy_from_slice(&raw[5..5 + dlen]);
    let mut stepped = 0u32;
    let out = loop {
        if stepped >= STEP_LIMIT {
            die(5, "step limit exceeded");
        }
        stepped += 1;
        let at = v.pc;
        if at + 4 > code.len() {
            die(3, "pc ran off the code segment");
        }
        let w = [code[at], code[at + 1], code[at + 2], code[at + 3]];
        let op = w[0] >> 4;
        let a = (w[0] & 0x0F) as usize;
        let b = (w[1] & 0x0F) as usize;
        let imm = w[2];
        if w[3] != (w[0].wrapping_add(w[1]).wrapping_add(imm) ^ 0x5A) {
            die(4, &format!("guard mismatch at word {at}"));
        }
        v.pc += 4;
        match op {
            OP_LDI => v.r[a] = imm,
            OP_JNE => {
                if v.r[a] != v.r[b] {
                    v.pc = (imm as usize) * 4;
                }
            }
            OP_MOV => v.r[a] = v.r[b],
            OP_ADDI => v.r[a] = v.r[a].wrapping_add(imm),
            OP_ADD => v.r[a] = v.r[a].wrapping_add(v.r[b]),
            OP_XOR => v.r[a] ^= v.r[b],
            OP_ROL => v.r[a] = v.r[a].rotate_left((v.r[b] & 7) as u32),
            OP_LDM => v.r[a] = v.mem[v.r[b] as usize],
            OP_MIX => v.d = mix(v.d, v.r[a], imm),
            OP_HLT => break v.d,
            _ => die(3, &format!("unknown opcode {op:#x} at word {at}")),
        }
    };
    println!("KVM-DIGEST {out:016x}");
}
