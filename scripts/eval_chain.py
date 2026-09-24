#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_chain.py — the multi-layer decryption-chain tier (issue #370, eval-v1.4).

Owner directive 2026-09-24: the ladder's simple units pass by constant
lookup (zero discrimination). This tier mints units where the answer
sits behind 2-5 NESTED protection stages, each layer's output feeds the
next, pass requires peeling ALL layers, and every layer exposes a
mechanically checkable checkpoint (dense per-layer credit, scored by
scripts/eval_chain_grader.py).

Layer menu (mechanisms; a unit mixes >= 3 distinct):
  obfuscation       custom packer: encoded payload + string-table
                    loader + control-flattening (js/py), packed
                    field-blob (go) — the outer stage
  junk-code         花指令: opaque predicates + no-op forests INSIDE the
                    real code path; the naive decompile of the polluted
                    payload is visibly wrong; a strip restores clean
                    analysis (checkpoint class: junk-stripped)
  encrypted-config  the derivation parameters exist ONLY inside a
                    seeded stream-cipher blob; the blob key is derived
                    at RUNTIME from machine-fingerprint constants via
                    the ARX KDF — never a committed literal
  custom-cipher     ARX core with planted non-standard constants;
                    stock-crypto candidates fail every pair by
                    construction (the mod-crypto anti-standard rule)
  decoy-path        伪装层: a parallel, WORKING implementation with
                    plausible constants whose outputs are well-formed
                    garbage; branch selection keyed to a subtle
                    integrity/fingerprint fold (checkpoint class:
                    true-path-identified)
  anti-debug-gate   MD-3 discipline: a debugger/timing gate that
                    silently corrupts the derivation when tripped —
                    correct outputs only via bypass
  rotation/timer    L3: the core parameters rotate across request
                    lanes; the candidate must induce the cadence

Anti-shortcut construction (binding, the win-kdf-l1 lesson): runtime
keys are derived, never literals; answer constants exist only inside
the encrypted config; decoy constants and a honeypot key are planted;
and EVERY unit's manifest.json records the mint-time shortcut audit —
naive strings/constant scans re-run against the committed artifact must
FAIL to yield the answer (the deception-smoke gate applied to the whole
ladder). Mint refuses a unit whose audit would pass.

Grading: the final answer face reuses the mechanical replay machinery
(eval_checker, probes_for/expected_for here); the dense per-layer face
is eval_chain_grader.py over the analysis workspace's layer artifacts.

stdlib only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


import eval_targets as tg

_SCRIPTS = Path(__file__).resolve().parent
TIER = "chain"
EVAL_VERSION = "eval-v1.4"
SCHEMA_TASK = tg.SCHEMA_TASK
SCHEMA_GROUND_TRUTH = tg.SCHEMA_GROUND_TRUTH
SCHEMA_MANIFEST = "kunglao-eval-chain-manifest/1"
SCHEMA_SCORES = "kunglao-eval-chain-scores/1"

PUBLISHED_COUNT = 8
MINTED_COUNT = 8
ROTATION_LANES = 3

# layer-id vocabulary (the menu); checkpoint classes map onto these
L_OBFUSCATION = "obfuscation"
L_JUNK = "junk-code"
L_CONFIG = "encrypted-config"
L_CIPHER = "custom-cipher-core"
L_DECOY = "decoy-path"
L_GATE = "anti-debug-gate"

M32 = 0xFFFFFFFF


class ChainMintRefusal(RuntimeError):
    """A unit whose shortcut audit does not FAIL does not ship."""


# ------------------------------------------------------------------ ARX core
def _rotl(x: int, r: int) -> int:
    r &= 31
    if r == 0:
        return x & M32
    return ((x << r) | (x >> (32 - r))) & M32


def arx_permute(w: list[int], rc: list[int]) -> list[int]:
    """One 4-word ARX round. THE canonical rotation normalization, one
    for every face (model + js + py + go): r = (rc & 15) + 1 — never
    zero, so the data-dependent rotation face survives constant
    folding; the rendered tables carry the RAW rc words."""
    a, b, c, d = w
    a = (a + d) & M32
    b ^= _rotl(a, (rc[0] & 15) + 1)
    c = (c + b) & M32
    d ^= _rotl(c, (rc[1] & 15) + 1)
    a = (a + b) & M32
    c ^= _rotl(a, (rc[2] & 15) + 1)
    d = (d + c) & M32
    b ^= _rotl(d, (rc[3] & 15) + 1)
    return [a, b, c, d]


def _rc_lane(seed: int) -> list[list[int]]:
    """The planted round-constant table: 8 rounds x 4 rotation seeds.
    Committed as literals (they ARE the cipher constants an analyst
    restores) but seeded per unit — a memorized table is wrong here."""
    raw = [tg._u32(seed ^ 0xA11CE, 20 + i) for i in range(32)]
    return [raw[i * 4:(i + 1) * 4] for i in range(8)]


KDF_ROUNDS = 8
DRBG_ROUNDS = 6


def kdf_runtime(fp: list[int], salt: int, rc: list[list[int]]) -> bytes:
    """The runtime key derivation: ARX cascade over the machine
    fingerprint words + salt under the planted round-constant table.
    The RESULT never appears in any artifact (asserted at mint)."""
    w = [(fp[0] ^ rc[0][0]) | 1, fp[1] ^ rc[0][1], fp[2] ^ rc[0][2],
         salt ^ rc[0][3]]
    for r in range(KDF_ROUNDS):
        w = arx_permute(w, rc[r % len(rc)])
        w[r % 4] ^= (r + 1) * 0x2545F491 & M32
    return b"".join(x.to_bytes(4, "big") for x in w)


def drbg_block(key: bytes, counter: int, rc: list[list[int]]) -> bytes:
    """One 16-byte keystream block (ARX-DRBG): the stream-cipher face
    for the config blob. Custom by construction — no stock primitive
    reproduces it."""
    kw = [int.from_bytes(key[i * 4:i * 4 + 4], "big") for i in range(4)]
    w = [kw[0], kw[1], kw[2], kw[3] ^ counter]
    for r in range(DRBG_ROUNDS):
        w = arx_permute(w, rc[(r + 2) % len(rc)])
    return b"".join(x.to_bytes(4, "big") for x in w)


def stream_xor(key: bytes, data: bytes, rc: list[list[int]]) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        out += drbg_block(key, counter, rc)
        counter += 1
    return bytes(x ^ y for x, y in zip(data, out[:len(data)]))


def _words(key: bytes) -> list[int]:
    return [int.from_bytes(key[i * 4:i * 4 + 4], "big") for i in range(4)]


def chain_mac(key: bytes, data: bytes, rc: list[list[int]]) -> str:
    """The L1 answer face: ARX MAC keyed with the config-recovered key
    (16 hex chars). Absorb 4 bytes per round, squeeze two words."""
    w = _words(key)
    padded = data + b"\x80" + b"\x00" * ((-len(data) - 1) % 4)
    for off in range(0, len(padded), 4):
        chunk = int.from_bytes(padded[off:off + 4].ljust(4, b"\x00"), "big")
        w[0] ^= chunk
        w = arx_permute(w, rc[(off // 4) % len(rc)])
    w = arx_permute(w, rc[0])
    w = arx_permute(w, rc[1])
    return f"{(w[0] ^ w[2]):08x}{(w[1] ^ w[3]):08x}"


def chain_core(p: dict, data: bytes, lane: int = 0) -> str:
    """The L2/L3 answer face: the restored ARX core over the
    config-recovered parameter set. lane != 0 folds the rotation
    (L3): c0/c1 rotate per lane — the cadence must be induced."""
    c0, c1 = p["c0"], p["c1"]
    if lane:
        c0 ^= _rotl((p["odd"] * lane) & M32, 3)
        c1 = (c1 + lane * p["odd2"]) & M32
    a, b, acc = c0, c1, p["c2"]
    rot = p["rot"]
    odd = p["odd"]
    for byte in data:
        a = (a + byte) & M32
        a = _rotl(a ^ b, rot)
        b = (b + a) & M32
        acc ^= _rotl((a + acc) & M32, 3)
    h1 = (acc * odd) & M32
    h2 = (_rotl((h1 ^ b) & M32, 7) * odd) & M32
    return f"{h1:08x}{h2:08x}"


def decoy_core(p: dict, data: bytes, lane: int = 0) -> str:
    """The decoy branch: the SAME ARX shape over the decoy parameter
    set — a working decrypt whose outputs are well-formed garbage."""
    return chain_core(p, data, lane)


# ------------------------------------------------------------------ config
CONFIG_MAGIC = b"CF70"


def config_plain_for(blob: dict, cfg: dict) -> bytes:
    """The canonical config plaintext (digest-stable: sorted compact
    json + the magic envelope)."""
    body = json.dumps(blob, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return CONFIG_MAGIC + body


def encrypt_config(cfg: dict, blob: dict) -> str:
    """Seal one config blob under the runtime key (counter-mode ARX
    stream over the planted round-constant table)."""
    key = kdf_runtime(cfg["fp"], cfg["salt"], cfg["rc"])
    return stream_xor(key, config_plain_for(blob, cfg), cfg["rc"]).hex()


def decrypt_config(cfg: dict, hex_blob: str) -> dict:
    key = kdf_runtime(cfg["fp"], cfg["salt"], cfg["rc"])
    raw = stream_xor(key, bytes.fromhex(hex_blob), cfg["rc"])
    if not raw.startswith(CONFIG_MAGIC):
        raise ValueError("config magic mismatch")
    return json.loads(raw[len(CONFIG_MAGIC):].decode("utf-8"))


# ----------------------------------------------------------------- registry
FAMILIES: dict[str, dict] = {
    "chain-js": {
        "toolchain": "node", "language": "javascript", "ext": "js",
        "target": "target/chain_bundle.js",
        "candidate": "reference_candidate.js",
        "space_bits": 64,
        "seam": ("A Node module exporting derive(req) where req = "
                 "{payload: hex string, lane: int} -> 16-hex lowercase "
                 "string over the fully-peeled derivation."),
    },
    "chain-py": {
        "toolchain": "python3", "language": "python", "ext": "py",
        "target": "target/chain_bundle.py",
        "candidate": "reference_candidate.py",
        "space_bits": 64,
        "seam": ("A Python module exposing derive(payload_hex: str, "
                 "lane: int = 0) -> 16-hex lowercase string over the "
                 "fully-peeled derivation."),
    },
    "chain-go": {
        "toolchain": "go", "language": "go", "ext": "go",
        "target": "target/chain_bundle.go",
        "candidate": "reference_candidate.go",
        "space_bits": 64,
        "seam": ("A Go program reading one JSON object per line on "
                 "stdin ({\"i\": N, \"payload\": hex, \"lane\": R}) "
                 "and printing {\"i\": N, \"out\": hex} per line."),
    },
}

# gradient -> (layer ids, per-layer mechanisms)
_L1 = [(L_OBFUSCATION, ["obfuscation", "junk-code"]),
       (L_CONFIG, ["encrypted-config"])]
_L2 = [(L_OBFUSCATION, ["obfuscation", "junk-code"]),
       (L_CONFIG, ["encrypted-config"]),
       (L_CIPHER, ["custom-cipher-core"])]
_L3 = [(L_OBFUSCATION, ["obfuscation"]),
       (L_JUNK, ["junk-code"]),
       (L_CONFIG, ["encrypted-config"]),
       (L_CIPHER, ["custom-cipher-core", "decoy-path"]),
       (L_GATE, ["anti-debug-gate", "rotation-timer"])]

GRADIENT_LAYERS = {"L1": _L1, "L2": _L2, "L3": _L3}

UNITS: list[dict] = [
    {"task_id": "chain-l1-js-v1", "family": "chain-js", "seed": 37001,
     "gradient": "L1"},
    {"task_id": "chain-l1-py-v1", "family": "chain-py", "seed": 37002,
     "gradient": "L1"},
    {"task_id": "chain-l2-js-v1", "family": "chain-js", "seed": 37003,
     "gradient": "L2"},
    {"task_id": "chain-l2-py-v1", "family": "chain-py", "seed": 37004,
     "gradient": "L2"},
    {"task_id": "chain-l2-go-v1", "family": "chain-go", "seed": 37005,
     "gradient": "L2"},
    {"task_id": "chain-l3-js-v1", "family": "chain-js", "seed": 37006,
     "gradient": "L3"},
    {"task_id": "chain-l3-py-v1", "family": "chain-py", "seed": 37007,
     "gradient": "L3"},
]
UNIT_BY_ID = {u["task_id"]: u for u in UNITS}


def _payload_hex(seed: int, k: int) -> str:
    return ((_u32(seed, 80 + k) << 32)
            | _u32(seed ^ 0x5EED, 80 + k)).to_bytes(16, "big").hex()


def _u32(seed: int, lane: int) -> int:
    return tg._u32(seed, lane)


# -------------------------------------------------------------------- model
def derive_cfg(family: str, seed: int, gradient: str) -> dict:
    """Ground truth BY CONSTRUCTION: every parameter set, both config
    blobs, the runtime key, the gate and decoy faces — all minted from
    the seed. The runtime key is computed here and asserted ABSENT from
    every committed artifact at mint."""
    cfg: dict = {"seed": seed, "family": family, "gradient": gradient}
    cfg["rc"] = _rc_lane(seed)
    cfg["fp"] = [_u32(seed, 11), _u32(seed, 12), _u32(seed, 13)]
    cfg["salt"] = _u32(seed, 14)
    # hex face: cfg is JSON-serialized into ground truth
    cfg["rt_key"] = kdf_runtime(cfg["fp"], cfg["salt"],
                                cfg["rc"]).hex()
    cfg["honeypot"] = b"".join(
        _u32(seed ^ 0xB41D, 71 + i).to_bytes(4, "big")
        for i in range(8)).hex()
    cfg["corrupt"] = _u32(seed, 15)
    cfg["gate_dt_ms"] = 250 + (_u32(seed, 16) % 400)
    core = {"c0": _u32(seed, 21), "c1": _u32(seed, 22), "c2": _u32(seed, 23),
            "rot": 1 + (_u32(seed, 24) % 31), "odd": _u32(seed, 25) | 1,
            "odd2": _u32(seed, 26) | 1}
    decoy = {"c0": _u32(seed ^ 0xD09, 31), "c1": _u32(seed ^ 0xD09, 32),
             "c2": _u32(seed ^ 0xD09, 33), "rot": 1 + (_u32(seed, 34) % 31),
             "odd": _u32(seed ^ 0xD09, 35) | 1,
             "odd2": _u32(seed ^ 0xD09, 36) | 1}
    # the integrity fold: branch selection + gate trip face (L3)
    cfg["integ"] = _u32(seed, 41)
    cfg["sel_val"] = (cfg["fp"][0] ^ cfg["integ"]) & M32
    cfg["sel_key"] = cfg["sel_val"] & 0xFF
    config = {"v": 1, "core": core}
    if gradient == "L1":
        # sealed config-only material: derived from seed lanes the
        # payload NEVER carries, so the encrypted-config layer is
        # load-bearing (runtime key alone must not unlock the answer)
        config["mac_key"] = b"".join(
            _u32(seed, 91 + i).to_bytes(4, "big") for i in range(4)).hex()
    else:
        config["lanes"] = ROTATION_LANES
    if gradient == "L3":
        config["integ"] = f"{cfg['integ']:08x}"
        config["gate"] = {"dt_ms": cfg["gate_dt_ms"],
                          "corrupt": f"{cfg['corrupt']:08x}"}
    cfg["config"] = config
    cfg["decoy_config"] = {"v": 0, "core": decoy}
    if gradient == "L1":
        cfg["decoy_config"]["mac_key"] = b"".join(
            _u32(seed ^ 0xD09, 95 + i).to_bytes(4, "big")
            for i in range(4)).hex()
    return cfg


def _words_hex(key: bytes) -> str:
    return key.hex()


def model_out(cfg: dict, payload_hex: str, lane: int = 0) -> str:
    """The checker-side truth for one probe (the final derivation)."""
    if cfg["gradient"] == "L1":
        rc = cfg["rc"]
        return chain_mac(bytes.fromhex(cfg["config"]["mac_key"]),
                         bytes.fromhex(payload_hex), rc)
    return chain_core(cfg["config"]["core"], bytes.fromhex(payload_hex),
                      lane if cfg["gradient"] == "L3" else 0)


def decoy_out(cfg: dict, payload_hex: str, lane: int = 0) -> str:
    """The decoy-path answer: working, plausible, WRONG."""
    if cfg["gradient"] == "L1":
        return chain_mac(bytes.fromhex(cfg["decoy_config"]["mac_key"]),
                         bytes.fromhex(payload_hex), cfg["rc"])
    return decoy_core(cfg["decoy_config"]["core"],
                      bytes.fromhex(payload_hex),
                      lane if cfg["gradient"] == "L3" else 0)


def honeypot_out(cfg: dict, payload_hex: str) -> str:
    """The naive strings-scan answer: chain_mac keyed with the planted
    honeypot literal — the key the scan finds is exactly the wrong one."""
    return chain_mac(bytes.fromhex(cfg["honeypot"]),
                     bytes.fromhex(payload_hex), cfg["rc"])


def published_pairs(unit: dict) -> list[dict]:
    seed, family = unit["seed"], unit["family"]
    cfg = derive_cfg(family, seed, unit["gradient"])
    pairs = []
    for k in range(PUBLISHED_COUNT):
        payload = _payload_hex(0, k)
        lane = (k % ROTATION_LANES) if unit["gradient"] == "L3" else 0
        pairs.append({"i": k, "payload": payload, "lane": lane,
                      "out": model_out(cfg, payload, lane)})
    return pairs


def probes_for(gt: dict) -> list[dict]:
    """Published probes + checker-minted fresh-seed lanes (the
    anti-digest-table face; expected rows recomputed checker-side)."""
    unit = UNIT_BY_ID[gt["task_id"]]
    probes = [{"i": p["i"], "payload": p["payload"], "lane": p["lane"]}
              for p in gt["published_pairs"]]
    seed = gt["seed"] ^ 0x5EED
    for k in range(MINTED_COUNT):
        lane = ((k + 1) % ROTATION_LANES) if unit["gradient"] == "L3" else 0
        probes.append({"i": 100 + k, "payload": _payload_hex(seed, k),
                       "lane": lane})
    return probes


def expected_for(gt: dict, probes: list[dict]) -> dict[int, str]:
    cfg = gt["core"]
    return {p["i"]: model_out(cfg, p["payload"], p["lane"])
            for p in probes}


# ------------------------------------------------------- naive baselines
_PRINTABLE_RUN = re.compile(rb"[\x20-\x7e]{8,}")
# key-shaped literal: EXACTLY 64 hex chars quoted (the md discipline:
# the honeypot is minted to be the only such literal anywhere)
_HEX64 = re.compile(r"['\"]([0-9a-fA-F]{64})['\"]")


def naive_strings_scan(data: bytes) -> list[str]:
    """The scripted naive method, concretely: a strings-like printable
    run extraction, then the key-shaped literal grab (the first long
    hex string a naive analyst would key on)."""
    return [m.group(0).decode("latin1") for m in _PRINTABLE_RUN.finditer(data)]


def naive_key_hit(text: str) -> str | None:
    hits = _HEX64.search(text)
    return hits.group(1).lower() if hits else None


def constant_scan(text: str, values: list[int]) -> list[int]:
    """Which of the integer values appear in the text as literals:
    0x-prefixed hex (padded and unpadded) or, for wide values, a
    word-boundary-delimited decimal (bare decimal substrings collide
    with ordinary numeric text; values below a byte have no distinctive
    literal face and are never reported)."""
    found = []
    for v in values:
        if v < 0x100:
            continue
        if f"0x{v:08x}" in text.lower() or f"0x{v:x}" in text.lower():
            found.append(v)
            continue
        if v >= 0x10000 and re.search(rf"(?<![0-9a-fA-F]){v}(?![0-9a-fA-F])",
                                      text):
            found.append(v)
    return found


def answer_literals(cfg: dict) -> list[str]:
    """The bare hex STRING literals that shortcut the answer if they
    ever appear (the runtime key and the sealed config keys — these are
    32-hex strings, invisible to the 0x-prefixed constant scan and
    below the 64-hex key-shaped threshold)."""
    # NOTE: the DECOY key material is deliberately absent — it is
    # planted bait, its visibility is the trap (recorded in the audit)
    lits = [cfg["rt_key"]]
    mk = cfg["config"].get("mac_key")
    if mk:
        lits.append(mk)
    return [v.lower() for v in lits]


def answer_constants(cfg: dict) -> list[int]:
    """The constants that shortcut the ANSWER if they ever appear as
    literals (they must not): the core parameter set, the sealed mac
    key words, the runtime key words. Route/gate material (INTEG,
    CORRUPT) is deliberately EXCLUDED — it is visible by design: the
    analyst must find and cite it (the true-path/gate checkpoints)."""
    vals: list[int] = []
    core = cfg["config"].get("core", {})
    vals += [v for v in core.values() if isinstance(v, int)]
    mk = cfg["config"].get("mac_key")
    if mk:
        vals += [int(mk[i:i + 8], 16) for i in range(0, len(mk), 8)]
    vals += list(_words(bytes.fromhex(cfg["rt_key"])))
    return vals
