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
import re
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

from harness_common import utc_now_z as _utc_now  # #863 Family F: single source (was a local def)


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
    # #812: tool-tier selection table rides the contract (same optional-key
    # pattern as providers — fail-open, key absent on loader failure; NOT in
    # VERIFIER_SAFE_KEYS, same orchestrator-side class as tier/tools).
    try:
        import tool_tiers as _tt
        tool_tiers_block = _tt.inject_for_workspace(ws)
    except Exception:  # noqa: BLE001 — context build never raises
        tool_tiers_block = None
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
    if tool_tiers_block is not None:
        ctx["tool_tiers"] = tool_tiers_block
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


# ---------- redo GAP slice (issue #772 重做方向盲性缺口) ----------

REDO_CONTEXT_VERSION = 1

# The DIFF's on-disk form is runs/verify-redteam-<target>.md (issue 取证:
# kunglao-redteam's only write contract; the issue title's guessed
# redteam-status-C*.md / evidence/redteam-*.json shapes do not exist).
REDO_DIFF_GLOB = "runs/verify-redteam-*.md"

# Section headers whose BODY is the red team's own derivation — i.e. the
# answer a redo worker would copy. Content under them is withheld wholesale
# (the header line itself degrades to an explicit placeholder so the
# orchestrator can see something was deliberately cut, not lost).
_REDO_WITHHELD_SECTION_MARKERS = (
    "my independent derivation",
)

# machine_check fences (#332) carry expected/actual literals BY CONTRACT —
# exactly what a redo worker must never see.
_REDO_FENCE_RES = (
    re.compile(r"```[^\n]*machine[-_]check[^\n]*\n.*?```", re.DOTALL | re.I),
    re.compile(r"```[^\n]*\n(?:(?!```)[^\n])*\b(?:expected|actual)\b(?:(?!```)[^\n])*```", re.DOTALL | re.I),
)

# Conclusion-led lines (English-only on principle, same posture as
# dispatch_gate._DISPATCH_MUST_STOP_PATTERNS): value-carrying derivation
# lines, not gap-shape lines.
_REDO_DROP_LINE_RES = tuple(
    re.compile(p, re.IGNORECASE) for p in (
        r"^\s*(?:[-*]|\d+[.)]\s*)?(?:my\s+|our\s+)?(?:re)?computed\b.*\d",
        r"\bproducer claimed\b.*\d",
        r"\b(actual|expected)\s+(?:anchor|value|result|output|byte|offset)\b",
        r"^(?:[-*]|\s)*\s*(?:actual|expected)\s*[:=]",
        r"\bderivation chain\b",
    )
)

# Token-level scrubbing. Order matters: ids are PROTECTED first (they are
# bookkeeping references, not derived answers), then addresses / hex /
# decimal magnitudes are redacted. Over-redaction is acceptable — leaking
# an answer is not.
_REDO_ID_PROTECT_RE = re.compile(r"\b([FC]-?\d{3})\b")
_REDO_ADDR_RE = re.compile(r"0[xX][0-9a-fA-F]+")
_REDO_HEX_RE = re.compile(r"\b[0-9a-fA-F]{8,}\b")
_REDO_NUM_RE = re.compile(r"\d{3,}")

_REDO_TITLE_RE = re.compile(r"^#\s*Red-team verification:\s*(.+)$", re.I)
_REDO_CLAIM_RE = re.compile(r"\b(C-\d+)\b")
_REDO_VERDICT_RE = re.compile(
    r"RED-TEAM VERDICT:\s*(CONFIRMED|REFUTED|UNVERIFIED-WITH-GAP)", re.I)
_HEADER_RE = re.compile(r"^#{1,6}\s+")


def _classify_divergence(text: str) -> str:
    """Keyword classification of the divergence SHAPE (never its values):
    anchor_mismatch > method_challenged > evidence_gap > unclassified."""
    t = text.lower()
    if any(k in t for k in ("anchor", "mismatch", "offset", "disagree",
                            "differs")):
        return "anchor_mismatch"
    if any(k in t for k in ("method", "assumption", "granularity",
                            "blind spot", "invalid", "encoding")):
        return "method_challenged"
    if any(k in t for k in ("gap", "unproven", "insufficient",
                            "missing evidence", "coverage")):
        return "evidence_gap"
    return "unclassified"


def _redact_tokens(line: str, counter: list[int]) -> str:
    """Scrub answer-bearing tokens from one kept line.

    Protected claim/fact ids are swapped to digit-free placeholders for the
    duration of the numeric passes — a sentinel that itself contains digits
    would be scrubbed by its own pipeline."""
    saved: list[str] = []

    def prot(m: "re.Match[str]") -> str:
        saved.append(m.group(1))
        return f"\x00{len(saved)}\x00"

    def bump(tag: str) -> str:
        counter[0] += 1
        return f"<redacted-{tag}>"

    out = _REDO_ID_PROTECT_RE.sub(prot, line)
    out = _REDO_ADDR_RE.sub(lambda m: bump("addr"), out)
    out = _REDO_HEX_RE.sub(lambda m: bump("token"), out)
    out = _REDO_NUM_RE.sub(lambda m: bump("num"), out)
    return re.sub("\x00(\\d+)\x00",
                  lambda m: saved[int(m.group(1)) - 1], out)


def _sanitize_diff_body(text: str) -> tuple[list[str], int]:
    """Three mechanical passes over the DIFF text -> kept lines + count.

    1. fenced blocks dropped (machine_check carries expected/actual)
    2. withheld-section bodies dropped (independent derivation = the answer)
    3. conclusion-led lines dropped per regex, surviving tokens redacted
    """
    kept: list[str] = []
    counter = [0]
    body = text
    for fence_re in _REDO_FENCE_RES:
        body = fence_re.sub("[redacted machine-check block]", body)
    in_withheld = False
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        # F1 (#772 r1 review): real DIFF headers carry MD hashes — strip the
        # prefix BEFORE marker comparison or "## My independent derivation"
        # never matches and the answer body rides straight through.
        lowered = stripped.lstrip("#").strip().lower()
        if any(lowered.startswith(m) for m in _REDO_WITHHELD_SECTION_MARKERS):
            in_withheld = True
            kept.append("## [redacted section: independent derivation "
                        "withheld from redo slice (#772)]")
            continue
        if in_withheld and _HEADER_RE.match(stripped) \
                and not lowered.startswith("my independent derivation"):
            in_withheld = False  # next real section resumes
        if in_withheld:
            continue
        if any(rx.search(stripped) for rx in _REDO_DROP_LINE_RES):
            continue
        if stripped.startswith("```"):
            continue
        kept.append(_redact_tokens(raw_line.rstrip(), counter))
    return kept, counter[0]


def _extract_claim_id(title_text: str, name: str) -> str | None:
    m = _REDO_CLAIM_RE.search(title_text or "")
    if m:
        return m.group(1)
    m = re.search(r"(C-\d+)", name or "")
    return m.group(1) if m else None


def latest_redteam_diff(ws: Path) -> Path | None:
    """Most recently written runs/verify-redteam-*.md, or None (fail-open)."""
    runs = ws / "runs"
    if not runs.is_dir():
        return None
    try:
        hits = sorted(runs.glob(Path(REDO_DIFF_GLOB).name),
                      key=lambda p: p.stat().st_mtime)
    except OSError:
        return None
    return hits[-1] if hits else None


def build_redo_context(ws: Path, diff_path: Path | None = None) -> dict:
    """GAP-only redo slice from a red-team DIFF (issue #772).

    Desanitized boundary — the redo worker learns WHERE the prior attempt
    diverged (field mismatch / challenged assumption / alternative method
    direction), NEVER what the red team derived (values, anchors,
    conclusions). Symmetric to #527's verifier BLIND slice but on the
    OPPOSITE edge of maker-checker. Fail-open: a missing/unreadable diff
    yields an honest error-marker dict; this function never raises.
    """
    ws = Path(ws)
    diff_ref: str | None = None
    path: Path | None = None
    if diff_path is not None:
        path = Path(diff_path)
    else:
        path = latest_redteam_diff(ws)
    error: str | None = None
    text: str | None = None
    if path is None:
        error = "diff_not_found"
    elif not path.exists():
        error = "diff_not_found"
    else:
        diff_ref = str(path.name)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            error = "diff_unreadable"
    ctx: dict[str, Any] = {
        "version": REDO_CONTEXT_VERSION,
        "kind": "REDO",
        "diff_ref": diff_ref,
        "claim_id": None,
        "verdict": None,
        "divergence_class": "unclassified",
        "gap": "",
        "challenged": [],
        "hint_direction": (
            "re-derive independently from the raw artifact; the redo must "
            "NOT reuse values seen in prior DIFFs"),
        "sanitized": True,
        "redactions": 0,
    }
    if error is not None or text is None:
        ctx["error"] = error or "diff_not_found"
        return ctx

    title_m = _REDO_TITLE_RE.search(text)
    verdict_m = _REDO_VERDICT_RE.search(text)
    claim_id = _extract_claim_id(
        title_m.group(1) if title_m else "", path.name)
    kept_lines, n_redactions = _sanitize_diff_body(text)

    # gap summary: prefer the GAPs section body (the where-diverged goldmine)
    gaps_header_re = re.compile(r"^#{1,6}\s+gaps\b", re.IGNORECASE)
    gap_body: list[str] = []
    in_gaps = False
    challenged: list[str] = []
    for line in kept_lines:
        s = line.strip()
        low = s.lower()
        if low.startswith("#"):
            in_gaps = bool(gaps_header_re.match(s))
            continue
        if not s or s.startswith("[redacted"):
            continue
        if in_gaps:
            gap_body.append(s.lstrip("-* ").strip())
        if "assumption" in low or "假设" in s:
            c = s.lstrip("-* ").strip()
            if len(c) > 160:
                c = c[:157] + "..."
            if c not in challenged:
                challenged.append(c)
    gap = "; ".join(gap_body)[:600]
    # fall back to Attack attempts shape when no GAPs section exists
    if not gap:
        fallback = [
            ln.strip().lstrip("-* ").strip()
            for ln in kept_lines
            if ln.strip() and not ln.strip().startswith(("#", "[redacted"))
        ]
        gap = "; ".join(fallback)[:600]
    # classify over ALL sanitized shape text — a GAPs body can be neutral
    # prose while the divergence shape lives in Attack attempts
    classification_src = "\n".join(gap_body) + "\n" + "\n".join(kept_lines)
    ctx.update({
        "claim_id": claim_id,
        "verdict": verdict_m.group(1).upper() if verdict_m else None,
        "divergence_class": _classify_divergence(classification_src),
        "gap": gap,
        "challenged": challenged[:5],
        "redactions": n_redactions,
    })
    return ctx


# ---------- CLI (smoke test) ----------

def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Build / validate / write a dispatch context block")
    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("--claim", default=None,
                        help="claim id (C-NN); optional with --redo-diff")
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
    parser.add_argument("--redo-diff", default=None,
                        help="#772: print the GAP-only redo slice built from "
                             "this red-team DIFF file (runs/verify-redteam-*.md)")
    args = parser.parse_args()
    ws = Path(args.workspace)
    if args.verifier_blind:
        blind = verifier_dispatch_view(ws, args.claim)
        print(json.dumps(blind, ensure_ascii=False, indent=2))
        return 0
    if args.redo_diff:
        redo = build_redo_context(ws, Path(args.redo_diff))
        print(json.dumps(redo, ensure_ascii=False, indent=2))
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