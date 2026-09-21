#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_targets.py — constructed-target generator (the eval-dataset card) (smoke tier, eval-v1).

Parametric variants of known mechanism families with ground truth BY
CONSTRUCTION: one python model per family both renders the target source
and computes the reference outputs, so the captured pairs can never drift
from the artifact they were captured from (no dual maintenance, no real
workspace data — every constant is minted from a seed).

Families (the three smoke-tier mechanism families):
  go-arx     ~30-line SHA-1-family KDF: mutated K0 / golden constant /
             rotation base + a toy ARX step. Oracles: constant-hit
             (static: the mutated constants must appear in a candidate's
             source) + pair-match (reproduction: a re-implementation must
             reproduce the captured pairs).
  js-sign    small obfuscated-style signer bundle (hex identifiers, a
             string table, decoy constants) around two mutated 32-bit
             round constants. Oracles: constant-hit + replay-roundtrip
             through the exposed sign().
  py-derive  pure-algo 64-bit derivation (FNV-shaped with an avalanche
             fold) over three mutated 64-bit parameters. Oracle:
             replay-roundtrip on deterministic probes.

Anti-memorization: variants differ by mutated constants (an answer
memorized from the canonical family members — stock SHA-1 constants, stock
FNV primes — is wrong by construction; the checker-minted probes defeat
digest-table copying on the js/py replay faces).

The minted task unit is the eval-task schema instantiated:
task.yaml + target/ + ground_truth.json + a checker.py shim that makes the
unit standalone-runnable (the bare-LLM control arm's entry surface).

CLI (regeneration / eval-v2 churn; the landed eval-v1 corpus was minted
with exactly these seeds):
  python scripts/eval_targets.py --root eval/v1/tasks/smoke \
      --mint go-arx:29901:go-arx-v1 --mint js-sign:29902:js-sign-v1 \
      --mint py-derive:29903:py-derive-v1

stdlib only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

# canonical family members a lazy/memorizing candidate would reach for —
# the generator REFUSES to mint them (divergence is the anti-memorization
# property, asserted per variant at mint time)
CANONICAL_K0 = 0x5A827999
CANONICAL_GOLDEN = 0x9E3779B9

M32 = 0xFFFFFFFF
M64 = 0xFFFFFFFFFFFFFFFF

SCHEMA_TASK = "kunglao-eval-task/1"
SCHEMA_GROUND_TRUTH = "kunglao-eval-ground-truth/1"

# family registry: toolchain (checker replay face), target filename,
# candidate contract anchor
FAMILIES: dict[str, dict] = {
    "go-arx": {
        "toolchain": "go",
        "target": "target/sample_kdf.go",
        "language": "go",
        "task_id": "go-arx-v1",
        "seed": 29901,
        "space_bits": 96,
        "kind": "pair-match",
        "oracles": ["constant-hit", "pair-match"],
        "thresholds": {"min_constant_hits": 3, "min_pair_ratio": 0.75},
    },
    "js-sign": {
        "toolchain": "node",
        "target": "target/sign_bundle.js",
        "language": "javascript",
        "task_id": "js-sign-v1",
        "seed": 29902,
        "space_bits": 64,
        "kind": "replay-roundtrip",
        "oracles": ["constant-hit", "replay-roundtrip"],
        "thresholds": {"min_constant_hits": 2, "min_pair_ratio": 1.0},
    },
    "py-derive": {
        "toolchain": "python3",
        "target": "target/derive.py",
        "language": "python",
        "task_id": "py-derive-v1",
        "seed": 29903,
        "space_bits": 192,
        "kind": "replay-roundtrip",
        "oracles": ["replay-roundtrip"],
        "thresholds": {"min_pair_ratio": 1.0},
    },
}


# ------------------------------------------------------------ deterministic rng
def _splitmix32(x: int) -> int:
    """SplitMix32 finalizer — a pure function, so every derived constant is
    stable across python versions and machines (no RNG module state)."""
    x = (x + 0x9E3779B9) & M32
    z = x
    z = ((z ^ (z >> 16)) * 0x21F0AAAD) & M32
    z = ((z ^ (z >> 15)) * 0x735A2D97) & M32
    return (z ^ (z >> 15)) & M32


def _u32(seed: int, lane: int) -> int:
    v = _splitmix32((seed ^ (lane * 0x85EBCA6B)) & M32) | 1  # odd, nonzero
    return v & M32


def _u64(seed: int, lane: int) -> int:
    return ((_u32(seed, lane) << 32) | _u32(seed ^ 0xDEADBEEF, lane)) & M64


# ------------------------------------------------------------------ configs
def derive_cfg(family: str, seed: int) -> dict:
    """The per-variant constant set (the ground truth by construction)."""
    if family == "go-arx":
        k0, z, rot_base = _u32(seed, 1), _u32(seed, 2), _u32(seed, 3)
        # refuse the canonical SHA-1-family members: memorizing the stock
        # constants must score zero, so the variant must not be one
        while k0 == CANONICAL_K0:
            k0 = _u32(k0, 1)
        while z == CANONICAL_GOLDEN:
            z = _u32(z, 2)
        return {"k0": k0, "z": z, "rot_base": rot_base}
    if family == "js-sign":
        c1, c2 = _u32(seed, 1), _u32(seed, 2)
        d1, d2 = _u32(seed, 3), _u32(seed, 4)
        while d1 in (c1, c2):
            d1 = _u32(d1, 3)
        while d2 in (c1, c2, d1):
            d2 = _u32(d2, 4)
        return {"c1": c1, "c2": c2, "decoys": [d1, d2]}
    if family == "py-derive":
        return {"offset": _u64(seed, 1), "prime": _u64(seed, 2),
                "fold": _u64(seed, 3)}
    raise ValueError(f"unknown family: {family}; valid: {sorted(FAMILIES)}")


def _rotl32(x: int, r: int) -> int:
    r %= 32
    return ((x << r) | (x >> (32 - r))) & M32 if r else x & M32


# ------------------------------------------------------------------- models
# ONE python model per family: the same function computes the reference
# outputs (ground truth) and documents the transform the renderer emits —
# construction, not capture.
def go_model(cfg: dict, i: int, x: int) -> int:
    t = ((i + 1) * cfg["rot_base"]) & M32
    r = (i % 31) + 1
    return ((x + _rotl32(t, r) + cfg["z"]) & M32) ^ cfg["k0"]


def js_model(cfg: dict, data: bytes) -> str:
    h = cfg["c1"]
    for b in data:
        h = (h ^ b) & M32
        h = _rotl32(h, 5)
        h = (h + cfg["c2"]) & M32
    h = (h ^ (h >> 16)) & M32
    return f"{h:08x}"


def py_model(cfg: dict, data: bytes) -> int:
    h = cfg["offset"]
    for b in data:
        h = ((h ^ b) * cfg["prime"]) & M64
    h ^= h >> 31
    h = (h * cfg["fold"]) & M64
    h ^= h >> 29
    return h


def model_output(family: str, cfg: dict, i: int, x):
    if family == "go-arx":
        xin = x[0] if isinstance(x, list) else x  # pairs store input as [x]
        return go_model(cfg, i, xin)
    if family == "js-sign":
        return js_model(cfg, bytes(x))
    if family == "py-derive":
        return py_model(cfg, bytes(x))
    raise ValueError(f"unknown family: {family}")


# -------------------------------------------------------------- probe minting
GO_INPUT_FORMULA = "params[i] = uint32(i)*2654435761 + 1"


def go_inputs(count: int) -> list[int]:
    return [(i * 2654435761 + 1) & M32 for i in range(count)]


def minted_probes(family: str, seed: int, count: int) -> list[dict]:
    """Checker-minted probes: fresh inputs derived from the variant seed —
    the anti-digest-table face (a candidate hardcoding the PUBLISHED
    pairs passes those and fails these, by construction). Inputs are
    stored nowhere; the checker recomputes them (and the expected
    outputs) from the seed model at run time."""
    probes = []
    for k in range(count):
        if family == "go-arx":
            data = [_u32(seed ^ 0x5EED, k + 1)]  # one uint32 per probe
        else:
            raw = _u64(seed ^ 0x5EED, k + 1).to_bytes(8, "big")
            if family == "js-sign":
                data = list(raw[:6])  # 6-byte inputs (byte-level sign)
            else:
                data = list(raw)  # py face: the full 8 bytes
        probes.append({"i": 100 + k, "input": data})
    return probes


def published_pairs(family: str, cfg: dict, count: int) -> list[dict]:
    if family == "go-arx":
        return [{"i": i, "input": [x], "out": go_model(cfg, i, x)}
                for i, x in enumerate(go_inputs(count))]
    fn = js_model if family == "js-sign" else py_model
    fixed = minted_probes(family, 0, count)  # published face: stable inputs
    # published pairs take i = 0..N-1; checker-minted probes take i >= 100
    # (disjoint keys — the keyed comparison never aliases the two faces)
    return [{"i": k, "input": p["input"], "out": fn(cfg, bytes(p["input"]))}
            for k, p in enumerate(fixed)]


# ------------------------------------------------------------------ renderers
def render_go(cfg: dict) -> str:
    return f'''// sample_kdf.go — CONSTRUCTED eval target (family go-arx, eval-v1).
// NOT malware; no real workspace data: every constant below is a seeded
// mutation of the SHA-1-family mechanism shape, minted by eval_targets.py.
//
// Recover the three embedded constants and re-implement the pipeline:
//   out = ((in + rotl32((i+1)*rotBase, (i%31)+1) + z) mod 2^32) XOR k0
// The published capture pins the fixed face
//   {GO_INPUT_FORMULA}
// but the program is INPUT-AGNOSTIC: it reads one JSON object per line on
// stdin ({{"i": N, "in": X}}) and prints one per line
// ({{"i": N, "in": X, "out": Y}}) — the checker drives freshly minted
// inputs through it, so a PASS requires the actual derivation (a
// constants+lookup shortcut fails on inputs it never saw).
package main

import (
\t"bufio"
\t"encoding/json"
\t"fmt"
\t"os"
)

const (
\tk0      uint32 = 0x{cfg["k0"]:08x}
\tz       uint32 = 0x{cfg["z"]:08x}
\trotBase uint32 = 0x{cfg["rot_base"]:08x}
)

func rotl32(x uint32, r uint) uint32 {{
\treturn (x << r) | (x >> (32 - r))
}}

func arxStep(x, t uint32, i uint) uint32 {{
\treturn ((x + rotl32(t, (i%31)+1) + z) & 0xffffffff) ^ k0
}}

func main() {{
\tsc := bufio.NewScanner(os.Stdin)
\tsc.Buffer(make([]byte, 64*1024), 1024*1024)
\tw := bufio.NewWriter(os.Stdout)
\tdefer w.Flush()
\tfor sc.Scan() {{
\t\tvar req struct {{
\t\t\tI  int    `json:"i"`
\t\t\tIn uint32 `json:"in"`
\t\t}}
\t\tif err := json.Unmarshal(sc.Bytes(), &req); err != nil {{
\t\t\tcontinue
\t\t}}
\t\tout := arxStep(req.In, (uint32(req.I)+1)*rotBase, uint(req.I))
\t\tfmt.Fprintf(w, "{{\\"i\\": %d, \\"in\\": %d, \\"out\\": %d}}\\n",
\t\t\treq.I, req.In, out)
\t}}
}}
'''


def render_js(cfg: dict) -> str:
    d1, d2 = cfg["decoys"]
    return f'''// sign_bundle.js — #299 CONSTRUCTED eval target (family js-sign, eval-v1).
// NOT malware; no real workspace data: an obfuscated-style signer bundle
// seeded by eval_targets.py. Two of the four 32-bit constants below are
// load-bearing (C1, C2); the D-constants are decoys.
// Contract: module.exports.sign(inputString) -> 8-hex-char lowercase.
var _0x4b = ['round', 'fold'];
var C1 = 0x{cfg["c1"]:08x};
var C2 = 0x{cfg["c2"]:08x};
var D1 = 0x{d1:08x};
var D2 = 0x{d2:08x};

function _0x2f(h, b) {{
  h = (h ^ b) >>> 0;
  h = ((h << 5) | (h >>> 27)) >>> 0;
  return (h + C2) >>> 0;
}}

function _0x7a(h) {{
  return (((h ^ (h >>> 16)) >>> 0) + D2 * 0) >>> 0;
}}

function sign(input) {{
  var h = C1;
  for (var i = 0; i < input.length; i++) {{
    h = _0x2f(h, input.charCodeAt(i) & 0xff);
  }}
  h = _0x7a(h);
  return ('00000000' + h.toString(16)).slice(-8);
}}

module.exports = {{ sign: sign, _table: _0x4b }};

if (typeof require !== 'undefined' && require.main === module) {{
  console.log(JSON.stringify({{ in: 'alpha', out: sign('alpha') }}));
  console.log(JSON.stringify({{ in: 'bravo', out: sign('bravo') }}));
}}
'''


def render_py(cfg: dict) -> str:
    return f'''# derive.py — #299 CONSTRUCTED eval target (family py-derive, eval-v1).
# NOT malware; no real workspace data: a pure-algo 64-bit derivation seeded
# by eval_targets.py. Recover the three parameters and re-implement
# derive(data: bytes) -> int so it reproduces the reference outputs.
OFFSET = 0x{cfg["offset"]:016x}
PRIME = 0x{cfg["prime"]:016x}
FOLD = 0x{cfg["fold"]:016x}

_M64 = (1 << 64) - 1


def derive(data: bytes) -> int:
    h = OFFSET
    for b in data:
        h = ((h ^ b) * PRIME) & _M64
    h ^= h >> 31
    h = (h * FOLD) & _M64
    h ^= h >> 29
    return h


if __name__ == "__main__":
    for probe in (b"alpha", b"bravo"):
        print(probe.hex(), derive(probe))
'''


RENDERERS = {"go-arx": render_go, "js-sign": render_js, "py-derive": render_py}


# --------------------------------------------------------------- unit minting
_ANCHORS = {
    "go-arx": {
        "goal_verbatim": (
            "Recover the three mutated constants embedded in "
            "target/sample_kdf.go and re-implement the KDF pipeline so that "
            "it reproduces the captured input/output pairs byte-exact."),
        "success_criterion": (
            "A re-implementation carrying the three recovered constants that "
            "reproduces the 16 captured pairs and the checker-minted stdin "
            "probes."),
        "verification_method": "reproduction",
    },
    "js-sign": {
        "goal_verbatim": (
            "Deobfuscate target/sign_bundle.js, recover the two load-bearing "
            "round constants (ignore the decoys), and re-expose a sign() that "
            "reproduces the captured (input, output) pairs."),
        "success_criterion": (
            "A sign() re-implementation carrying the two recovered constants "
            "that reproduces every captured and checker-minted pair."),
        "verification_method": "reproduction",
    },
    "py-derive": {
        "goal_verbatim": (
            "Recover the three parameters of the derivation in "
            "target/derive.py and re-implement derive(data) -> int so it "
            "reproduces the reference outputs on arbitrary inputs."),
        "success_criterion": (
            "A derive() re-implementation that reproduces every published and "
            "checker-minted probe output exactly."),
        "verification_method": "reproduction",
    },
}

_CANDIDATE_CONTRACT = {
    "go-arx": ("A Go program that is INPUT-AGNOSTIC: reads one JSON object "
               "per line from stdin ({\"i\": N, \"in\": X}) and prints one "
               "JSON object per line ({\"i\": N, \"in\": X, \"out\": Y}) "
               "with out = the pipeline applied to in. The published capture "
               "(" + GO_INPUT_FORMULA + ") is the fixed face; the checker "
               "additionally drives freshly minted stdin probes, so a PASS "
               "requires the actual derivation — a constants+lookup shortcut "
               "fails on inputs it never saw."),
    "js-sign": ("A Node module exporting sign(inputString) -> 8-hex-char "
                "lowercase string."),
    "py-derive": ("A Python module exposing derive(data: bytes) -> int."),
}

_GOAL_NOTE = {
    "go-arx": ("pair-match tolerance keeps the case-admission C2 shape "
               "(>= 20 of 26); the minted stdin probes close the "
               "constants+table shortcut."),
    "js-sign": "round-trip face runs the exposed sign() over published + minted probes.",
    "py-derive": "round-trip face runs derive() over published + checker-minted probes.",
}


def _published_count(family: str) -> int:
    return {"go-arx": 16, "js-sign": 10, "py-derive": 12}[family]


def _minted_count(family: str) -> int:
    return {"go-arx": 10, "js-sign": 10, "py-derive": 12}[family]


def _constants_public(family: str, cfg: dict) -> dict:
    if family == "go-arx":
        return {"k0": cfg["k0"], "z": cfg["z"], "rot_base": cfg["rot_base"]}
    if family == "js-sign":
        return {"c1": cfg["c1"], "c2": cfg["c2"]}
    return {"offset": cfg["offset"], "prime": cfg["prime"], "fold": cfg["fold"]}


def build_task_unit(family: str, seed: int, task_id: str) -> dict:
    """Everything the unit needs, in memory: task.yaml payload, target
    source, ground_truth payload, checker shim."""
    meta = FAMILIES[family]
    cfg = derive_cfg(family, seed)
    published = published_pairs(family, cfg, _published_count(family))
    task = {
        "schema": SCHEMA_TASK,
        "task_id": task_id,
        "eval_version": "eval-v1",
        "tier": "smoke",
        "source": "constructed",
        "family": family,
        "seed": seed,
        "anchors": dict(_ANCHORS[family]),
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
    ground_truth = {
        "schema": SCHEMA_GROUND_TRUTH,
        "task_id": task_id,
        "family": family,
        "seed": seed,
        "constants": _constants_public(family, cfg),
        "space_bits": meta["space_bits"],
        "published_pairs": published,
        "minted_probe_count": _minted_count(family),
        "note": _GOAL_NOTE[family],
    }
    if family == "js-sign":
        ground_truth["decoy_constants"] = {"d1": cfg["decoys"][0],
                                           "d2": cfg["decoys"][1]}
    shim = (
        "#!/usr/bin/env python3\n"
        f"# checker.py — {task_id} mechanical-checker shim (#299).\n"
        "# Standalone entry for the task unit: delegates to the shared\n"
        "# mechanical checker with this task directory. Default candidate is\n"
        "# the constructed target itself (self-check); pass --candidate to\n"
        "# grade an arm's re-implementation (the #236 control-arm surface).\n"
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
        f"{meta['target']!r})]\n"
        "    raise SystemExit(eval_checker.main([\"--task\", str(_HERE)] + argv))\n")
    return {"task": task, "target_path": meta["target"],
            "target_source": RENDERERS[family](cfg),
            "ground_truth": ground_truth, "checker_shim": shim}


def write_task_unit(family: str, seed: int, task_id: str, root: Path) -> Path:
    """Mint one task unit onto disk (idempotent per (family, seed))."""
    unit = build_task_unit(family, seed, task_id)
    tdir = Path(root) / task_id
    (tdir / "target").mkdir(parents=True, exist_ok=True)
    (tdir / "task.yaml").write_text(
        yaml.safe_dump(unit["task"], sort_keys=False, allow_unicode=True),
        encoding="utf-8")
    (tdir / unit["target_path"]).write_text(unit["target_source"], encoding="utf-8")
    (tdir / "ground_truth.json").write_text(
        json.dumps(unit["ground_truth"], indent=2) + "\n", encoding="utf-8")
    shim = tdir / "checker.py"
    shim.write_text(unit["checker_shim"], encoding="utf-8")
    shim.chmod(0o755)
    return tdir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval_targets.py",
        description="Mint #299 constructed eval-task units (family:seed:task_id).")
    ap.add_argument("--root", default="eval/v1/tasks/smoke",
                    help="task corpus root (default: eval/v1/tasks/smoke)")
    ap.add_argument("--mint", action="append", default=[],
                    help="family:seed:task_id (repeatable)")
    args = ap.parse_args(argv)
    if not args.mint:
        ap.error("nothing to mint: pass --mint family:seed:task_id")
    from pathlib import Path as _P
    for spec in args.mint:
        family, seed_s, task_id = spec.split(":")
        tdir = write_task_unit(family, int(seed_s), task_id, _P(args.root))
        print(f"MINTED {task_id} ({family}, seed={seed_s}) -> {tdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
