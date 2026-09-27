#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eval_toolflex.py — the TF eval family (tool-combination flexibility).

Owner directive 2026-09-23 (#356): the ladder grades OUTCOMES; the TF
family grades PATH CAPABILITY — can the system select, chain, and RE-ROUTE
tool combinations. Units are constructed so NO single tool computes the
answer: the solution requires chaining >= K distinct tools (K=2/3/4
families), with MULTIPLE valid combinations coexisting (every role carries
>= 2 interchangeable implementers).

Construction (ground truth by construction, one python model per family):
  - the pipeline parameters (four seeded 64-bit words) live ONLY inside an
    encrypted blob (the repo's mod-crypto core, scripts/eval_targets —
    stock crypto is wrong by construction);
  - the toolbox tools are the ONLY holders of the blob key (extract role)
    and of the stage transforms (mix / expand / final roles); every role
    ships an `a` variant (positional CLI) and a `b` variant (flag CLI);
  - the final digest fold multiplies in a seeded odd constant that exists
    ONLY in final-stage tool sources — a single extract run cannot finish
    the pipeline without at least reading a final tool.

Mint-time gates (the deception-smoke analog — a unit whose baselines don't
all fail does not ship):
  A self-check        the reference minimal chain greens the unit checker;
  B chain-necessity   for EVERY toolbox tool: run that tool ALONE (all
                      others PATH-shadowed) + mechanical naive completion
                      (stock digests, zero-state, raw echo) — the checker
                      must FAIL every attempt, recorded in the manifest;
  C blocked variants  one variant per minimal-chain tool: the shadow
                      errors honestly (marker + nonzero rc) AND the
                      re-route chain (alternate implementers) still greens
                      the checker.

Threat-model boundary (honest scope note, mirrored into every manifest):
the gate proves execution-level necessity — no single-tool INVOCATION
shortcut produces the answer. Tool sources are readable by design, so a
session that reads a blocked tool's source and reimplements its transform
is a legitimate (trace-visible) path, not something the shadow prevents.

Known shadow limitation (documented, graded — never denied): PATH
shadowing blocks invocation BY NAME only; absolute-path invocation bypasses
it. The TF graders flag bypass invocations and report f2_reroute, which
excludes bypass solves (scripts/eval_tf_graders.py).

Shared-contract coordination (#352): the single-source family contract
lives in scripts/eval_contract.py (FAMILY_CONTRACT). TF units follow the
per-driver mirror convention until the families are unioned into that
table — the union (suffix ".txt", target_surface "text") lands with the
dev merge-sync; tests/test_eval_toolflex_356.py enforces the strict
conformance face the moment the module is importable.

CLI (regeneration; the landed corpus was minted with exactly these seeds):
  python scripts/eval_toolflex.py --root eval/v1/tasks/toolflex \
      --mint tf-chain2:tf-chain2-py-v1 --mint tf-chain3:tf-chain3-js-v1 \
      --mint tf-chain4:tf-chain4-py-v1

stdlib + yaml + repo eval modules only.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import eval_targets as tg  # the repo RNG + mod-crypto core (sibling convention)
import eval_tf_shadow as sh

SCHEMA_MANIFEST = "kunglao-eval-tf-manifest/1"
TF_TIER = "toolflex"
TF_EVAL_VERSION = "eval-v1.3"

M64 = 0xFFFFFFFFFFFFFFFF
GOLD = 0x9E3779B97F4A7C15
MIX_C = 0xBF58476D1CE4E5B9
EXP_C = 0x94D049BB133111EB

PROBE_COUNT = 6  # published probes; +1 main payload = 7 answer lines
SPACE_BITS = 64 * (PROBE_COUNT + 1)

THREAT_MODEL = (
    "execution-level chain necessity: every single-tool baseline (that "
    "tool alone + mechanical naive completion) fails the unit checker. "
    "Tool sources are readable by design; source-reading reimplementation "
    "is a trace-visible path outside the gate's scope.")

SESSION_SURFACE = {
    "bare-cc-default": (
        "the session subprocess inherits the environment: prepend the "
        "variant's shadow dir to PATH before launch (see "
        "eval_tf_shadow.prepend_path); every tool shell sees it"),
    "kunglao-loop": (
        "eval_loop_runner.launch_session inherits the parent env: the "
        "same exported PATH reaches the session and its dispatched "
        "children — no runner code change"),
    "harness": (
        "checker/solver subprocesses take the prepended env explicitly "
        "(env= kwarg)"),
    "shadow-limitation": sh.SHADOW_MARKER + (
        " blocks name invocation only; absolute-path bypass is flagged "
        "by the graders (bypass_detected / f2_reroute)"),
}


class MintRefusal(RuntimeError):
    """A mint gate refused the unit (the unit does not ship)."""


# ------------------------------------------------------------- registry
# role order = chain order; each role lists its interchangeable
# implementers (impl[0] = `a` variant, impl[1] = `b` variant)
TF_FAMILIES: dict[str, dict] = {
    "tf-chain2": {
        "seed": 35601, "unit_id": "tf-chain2-py-v1", "k": 2,
        "roles": ({"role": "extract", "impls": ("peek", "probe")},
                  {"role": "fold", "impls": ("fold64", "refold64")}),
    },
    "tf-chain3": {
        "seed": 35602, "unit_id": "tf-chain3-js-v1", "k": 3,
        "roles": ({"role": "unwrap", "impls": ("xtract", "scan")},
                  {"role": "keymix", "impls": ("mix", "blend")},
                  {"role": "emit", "impls": ("emit64", "reemit64")}),
    },
    "tf-chain4": {
        "seed": 35603, "unit_id": "tf-chain4-py-v1", "k": 4,
        "roles": ({"role": "open", "impls": ("unlock", "peel")},
                  {"role": "derive", "impls": ("sprout", "distill")},
                  {"role": "expand", "impls": ("weave", "braid")},
                  {"role": "seal", "impls": ("seal", "cap")}),
    },
}

FINAL_INPUT = {2: "params", 3: "key", 4: "ks"}


def _stage_kind(k: int, role_index: int) -> str:
    """Chain position -> stage kind: extract | mix | expand | final."""
    if role_index == 0:
        return "extract"
    if role_index == k - 1:
        return "final"
    if role_index == 1:
        return "mix"
    if role_index == 2:
        return "expand"
    raise ValueError(f"no stage for role {role_index} of K={k}")


def _validate_registry() -> None:
    seen: set[str] = set()
    for family, meta in TF_FAMILIES.items():
        names = [t for r in meta["roles"] for t in r["impls"]]
        if len(meta["roles"]) != meta["k"]:
            raise ValueError(f"{family}: roles must equal K")
        if any(len(r["impls"]) != 2 for r in meta["roles"]):
            raise ValueError(f"{family}: every role needs exactly 2 impls")
        dup = seen.intersection(names)
        if dup:
            raise ValueError(f"{family}: tool names reused across families: "
                             f"{sorted(dup)}")
        seen.update(names)


_validate_registry()


def tool_usage(family: str) -> dict[str, str]:
    """The per-tool argv template (machine-readable, rides the manifest).
    Placeholders: {tool} {blob} {state} {payload}."""
    meta = TF_FAMILIES[family]
    k = meta["k"]
    usage: dict[str, str] = {}
    for i, role in enumerate(meta["roles"]):
        kind = _stage_kind(k, i)
        a, b = role["impls"]
        if kind == "extract":
            usage[a], usage[b] = "{tool} {blob}", "{tool} --blob {blob}"
        elif kind == "mix":
            usage[a], usage[b] = "{tool} {state}", "{tool} --state {state}"
        elif kind == "expand":
            usage[a], usage[b] = "{tool} {state}", "{tool} --in {state}"
        else:  # final
            flag = {"params": "--params", "key": "--key",
                    "ks": "--state"}[FINAL_INPUT[k]]
            usage[a] = "{tool} {state} {payload}"
            usage[b] = f"{{tool}} {flag} {{state}} --payload {{payload}}"
    return usage


# --------------------------------------------------- deterministic config
def _k1_bytes(seed: int) -> bytes:
    """The 32-byte blob key (eight seeded u32 lanes). Exists ONLY inside
    the extract-tool sources — nowhere else in the unit."""
    return b"".join(tg._u32(seed, 21 + i).to_bytes(4, "big")
                    for i in range(8))


def derive_tf_cfg(family: str, seed: int) -> dict:
    """The seeded per-variant constants: pipeline params (4 x u64) + the
    blob key hex (extract-tool-only material)."""
    del family  # the parameter shape is family-invariant; registry-checked
    return {"p": [tg._u64(seed, 1), tg._u64(seed, 2),
                  tg._u64(seed, 3), tg._u64(seed, 4)],
            "k1_hex": _k1_bytes(seed).hex()}


# ------------------------------------------------------- the model (mirror)
def mix_stage(p: list[int]) -> int:
    h = p[0] & M64
    for x in p[1:]:
        h = (((h ^ (x & M64)) * GOLD) + MIX_C) & M64
    return h


def expand_stage(key: int) -> tuple[int, int]:
    a = ((key ^ (key >> 30)) * MIX_C) & M64
    a = ((a ^ (a >> 27)) * EXP_C) & M64
    return (a ^ (a >> 31)) & M64, (a + GOLD) & M64


def final_stage(w0: int, w1: int, data: bytes) -> int:
    h = w0 & M64
    mul = (w1 | 1) & M64
    for b in data:
        h = ((h ^ b) * mul) & M64
    return (h ^ (h >> 31)) & M64


def stage_digest(cfg: dict, data: bytes) -> int:
    """The full pipeline over one payload — the model mirror of the tool
    chain: params -> mix -> expand -> final. K changes only how many
    TOOLS carry these transforms, never the math, so every K's ground
    truth comes from this one face."""
    w0, w1 = expand_stage(mix_stage(cfg["p"]))
    return final_stage(w0, w1, data)


def _payload_text(seed: int, index: int) -> str:
    lines = [f"{tg._u64(seed ^ 0xCAFE, 40 + index * 4 + j):016x}"
             f"{tg._u64(seed ^ 0xBEEF, 40 + index * 4 + j):016x}"
             for j in range(2)]
    return "\n".join(lines) + "\n"


def _encrypt_params(cfg: dict, seed: int) -> str:
    """blob.enc: the params JSON under the mod-crypto keystream (counter
    mode keyed by K1). The key exists ONLY in the extract tools."""
    plain = json.dumps({"p": cfg["p"]}, sort_keys=True).encode("utf-8")
    cfg_sha = tg.mod_sha_cfg(seed)
    key = _k1_bytes(seed)
    stream = bytearray()
    counter = 0
    while len(stream) < len(plain):
        stream += tg.mod_sha256(cfg_sha, key + counter.to_bytes(4, "big"))
        counter += 1
    blob = bytes(a ^ b for a, b in zip(plain, stream))
    return blob.hex() + "\n"


# ------------------------------------------------------------- tool source
_TOOL_SHA_LIB = '''
def _rotr(x, n):
    return ((x >> n) | (x << (32 - n))) & 0xFFFFFFFF


def _pad(data):
    msg = bytearray(data)
    ml = len(data) * 8
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += ml.to_bytes(8, "big")
    return bytes(msg)


def mod_sha256(data):
    h = list(HT)
    kt = KT
    msg = _pad(data)
    for off in range(0, len(msg), 64):
        w = [int.from_bytes(msg[off + i * 4: off + i * 4 + 4], "big")
             for i in range(16)]
        for i in range(16, 64):
            s0 = _rotr(w[i - 15], 7) ^ _rotr(w[i - 15], 18) ^ (w[i - 15] >> 3)
            s1 = _rotr(w[i - 2], 17) ^ _rotr(w[i - 2], 19) ^ (w[i - 2] >> 10)
            w.append((w[i - 16] + s0 + w[i - 7] + s1) & 0xFFFFFFFF)
        a, b, c, d, e, f, g, hh = h
        for i in range(64):
            S1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25)
            ch = (e & f) ^ (~e & g)
            t1 = (hh + S1 + ch + kt[i] + w[i]) & 0xFFFFFFFF
            S0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22)
            mj = (a & b) ^ (a & c)
            t2 = (S0 + mj) & 0xFFFFFFFF
            hh, g, f = g, f, e
            e = (d + t1) & 0xFFFFFFFF
            d, c, b = c, b, a
            a = (t1 + t2) & 0xFFFFFFFF
        h = [(x + y) & 0xFFFFFFFF
             for x, y in zip(h, (a, b, c, d, e, f, g, hh))]
    return b"".join(x.to_bytes(4, "big") for x in h)
'''

_TOOL_MATH_LIB = '''
M64 = 0xFFFFFFFFFFFFFFFF
GOLD = 0x9E3779B97F4A7C15
MIX_C = 0xBF58476D1CE4E5B9
EXP_C = 0x94D049BB133111EB


def stage_mix(p):
    h = p[0] & M64
    for x in p[1:]:
        h = (((h ^ (x & M64)) * GOLD) + MIX_C) & M64
    return h


def stage_expand(key):
    a = ((key ^ (key >> 30)) * MIX_C) & M64
    a = ((a ^ (a >> 27)) * EXP_C) & M64
    return (a ^ (a >> 31)) & M64, (a + GOLD) & M64


def stage_final(w0, w1, data):
    h = w0 & M64
    mul = (w1 | 1) & M64
    for b in data:
        h = ((h ^ b) * mul) & M64
    return (h ^ (h >> 31)) & M64
'''

_EXTRACT_BODY = '''
def main(argv):
    blob = argv[0] if not __FLAGPARSE__ else _flag_value(argv, "--blob")
    try:
        data = bytes.fromhex(open(blob, encoding="utf-8").read().strip())
    except (OSError, ValueError) as exc:
        sys.stderr.write("__NAME__: cannot read blob: %s\\n" % exc)
        return 2
    key = bytes.fromhex(_K1)
    stream = bytearray()
    counter = 0
    while len(stream) < len(data):
        stream += mod_sha256(key + counter.to_bytes(4, "big"))
        counter += 1
    plain = bytes(a ^ b for a, b in zip(data, stream))
    try:
        params = json.loads(plain.decode("utf-8"))["p"]
    except (json.JSONDecodeError, KeyError, UnicodeDecodeError) as exc:
        sys.stderr.write("__NAME__: blob did not decode: %s\\n" % exc)
        return 2
    print(json.dumps({"p": params}, sort_keys=True))
    return 0
'''

_MIX_BODY = '''
def main(argv):
    state = argv[0] if not __FLAGPARSE__ else _flag_value(argv, "__FLAG__")
    try:
        p = json.loads(open(state, encoding="utf-8").read())["p"]
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        sys.stderr.write("__NAME__: cannot read params: %s\\n" % exc)
        return 2
    print("%016x" % stage_mix(p))
    return 0
'''

_EXPAND_BODY = '''
def main(argv):
    state = argv[0] if not __FLAGPARSE__ else _flag_value(argv, "__FLAG__")
    try:
        key = int(open(state, encoding="utf-8").read().strip(), 16)
    except (OSError, ValueError) as exc:
        sys.stderr.write("__NAME__: cannot read stage key: %s\\n" % exc)
        return 2
    w0, w1 = stage_expand(key)
    print("%016x %016x" % (w0, w1))
    return 0
'''

_FINAL_BODY = '''
def main(argv):
    if __FLAGPARSE__:
        state = _flag_value(argv, "__STATEFLAG__")
        payload = _flag_value(argv, "--payload")
    else:
        state, payload = argv[0], argv[1]
    try:
        raw = open(state, encoding="utf-8").read().strip()
        data = open(payload, "rb").read()
    except (OSError, ValueError) as exc:
        sys.stderr.write("__NAME__: cannot read inputs: %s\\n" % exc)
        return 2
    try:
        if __INPUT__ == "params":
            w0, w1 = stage_expand(stage_mix(json.loads(raw)["p"]))
        elif __INPUT__ == "key":
            w0, w1 = stage_expand(int(raw, 16))
        else:
            parts = raw.split()
            w0, w1 = int(parts[0], 16), int(parts[1], 16)
    except (json.JSONDecodeError, KeyError, ValueError, IndexError) as exc:
        sys.stderr.write("__NAME__: bad stage state: %s\\n" % exc)
        return 2
    print("%016x" % stage_final(w0, w1, data))
    return 0
'''

_FLAG_HELPER = '''

def _flag_value(argv, flag):
    if flag not in argv:
        raise SystemExit("__NAME__: missing %s" % flag)
    return argv[argv.index(flag) + 1]
'''


def _render_tool(name: str, kind: str, variant: str, final_input: str,
                 seed: int) -> str:
    """One standalone toolbox tool (python3, stdlib only). Impl `b`
    differs in CLI surface (flags vs positional) — the math is identical
    so the variants are truly interchangeable within the role."""
    k1_line = f'_K1 = "{_k1_bytes(seed).hex()}"' if kind == "extract" \
        else "_K1 = None"
    cfg_sha = tg.mod_sha_cfg(seed)
    tables = ""
    sha_lib = ""
    if kind == "extract":
        tables = ("HT = [%s]\nKT = [%s]\n" % (
            ", ".join(f"0x{v:08x}" for v in cfg_sha["h"]),
            ", ".join(f"0x{v:08x}" for v in cfg_sha["k"])))
        sha_lib = _TOOL_SHA_LIB
    stateflag = {"params": "--params", "key": "--key", "ks": "--state"}
    body = {"extract": _EXTRACT_BODY, "mix": _MIX_BODY,
            "expand": _EXPAND_BODY, "final": _FINAL_BODY}[kind]
    flags = {"extract": "--blob", "mix": "--state", "expand": "--in"}
    body = (body
            .replace("__FLAGPARSE__", "True" if variant == "b" else "False")
            .replace("__FLAG__", flags.get(kind, stateflag[final_input]))
            .replace("__STATEFLAG__", stateflag[final_input])
            .replace("__INPUT__", repr(final_input))
            .replace("__NAME__", name))
    helper = _FLAG_HELPER.replace("__NAME__", name) if variant == "b" else ""
    head = (
        f"#!/usr/bin/env python3\n"
        f"# toolbox/{name} — constructed TF pipeline tool (#356).\n"
        f"# Synthetic; seeded by scripts/eval_toolflex.py. stage={kind} "
        f"variant={variant}\n"
        f"import json\nimport sys\n\n{k1_line}\n{tables}{sha_lib}"
        f"{_TOOL_MATH_LIB}{helper}\n")
    return head + body + f'\n\nif __name__ == "__main__":\n    ' \
                         f"raise SystemExit(main(sys.argv[1:]))\n"


# ------------------------------------------------------------ checker shim
_CHECKER_TEMPLATE = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""checker.py — __UNIT__ TF answer checker (#356).

Standalone (stdlib only): grades the session's answer.txt byte-exact
against the unit's constructed ground truth. Emits the runner-style
stream (METRIC / FAILURE / EVIDENCE / VERDICT); exit 0 PASS / 1 FAIL /
2 REFUSED (no gradeable answer file)."""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HEX16 = __HEXRE__

def _failures(expected, got_lines):
    failures = []
    for i, want in enumerate(expected):
        if i >= len(got_lines):
            failures.append({"code": "PAIR_MISMATCH",
                             "detail": f"line {i} missing"})
            continue
        got = got_lines[i].strip()
        if not HEX16.match(got):
            failures.append({"code": "PAIR_MISMATCH",
                             "detail": f"line {i} malformed (want 16-hex)"})
        elif got != want:
            failures.append({"code": "PAIR_MISMATCH",
                             "detail": f"line {i} mismatched"})
    extra = len(got_lines) - len(expected)
    if extra > 0:
        failures.append({"code": "PAIR_MISMATCH",
                         "detail": f"{extra} extra line(s)"})
    return failures

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--answer", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    gt = json.loads((HERE / "ground_truth.json").read_text(encoding="utf-8"))
    expected = [p["out"] for p in gt["published_pairs"]]
    answer = Path(args.answer)
    out = Path(args.out) if args.out else HERE.parent / "runs" / "tf-check" \\
        / gt["task_id"]
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    answer_ref = str(answer)
    if not answer.is_file():
        failures = [{"code": "BAD_CANDIDATE",
                     "detail": f"answer file missing: {answer}"}]
        verdict, rc = "REFUSED", 2
        matched = 0
    else:
        got_lines = answer.read_text(encoding="utf-8",
                                     errors="replace").splitlines()
        failures = _failures(expected, got_lines)
        line_failures = [f for f in failures
                         if f["detail"].startswith("line ")]
        matched = len(expected) - len(line_failures)
        verdict, rc = ("PASS", 0) if not failures else ("FAIL", 1)
    metrics = {"ttc_seconds": round(time.time() - started, 3),
               "dispatch_count": 1,
               "pass_at_k_contribution": 1 if verdict == "PASS" else 0,
               "converged": 1 if verdict == "PASS" and not failures else 0}
    evidence = {
        "schema": "kunglao-eval-evidence/1",
        "task_id": gt["task_id"], "eval_version": gt.get("eval_version"),
        "family": gt["family"], "tier": "toolflex",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "candidate": answer_ref,
        "faces": {"tf-answer": {"matched": matched,
                                "count": len(expected)}},
        "metrics": metrics, "verdict": verdict, "failures": failures,
    }
    ev = out / (f"evidence-{gt['task_id']}-"
                f"{time.strftime('%Y%m%dT%H%M%SZ')}-"
                f"{os.getpid() % 100000}.json")
    ev.write_text(json.dumps(evidence, indent=2) + "\\n", encoding="utf-8")
    for name, value in metrics.items():
        print(f"METRIC {name}={value:g}"
              if isinstance(value, float) else f"METRIC {name}={value}")
    for f in failures:
        print(f"FAILURE code={f['code']} detail={f['detail']}")
    print(f"EVIDENCE {ev}")
    print(f"VERDICT {verdict}")
    return rc

if __name__ == "__main__":
    raise SystemExit(main())
'''


# ------------------------------------------------------------- unit build
def build_unit(family: str, unit_id: str, seed: int) -> dict:
    """Everything the unit needs, in memory: {files: {rel: text},
    task: task dict}. Deterministic in (family, seed) — re-mints are
    byte-identical (manifest.json is mint-gate output, NOT here)."""
    meta = TF_FAMILIES[family]
    k = meta["k"]
    cfg = derive_tf_cfg(family, seed)
    roles = [{"role": r["role"], "implements": list(r["impls"])}
             for r in meta["roles"]]
    minimal_chain = [r["impls"][0] for r in meta["roles"]]
    required = {r["role"]: list(r["impls"]) for r in meta["roles"]}
    blocked = [f"block-{t}" for t in minimal_chain]

    payloads = [(_payload_text(seed, i), f"probes/payload-{i}.bin")
                for i in range(PROBE_COUNT)]
    payloads.append((_payload_text(seed, 99), "target/payload.bin"))
    pairs = []
    for i, (text, rel) in enumerate(payloads):
        pairs.append({"i": i, "file": rel,
                      "out": f"{stage_digest(cfg, text.encode()):016x}"})

    readme = (
        "# TF pipeline workspace (#356, constructed)\n\n"
        "GOAL: produce answer.txt in the workspace root — seven lines,\n"
        "each the 16-hex-char lowercase digest of one payload:\n"
        "  probes/payload-0.bin .. probes/payload-5.bin (index order),\n"
        "  then target/payload.bin last.\n\n"
        "toolbox/ ships the pipeline tools. The stages hand off state\n"
        "(blob -> stage state -> ... -> digest); no single tool computes\n"
        "the answer, and more than one tool combination does.\n\n"
        "Files: target/blob.enc (encrypted stage parameters),\n"
        "target/payload.bin (main material), probes/*.bin (probe\n"
        "payloads), toolbox/* (the pipeline tools).\n")

    files: dict[str, str] = {
        "target/README.txt": readme,
        "target/blob.enc": _encrypt_params(cfg, seed),
    }
    files.update({rel: text for text, rel in payloads})
    for i, role in enumerate(meta["roles"]):
        kind = _stage_kind(k, i)
        for j, name in enumerate(role["impls"]):
            files[f"toolbox/{name}"] = _render_tool(
                name, kind, "a" if j == 0 else "b", FINAL_INPUT[k], seed)

    ground_truth = {
        "schema": tg.SCHEMA_GROUND_TRUTH,
        "task_id": unit_id, "family": family, "seed": seed,
        "eval_version": TF_EVAL_VERSION,
        "space_bits": SPACE_BITS,
        "published_pairs": pairs,
        "minted_probe_count": 0,
        "note": ("TF family (#356): the answer file is graded byte-exact; "
                 "chain necessity and blocked-variant verification are "
                 "mint-time gates recorded in manifest.json."),
    }
    goal = (
        "Workspace puzzle: produce answer.txt in the workspace root. The "
        "toolbox/ directory ships the pipeline tools. For each probe "
        "payload (probes/payload-0.bin .. probes/payload-5.bin) in index "
        "order and finally the main material (target/payload.bin), "
        "compute the 16-hex-char digest and write one line per item into "
        "answer.txt (7 lines, lowercase hex, in that order). The pipeline "
        "stages hand off state: no single tool computes the answer.")
    scaffold_files = (["target/README.txt", "target/blob.enc",
                       "target/payload.bin"]
                      + sorted(f for f in files if f.startswith("toolbox/"))
                      + [rel for _, rel in payloads if rel != "target/"
                         "payload.bin"])
    task = {
        "schema": tg.SCHEMA_TASK,
        "task_id": unit_id,
        "eval_version": TF_EVAL_VERSION,
        "tier": TF_TIER,
        "source": "constructed",
        "family": family,
        "seed": seed,
        "anchors": {
            "goal_verbatim": goal,
            "success_criterion": (
                "answer.txt carries the seven digests byte-exact "
                "(lowercase 16-hex per line, probes in index order then "
                "target/payload.bin) as fixed by the unit's construction."),
            "verification_method": "reproduction",
        },
        "workspace_scaffold": {
            "language": "python",
            "files": scaffold_files,
            "entry": "target/README.txt",
            "candidate_contract": (
                "answer.txt — seven 16-hex-char lowercase lines: probes in "
                "index order, then target/payload.bin."),
        },
        "checker": {
            "kind": "replay-roundtrip",
            "oracles": ["replay-roundtrip"],
            "entrypoint": "checker.py",
            "metrics": ["ttc_seconds", "dispatch_count",
                        "pass_at_k_contribution", "converged"],
            "thresholds": {"min_pair_ratio": 1.0},
        },
        "ground_truth": {"file": "ground_truth.json",
                         "space_bits": SPACE_BITS},
        "contamination": {
            "held_out": True,
            "distiller_excluded": True,
            "provenance": "constructed",
        },
        "toolflex": {
            "manifest": "manifest.json",
            "k": k,
            "roles": [r["role"] for r in roles],
            "minimum_required_set": required,
            "blocked_variants": blocked,
        },
    }
    files["ground_truth.json"] = json.dumps(ground_truth, indent=2) + "\n"
    files["task.yaml"] = yaml.safe_dump(task, sort_keys=False,
                                        allow_unicode=True)
    files["checker.py"] = _CHECKER_TEMPLATE.replace(
        "__UNIT__", unit_id).replace(
        "__HEXRE__", "re.compile(r'^[0-9a-f]{16}$')")
    return {"files": files, "task": task}


# --------------------------------------------------------------- checking
def _parse_checker_stream(text: str) -> dict:
    out: dict = {"metrics": {}, "failures": [], "verdict": None}
    for line in text.splitlines():
        if line.startswith("VERDICT "):
            out["verdict"] = line[len("VERDICT "):].strip()
        elif line.startswith("FAILURE "):
            head, _, detail = line[len("FAILURE "):].partition("detail=")
            out["failures"].append({"code": head.strip().replace("code=", ""),
                                    "detail": detail.strip()})
    return out


def run_checker(tdir: Path, answer: Path,
                out: Path) -> tuple[int, dict]:
    """The unit checker face (subprocess): returns (rc, parsed stream)."""
    proc = subprocess.run(
        [sys.executable, str(Path(tdir) / "checker.py"),
         "--answer", str(answer), "--out", str(out)],
        capture_output=True, text=True, timeout=120)
    return proc.returncode, _parse_checker_stream(proc.stdout)


def _chain_env(tdir: Path, env: dict | None) -> dict:
    """The chain-runner env: the toolbox dir is inserted AFTER any
    leading SHADOW dirs (a caller's prepended shadow must keep winning
    for blocked names) but BEFORE the system PATH (so a toolbox tool is
    never beaten by a same-named system binary — the /usr/bin/fold
    class of collision). Shadow dirs are recognized by their marker file
    (eval_tf_shadow.build_shadow stamps one). The toolbox entry is
    ABSOLUTE: a relative PATH entry would not resolve once the tool
    subprocess runs under a different cwd."""
    base = dict(os.environ) if env is None else dict(env)
    toolbox = str(Path(base.get("TF_TOOLBOX")
                       or (Path(tdir) / "toolbox")).resolve())
    old = [e for e in base.get("PATH", "").split(os.pathsep)
           if e and Path(e).resolve() != Path(toolbox)]
    head = 0
    while head < len(old) and (Path(old[head]) / sh.SHADOW_MARKER_FILE
                               ).is_file():
        head += 1
    entries = old[:head] + [toolbox] + old[head:]
    base["PATH"] = os.pathsep.join(entries)
    return base


def _run_tool(tool: str, usage: str, env: dict, *, blob: Path,
              state: Path, payload: Path | None) -> tuple[int, str]:
    """One toolbox invocation through PATH (name lookup under ``env``).
    Unused placeholders render empty — the templates reference only what
    they need. No cwd is set: every path argument is absolute (a tool
    must resolve its inputs identically from any cwd)."""
    argv = shlex.split(usage.format(tool=tool, blob=blob, state=state,
                                    payload=payload or ""))
    resolved = shutil.which(tool, path=env.get("PATH", ""))
    if resolved is None:
        return 127, ""
    proc = subprocess.run([resolved] + argv[1:], capture_output=True,
                          text=True, env=env, timeout=60)
    return proc.returncode, proc.stdout


def _solve_chain_with(tdir: Path, usage_map: dict, combo: list[str],
                      answer: Path, env: dict | None) -> int:
    """Drive one tool combination: stage outputs chain via temp state
    files; the final tool runs per payload. rc != 0 on any stage
    failure (the answer is not written). All paths are made ABSOLUTE —
    tool subprocesses run without a cwd and must resolve everything."""
    tdir = Path(tdir).resolve()
    answer = Path(answer).resolve()
    env = _chain_env(tdir, env)
    payloads = [tdir / "probes" / f"payload-{i}.bin"
                for i in range(PROBE_COUNT)]
    payloads.append(tdir / "target" / "payload.bin")
    work = answer.parent
    work.mkdir(parents=True, exist_ok=True)
    state_path = tdir / "target" / "blob.enc"
    for i, tool in enumerate(combo):
        last = i == len(combo) - 1
        if not last:
            rc, out = _run_tool(tool, usage_map[tool], env, blob=state_path,
                                state=state_path, payload=None)
            if rc != 0:
                return rc
            state_path = work / f"state-{i}.txt"
            state_path.write_text(out, encoding="utf-8")
    final = combo[-1]
    lines = []
    for payload in payloads:
        rc, out = _run_tool(final, usage_map[final], env, blob=state_path,
                            state=state_path, payload=payload)
        if rc != 0:
            return rc
        lines.append(out.strip())
    answer.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


def solve_chain(tdir: Path, combo: list[str], answer: Path,
                env: dict | None = None) -> int:
    """Public chain-runner face (landed units: usage rides
    manifest.json)."""
    tdir = Path(tdir)
    manifest = json.loads((tdir / "manifest.json").read_text("utf-8"))
    return _solve_chain_with(tdir, manifest["tool_usage"], combo, answer,
                             env)


# ------------------------------------------------------------ mint gates
def _manifest_skeleton(stage: Path, task: dict) -> dict:
    family = task["family"]
    meta = TF_FAMILIES[family]
    k = meta["k"]
    roles = [{"role": r["role"], "implements": list(r["impls"])}
             for r in meta["roles"]]
    minimal_chain = [r["impls"][0] for r in meta["roles"]]
    return {
        "schema": SCHEMA_MANIFEST,
        "task_id": task["task_id"],
        "family": family,
        "seed": task["seed"],
        "k": k,
        "roles": roles,
        "minimum_required_set": {r["role"]: list(r["impls"])
                                 for r in meta["roles"]},
        "minimal_chain": minimal_chain,
        "valid_combinations": [list(c) for c in itertools.product(
            *[r["impls"] for r in meta["roles"]])],
        "tool_usage": tool_usage(family),
        "blocked_variant_names": [f"block-{t}" for t in minimal_chain],
        "threat_model": THREAT_MODEL,
        "session_surface": SESSION_SURFACE,
        "shared_contract_note": (
            "union tf-chain2/3/4 into scripts/eval_contract.py "
            "FAMILY_CONTRACT (suffix .txt, response_language text-answer, "
            "target_surface text) at the dev merge-sync when not already "
            "present; strict conformance activates with the module."),
    }


def _naive_attempts(solo_out: str, payloads: list[bytes]) -> list[dict]:
    """Mechanical single-tool completions (no other toolbox invocation):
    stock digests, the zero-state fold, and the raw solo stdout echo."""
    attempts: list[dict] = []

    def add(name: str, lines: list[str]) -> None:
        attempts.append({"name": name, "lines": lines})

    for algo in ("sha256", "sha1", "md5"):
        add(f"stock-{algo}-16",
            [hashlib.new(algo, p).hexdigest()[:16] for p in payloads])
    zero = [f"{final_stage(0, 0, p):016x}" for p in payloads]
    add("zero-state-fold", zero)
    raw = [ln.strip() for ln in solo_out.splitlines()]
    if len(raw) == len(payloads) and \
            all(len(x) == 16 for x in raw):
        add("raw-solo-stdout", raw)
    return attempts


def _solo_baseline(stage: Path, m: dict, tool: str,
                   work: Path) -> dict:
    """Gate B for one tool: only ``tool`` executable (all others
    PATH-shadowed), solo run + naive completion — the checker must
    FAIL every attempt."""
    others = {t for r in m["roles"] for t in r["implements"]} - {tool}
    shadow = sh.build_shadow(work / f"shadow-{tool}",
                             {o: f"baseline-{tool}-{o}" for o in others})
    env = sh.prepend_path(shadow, env=None)
    env = _chain_env(stage, env)
    blob = (stage / "target" / "blob.enc").resolve()
    main_payload = (stage / "target" / "payload.bin").resolve()
    solo_usage = m["tool_usage"][tool]
    solo_rc, solo_out = _run_tool(tool, solo_usage, env, blob=blob,
                                  state=blob, payload=main_payload)
    payloads = [(stage / "probes" / f"payload-{i}.bin").resolve()
                .read_bytes() for i in range(PROBE_COUNT)]
    payloads.append(main_payload.read_bytes())
    records = []
    verdict = "FAIL"
    codes: list[str] = []
    for attempt in _naive_attempts(solo_out, payloads):
        ans = work / f"answer-{tool}.txt"
        ans.write_text("\n".join(attempt["lines"]) + "\n", encoding="utf-8")
        crc, parsed = run_checker(stage, ans, work)
        records.append({"name": attempt["name"],
                        "verdict": parsed.get("verdict") or "FAIL"})
        codes = [f["code"] for f in parsed.get("failures", [])]
        if parsed.get("verdict") == "PASS":
            verdict = "PASS"
            break
    return {"tool": tool, "solo_rc": solo_rc, "attempts": records,
            "verdict": verdict, "failure_codes": codes}


def _verify_blocked_variant(stage: Path, m: dict, tool: str,
                            work: Path) -> dict:
    """Gate C for one minimal-chain tool: the shadow errors honestly AND
    the re-route chain (alternate implementers) still greens the
    checker."""
    variant = f"block-{tool}"
    shadow = sh.build_shadow(work / f"shadow-{variant}", {tool: variant})
    env = sh.prepend_path(shadow, env=None)
    verified = sh.verify_shadow(tool, shadow, env)
    reroute = [next(t for t in r["implements"] if t != tool)
               for r in m["roles"]]
    ans = work / f"answer-{variant}.txt"
    rc = _solve_chain_with(stage, m["tool_usage"], reroute, ans, env=env)
    crc, parsed = run_checker(stage, ans, work)
    reroute_verdict = parsed.get("verdict") or "FAIL"
    if not (verified["rc"] != 0 and verified["marker"]):
        raise MintRefusal(
            f"{variant}: shadow did not fail honestly: {verified}")
    if reroute_verdict != "PASS" or rc != 0:
        raise MintRefusal(
            f"{variant}: re-route chain {reroute} did not solve "
            f"(rc={rc}, verdict={reroute_verdict})")
    return {"variant": variant, "blocked_tool": tool,
            "shadow_verified": {"rc": verified["rc"],
                                "marker": verified["marker"]},
            "reroute_chain": reroute,
            "reroute_verdict": reroute_verdict}


def mint_staged_unit(stage: Path, task: dict, staging_root: Path) -> Path:
    """Run all mint gates over a staged unit; on success write
    manifest.json (gate evidence included) into the stage dir. Any gate
    failure raises MintRefusal — the unit does not ship."""
    stage = Path(stage)
    staging_root = Path(staging_root)
    m = _manifest_skeleton(stage, task)
    work = staging_root / f"gate-work-{task['task_id']}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    # Gate A — self-check: the reference minimal chain greens the checker
    ans = work / "answer-reference.txt"
    rc = _solve_chain_with(stage, m["tool_usage"], m["minimal_chain"],
                           ans, env=None)
    if rc != 0:
        raise MintRefusal(f"self-check: reference chain rc={rc}")
    _crc, parsed = run_checker(stage, ans, work)
    if parsed.get("verdict") != "PASS":
        raise MintRefusal(
            f"self-check: reference chain verdict={parsed.get('verdict')} "
            f"failures={parsed.get('failures')}")

    # Gate B — chain necessity: EVERY single-tool baseline must FAIL
    baselines = []
    tools = sorted(t for r in m["roles"] for t in r["implements"])
    for tool in tools:
        rec = _solo_baseline(stage, m, tool, work)
        if rec["verdict"] == "PASS":
            raise MintRefusal(
                f"chain-necessity: single-tool baseline PASSED for "
                f"{tool} — the unit does not ship")
        baselines.append(rec)
    m["chain_necessity"] = baselines
    m["chain_necessity_ok"] = True

    # Gate C — blocked variants: shadow honest + re-route solves
    variants = []
    for tool in m["minimal_chain"]:
        variants.append(_verify_blocked_variant(stage, m, tool, work))
    m["blocked_variants"] = variants

    (stage / "manifest.json").write_text(
        json.dumps(m, indent=2) + "\n", encoding="utf-8")
    return stage


def mint_unit(family: str, unit_id: str, root: Path) -> Path:
    """Stage -> gates -> move into the corpus root (all-or-nothing)."""
    root = Path(root)
    unit = build_unit(family, unit_id, TF_FAMILIES[family]["seed"])
    staging = root.parent / f".tf-staging-{unit_id}"
    shutil.rmtree(staging, ignore_errors=True)
    stage = staging / unit_id
    for rel, text in unit["files"].items():
        p = stage / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        if rel.startswith("toolbox/"):
            p.chmod(0o755)
        elif rel == "checker.py":
            p.chmod(0o755)
    mint_staged_unit(stage, unit["task"], staging)
    dest = root / unit_id
    shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    stage.rename(dest)
    shutil.rmtree(staging, ignore_errors=True)
    print(f"MINTED {unit_id} ({family}, "
          f"seed={TF_FAMILIES[family]['seed']}, "
          f"K={unit['task']['toolflex']['k']}) -> {dest}")
    return dest


# ------------------------------------------------------------------ CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval_toolflex.py",
        description="Mint #356 TF eval units (chain-necessity + "
                    "blocked-path variants).")
    ap.add_argument("--root", default="eval/v1/tasks/toolflex")
    ap.add_argument("--mint", action="append", default=[],
                    help="family:unit_id (repeatable)")
    ap.add_argument("--mint-all", action="store_true")
    ap.add_argument("--self-check", default=None, metavar="TASK_ID",
                    help="re-run the reference chain + checker on a "
                         "landed unit")
    ap.add_argument("--check", default=None, metavar="TASK_ID")
    ap.add_argument("--answer", default=None, metavar="PATH")
    args = ap.parse_args(argv)
    root = Path(args.root)
    if args.self_check:
        tdir = root / args.self_check
        answer = Path(args.answer) if args.answer else \
            Path(f"/tmp/tf-selfcheck-{args.self_check}.txt")
        rc = solve_chain(tdir,
                         json.loads((tdir / "manifest.json")
                                    .read_text("utf-8"))["minimal_chain"],
                         answer)
        crc, parsed = run_checker(tdir, answer, tdir.parent / "runs")
        print(f"VERDICT {args.self_check} {parsed.get('verdict')} "
              f"(chain rc={rc}, checker rc={crc})")
        return 0 if rc == 0 and crc == 0 else 1
    if args.check:
        if not args.answer:
            ap.error("--check needs --answer PATH")
        crc, parsed = run_checker(root / args.check, Path(args.answer),
                                  root.parent / "runs")
        return crc
    specs = args.mint
    if args.mint_all:
        specs = [f"{f}:{m['unit_id']}" for f, m in TF_FAMILIES.items()]
    if not specs:
        ap.error("nothing to do: pass --mint family:unit_id "
                 "(or --mint-all / --self-check / --check)")
    for spec in specs:
        family, _, unit_id = spec.partition(":")
        if family not in TF_FAMILIES or not unit_id:
            ap.error(f"bad --mint spec {spec!r} (want family:unit_id; "
                     f"families: {sorted(TF_FAMILIES)})")
        mint_unit(family, unit_id, root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
