# -*- coding: utf-8 -*-
"""obligation_discovery — DiscoveryEmitted → ObligationCreated (#147 P0).

Convergence only manages REGISTERED work; discoveries written into fact
bodies (shellcode found / downstream payload not analyzed / next-stage
URLs) never became obligations. This module scans fact bodies for typed
discovery patterns and returns obligation templates. The consumer
(convergence_check / future case controller) creates child obligations.

Deterministic: same facts → same obligations. Materiality rejection is
NOT implemented here (P0 scope) — every disclosure becomes an
obligation template; a future MaterialityRejected event needs a reason
and policy version (report §4.2).
"""
from __future__ import annotations

import re
from pathlib import Path


TEMPLATES: dict[str, dict[str, str]] = {
    "payload-analysis": {
        "name": "payload-analysis",
        "question": "extract and analyze the disclosed payload",
        "closure_policy": "byte-anchored facts + verifier sign-off",
    },
    "next-stage": {
        "name": "next-stage",
        "question": "recover and analyze the next-stage URL/payload",
        "closure_policy": "byte-anchored facts + verifier sign-off",
    },
}

_DISCLOSURE_PATTERNS = [
    (re.compile(r"shellcode", re.IGNORECASE), "shellcode", "payload-analysis"),
    (re.compile(r"downstream payload", re.IGNORECASE), "downstream", "payload-analysis"),
    (re.compile(r"next[- ]stage", re.IGNORECASE), "next-stage", "next-stage"),
    (re.compile(r"second[- ]stage", re.IGNORECASE), "second-stage", "next-stage"),
]

# Disclosures that are already followed up are NOT new obligations.
_FOLLOWUP_PATTERNS = [
    re.compile(r"payload analyzed", re.IGNORECASE),
    re.compile(r"next[- ]stage analyzed", re.IGNORECASE),
    re.compile(r"second[- ]stage recovered", re.IGNORECASE),
]


def _disclosures(fact_text: str) -> list[tuple[str, str]]:
    out = []
    for pat, key, template in _DISCLOSURE_PATTERNS:
        if pat.search(fact_text):
            out.append((key, template))
    return out


def scan_discoveries(facts_dir: Path, register_path: Path) -> list[dict]:
    """Scan every non-index fact body for typed disclosures.

    Returns list of {"type", "trigger", "obligation_template"} — one per
    (fact, disclosure-type) that is not already followed up."""
    obs = []
    for p in sorted(facts_dir.glob("F*.md")):
        if p.name.startswith("_"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        followed_up = any(f.search(text) for f in _FOLLOWUP_PATTERNS)
        for key, template in _disclosures(text):
            if followed_up and key in ("downstream", "next-stage", "second-stage"):
                continue
            obs.append({
                "type": key,
                "trigger": p.name,
                "obligation_template": template,
            })
    return obs


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        description="scan fact bodies for un-consumed discoveries")
    ap.add_argument("ws", type=Path, help="workspace root (facts/ inside)")
    args = ap.parse_args(argv)
    ws = args.ws
    obs = scan_discoveries(ws / "facts", ws / "claim-register.yaml")
    for o in obs:
        print(f"DISCOVERY: {o['trigger']} -> {o['obligation_template']}")
    return 0 if not obs else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
