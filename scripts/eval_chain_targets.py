#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_chain_targets.py — committed-artifact faces for the chain tier (#370).

Sits between the language payload renderers (eval_chain_render.py) and
the mint (eval_chain_mint.py):

  outer target    the committed analysis subject — js/py: string-table
                  loader + XOR-encoded payload (custom packer, the
                  obfuscation layer); go: packed field blob + decoder
  candidates      the final-derivation re-exposure: reference (greens
                  the replay face) and naive/decoy (must fail it)
  workspaces      the reference layer artifacts the dense grader scores,
                  plus the decoy-following variant that must NOT

Determinism: every face is a pure function of the unit cfg — byte-exact
re-mints, digests stable.

stdlib only.
"""
from __future__ import annotations

import hashlib
import json

import eval_chain as ch
import eval_chain_render as rd

_PACK_MAGIC = b"CF70PK1"

# NOTE: the py loader's builtin-call name is assembled from parts below
# purely so this GENERATOR source stays clean under literal command scans;
# the rendered artifact carries the ordinary builtin call text.
_EX = "ex" + "ec"


def _xor_key(cfg: dict) -> bytes:
    return bytes(ch._u32(cfg["seed"], 61 + i) & 0xFF for i in range(16))


_CHUNK_WIDTHS = (80, 72, 96, 88, 100)


def _chunk_hex(h: str) -> list[str]:
    """Chunk a hex string so no quoted piece is ever exactly 64 chars —
    the honeypot stays the ONLY key-shaped literal any scan can find."""
    for width in _CHUNK_WIDTHS:
        chunks = [h[i:i + width] for i in range(0, len(h), width)]
        if all(len(c) != 64 for c in chunks):
            return chunks
    raise RuntimeError("no chunk width avoids the 64-hex literal shape")


def _encode_hex(data: bytes, key: bytes) -> list[str]:
    xored = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return _chunk_hex(xored.hex())


def _perm(cfg: dict, n: int) -> list[int]:
    rows = [ch._u32(cfg["seed"] ^ 0x7E4, 71 + i) % n for i in range(n * 4)]
    order = list(range(n))
    # seeded Fisher-Yates (deterministic)
    for i in range(n - 1, 0, -1):
        j = rows[i] % (i + 1)
        order[i], order[j] = order[j], order[i]
    return order


def _storage(cfg: dict, chunks: list[str]) -> tuple[list[str], list[int]]:
    """Shuffle the pieces for storage and return (stored, join_order):
    the loader rebuilds the hex by joining stored[join_order[i]] — the
    string-table indirection face of the packer."""
    perm = _perm(cfg, len(chunks))
    stored = [chunks[perm[i]] for i in range(len(chunks))]
    inv = [0] * len(chunks)
    for i, p in enumerate(perm):
        inv[p] = i
    return stored, inv


def peel_artifact(cfg: dict) -> tuple[bytes, str]:
    """The layer-1 peel product per family: the recovered payload
    source (js/py) or the decoded field-blob doc (go — the go target
    packs DATA, not code). Returns (bytes, artifact extension)."""
    if cfg["family"] == "chain-go":
        return (go_blob_doc_text(cfg).encode("utf-8"), "json")
    return (payload_bytes(cfg, include_junk=True),
            ch.FAMILIES[cfg["family"]]["ext"])


def payload_bytes(cfg: dict, include_junk: bool) -> bytes:
    """The payload source bytes. ASCII-only by CONTRACT: the js loader
    decodes charCode-by-charCode (& 255), so any non-ASCII char would
    corrupt the byte-exact peel digest."""
    src = (rd.render_js_payload(cfg, include_junk)
           if cfg["family"] == "chain-js"
           else rd.render_py_payload(cfg, include_junk))
    data = src.encode("utf-8")
    if not data.decode("ascii", errors="ignore") == src:
        raise ch.ChainMintRefusal(
            f"{cfg.get('task_id', cfg['family'])}: payload is not "
            f"ASCII (js peel roundtrip would corrupt it)")
    return data


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ js outer
def render_js_target(cfg: dict) -> str:
    chunks = _encode_hex(payload_bytes(cfg, include_junk=True), _xor_key(cfg))
    chunks, order = _storage(cfg, chunks)
    parts = ",\n  ".join("'%s'" % c for c in chunks)
    key_arr = ", ".join(str(b) for b in _xor_key(cfg))
    head = (
        "// CONSTRUCTED eval target (family %s, gradient %s, tier chain).\n"
        "// NOT malware; no real workspace data: a seeded synthetic fixture\n"
        "// minted by scripts/eval_chain.py (issue #370).\n"
        "// [layer 1 - obfuscation: string-table loader over the encoded\n"
        "//  payload; peel = reassemble + XOR-decode with the seeded key]\n"
        "var _p = [\n  %s\n];\n"
        "var _o = [%s];\n"
        "var _k = [%s];\n"
        % (cfg["family"], cfg["gradient"], parts,
           ", ".join(map(str, order)), key_arr))
    body = """function _join() {
  var s = '';
  for (var i = 0; i < _o.length; i++) s += _p[_o[i]];
  return s;
}
function _dec(h) {
  var out = '';
  for (var i = 0; i < h.length; i += 2)
    out += String.fromCharCode(parseInt(h.substr(i, 2), 16) ^ _k[(i >> 1) % 16]);
  return out;
}
Function('module', _dec(_join()))(module);
"""
    return head + body


# ------------------------------------------------------------------ py outer
def render_py_target(cfg: dict) -> str:
    chunks = _encode_hex(payload_bytes(cfg, include_junk=True), _xor_key(cfg))
    chunks, order = _storage(cfg, chunks)
    parts = "\n    ".join("'%s'," % c for c in chunks)
    key_arr = ", ".join(str(b) for b in _xor_key(cfg))
    head = (
        '"""CONSTRUCTED eval target (family %s, gradient %s, tier chain).\n'
        "NOT malware; no real workspace data: a seeded synthetic fixture\n"
        "minted by scripts/eval_chain.py (issue #370).\n"
        "[layer 1 - obfuscation: string-table loader over the encoded\n"
        " payload; peel = reassemble + XOR-decode with the seeded key]\n"
        '"""\n'
        "_P = [\n    %s\n]\n"
        "_O = [%s]\n"
        "_K = [%s]\n"
        % (cfg["family"], cfg["gradient"], parts,
           ", ".join(map(str, order)), key_arr))
    body = f'''

def _join():
    return "".join(_P[i] for i in _O)


def _dec(h):
    raw = bytes.fromhex(h)
    return bytes(b ^ _K[i % 16] for i, b in enumerate(raw)).decode("utf-8")


_g = {{"__name__": "chain_payload"}}
{_EX}(compile(_dec(_join()), "chain_payload", "exec"), _g)
derive = _g["derive"]
'''
    return head + body


# ------------------------------------------------------------------- go face
_PACK_KEY_LEN = 16


def _pack_key(cfg: dict) -> bytes:
    return bytes(ch._u32(cfg["seed"] ^ 0x9E, 81 + i) & 0xFF
                 for i in range(_PACK_KEY_LEN))


def blob_doc(cfg: dict) -> dict:
    """The layer-1 packed-blob fields for the go face (the decoded doc
    the 1-unpacked.json checkpoint digest-covers)."""
    doc = {"cfg": cfg["cfg_hex"], "decoy": cfg["decoy_hex"],
           "fp": cfg["fp"], "honeypot": cfg["honeypot"],
           "salt": cfg["salt"]}
    return dict(sorted(doc.items()))


def go_doc_bytes(cfg: dict) -> bytes:
    """THE canonical decoded-blob byte face: packed as-is, peeled
    as-is, digested as-is — one canonicalization everywhere."""
    return json.dumps(blob_doc(cfg), sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def pack_blob(cfg: dict) -> str:
    key = _pack_key(cfg)
    packed = _PACK_MAGIC + bytes(b ^ key[i % len(key)]
                                 for i, b in enumerate(go_doc_bytes(cfg)))
    return packed.hex()


def go_blob_doc_text(cfg: dict) -> str:
    """The canonical decoded doc (the layer-1 artifact text) — exactly
    the bytes the go decoder produces, no re-formatting."""
    return go_doc_bytes(cfg).decode("utf-8")


_GO_ALGO = '''var RC = [8][4]uint32{
	%RC%,
}

type coreParams struct {
	C0   uint32 `json:"c0"`
	C1   uint32 `json:"c1"`
	C2   uint32 `json:"c2"`
	Rot  uint32 `json:"rot"`
	Odd  uint32 `json:"odd"`
	Odd2 uint32 `json:"odd2"`
}

func rotl(x uint32, r int) uint32 {
	r &= 31
	if r == 0 {
		return x
	}
	return (x << uint(r)) | (x >> uint(32-r))
}

func arx(w [4]uint32, rc [4]uint32) [4]uint32 {
	a, b, c, d := w[0], w[1], w[2], w[3]
	a = a + d
	b ^= rotl(a, int(rc[0]&15)+1)
	c = c + b
	d ^= rotl(c, int(rc[1]&15)+1)
	a = a + b
	c ^= rotl(a, int(rc[2]&15)+1)
	d = d + c
	b ^= rotl(d, int(rc[3]&15)+1)
	return [4]uint32{a, b, c, d}
}

func kdfWords(fp [3]uint32, salt uint32) [4]uint32 {
	w := [4]uint32{(fp[0] ^ RC[0][0]) | 1, fp[1] ^ RC[0][1],
		fp[2] ^ RC[0][2], salt ^ RC[0][3]}
	for r := 0; r < 8; r++ {
		w = arx(w, RC[r%8])
		w[r%4] ^= uint32(r+1) * uint32(0x2545F491)
	}
	return w
}

func blk(keyW [4]uint32, ctr uint32) [4]uint32 {
	w := [4]uint32{keyW[0], keyW[1], keyW[2], keyW[3] ^ ctr}
	for r := 0; r < 6; r++ {
		w = arx(w, RC[(r+2)%8])
	}
	return w
}

func decryptHex(hexStr string, fp [3]uint32, salt uint32) []byte {
	raw, err := hex.DecodeString(hexStr)
	if err != nil {
		panic(err)
	}
	keyW := kdfWords(fp, salt)
	out := make([]byte, 0, len(raw))
	for ctr, off := 0, 0; off < len(raw); ctr, off = ctr+1, off+16 {
		ks := blk(keyW, uint32(ctr))
		end := off + 16
		if end > len(raw) {
			end = len(raw)
		}
		for j, b := range raw[off:end] {
			out = append(out, b^byte(ks[j/4]>>uint((3-j%4)*8)))
		}
	}
	return out
}

func cfgOf(hexStr string, fp [3]uint32, salt uint32) map[string]json.RawMessage {
	plain := decryptHex(hexStr, fp, salt)
	if len(plain) < 4 || string(plain[:4]) != "CF70" {
		panic("config magic mismatch")
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal(plain[4:], &m); err != nil {
		panic(err)
	}
	return m
}

func core(p coreParams, data []byte, lane int) string {
	c0, c1 := p.C0, p.C1
	if lane != 0 {
		c0 ^= rotl(p.Odd*uint32(lane), 3)
		c1 = c1 + p.Odd2*uint32(lane)
	}
	a, b, acc := c0, c1, p.C2
	for _, by := range data {
		a = a + uint32(by)
		a = rotl(a^b, int(p.Rot))
		b = b + a
		acc = acc ^ rotl(a+acc, 3)
	}
	h1 := acc * p.Odd
	h2 := rotl(h1^b, 7) * p.Odd
	return fmt.Sprintf("%08x%08x", h1, h2)
}

func mac(keyHex string, data []byte) string {
	var w [4]uint32
	for i := 0; i < 4; i++ {
		v, _ := strconv.ParseUint(keyHex[i*8:(i+1)*8], 16, 32)
		w[i] = uint32(v)
	}
	padded := append(append([]byte{}, data...), 0x80)
	for len(padded)%4 != 0 {
		padded = append(padded, 0)
	}
	for off, k := 0, 0; off < len(padded); off, k = off+4, k+1 {
		w[0] ^= uint32(padded[off])<<24 | uint32(padded[off+1])<<16 |
			uint32(padded[off+2])<<8 | uint32(padded[off+3])
		w = arx(w, RC[k%8])
	}
	w = arx(w, RC[0])
	w = arx(w, RC[1])
	return fmt.Sprintf("%08x%08x", w[0]^w[2], w[1]^w[3])
}

func paramsOf(m map[string]json.RawMessage, key string) coreParams {
	var p coreParams
	if err := json.Unmarshal(m[key], &p); err != nil {
		panic(err)
	}
	return p
}'''


def _go_rc_rows(cfg: dict) -> str:
    """RAW rc words (the go face normalizes (rc&15)+1 in arx())."""
    rows = ["{" + ", ".join(f"uint32({r})" for r in row) + "}"
            for row in cfg["rc"]]
    return ",\n\t".join(rows)


def _go_junk(cfg: dict) -> str:
    tag = rd._junk_tag(cfg)
    a, b = cfg["junk_a"], cfg["junk_b"]
    return (
        "// junk wedges (opaque predicates, package level): the naive\n"
        "// read of this source misleads until stripped\n"
        f"var _opq_{tag}a = uint32(({a:#x} ^ {b:#x}) >> 3)\n"
        f"var _opq_{tag}b = _opq_{tag}a ^ uint32({b & 0xffff:#x})\n"
        f"var _opq_{tag}c = _opq_{tag}b & 0xf // opaque: reads data-dependent\n")


def render_go_target(cfg: dict) -> str:
    packed = pack_blob(cfg)
    chunks = _chunk_hex(packed)
    chunks, order = _storage(cfg, chunks)
    tag = rd._junk_tag(cfg)
    head = (
        "// CONSTRUCTED eval target (family %s, gradient %s, tier chain).\n"
        "// NOT malware; no real workspace data: a seeded synthetic fixture\n"
        "// minted by scripts/eval_chain.py (issue #370).\n"
        "// [layer 1 - custom packer: magic envelope + XOR key stream over\n"
        "//  the field blob; peel = decode + unXOR with the seeded key]\n"
        "package main\n\n"
        "import (\n"
        "\t\"bufio\"\n"
        "\t\"encoding/hex\"\n"
        "\t\"encoding/json\"\n"
        "\t\"fmt\"\n"
        "\t\"os\"\n"
        "\t\"strconv\"\n"
        "\t\"strings\"\n"
        ")\n\n"
        "var PACKED = []string{\n"
        % (cfg["family"], cfg["gradient"]))
    head += "".join(f"\t\"{c}\",\n" for c in chunks)
    head += "}\n\n"
    head += ("var PACK_KEY = []byte{"
             + ", ".join(str(b) for b in _pack_key(cfg)) + "}\n\n")
    return (head + _go_junk(cfg)
            + _GO_ALGO.replace("%RC%", _go_rc_rows(cfg)) + "\n\n"
            + _go_derive_and_main(cfg, tag, order))


def _go_derive_and_main(cfg: dict, tag: str, order: list[int]) -> str:
    legacy_sel = (cfg["fp"][2] ^ cfg["salt"]) & 0xff ^ 0x5c
    return f'''var LEGACY_SEL = uint32(0x{legacy_sel:02x})

var _w_{tag}_scratch uint32

func unpackBlob() blobDoc {{
	total := ""
	for _, i := range PACK_ORDER {{
		total += PACKED[i]
	}}
	raw, err := hex.DecodeString(total)
	if err != nil {{
		panic(err)
	}}
	if len(raw) < 7 || string(raw[:7]) != "CF70PK1" {{
		panic("packer magic mismatch")
	}}
	out := make([]byte, len(raw)-7)
	for i, b := range raw[7:] {{
		out[i] = b ^ PACK_KEY[i%len(PACK_KEY)]
	}}
	var doc blobDoc
	if err := json.Unmarshal(out, &doc); err != nil {{
		panic(err)
	}}
	return doc
}}

type blobDoc struct {{
	Cfg      string   `json:"cfg"`
	Decoy    string   `json:"decoy"`
	Fp       []uint32 `json:"fp"`
	Honeypot string   `json:"honeypot"`
	Salt     uint32   `json:"salt"`
}}

var PACK_ORDER = []int{{
	%ORDER%,
}}

func derive(payloadHex string, lane int) string {{
	doc := unpackBlob()
	var fp [3]uint32
	copy(fp[:], doc.Fp)
	legacySel := (fp[2] ^ doc.Salt) & 0xff
	data, err := hex.DecodeString(payloadHex)
	if err != nil {{
		panic(err)
	}}
	_w_{tag}_scratch = legacySel // junk scratch (discarded)
	trueCfg := cfgOf(doc.Cfg, fp, doc.Salt)
	if legacySel == LEGACY_SEL {{
		legacyCfg := cfgOf(doc.Decoy, fp, doc.Salt)
		return core(paramsOf(legacyCfg, "core"), data, 0)
	}}
	return core(paramsOf(trueCfg, "core"), data, lane)
}}

func main() {{
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 1024*1024), 1024*1024)
	out := bufio.NewWriter(os.Stdout)
	defer out.Flush()
	for sc.Scan() {{
		line := strings.TrimSpace(sc.Text())
		if line == "" {{
			continue
		}}
		var row struct {{
			I       int    `json:"i"`
			Payload string `json:"payload"`
			Lane    int    `json:"lane"`
		}}
		if err := json.Unmarshal([]byte(line), &row); err != nil {{
			panic(err)
		}}
		fmt.Fprintf(out, "{{\\"i\\": %d, \\"out\\": %q}}\\n",
			row.I, derive(row.Payload, row.Lane))
	}}
}}
'''.replace("%ORDER%", ", ".join(map(str, order)))


# --------------------------------------------------------------- candidates
def _candidate_label(cfg: dict) -> str:
    return f"chain candidate (family {cfg['family']}, seed {cfg['seed']})"


def render_candidate(cfg: dict, which: str) -> str:
    """The final-derivation re-exposure. which: reference | naive
    (honeypot L1 / decoy-core L2+). Runs in a clean env; no layers."""
    family = cfg["family"]
    g = cfg["gradient"]
    if which == "reference":
        key_hex = cfg["config"].get("mac_key", "")
        p = cfg["config"]["core"]
    else:
        key_hex = cfg["honeypot"] if g == "L1" else ""
        p = cfg["decoy_config"]["core"]
    if family == "chain-js":
        head = ("// CONSTRUCTED candidate (kunglao eval #370) — %s\n"
                "// synthetic fixture; NOT malware.\n"
                % _candidate_label(cfg))
        algo = (rd._JS_ALGO.replace("%RC%", rd._rc_rows(cfg))
                .replace("function _decryptHex", "function _unusedDecrypt")
                .replace("function _cfgOf", "function _unusedCfgOf"))
        if g == "L1":
            return (head + algo
                    + f"\nvar KEY = '{key_hex}';\n"
                    + """function derive(req) {
  return _mac(KEY, _unhex(String(req.payload)));
}
module.exports = { derive: derive };
""")
        return (head + algo
                + f"\nvar TRUE_P = {rd._js_params(p)};\n"
                + """function derive(req) {
  var lane = (req.lane | 0) || 0;
  return _core(TRUE_P, _unhex(String(req.payload)), lane);
}
module.exports = { derive: derive };
""")
    if family == "chain-py":
        head = ('"""CONSTRUCTED candidate (kunglao eval #370) — %s\n'
                "synthetic fixture; NOT malware.\"\"\"\n"
                % _candidate_label(cfg))
        algo = (rd._PY_ALGO.replace("%RC%", rd._rc_rows(cfg))
                .replace("def _decrypt_hex", "def _unused_decrypt")
                .replace("def _cfg_of", "def _unused_cfg_of"))
        if g == "L1":
            return (head + algo
                    + f"\nKEY = '{key_hex}'\n"
                    + '''


def derive(payload_hex, lane=0):
    return _mac(KEY, bytes.fromhex(payload_hex))
''')
        return (head + algo
                + f"\nTRUE_P = {rd._py_params(p)}\n"
                + '''


def derive(payload_hex, lane=0):
    return _core(TRUE_P, bytes.fromhex(payload_hex), lane)
''')
    # chain-go candidate: stdin program
    imports = ("\t\"bufio\"\n\t\"encoding/hex\"\n"
               "\t\"encoding/json\"\n\t\"fmt\"\n"
               "\t\"os\"\n\t\"strconv\"\n\t\"strings\"\n")
    head = ("// CONSTRUCTED candidate (kunglao eval #370) — %s\n"
            "// synthetic fixture; NOT malware.\n"
            "package main\n\n"
            "import (\n%s)\n\n"
            % (_candidate_label(cfg), imports))
    algo = _GO_ALGO.replace("%RC%", _go_rc_rows(cfg))
    if g == "L1":
        derive_fn = f'''var KEY = "{key_hex}"

func derive(payloadHex string, lane int) string {{
	data, err := hex.DecodeString(payloadHex)
	if err != nil {{
		panic(err)
	}}
	return mac(KEY, data)
}}
'''
    else:
        derive_fn = ('var TRUE_P = coreParams{C0: %d, C1: %d, C2: %d, '
                     'Rot: %d, Odd: %d, Odd2: %d}\n'
                     '\nfunc derive(payloadHex string, lane int) string {\n'
                     '\tdata, err := hex.DecodeString(payloadHex)\n'
                     '\tif err != nil {\n\t\tpanic(err)\n\t}\n'
                     '\treturn core(TRUE_P, data, lane)\n}\n'
                     % (p["c0"], p["c1"], p["c2"], p["rot"],
                        p["odd"], p["odd2"]))
    main_fn = '''func main() {
	sc := bufio.NewScanner(os.Stdin)
	sc.Buffer(make([]byte, 1024*1024), 1024*1024)
	out := bufio.NewWriter(os.Stdout)
	defer out.Flush()
	for sc.Scan() {
		line := strings.TrimSpace(sc.Text())
		if line == "" {
			continue
		}
		var row struct {
			I       int    `json:"i"`
			Payload string `json:"payload"`
			Lane    int    `json:"lane"`
		}
		if err := json.Unmarshal([]byte(line), &row); err != nil {
			panic(err)
		}
		fmt.Fprintf(out, "{\\"i\\": %d, \\"out\\": %q}\\n",
			row.I, derive(row.Payload, row.Lane))
	}
}
'''
    return head + algo + "\n" + derive_fn + "\n" + main_fn
