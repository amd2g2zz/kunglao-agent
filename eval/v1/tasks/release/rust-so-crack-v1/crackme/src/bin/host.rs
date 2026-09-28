//! crackme_host — the host-side oracle (rust-so-crack-v1).
//!
//! Same crypto core as the android cdylib (src/core.rs), pure: the
//! anti-analysis syscall wiring is android-only, so the host build is the
//! deterministic mint/replay oracle the checker uses to grade candidates.
//!
//! subcommands:
//!   replay        stdin JSON lines {"i":<int>,"input":[<ints>...]} ->
//!                 stdout JSON lines {"i":<int>,"verify":<int>,"probe":"<16hex>"}
//!   selftest      internal sanity checks -> {"ok":bool,...}
//!   mint          canonical valid license + decoy input -> JSON
//!   determinism   two identical passes over fixed inputs -> JSON

use std::io::{self, BufRead, Write};

fn out_json(line: &str) {
    let mut so = io::stdout();
    let _ = writeln!(so, "{}", line);
    let _ = so.flush();
}

fn parse_i(line: &str) -> Option<(i64, Vec<u8>)> {
    let i_pos = line.find("\"i\"")?;
    let rest = &line[i_pos + 3..];
    let colon = rest.find(':')?;
    let rest = &rest[colon + 1..];
    let mut j = 0;
    let bytes = rest.as_bytes();
    while j < bytes.len() && (bytes[j] == b' ' || bytes[j] == b'\t') {
        j += 1;
    }
    let start = j;
    while j < bytes.len() && bytes[j].is_ascii_digit() {
        j += 1;
    }
    let i: i64 = rest[start..j].parse().ok()?;
    let in_pos = line.find("\"input\"")?;
    let rest2 = &line[in_pos + 7..];
    let open = rest2.find('[')?;
    let close = rest2.find(']')?;
    let body = &rest2[open + 1..close];
    let mut input = Vec::new();
    for part in body.split(',') {
        let p = part.trim();
        if p.is_empty() {
            continue;
        }
        input.push(p.parse::<u8>().ok()?);
    }
    Some((i, input))
}

fn hex16(v: u64) -> String {
    let mut s = String::with_capacity(16);
    for k in 0..8 {
        s.push_str(&format!("{:02x}", (v >> (8 * k)) & 0xff));
    }
    s
}

fn cmd_replay() -> i32 {
    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => return 1,
        };
        if line.trim().is_empty() {
            continue;
        }
        let (i, input) = match parse_i(&line) {
            Some(x) => x,
            None => return 1,
        };
        let v = crackme::core::core_verify(&input, crackme::core::clean_tweak);
        let p = crackme::core::core_probe(&input);
        out_json(&format!(
            "{{\"i\":{},\"verify\":{},\"probe\":\"{}\"}}",
            i, v, hex16(p)
        ));
    }
    0
}

fn cmd_selftest() -> i32 {
    let mut ok = true;
    // stock parameters must reproduce the FIPS-197 AES-128 vector
    let spn = crackme::core::Spn::new(&[0u8; 16], 1, 0, 0);
    let ct = spn.encrypt(&[0u8; 16]);
    let fips: Vec<u8> = (0u8..16)
        .map(|j| ct[j as usize])
        .collect();
    let want = [
        0x66u8, 0xe9, 0x4b, 0xd4, 0xef, 0x8a, 0x2c, 0x3b, 0x88, 0x4c, 0xfa,
        0x59, 0xca, 0x34, 0x2b, 0x2e,
    ];
    let fips_ok = fips == want;
    ok &= fips_ok;
    // sbox bijectivity at the graded seed
    let (sbox, inv) = crackme::core::build_sbox(
        crackme::core::sbox_a(crackme::core::SBOX_SEED),
        crackme::core::sbox_b(crackme::core::SBOX_SEED),
    );
    let mut seen = [false; 256];
    let mut bijective = true;
    for v in sbox.iter() {
        if seen[*v as usize] {
            bijective = false;
        }
        seen[*v as usize] = true;
    }
    for i in 0..256 {
        if inv[sbox[i] as usize] != i as u8 {
            bijective = false;
        }
    }
    ok &= bijective;
    // a minted valid license verifies 0; a one-byte mutation flips to 1
    let lic = crackme::core::mint_valid_license(16, 1 << 22);
    let lic = match lic {
        Some(l) => l,
        None => {
            out_json("{\"ok\":false,\"mint\":\"failed\"}");
            return 1;
        }
    };
    let v0 = crackme::core::core_verify(&lic, crackme::core::clean_tweak);
    let mut bad = lic.clone();
    let n = bad.len();
    bad[n - 1] ^= 0x01;
    let v1 = crackme::core::core_verify(&bad, crackme::core::clean_tweak);
    let mint_ok = v0 == 0 && v1 == 1;
    ok &= mint_ok;
    // decoy input verifies 0 through the stock lane
    let dec = crackme::core::mint_decoy_input(12, 1 << 22);
    let dec_ok = match dec {
        Some(d) => {
            crackme::core::core_verify(&d, crackme::core::clean_tweak) == 0
        }
        None => false,
    };
    ok &= dec_ok;
    out_json(&format!(
        "{{\"ok\":{},\"fips197_aes128\":{},\"sbox_bijective\":{},\"mint_valid_license\":{},\"decoy_fake_success\":{}}}",
        ok, fips_ok, bijective, mint_ok, dec_ok
    ));
    if ok {
        0
    } else {
        1
    }
}

fn cmd_mint() -> i32 {
    let lic = crackme::core::mint_valid_license(16, 1 << 24);
    let dec = crackme::core::mint_decoy_input(12, 1 << 24);
    match (lic, dec) {
        (Some(l), Some(d)) => {
            let lh: String =
                l.iter().map(|b| format!("{:02x}", b)).collect();
            let dh: String =
                d.iter().map(|b| format!("{:02x}", b)).collect();
            out_json(&format!(
                "{{\"valid_license_hex\":\"{}\",\"decoy_hex\":\"{}\"}}",
                lh, dh
            ));
            0
        }
        _ => {
            out_json("{\"error\":\"mint search failed\"}");
            1
        }
    }
}

fn cmd_determinism() -> i32 {
    let fixed: Vec<Vec<u8>> = vec![
        (0u8..32).collect(),
        (0u8..24).map(|j| 0xa5 ^ (j * 7)).collect(),
        vec![0x11; 8],
    ];
    let pass1: Vec<(i32, String)> = fixed
        .iter()
        .map(|inp| {
            (
                crackme::core::core_verify(
                    inp,
                    crackme::core::clean_tweak,
                ),
                hex16(crackme::core::core_probe(inp)),
            )
        })
        .collect();
    let pass2: Vec<(i32, String)> = fixed
        .iter()
        .map(|inp| {
            (
                crackme::core::core_verify(
                    inp,
                    crackme::core::clean_tweak,
                ),
                hex16(crackme::core::core_probe(inp)),
            )
        })
        .collect();
    let det = pass1 == pass2;
    out_json(&format!(
        "{{\"deterministic\":{},\"pass1_len\":{}}}",
        det,
        pass1.len()
    ));
    if det {
        0
    } else {
        1
    }
}

fn usage() -> i32 {
    eprintln!(
        "usage: crackme_host replay|selftest|mint|determinism  \
         (replay reads {{\"i\",\"input\"}} JSON lines on stdin)"
    );
    2
}

fn main() {
    let code = match std::env::args().nth(1).as_deref() {
        Some("replay") => cmd_replay(),
        Some("selftest") => cmd_selftest(),
        Some("mint") => cmd_mint(),
        Some("determinism") => cmd_determinism(),
        _ => usage(),
    };
    std::process::exit(code);
}
