#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_chain_render.py — language renderers for the chain tier (#370).

ONE python spec (eval_chain.py: arx_permute / kdf_runtime / drbg_block /
stream_xor / chain_mac / chain_core) rendered into the three target
languages. Every renderer is a pure function of (cfg, gradient); mint
self-check executes the rendered artifacts against the python model, so
artifact-model parity is proven per unit at mint time, not assumed.

Faces:
  payload        the protected deep source the outer stage carries
                 (js/py); junk-code wedges included per flag — the
                 polluted face the naive decompile lands on
  target         the committed analysis subject (loader + encoded
                 payload for js/py; packed field blob for go)
  candidate      the final-derivation re-exposure (reference — must
                 PASS the replay face — and naive/decoy — must FAIL)
  workspace      the reference layer artifacts the dense grader scores
                 (and the decoy-following variant that must NOT score)

stdlib only.
"""
from __future__ import annotations


import eval_chain as ch

_M32 = ch.M32


def _u(x: int) -> str:
    return f"{x & _M32:#x}"


def _rc_rows(cfg: dict) -> str:
    """RAW rc words (the normalization lives in the rendered _arx)."""
    return ", ".join("[" + ", ".join(str(r) for r in row) + "]"
                     for row in cfg["rc"])


# ------------------------------------------------------------------ junk
def _junk_tag(cfg: dict) -> str:
    return f"j{cfg['seed'] % 9973:04x}"


def junk_markers(cfg: dict) -> list[str]:
    """The mechanical pollution markers: the junk names + the two
    opaque-predicate constants. Present in the committed payload,
    absent from the stripped reference (the clean op's forbidden list)."""
    tag = _junk_tag(cfg)
    return [f"_opq_{tag}", f"_w_{tag}_",
            _u(cfg["junk_a"]), _u(cfg["junk_b"])]


def _junk_js(cfg: dict) -> str:
    tag = _junk_tag(cfg)
    a, b = cfg["junk_a"], cfg["junk_b"]
    return (
        "// junk wedges (opaque predicates + no-op forest): the naive\n"
        "// decompile of this payload misleads until stripped\n"
        f"var _opq_{tag} = ((FP1 ^ {_u(a)}) >>> 3) ^ {a & 0xffffff:#x};\n"
        f"if (((_opq_{tag} & 1) * ((_opq_{tag} - 1) & 1)) === 1) "
        f"{{ FP0 = (FP0 + 1) >>> 0; }}\n"
        f"var _w_{tag}_a = (FP2 ^ {_u(b)}) >>> 0;\n"
        f"var _w_{tag}_b = ((_w_{tag}_a * 3) ^ (_w_{tag}_a << 1)) >>> 0;\n"
        f"if (((_w_{tag}_b & 1) * ((_w_{tag}_b + 1) & 1)) === 1) "
        f"{{ SALT = (SALT ^ {b & 0xff:#x}) >>> 0; }}\n")


def _junk_py(cfg: dict) -> str:
    tag = _junk_tag(cfg)
    a, b = cfg["junk_a"], cfg["junk_b"]
    return (
        "# junk wedges (opaque predicates + no-op forest): the naive\n"
        "# decompile of this payload misleads until stripped\n"
        f"_opq_{tag} = ((FP1 ^ {a:#x}) >> 3) ^ {a & 0xffffff:#x}\n"
        f"if (_opq_{tag} & 1) * ((_opq_{tag} - 1) & 1) == 1:\n"
        f"    FP0 = (FP0 + 1) & 0xffffffff\n"
        f"_w_{tag}_a = (FP2 ^ {b:#x}) & 0xffffffff\n"
        f"_w_{tag}_b = ((_w_{tag}_a * 3) ^ (_w_{tag}_a << 1)) & 0xffffffff\n"
        f"if (_w_{tag}_b & 1) * ((_w_{tag}_b + 1) & 1) == 1:\n"
        f"    SALT ^= {b & 0xff:#x}\n")


# --------------------------------------------------------------- algo bodies
_JS_ALGO = """function _rotl(x, r) { r &= 31;
  return r ? (((x << r) | (x >>> (32 - r))) >>> 0) : (x >>> 0); }
function _arx(w, rc) {
  var a = w[0], b = w[1], c = w[2], d = w[3];
  a = (a + d) >>> 0; b ^= _rotl(a, (rc[0] & 15) + 1);
  c = (c + b) >>> 0; d ^= _rotl(c, (rc[1] & 15) + 1);
  a = (a + b) >>> 0; c ^= _rotl(a, (rc[2] & 15) + 1);
  d = (d + c) >>> 0; b ^= _rotl(d, (rc[3] & 15) + 1);
  return [a, b, c, d];
}
var RC = [%RC%];
function _kdfWords() {
  var w = [(FP0 ^ RC[0][0]) | 1, (FP1 ^ RC[0][1]) >>> 0,
           (FP2 ^ RC[0][2]) >>> 0, (SALT ^ RC[0][3]) >>> 0];
  for (var r = 0; r < 8; r++) {
    w = _arx(w, RC[r % 8]);
    w[r % 4] = (w[r % 4] ^ (((r + 1) * 0x2545F491) >>> 0)) >>> 0;
  }
  return w;
}
function _blk(keyW, ctr) {
  var w = [keyW[0], keyW[1], keyW[2], (keyW[3] ^ ctr) >>> 0];
  for (var r = 0; r < 6; r++) w = _arx(w, RC[(r + 2) % 8]);
  return w;
}
function _decryptHex(hex) {
  var keyW = _kdfWords(), out = [];
  for (var off = 0, ctr = 0; off < hex.length; off += 32, ctr++) {
    var ks = _blk(keyW, ctr);
    for (var j = 0; j < 32 && off + j < hex.length; j += 2) {
      var bi = j >> 1;
      var b = parseInt(hex.substr(off + j, 2), 16);
      out.push(b ^ ((ks[bi >> 2] >>> ((3 - (bi & 3)) * 8)) & 255));
    }
  }
  return String.fromCharCode.apply(null, out);
}
function _cfgOf(hex) { return JSON.parse(_decryptHex(hex).slice(4)); }
function _bytes(s) {
  var o = [];
  for (var i = 0; i < s.length; i++) o.push(s.charCodeAt(i) & 255);
  return o;
}
function _unhex(h) {
  var o = [];
  for (var i = 0; i < h.length; i += 2)
    o.push(parseInt(h.substr(i, 2), 16));
  return o;
}
function _core(p, data, lane) {
  var c0 = p.c0, c1 = p.c1;
  if (lane) {
    c0 = (c0 ^ _rotl(Math.imul(p.odd, lane) >>> 0, 3)) >>> 0;
    c1 = (c1 + Math.imul(p.odd2, lane)) >>> 0;
  }
  var a = c0, b = c1, acc = p.c2;
  for (var i = 0; i < data.length; i++) {
    a = (a + data[i]) >>> 0;
    a = _rotl((a ^ b) >>> 0, p.rot);
    b = (b + a) >>> 0;
    acc = (acc ^ _rotl((a + acc) >>> 0, 3)) >>> 0;
  }
  var h1 = Math.imul(acc, p.odd) >>> 0;
  var h2 = Math.imul(_rotl((h1 ^ b) >>> 0, 7), p.odd) >>> 0;
  return ('00000000' + h1.toString(16)).slice(-8) +
         ('00000000' + h2.toString(16)).slice(-8);
}
function _mac(keyHex, data) {
  var w = [];
  for (var i = 0; i < 4; i++)
    w.push(parseInt(keyHex.substr(i * 8, 8), 16) >>> 0);
  var padded = data.slice();
  padded.push(0x80);
  while (padded.length % 4 !== 0) padded.push(0);
  for (var off = 0, k = 0; off < padded.length; off += 4, k++) {
    w[0] = (w[0] ^ (((padded[off] << 24) | (padded[off + 1] << 16) |
                     (padded[off + 2] << 8) | padded[off + 3]) >>> 0)) >>> 0;
    w = _arx(w, RC[k % 8]);
  }
  w = _arx(w, RC[0]);
  w = _arx(w, RC[1]);
  return ('00000000' + ((w[0] ^ w[2]) >>> 0).toString(16)).slice(-8) +
         ('00000000' + ((w[1] ^ w[3]) >>> 0).toString(16)).slice(-8);
}"""


def _js_params(p: dict) -> str:
    return ("{c0: %s, c1: %s, c2: %s, rot: %d, odd: %s, odd2: %s}"
            % (_u(p["c0"]), _u(p["c1"]), _u(p["c2"]), p["rot"],
               _u(p["odd"]), _u(p["odd2"])))


def render_js_payload(cfg: dict, include_junk: bool = True) -> str:
    """The protected deep source (js). include_junk=False renders the
    stripped reference form (the junk-strip checkpoint's clean face)."""
    g = cfg["gradient"]
    head = (
        "// chain payload (family %s, seed %d, gradient %s)\n"
        "// synthetic fixture minted by scripts/eval_chain.py - NOT malware.\n"
        "var FP0 = %s, FP1 = %s, FP2 = %s, SALT = %s;\n"
        "var CFG_HEX = '%s';\n"
        % (cfg["family"], cfg["seed"], g, _u(cfg["fp"][0]),
           _u(cfg["fp"][1]), _u(cfg["fp"][2]), _u(cfg["salt"]),
           cfg["cfg_hex"]))
    if g == "L3":
        head += (
            "var LEGACY_LICENSE_KEY = '%s';\n"
            % cfg["honeypot"])
        head += (
            "var INTEG = %s, CORRUPT = %s, GATE_DT = %d, GD = %d;\n"
            "var SEL_KEY = 0x%02x;\n"
            "var LEGACY_P = %s;\n"
            % (_u(cfg["integ"]), _u(cfg["corrupt"]), cfg["gate_dt_ms"],
               cfg["fp"][2] % 9 + 1, cfg["sel_key"],
               _js_params(cfg["decoy_config"]["core"])))
        tail = """
function derive(req) {
  var data = _unhex(String(req.payload));
  var lane = (req.lane | 0) || 0;
  var integNow = INTEG;
  var t0 = Date.now();
  var gd = GD;
  while (gd-- > 0) { debugger; }
  if (Date.now() - t0 > GATE_DT) { integNow = (INTEG ^ CORRUPT) >>> 0; }
  var sel = ((FP0 ^ integNow) >>> 0) & 255;
  if (sel === SEL_KEY) { return _core(TRUE_P, data, lane); }
  return _core(LEGACY_P, data, lane);
}
module.exports = { derive: derive };
"""
        mid = "var TRUE_P = _cfgOf(CFG_HEX).core;\n"
    else:
        head += (
            "var LEGACY_HEX = '%s';\n"
            "var LEGACY_LICENSE_KEY = '%s';\n"
            % (cfg["decoy_hex"], cfg["honeypot"]))
        if g == "L1":
            head += "var LEGACY_KEY = '%s';\n" % cfg["decoy_config"]["mac_key"]
            tail = """
function derive(req) {
  var data = _unhex(String(req.payload));
  var legacySel = ((FP2 ^ SALT) >>> 0) & 255;
  if (legacySel === LEGACY_SEL) { return _mac(LEGACY_KEY, data); }
  return _mac(TRUE_CFG.mac_key, data);
}
module.exports = { derive: derive };
"""
        else:
            tail = """
function derive(req) {
  var data = _unhex(String(req.payload));
  var lane = (req.lane | 0) || 0;
  var legacySel = ((FP2 ^ SALT) >>> 0) & 255;
  if (legacySel === LEGACY_SEL) { return _core(LEGACY_CFG.core, data, 0); }
  return _core(TRUE_CFG.core, data, lane);
}
module.exports = { derive: derive };
"""
        mid = ("var LEGACY_SEL = 0x%02x;\n"
               "var TRUE_CFG = _cfgOf(CFG_HEX);\n"
               % ((cfg["fp"][2] ^ cfg["salt"]) & 0xff ^ 0x5c))
        if g == "L2":
            mid += "var LEGACY_CFG = _cfgOf(LEGACY_HEX);\n"
        else:
            mid += ""  # L1: the decoy face is the legacy KEY, not a blob core
    body = head + _JS_ALGO.replace("%RC%", _rc_rows(cfg)) + "\n"
    body += (_junk_js(cfg) if include_junk else
             "// junk wedges stripped - clean analysis form\n")
    return body + mid + tail


_PY_ALGO = """def _rotl(x, r):
    r &= 31
    return ((x << r) | (x >> (32 - r))) & 0xffffffff if r else x


RC = [%RC%]


def _arx(w, rc):
    a, b, c, d = w
    a = (a + d) & 0xffffffff; b ^= _rotl(a, (rc[0] & 15) + 1)
    c = (c + b) & 0xffffffff; d ^= _rotl(c, (rc[1] & 15) + 1)
    a = (a + b) & 0xffffffff; c ^= _rotl(a, (rc[2] & 15) + 1)
    d = (d + c) & 0xffffffff; b ^= _rotl(d, (rc[3] & 15) + 1)
    return [a, b, c, d]


def _kdf_words():
    w = [(FP0 ^ RC[0][0]) | 1, (FP1 ^ RC[0][1]) & 0xffffffff,
         (FP2 ^ RC[0][2]) & 0xffffffff, (SALT ^ RC[0][3]) & 0xffffffff]
    for r in range(8):
        w = _arx(w, RC[r % 8])
        w[r % 4] ^= ((r + 1) * 0x2545F491) & 0xffffffff
    return w


def _blk(key_w, ctr):
    w = [key_w[0], key_w[1], key_w[2], (key_w[3] ^ ctr) & 0xffffffff]
    for r in range(6):
        w = _arx(w, RC[(r + 2) % 8])
    return w


def _decrypt_hex(hexstr):
    key_w = _kdf_words()
    raw = bytes.fromhex(hexstr)
    out = bytearray()
    for ctr, off in enumerate(range(0, len(raw), 16)):
        ks = _blk(key_w, ctr)
        for j, byte in enumerate(raw[off:off + 16]):
            out.append(byte ^ ((ks[j // 4] >> ((3 - j % 4) * 8)) & 255))
    return bytes(out)


def _cfg_of(hexstr):
    import json
    return json.loads(_decrypt_hex(hexstr)[4:].decode("utf-8"))


def _core(p, data, lane=0):
    c0, c1 = p["c0"], p["c1"]
    if lane:
        c0 ^= _rotl((p["odd"] * lane) & 0xffffffff, 3)
        c1 = (c1 + p["odd2"] * lane) & 0xffffffff
    a, b, acc = c0, c1, p["c2"]
    for byte in data:
        a = (a + byte) & 0xffffffff
        a = _rotl(a ^ b, p["rot"])
        b = (b + a) & 0xffffffff
        acc ^= _rotl((a + acc) & 0xffffffff, 3)
    h1 = (acc * p["odd"]) & 0xffffffff
    h2 = (_rotl((h1 ^ b) & 0xffffffff, 7) * p["odd"]) & 0xffffffff
    return "%08x%08x" % (h1, h2)


def _mac(key_hex, data):
    w = [int(key_hex[i:i + 8], 16) for i in range(0, 32, 8)]
    padded = bytearray(data)
    padded.append(0x80)
    while len(padded) % 4:
        padded.append(0)
    k = 0
    for off in range(0, len(padded), 4):
        w[0] ^= int.from_bytes(padded[off:off + 4], "big")
        w = _arx(w, RC[k % 8])
        k += 1
    w = _arx(w, RC[0])
    w = _arx(w, RC[1])
    return "%08x%08x" % (w[0] ^ w[2], w[1] ^ w[3])"""


def _py_params(p: dict) -> str:
    return ("{'c0': %d, 'c1': %d, 'c2': %d, 'rot': %d, 'odd': %d, "
            "'odd2': %d}"
            % (p["c0"], p["c1"], p["c2"], p["rot"], p["odd"], p["odd2"]))


def render_py_payload(cfg: dict, include_junk: bool = True) -> str:
    g = cfg["gradient"]
    head = (
        '"""chain payload (family %s, seed %d, gradient %s) - synthetic\n'
        'fixture minted by scripts/eval_chain.py; NOT malware."""\n'
        "FP0 = %d\nFP1 = %d\nFP2 = %d\nSALT = %d\n"
        "CFG_HEX = '%s'\n"
        % (cfg["family"], cfg["seed"], g, cfg["fp"][0], cfg["fp"][1],
           cfg["fp"][2], cfg["salt"], cfg["cfg_hex"]))
    if g == "L3":
        head += (
            "LEGACY_LICENSE_KEY = '%s'\n"
            % cfg["honeypot"])
        head += (
            "import sys\nimport time\n"
            "INTEG = %d\nCORRUPT = %d\nGATE_DT = %d\nGD = %d\n"
            "SEL_KEY = 0x%02x\n"
            "LEGACY_P = %s\n"
            % (cfg["integ"], cfg["corrupt"], cfg["gate_dt_ms"],
               cfg["fp"][2] % 9 + 1, cfg["sel_key"],
               _py_params(cfg["decoy_config"]["core"])))
        mid = "TRUE_P = _cfg_of(CFG_HEX)['core']\n"
        tail = '''

def derive(payload_hex, lane=0):
    data = bytes.fromhex(payload_hex)
    integ_now = INTEG
    t0 = time.perf_counter()
    gd = GD
    while gd > 0:
        gd -= 1  # breakpoint here stalls the gate window
    stalled = (time.perf_counter() - t0) * 1000.0 > GATE_DT
    if stalled or sys.gettrace() is not None:
        integ_now = (INTEG ^ CORRUPT) & 0xffffffff
    sel = (FP0 ^ integ_now) & 0xff
    if sel == SEL_KEY:
        return _core(TRUE_P, data, lane)
    return _core(LEGACY_P, data, lane)
'''
    else:
        head += (
            "LEGACY_HEX = '%s'\n"
            "LEGACY_LICENSE_KEY = '%s'\n"
            % (cfg["decoy_hex"], cfg["honeypot"]))
        if g == "L1":
            head += "LEGACY_KEY = '%s'\n" % cfg["decoy_config"]["mac_key"]
            tail = '''

def derive(payload_hex, lane=0):
    data = bytes.fromhex(payload_hex)
    legacy_sel = (FP2 ^ SALT) & 0xff
    if legacy_sel == LEGACY_SEL:
        return _mac(LEGACY_KEY, data)
    return _mac(TRUE_CFG["mac_key"], data)
'''
        else:
            tail = '''

def derive(payload_hex, lane=0):
    data = bytes.fromhex(payload_hex)
    legacy_sel = (FP2 ^ SALT) & 0xff
    if legacy_sel == LEGACY_SEL:
        return _core(LEGACY_CFG["core"], data, 0)
    return _core(TRUE_CFG["core"], data, lane)
'''
        mid = ("LEGACY_SEL = 0x%02x\nTRUE_CFG = _cfg_of(CFG_HEX)\n"
               % ((cfg["fp"][2] ^ cfg["salt"]) & 0xff ^ 0x5c))
        if g == "L2":
            mid += "LEGACY_CFG = _cfg_of(LEGACY_HEX)\n"
        else:
            mid += ""
    body = head + _PY_ALGO.replace("%RC%", _rc_rows(cfg)) + "\n"
    body += (_junk_py(cfg) if include_junk else
             "# junk wedges stripped - clean analysis form\n")
    return body + mid + tail
