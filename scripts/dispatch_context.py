#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dispatch_context.py — issue #527 派单 context 块机械化.

Builds the structured context block that the worker channel MUST receive
on every passing dispatch. Pre-#527 the worker got the raw dispatch prompt
alone; structural context (fact snapshot, priority state, validated
capability, plan reference, sibling claims) had to be re-derived by the
worker — and the verifier could not be safely BLIND because the same
dispatch prompt carried that information.

The fix is MECHANICAL:

  - build_dispatch_context(workspace, claim_id, tier, tools, agent)
      -> dict: the FULL context block (orchestrator-side view only)
  - apply_dispatch_context(workspace, context_dict)
      -> Path: writes runs/dispatch-context-C<NN>.json (FAIL_OPEN writer)
  - dispatch_inject(context_dict) -> str
      prompt-side injection (the marker KUNGLAO_DISPATCH_CONTEXT wraps the
      JSON; the worker greps it from the prompt)
  - validate_context_shape(context_dict) -> None
      raises on contract violation (mandatory keys + value constraints)
  - verifier_dispatch_view(workspace, claim_id) -> dict
      the BLIND slice — facts + plan only, no orchestrator context
  - VERIFIER_SAFE_KEYS (frozenset): explicit allow-list of what the
      verifier may see; anything not in this set is structurally excluded.

#527 integration with #461 dispatch_linkage: dispatch_linkage owns the
lifecycle event (renew / arm / phase=DISPATCH + heartbeat tick) at the
worker_budget.pre_check point. The context block is an ADDITIONAL artifact
written alongside, in the same lifecycle event. The two are intentionally
separate (the linkage call must stay usable even when the context build
fails — and the context build must stay usable even when linkage is dormant).

Fail-open posture: a missing facts/ dir, an unreadable claim-register, an
unavailable priority scorer — all result in partial context (None / empty
list / FAIL_OPEN defaults), NEVER an exception. The validate_context_shape
function is the only strict face and it is invoked explicitly by tests.

BLIND guarantees (issue #527 verifier BLIND 硬排除):
  1. The dedicated verifier entry is a HAND-ROLLED read from facts/ + plan/
     ONLY — it never calls build_dispatch_context (which would re-introduce
     the orchestrator surface).
  2. The artifact lives in runs/dispatch-context-C<NN>.json — a path
     verifier_dispatch_view deliberately does not read.
  3. The safe-key allow-list is an explicit frozenset constant, never a
     dynamic "all keys except N" filter (which silently widens on schema
     additions).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

# ---------- constants ----------

CONTEXT_BLOCK_VERSION = 1
DISPATCH_INJECT_MARKER = "KUNGLAO_DISPATCH_CONTEXT"
DISPATCH_CONTEXT_FILE = "runs/dispatch-context-{nid}.json"

# Verifier safe-key allow-list — explicit, immutable. Adding a key here is
# the gate to allowing the verifier to see it. Issue #527 forbids:
#   - agent (worker assignment leaks expectations)
#   - tier / tools (the dispatch contract, not the artifact under test)
#   - dispatch_ts (orchestrator timing)
#   - priority_context / sibling_claims / validated_capability
#     (priority rankings — the verifier pattern-matcher's failure mode)
VERIFIER_SAFE_KEYS: frozenset[str] = frozenset({
    "claim_id",
    "fact_snapshot",
    "facts",
    "plan_ref",
})


# ---------- helpers ----------

def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z")


def _claim_key(claim_id: str) -> str:
    """C-001 -> C001 for filename conventions (strip the dash, keep the C)."""
    return claim_id.replace("-", "")


def _load_yaml(path: Path) -> dict:
    if not path or not Path(path).exists():
        return {}
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _read_claim(ws: Path, claim_id: str) -> dict | None:
    reg = _load_yaml(ws / "claim-register.yaml")
    for c in reg.get("claims") or []:
        if c.get("id") == claim_id:
            return c
    return None


def _fact_snapshot(ws: Path) -> dict:
    """Count + list of fact files under facts/ (FAIL_OPEN on any error).

    Excludes the _INDEX.md registry file — that is the manifest, not a
    fact. Matches the priority_ratio/EvidenceView convention: only
    file basenames matching fact naming (F0/F1 prefix) count."""
    facts_dir = ws / "facts"
    if not facts_dir.is_dir():
        return {"count": 0, "files": []}
    try:
        files = sorted(p.name for p in facts_dir.glob("*.md")
                       if p.is_file() and not p.name.startswith("_"))
    except OSError:
        return {"count": 0, "files": []}
    return {"count": len(files), "files": files}


def _priority_context(ws: Path, claim_id: str) -> dict:
    """Priority context for the dispatched claim — top-ranked claim +
    optional ratio. FAIL_OPEN: scorer unavailable -> ratio=None."""
    pc: dict[str, Any] = {"dispatched": claim_id, "top_rank": None,
                          "ratio": None, "deviation_reason": None}
    reg = _load_yaml(ws / "claim-register.yaml")
    claims = [c for c in (reg.get("claims") or []) if c.get("id")]
    if not claims:
        return pc
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        import priority_ratio as pr  # type: ignore
        from priority_ratio import EvidenceView  # type: ignore
        evidence = EvidenceView.from_workspace(ws)
        actions = pr.priority_ratio(claims, {}, evidence)
    except Exception:
        return pc
    if not actions:
        return pc
    top = actions[0]
    pc["top_rank"] = top.claim_id
    if top.claim_id != claim_id:
        # dispatch deviation — record for the audit trail
        rank = next((i + 1 for i, a in enumerate(actions)
                    if a.claim_id == claim_id), None)
        if rank is not None:
            pc["deviation_reason"] = (
                f"{claim_id} rank #{rank} (score {actions[rank - 1].score}); "
                f"top is {top.claim_id} (score {top.score})")
    return pc


def _validated_capability(ws: Path, claim_id: str) -> dict:
    """Validated capability for the claim (or its obstacle_for parent)."""
    try:
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).parent))
        import priority_ratio as pr  # type: ignore
        from priority_ratio import EvidenceView  # type: ignore
        evidence = EvidenceView.from_workspace(ws)
        claim_ids = {claim_id}
        target = _read_claim(ws, claim_id)
        parent = (target or {}).get("obstacle_for")
        if parent:
            claim_ids.add(str(parent))
        for cid, cap in evidence.validated_capabilities:
            if cid in claim_ids:
                return {"claim_id": cid, "capability": cap}
    except Exception:
        pass
    return {}


def _plan_ref(ws: Path, claim_id: str) -> str | None:
    """runs/plan-C<NN>.md (case-insensitive glob — Windows/POSIX parity)."""
    key = _claim_key(claim_id)
    runs = ws / "runs"
    if not runs.is_dir():
        return None
    for pat in (f"plan-{key}.md", f"plan-{key}-*.md",
                f"plan-{key.lower()}.md", f"plan-{key.lower()}-*.md"):
        hits = sorted(runs.glob(pat))
        if hits:
            rel = hits[0].relative_to(ws)
            return str(rel).replace("\\", "/")
    return None


def _sibling_claims(ws: Path, claim_id: str) -> list[dict]:
    """Sibling claims — those that obstacle_for this claim (children in the
    obstacle graph) and those that share an obstacle_for parent."""
    reg = _load_yaml(ws / "claim-register.yaml")
    out: list[dict] = []
    for c in (reg.get("claims") or []):
        if c.get("id") == claim_id:
            continue
        # child obstacle
        if c.get("obstacle_for") == claim_id:
            out.append({"id": c.get("id"), "relation": "obstacle_child",
                        "status": c.get("status", "OPEN")})
            continue
        # sibling via shared obstacle_for
        target = _read_claim(ws, claim_id)
        target_parent = (target or {}).get("obstacle_for")
        if target_parent and c.get("obstacle_for") == target_parent:
            out.append({"id": c.get("id"), "relation": "sibling",
                        "status": c.get("status", "OPEN")})
    return out


# ---------- public API ----------

def _providers_block(ws: Path, capability: str | None) -> dict | None:
    """#692 WP4 (design D5): the ranked provider block for one capability.

    Fail-open: any failure (missing index, unparseable state, selection
    error) omits the block — the context build never raises. Returns the
    select_providers result {capability, providers, recommendation,
    rationale} or None when there is no capability / no provider rows.
    """
    if not capability:
        return None
    try:
        import route_capability as rc  # sibling (scripts/ on sys.path)

        tools = rc.load_index(rc.DEFAULT_INDEX)
        if not tools:
            return None
        state = rc.load_workspace_state(ws)
        result = rc.select_providers(capability, tools, state)
        if not result.get("providers"):
            return None
        return result
    except Exception:  # noqa: BLE001 — fail-open, never block dispatch
        return None


def build_dispatch_context(
    *,
    ws: Path,
    claim_id: str,
    tier: int,
    tools: list[str],
    agent_name: str,
    capability: str | None = None,
) -> dict:
    """Build the FULL dispatch context block (orchestrator-side view).

    Required keys (issue #527): claim_id, tier, tools, agent, dispatch_ts,
    workspace_ref, priority_context, fact_snapshot, validated_capability,
    plan_ref, sibling_claims, version.

    Returns a plain dict (caller decides serialization / injection)."""
    ws = Path(ws)
    # #692 WP4: providers ride the context (fail-open, optional key) so the
    # worker holds in-flight degradation authority; explicit capability
    # wins, else the claim's validated capability. NOT in
    # VERIFIER_SAFE_KEYS — the verifier stays BLIND to the dispatch
    # contract (same class as tier/tools).
    try:
        providers = _providers_block(
            ws,
            capability or _validated_capability(
                ws, claim_id).get("capability"))
    except Exception:  # noqa: BLE001 — context build never raises
        providers = None
    ctx = {
        "version": CONTEXT_BLOCK_VERSION,
        "claim_id": claim_id,
        "tier": tier,
        "tools": list(tools),
        "agent": agent_name,
        "dispatch_ts": _utc_now(),
        "workspace_ref": str(ws),
        "priority_context": _priority_context(ws, claim_id),
        "fact_snapshot": _fact_snapshot(ws),
        "validated_capability": _validated_capability(ws, claim_id),
        "plan_ref": _plan_ref(ws, claim_id),
        "sibling_claims": _sibling_claims(ws, claim_id),
    }
    if providers is not None:
        ctx["providers"] = providers
    return ctx


def validate_context_shape(ctx: dict) -> None:
    """Strict validation — raises ValueError on contract violation.

    Mandatory keys: claim_id (C-NN format), tier (1|2|3), tools (list[str]),
    agent (str), dispatch_ts (ISO 8601 Z), workspace_ref (str),
    priority_context (dict), fact_snapshot (dict), validated_capability
    (dict), plan_ref (str|None), sibling_claims (list), version (int)."""
    required = {
        "claim_id": str,
        "tier": int,
        "tools": list,
        "agent": str,
        "dispatch_ts": str,
        "workspace_ref": str,
        "priority_context": dict,
        "fact_snapshot": dict,
        "validated_capability": dict,
        "plan_ref": (str, type(None)),
        "sibling_claims": list,
        "version": int,
    }
    for key, typ in required.items():
        if key not in ctx:
            raise ValueError(f"context missing required key: {key!r}")
        if not isinstance(ctx[key], typ):
            raise ValueError(
                f"context key {key!r} has wrong type: "
                f"got {type(ctx[key]).__name__}, expected "
                f"{getattr(typ, '__name__', str(typ))}")
    # value constraints
    import re as _re
    if not _re.fullmatch(r"C-\d+", str(ctx["claim_id"])):
        raise ValueError(
            f"context claim_id {ctx['claim_id']!r} is not C-NN format")
    if ctx["tier"] not in (1, 2, 3):
        raise ValueError(
            f"context tier {ctx['tier']} is not in {{1, 2, 3}}")
    if not str(ctx["dispatch_ts"]).endswith("Z"):
        raise ValueError(
            f"context dispatch_ts {ctx['dispatch_ts']!r} is not UTC Z-form")
    # #692 WP4: providers is OPTIONAL (#527 backward compat); when present
    # it must be the select_providers face: {capability, providers, ...}.
    if "providers" in ctx:
        prov = ctx["providers"]
        if not isinstance(prov, dict) or "capability" not in prov \
                or "providers" not in prov:
            raise ValueError(
                "context 'providers' must be a dict carrying "
                "'capability' and 'providers' keys (the #692 "
                "select_providers face)")


def apply_dispatch_context(ws: Path, ctx: dict) -> Path:
    """Persist the dispatch context to runs/dispatch-context-C<NN>.json.

    Fail-open writer — does NOT call validate_context_shape (a malformed
    ctx is written verbatim and the strict face is the caller's concern).
    Returns the path written (creates parent dirs if missing)."""
    ws = Path(ws)
    claim_id = str(ctx.get("claim_id") or "UNKNOWN")
    nid = _claim_key(claim_id)
    path = ws / DISPATCH_CONTEXT_FILE.format(nid=nid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ctx, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def dispatch_inject(ctx: dict) -> str:
    """Render the context block as a prompt-injectable string.

    Marker `KUNGLAO_DISPATCH_CONTEXT` brackets the JSON; the worker greps
    the marker to extract the context (mirrors the v0 facts-snapshot marker
    discipline in worker_budget.pre_check)."""
    return (
        f"<!-- {DISPATCH_INJECT_MARKER} v{CONTEXT_BLOCK_VERSION} -->\n"
        f"```json\n{json.dumps(ctx, ensure_ascii=False, indent=2)}\n```\n"
        f"<!-- /{DISPATCH_INJECT_MARKER} -->"
    )


# ---------- verifier BLIND slice (issue #527 硬排除) ----------

def verifier_dispatch_view(ws: Path, claim_id: str) -> dict:
    """BLIND slice for the verifier — facts + plan only.

    #527 硬排除 contract: the verifier MUST NOT see orchestrator-side
    context (agent, priority_context, sibling_claims, validated_capability,
    dispatch_ts, tools, tier). This function is hand-rolled from facts/ +
    plan/ — it NEVER calls build_dispatch_context (which would re-introduce
    the orchestrator surface; tests pin this as a separate symbol).

    The slice is filtered through VERIFIER_SAFE_KEYS — an explicit allow-
    list, never a dynamic "all keys except N" filter (which silently widens
    on schema additions).
    """
    ws = Path(ws)
    # Hand-rolled BLIND payload — built from the verifier's own data
    # sources (facts/ + plan/), not from the orchestrator context block.
    raw: dict[str, Any] = {
        "claim_id": claim_id,
        "fact_snapshot": _fact_snapshot(ws),
        "plan_ref": _plan_ref(ws, claim_id),
    }
    # Filter through the safe-key allow-list (defense-in-depth — even if a
    # future edit added a key to raw, the filter rejects it).
    return {k: v for k, v in raw.items() if k in VERIFIER_SAFE_KEYS}


# ---------- CLI (smoke test) ----------

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Build / validate / write a #527 dispatch context block")
    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("--claim", required=True, help="claim id (C-NN)")
    parser.add_argument("--tier", type=int, default=1, choices=[1, 2, 3])
    parser.add_argument("--tools", default="", help="comma-separated tools")
    parser.add_argument("--agent", default="kunglao-worker",
                        help="dispatch agent name")
    parser.add_argument("--write", action="store_true",
                        help="persist to runs/dispatch-context-C<NN>.json")
    parser.add_argument("--inject", action="store_true",
                        help="print the prompt-injectable string")
    parser.add_argument("--verifier-blind", action="store_true",
                        help="print the BLIND verifier slice instead")
    args = parser.parse_args()
    ws = Path(args.workspace)
    if args.verifier_blind:
        blind = verifier_dispatch_view(ws, args.claim)
        print(json.dumps(blind, ensure_ascii=False, indent=2))
        return 0
    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    ctx = build_dispatch_context(ws=ws, claim_id=args.claim, tier=args.tier,
                                 tools=tools, agent_name=args.agent)
    validate_context_shape(ctx)
    if args.write:
        path = apply_dispatch_context(ws, ctx)
        print(f"OK: wrote {path}")
    elif args.inject:
        print(dispatch_inject(ctx))
    else:
        print(json.dumps(ctx, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())