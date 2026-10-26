#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lane_profile.py — the lane DATA PROFILE registry (init v2).

Lane was a code axis: the prescan probe list, the difficulty families and
the env capability vocabulary each baked the binary-RE assumptions in a
different module, so a lane:web workspace was initialized with apkid/die
obligations it can never satisfy and a dead all-zero "easy" difficulty
(the 51job live evidence: a month-old web workspace blocked by its own
gates). The panel amendment (architecture seat): lane is a DATA PROFILE —
each lane entry declares the material contract and every lane-shaped
surface reads its slice from HERE, so web-lane support is a profile entry
instead of a sixth code fork.

Profiles (per lane, the enum is lane_spec.LANES):

  prescan_probes        the lane's T1 pre-scan tools (init-time promise
                        face); out-of-lane probes are DROPPED at init,
                        never emitted as WARN stubs
  java_reachability     the jadx/baksmali/apktool promise face (binary-only)
  obfuscation_prior     the apkid obfuscator prior face (binary-only)
  obligation_artifacts  the evidence artifacts the lane's first-claim T1
                        obligation names (generated from the registry —
                        the T1 first-claim obligation is in-lane only)
  factor_set            the difficulty-calibration factor map key
  capabilities          the env capability vocabulary dispatch may consult
                        on this lane (the R2 axis; device_root is FIRST-
                        CLASS — the machine-anchored counter-check the
                        "device has no root" narration lacked — the
                        live-run logs review)

Fail-open contract: an unknown lane value resolves to the malware profile
(the pre-lane historical contract) with exact=False — callers must emit a
loud WARN; today's binary-shaped yaml is the fallback, never a guess of a
new shape.

stdlib only (consumed by init-face modules that promise stdlib+yaml).
"""
from __future__ import annotations

import lane_spec

# The pre-lane historical contract: an unknown lane behaves as malware
# (lane_spec.DEFAULT_LEGACY), and the profile fallback keeps the binary
# battery so today's yaml is the floor (fail-open, never a new guess).
DEFAULT_LANE = lane_spec.DEFAULT_LEGACY

_WEB_BATTERY_NOTE = (
    "web-native prescan battery (captures present / bundle inventory / "
    "WASM count / cipher-shape markers / prior-art scan) — replaces the "
    "binary stubs (panel amendment); probes are cost_tier=probe arms, never "
    "init-time WARN stubs")

LANE_PROFILES: dict[str, dict] = {
    "malware": {
        "prescan_probes": ("apkid", "die"),
        "java_reachability": True,
        "obfuscation_prior": True,
        "obligation_artifacts": ("evidence/apkid.json", "evidence/die.json"),
        "factor_set": "binary",
        "capabilities": ("vm_reachable", "mcp_bridge", "adb",
                         "frida_server", "jdwp_debug", "device_root"),
    },
    "algorithm": {
        "prescan_probes": (),
        "java_reachability": False,
        "obfuscation_prior": False,
        "obligation_artifacts": (),
        "factor_set": "binary",
        "capabilities": ("mcp_bridge",),
    },
    "protocol": {
        "prescan_probes": (),
        "java_reachability": False,
        "obfuscation_prior": False,
        "obligation_artifacts": (),
        "factor_set": "binary",
        "capabilities": ("mcp_bridge",),
    },
    "web": {
        "prescan_probes": (),
        "java_reachability": False,
        "obfuscation_prior": False,
        "obligation_artifacts": (),
        "factor_set": "web",
        # the analysis-chain supplies join the dispatch vocabulary: the
        # jsir docker face and the iv8 module face are env capabilities
        # dispatch may consult (the R2 axis), next to the MCP bridge the
        # camoufox L4 face rides on
        "capabilities": ("mcp_bridge", "host_docker", "iv8_module"),
        "battery_note": _WEB_BATTERY_NOTE,
    },
    "data": {
        "prescan_probes": (),
        "java_reachability": False,
        "obfuscation_prior": False,
        "obligation_artifacts": (),
        "factor_set": "binary",
        "capabilities": (),
    },
    "app": {
        "prescan_probes": (),
        "java_reachability": False,
        "obfuscation_prior": False,
        "obligation_artifacts": (),
        "factor_set": "binary",
        "capabilities": ("adb", "frida_server", "jdwp_debug",
                         "device_root"),
    },
}

# The R2 dispatch face: env capability -> the tool families that
# MECHANICALLY require it (the priority_ratio family vocabulary; a
# capability-DOWN entry makes those dispatches ineligible). Absent from
# the map = no mechanical dependency (no fabrication).
CAPABILITY_TOOL_FAMILIES: dict[str, tuple[str, ...]] = {
    "frida_server": ("frida",),
    "vm_reachable": ("vm",),
    # the web analysis chain: jsir runs through the docker image face,
    # iv8 needs its module importable in the workspace env — a DOWN entry
    # stops a jsir/iv8 dispatch into a supply the env-state records dead
    "host_docker": ("jsir",),
    "iv8_module": ("iv8",),
}


def profile_for(lane: str | None) -> tuple[dict, bool]:
    """(profile, exact) — exact=False marks the fail-open fallback; the
    caller OWNS the loud WARN (this module never prints)."""
    key = str(lane or "").strip().lower()
    prof = LANE_PROFILES.get(key)
    if prof is not None:
        return prof, True
    return LANE_PROFILES[DEFAULT_LANE], False


def prescan_probes(lane: str | None) -> tuple[str, ...]:
    prof, _ = profile_for(lane)
    return tuple(prof["prescan_probes"])


def obligation_artifacts(lane: str | None) -> tuple[str, ...]:
    prof, _ = profile_for(lane)
    return tuple(prof["obligation_artifacts"])


def factor_set(lane: str | None) -> str:
    prof, _ = profile_for(lane)
    return str(prof["factor_set"])


def lane_capabilities(lane: str | None) -> tuple[str, ...]:
    prof, _ = profile_for(lane)
    return tuple(prof["capabilities"])


def analysis_chains(lane: str | None) -> tuple[dict, ...]:
    """The lane's registered analysis chains (web only — every other lane
    is () until it registers a chain; the web registry lives in
    web_chain, this accessor is the lane-shaped read face)."""
    if str(lane or "").strip().lower() != "web":
        return ()
    import web_chain  # sibling registry (lazy: keeps import cost local)
    return web_chain.CHAINS


def has_binary_face(lane: str | None) -> bool:
    """True when the lane's analysis subject is a native binary (the
    java_reachability / obfuscation_prior promise faces exist there)."""
    prof, _ = profile_for(lane)
    return bool(prof.get("java_reachability"))


def capabilities_for_family(family: str) -> tuple[str, ...]:
    """Reverse map: the env capabilities the tool family mechanically
    requires (order-stable, registry order)."""
    fam = str(family or "").strip().lower()
    return tuple(cap for cap, fams in CAPABILITY_TOOL_FAMILIES.items()
                 if fam in fams)
