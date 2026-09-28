//! Host-gated tests (run with plain `cargo test` — dev profile).
//! The android-only syscall faces are not host-testable; their pure
//! parsers/scanners and the poison semantics are.

use crackme::antianalysis;
use crackme::core;

#[test]
fn fips197_aes128_vector_at_stock_parameters() {
    // stock face (a=1, b=0, shift=0) must be plain AES-128:
    // AES-128(0-key, 0-block) = 66e94bd4ef8a2c3b884cfa59ca342b2e
    let spn = core::Spn::new(&[0u8; 16], 1, 0, 0);
    let ct = spn.encrypt(&[0u8; 16]);
    assert_eq!(
        ct,
        [
            0x66, 0xe9, 0x4b, 0xd4, 0xef, 0x8a, 0x2c, 0x3b, 0x88, 0x4c,
            0xfa, 0x59, 0xca, 0x34, 0x2b, 0x2e
        ]
    );
}

#[test]
fn mutated_parameters_diverge_from_stock() {
    // the graded constants must NOT be the stock ones
    assert_ne!(core::SIGMA_MUT, core::SIGMA_STD[0]);
    assert_ne!(core::MAGIC, core::DECOY_MAGIC);
    let (sbox_mut, _) = core::build_sbox(
        core::sbox_a(core::SBOX_SEED),
        core::sbox_b(core::SBOX_SEED),
    );
    let (sbox_stock, _) = core::build_sbox(1, 0);
    let diffs = (0..256).filter(|&i| sbox_mut[i] != sbox_stock[i]).count();
    assert!(diffs > 200, "mutated sbox too close to stock: {diffs} diffs");
}

#[test]
fn sbox_is_bijective_at_graded_seed() {
    let (sbox, inv) = core::build_sbox(
        core::sbox_a(core::SBOX_SEED),
        core::sbox_b(core::SBOX_SEED),
    );
    let mut seen = [false; 256];
    for v in sbox.iter() {
        assert!(!seen[*v as usize], "sbox not injective");
        seen[*v as usize] = true;
    }
    for i in 0..256 {
        assert_eq!(inv[sbox[i] as usize], i as u8);
    }
}

#[test]
fn determinism_probe_and_verify() {
    let inputs: Vec<Vec<u8>> = vec![
        (0u8..32).collect(),
        (0u8..17).map(|j| 0x3c ^ j).collect(),
        vec![0x42; 1],
        vec![0x90; 16],
    ];
    for inp in &inputs {
        let p1 = core::core_probe(inp);
        let p2 = core::core_probe(inp);
        assert_eq!(p1, p2);
        let v1 = core::core_verify(inp, core::clean_tweak);
        let v2 = core::core_verify(inp, core::clean_tweak);
        assert_eq!(v1, v2);
    }
}

#[test]
fn valid_license_mints_and_verifies() {
    let lic = core::mint_valid_license(16, 1 << 22).expect("mint search");
    assert_eq!(core::core_verify(&lic, core::clean_tweak), 0);
    // probe is defined for the same input
    assert_ne!(core::core_probe(&lic), 0);
    // one flipped byte breaks the double match
    let mut bad = lic.clone();
    let n = bad.len();
    bad[n - 1] ^= 0x01;
    assert_eq!(core::core_verify(&bad, core::clean_tweak), 1);
    // flipping a header byte breaks the magic
    let mut bad2 = lic.clone();
    bad2[0] ^= 0x01;
    assert_eq!(core::core_verify(&bad2, core::clean_tweak), 1);
}

#[test]
fn decoy_lane_is_fake_success_with_stock_constants() {
    let dec = core::mint_decoy_input(12, 1 << 22).expect("decoy mint");
    assert_eq!(dec[0], 0x44);
    assert_eq!(dec[1], 0x45);
    assert_eq!(core::core_verify(&dec, core::clean_tweak), 0);
    // a DE-prefixed input that misses the decoy magic fails
    let mut miss = dec.clone();
    miss[7] ^= 0x01;
    assert_eq!(core::core_verify(&miss, core::clean_tweak), 1);
}

#[test]
fn edge_arguments() {
    // empty input -> 2 (invalid args); short input -> 1 (verify can't run)
    assert_eq!(core::core_verify(&[], core::clean_tweak), 2);
    assert_eq!(core::core_verify(&[0x01], core::clean_tweak), 1);
    // probe stays total for any non-empty input (cyclic seed fill); the
    // material length feeds the nonce, so 8x0xab and 1x0xab differ
    let p8a = core::core_probe(&[0xab; 8]);
    let p8b = core::core_probe(&[0xab; 8]);
    assert_eq!(p8a, p8b);
    assert_ne!(p8a, core::core_probe(&[0xab]));
    let p1 = core::core_probe(&[0xab]);
    assert_eq!(p1, core::core_probe(&[0xab]));
}

// ---------------------------------------------------- anti-analysis faces

#[test]
fn tracer_pid_parser() {
    let clean = b"Name:\tcrackme\nState:\tS\nTracerPid:\t0\n".to_vec();
    assert_eq!(antianalysis::parse_tracer_pid(&clean), Some(0));
    let traced = b"Name:\tcrackme\nTracerPid:\t4711\nFDSize:\t64".to_vec();
    assert_eq!(antianalysis::parse_tracer_pid(&traced), Some(4711));
    let absent = b"Name:\tcrackme\nState:\tS\n".to_vec();
    assert_eq!(antianalysis::parse_tracer_pid(&absent), None);
    // "TracerPid" appearing as substring of another field name is not
    // matched (needle anchored on the colon)
    let decoy_field = b"OtherTracerPidX:\t9\n".to_vec();
    assert_eq!(antianalysis::parse_tracer_pid(&decoy_field), None);
}

#[test]
fn frida_maps_scan() {
    let clean = b"12c00000-12c50000 r--p 00000000 b3:02 123 /system/lib/libc.so\n".to_vec();
    assert!(!antianalysis::maps_has_frida(&clean));
    let frida = b"7f001000-7f009000 r-xp 00000000 00:00 0 /data/local/tmp/frida-agent-16.so\n".to_vec();
    assert!(antianalysis::maps_has_frida(&frida));
    let gadget = b"7f001000-7f009000 r-xp 00000000 00:00 0 /data/local/tmp/renamed_gadget.so [gum-js-loop]\n".to_vec();
    assert!(antianalysis::maps_has_frida(&gadget));
}

#[test]
fn brk_scan_arm64_int3_equivalent() {
    // clean arm64 code: no BRK encodings
    let clean: Vec<u8> = (0..0x40)
        .map(|j| ((j as u32).wrapping_mul(0x01010101)) as u8)
        .collect();
    assert!(!antianalysis::scan_brk(&clean));
    // BRK #0 (0xD4200000) — the gdb/lldb breakpoint — is caught
    let mut hit = clean.clone();
    hit[16..20].copy_from_slice(&0xD420_0000u32.to_le_bytes());
    assert!(antianalysis::scan_brk(&hit));
    // BRK #0x3448 (any imm) is caught; HLT (0xD4400000) is not BRK
    let mut hit2 = clean.clone();
    hit2[20..24].copy_from_slice(&0xD426_8900u32.to_le_bytes());
    assert!(antianalysis::scan_brk(&hit2));
    let mut hlt = clean.clone();
    hlt[20..24].copy_from_slice(&0xD440_0000u32.to_le_bytes());
    assert!(!antianalysis::scan_brk(&hlt));
}

#[test]
fn timing_threshold_face() {
    assert!(!antianalysis::timing_tripped(0));
    assert!(!antianalysis::timing_tripped(1_000_000)); // 1 ms: clean core
    assert!(!antianalysis::timing_tripped(antianalysis::TIMING_THRESH_NS));
    assert!(antianalysis::timing_tripped(antianalysis::TIMING_THRESH_NS + 1));
}

#[test]
fn poison_semantics_look_like_wrong_key_not_detection() {
    antianalysis::reset_for_tests();
    assert!(!antianalysis::poisoned());
    // poison corrupts a valid license into a plain verify-failure — no
    // dedicated "detected" return code exists anywhere in the ABI
    let lic = core::mint_valid_license(16, 1 << 22).expect("mint");
    assert_eq!(core::core_verify(&lic, core::clean_tweak), 0);
    assert_eq!(
        core::core_verify(&lic, core::poison_tweak),
        1,
        "poisoned output must be a plain failure code"
    );
    // and the probe oracle shifts to a corrupted-but-legal value
    let p_clean = core::core_probe(&lic);
    let p_poison = core::core_probe_with(&lic, core::poison_tweak);
    assert_ne!(p_clean, p_poison);
    // determinism of the corruption itself
    assert_eq!(
        core::core_probe_with(&lic, core::poison_tweak),
        p_poison
    );
    // a wrong key and a poisoned run share the same observable SHAPE:
    // both are verify()==1 with ordinary probe bytes
    let mut wrong = lic.clone();
    wrong[3] ^= 0xff;
    assert_eq!(core::core_verify(&wrong, core::clean_tweak), 1);
}
