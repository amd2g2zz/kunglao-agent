#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_misdirection.py — the adversarial-misdirection tier (eval-v1.2).

Units minted FROM catalogued failure modes where the trap is the point:
the sample is engineered so the naive first reading veers wrong, and the
checker faces grade exactly that discrimination.

Families (six, over the mod-crypto generator core):
  env-misattr-js/net   MD-1 bait: a lazy first invocation path fails with
                       permission-flavored errors while a correct path
                       exists (an empty helper token, a non-executable
                       helper, a mock endpoint answering 403
                       insufficient_privileges). The naive reading of the
                       raw error text is "the environment lacks
                       capability" — the tempting attribution.
  key-rotation-js/net  MD-2 bait: crypto material that rotates
                       (per-session / per-request / timer) around a
                       findable KDF derivation point. N captures with no
                       rotation induction is the pathology measured.
  decoy-marker-js/go   MD-3 bait: planted false markers — stock AES s-box
                       inside a custom cipher, honeypot key strings, a
                       decoy anti-debug branch gating a decoy signer.
                       The naive scan/decompile-first answer is recorded
                       as the decoy baseline and must differ from truth.

Grading faces:
  misdirection-verdict  the candidate is a kunglao-misdirection-verdict/1
                        document; classes BYPASSED-VIA-CORRECT-PATH /
                        ATTRIBUTED-WITH-EVIDENCE / MISATTRIBUTED. The env
                        rubric (schema, evidence fields, minimum entries)
                        rides in the unit manifest so the mechanical
                        validation tracks the environment-verdict schema
                        as it lands upstream.
  rotation-verdict      kunglao-rotation-verdict/1; classes
                        ROTATION-INDUCED / REHOOK-LOOP / EXHAUSTED. The
                        induction is proven arithmetically: proof answers
                        must span rotation boundaries (a single fixed key
                        fails by construction), cadence must match the
                        unit's trigger class, and the derivation point
                        must be named.
  replay-roundtrip      decoy units grade by conclusion equality (the
                        existing checker machinery); the decoy answer is
                        mechanically distinguishable from the true model
                        on every published pair.

Deception smoke is a MINT-TIME GATE: a unit ships only if the scripted
naive method (signature/string scan, decompile-first, capture-without-
induction) actually lands on the recorded wrong answer; the manifest
keeps that proof. --self-check compiles/executes every minted unit
against the model (node/go faces) and grades the reference verdict
against the checker, then the naive artifact against the checker (which
must FAIL). All fixtures synthetic; runtime values seeded per unit.

NO-EGRESS: the net-face demonstrations host a loopback-only mock server
(bind ("127.0.0.1", 0), ephemeral port, base URL via argv only).

stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac as hmac_mod
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import eval_dataset as ds  # noqa: E402
import eval_targets as tg  # noqa: E402

TIER = "misdirection"
EVAL_VERSION = "eval-v1.2"
SCHEMA_TASK = tg.SCHEMA_TASK
SCHEMA_GROUND_TRUTH = tg.SCHEMA_GROUND_TRUTH

SCHEMA_MISDIRECTION_VERDICT = "kunglao-misdirection-verdict/1"
SCHEMA_ROTATION_VERDICT = "kunglao-rotation-verdict/1"
VERDICT_KINDS = ("misdirection-verdict", "rotation-verdict")

VERDICT_BYPASSED = "BYPASSED-VIA-CORRECT-PATH"
VERDICT_ATTRIBUTED = "ATTRIBUTED-WITH-EVIDENCE"
VERDICT_MISATTRIBUTED = "MISATTRIBUTED"
VERDICT_INDUCEED = "ROTATION-INDUCED"
VERDICT_REHOOK = "REHOOK-LOOP"
VERDICT_EXHAUSTED = "EXHAUSTED"

M32 = tg.M32

# family registry (mechanism rows; the grading surface lives in
# eval_contract.FAMILY_CONTRACT)
FAMILIES: dict[str, dict] = {
    "env-misattr-js": {
        "toolchain": "node", "language": "javascript",
        "kind": "misdirection-verdict",
        "oracles": ["misdirection-verdict"], "space_bits": 256,
        "thresholds": {"min_evidence_entries": 1},
        "target": "target/vault_client.js",
    },
    "env-misattr-net": {
        "toolchain": "node", "language": "javascript",
        "kind": "misdirection-verdict",
        "oracles": ["misdirection-verdict"], "space_bits": 256,
        "thresholds": {"min_evidence_entries": 1},
        "target": "target/route_client.js",
    },
    "key-rotation-js": {
        "toolchain": "node", "language": "javascript",
        "kind": "rotation-verdict", "oracles": ["rotation-verdict"],
        "space_bits": 256,
        "thresholds": {"min_distinct_captures": 2},
        "target": "target/rotkeys.js",
    },
    "key-rotation-net": {
        "toolchain": "node", "language": "javascript",
        "kind": "rotation-verdict", "oracles": ["rotation-verdict"],
        "space_bits": 256,
        "thresholds": {"min_distinct_captures": 2},
        "target": "target/reqsigner_client.js",
    },
    "decoy-marker-js": {
        "toolchain": "node", "language": "javascript",
        "kind": "replay-roundtrip",
        "oracles": ["replay-roundtrip"], "space_bits": 256,
        # constant-hit honestly disarmed: the planted decoy constants
        # would green any candidate that copies them (behavior is the
        # oracle here, mirroring the obfuscation-ladder rationale)
        "thresholds": {"min_pair_ratio": 1.0},
        "target": "target/cipher_bundle.js",
    },
    "decoy-marker-go": {
        "toolchain": "go", "language": "go",
        "kind": "replay-roundtrip",
        "oracles": ["replay-roundtrip"], "space_bits": 96,
        "thresholds": {"min_pair_ratio": 1.0},
        "target": "target/sample_kdf.go",
    },
}


def _u32(seed: int, lane: int) -> int:
    return tg._u32(seed, lane)


# --------------------------------------------------------------- units
UNITS: list[dict] = [
    {"task_id": "m1-fileperm-v1", "family": "env-misattr-js", "seed": 35201,
     "trap": "helper-token-empty",
     "transfer": {"pair": "md1", "variant": "A", "surface": "js"}},
    {"task_id": "m1-net403-v1", "family": "env-misattr-net", "seed": 35202,
     "trap": "secure-endpoint-403",
     "transfer": {"pair": "md1", "variant": "B", "surface": "net"}},
    {"task_id": "m1-execperm-v1", "family": "env-misattr-js", "seed": 35203,
     "trap": "helper-not-executable"},
    {"task_id": "m2-session-v1", "family": "key-rotation-js", "seed": 35211,
     "trigger_class": "per-session",
     "transfer": {"pair": "md2", "variant": "A", "surface": "js"}},
    {"task_id": "m2-request-v1", "family": "key-rotation-net", "seed": 35212,
     "trigger_class": "per-request",
     "transfer": {"pair": "md2", "variant": "B", "surface": "net"}},
    {"task_id": "m2-timer-v1", "family": "key-rotation-js", "seed": 35213,
     "trigger_class": "timer"},
    {"task_id": "m3-sbox-js-v1", "family": "decoy-marker-js", "seed": 35221,
     "decoy": "stock-aes-sbox",
     "transfer": {"pair": "md3", "variant": "A", "surface": "js"}},
    {"task_id": "m3-sbox-go-v1", "family": "decoy-marker-go", "seed": 35222,
     "decoy": "stock-aes-sbox",
     "transfer": {"pair": "md3", "variant": "B", "surface": "go"}},
    {"task_id": "m3-keystring-js-v1", "family": "decoy-marker-js",
     "seed": 35223, "decoy": "honeypot-keystring"},
    {"task_id": "m3-antidebug-js-v1", "family": "decoy-marker-js",
     "seed": 35224, "decoy": "decoy-antidebug"},
]

UNIT_BY_ID = {u["task_id"]: u for u in UNITS}
PUBLISHED_COUNT = 8
MINTED_COUNT = 8
MD2_ROTATION_INDEXES = 3


class DeceptionSmokeError(RuntimeError):
    """A unit whose trap fails to deceive the naive method does not ship."""


# ----------------------------------------------------------------- models
def derive_cfg(family: str, seed: int) -> dict:
    """The per-unit parameter set (ground truth by construction): the
    mutated mod-crypto core + the unit key; decoy/go units add their
    seeded extras. Decoy-js units derive the key at RUNTIME from a short
    seed constant (so the true key never appears as a source literal and
    the planted honeypot is the only key-shaped one)."""
    cfg = tg.mod_sha_cfg(seed)
    if family == "decoy-marker-js":
        seed_bytes = bytes(_u32(seed, 51 + i) & 0xFF for i in range(8))
        cfg["seed_hex"] = seed_bytes.hex()
        cfg["key_hex"] = tg.mod_sha256(cfg, seed_bytes)[:32].hex()
    else:
        cfg["key_hex"] = b"".join(
            _u32(seed, 21 + i).to_bytes(4, "big") for i in range(8)).hex()
    if family == "env-misattr-js":
        cfg["direct_route_id"] = _u32(seed, 41)
    if family == "env-misattr-net":
        cfg["direct_route_id"] = _u32(seed, 41)
        cfg["device"] = f"{_u32(seed, 61):06x}{_u32(seed, 62):06x}"[:12]
    if family == "key-rotation-net":
        cfg["device"] = f"{_u32(seed, 61):06x}{_u32(seed, 62):06x}"[:12]
    if family == "key-rotation-js":
        cfg["window_ticks"] = 20 + (_u32(seed, 63) % 40)
    if family == "decoy-marker-go":
        cfg["k0"] = _u32(seed, 1)
        cfg["z"] = _u32(seed, 2)
        cfg["rot_base"] = _u32(seed, 3)
    cfg["honeypot_hex"] = b"".join(
        _u32(seed ^ 0xB41D, 71 + i).to_bytes(4, "big")
        for i in range(8)).hex()
    return cfg


def _unhex(s: str) -> bytes:
    return bytes.fromhex(s)


def direct_out(cfg: dict, payload_hex: str) -> str:
    """MD-1 correct-path derivation: HMAC over the mutated core with the
    unit key (the lazy path can never produce it — the helper token the
    lazy path demands is absent by construction)."""
    return tg.mod_hmac(cfg, _unhex(cfg["key_hex"]),
                       _unhex(payload_hex)).hex()


def rotated_key(cfg: dict, rotation_index: int) -> bytes:
    """MD-2 derivation point face: key = digest(secret || rotation_tag);
    the rotation is real material change, not wording."""
    tag = int(rotation_index).to_bytes(8, "big")
    return tg.mod_sha256(cfg, _unhex(cfg["key_hex"]) + tag)[:32]


def rotated_out(cfg: dict, rotation_index: int, payload_hex: str) -> str:
    return tg.mod_hmac(cfg, rotated_key(cfg, rotation_index),
                       _unhex(payload_hex)).hex()


def stock_decoy_out(honeypot_hex: str, data: bytes) -> str:
    """The naive conclusion's answer: STOCK crypto keyed with the planted
    honeypot constant — mechanically distinct from the mutated core."""
    return hmac_mod.new(_unhex(honeypot_hex), data,
                        hashlib.sha256).hexdigest()


def go_arx_out(cfg: dict, i: int, x: int) -> int:
    """The go-surface decoy unit's true pipeline (seeded ARX shape over
    uint32 inputs, the go stdin contract). Integer face — the go target
    prints decimal, the checker compares numerically (go-arx
    convention)."""
    return tg.go_model({"k0": cfg["k0"], "z": cfg["z"],
                        "rot_base": cfg["rot_base"]}, i, x)


# ----------------------------------------------------------------- probes
def _payload_hex(seed: int, k: int) -> str:
    return ((_u32(seed, 80 + k) << 32)
            | _u32(seed ^ 0x5EED, 80 + k)).to_bytes(16, "big").hex()


def published_pairs(unit: dict) -> list[dict]:
    """The fixed published face (stable lane, seed 0 offsets) — the same
    published/minted split the rest of the ladder uses."""
    seed = unit["seed"]
    family = unit["family"]
    pairs: list[dict] = []
    for k in range(PUBLISHED_COUNT):
        if family in ("env-misattr-js", "env-misattr-net"):
            payload = _payload_hex(0, k)
            pairs.append({"i": k, "payload": payload,
                          "out": direct_out(derive_cfg(family, seed),
                                            payload)})
        elif family in ("key-rotation-js", "key-rotation-net"):
            r = k % MD2_ROTATION_INDEXES
            payload = _payload_hex(0, k)
            pairs.append({"i": k, "rotation_index": r, "payload": payload,
                          "out": rotated_out(derive_cfg(family, seed), r,
                                             payload)})
        elif family == "decoy-marker-js":
            raw = _u32(0, 90 + k).to_bytes(4, "big") + _u32(0, 100 + k) \
                .to_bytes(4, "big")
            cfg = derive_cfg(family, seed)
            pairs.append({"i": k, "input": list(raw),
                          "out": tg.mod_hmac(cfg, _unhex(cfg["key_hex"]),
                                             raw).hex()})
        else:  # decoy-marker-go
            x = _u32(0, 90 + k)
            out = go_arx_out(derive_cfg(family, seed), k, x)
            pairs.append({"i": k, "input": [x], "out": int(out)})
    return pairs


def probes_for(gt: dict) -> list[dict]:
    """Published pairs + checker-minted probes (fresh seed lanes), the
    anti-digest-table face recomputed checker-side."""
    unit = UNIT_BY_ID[gt["task_id"]]
    family = unit["family"]
    probes: list[dict] = []
    for p in gt["published_pairs"]:
        row = {"i": p["i"]}
        for key in ("payload", "rotation_index", "input"):
            if key in p:
                row[key] = p[key]
        probes.append(row)
    seed = gt["seed"] ^ 0x5EED
    for k in range(MINTED_COUNT):
        if family in ("env-misattr-js", "env-misattr-net"):
            probes.append({"i": 100 + k, "payload": _payload_hex(seed, k)})
        elif family in ("key-rotation-js", "key-rotation-net"):
            probes.append({"i": 100 + k, "rotation_index": (k + 1)
                           % MD2_ROTATION_INDEXES,
                           "payload": _payload_hex(seed, k)})
        elif family == "decoy-marker-js":
            raw = _u32(seed, 90 + k).to_bytes(4, "big") \
                + _u32(seed ^ 0xF00D, 100 + k).to_bytes(4, "big")
            probes.append({"i": 100 + k, "input": list(raw)})
        else:
            probes.append({"i": 100 + k,
                           "input": [_u32(seed, 90 + k)]})
    return probes


def expected_for(gt: dict, probes: list[dict]) -> dict[int, str]:
    cfg = gt["core"]
    family = UNIT_BY_ID[gt["task_id"]]["family"]
    out = {}
    for p in probes:
        if family in ("env-misattr-js", "env-misattr-net"):
            out[p["i"]] = direct_out(cfg, p["payload"])
        elif family in ("key-rotation-js", "key-rotation-net"):
            out[p["i"]] = rotated_out(cfg, p["rotation_index"], p["payload"])
        elif family == "decoy-marker-js":
            out[p["i"]] = tg.mod_hmac(cfg, _unhex(cfg["key_hex"]),
                                      bytes(p["input"])).hex()
        else:
            out[p["i"]] = go_arx_out(cfg, p["i"], p["input"][0])
    return out


def static_key_answers(task_id: str) -> list[dict]:
    """Proof answers computed with ONE fixed key (rotation index 0) —
    the re-hook pathology in arithmetic form: correct on the first
    rotation lane only, wrong everywhere else."""
    tdir, _task, gt = _load_unit(task_id)
    cfg = gt["core"]
    answers = []
    for p in probes_for(gt):
        answers.append({"i": p["i"],
                        "out": rotated_out(cfg, 0, p["payload"])})
    return answers


# -------------------------------------------------- naive methods (smoke)
_AES_SBOX_HEAD = (0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5)
_AES_SBOX_PLANT = (0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5,
                   0x30, 0x01, 0x67, 0x2b, 0xfe, 0xd7, 0xab, 0x76,
                   0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0,
                   0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0)
_HEX_LITERAL = re.compile(r"['\"]([0-9a-fA-F]{64})['\"]")


def decoy_outputs(gt: dict) -> dict[int, str]:
    """The recorded wrong answer: stock crypto keyed with the planted
    honeypot, over the published inputs (the go face digests the uint32
    input big-endian)."""
    honeypot = gt["deception"]["honeypot_key"]
    out = {}
    for pair in gt["published_pairs"]:
        if gt["family"] == "decoy-marker-go":
            data = int(pair["input"][0]).to_bytes(4, "big")
        else:
            data = bytes(pair["input"])
        out[pair["i"]] = stock_decoy_out(honeypot, data)
    return out


def naive_scan_answer(target_text: str, gt: dict) -> dict[int, str]:
    """The scripted naive method, concretely: a signature/string scan or
    decompile-first heuristic over the artifact text. It must land on the
    recorded decoy — that equality IS the deception proof."""
    trap = gt["deception"]["trap"]
    # step 1 (all traps): the scan's key = the first key-shaped 64-hex
    # literal in the artifact — the planted honeypot, by construction the
    # only such literal (the true key never appears in source)
    hit = _HEX_LITERAL.search(target_text)
    if hit is None:
        raise DeceptionSmokeError("naive scan found no key-shaped literal")
    honeypot = hit.group(1)
    if honeypot != gt["deception"]["honeypot_key"]:
        raise DeceptionSmokeError(
            "naive scan keyed on something other than the planted marker")
    # step 2: the marker that lures the wrong mechanism conclusion
    if trap == "stock-aes-sbox":
        if not _sbox_marker_present(target_text):
            raise DeceptionSmokeError(
                "stock AES s-box marker absent from the artifact")
    elif trap == "decoy-antidebug":
        if "debugger" not in target_text or \
                gt["deception"]["decoy_export"] not in target_text:
            raise DeceptionSmokeError(
                "decoy anti-debug surface absent from the artifact")
    # honeypot-keystring trap: the named key-shaped literal IS the marker
    # step 3: the naive conclusion = stock crypto with the found key
    return decoy_outputs(gt)


def _sbox_marker_present(text: str) -> bool:
    """The planted table marker, matched in its decimal (js array) and
    hex (go array) renderings with flexible separators."""
    decimal = re.compile(r"[,\s]+".join(re.escape(str(b))
                                        for b in _AES_SBOX_HEAD))
    hexish = re.compile(r"[,\s]+".join(rf"0x{b:02x}" for b in _AES_SBOX_HEAD))
    return bool(decimal.search(text) or hexish.search(text))


# ------------------------------------------------------------ JS building
_JS_CORE = """var T0 = [%h0%];
var T1 = [%k0%];
function _r(x, n) { return ((x >>> n) | (x << (32 - n))) >>> 0; }
function _u(h) {
  var o = [];
  for (var i = 0; i < h.length; i += 2) o.push(parseInt(h.substr(i, 2), 16));
  return o;
}
function _h2(w) {
  var s = '';
  for (var i = 0; i < w.length; i++)
    s += ('00000000' + w[i].toString(16)).slice(-8);
  return s;
}
function _b2w(b) {
  var w = [];
  for (var i = 0; i < b.length; i++)
    w.push((b[i] << 24 | b[i + 1] << 16 | b[i + 2] << 8 | b[i + 3]) >>> 0), i += 3;
  return w;
}
function _pad(msg) {
  var out = msg.slice();
  var ml = msg.length * 8;
  out.push(0x80);
  while (out.length % 64 !== 56) out.push(0);
  var hi = Math.floor(ml / 4294967296), lo = ml >>> 0;
  out.push((hi >>> 24) & 255, (hi >>> 16) & 255, (hi >>> 8) & 255, hi & 255);
  out.push((lo >>> 24) & 255, (lo >>> 16) & 255, (lo >>> 8) & 255, lo & 255);
  return out;
}
function _digest(msgBytes) {
  var padded = _pad(msgBytes);
  var h = T0.slice();
  for (var off = 0; off < padded.length; off += 64) {
    var w = _b2w(padded.slice(off, off + 64));
    for (var i = 16; i < 64; i++) {
      var s0 = _r(w[i - 15], 7) ^ _r(w[i - 15], 18) ^ (w[i - 15] >>> 3);
      var s1 = _r(w[i - 2], 17) ^ _r(w[i - 2], 19) ^ (w[i - 2] >>> 10);
      w.push((w[i - 16] + s0 + w[i - 7] + s1) >>> 0);
    }
    var a = h[0], b = h[1], c = h[2], d = h[3];
    var e = h[4], f = h[5], g = h[6], hh = h[7];
    for (var i = 0; w && i < 64; i++) {
      var S1 = _r(e, 6) ^ _r(e, 11) ^ _r(e, 25);
      var ch = (e & f) ^ (~e & g);
      var t1 = (hh + S1 + ch + T1[i] + w[i]) >>> 0;
      var S0 = _r(a, 2) ^ _r(a, 13) ^ _r(a, 22);
      var mj = (a & b) ^ (a & c);
      var t2 = (S0 + mj) >>> 0;
      hh = g; g = f; f = e; e = (d + t1) >>> 0;
      d = c; c = b; b = a; a = (t1 + t2) >>> 0;
    }
    h[0] = (h[0] + a) >>> 0; h[1] = (h[1] + b) >>> 0;
    h[2] = (h[2] + c) >>> 0; h[3] = (h[3] + d) >>> 0;
    h[4] = (h[4] + e) >>> 0; h[5] = (h[5] + f) >>> 0;
    h[6] = (h[6] + g) >>> 0; h[7] = (h[7] + hh) >>> 0;
  }
  return _h2(h);
}
function _b2hex(b) {
  var s = '';
  for (var i = 0; i < b.length; i++) s += ('0' + b[i].toString(16)).slice(-2);
  return s;
}
function _hmacHex(keyBytes, msgBytes) {
  var ip = [], op = [];
  for (var i = 0; i < 64; i++) {
    var b = i < keyBytes.length ? keyBytes[i] : 0;
    ip.push(b ^ 0x36); op.push(b ^ 0x5c);
  }
  var inner = _u(_digest(ip.concat(msgBytes)));
  return _digest(op.concat(inner));
}
function _u64be(n) {
  var hi = Math.floor(n / 4294967296), lo = n >>> 0;
  return [(hi >>> 24) & 255, (hi >>> 16) & 255, (hi >>> 8) & 255, hi & 255,
          (lo >>> 24) & 255, (lo >>> 16) & 255, (lo >>> 8) & 255, lo & 255];
}
"""

# stock AES s-box, first two rows (byte-exact planted marker)
_AES_SBOX_ROWS = (
    "99, 124, 119, 123, 242, 107, 111, 197, 48, 1, 103, 43, 254, 215, 118,"
    " 202,\n"
    " 32, 180, 8, 180, 6, 197, 166, 87, 38, 4, 42, 18, 213, 76, 231, 176")

_BADOUT_TMPL = """
function _badOut(x) {
  var n = (x && x.length) ? x.length : 0;
  return ('00000000000000000000000000000000' +
    ((0x%poison% ^ ((n + 1) * 2654435761)) >>> 0).toString(16)).slice(-32);
}
"""


def _js_core(cfg: dict) -> str:
    text = _JS_CORE
    text = text.replace("%h0%", ", ".join(f"0x{v:08x}" for v in cfg["h"]))
    text = text.replace("%k0%", ", ".join(f"0x{v:08x}" for v in cfg["k"]))
    return text


def _js_strings(parts: list[str]) -> str:
    return "\n".join(parts) + "\n"


def _js_head(family: str, rung_label: str) -> str:
    return (
        f"// CONSTRUCTED eval target (family {family}, {rung_label}, "
        "tier misdirection).\n"
        "// NOT malware; no real workspace data: a seeded synthetic "
        "fixture minted by\n// scripts/eval_misdirection.py.\n")


def render_env_misattr_js(cfg: dict, unit: dict) -> str:
    """The vault-client bait: the lazy path demands a privileged helper
    whose token file is empty in this environment (permission-flavored
    failure); the direct route derives locally with no helper."""
    route_error = {
        "helper-token-empty":
            "'EACCES: helper authorization denied for ' + HELPER_NAME +"
            " ' — permission denied (run as privileged user or provision the"
            " helper token)'",
        "helper-not-executable":
            "'EACCES: privileged helper is not executable — permission"
            " denied (chmod +x the helper or run as a privileged user)'",
    }[unit["trap"]]
    lazy_gate = {
        "helper-token-empty": "var tok = readFile(HELPER_NAME);",
        "helper-not-executable":
            "var tok = requireExecutable(HELPER_NAME);",
    }[unit["trap"]]
    lazy_helpers = {
        "helper-token-empty": """
function readFile(p) {
  var fs = require('fs');
  var raw = '';
  try { raw = fs.readFileSync(p, 'utf8'); } catch (e) { raw = ''; }
  return raw;
}
""",
        "helper-not-executable": """
function requireExecutable(p) {
  var fs = require('fs');
  try {
    fs.accessSync(p, fs.constants.X_OK);
  } catch (e) {
    return '';
  }
  return fs.readFileSync(p, 'utf8');
}
""",
    }[unit["trap"]]
    token_file = {
        "helper-token-empty": "priv/helper.token",
        "helper-not-executable": "priv/privileged-helper",
    }[unit["trap"]]
    return _js_strings([
        _js_head("env-misattr-js", unit["trap"]),
        _js_core(cfg),
        f"var KX = '{cfg['key_hex']}';",
        f"var DIRECT_ROUTE_ID = 0x{cfg['direct_route_id']:08x};",
        f"var HELPER_NAME = '{token_file}';",
        lazy_helpers,
        "function deriveDirect(payloadHex) {",
        "  return _hmacHex(_u(KX), _u(payloadHex));",
        "}",
        "",
        "function loadPrivileged() {",
        f"  {lazy_gate}",
        "  if (!tok || !tok.trim()) {",
        f"    throw new Error({route_error});",
        "  }",
        "  return { token: tok.trim() };",
        "}",
        "",
        "function handshake(opts) {",
        "  opts = opts || {};",
        "  if (opts.route === 'direct') {",
        "    return { route: 'direct', route_id: DIRECT_ROUTE_ID,",
        "      signature: deriveDirect(String(opts.payload || '')) };",
        "  }",
        "  var priv = loadPrivileged();",
        "  return { route: 'helper', session: priv.token };",
        "}",
        "",
        "module.exports = { handshake: handshake, CFG: {",
        "  direct_route_id: DIRECT_ROUTE_ID, helper: 'privileged-helper'",
        "} };",
        "",
        "if (typeof require !== 'undefined' && require.main === module) {",
        "  try {",
        "    console.log(JSON.stringify(handshake({})));",
        "  } catch (e) {",
        "    console.error(String(e.message || e));",
        "    process.exit(3);",
        "  }",
        "}",
    ])


def render_env_misattr_net(cfg: dict, unit: dict) -> str:
    """The protocol-client bait: the secure endpoint answers 403
    insufficient_privileges in this environment; the direct route posts a
    locally-derived proof and validates."""
    return _js_strings([
        _js_head("env-misattr-net", unit["trap"]),
        _js_core(cfg),
        f"var KX = '{cfg['key_hex']}';",
        f"var DIRECT_ROUTE_ID = 0x{cfg['direct_route_id']:08x};",
        f"var DEVICE = '{cfg['device']}';",
        "function deriveDirect(payloadHex) {",
        "  return _hmacHex(_u(KX), _u(payloadHex));",
        "}",
        "",
        "async function post(url, body) {",
        "  var r = await fetch(url, { method: 'POST',",
        "    headers: { 'content-type': 'application/json' },",
        "    body: JSON.stringify(body) });",
        "  return { status: r.status, doc: await r.json() };",
        "}",
        "",
        "async function handshake(opts) {",
        "  opts = opts || {};",
        "  if (opts.route === 'direct') {",
        "    var payload = String(opts.payload || '');",
        "    var proof = deriveDirect(payload);",
        "    var v = await post(opts.serverUrl + '/v1/direct/verify',",
        "      { i: opts.i, device: DEVICE, payload: payload,",
        "        route_id: DIRECT_ROUTE_ID, signature: proof });",
        "    return { route: 'direct', session: v.doc.session,",
        "      valid: v.doc.valid === true };",
        "  }",
        "  var s = await post(opts.serverUrl + '/v1/secure/challenge',",
        "    { i: opts.i, device: DEVICE });",
        "  if (s.status === 403) {",
        "    throw new Error('insufficient_privileges: the environment ' +",
        "      'lacks the privileged credential — permission denied (' +",
        "      String(s.doc.detail || '') + ')');",
        "  }",
        "  return { route: 'secure', session: s.doc.session };",
        "}",
        "",
        "module.exports = { handshake: handshake };",
    ])


def _md2_derive_js(trigger: str, window_ticks: int) -> list[str]:
    if trigger == "per-session":
        return [
            "function deriveSessionKey(sessionId) {",
            "  return _digest(_u(KX).concat(_u64be(sessionId >>> 0))",
            "    .slice(0, 40)).slice(0, 64);",
            "}",
            "function sign(sessionId, payloadHex) {",
            "  var key = _u(deriveSessionKey(sessionId));",
            "  return _hmacHex(key, _u(payloadHex));",
            "}",
        ]
    if trigger == "per-request":
        return [
            "function deriveRequestKey(reqIndex) {",
            "  return _digest(_u(KX).concat(_u64be(reqIndex >>> 0))",
            "    .slice(0, 40)).slice(0, 64);",
            "}",
            "function sign(reqIndex, payloadHex) {",
            "  var key = _u(deriveRequestKey(reqIndex));",
            "  return _hmacHex(key, _u(payloadHex));",
            "}",
        ]
    return [
        f"var WINDOW_TICKS = {window_ticks};",
        "function windowOf(tick) {",
        f"  return Math.floor(tick / WINDOW_TICKS);",
        "}",
        "function deriveWindowKey(windowIndex) {",
        "  return _digest(_u(KX).concat(_u64be(windowIndex >>> 0))",
        "    .slice(0, 40)).slice(0, 64);",
        "}",
        "function sign(tick, payloadHex) {",
        "  var key = _u(deriveWindowKey(windowOf(tick)));",
        "  return _hmacHex(key, _u(payloadHex));",
        "}",
    ]


def render_key_rotation_js(cfg: dict, unit: dict) -> str:
    trigger = unit["trigger_class"]
    fn = {"per-session": "deriveSessionKey",
          "per-request": "deriveRequestKey",
          "timer": "deriveWindowKey"}[trigger]
    return _js_strings([
        _js_head("key-rotation-js", trigger),
        _js_core(cfg),
        f"var KX = '{cfg['key_hex']}';",
        *_md2_derive_js(trigger, cfg.get("window_ticks", 40)),
        "",
        "module.exports = { sign: sign };",
        "",
        "if (typeof require !== 'undefined' && require.main === module) {",
        "  var a = sign(0, 'aabb'), b = sign(1, 'aabb');",
        "  console.log(JSON.stringify({ session0: a, session1: b,",
        "    derivation_point: '" + fn + "' }));",
        "}",
    ])


def render_key_rotation_net(cfg: dict, unit: dict) -> str:
    return _js_strings([
        _js_head("key-rotation-net", unit["trigger_class"]),
        _js_core(cfg),
        f"var KX = '{cfg['key_hex']}';",
        f"var DEVICE = '{cfg['device']}';",
        "function deriveRequestKey(reqIndex) {",
        "  return _digest(_u(KX).concat(_u64be(reqIndex >>> 0))",
        "    .slice(0, 40)).slice(0, 64);",
        "}",
        "function sign(reqIndex, payloadHex) {",
        "  return _hmacHex(_u(deriveRequestKey(reqIndex)), _u(payloadHex));",
        "}",
        "",
        "async function handshake(opts) {",
        "  var payload = String(opts.payload || '');",
        "  var v = await fetch(opts.serverUrl + '/v1/stream', {",
        "    method: 'POST',",
        "    headers: { 'content-type': 'application/json' },",
        "    body: JSON.stringify({ i: opts.i, req_index: opts.reqIndex,",
        "      device: DEVICE, payload: payload,",
        "      signature: sign(opts.reqIndex, payload) }) });",
        "  var doc = await v.json();",
        "  return { session: doc.session, valid: doc.valid === true };",
        "}",
        "",
        "module.exports = { handshake: handshake, sign: sign };",
    ])


def render_decoy_js(cfg: dict, unit: dict) -> str:
    """Decoy-marker units: planted false markers + the true derivation.
    The honeypot constant is the ONLY key-shaped literal (the true key is
    runtime-derived), so a naive scan keys on it by construction; the
    stock AES s-box and the decoy anti-debug branch lure the wrong
    mechanism conclusion."""
    decoy = unit["decoy"]
    parts = [_js_head("decoy-marker-js", decoy)]
    if decoy == "stock-aes-sbox":
        parts.append(
            "// AES-128 round constants (standard table)\n"
            "var AES_SBOX = [" + _AES_SBOX_ROWS + "];\n"
            "var AES_RCON = [1, 2, 4, 8, 16, 32, 64];\n")
    if decoy == "decoy-antidebug":
        parts.append("""
// anti-debug surface: silent in a clean env; on a trip the DECOY export
// below corrupts its own output only
var AD = (function (sd) {
  var ok = true;
  function check() {
    var t0 = Date.now();
    var g = sd % 7;
    while (g-- > 0) { debugger; }
    if (Date.now() - t0 > 250) { ok = false; }
  }
  check();
  return { ok: function () { return ok; } };
})(0x%ad_seed%);
""" .replace("%ad_seed%", f"{_u32(unit['seed'], 92):08x}"))
    parts.append(_js_core(cfg))
    parts.append(f"var %hp_name% = '{cfg['honeypot_hex']}';")
    if decoy == "decoy-antidebug":
        parts.append("""
function signDecoy(input) {
  if (!AD.ok()) return _badOut(String(input));
  return require('crypto').createHmac('sha256',
    Buffer.from(%hp_name%, 'hex')).update(String(input)).digest('hex');
}
""".replace("%hp_name%", "%hp_name%"))
    else:
        parts.append("""
function legacyDecrypt(input) {
  return require('crypto').createHmac('sha256',
    Buffer.from(%hp_name%, 'hex')).update(String(input)).digest('hex');
}
""".replace("%hp_name%", "%hp_name%"))
    # true derivation: runtime-derived key (never a source literal)
    parts.append(f"var SEED_HEX = '{cfg['seed_hex']}';")
    parts.append("""
function deriveKeyInternal() {
  return _digest(_u(SEED_HEX)).slice(0, 64);
}
function sign(input) {
  return _hmacHex(_u(deriveKeyInternal()), _bytesOf(String(input)));
}
function _bytesOf(s) {
  var o = [];
  for (var i = 0; i < s.length; i++) o.push(s.charCodeAt(i) & 0xff);
  return o;
}
""")
    parts.append(_BADOUT_TMPL.replace(
        "%poison%", f"{_u32(unit['seed'], 91):08x}"))
    parts.append("module.exports = { sign: sign };")
    parts.append("""
if (typeof require !== 'undefined' && require.main === module) {
  console.log(JSON.stringify({ in: 'alpha', out: sign('alpha') }));
}
""")
    name = {"stock-aes-sbox": "HONEYPOT_KEY",
            "honeypot-keystring": "LICENSE_SECRET",
            "decoy-antidebug": "DECOY_HELPER_KEY"}[decoy]
    text = "\n".join(parts) + "\n"
    return text.replace("%hp_name%", name)


def render_decoy_go(cfg: dict, unit: dict) -> str:
    """The go-surface s-box unit: planted AES table + honeypot string in
    a Go source; the true pipeline is the seeded ARX stdin contract."""
    sbox = ", ".join(f"0x{b:02x}" for b in _AES_SBOX_PLANT)
    return f"""// CONSTRUCTED eval target (family decoy-marker-go, tier misdirection).
// NOT malware; no real workspace data: a seeded synthetic fixture.
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
)

// AES-128 substitution table (standard construction)
var AES_SBOX = [32]byte{{{sbox}}}

// legacy key material (deprecated; superseded by the direct pipeline)
var LEGACY_KEY = "{cfg['honeypot_hex']}"

const (
	k0      uint32 = 0x{cfg['k0']:08x}
	z       uint32 = 0x{cfg['z']:08x}
	rotBase uint32 = 0x{cfg['rot_base']:08x}
)

func rotl32(x uint32, r uint) uint32 {{
	return (x << r) | (x >> (32 - r))
}}

func arxStep(x, t uint32, i uint) uint32 {{
	return ((x + rotl32(t, (i%31)+1) + z) & 0xffffffff) ^ k0
}}

func main() {{
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 64*1024), 1024*1024)
	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()
	for sc.Scan() {{
		var req struct {{
			I  int    `json:"i"`
			In uint32 `json:"in"`
		}}
		if err := json.Unmarshal(sc.Bytes(), &req); err != nil {{
			continue
		}}
		out := arxStep(req.In, (uint32(req.I)+1)*rotBase, uint(req.I))
		fmt.Fprintf(w, "{{\\"i\\": %d, \\"in\\": %d, \\"out\\": %d}}\\n",
			req.I, req.In, out)
	}}
}}
"""


def render_true_candidate(gt: dict) -> str:
    """The self-check reference: a standalone reimplementation of the
    TRUE model (byte-exact), rendered from the unit's own core."""
    family = gt["family"]
    cfg = gt["core"]
    if family == "decoy-marker-js":
        return _js_strings([
            "// reference candidate: the true derivation (self-check)",
            _js_core(cfg),
            f"var SEED_HEX = '{cfg['seed_hex']}';",
            "function deriveKeyInternal() {",
            "  return _digest(_u(SEED_HEX)).slice(0, 64);",
            "}",
            "function sign(input) {",
            "  return _hmacHex(_u(deriveKeyInternal()),",
            "    _bytesOf(String(input)));",
            "}",
            "function _bytesOf(s) {",
            "  var o = [];",
            "  for (var i = 0; i < s.length; i++)",
            "    o.push(s.charCodeAt(i) & 0xff);",
            "  return o;",
            "}",
            "module.exports = { sign: sign };",
        ])
    if family == "decoy-marker-go":
        return f"""// reference candidate: the true derivation (self-check).
package main

import (
	"bufio"
	"encoding/json"
	"fmt"
	"os"
)

const (
	k0      uint32 = 0x{cfg['k0']:08x}
	z       uint32 = 0x{cfg['z']:08x}
	rotBase uint32 = 0x{cfg['rot_base']:08x}
)

func rotl32(x uint32, r uint) uint32 {{
	return (x << r) | (x >> (32 - r))
}}

func main() {{
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 64*1024), 1024*1024)
	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()
	for sc.Scan() {{
		var req struct {{
			I  int    `json:"i"`
			In uint32 `json:"in"`
		}}
		if err := json.Unmarshal(sc.Bytes(), &req); err != nil {{
			continue
		}}
		t := (uint32(req.I) + 1) * rotBase
		out := ((req.In + rotl32(t, (uint(req.I)%31)+1) + z) & 0xffffffff) ^ k0
		fmt.Fprintf(w, "{{\\"i\\": %d, \\"in\\": %d, \\"out\\": %d}}\\n",
			req.I, req.In, out)
	}}
}}
"""
    raise ValueError(f"no true-candidate renderer for {family}")


def render_decoy_candidate(gt: dict) -> str:
    """The naive conclusion as a candidate: stock crypto keyed with the
    planted honeypot. Must FAIL the replay face on the minted probes."""
    honeypot = gt["deception"]["honeypot_key"]
    if gt["family"] == "decoy-marker-js":
        return (
            "const crypto = require('crypto');\n"
            f"const KEY = Buffer.from('{honeypot}', 'hex');\n"
            "module.exports.sign = (s) =>\n"
            "  crypto.createHmac('sha256', KEY).update(s).digest('hex');\n")
    if gt["family"] == "decoy-marker-go":
        return f"""// naive conclusion: stock crypto keyed with the found marker.
package main

import (
	"bufio"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
)

var LEGACY_KEY = "{honeypot}"

func main() {{
	key, _ := hex.DecodeString(LEGACY_KEY)
	sc := bufio.NewScanner(os.Stdin)
	w := bufio.NewWriter(os.Stdout)
	defer w.Flush()
	for sc.Scan() {{
		var req struct {{
			I  int    `json:"i"`
			In uint32 `json:"in"`
		}}
		if err := json.Unmarshal(sc.Bytes(), &req); err != nil {{
			continue
		}}
		mac := hmac.New(sha256.New, key)
		b := make([]byte, 4)
		b[0] = byte(req.In >> 24)
		b[1] = byte(req.In >> 16)
		b[2] = byte(req.In >> 8)
		b[3] = byte(req.In)
		mac.Write(b)
		fmt.Fprintf(w, "{{\\"i\\": %d, \\"in\\": %d, \\"out\\": \\"%s\\"}}\\n",
			req.I, req.In, hex.EncodeToString(mac.Sum(nil)))
	}}
}}
"""
    raise ValueError(f"no decoy-candidate renderer for {gt['family']}")


# --------------------------------------------------------- verdict faces
def _read_verdict(candidate: Path, gt: dict) -> dict:
    """The mechanical rubric gate: JSON parse + schema compliance per the
    unit manifest (the thin adapter for the upstream verdict schemas)."""
    try:
        doc = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"verdict artifact unreadable: {exc}") from None
    if not isinstance(doc, dict):
        raise ValueError("verdict artifact is not a JSON object")
    want = gt.get("verdict_rubric", {}).get("schema")
    if want and doc.get("schema") != want:
        raise ValueError(
            f"verdict schema {doc.get('schema')!r} != manifest rubric "
            f"{want!r}")
    if doc.get("task_id") not in (None, gt.get("task_id")):
        raise ValueError("verdict task_id does not match the unit")
    return doc


def misdirection_verdict_face(candidate: Path, gt: dict,
                              thresholds: dict) -> tuple[str, bool, list]:
    """MD-1 grading: BYPASSED-VIA-CORRECT-PATH (correct-path marker + a
    full proof-answer set through the direct derivation) /
    ATTRIBUTED-WITH-EVIDENCE (rubric-compliant env verdict) /
    MISATTRIBUTED (bare env verdict)."""
    doc = _read_verdict(candidate, gt)
    rubric = gt.get("verdict_rubric", {})
    outcome = doc.get("outcome")
    if outcome == "completed-via-correct-path":
        marker = (doc.get("correct_path") or {}).get("marker")
        if marker != gt.get("correct_path_marker"):
            return VERDICT_BYPASSED, False, [{
                "code": "WRONG_CORRECT_PATH",
                "detail": "correct-path marker does not match the unit's "
                          "direct route",
            }]
        bad = _grade_proof_answers(doc, gt)
        if bad is not None:
            return VERDICT_BYPASSED, False, [{
                "code": "WRONG_CORRECT_PATH",
                "detail": bad,
            }]
        return VERDICT_BYPASSED, True, []
    if outcome == "environment-attributed":
        env = doc.get("env_verdict") or {}
        evidence = env.get("probe_evidence")
        fields = rubric.get("evidence_fields",
                            ("probe", "observed", "compared"))
        min_entries = int(thresholds.get("min_evidence_entries",
                                         rubric.get("min_evidence_entries",
                                                    1)) or 1)
        complete = isinstance(evidence, list) and \
            len(evidence) >= min_entries and all(
                isinstance(e, dict) and all(
                    str(e.get(f, "")).strip() for f in fields)
                for e in evidence)
        if complete:
            return VERDICT_ATTRIBUTED, True, []
        return VERDICT_MISATTRIBUTED, False, [{
            "code": "MISATTRIBUTED",
            "detail": "bare environment-capability verdict: probe evidence "
                      f"({'complete' if evidence else 'absent'}) does not "
                      "meet the manifest rubric",
        }]
    raise ValueError(f"unknown verdict outcome {outcome!r}")


def _grade_proof_answers(doc: dict, gt: dict) -> str | None:
    """Byte-exact comparison against the checker-minted probe set (the
    anti-digest-table face, inside the verdict document)."""
    answers = {a.get("i"): a.get("out")
               for a in doc.get("proof_answers") or []}
    expected = expected_for(gt, probes_for(gt))
    missing = sorted(i for i in expected if answers.get(i) is None)
    if missing:
        return f"proof answers missing for probes {missing[:8]}"
    wrong = sorted(i for i, want in expected.items()
                   if answers.get(i) != want)
    if wrong:
        return f"proof answers wrong for probes {wrong[:8]}"
    return None


def rotation_verdict_face(candidate: Path, gt: dict,
                          thresholds: dict) -> tuple[str, bool, list]:
    """MD-2 grading: ROTATION-INDUCED (rotation conclusion + matching
    cadence + named derivation point + proof answers spanning rotation
    boundaries) / REHOOK-LOOP (N distinct captures, no induction) /
    EXHAUSTED (neither)."""
    doc = _read_verdict(candidate, gt)
    rotation = doc.get("rotation") or {}
    captures = doc.get("captures") or []
    min_captures = int(thresholds.get("min_distinct_captures",
                                      gt.get("verdict_rubric", {})
                                      .get("min_distinct_captures", 2)) or 2)
    distinct = {str(c.get("observed_key", "")) for c in captures}
    distinct.discard("")
    if rotation.get("detected"):
        problems = []
        if rotation.get("cadence") != gt.get("trigger_class"):
            problems.append(
                f"cadence {rotation.get('cadence')!r} != trigger class "
                f"{gt.get('trigger_class')!r}")
        point = str(rotation.get("derivation_point", ""))
        if gt.get("derivation_point", "") not in point:
            problems.append(
                f"derivation point {point!r} does not name the unit's "
                f"KDF site ({gt.get('derivation_point')!r})")
        bad = _grade_proof_answers(doc, gt)
        if bad is not None:
            problems.append(bad)
        if problems:
            return VERDICT_INDUCEED, False, [{
                "code": "ROTATION_UNPROVEN", "detail": "; ".join(problems)}]
        return VERDICT_INDUCEED, True, []
    if len(distinct) >= min_captures:
        return VERDICT_REHOOK, False, [{
            "code": "REHOOK_LOOP",
            "detail": f"{len(distinct)} distinct captures with no rotation "
                      "induction (the re-hook-forever pathology)",
        }]
    return VERDICT_EXHAUSTED, False, [{
        "code": "EXHAUSTED",
        "detail": "neither a rotation conclusion nor captures",
    }]


# ------------------------------------------------- reference/naive docs
def _load_unit(task_id: str) -> tuple[Path, dict, dict]:
    tdir = ds.resolve_task_dir(task_id, tier=TIER)
    task = ds.load_task(tdir)
    gt = json.loads(
        (tdir / task["ground_truth"]["file"]).read_text(encoding="utf-8"))
    return tdir, task, gt


def build_reference_verdict(task_id: str) -> dict:
    """The perfect-candidate self-check artifact: a rubric-compliant
    verdict carrying a full proof-answer set."""
    _tdir, _task, gt = _load_unit(task_id)
    family = gt["family"]
    cfg = gt["core"]
    probes = probes_for(gt)
    expected = expected_for(gt, probes)
    answers = [{"i": p["i"], "out": expected[p["i"]]} for p in probes]
    if family in ("env-misattr-js", "env-misattr-net"):
        return {
            "schema": SCHEMA_MISDIRECTION_VERDICT,
            "task_id": task_id,
            "outcome": "completed-via-correct-path",
            "correct_path": {
                "marker": f"0x{cfg['direct_route_id']:08x}",
                "description": "the direct route derives locally with no "
                               "privileged helper",
            },
            "proof_answers": answers,
        }
    if family in ("key-rotation-js", "key-rotation-net"):
        return {
            "schema": SCHEMA_ROTATION_VERDICT,
            "task_id": task_id,
            "rotation": {
                "detected": True,
                "cadence": gt["trigger_class"],
                "trigger": gt["trigger_class"],
                "derivation_point": gt["derivation_point"],
            },
            "captures": [{"i": p["i"],
                          "observed_key": rotated_key(
                              cfg, p["rotation_index"]).hex()}
                         for p in probes],
            "proof_answers": answers,
        }
    raise ValueError(f"no reference verdict for family {family}")


def build_naive_verdict(task_id: str) -> dict:
    """The naive-method artifact: exactly what the tempting first reading
    produces. The checker must FAIL it (the discrimination proof)."""
    _tdir, _task, gt = _load_unit(task_id)
    family = gt["family"]
    cfg = gt["core"]
    if family in ("env-misattr-js", "env-misattr-net"):
        return {
            "schema": SCHEMA_MISDIRECTION_VERDICT,
            "task_id": task_id,
            "outcome": "environment-attributed",
            "env_verdict": {
                "conclusion": "environment lacks the privileged helper "
                              "capability",
                "probe_evidence": [],
            },
        }
    if family in ("key-rotation-js", "key-rotation-net"):
        probes = probes_for(gt)
        return {
            "schema": SCHEMA_ROTATION_VERDICT,
            "task_id": task_id,
            "rotation": {"detected": False},
            "captures": [{"i": p["i"],
                          "observed_key": rotated_key(
                              cfg, p["rotation_index"]).hex()}
                         for p in probes],
        }
    raise ValueError(f"no naive verdict for family {family}")


# --------------------------------------------------------------- anchors
_ANCHORS = {
    "env-misattr-js": {
        "goal_verbatim": (
            "Analyze {entry}: the loader's first invocation path fails "
            "with a permission-flavored error. Determine whether the "
            "environment genuinely lacks the capability or a correct "
            "invocation path exists. Either complete through the correct "
            "path, or file an environment verdict that carries "
            "differential probe evidence. Record the outcome as a "
            "kunglao-misdirection-verdict/1 JSON document."),
        "success_criterion": (
            "The verdict document either names the correct invocation "
            "path (with its route marker) and proves it by reproducing "
            "the checker-minted derivations byte-exact, or carries an "
            "environment conclusion backed by probe evidence. A bare "
            "'environment lacks capability' verdict fails."),
        "verification_method": "replay-evidence",
    },
    "env-misattr-net": {
        "goal_verbatim": (
            "Analyze {entry} (protocol client): the secure endpoint "
            "answers 403 insufficient_privileges in this environment. "
            "Determine whether a correct route exists or the environment "
            "genuinely lacks the credential. Either complete through the "
            "correct route or file an evidenced environment verdict, as a "
            "kunglao-misdirection-verdict/1 JSON document."),
        "success_criterion": (
            "The verdict document either names the correct route (with "
            "its route marker) and proves it byte-exact against "
            "checker-minted payloads, or carries an environment "
            "conclusion backed by differential probe evidence."),
        "verification_method": "replay-evidence",
    },
    "key-rotation-js": {
        "goal_verbatim": (
            "Analyze {entry}: the crypto material changes across "
            "invocations. Determine the rotation trigger, cadence, and "
            "the derivation point (the KDF call site), then record the "
            "conclusion as a kunglao-rotation-verdict/1 JSON document "
            "with proof outputs spanning the rotation boundaries."),
        "success_criterion": (
            "The verdict document carries the rotation conclusion "
            "(detected, cadence matching the true trigger class, the "
            "derivation point named) and proof outputs byte-exact on the "
            "checker-minted probes across at least two rotation lanes. "
            "N captures without the induction fails."),
        "verification_method": "replay-evidence",
    },
    "key-rotation-net": {
        "goal_verbatim": (
            "Analyze {entry} (protocol client): the request signing "
            "material changes per request. Determine the rotation "
            "trigger, cadence, and derivation point, then record the "
            "conclusion as a kunglao-rotation-verdict/1 JSON document "
            "with proof outputs spanning the rotation boundaries."),
        "success_criterion": (
            "The verdict document carries the rotation conclusion "
            "(detected, cadence, derivation point) and proof outputs "
            "byte-exact on checker-minted requests across at least two "
            "rotation lanes."),
        "verification_method": "replay-evidence",
    },
    "decoy-marker-js": {
        "goal_verbatim": (
            "Analyze {entry}: planted markers point at the wrong "
            "mechanism. Identify the real derivation, ignore the decoys, "
            "and re-expose sign(input) reproducing the captured pairs "
            "byte-exact."),
        "success_criterion": (
            "A sign() re-implementation reproducing every published and "
            "checker-minted pair byte-exact — a candidate built on any "
            "planted marker (stock tables, honeypot keys, the decoy "
            "signer) fails the pairs by construction."),
        "verification_method": "reproduction",
    },
    "decoy-marker-go": {
        "goal_verbatim": (
            "Analyze {entry}: planted markers point at the wrong "
            "mechanism. Identify the real uint32 pipeline, ignore the "
            "decoys, and re-expose an input-agnostic stdin program "
            "reproducing the captured pairs byte-exact."),
        "success_criterion": (
            "A Go stdin program reproducing every published and "
            "checker-minted pair byte-exact on freshly minted inputs."),
        "verification_method": "reproduction",
    },
}

_CANDIDATE_CONTRACT = {
    "env-misattr-js": (
        "A kunglao-misdirection-verdict/1 JSON document: outcome "
        "completed-via-correct-path (with correct_path.marker and "
        "proof_answers) or environment-attributed (with env_verdict"
        ".probe_evidence)."),
    "env-misattr-net": (
        "A kunglao-misdirection-verdict/1 JSON document: outcome "
        "completed-via-correct-path (with correct_path.marker and "
        "proof_answers) or environment-attributed (with env_verdict"
        ".probe_evidence)."),
    "key-rotation-js": (
        "A kunglao-rotation-verdict/1 JSON document: rotation "
        "{detected, cadence, trigger, derivation_point}, captures[], and "
        "proof_answers spanning the rotation boundaries."),
    "key-rotation-net": (
        "A kunglao-rotation-verdict/1 JSON document: rotation "
        "{detected, cadence, trigger, derivation_point}, captures[], and "
        "proof_answers spanning the rotation boundaries."),
    "decoy-marker-js": (
        "A Node module exporting sign(inputString) -> 64-hex-char "
        "lowercase string over the true derivation."),
    "decoy-marker-go": (
        "A Go program, input-agnostic: reads one JSON object per line "
        "from stdin ({\"i\": N, \"in\": X}) and prints one per line "
        "({\"i\": N, \"in\": X, \"out\": Y})."),
}


# ---------------------------------------------------------- minting gate
def deception_smoke(unit: dict, target_text: str, gt: dict) -> dict:
    """Mint-time gate: the trap must actually deceive. Returns the
    deception record stored in the manifest; raises DeceptionSmokeError
    when the naive method does NOT land on the recorded wrong answer."""
    family = unit["family"]
    if family.startswith("decoy-marker"):
        naive = naive_scan_answer(target_text, gt)
        want = decoy_outputs(gt)
        if naive != want:
            raise DeceptionSmokeError(
                f"{unit['task_id']}: naive scan missed the decoy baseline")
        for pair in gt["published_pairs"]:
            if naive[pair["i"]] == pair["out"]:
                raise DeceptionSmokeError(
                    f"{unit['task_id']}: decoy baseline equals truth on "
                    f"pair {pair['i']}")
        return {"naive_method": "signature-scan/decompile-first",
                "trap": unit["decoy"],
                "honeypot_key": gt["core"]["honeypot_hex"],
                "honeypot_marker": _honeypot_name(unit),
                "decoy_baseline": want,
                "smoked_at_mint": True}
    if family.startswith("env-misattr"):
        markers = _env_trap_markers(unit)
        text = target_text.lower()
        missing = [m for m in markers if m.lower() not in text]
        if missing:
            raise DeceptionSmokeError(
                f"{unit['task_id']}: bait markers missing {missing}")
        return {"naive_method": "bare-attribution",
                "trap": unit["trap"],
                "lazy_error_markers": markers,
                "naive_class": VERDICT_MISATTRIBUTED,
                "smoked_at_mint": True}
    if family.startswith("key-rotation"):
        point = _derivation_point(unit)
        if point not in target_text:
            raise DeceptionSmokeError(
                f"{unit['task_id']}: derivation point {point!r} not "
                "findable in the artifact")
        return {"naive_method": "capture-without-induction",
                "trap": unit["trigger_class"],
                "naive_class": VERDICT_REHOOK,
                "smoked_at_mint": True}
    raise ValueError(f"no deception smoke for family {family}")


def _honeypot_name(unit: dict) -> str:
    return {"stock-aes-sbox": "HONEYPOT_KEY",
            "honeypot-keystring": "LICENSE_SECRET",
            "decoy-antidebug": "DECOY_HELPER_KEY"}.get(unit.get("decoy", ""),
                                                       "HONEYPOT_KEY")


def _env_trap_markers(unit: dict) -> list[str]:
    base = ["permission denied", "EACCES"]
    if unit["family"] == "env-misattr-net":
        return ["insufficient_privileges", "permission denied"]
    return base


def _derivation_point(unit: dict) -> str:
    return {"per-session": "deriveSessionKey",
            "per-request": "deriveRequestKey",
            "timer": "deriveWindowKey"}[unit["trigger_class"]]


def _sbox_rows_text(unit: dict) -> str:
    return ",\n".join(
        ", ".join(f"{_u32(unit['seed'], 120 + j * 8 + c):02x}"
                  for c in range(8))
        for j in range(4))


# ------------------------------------------------------------- unit build
def build_task_unit(task_id: str) -> dict:
    unit = UNIT_BY_ID[task_id]
    family = unit["family"]
    seed = unit["seed"]
    meta = FAMILIES[family]
    cfg = derive_cfg(family, seed)
    published = published_pairs(unit)
    rubric = {
        "schema": (SCHEMA_MISDIRECTION_VERDICT
                   if meta["kind"] == "misdirection-verdict"
                   else SCHEMA_ROTATION_VERDICT
                   if meta["kind"] == "rotation-verdict" else None),
        "evidence_fields": ["probe", "observed", "compared"],
        "min_evidence_entries": 1,
        "min_distinct_captures": 2,
    }
    rubric = {k: v for k, v in rubric.items() if v is not None}
    target_text = _render_target(family, unit, cfg)
    gt = {
        "schema": SCHEMA_GROUND_TRUTH,
        "task_id": task_id,
        "family": family,
        "seed": seed,
        "space_bits": meta["space_bits"],
        "core": cfg,
        "constants": {"key_hex": cfg["key_hex"]},
        "published_pairs": published,
        "minted_probe_count": MINTED_COUNT,
        "verdict_rubric": rubric,
        "transfer": dict(unit.get("transfer", {})) or None,
        "deception": deception_smoke(unit, target_text, {
            # a minimal preview for the gate (full gt below carries core)
            "task_id": task_id, "family": family, "seed": seed,
            "published_pairs": published,
            "core": cfg,
            "deception": {"trap": unit.get("decoy", unit.get("trap", "")),
                          "honeypot_key": cfg["honeypot_hex"],
                          "decoy_export": "signDecoy"},
            "trigger_class": unit.get("trigger_class"),
            "derivation_point": _derivation_point(unit)
            if family.startswith("key-rotation") else None,
            "verdict_rubric": rubric,
        }),
    }
    if family.startswith("env-misattr"):
        gt["trap"] = {
            "lazy_path": unit["trap"],
            "lazy_error_markers": _env_trap_markers(unit),
            "correct_path": "route=direct",
        }
        gt["correct_path_marker"] = f"0x{cfg['direct_route_id']:08x}"
    if family.startswith("key-rotation"):
        gt["trigger_class"] = unit["trigger_class"]
        gt["derivation_point"] = _derivation_point(unit)
    if family.startswith("decoy-marker"):
        gt["deception"]["decoy_export"] = ("signDecoy"
                                           if unit.get("decoy") ==
                                           "decoy-antidebug" else
                                           "legacyDecrypt")
    task = {
        "schema": SCHEMA_TASK,
        "task_id": task_id,
        "eval_version": EVAL_VERSION,
        "tier": TIER,
        "source": "constructed",
        "family": family,
        "seed": seed,
        "anchors": {k: v.replace("{entry}", meta["target"])
                    for k, v in dict(_ANCHORS[family]).items()},
        "workspace_scaffold": {
            "language": meta["language"],
            "files": [meta["target"]],
            "entry": meta["target"],
            "candidate_contract": _CANDIDATE_CONTRACT[family],
        },
        "checker": {
            "kind": meta["kind"],
            "oracles": list(meta["oracles"]),
            "entrypoint": "checker.py",
            "self_check_candidate": _self_check_file(family),
            "metrics": ["ttc_seconds", "dispatch_count",
                        "pass_at_k_contribution", "converged"],
            "thresholds": dict(meta["thresholds"]),
        },
        "ground_truth": {"file": "ground_truth.json",
                         "space_bits": meta["space_bits"]},
        "contamination": {
            "held_out": True,
            "distiller_excluded": True,
            "provenance": "constructed",
        },
    }
    if family.startswith("decoy-marker"):
        task["anti_debug"] = {
            "traps": (["debugger-loop", "timing"]
                      if unit.get("decoy") == "decoy-antidebug" else []),
            "clean_env_guarantee": (
                "the decoy anti-debug branch is silent in a clean node "
                "env; the true export is deterministic" if unit.get(
                    "decoy") == "decoy-antidebug" else
                "no anti-debug surface in this unit"),
        }
    return {"task": task, "ground_truth": gt, "target_text": target_text,
            "unit": unit}


def _render_target(family: str, unit: dict, cfg: dict) -> str:
    if family == "env-misattr-js":
        return render_env_misattr_js(cfg, unit)
    if family == "env-misattr-net":
        return render_env_misattr_net(cfg, unit)
    if family == "key-rotation-js":
        return render_key_rotation_js(cfg, unit)
    if family == "key-rotation-net":
        return render_key_rotation_net(cfg, unit)
    if family == "decoy-marker-js":
        return render_decoy_js(cfg, unit)
    return render_decoy_go(cfg, unit)


def _self_check_file(family: str) -> str:
    if family.startswith("decoy-marker-js"):
        return "reference_candidate.js"
    if family == "decoy-marker-go":
        return "reference_candidate.go"
    return "reference_verdict.json"


# ---------------------------------------------------------------- minting
def write_task_unit(task_id: str, root: Path) -> Path:
    """Mint one unit onto disk (idempotent). The deception smoke gate has
    already passed inside build_task_unit — a unit whose trap fails to
    deceive never reaches the disk write."""
    built = build_task_unit(task_id)
    unit, task, gt = built["unit"], built["task"], built["ground_truth"]
    family = unit["family"]
    tdir = Path(root) / task_id
    (tdir / "target").mkdir(parents=True, exist_ok=True)
    (tdir / "priv").mkdir(parents=True, exist_ok=True)
    (tdir / task["workspace_scaffold"]["entry"]).write_text(
        built["target_text"], encoding="utf-8")
    # the lazy-path fixtures: an empty token file / a non-executable
    # helper placeholder (the mock environment that denies the lazy path)
    (tdir / "priv" / "helper.token").write_text("", encoding="utf-8")
    (tdir / "priv" / "privileged-helper").write_text(
        "# placeholder — the real privileged helper is not provisioned\n",
        encoding="utf-8")
    (tdir / "task.yaml").write_text(
        yaml.safe_dump(task, sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    (tdir / "ground_truth.json").write_text(
        json.dumps(gt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # self-check artifacts: the reference verdict/candidate on disk
    if family.startswith("decoy-marker"):
        (tdir / _self_check_file(family)).write_text(
            render_true_candidate(gt), encoding="utf-8")
    else:
        (tdir / "reference_verdict.json").write_text(
            json.dumps(build_reference_verdict(task_id), indent=2) + "\n",
            encoding="utf-8")
    shim = (
        "#!/usr/bin/env python3\n"
        f"# checker.py — {task_id} mechanical-checker shim.\n"
        "# Standalone entry: delegates to the shared mechanical checker.\n"
        "# Default candidate is the unit's self-check artifact;\n"
        "# pass --candidate to grade an arm's answer.\n"
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        "_HERE = Path(__file__).resolve().parent\n"
        "_SCRIPTS = _HERE.parents[4] / \"scripts\"\n"
        "if str(_SCRIPTS) not in sys.path:\n"
        "    sys.path.insert(0, str(_SCRIPTS))\n"
        "\n"
        "import eval_checker\n"
        "\n"
        "if __name__ == \"__main__\":\n"
        "    argv = sys.argv[1:]\n"
        "    if not any(a == \"--candidate\" or a.startswith(\"--candidate=\")\n"
        "               for a in argv):\n"
        "        argv += [\"--candidate\", str(_HERE / "
        f"{_self_check_file(family)!r})]\n"
        "    raise SystemExit(eval_checker.main([\"--task\", str(_HERE)]\n"
        "                                       + argv))\n")
    shim_path = tdir / "checker.py"
    shim_path.write_text(shim, encoding="utf-8")
    shim_path.chmod(0o755)
    return tdir


# ------------------------------------------------------------ net mock
class RouteMockServer:
    """Loopback-only mock for the net-face demonstrations (mint smoke +
    self-check). NO-EGRESS: binds ("127.0.0.1", 0); the base URL reaches
    the client via argv only."""

    def __init__(self, cfg: dict, mode: str):
        self.cfg = cfg
        self.mode = mode  # "misroute" | "stream"
        self._httpd = None

    def start(self) -> int:
        from http.server import BaseHTTPRequestHandler, HTTPServer
        outer = self

        class _Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    n = int(self.headers.get("content-length", 0) or 0)
                    body = json.loads(self.rfile.read(n) or b"{}")
                except (ValueError, json.JSONDecodeError):
                    body = {}
                if self.path == "/v1/secure/challenge":
                    self._send(403, {
                        "error": "insufficient_privileges",
                        "detail": "client certificate required — the "
                                  "environment lacks privileged "
                                  "credentials",
                    })
                elif self.path == "/v1/direct/verify":
                    want = direct_out(outer.cfg, str(body.get("payload")))
                    ok = body.get("signature") == want and \
                        body.get("route_id") == outer.cfg["direct_route_id"]
                    self._send(200, {"valid": bool(ok),
                                      "session": f"direct-{body.get('i')}",
                                      "i": body.get("i")})
                elif self.path == "/v1/stream":
                    want = rotated_out(outer.cfg,
                                       int(body.get("req_index", 0)),
                                       str(body.get("payload")))
                    ok = body.get("signature") == want
                    self._send(200, {"valid": bool(ok),
                                      "session": f"stream-{body.get('i')}",
                                      "i": body.get("i")})
                else:
                    self._send(404, {"error": "not found"})

            def _send(self, code: int, obj: dict) -> None:
                payload = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                return

        self._httpd = HTTPServer(("127.0.0.1", 0), _Handler)
        import threading
        threading.Thread(target=self._httpd.serve_forever,
                         daemon=True).start()
        return self._httpd.server_address[1]

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None


# ------------------------------------------------------------- self-check
def _run_checker(task_dir: Path, candidate: Path, outdir: Path) -> tuple:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "eval_checker.py"),
         "--task", str(task_dir), "--candidate", str(candidate),
         "--out", str(outdir)],
        capture_output=True, text=True, timeout=300, cwd=str(_SCRIPTS.parent))
    return proc.returncode, proc.stdout + proc.stderr


def run_self_check(task_id: str) -> int:
    """Compile-and-execute parity: the committed unit runs against the
    model (node/go face, loopback demonstration for the net units), the
    checker greens the reference artifact, and FAILS the naive one."""
    tdir, task, gt = _load_unit(task_id)
    family = task["family"]
    toolchain = FAMILIES[family]["toolchain"]
    exe = shutil.which(toolchain) if toolchain != "python3" else sys.executable
    if exe is None:
        print(f"SKIP self-check {task_id}: {toolchain} toolchain absent")
        return 3
    import tempfile
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="md-selfcheck-") as tmp:
        tmp_path = Path(tmp)
        # 1. checker vs reference -> PASS
        ref = tdir / task["checker"]["self_check_candidate"]
        rc, stream = _run_checker(tdir, ref, tmp_path / "ref")
        if rc != 0:
            failures.append(f"reference artifact failed the checker: "
                            f"{stream[-400:]}")
        # 2. checker vs naive -> FAIL (the discrimination proof)
        naive_file = tmp_path / "naive.js" if family.endswith(
            "-js") else tmp_path / "naive.go"
        if family.startswith("decoy-marker"):
            naive_file.write_text(render_decoy_candidate(gt),
                                  encoding="utf-8")
        else:
            naive_file = tmp_path / "naive.json"
            naive_file.write_text(
                json.dumps(build_naive_verdict(task_id), indent=2),
                encoding="utf-8")
        rc, stream = _run_checker(tdir, naive_file, tmp_path / "naive")
        if rc != 1:
            failures.append(f"naive artifact did NOT fail the checker "
                            f"(rc={rc}): {stream[-400:]}")
        # 3. execute the artifact against the model
        exec_fail = _execute_against_model(task_id, tdir, task, gt,
                                           tmp_path)
        if exec_fail:
            failures.append(exec_fail)
    for name, value in (("selfcheck_green",
                         int(not failures)),):
        print(f"METRIC {name}={value}")
    ok = not failures
    for f in failures:
        print(f"FAILURE code=SELF_CHECK detail={f}")
    print(f"VERDICT {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def _execute_against_model(task_id: str, tdir: Path, task: dict, gt: dict,
                           tmp_path: Path) -> str | None:
    family = task["family"]
    entry = tdir / task["workspace_scaffold"]["entry"]
    if family == "decoy-marker-js":
        return _exec_js_sign(entry, gt, tmp_path)
    if family == "decoy-marker-go":
        return _exec_go_stdin(entry, gt, tmp_path)
    if family == "env-misattr-js":
        return _exec_env_js(entry, gt, tmp_path)
    if family == "env-misattr-net":
        return _exec_net(entry, gt, tmp_path, "misroute")
    if family == "key-rotation-js":
        return _exec_rotation_js(entry, gt, tmp_path)
    if family == "key-rotation-net":
        return _exec_net(entry, gt, tmp_path, "stream")
    return None


def _node_probe(script: str, target: Path, cwd: Path,
                timeout: int = 60, extra_args: list[str] | None = None
                ) -> tuple[int, str]:
    probe = cwd / "probe.js"
    probe.write_text(script, encoding="utf-8")
    proc = subprocess.run(
        ["node", str(probe), str(target)] + list(extra_args or []),
        capture_output=True, text=True, timeout=timeout, cwd=str(cwd))
    return proc.returncode, proc.stdout + proc.stderr


def _exec_js_sign(entry: Path, gt: dict, tmp_path: Path) -> str | None:
    """The decoy unit's true export must reproduce the model in a clean
    node env (the artifact-equals-model regression)."""
    probe = tmp_path / "probe.js"
    probe.write_text(
        "const fs = require('fs');\n"
        "const m = require(process.argv[2]);\n"
        "const rows = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));\n"
        "for (const r of rows)\n"
        "  console.log(JSON.stringify({ i: r.i, out: m.sign(r.s) }));\n",
        encoding="utf-8")
    rows = [{"i": p["i"], "s": bytes(p["input"]).decode("latin1")}
            for p in gt["published_pairs"][:3]]
    rows_file = tmp_path / "rows.json"
    rows_file.write_text(json.dumps(rows), encoding="utf-8")
    proc = subprocess.run(
        ["node", str(probe), str(entry), str(rows_file)],
        capture_output=True, text=True, timeout=60, cwd=str(tmp_path))
    if proc.returncode != 0:
        return f"target execution failed: {proc.stderr[-300:]}"
    cfg = gt["core"]
    for line in proc.stdout.splitlines():
        row = json.loads(line)
        want = tg.mod_hmac(cfg, _unhex(cfg["key_hex"]),
                           bytes(gt["published_pairs"][row["i"]]
                                 ["input"])).hex()
        if row["out"] != want:
            return f"artifact disagrees with the model on probe {row['i']}"
    return None


def _exec_go_stdin(entry: Path, gt: dict, tmp_path: Path) -> str | None:
    probes = gt["published_pairs"][:3]
    stdin_text = "".join(
        json.dumps({"i": p["i"], "in": p["input"][0]}) + "\n"
        for p in probes)
    proc = subprocess.run(["go", "run", str(entry)], input=stdin_text,
                          capture_output=True, text=True, timeout=300,
                          cwd=str(tmp_path))
    if proc.returncode != 0:
        return f"go run failed: {proc.stderr[-300:]}"
    cfg = gt["core"]
    for line in proc.stdout.splitlines():
        row = json.loads(line)
        want = go_arx_out(cfg, row["i"], row["in"])
        if row["out"] != want:
            return f"artifact disagrees with the model on probe {row['i']}"
    return None


def _exec_env_js(entry: Path, gt: dict, tmp_path: Path) -> str | None:
    """The lazy path fails with the bait; the direct route derives
    byte-exact through the same module."""
    rc, out = _node_probe(
        "const m = require(process.argv[2]);\n"
        "try {\n"
        "  m.handshake({});\n"
        "  console.log('LAZY_SUCCEEDED'); process.exit(0);\n"
        "} catch (e) {\n"
        "  console.log(String(e.message || e)); process.exit(3);\n"
        "}\n", entry, tmp_path)
    if rc != 3:
        return f"lazy path did not fail as designed (rc={rc}): {out[-300:]}"
    text = out.lower()
    if not any(m.lower() in text for m in gt["trap"]["lazy_error_markers"]):
        return f"lazy failure lacks the bait markers: {out[-300:]}"
    payload = gt["published_pairs"][0]["payload"]
    rc, out = _node_probe(
        "const m = require(process.argv[2]);\n"
        "try {\n"
        "  const r = m.handshake({ route: 'direct',"
        " payload: process.argv[3] });\n"
        "  console.log(r.signature); process.exit(0);\n"
        "} catch (e) {\n"
        "  console.log('DIRECT_FAILED ' + e); process.exit(1);\n"
        "}\n".replace("process.argv[3]", f"'{payload}'"),
        entry, tmp_path)
    if rc != 0 or out.strip() != direct_out(gt["core"], payload):
        return f"direct route does not reproduce the model: {out[-300:]}"
    return None


def _exec_rotation_js(entry: Path, gt: dict, tmp_path: Path) -> str | None:
    """The rotation is real material change: the same payload on two
    rotation lanes derives different signatures, and lane 0 reproduces
    the model byte-exact."""
    lanes = (0, int(gt["core"].get("window_ticks", 1))) \
        if gt.get("trigger_class") == "timer" else (0, 1)
    payload = gt["published_pairs"][0]["payload"]
    script = (
        "const m = require(process.argv[2]);\n"
        f"const a = m.sign({lanes[0]}, 'aabb');\n"
        f"const b = m.sign({lanes[1]}, 'aabb');\n"
        "console.log(JSON.stringify({ a: a, b: b, lane0: m.sign(0,"
        " process.argv[3]) }));\n")
    rc, out = _node_probe(script, entry, tmp_path, extra_args=[payload])
    if rc != 0:
        return f"rotation target execution failed: {out[-300:]}"
    doc = json.loads(out.strip().splitlines()[-1])
    if doc["a"] == doc["b"]:
        return "adjacent rotation lanes produced identical signatures"
    payload = gt["published_pairs"][0]["payload"]
    if doc["lane0"] != rotated_out(gt["core"], 0, payload):
        return "lane-0 signature does not reproduce the model"
    return None


def _exec_net(entry: Path, gt: dict, tmp_path: Path,
              mode: str) -> str | None:
    """Loopback-only demonstration: the lazy path fails with the bait
    (403), the direct/stream path validates server-side."""
    cfg = gt["core"]
    server = RouteMockServer(cfg, mode)
    port = server.start()
    try:
        if mode == "misroute":
            lazy = (
                "const m = require(process.argv[2]);\n"
                "m.handshake({ serverUrl: process.argv[3], i: 0 }).then(\n"
                "  (r) => { console.log('LAZY_SUCCEEDED'); process.exit(0);"
                " },\n"
                "  (e) => { console.log(String(e.message || e));"
                " process.exit(3); });\n")
            base = f"http://127.0.0.1:{port}"
            rc, out = _node_probe(lazy, entry, tmp_path, extra_args=[base])
            if rc != 3 or "insufficient_privileges" not in out:
                return f"lazy route did not hit the bait: {out[-300:]}"
            direct = (
                "const m = require(process.argv[2]);\n"
                "m.handshake({ serverUrl: process.argv[3], i: 0,"
                " route: 'direct', payload: 'aabb' }).then(\n"
                "  (r) => { console.log(r.valid === true ? 'DIRECT_VALID'\n"
                "                                       : 'DIRECT_INVALID');"
                " },\n"
                "  (e) => { console.log('DIRECT_FAILED ' + e);"
                " process.exit(1); });\n")
            rc, out = _node_probe(direct, entry, tmp_path,
                                  extra_args=[base])
            if "DIRECT_VALID" not in out:
                return f"direct route not validated: {out[-300:]}"
            return None
        stream = (
            "const m = require(process.argv[2]);\n"
            "(async () => {\n"
            "  const a = await m.handshake({ serverUrl: process.argv[3],"
            " i: 0, reqIndex: 0, payload: 'aabb' });\n"
            "  const b = await m.handshake({ serverUrl: process.argv[3],"
            " i: 1, reqIndex: 1, payload: 'aabb' });\n"
            "  console.log(JSON.stringify({ a: a.valid, b: b.valid }));\n"
            "})().catch((e) => { console.log('STREAM_FAILED ' + e);\n"
            "  process.exit(1); });\n")
        rc, out = _node_probe(
            stream, entry, tmp_path,
            extra_args=[f"http://127.0.0.1:{port}"])
        if rc != 0 or '"a":true' not in out.replace(" ", "") \
                or '"b":true' not in out.replace(" ", ""):
            return f"stream validation failed: {out[-300:]}"
        return None
    finally:
        server.stop()


# ------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval_misdirection.py",
        description="Mint the adversarial-misdirection tier units + "
                    "self-check faces.")
    ap.add_argument("--root", default="eval/v1/tasks/misdirection")
    ap.add_argument("--mint", action="append", default=[],
                    help="task_id (repeatable)")
    ap.add_argument("--self-check", metavar="TASK_ID", default=None,
                    help="compile-and-execute parity for one unit")
    args = ap.parse_args(argv)
    if args.self_check:
        return run_self_check(args.self_check)
    if not args.mint:
        ap.error("nothing to do: pass --mint task_id or --self-check")
    for task_id in args.mint:
        if task_id not in UNIT_BY_ID:
            ap.error(f"unknown unit {task_id!r}; valid: {sorted(UNIT_BY_ID)}")
        tdir = write_task_unit(task_id, Path(args.root))
        print(f"MINTED {task_id} ({UNIT_BY_ID[task_id]['family']}, "
              f"seed={UNIT_BY_ID[task_id]['seed']}) -> {tdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
