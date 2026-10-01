#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""distill_spine.py — the ONE distillation T-pass + source-trust gate
(#478; five owner rulings 2026-09-30: product stack, E-many/T-L-one,
precision, adaptive compression, analogy transfer).

Every extractor (rollup lessons, #477 harvest, #458 external
candidates) feeds THIS transformation; landing goes through the
EXISTING #474 API. Stage order is fixed:
    de_case -> promote_form -> tag -> verify -> dedup
A product that skips a stage is a contract violation (raises
SpineOrderError — loud, never silent).

CLI faces: validate / trust (read) — the producers import the library.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

TRUST_REL = "runs/distill-trust.json"
PRODUCTS_REL = "runs/distill-products"
FALSIFY_BLACKLIST_N = 2

PLAYBOOK_SCHEMA = "playbook/1"
DECISION_SCHEMA = "decision-entry/1"
PRODUCT_SCHEMAS = (PLAYBOOK_SCHEMA, DECISION_SCHEMA)


class SpineOrderError(RuntimeError):
    """A product skipped a T-pass stage — a contract violation."""


# ------------------------------------------------------------- schemas ---

def content_hash(doc: dict) -> str:
    blob = json.dumps(doc, sort_keys=True, ensure_ascii=False,
                      default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _validate_playbook(doc: dict) -> list[str]:
    bad: list[str] = []
    if doc.get("schema") != PLAYBOOK_SCHEMA:
        bad.append("schema-mismatch")
    steps = doc.get("steps")
    if not isinstance(steps, list) or not steps:
        return bad + ["playbook-no-steps"]
    for i, s in enumerate(steps):
        if not isinstance(s, dict) or not s.get("tool_ref"):
            bad.append(f"step-{i}-no-tool-ref")
        if not isinstance(s.get("expected_evidence"), str):
            bad.append(f"step-{i}-no-expected-evidence")
    if not isinstance(doc.get("problem_signature"), list):
        bad.append("playbook-no-signature")
    return bad


def _validate_decision(doc: dict) -> list[str]:
    bad: list[str] = []
    if doc.get("schema") != DECISION_SCHEMA:
        bad.append("schema-mismatch")
    for f in ("signature_tokens", "method_family", "applicability"):
        if not doc.get(f):
            bad.append(f"decision-missing-{f}")
    if not isinstance(doc.get("failure_modes"), list):
        bad.append("decision-failure-modes-not-list")
    return bad


def validate_product(kind: str, doc: dict) -> list[str]:
    """Named violations (empty list = valid). Structural only — the
    verify stage owns semantic validation."""
    if not isinstance(doc, dict):
        return ["not-a-mapping"]
    if kind == "playbook":
        return _validate_playbook(doc)
    if kind == "decision":
        return _validate_decision(doc)
    return ["unknown-kind"]


# --------------------------------------------------------- T-pass (1-5) ---

_ABSOLUTE = re.compile(r"(/private)?/tmp/[^ \t\"')\]]*|"
                       r"/Users/[^ \t\"')\]]*")
_HEX_BLOB = re.compile(r"\b[0-9a-f]{24,}\b")


def de_case(payload: dict, provenance: dict) -> dict:
    """Stage 1 — strip the non-transferable: absolute paths, long hex
    blobs (sample-specific bytes), transient env quirks. The method
    survives verbatim; anything case-bound is DROPPED, not rewritten."""
    text = json.dumps(payload, ensure_ascii=False, default=str)
    text = _ABSOLUTE.sub("<path>", text)
    text = _HEX_BLOB.sub("<blob>", text)
    doc = json.loads(text)
    doc.setdefault("provenance", {}).update(provenance)
    return doc


def promote_form(payload: dict) -> dict:
    """Stage 2 — code form first (O1): when a script artifact exists it
    is attached as the primary form; prose becomes second-class."""
    src = payload.get("provenance", {}).get("script_path")
    if src:
        payload["form"] = {"kind": "code", "script": src}
        payload["form"].setdefault("prose", payload.get("summary"))
        payload.pop("summary", None)
    else:
        payload["form"] = {"kind": "prose"}
    return payload


def tag(payload: dict, *, capability: str | None = None,
        when_not: list | None = None,
        version_stamps: dict | None = None) -> dict:
    """Stage 3 — capability tag, grown when_not (decision-entry
    negatives join here), version stamps (O3)."""
    meta = payload.setdefault("tags", {})
    if capability:
        meta["capability"] = capability
    if when_not:
        meta["when_not"] = when_not
    meta["version_stamps"] = version_stamps or {}
    return payload


def verify(kind: str, payload: dict, fixture) -> dict:
    """Stage 4 — per-kind verification. `fixture` carries the kind's
    evidence: playbook -> {'milestones_reached': [...]} from a replay;
    decision -> {'statistics'': {...}|None}; the caller runs the
    replay/statistics — the spine adjudicates."""
    if kind == "playbook":
        reached = (fixture or {}).get("milestones_reached") or []
        need = {s.get("expected_evidence") for s in payload["steps"]}
        missing = sorted(need - set(reached))
        return {"ok": not missing,
                "evidence": {"missing_milestones": missing}}
    if kind == "decision":
        stats = (fixture or {}).get("statistics")
        consistent = None if stats is None else bool(
            stats.get("supports", True))
        payload["statistics_consistency"] = consistent
        return {"ok": consistent is not False,
                "evidence": {"statistics_consistency": consistent}}
    return {"ok": False, "evidence": {"reason": "unknown-kind"}}


def dedup(kind: str, payload: dict, existing: list) -> dict:
    """Stage 5 — content-hash exact dedup; (kind, signature) near-dup
    merges as corroboration (the adaptive-compression input)."""
    h = content_hash(payload)
    sig = tuple(payload.get("problem_signature")
                or payload.get("signature_tokens") or ())
    for prior in existing:
        if prior.get("_hash") == h:
            return {"action": "duplicate", "hash": h}
        psig = tuple(prior.get("problem_signature")
                     or prior.get("signature_tokens") or ())
        if psig and psig == sig:
            prior["corroboration"] = prior.get("corroboration", 1) + 1
            prior.setdefault("corroborating_hashes", []).append(h)
            return {"action": "merged", "into": prior.get("name"),
                    "hash": h}
    payload["_hash"] = h
    payload.setdefault("corroboration", 1)
    return {"action": "new", "hash": h}


def tpass(kind: str, payload: dict, *, provenance: dict,
          capability: str | None = None, when_not: list | None = None,
          version_stamps: dict | None = None, fixture=None,
          existing: list | None = None) -> dict:
    """The fixed-order pipeline. Returns {action: new|merged|duplicate|
    archived, product?} — archived means verify failed (honest, never
    silent). Raises SpineOrderError only on contract misuse."""
    bad = validate_product(kind, payload)
    if bad:
        return {"action": "rejected", "violations": bad}
    doc = de_case(payload, provenance)
    doc = promote_form(doc)
    doc = tag(doc, capability=capability, when_not=when_not,
              version_stamps=version_stamps)
    verdict = verify(kind, doc, fixture)
    if not verdict["ok"]:
        return {"action": "archived", "evidence": verdict["evidence"]}
    outcome = dedup(kind, doc, existing or [])
    if outcome["action"] == "new":
        outcome["product"] = doc
    return outcome


# ------------------------------------------------------ source trust -----

def load_trust(ws) -> dict:
    p = Path(ws) / TRUST_REL
    if not p.is_file():
        return {"sources": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {"sources": {}}
    except (OSError, ValueError):
        return {"sources": {}}


def save_trust(ws, doc: dict) -> None:
    p = Path(ws) / TRUST_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n",
                 encoding="utf-8")


def trust_event(ws, source_id: str, landed: bool) -> dict:
    """Record a landed/falsified product for a source; >=2 falsified
    blacklists the source and batch-demotes its landed products."""
    doc = load_trust(ws)
    s = doc["sources"].setdefault(
        source_id, {"landed": 0, "falsified": 0, "trust": 1.0,
                    "blacklisted": False})
    if landed:
        s["landed"] += 1
    else:
        s["falsified"] += 1
    if s["falsified"] >= FALSIFY_BLACKLIST_N and not s["blacklisted"]:
        s["blacklisted"] = True
        s["trust"] = min(s["trust"], 0.1)
        # batch demotion: every landed product of this source
        prod_dir = Path(ws) / PRODUCTS_REL
        if prod_dir.is_dir():
            for f in prod_dir.glob("*.json"):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if d.get("provenance", {}).get("source") == source_id:
                    d["trust_demoted"] = True
                    f.write_text(json.dumps(d, indent=2, sort_keys=True)
                                 + "\n", encoding="utf-8")
    save_trust(ws, doc)
    return s


def blacklisted(ws, source_id: str) -> bool:
    return bool(load_trust(ws)["sources"].get(source_id, {})
                .get("blacklisted"))


def main(argv: list[str] | None = None) -> int:
    cmd = (sys.argv[1:] if argv is None else argv)
    if len(cmd) == 2 and cmd[0] == "trust":
        print(json.dumps(load_trust(cmd[1]), indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
