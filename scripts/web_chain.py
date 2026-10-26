#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web_chain.py — the web lane's analysis-chain registry (single source).

The web lane's reading of "static analysis" is a LADDER, not one tool face:

  L1 AST census        markers scanned below (the true AST census —
                       babel/acorn shape IDs — is the JS tool face; this
                       module pins the FEATURES the router consumes)
  L2 IR deep-analysis  web:static-jsir   (jsir_gen via docker: source-to-
                       source deobfuscation, taint from request params to
                       crypto ops, Hermes bytecode decompilation)
  L3 offline execution web:offline-iv8   (iv8: headless V8 with a faithful
                       browser env — requests-injection loop, logical
                       time, browser-API monitoring that locates env-
                       detection chains; no browser needed)
  L4 live capture      web:live-camoufox (the registered camoufox-reverse
                       MCP; fingerprint spoofing, fresh-input validation)
  corner WASM          web:wasm          (the \\0asm magic routes here;
                       wasm2wat/wabt re-applies the binary feature set)

Wiring, not vendoring: the tool BODIES install through the kunglao-init
toolchain face (agent-do). This module owns the registry facts the other
surfaces read — chains, supply pins, census markers, rule->chain map and
the abstention default.

Supply gates:
  JSIR  upstream publishes no image; the SOURCE REF is the pin and the
        first agent-do `docker build` mints (freezes) the digest here.
        License verified Apache-2.0 (Google OSS).
  iv8   PyPI `==` pin. Distributed as compiled binaries under a
        proprietary non-commercial license (decompilation prohibited);
        the constraint travels with every remediation line.

Abstention default (owner ruling): no census rule fired on the web lane
-> the router returns {recommendation: null, hand_to: "agent"} and emits
`route_abstained` telemetry — a fabricated low-confidence chain pollutes
telemetry and misleads consumers; the agent's self-disposal IS the
learning corpus for the future learnable router.

stdlib only (consumed by init-face modules that promise stdlib+yaml).
"""
from __future__ import annotations

import re

WEB_LANE = "web"

# ------------------------------------------------------------ the chains
# name -> {rung, toolchain, supply, note}; order = ladder order (L2, L3,
# L4, corner). The L4 face is the already-integrated camoufox MCP supply.

CHAINS: tuple[dict, ...] = (
    {"name": "web:static-jsir", "rung": "L2",
     "toolchain": "jsir_gen (docker image)",
     "supply": "jsir-image",
     "note": "source-to-source deobfuscation + taint (request params -> "
             "crypto ops) + Hermes bytecode decompilation"},
    {"name": "web:offline-iv8", "rung": "L3",
     "toolchain": "iv8 (PyPI)",
     "supply": "iv8-pypi",
     "note": "headless V8 + faithful browser env: requests-injection "
             "loop, logical time, browser-API monitoring for env-detection "
             "chains; drives the algorithm against captured pairs"},
    {"name": "web:live-camoufox", "rung": "L4",
     "toolchain": "camoufox-reverse (registered MCP)",
     "supply": "mcp-bridge",
     "note": "live capture, fingerprint spoofing, fresh-input "
             "validation — the master oracle's face"},
    {"name": "web:wasm", "rung": "corner",
     "toolchain": "wabt (wasm2wat)",
     "supply": "system-wabt",
     "note": "\\0asm magic detected -> the binary feature set applies "
             "again (entropy/density live in the wasm module)"},
)

CHAIN_NAMES: tuple[str, ...] = tuple(c["name"] for c in CHAINS)

# ------------------------------------------------------------ supply pins

#: jsir docker image contract. upstream ships no image — build from the
#: pinned upstream source ref, then freeze the sha256 image digest HERE
#: (the supply gate reads this field; absent digest = build guidance).
JSIR_IMAGE: dict = {
    "image": "jsir",
    "source_repo": "google/jsir",
    "source_ref": "3ef1529ee4ecaa97f2891125b8d01ba2d0a75c3e",
    "digest": None,  # frozen at the first agent-do build (never guessed)
}

#: license face, verified against the upstream repo metadata
JSIR_LICENSE = "Apache-2.0"

#: iv8 PyPI exact pin (registry truth at pin time)
IV8_PIN = "0.1.4"

#: non-commercial constraint — rides every remediation line that names
#: the install command
IV8_LICENSE_NOTE = (
    "proprietary binary distribution: personal/research/non-commercial "
    "use only, decompilation prohibited; owner acknowledgment required "
    "before any commercial deployment")

#: the telemetry word for the abstention face (registered in
#: event_taxonomy.EMIT_ACTIONS — one word per emit face)
ROUTE_ABSTAINED = "route_abstained"

# ------------------------------------------------------------ the census
# (marker name, compiled text regex) — deterministic scan over the decoded
# bundle text; bytes sources decode lossy (the \\0asm magic survives a
# lossy decode). A marker is a PRIOR, not a proof: the deep census is the
# L1 AST tool face.

CENSUS_MARKERS: tuple[tuple[str, re.Pattern], ...] = (
    ("wasm_magic", re.compile(r"\x00asm")),
    ("hermes_bytecode", re.compile(r"[0-9]{1,4}cHermes")),
    ("string_array_decoder",
     re.compile(r"_0x[0-9a-fA-F]{4,6}\(\s*0x[0-9a-fA-F]+\s*\)")),
    ("hex_renamed_ids", re.compile(r"_0x[0-9a-fA-F]{4,6}\b")),
    ("webpack_bootstrap",
     re.compile(r"(webpackBootstrap|__webpack_require__)")),
    ("crypto_api", re.compile(
        r"(SubtleCrypto|crypto\.subtle|CryptoJS|JSEncrypt|jsencrypt"
        r"|\bmd5\b|\bsha1\b|\bsha256\b|\bhmac\b|\baes\b)", re.IGNORECASE)),
    ("xhr_fetch", re.compile(r"(XMLHttpRequest|fetch\s*\()")),
    ("env_probe", re.compile(
        r"(navigator\.webdriver|\bheadless\b|\bphantom\b|\bselenium\b"
        r"|\$?cdc_[a-zA-Z0-9]{6,})")),
)

#: hex-renamed identifiers below this count are noise (single-digit hits
#: appear in hand-written helpers); the population marker needs a family
HEX_ID_FLOOR = 8


def census(*sources) -> dict[str, int]:
    """Marker counts over one or more bundle sources (str or bytes).

    Deterministic: same inputs -> same counts, every marker name present
    (0 when absent). A lossy decode never raises."""
    parts: list[str] = []
    for src in sources or ():
        if isinstance(src, bytes):
            parts.append(src.decode("utf-8", errors="replace"))
        elif isinstance(src, str):
            parts.append(src)
    text = "\n".join(parts)
    return {name: len(rx.findall(text)) for name, rx in CENSUS_MARKERS}


# ------------------------------------------------------ rule -> chain map

def _hits_for(name: str, count: int) -> tuple[str, float, str] | None:
    """One marker's rule: (chain, strength, reason) or None."""
    if count <= 0:
        return None
    if name == "wasm_magic":
        return ("web:wasm", 0.9, f"WASM magic detected ({count} hit(s)) "
                "-> the binary feature set applies to the module")
    if name == "hermes_bytecode":
        return ("web:static-jsir", 0.9, "Hermes bytecode magic -> the "
                "RN/mini-program decompilation face")
    if name == "string_array_decoder":
        return ("web:static-jsir", 0.9, "string-array decoder shape -> "
                "source-to-source deobfuscation")
    if name == "hex_renamed_ids":
        if count < HEX_ID_FLOOR:
            return None
        return ("web:static-jsir", 0.7, f"hex-renamed identifier "
                f"population ({count}) -> obfuscated bundle")
    if name == "webpack_bootstrap":
        return ("web:static-jsir", 0.6, "webpack bootstrap -> unbundle "
                "before deep-analysis")
    if name == "crypto_api":
        return ("web:offline-iv8", 0.6, "crypto API census hit -> the "
                "sign/encryption reproduction face")
    if name == "xhr_fetch":
        return None  # fires only as the corroboration arm (see below) —
        # a bare request surface is not a reproduction signal by itself
    if name == "env_probe":
        return ("web:live-camoufox", 0.8, "environment-detection probes -> "
                "the fingerprint-spoof face")
    return None


def route_web(census_features: dict) -> list[tuple[str, float, str]]:
    """Fire the rule->chain map over census counts.

    One entry per chain: max strength wins, the strongest rule's reason
    travels. The crypto+xhr CORROBORATION raises the offline chain to the
    exact band (both faces present = the sign-reproduction signature)."""
    best: dict[str, list] = {}
    order: list[str] = []
    for name, count in (census_features or {}).items():
        hit = _hits_for(name, int(count or 0))
        if hit is None:
            continue
        chain, strength, reason = hit
        if chain not in best:
            best[chain] = [strength, reason]
            order.append(chain)
        elif strength > best[chain][0]:
            best[chain][0] = strength
    has_crypto = int((census_features or {}).get("crypto_api") or 0) > 0
    has_xhr = int((census_features or {}).get("xhr_fetch") or 0) > 0
    if has_crypto and has_xhr and "web:offline-iv8" in best:
        best["web:offline-iv8"][0] = 0.9
        best["web:offline-iv8"][1] = ("crypto API over a request surface "
                                      "-> the sign/encryption "
                                      "reproduction face")
    return [(chain, best[chain][0], best[chain][1]) for chain in order]


# --------------------------------------------------------- abstention

ABSTENTION_HAND_TO = "agent"


def abstention(lane: str, reason: str) -> dict:
    """The no-evidence shape: NO fabricated chain, NO fake confidence.

    `recommendation: None` is the contract consumers must honor (a null
    recommendation with hand_to=agent is an instruction, not a failure)."""
    return {"recommendation": None,
            "reason": reason,
            "hand_to": ABSTENTION_HAND_TO,
            "lane": lane}
