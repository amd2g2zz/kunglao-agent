//! Anti-analysis faces (rust-so-crack-v1).
//!
//! Faces (each individually bypassable, stacked; poison semantics:
//! detection SILENTLY corrupts the derived keystream — the observable is
//! a wrong key, never an exception or log line):
//!   1. PTRACE_TRACEME self-probe at init (EPERM -> already traced)
//!   2. /proc/self/status TracerPid parse via INLINE syscalls
//!   3. clock_gettime timing deltas around the core (threshold -> poison)
//!   4. .text BRK (arm64 "int3") self-scan over the verify entry window
//!   5. anti-frida /proc/self/maps scan
//!
//! Ordering guarantee (clean-run determinism): the TracerPid parse and the
//! frida maps scan run BEFORE the TRACEME probe — a successful TRACEME
//! legitimately marks the parent as tracer, and re-parsing TracerPid after
//! it would self-poison a clean process. TracerPid is therefore never
//! re-checked after init; verify-time re-checks are timing + BRK only.
//!
//! The pure parsers/scanners (TracerPid, maps needle, BRK pattern, timing
//! threshold) compile on every target and are host-tested; the syscall
//! wiring is aarch64-linux/android only.

use core::sync::atomic::{AtomicU8, Ordering};

pub const TIMING_THRESH_NS: u64 = 100_000_000; // 100 ms; core runs in µs
/// BRK scan window: bytes of the verify entry region scanned at verify time.
pub const BRK_SCAN_WINDOW: usize = 0x600;

static POISON: AtomicU8 = AtomicU8::new(0);
static INIT_DONE: AtomicU8 = AtomicU8::new(0);

pub fn trip() {
    POISON.store(1, Ordering::SeqCst);
}

pub fn poisoned() -> bool {
    POISON.load(Ordering::SeqCst) != 0
}

/// reset (host tests only)
pub fn reset_for_tests() {
    POISON.store(0, Ordering::SeqCst);
    INIT_DONE.store(0, Ordering::SeqCst);
}

// ------------------------------------------------------------ pure faces

/// Parse "TracerPid:\t<n>" out of a /proc/self/status image.
/// None when the field is absent (treat as clean — never guess poison).
pub fn parse_tracer_pid(buf: &[u8]) -> Option<u32> {
    let needle = b"TracerPid:";
    let mut i = 0;
    while i + needle.len() <= buf.len() {
        if &buf[i..i + needle.len()] == needle {
            let mut j = i + needle.len();
            while j < buf.len() && (buf[j] == b' ' || buf[j] == b'\t') {
                j += 1;
            }
            let start = j;
            while j < buf.len() && buf[j].is_ascii_digit() {
                j += 1;
            }
            if j > start {
                let mut v: u32 = 0;
                for &c in &buf[start..j] {
                    v = v
                        .wrapping_mul(10)
                        .wrapping_add((c - b'0') as u32);
                }
                return Some(v);
            }
            return None;
        }
        i += 1;
    }
    None
}

const FRIDA_NEEDLES: [&[u8]; 4] =
    [b"frida-agent", b"frida-gadget", b"gum-js-loop", b"linjector"];

/// /proc/self/maps scan: any frida gadget/agent signature -> true.
pub fn maps_has_frida(buf: &[u8]) -> bool {
    FRIDA_NEEDLES.iter().any(|n| contains(buf, n))
}

fn contains(hay: &[u8], needle: &[u8]) -> bool {
    if needle.is_empty() || hay.len() < needle.len() {
        return false;
    }
    hay.windows(needle.len()).any(|w| w == needle)
}

/// arm64 .text self-scan: any BRK instruction in the window -> true.
/// BRK encoding: 1101 0100 001i iiii iiii iiii ii0 0000 — the fixed
/// pattern 0xD4200000 with the imm16 field free (mask 0xFFE0001F).
/// This is the arm64 equivalent of the x86 int3 (0xCC) self-scan.
pub fn scan_brk(bytes: &[u8]) -> bool {
    let mut off = 0;
    // 4-byte instruction alignment: caller passes a window-aligned view
    while off + 4 <= bytes.len() {
        let w = u32::from_le_bytes([
            bytes[off],
            bytes[off + 1],
            bytes[off + 2],
            bytes[off + 3],
        ]);
        if w & 0xFFE0_001F == 0xD420_0000 {
            return true;
        }
        off += 4;
    }
    false
}

/// Timing threshold face (pure): a wall delta over the limit trips.
pub fn timing_tripped(delta_ns: u64) -> bool {
    delta_ns > TIMING_THRESH_NS
}

// -------------------------------------------------- android syscall wiring

#[cfg(all(target_arch = "aarch64", target_os = "android"))]
pub mod raw {
    /// raw linux syscall (aarch64): nr in x8, args x0..x5, ret x0
    #[inline(always)]
    pub unsafe fn sys6(
        nr: usize,
        a0: usize,
        a1: usize,
        a2: usize,
        a3: usize,
        a4: usize,
        a5: usize,
    ) -> isize {
        let ret: usize;
        core::arch::asm!(
            "svc 0",
            inlateout("x0") a0 => ret,
            in("x1") a1,
            in("x2") a2,
            in("x3") a3,
            in("x4") a4,
            in("x5") a5,
            in("x8") nr,
            options(nostack)
        );
        ret as isize
    }

    const SYS_OPENAT: usize = 56;
    const SYS_READ: usize = 63;
    const SYS_CLOSE: usize = 57;
    const SYS_CLOCK_GETTIME: usize = 113;
    const SYS_PTRACE: usize = 117;
    const AT_FDCWD: isize = -100;

    /// open+read a /proc file into buf; returns bytes read (0 on failure —
    /// a missing procfs entry is treated as no-evidence, never poison).
    pub unsafe fn read_proc(path: &[u8], buf: &mut [u8]) -> usize {
        let fd = sys6(SYS_OPENAT, AT_FDCWD as usize,
                      path.as_ptr() as usize, 0 /* O_RDONLY */,
                      0, 0, 0);
        if fd < 0 {
            return 0;
        }
        let mut total = 0usize;
        while total < buf.len() {
            let n = sys6(SYS_READ, fd as usize,
                         buf.as_mut_ptr().add(total) as usize,
                         buf.len() - total, 0, 0, 0);
            if n <= 0 {
                break;
            }
            total += n as usize;
        }
        sys6(SYS_CLOSE, fd as usize, 0, 0, 0, 0, 0);
        total
    }

    /// CLOCK_MONOTONIC via inline syscall; 0 on failure (fail-open: a
    /// broken clockface yields delta 0 — no poison on clean hardware).
    pub unsafe fn monotonic_ns() -> u64 {
        let mut ts = [0isize; 2]; // { tv_sec, tv_nsec }
        let r = sys6(SYS_CLOCK_GETTIME, 1 /* CLOCK_MONOTONIC */,
                     ts.as_mut_ptr() as usize, 0, 0, 0, 0);
        if r < 0 {
            return 0;
        }
        ts[0] as u64 * 1_000_000_000 + ts[1] as u64
    }

    /// PTRACE_TRACEME probe: < 0 means EPERM — someone already traces us.
    pub unsafe fn ptrace_traceme_denied() -> bool {
        sys6(SYS_PTRACE, 0 /* PTRACE_TRACEME */, 0, 0, 0, 0, 0) < 0
    }
}

#[cfg(all(target_arch = "aarch64", target_os = "android"))]
pub use raw::monotonic_ns as now_ns;

#[cfg(not(all(target_arch = "aarch64", target_os = "android")))]
pub fn now_ns() -> u64 {
    // host (pure oracle build): std clock, face inert by construction
    use std::time::Instant;
    use std::sync::OnceLock;
    static T0: OnceLock<Instant> = OnceLock::new();
    let t0 = T0.get_or_init(Instant::now);
    t0.elapsed().as_nanos() as u64
}

/// One-shot init self-check: TracerPid parse + frida maps scan + the
/// TRACEME probe (strictly last — see the module ordering guarantee).
#[cfg(all(target_arch = "aarch64", target_os = "android"))]
pub fn ensure_init() {
    if INIT_DONE.swap(1, Ordering::SeqCst) != 0 {
        return;
    }
    unsafe {
        let path = b"/proc/self/status\0";
        let mut buf = [0u8; 8192];
        let n = raw::read_proc(path, &mut buf);
        if let Some(pid) = parse_tracer_pid(&buf[..n]) {
            if pid != 0 {
                trip();
            }
        }
        let maps = b"/proc/self/maps\0";
        let mut mbuf = [0u8; 32768];
        let m = raw::read_proc(maps, &mut mbuf);
        if maps_has_frida(&mbuf[..m]) {
            trip();
        }
        if raw::ptrace_traceme_denied() {
            trip();
        }
    }
}

#[cfg(not(all(target_arch = "aarch64", target_os = "android")))]
pub fn ensure_init() {
    // host oracle build: no faces armed; pure deterministic core
    INIT_DONE.store(1, Ordering::SeqCst);
}

/// verify-time faces: BRK self-scan over the verify entry window.
/// `entry` is the address of the exported crackme_verify; the window is
/// validated BRK-free on the committed build (see ground_truth
/// build_record).
#[cfg(all(target_arch = "aarch64", target_os = "android"))]
pub fn brk_self_scan(entry: usize) {
    let base = entry & !0x3usize; // 4-byte align
    let mut buf = [0u8; BRK_SCAN_WINDOW];
    unsafe {
        let src = base as *const u8;
        for i in 0..BRK_SCAN_WINDOW {
            buf[i] = *src.add(i);
        }
    }
    if scan_brk(&buf) {
        trip();
    }
}

#[cfg(not(all(target_arch = "aarch64", target_os = "android")))]
pub fn brk_self_scan(_entry: usize) {}
