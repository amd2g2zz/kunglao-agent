#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""method_families.py — the #432 method-family vocabulary owner.

Loads scripts/method_families.yaml (the CLOSED registry), validates
dispatch envelope declarations against it (fail-closed), quarantines
other(<one-line>) escapes, re-indexes usage into (family, cell) counts
for Q(state signature, method family), and computes the vocabulary
health signals rendered at the existing Q/report face
(experience_triples.q_report).

## Faces

  registry      load_registry() / registered_tokens() — the closed set
  overlay       load_discovered() / the ws-aware registered_tokens() —
                a workspace's runs/discovered-families.yaml merges into
                the CANDIDATE ENUMERATION set only (the discovery layer's
                admitted arms ride it); the repo registry bytes are never
                touched, and without a workspace the set is exactly the
                closed one
  validation    declared_value() + validate_method_family() — the ONE
                gate chokepoint (hooks/worker_budget_sinks.pre_check)
                imports these; dispatch_gate.py stays family-free
  quarantine    other(<one-line>) rows -> runs/method-family-quarantine.jsonl;
                triage() reports frequencies + promotion candidates and
                NEVER auto-promotes (promotion is a reviewed registry
                diff with a new derivation-doc row)
  usage         ALLOW-tail rows -> runs/method-family-log.jsonl; the
                unified-log dispatch row carries method_family=<token>
                so logs replay-re-index
  re-index      reindex(root) — scan a campaign/workspaces root for
                usage logs + unified-log dispatch rows; legacy rows
                without a family count as unattributed (honest gap,
                never fabricated)
  health        family_health(ws) — never-fills / dominates-all /
                other>20%-persistent from (family, cell) usage

## Q-key policy (registry header, repeated here for importers)

A method family names the APPROACH, never the tool chain; it is the Q
key's action half, the tool chain is a rider. Cell keys are claim ids
today; W2 re-keys cells to state_signature hashes (state_signature.py
stays untouched by #432 — this module never imports it, keeping the
issue-396 freeze direction clean).

## CLI

  python scripts/method_families.py --validate <token>
  python scripts/method_families.py --triage <workspace>
  python scripts/method_families.py --reindex <root>
  python scripts/method_families.py --health <workspace>
"""
from __future__ import annotations

import argparse
import json
import re
import sys

from kunglao_log import warn
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

SCHEMA = "method-families/1"
REGISTRY_PATH = Path(__file__).resolve().parent / "method_families.yaml"

USAGE_SCHEMA = "method-family-usage/1"
QUARANTINE_SCHEMA = "method-family-quarantine/1"
USAGE_REL = "runs/method-family-log.jsonl"
QUARANTINE_REL = "runs/method-family-quarantine.jsonl"

# the workspace-local discovery overlay (producer: rlvr/expansion.py —
# this module only READS it; the repo registry stays closed)
DISCOVERED_SCHEMA = "discovered-families/1"
DISCOVERED_REL = "runs/discovered-families.yaml"

OTHER = "other"
OTHER_RE = re.compile(r"^other\((.+)\)$", re.DOTALL)
OTHER_DETAIL_MAX = 120
TOKEN_RE = re.compile(r"^[a-z][a-z0-9-]{2,39}$")

# v0 prose declaration face (the #105 dual-face precedent: v1 envelope
# field OR prose marker; ONE contract, two declaration shapes).
V0_MARKER_RE = re.compile(r"method-family:\s*([^\n]+)", re.IGNORECASE)

# triage / health policy constants (documented, not fitted)
PROMOTION_MIN = 3        # same one-line seen >= N times -> promotion candidate
DOMINANCE_THRESHOLD = 0.8  # one family's share of attributed rows
DOMINANCE_MIN_ROWS = 5     # below this the share is noise, not monoculture
OTHER_SHARE_THRESHOLD = 0.2  # other(...) share of attributed rows
PERSISTENT_CELL_MIN = 3      # ...spanning >= N distinct cells = persistent


class RegistryError(Exception):
    """The registry is missing/malformed — the validator cannot see."""


_REGISTRY_CACHE: dict | None = None


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

def load_registry() -> dict:
    """Parse the closed registry (cached). Raises RegistryError on a
    missing/malformed file — callers translate that into fail-closed
    behavior, never a silent open."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is not None:
        return _REGISTRY_CACHE
    if not REGISTRY_PATH.is_file():
        raise RegistryError(f"registry missing: {REGISTRY_PATH}")
    try:
        data = yaml.safe_load(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"registry unreadable: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise RegistryError(f"registry schema != {SCHEMA}")
    fams = data.get("families")
    if not isinstance(fams, list) or not fams:
        raise RegistryError("registry has no families")
    for f in fams:
        if not isinstance(f, dict) or not isinstance(f.get("token"), str) \
                or not TOKEN_RE.fullmatch(f["token"]):
            raise RegistryError(f"malformed family entry: {f!r:.120}")
    tokens = [f["token"] for f in fams]
    if len(tokens) != len(set(tokens)):
        raise RegistryError("duplicate token in registry")
    _REGISTRY_CACHE = data
    return data


def registered_tokens(ws=None) -> frozenset[str]:
    """The candidate-enumeration vocabulary. No workspace (or a corrupt
    overlay) => exactly the closed repo registry; with one, the
    workspace's admitted discovery arms merge in (repo tokens win — the
    union cannot shadow a mined token)."""
    tokens = {f["token"] for f in load_registry()["families"]}
    if ws is not None:
        tokens.update(str(r["token"]) for r in load_discovered(ws))
    return frozenset(tokens)


def load_discovered(ws) -> list[dict]:
    """Tolerant read of the workspace's discovery overlay. Returns only
    well-formed rows ({token, receipt} with a grammar-valid token);
    absence, corruption, or a schema mismatch read as EMPTY — the set
    behind it stays closed, never half-open."""
    if ws is None:
        return []
    path = Path(ws) / DISCOVERED_REL
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        warn("method_family_overlay",
             f"unreadable ({type(exc).__name__}: {exc}) — vocabulary "
             "stays closed")
        return []
    if not isinstance(data, dict) or data.get("schema") != DISCOVERED_SCHEMA:
        warn("method_family_overlay",
             f"schema mismatch — expected {DISCOVERED_SCHEMA}; vocabulary "
             "stays closed")
        return []
    rows: list[dict] = []
    for f in data.get("families") or []:
        if not isinstance(f, dict) or not isinstance(f.get("token"), str) \
                or not TOKEN_RE.fullmatch(f["token"]) \
                or not str(f.get("receipt") or "").strip():
            continue
        rows.append(f)
    return rows


def _overlay_admits(ws, token: str) -> bool:
    """The provenance gate behind an overlay declaration: the token's
    overlay row cites an expansion receipt that (a) exists in the
    workspace, (b) carries the expansion schema, and (c) lists a
    hypothesis with THIS family among the move's admitted ids."""
    for row in load_discovered(ws):
        if str(row.get("token")) != token:
            continue
        rid = str(row.get("receipt") or "").strip()
        path = Path(ws) / "runs" / "expansion" / f"{rid}.json"
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(doc, dict) or doc.get("schema") != "expansion/1":
            continue
        admitted = {str(h) for h in doc.get("admitted") or []}
        for hyp in doc.get("hypotheses") or []:
            if isinstance(hyp, dict) \
                    and str(hyp.get("family") or "") == token \
                    and str(hyp.get("id") or "") in admitted:
                return True
    return False


# ---------------------------------------------------------------------------
# validation (the ONE gate chokepoint imports these)
# ---------------------------------------------------------------------------

def declared_value(envelope_meta: dict | None, prompt_text: str) -> str | None:
    """The declared method family: v1 envelope field first, v0 prose
    marker second (the #105 dual-face order). None when undeclared."""
    if isinstance(envelope_meta, dict):
        v = envelope_meta.get("method_family")
        if isinstance(v, str) and v.strip():
            return v.strip()
    m = V0_MARKER_RE.search(prompt_text or "")
    if m:
        return m.group(1).strip()
    return None


def validate_method_family(value: str | None,
                           ws=None) -> tuple[bool, str]:
    """Fail-closed vocabulary check. (True, '') iff the value is a
    registered token, a workspace-admitted discovery arm (the overlay
    row's receipt chain must close — see _overlay_admits), or a
    well-formed other(<one-line>) escape. Without a workspace this is
    exactly the closed-registry check."""
    if value is None or not str(value).strip():
        return (False,
                "dispatch declares no method_family (protocol v1 envelope "
                "field, or a `method-family: <token>` line on v0 prompts) "
                "— the approach must be countable for "
                "Q(state signature, method family) (#432).")
    v = str(value).strip()
    try:
        registered = registered_tokens()
    except RegistryError as exc:
        return (False, f"method-family registry unavailable ({exc}) — "
                       "fail-closed per the 2026-09-28 owner ruling")
    if v in registered:
        return (True, "")
    if ws is not None and _overlay_admits(ws, v):
        return (True, "")
    if v == OTHER or v.startswith("other"):
        detail = parse_other_detail(v)
        if detail is None:
            return (False,
                    "method_family=other must carry a one-line reason: "
                    "other(<what approach this actually is>) — a bare "
                    "'other' is a vocabulary dodge, not a declaration.")
        return (True, "")
    pretty = ", ".join(sorted(registered))
    return (False,
            f"method_family {v!r} is unregistered (#432 closed vocabulary). "
            f"Registered tokens: {pretty}. Use other(<one-line>) when no "
            "registered approach fits — the line is quarantined and "
            "triaged for promotion; never invent tokens in dispatches.")


def parse_other_detail(value: str | None) -> str | None:
    """The one-line reason inside other(...), or None when the value is
    not a well-formed escape hatch."""
    if not isinstance(value, str):
        return None
    m = OTHER_RE.match(value.strip())
    if not m:
        return None
    detail = m.group(1).strip()
    if not detail or "\n" in detail or len(detail) > OTHER_DETAIL_MAX:
        return None
    return detail


# ---------------------------------------------------------------------------
# quarantine + usage rows (fail-open bookkeeping at the ALLOW tail)
# ---------------------------------------------------------------------------

def _utc_now_z() -> str:
    return datetime.now(tz=timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _append_jsonl(path: Path, row: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError as exc:
        # fail-open: bookkeeping never blocks an approved dispatch, but the
        # skip is recorded (canonical warn, process-deduped per #419)
        warn("method_family_bookkeeping", f"{type(exc).__name__}: {exc}")


def append_quarantine_row(ws, claim: str | None, detail: str,
                          agent: str | None) -> None:
    """One quarantine row per other(...) dispatch — the triage feed."""
    _append_jsonl(Path(ws) / QUARANTINE_REL, {
        "schema": QUARANTINE_SCHEMA, "ts": _utc_now_z(),
        "claim": claim, "detail": detail, "agent": agent})


def append_usage_row(ws, claim: str | None, family: str, agent: str | None,
                     tier: int = 0, tools: list | None = None) -> None:
    """One usage row per approved dispatch — the (family, cell) counting
    feed. cell = the claim id today; W2 re-keys to state signatures."""
    _append_jsonl(Path(ws) / USAGE_REL, {
        "schema": USAGE_SCHEMA, "ts": _utc_now_z(),
        "claim": claim, "cell": claim, "family": family, "agent": agent,
        "tier": tier, "tools": list(tools or [])})


def _read_jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows: list[dict] = []
    for ln in path.read_text(encoding="utf-8",
                             errors="replace").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def read_usage(ws) -> list[dict]:
    return _read_jsonl(Path(ws) / USAGE_REL)


# ---------------------------------------------------------------------------
# triage face (frequency report, NO auto-promote)
# ---------------------------------------------------------------------------

def triage(ws) -> dict:
    """Quarantine frequency report + promotion candidates. Advisory only:
    the registry is never modified here (promotion is a reviewed diff
    with a new derivation-doc mining row)."""
    counts = Counter()
    claims: dict[str, set[str]] = {}
    for row in _read_jsonl(Path(ws) / QUARANTINE_REL):
        detail = str(row.get("detail") or "").strip()
        if not detail:
            continue
        counts[detail] += 1
        claims.setdefault(detail, set()).add(str(row.get("claim")))
    frequencies = [{"detail": d, "count": c, "cells": len(claims[d])}
                   for d, c in counts.most_common()]
    candidates = [{"detail": d, "count": c, "cells": len(claims[d])}
                  for d, c in counts.items() if c >= PROMOTION_MIN]
    candidates.sort(key=lambda r: (-r["count"], r["detail"]))
    return {"schema": "method-family-triage/1",
            "quarantine_rows": sum(counts.values()),
            "frequencies": frequencies,
            "promotion_candidates": candidates,
            "promotion_min": PROMOTION_MIN,
            "note": "promotion is a reviewed registry diff "
                    "(scripts/method_families.yaml + derivation doc row); "
                    "never automatic"}


# ---------------------------------------------------------------------------
# replay re-index ((family, cell) usage over a campaign/workspaces root)
# ---------------------------------------------------------------------------

_FAMILY_DETAIL_RE = re.compile(r"\bmethod_family=([A-Za-z0-9-]+)")


def reindex(root) -> dict:
    """Re-index dispatch actions into (family, cell) usage counts.
    Legacy dispatch rows WITHOUT a family are counted once as
    unattributed — the honest gap, never a fabricated bucket.

    Face precedence: a workspace that HAS a usage log is counted from
    that face only (its unified-log dispatch rows are skipped) — once
    the #432 gate ships, every approved dispatch lands in BOTH faces and
    summing them would double-count. The log face therefore covers
    legacy/replay workspaces only."""
    root = Path(root)
    cells: Counter = Counter()
    fams: Counter = Counter()
    pair: Counter = Counter()
    unattributed = 0
    total = 0
    usage_roots: set[Path] = set()
    for p in sorted(root.rglob(USAGE_REL)):
        usage_roots.add(p.parent.parent)
        for row in _read_jsonl(p):
            total += 1
            family = str(row.get("family") or "")
            cell = str(row.get("cell") or row.get("claim") or "")
            if not family:
                unattributed += 1
                continue
            fams[family] += 1
            cells[cell] += 1
            pair[(family, cell)] += 1
    for p in sorted(root.rglob("runs/logs/kunglao-*.jsonl")):
        if p.parent.parent in usage_roots:
            continue  # counted from its authoritative usage face already
        for row in _read_jsonl(p):
            if row.get("action") != "dispatch":
                continue
            total += 1
            m = _FAMILY_DETAIL_RE.search(str(row.get("detail") or ""))
            family = m.group(1) if m else ""
            cell = str(row.get("claim") or "")
            if not family:
                unattributed += 1
                continue
            fams[family] += 1
            cells[cell] += 1
            pair[(family, cell)] += 1
    return {
        "schema": "method-family-reindex/1",
        "root": str(root),
        "rows_scanned": total,
        "unattributed": unattributed,
        "families": [{"family": f, "count": c}
                     for f, c in fams.most_common()],
        "cells": [{"cell": cell, "n": n} for cell, n in cells.most_common()],
        "family_cells": [{"family": f, "cell": cell, "n": n}
                         for (f, cell), n in sorted(pair.items())],
    }


# ---------------------------------------------------------------------------
# health signals (rendered at the existing Q/report face)
# ---------------------------------------------------------------------------

def compute_family_health(usage: list[dict],
                          registered: frozenset[str] | None = None) -> dict:
    """Vocabulary health from (family, cell) usage rows:

    - never_fills           registered tokens with zero usage (dead vocab)
    - dominates_all         one family > DOMINANCE_THRESHOLD of attributed
                            rows (monoculture; None below DOMINANCE_MIN_ROWS)
    - other_share_persistent  other(...) rows > OTHER_SHARE_THRESHOLD of
                            attributed rows spanning >= PERSISTENT_CELL_MIN
                            distinct cells (None when concentrated)
    """
    if registered is None:
        registered = registered_tokens()
    fams: Counter = Counter()
    other_cells: set[str] = set()
    attributed = 0
    for row in usage:
        family = str(row.get("family") or "")
        if not family:
            continue
        attributed += 1
        fams[family] += 1
        if family.startswith(f"{OTHER}("):
            other_cells.add(str(row.get("cell") or row.get("claim") or ""))
    used = set(fams)
    never_fills = sorted(registered - used)
    dominates = None
    if attributed >= DOMINANCE_MIN_ROWS:
        top, top_n = fams.most_common(1)[0]
        if top_n / attributed > DOMINANCE_THRESHOLD:
            dominates = {"family": top, "share": round(
                top_n / attributed, 4), "rows": top_n}
    other_persistent = None
    other_n = sum(n for f, n in fams.items() if f.startswith(f"{OTHER}("))
    if attributed and other_n / attributed > OTHER_SHARE_THRESHOLD \
            and len(other_cells) >= PERSISTENT_CELL_MIN:
        other_persistent = {
            "share": round(other_n / attributed, 4), "rows": other_n,
            "cells": sorted(other_cells)}
    return {"never_fills": never_fills,
            "dominates_all": dominates,
            "other_share_persistent": other_persistent,
            "attributed_rows": attributed}


def family_health(ws) -> dict:
    return compute_family_health(read_usage(ws))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="method_families.py",
        description="#432 method-family vocabulary: validate, triage, "
                    "re-index, health")
    ap.add_argument("--validate", metavar="TOKEN",
                    help="validate one method_family declaration")
    ap.add_argument("--triage", metavar="WS",
                    help="quarantine frequency report + promotion candidates")
    ap.add_argument("--reindex", metavar="ROOT",
                    help="re-index a campaign/workspaces root into "
                         "(family, cell) usage")
    ap.add_argument("--health", metavar="WS",
                    help="vocabulary health signals for one workspace")
    args = ap.parse_args(argv)
    if args.validate is not None:
        ok, msg = validate_method_family(args.validate)
        print(json.dumps({"token": args.validate, "ok": ok, "msg": msg},
                         ensure_ascii=False))
        return 0 if ok else 2
    if args.triage:
        print(json.dumps(triage(args.triage), ensure_ascii=False, indent=2))
        return 0
    if args.reindex:
        print(json.dumps(reindex(args.reindex), ensure_ascii=False, indent=2))
        return 0
    if args.health:
        print(json.dumps(family_health(args.health),
                         ensure_ascii=False, indent=2))
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
