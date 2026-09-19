#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""claim_granularity.py — claim granularity discipline (issue 241).

THE GAP (issue 241, wbtest C-005 field evidence): under the issue-239 v2
contract the plan-first gate checks plan EXISTENCE only. A 12+-step plan
hanging on ONE claim ("Reverse white-box crypto core — safeEncrypt
whitebox VM") is itself the "should split" signal — no machinery reads it.
Monolithic claims degrade EVERY downstream channel (spawn-recall quality =
f(dispatch-text domain precision); evidence verification, per-unit
settlement, TS pricing granularity). Fixing recall without fixing
decomposition is re-dicing a lottery machine.

This module is the granularity plane, riding the issue-234 fan-out machinery at
CREATION time (not obstacle time):

  - plan-size gate: a plan exceeding K = GRANULARITY_MAX_STEPS (8)
    enumerated steps is monolithic. Padded/trivial steps ("wait"/"check")
    count toward K — no free passes.
  - domain-span gate: steps referencing >= 2 distinct mechanism families
    with >= GRANULARITY_MIN_FAMILY_STEPS (2) steps each span domains. The
    family vocabulary reuses the issue-234 mechanism families where they fit
    (static-unpacking / dynamic-tracing / memory-imaging / emulation);
    families outside that vocabulary are inference families and are
    LABELLED "(inferred)" in the guidance — never passed off as ladder
    vocabulary.
  - split fan-out: `mint_split_claims` registers one OPEN sub-claim per
    domain group (chunked so each unit covers <= K steps), origin
    granularity-split, `split_for` the parent, a real claim_deps.yaml
    depends_on edge, the `domain_family` tag, answers_question inherited —
    the same construction as target_ladder.mint_sibling_claims (the issue-234
    operator), immediately TS-samplable (priority_ratio.is_open).
    Idempotent on the (origin, split_for, domain_family, split_chunk)
    marker, never on text.

Firing point (post-issue-239 contract): planning is the worker's first act —
on the FIRST dispatch no worker-authored plan exists and the gate is not
armed. The gate fires at the plan-check point of the execution loop (the
re-dispatch leg, hooks/worker_budget_gates.check_claim_granularity) on the
plan the worker authored.

Usage:
  python scripts/claim_granularity.py <ws> --check C-NN   # granularity verdict
  python scripts/claim_granularity.py <ws> --split C-NN   # mint domain sub-claims
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

# The K from issue 241 (calibration "start ~8"): a plan above this many
# enumerated steps is monolithic. Named constant — tests pin the value.
GRANULARITY_MAX_STEPS = 8

# Domain-span threshold: >= 2 distinct families with >= this many steps
# each is a span violation (issue 241 scope, verbatim).
GRANULARITY_MIN_FAMILY_STEPS = 2

GRANULARITY_SPLIT_ORIGIN = "granularity-split"
GRANULARITY_BOUNDARY_TYPE = "granularity-split"

# Step-domain table: (family, inferred, keywords) — FIRST match wins, so
# order is specificity order (network/crypto are keyword-scarce; the broad
# static/dynamic faces come last). Families flagged inferred=True sit
# outside the issue-234 mechanism-family vocabulary and are labelled in the
# guidance; the issue-234 families are labelled as vocabulary.
# "hooking" (issue-234 interception family) folds into dynamic-tracing here: a
# plan step that says "hook" is a dynamic step at plan granularity.
# Keyword precision rule (review round 1): single overloaded words ("dump",
# "memory") do NOT key a family — they collide with other families' steps
# ("dump the binary" is static work) and would force splits of cohesive
# plans. Families key on compound phrases instead; the residual FP risk of
# table keywords is accepted and documented in design.md.
STEP_DOMAIN_TABLE: tuple[tuple[str, bool, tuple[str, ...]], ...] = (
    ("network-replay", True,
     ("network", "replay", "pcap", "http", "tls", "socket", "packet")),
    ("crypto-analysis", True,
     ("crypto", "cipher", "whitebox", "white-box", "sbox", "keystream",
      "aes", "rsa")),
    ("emulation", False,
     ("emulat", "unidbg", "qemu", "unicorn")),
    ("memory-imaging", False,
     ("memory dump", "memdump", "core dump", "heap dump", "process memory",
      "memory image", "imaging", "volatility")),
    ("dynamic-tracing", False,
     ("frida", "x64dbg", "breakpoint", "trace", "attach", "debug",
      "dynamic", "hook")),
    ("static-unpacking", False,
     ("static", "disasm", "ghidra", "decompil", "ida", "strings",
      "unpack", ".rela", "binary")),
)

_STEPS_LINE_RE = re.compile(r"^\s*steps\s*:\s*(.*)$", re.IGNORECASE)
_STEP_MARKER_RE = re.compile(
    r"^\s*(?:[-*+]\s+|\d+\s*[.)]\s+|\[\s?\]\s+)(.*)$")
_HEADING_STEP_RE = re.compile(
    r"^\s*#{1,6}\s*step\s*[-:.]?\s*\d+\s*[.:)\-]?\s*(.*)$", re.IGNORECASE)
_FIELD_LINE_RE = re.compile(
    r"^\s*(goal|preflight|steps|fallback|dispatch-anchor)\s*:",
    re.IGNORECASE)


def parse_plan_steps(plan_text: str) -> list[str]:
    """The plan's enumerated steps (the `steps:` block).

    A bare `steps:` line collects the marker lines that follow (`-`, `*`,
    `+`, `N.`, `N)`, `[ ]`); an inline `steps: do X` counts as ONE step.
    Heading-enumerated steps (`## Step 3: ...` — a natural LLM plan
    format) count EVERYWHERE: inside the `steps:` block alongside the
    marker lines, and — when the block is absent or yields nothing — as
    the whole-document fallback, so a heading-steps plan cannot bypass
    the gate (review round 1 HIGH: `## Step N` blocks parsed as 0 steps).
    Every counted line counts — including padded/trivial ones (issue 241:
    steps of "wait"/"check" count toward K, no free passes). Continuation
    prose and blank lines inside the block are not steps. No enumerable
    step shape at all -> [] (the plan-content contract belongs to
    plan-first/issue-294).
    """
    # BOM strip: mirrors _plan_is_empty_shell's PowerShell/Notepad guard.
    text = plan_text.lstrip("﻿")
    lines = text.splitlines()

    def _heading_step(line: str) -> str | None:
        m = _HEADING_STEP_RE.match(line)
        return m.group(1).strip() if m else None

    for i, line in enumerate(lines):
        m = _STEPS_LINE_RE.match(line)
        if not m:
            continue
        inline = m.group(1).strip()
        if inline:
            return [inline]
        steps: list[str] = []
        for follow in lines[i + 1:]:
            heading = _heading_step(follow)
            if heading is not None:
                steps.append(heading)  # heading steps live INSIDE the block
                continue
            if _FIELD_LINE_RE.match(follow) or follow.lstrip().startswith("#"):
                break
            sm = _STEP_MARKER_RE.match(follow)
            if sm:
                steps.append(sm.group(1).strip())
        if steps:
            return steps
        break  # label present but empty -> fall through to the doc scan
    # no `steps:` label (or it yielded nothing): heading steps anywhere
    return [s for line in lines if (s := _heading_step(line)) is not None]


def infer_step_domains(steps: list[str]) -> list[tuple[str, bool]]:
    """One (family, inferred) tag per step — first keyword match wins."""
    tags: list[tuple[str, bool]] = []
    for step in steps:
        low = step.lower()
        for family, inferred, keywords in STEP_DOMAIN_TABLE:
            if any(k in low for k in keywords):
                tags.append((family, inferred))
                break
        else:
            tags.append(("unclassified", True))
    return tags


def domain_groups(steps: list[str]) -> dict[str, dict]:
    """family -> {"steps": [1-based step numbers], "inferred": bool}.

    Unclassified steps never establish a family of their own when any
    classified family exists (vague step text must not manufacture a
    second domain and manufacture a span violation): they ride the
    dominant classified group. All-unclassified plans keep the single
    "unclassified" group — a size-only shape.
    """
    groups: dict[str, dict] = {}
    for idx, (family, inferred) in enumerate(infer_step_domains(steps), 1):
        g = groups.setdefault(family, {"steps": [], "inferred": inferred})
        g["steps"].append(idx)
    unclassified = groups.pop("unclassified", None)
    if unclassified:
        if groups:
            dominant = max(groups.values(), key=lambda g: len(g["steps"]))
            dominant["steps"].extend(unclassified["steps"])
            dominant["steps"].sort()
        else:
            groups["unclassified"] = unclassified
    return groups


def granularity_defects(plan_text: str) -> tuple[list[str], dict]:
    """The pure granularity predicate: ([], detail) iff the plan is within
    threshold and single-domain. Defects are the named reasons:
      - plan-size:   step count > GRANULARITY_MAX_STEPS
      - domain-span: >= 2 distinct families with >= MIN_FAMILY_STEPS steps
    A plan with no enumerated steps has nothing to measure -> pass (the
    plan-content contract belongs to plan-first issue-294, not this gate).
    """
    steps = parse_plan_steps(plan_text)
    groups = domain_groups(steps) if steps else {}
    detail = {"steps": steps, "step_count": len(steps), "groups": groups}
    defects: list[str] = []
    if not steps:
        return defects, detail
    if len(steps) > GRANULARITY_MAX_STEPS:
        defects.append(
            f"plan-size: {len(steps)} enumerated steps > "
            f"GRANULARITY_MAX_STEPS={GRANULARITY_MAX_STEPS}")
    spanning = {family: g for family, g in groups.items()
                if len(g["steps"]) >= GRANULARITY_MIN_FAMILY_STEPS}
    if len(spanning) >= 2:
        parts = [f"{family} steps {g['steps']}"
                 for family, g in spanning.items()]
        defects.append(
            "domain-span: " + " + ".join(parts)
            + f" (>= {GRANULARITY_MIN_FAMILY_STEPS} steps in >= 2 distinct "
              f"mechanism families)")
    return defects, detail


def plan_files(ws: Path | str, claim_id: str) -> list[Path]:
    """The claim's on-disk plan files — the issue-239 plan-name contract, single
    source: plan-<KEY>.md / plan-<KEY>-*.md, case-folded variants (Windows
    globs are case-insensitive, POSIX are not), sorted per pattern."""
    runs = Path(ws) / "runs"
    if not runs.is_dir():
        return []
    key = claim_id.replace("-", "")
    hits: list[Path] = []
    for pat in (f"plan-{key}.md", f"plan-{key}-*.md",
                f"plan-{key.lower()}.md", f"plan-{key.lower()}-*.md"):
        hits.extend(sorted(runs.glob(pat)))
    return hits


def plan_file(ws: Path | str, claim_id: str) -> Path | None:
    """The first (authoritative) plan file for the claim, or None."""
    hits = plan_files(ws, claim_id)
    return hits[0] if hits else None


def read_plan(plan_path: Path) -> str | None:
    """utf-8-sig read (BOM guard, issue-294 posture); None on OSError."""
    try:
        return plan_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None


def split_guidance(claim_id: str, plan_name: str, defects: list[str],
                   detail: dict) -> str:
    """The mechanical split directive: names the mint entrypoint, the
    parent claim, and the observed domain split (which steps belong to
    which family — issue-234 vocabulary, inference-labelled otherwise)."""
    split_desc = "; ".join(
        f"{family}{' (inferred)' if g['inferred'] else ''} "
        f"steps {g['steps']}"
        for family, g in detail["groups"].items())
    return (
        f"GRANULARITY GATE: claim {claim_id} plan {plan_name} is monolithic "
        f"({'; '.join(defects)}) - split before re-dispatch: run "
        f"python scripts/claim_granularity.py <ws> --split {claim_id} "
        f"(mint_split_claims: the issue-234 fan-out at creation time) to mint "
        f"domain sub-claims with depends_on edges + a domain_family tag "
        f"(each unit under GRANULARITY_MAX_STEPS={GRANULARITY_MAX_STEPS} "
        f"steps), then dispatch the sub-claims; observed split: {split_desc}")


def _split_exists(claims: list, claim_id: str, family: str,
                  chunk_no: int) -> bool:
    """Idempotency marker: (origin, split_for, domain_family, split_chunk) —
    the marker-not-text rule of the issue-234 fan-out. Family comparison is
    case-insensitive (same posture as target_ladder._sibling_exists)."""
    return any(c.get("origin") == GRANULARITY_SPLIT_ORIGIN
               and c.get("split_for") == claim_id
               and str(c.get("domain_family") or "").lower()
               == family.lower()
               and c.get("split_chunk") == chunk_no
               for c in claims)


def _split_units(detail: dict) -> list[tuple[str, bool, int, list[int]]]:
    """Split units (family, inferred, chunk_no, step_numbers) — one per
    domain group; a group larger than K is CHUNKED into units of <= K
    steps (a domain split alone cannot fix a size violation)."""
    units: list[tuple[str, bool, int, list[int]]] = []
    for family, g in detail["groups"].items():
        nums = g["steps"]
        for start in range(0, len(nums), GRANULARITY_MAX_STEPS):
            chunk = nums[start:start + GRANULARITY_MAX_STEPS]
            units.append((family, g["inferred"],
                          start // GRANULARITY_MAX_STEPS + 1, chunk))
    return units


def _split_plan_input(ws: Path, claim_id: str) -> tuple[Path | None,
                                                        str | None,
                                                        str | None]:
    """The plan-input guard: (plan_path, plan_text, refusal) — a non-None
    refusal is terminal and minting must stop with it (explicit, never a
    silent partial write)."""
    plan = plan_file(ws, claim_id)
    if plan is None:
        return (None, None,
                f"no runs/plan-{claim_id}*.md on disk — the "
                f"worker-authored plan is the split input")
    plan_text = read_plan(plan)
    if plan_text is None:
        return None, None, f"plan unreadable: {plan.name}"
    defects, detail = granularity_defects(plan_text)
    if not detail["steps"]:
        return (None, None,
                f"{plan.name} enumerates no steps — nothing to split")
    if not defects:
        return (None, None,
                f"{plan.name} is within the granularity threshold "
                f"(<= {GRANULARITY_MAX_STEPS} steps, single domain) — "
                f"nothing to split")
    return plan, plan_text, None


def mint_split_claims(ws: Path | str, claim_id: str) -> dict:
    """Fan the monolithic plan out into domain sub-claims (issue 241 via the
    issue-234 operator, at CREATION time).

    Same construction as target_ladder.mint_sibling_claims: OPEN claim,
    depends_on the parent, answers_question inherited, a real
    claim_deps.yaml edge, idempotent on the marker (case-insensitive).
    One sub-claim per domain group; a group larger than K is CHUNKED into
    units of <= K steps (a domain split alone cannot fix a size violation).
    Ordering semantics: chunks of the SAME domain chain chunk N+1 ->
    depends_on chunk N (sequential within a domain — step order inside the
    family is preserved); different domains depend only on the parent
    (parallel across domains). The parent is annotated with `split_into`
    provenance and marked SUPERSEDED (superseded_by = the sub-claim ids,
    the issue-59 replacement semantics): the parent's whole scope is now
    carried by the sub-claims, and the pool's superseded_by consult
    (priority_ratio, review round 1) admits the sub-claims past the dep
    gate in ANY workspace — with only the register fallback, a workspace
    holding one settled fact row would dep-block the split forever.

    Guarded (same review-F3 shape as the issue-234 mint): the parent must EXIST
    and the plan must exist, enumerate steps, and be OUTSIDE the threshold
    BEFORE anything is minted — a mistyped id or an already-granular claim
    must never pollute the register and claim_deps.yaml.

    Returns {"minted": [rows], "refused": None} on success (rows may be
    empty when every unit is already minted), or
    {"minted": [], "refused": "<reason>"} — the refusal is explicit, never
    a silent partial write.
    """
    ws = Path(ws)
    # Deferred single-source imports (same shape as the issue-234 mint): the ID
    # grammar from failure_analysis_gate, the register/dep primitives from
    # target_ladder.
    from target_ladder import _ensure_dep_edge, _find_claim, _load_claims
    from failure_analysis_gate import _next_claim_id

    claims, p = _load_claims(ws)
    if p is None:
        return {"minted": [],
                "refused": f"no claim-register.yaml under {ws}"}
    parent = _find_claim(claims, claim_id)
    if parent is None:
        return {"minted": [],
                "refused": f"parent claim {claim_id} not found — refusing "
                           f"to mint split units against a nonexistent "
                           f"parent"}
    plan, plan_text, refusal = _split_plan_input(ws, claim_id)
    if refusal:
        return {"minted": [], "refused": refusal}
    _, detail = granularity_defects(plan_text)

    reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    # chunk N+1 depends_on chunk N within the same domain group (review
    # round 1): sequential execution WITHIN a domain, parallel ACROSS
    # domains. Resolved from existing subs too, so an incremental re-mint
    # after a plan rewrite chains onto the surviving predecessor chunk.
    existing_chunks = {(str(c.get("domain_family") or "").lower(),
                        c.get("split_chunk")): c.get("id")
                       for c in claims
                       if c.get("origin") == GRANULARITY_SPLIT_ORIGIN}
    minted: list[dict] = []
    prior_split_into = list(parent.get("split_into") or [])
    split_into = list(prior_split_into)
    for family, inferred, chunk_no, chunk in _split_units(detail):
        if _split_exists(claims, claim_id, family, chunk_no):
            continue
        new_id = _next_claim_id(claims)
        first_text = " ".join(detail["steps"][chunk[0] - 1].split())
        label = f"{family}{' (inferred)' if inferred else ''}"
        prev_id = existing_chunks.get((family.lower(), chunk_no - 1))
        dep_parents = [claim_id] + ([prev_id] if prev_id else [])
        sub = {
            "id": new_id,
            "status": "OPEN",
            "boundary_type": GRANULARITY_BOUNDARY_TYPE,
            "evidence_tier_attempted": 0,
            "promotion_attempts": 0,
            "depends_on": dep_parents,
            "statement": (f"Split of {claim_id} [{label}]: steps "
                          f"{chunk[0]}-{chunk[-1]} of {plan.name} — "
                          f"{first_text[:120]}"),
            "origin": GRANULARITY_SPLIT_ORIGIN,
            "split_for": claim_id,
            "domain_family": family,
            "split_chunk": chunk_no,
            "split_from_plan": plan.name,
        }
        if (parent or {}).get("answers_question"):
            sub["answers_question"] = parent["answers_question"]
        claims.append(sub)
        reg["claims"] = claims
        p.write_text(
            yaml.safe_dump(reg, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
        for dep in dep_parents:
            _ensure_dep_edge(ws, dep, new_id)
        existing_chunks[(family.lower(), chunk_no)] = new_id
        split_into.append(new_id)
        minted.append({"id": new_id, "family": family, "steps": len(chunk),
                       "chunk": chunk_no})
    if split_into != prior_split_into:
        parent["split_into"] = split_into
        # issue-59 replacement semantics: the parent's scope is fully carried
        # by the minted sub-claims — leaving it OPEN would dep-block every
        # sub-claim out of the dispatchable pool (a split that never ranks
        # is a deadlock, not a split). SUPERSEDED is terminal: the parent
        # exits the frontier. Admission of the sub-claims is the
        # priority_ratio superseded_by consult (review round 1 CRITICAL):
        # the dep gate reads facts/_INDEX rows first, and a workspace with
        # ANY settled fact never reaches the register fallback — so the
        # ranking face treats a depends_on parent carrying superseded_by as
        # satisfied (lineage, not evidence). Settled subs cite subs, never
        # the parent: only this consult lifts the block, permanently.
        parent["status"] = "SUPERSEDED"
        parent["superseded_by"] = list(split_into)
        p.write_text(
            yaml.safe_dump(reg, allow_unicode=True, sort_keys=False),
            encoding="utf-8")
    return {"minted": minted, "refused": None}


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="claim_granularity.py",
        description="Claim granularity discipline (issue 241): plan-size/"
                    "domain-span verdict + split fan-out for monolithic "
                    "claims")
    parser.add_argument("workspace", help="workspace root (claim-register.yaml)")
    parser.add_argument("--check", metavar="C-NN",
                        help="print the granularity verdict for the claim's "
                             "plan (exit 1 when monolithic)")
    parser.add_argument("--split", metavar="C-NN",
                        help="mint one sub-claim per domain group, chunked "
                             "to <= K steps each (idempotent)")
    args = parser.parse_args()
    ws = Path(args.workspace)
    if args.check:
        plan = plan_file(ws, args.check)
        if plan is None:
            print(f"no runs/plan-{args.check}*.md on disk — nothing to "
                  f"check (plan-first owns the no-plan case)")
            return 1
        plan_text = read_plan(plan)
        if plan_text is None:
            print(f"plan unreadable: {plan.name}")
            return 1
        defects, detail = granularity_defects(plan_text)
        if not defects:
            print(f"OK: {plan.name} ({detail['step_count']} steps <= "
                  f"{GRANULARITY_MAX_STEPS}, "
                  f"{len(detail['groups'])} domain group(s))")
            return 0
        print(split_guidance(args.check, plan.name, defects, detail))
        return 1
    if args.split:
        r = mint_split_claims(ws, args.split)
        if r["refused"]:
            print(f"REFUSED: {r['refused']}")
            return 1
        if not r["minted"]:
            print("no new split units (every unit already minted)")
            return 0
        for m in r["minted"]:
            print(f"MINTED {m['id']} <- {args.split} [{m['family']}] "
                  f"steps={m['steps']}")
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
