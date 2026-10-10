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

PR2 (adaptive retention + analogy transfer + landing wiring):
  retention          PURE four-signal adaptive compression
  signals_for        assembles the signals at T-pass time (trust
                     ledger + audit-stream reconstruction telemetry)
  analogy_layers     layer-wise transfer split (Jaccard via #460-B)
  transfer_hypothesis  writes the run-local HYPOTHESIS plan
  land               the ONE landing face — through #474's tier-1 path

Producer flow: r = tpass(..., signals=signals_for(...)); on
r["action"] in ("new", "merged") call land(ws, kind, r["product"]).
Transfers: analogy_layers -> transfer_hypothesis -> the runtime worker
adjudicates (works -> trust_event(landed=True); fails ->
trust_event(landed=False) + obstacle row + decision-entry negative).

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
HYPOTHESES_REL = "runs/distill-hypotheses"
ATTEMPTS_REL = "runs/distill-attempts"
FALSIFY_BLACKLIST_N = 2

# --- PR2 policy constants (adaptive retention / analogy / landing) -------
CORROBORATION_COMPRESS_N = 2   # >= 2 corroborations may compress
TRUST_COMPRESS_FLOOR = 0.5     # below this, retention never compresses
VERIF_STRONG = "byte-exact"    # the full verification strength
VERIF_WEAK = "weak"            # the thin verification strength
FEATURE_ALIGN_FLOOR = 0.5      # Jaccard bar for the technique-family layer

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
            # the merged-into prior rides the outcome: tpass recomputes
            # its retention on the new corroboration count (PR2)
            return {"action": "merged", "into": prior.get("name"),
                    "hash": h, "product": prior}
    payload["_hash"] = h
    payload.setdefault("corroboration", 1)
    return {"action": "new", "hash": h}


def tpass(kind: str, payload: dict, *, provenance: dict,
          capability: str | None = None, when_not: list | None = None,
          version_stamps: dict | None = None, fixture=None,
          existing: list | None = None,
          signals: dict | None = None) -> dict:
    """The fixed-order pipeline. Returns {action: new|merged|duplicate|
    archived, product?} — archived means verify failed (honest, never
    silent); product rides for new AND merged (the merged-into prior,
    post-corroboration). signals (PR2) feeds the adaptive-retention
    stamp — assemble it with signals_for() at T-pass time. Raises
    SpineOrderError only on contract misuse."""
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
    target = doc if outcome["action"] == "new" else outcome.get("product")
    if target is not None:
        sig = dict(signals or {})
        if outcome["action"] == "merged":
            # the merged-into prior keeps ITS OWN source's signals: the
            # incoming assembly describes the NEW source and must never
            # be stamped on the prior's product (trust attribution is
            # per-source). Its last snapshot is the prior's own-source
            # signal state; only corroboration refreshes.
            snap = (target.get("retention") or {}).get(
                "signals_snapshot") or {}
            sig["source_trust"] = snap.get("source_trust")
            sig["verification_strength"] = (
                snap.get("verification_strength") or VERIF_WEAK)
            sig["reconstruction_telemetry"] = (
                snap.get("reconstruction_telemetry") or {})
        # post-dedup truth always wins over the caller's assembly
        sig["corroboration"] = target.get("corroboration", 1)
        block = retention(target, sig)
        target["retention"] = block  # snapshot recorded, always
        _apply_retention(target, block)
        outcome["product"] = target
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


# --------------------------------------------- PR2: adaptive retention ---

def retention(product: dict, signals: dict) -> dict:
    """The four-signal adaptive compression — PURE (no workspace
    access; the signals arrive as data). Returns the retention block
    {detail_level, actions, signals_snapshot}; tpass stamps it onto
    the product as product["retention"].

    Precedence (safety first, deterministic — never a fixed dial):
      1. baseline: corroboration >= CORROBORATION_COMPRESS_N ->
         skeleton, else rich;
      2. weak verification -> rich (never compress what is weakly
         verified);
      3. unearned/low trust (None or < TRUST_COMPRESS_FLOOR) -> rich
         (trust is earned by landing; an unknown source never
         licenses compression);
      4. never-exercised (no retrievals AND no re-derive events) ->
         rich (no exercise evidence tightens);
      5. re-derive events > 0 -> skeleton (runtime proved
         reconstruction, so the skeleton suffices).
    """
    tel = signals.get("reconstruction_telemetry") or {}
    try:
        rederive = int(tel.get("rederive_events") or 0)
        retrievals = int(tel.get("retrievals") or 0)
    except (TypeError, ValueError):
        rederive = retrievals = 0
    trust = signals.get("source_trust")
    trust_ok = (isinstance(trust, (int, float))
                and not isinstance(trust, bool)
                and trust >= TRUST_COMPRESS_FLOOR)
    try:
        corrob = int(signals.get("corroboration",
                                 product.get("corroboration", 1)) or 1)
    except (TypeError, ValueError):
        corrob = 1
    strength = str(signals.get("verification_strength") or VERIF_WEAK)
    detail = ("skeleton" if corrob >= CORROBORATION_COMPRESS_N
              else "rich")
    if (strength != VERIF_STRONG or not trust_ok
            or (retrievals == 0 and rederive == 0)):
        detail = "rich"
    elif rederive > 0:
        detail = "skeleton"
    actions: list[str] = []
    if detail == "skeleton":
        form = product.get("form")
        if isinstance(form, dict) and "prose" in form:
            # the one field promote_form already demoted to second-class
            actions.append("drop:form.prose")
    return {
        "detail_level": detail,
        "actions": actions,
        "signals_snapshot": {
            "corroboration": corrob,
            "source_trust": trust,
            "verification_strength": strength,
            "reconstruction_telemetry": {
                "rederive_events": rederive, "retrievals": retrievals},
        },
    }


def _apply_retention(product: dict, block: dict) -> None:
    """Apply the licensed drops (post-dedup: the stored _hash is
    already fixed, so exact-dup detection is unaffected)."""
    for act in block.get("actions") or []:
        if act == "drop:form.prose":
            form = product.get("form")
            if isinstance(form, dict):
                form.pop("prose", None)


def _classify_audit_row(row: dict, name: str, tool_refs: set,
                        landed: str | None) -> tuple[int, int]:
    """(rederive_delta, retrieval_delta) for one audit row as it
    references THIS product (tool_call naming its landed face or a
    step tool_ref; recall_injected naming the product)."""
    action, tool = row.get("action"), str(row.get("tool") or "")
    if action == "tool_call":
        if landed and tool == landed:
            return 0, 1
        if tool in tool_refs:
            return 1, 0
    elif action == "recall_injected":
        blob = " ".join(str(row.get(k) or "")
                        for k in ("artifact", "detail"))
        if name in blob:
            return 0, 1
    return 0, 0


def reconstruction_telemetry(ws, product: dict) -> dict:
    """Read the audit stream at T-pass time (the design's telemetry
    source — never live). Counts, for THIS product:
      rederive_events — tool_call rows naming one of its steps[]
                       tool_refs (the worker re-executed the encoded
                       technique instead of retrieving the product);
      retrievals      — tool_call rows naming its landed tools-local
                       face + recall_injected rows naming the product.
    Tolerant by construction: missing logs / unreadable or malformed
    rows never count and never raise (absence degrades to the
    conservative tighten path in retention)."""
    counts = {"rederive_events": 0, "retrievals": 0}
    name = str(product.get("name") or "")
    if not name:
        return counts
    tool_refs = {str(s.get("tool_ref"))
                 for s in product.get("steps") or [] if isinstance(s, dict)}
    landed = _candidate_name(name)
    logs = Path(ws) / "runs" / "logs"
    if not logs.is_dir():
        return counts
    for f in sorted(logs.glob("kunglao-*.jsonl")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                d_red, d_ret = _classify_audit_row(row, name, tool_refs,
                                                   landed)
                counts["rederive_events"] += d_red
                counts["retrievals"] += d_ret
    return counts


def signals_for(ws, product: dict, *,
                verification_strength: str = VERIF_WEAK) -> dict:
    """Assemble the four signals at T-pass time: source trust from the
    ledger (None when the source has no earned entry), reconstruction
    telemetry from the audit stream, corroboration from the product.
    verification_strength is the caller's declaration (the fixture's
    business — byte-exact only when the replay actually pinned bytes)."""
    source = str((product.get("provenance") or {}).get("source") or "")
    trust = None
    if source:
        entry = load_trust(ws)["sources"].get(source)
        if isinstance(entry, dict):
            t = entry.get("trust")
            trust = t if isinstance(t, (int, float)) else None
    return {
        "corroboration": product.get("corroboration", 1),
        "source_trust": trust,
        "verification_strength": verification_strength,
        "reconstruction_telemetry": reconstruction_telemetry(ws, product),
    }


# ---------------------------------------------- PR2: analogy transfer -----

def analogy_layers(payload: dict, feature_match: dict) -> dict:
    """The layer-wise analogy split: case-surface is dropped (de_case's
    job — analogy never carries it), methodology is always kept, the
    technique-family layer is kept only when the features align
    (Jaccard over the source signature dims vs the target feature
    tokens, reusing #460-B's pure face). Mismatch dims become the
    explicit holes. feature_match = {"target_tokens": [...]}."""
    from rlvr.feature_prior import jaccard  # noqa: PLC0415 — lazy

    target = {str(t) for t in feature_match.get("target_tokens") or []
              if str(t)}
    dims = [str(d) for d in
            (payload.get("problem_signature")
             or payload.get("signature_tokens") or []) if str(d)]
    aligned = sorted(d for d in dims if d in target)
    holes = sorted(d for d in dims if d not in target)
    sim = jaccard(frozenset(dims), frozenset(target))
    kept = ["methodology"]
    if sim >= FEATURE_ALIGN_FLOOR:
        kept.append("technique-family")
    return {"kept": kept, "holes": holes, "aligned_dims": aligned,
            "similarity": sim}


def transfer_hypothesis(ws, product: dict, *,
                        feature_match: dict | None = None) -> Path:
    """Write the run-local HYPOTHESIS plan: a playbook/1 whose steps
    are the methodology layer, each carrying the mismatch holes and
    unverified: true, for the RUNTIME worker to adjudicate (works ->
    trust_event(landed=True) + "transferred, verified on our sample"
    provenance; fails -> trust_event(landed=False) + obstacle row +
    decision-entry negative). Run-local only — never the product
    store, never a landing."""
    split = (analogy_layers(product, feature_match)
             if feature_match is not None
             else product.get("analogy"))
    if not isinstance(split, dict) or "kept" not in split \
            or "holes" not in split:
        raise SpineOrderError(
            "transfer without analogy adjudication: pass feature_match "
            "or a pre-adjudicated product['analogy'] block — a skipped "
            "stage is never a silent full-confidence plan")
    holes = [str(h) for h in split.get("holes") or []]
    steps = []
    for i, s in enumerate(product.get("steps") or [], start=1):
        if not isinstance(s, dict):
            continue
        steps.append({"n": s.get("n", i), "tool_ref": s.get("tool_ref"),
                      "expected_evidence": s.get("expected_evidence"),
                      "holes": list(holes), "unverified": True})
    if not steps:
        raise SpineOrderError(
            "transfer source has no steps — nothing to hypothesize")
    plan = {
        "schema": PLAYBOOK_SCHEMA,
        "name": f"{product.get('name') or 'transfer'}-hypothesis",
        "problem_signature": list(product.get("problem_signature") or []),
        "steps": steps,
        "hypothesis": {"status": "HYPOTHESIS",
                       "transferred_from": product.get("name"),
                       "layers_kept": list(split.get("kept") or []),
                       "similarity": split.get("similarity"),
                       "holes": list(holes)},
        "provenance": dict(product.get("provenance") or {},
                           transferred=True),
    }
    dest = (Path(ws) / HYPOTHESES_REL
            / f"{_candidate_name(plan['name']) or 'transfer'}.json")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")
    return dest


# ------------------------------------------- PR2: landing through #474 ----

def _candidate_name(name: str) -> str | None:
    """Shelf-safe kebab name (the #474 candidate contract) or None."""
    kebab = re.sub(r"[^a-z0-9-]+", "-", str(name).lower()).strip("-")
    kebab = kebab[:64]
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", kebab):
        return None
    return kebab


def _contained(path: Path, root: Path) -> bool:
    """path resolves under root (the containment guard for
    product-supplied script paths)."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _landing_gates(ws: Path, kind: str, product: dict) -> tuple[str, str]:
    """(source, refusal_reason) — the gates before any write: inlet
    validation, a readable trust ledger (fail-closed), the blacklist,
    and the shared budget ledger's corrupt face. Empty reason = clear."""
    import online_distill  # noqa: PLC0415 — lazy (CLI faces stay light)

    bad = validate_product(kind, product)
    if bad:
        return "", "invalid-product: " + ",".join(bad)
    source = str((product.get("provenance") or {}).get("source") or "")
    trust_path = ws / TRUST_REL
    if trust_path.is_file():
        try:
            json.loads(trust_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return source, "trust-ledger-unreadable"
    if source and blacklisted(ws, source):
        return source, "source-blacklisted"
    if online_distill.ledger_state(ws).get("corrupt"):
        return source, "budget_ledger_unreadable"
    return source, ""


def _land_code_tool(ws: Path, product: dict, cand: str,
                    script: str) -> dict:
    """The tool phase of landing: resolve the product's code form
    (CONTAINED under the workspace or the repo — traversal is refused),
    stage the inputs #474's land_candidate needs, and CALL it. The
    landing itself (tools-local write + manifest + count_landed) stays
    #474's; oracle satisfaction is the T-pass verify verdict."""
    import online_distill  # noqa: PLC0415 — lazy (CLI faces stay light)

    out = {"tool_path": None, "manifest_path": None,
           "tool_landing": ""}
    repo_root = Path(__file__).resolve().parents[1]
    src = ws / script
    if not _contained(src, ws):
        # product-controlled path: traversal out of the workspace never
        # reaches the shelf, existent or not (defense in depth — the
        # repo-relative variant gets the same guard)
        out["tool_landing"] = "script-outside-workspace"
        return out
    if not src.is_file():
        alt = repo_root / script  # script_path may be repo-relative
        src = alt if _contained(alt, repo_root) and alt.is_file() else src
    if not src.is_file():
        out["tool_landing"] = "script-missing"
        return out
    attempt = ws / ATTEMPTS_REL / cand
    attempt.mkdir(parents=True, exist_ok=True)
    (attempt / f"{cand}.py").write_bytes(src.read_bytes())
    report = {
        "schema": online_distill.REPORT_SCHEMA,
        "candidates": [{
            "name": cand,
            "capability": (product.get("tags") or {}).get("capability"),
            "oracle": {"expect_rc": 0, "expect_stdout_contains": ""}}],
        "sources": [{"kind": "spine",
                     "ref": str((product.get("provenance") or {})
                                .get("source") or "unknown")}],
        "methods": [m for m in (
            product.get("method_family"),
            (product.get("tags") or {}).get("capability")) if m],
        "hops": [],
    }
    (attempt / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    oracle = {"satisfied": True,
              "verification": "tpass-verify-ok",
              "evidence": (product.get("retention") or {}).get(
                  "signals_snapshot", {})}
    got = online_distill.land_candidate(ws, attempt, report, cand, oracle)
    if got:
        out["tool_path"], out["manifest_path"] = got
        out["tool_landing"] = "landed"
    else:
        out["tool_landing"] = "land_candidate-refused"
    return out


def land(ws, kind: str, product: dict) -> dict:
    """The spine's ONE landing face — through #474's tier-1 path
    (online_distill), never a second landing:
      1. inlet guard (validate_product — malformed never lands);
      2. trust gate (blacklisted source refuses; an EXISTING but
         unreadable trust ledger refuses fail-closed);
      3. shared budget ledger, fail-closed parity (corrupt refuses; a
         COLD workspace mints via #474's own reinit_run — existing
         ledgers are never touched);
      4. product store write (runs/distill-products/, where
         trust_event's batch demotion reads) — idempotent per content
         hash, a different product under a taken name refuses;
      5. code-form products: _land_code_tool stages and CALLs
         online_distill.land_candidate;
      6. prose-only products: online_distill.count_landed (the shared
         landed counter, never a spine-local write);
      7. trust_event(ws, source, landed=True).
    Re-landing the same product (same content hash, same name) is
    idempotent — counters and trust never double-increment. Every
    refusal carries its reason; a missing script downgrades to
    store-only with the reason recorded — never silent."""
    import online_distill  # noqa: PLC0415 — lazy (CLI faces stay light)

    ws = Path(ws)
    source, reason = _landing_gates(ws, kind, product)
    if reason:
        return {"landed": False, "reason": reason}
    if not (ws / online_distill.LEDGER_NAME).is_file():
        online_distill.reinit_run(ws)  # cold workspace: mint the ledger
    name = str(product.get("name") or "")
    safe = _candidate_name(name) or f"product-{content_hash(product)[:12]}"
    prod_path = ws / PRODUCTS_REL / f"{safe}.json"
    prod_path.parent.mkdir(parents=True, exist_ok=True)
    if prod_path.is_file():
        try:
            prior = json.loads(prod_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prior = None
        if isinstance(prior, dict):
            # _hash-less products (direct callers) fall back to the
            # deterministic content hash — None == None must never read
            # as "same product" (review round-2 LOW)
            prior_hash = prior.get("_hash") or content_hash(prior)
            product_hash = product.get("_hash") or content_hash(product)
            if prior_hash == product_hash:
                return {"landed": True, "product_path": prod_path,
                        "tool_path": None, "manifest_path": None,
                        "tool_landing": "already-landed"}
            return {"landed": False, "reason": "store-name-collision"}
    prod_path.write_text(json.dumps(product, indent=2, sort_keys=True)
                         + "\n", encoding="utf-8")
    out = {"landed": True, "product_path": prod_path,
           "tool_path": None, "manifest_path": None,
           "tool_landing": "skipped-no-code-form"}
    form = product.get("form") or {}
    cand = _candidate_name(name)
    script = (str(form.get("script") or "")
              if form.get("kind") == "code" else "")
    if form.get("kind") == "code" and not script:
        out["tool_landing"] = "code-form-no-script"
    elif form.get("kind") == "code" and not cand:
        out["tool_landing"] = "unsafe-name"
    elif cand and script:
        out.update(_land_code_tool(ws, product, cand, script))
    if out["tool_landing"] != "landed":
        online_distill.count_landed(ws, 1)  # store-only still counts
    if source:
        trust_event(ws, source, landed=True)
    return out


def main(argv: list[str] | None = None) -> int:
    cmd = (sys.argv[1:] if argv is None else argv)
    if len(cmd) == 2 and cmd[0] == "trust":
        print(json.dumps(load_trust(cmd[1]), indent=2))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
