//! libcrackme.so — the rust-so-crack-v1 sample (arm64 android cdylib).
//!
//! C ABI surface (no jni needed):
//!   crackme_verify(const uint8_t *in, size_t n) -> int32
//!       0 valid · 1 invalid · 2 bad arguments
//!   crackme_probe(const uint8_t *in, size_t n, uint64_t *out) -> int32
//!       deterministic intermediate oracle: *out = first 8 bytes of the
//!       P2 keystream block 0 (LE u64); 0 ok · 2 bad arguments
//!
//! Anti-analysis runs only on the android target; a clean run (no tracer,
//! no frida, no breakpoints) is fully deterministic — no time-based key
//! material exists. Detection silently corrupts the derived keystream.
//!
//! The android lib build is no_std (build with `cargo build --release
//! --target aarch64-linux-android --lib`); host builds (bin + tests, which
//! need std::io / std::process) keep std through the cfg_attr below.

#![cfg_attr(all(target_os = "android", target_arch = "aarch64"), no_std)]

pub mod antianalysis;
pub mod core;

use ::core::slice;

/// no_std panic floor (android lib build only): exit_group(70) — an abort
/// that never emits a BRK byte into the .text BRK self-scan window.
#[cfg(all(target_os = "android", target_arch = "aarch64"))]
#[panic_handler]
fn crackme_panic(_: &::core::panic::PanicInfo<'_>) -> ! {
    unsafe {
        ::core::arch::asm!(
            "mov x8, #94",  // __NR_exit_group
            "mov x0, #70",
            "svc 0",
            options(noreturn)
        )
    }
}

/// identity-on-clean poison hook: corrupt only when a face has tripped
fn poison_hook(ks: &mut [u8]) {
    if antianalysis::poisoned() {
        core::poison_tweak(ks);
    }
}

/// unconditional corruption (recompute under poison)
fn force_tweak(ks: &mut [u8]) {
    core::poison_tweak(ks);
}

#[no_mangle]
pub unsafe extern "C" fn crackme_verify(buf: *const u8, len: usize) -> i32 {
    if buf.is_null() || len == 0 {
        return 2;
    }
    let input: &[u8] = slice::from_raw_parts(buf, len);
    antianalysis::ensure_init();
    let t0 = antianalysis::now_ns();
    let mut r = core::core_verify(input, poison_hook);
    let t1 = antianalysis::now_ns();
    // verify-time faces: wall-clock delta + .text BRK self-scan
    if antianalysis::timing_tripped(t1.saturating_sub(t0)) {
        antianalysis::trip();
    }
    let entry: unsafe extern "C" fn(*const u8, usize) -> i32 = crackme_verify;
    antianalysis::brk_self_scan(entry as usize);
    if antianalysis::poisoned() {
        // a face tripped (this call or an earlier one): the observable is
        // a wrong-key failure — identical shape to a genuinely wrong key
        r = core::core_verify(input, force_tweak);
    }
    r
}

#[no_mangle]
pub unsafe extern "C" fn crackme_probe(
    buf: *const u8,
    len: usize,
    out: *mut u64,
) -> i32 {
    if buf.is_null() || len == 0 || out.is_null() {
        return 2;
    }
    let input: &[u8] = slice::from_raw_parts(buf, len);
    antianalysis::ensure_init();
    let t0 = antianalysis::now_ns();
    let mut v = core::core_probe(input);
    let t1 = antianalysis::now_ns();
    if antianalysis::timing_tripped(t1.saturating_sub(t0)) {
        antianalysis::trip();
    }
    let entry: unsafe extern "C" fn(*const u8, usize, *mut u64) -> i32 =
        crackme_probe;
    antianalysis::brk_self_scan(entry as usize);
    if antianalysis::poisoned() {
        v = core::core_probe_with(input, force_tweak);
    }
    *out = v;
    0
}
