#!/usr/bin/env python3
"""completion_gate.py — code-owned completion gate (#55).

WHY: termination judgment has been pure LLM discretion — the 2026-08-11
session (#54's cleanest specimen) declared "task complete" with 6 items still
open and ZERO user sign-off, by self-inventing a "备注级（记录即可）" tier and
"deferred" labels neither present in the user's instruction. #54 DETECTS the
fingerprints in the closing declaration; THIS module is the GATE that refuses
the session permission to end until a pre-registered task-oracle.yaml is
satisfied. "done" becomes a CODE verdict, not LLM discretion.

LAYERING — complementary to the three existing termination defenses:
  #43 (runtime drift, scripts/lib_kunglao.py) — per loop iteration; reads the
      ledger signature rotation; catches a SPINNING loop. Does not block.
  #44 (per-turn re-anchor, hooks/state_anchor.py) — PostToolUse(Agent); injects
      mechanical state each turn; cures context rot. Mirrored here for the
      activation + workspace-resolve + FAIL_OPEN structure. Does not block.
  #54 (declaration detector, scripts/premature_termination_detect.py) — scans
      the closing declaration text for 4 fingerprints; REPORT-ONLY (its
      design.md R2 scopes the Stop-hook block to #55). This gate CONSUMES
      #54's detect() output as an OPTIONAL reason-enhancement (design.md D4).
  #55 (THIS) — declaration-TIME GATE: reads task-oracle.yaml (the user's goal,
      pre-registered verbatim) + the open_items ledger and returns a verdict;
      the hooks/completion_gate.py Stop shim BLOCKS termination on non-zero.

judge(oracle, declaration_text=None) -> (exit_code, reason). Exit codes:
  0 = PASS (task_text present, zero unresolved open_items, zero unsigned defers)
  1 = incomplete items remaining (open_items not closed and not user-deferred)
  2 = unsigned defer (a deferral's authorized_by is not a recognized user —
      the #54 self-defer; decided by a MECHANICAL deny-list, not LLM judgment)
  3 = task_text missing (oracle is None / task_text empty — refuse self-anchor,
      the #54 F1 self-anchoring structural fix)

Precedence: exit 3 > exit 2 > exit 1 > exit 0 (first hit wins).

The gate reads ONLY the oracle dict (+ optional declaration text for #54
folding). No workspace state, no network. Heuristic + mechanical, never LLM.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Mechanical policy tables (no LLM judgment; table-driven, extensible)
# ---------------------------------------------------------------------------

# D3: the user-vs-agent discriminator. authorized_by.casefold() in this set ⇒
# agent self-signing ⇒ exit 2. The threat model is specifically the AGENT
# self-deferring (#54); we deny agent identifiers and accept everything else
# (a new user handle works without an allowlist edit).
AGENT_IDENTIFIERS = {
    "agent", "claude", "ai", "self", "assistant", "llm", "kong", "kunglao",
    "worker", "verifier", "orchestrator", "auto", "system", "bot", "me",
}

# D7: comprehensiveness keywords in task_text trigger zero-tolerance + a reason
# clause. CJK entries matched verbatim; ascii entries case-insensitive.
COMPREHENSIVE_KEYWORDS = [
    "全面", "comprehensive", "all", "every", "所有", "逐项", "exhaustive",
]
_COMPREHENSIVE_RE = re.compile(
    "|".join(re.escape(k) for k in COMPREHENSIVE_KEYWORDS), re.IGNORECASE,
)

# D7: self-invented tier terms in a defer reason. Under a comprehensive task,
# a defer carrying one of these is treated as self-invented (the #54 F2
# fingerprint applied to defer records) and pushed to exit 2 even if
# authorized_by looks user-like. A genuine user defer ("不用查") has none.
TIER_TERMS = [
    "备注级", "记录即可", "deferred", "defer", "low-priority", "low priority",
    "nice-to-have", "nice to have", "out-of-scope", "out of scope",
    "信息级", "参考级", "低优先级",
]
_TIER_RE = re.compile(
    "|".join(re.escape(t) for t in TIER_TERMS), re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# User-vs-agent discrimination (D3)
# ---------------------------------------------------------------------------

def is_user_authorized(defer: dict) -> bool:
    """A deferral is user-authorized iff authorized_by is present, non-empty,
    NOT in the AGENT_IDENTIFIERS deny-list, AND (if a `source` field is
    present) it equals exactly 'user'. Mechanical, deterministic."""
    authorized_by = str(defer.get("authorized_by", "") or "").strip()
    if not authorized_by:
        return False
    if authorized_by.casefold() in AGENT_IDENTIFIERS:
        return False
    source = defer.get("source")
    if source is not None and str(source).strip().lower() != "user":
        return False  # source: agent (or anything other than user) ⇒ reject
    return True


# ---------------------------------------------------------------------------
# The gate (pure function; the unit-testable core)
# ---------------------------------------------------------------------------

def judge(oracle, declaration_text=None) -> tuple[int, str]:
    """Judge task completion against a pre-registered task-oracle.

    Returns (exit_code, reason). exit_code in {0, 1, 2, 3} per the module
    docstring; precedence 3 > 2 > 1 > 0. `declaration_text` (the closing
    declaration) is OPTIONAL: when supplied and the gate has resolved to exit
    1, #54's detector is run and its fired fingerprint ids are folded into the
    reason (D4 — corroborating color; the declaration NEVER changes the code).
    """
    # --- exit 3: no anchor (refuse self-produced anchor — #54 F1) ---
    # #147: global contradiction recompute — the workspace, not the oracle,
    # is the authority (replay #2: a pre-filled oracle with zero open_items
    # PASSED while two PROVEN facts contradicted). Import guarded so judge
    # stays pure when there is no workspace context. A workspace without a
    # facts index has zero facts and cannot hold a contradiction.
    ws_path = oracle.get("workspace_path") if isinstance(oracle, dict) else None
    if ws_path:
        try:
            import fact_contradiction_gate as fcg
            from pathlib import Path as _P
            _ws = _P(ws_path)
            if (_ws / "facts" / "_INDEX.md").exists():
                conflicts = fcg.scan_conflicts(_ws / "facts" / "_INDEX.md", _ws / "facts")
                if conflicts:
                    pairs = "; ".join(f"{c['fact_a']} <-> {c['fact_b']}" for c in conflicts)
                    return (1, f"GLOBAL CONTRADICTION: same-topic PROVEN facts with "
                               f"differing conclusions: {pairs}")
        except Exception:  # noqa: BLE001 — FAIL_CLOSED on this path (#147)
            return (1, "GLOBAL CONTRADICTION check unavailable — refuse completion")
    if not isinstance(oracle, dict):
        return (3, "task_text missing: oracle is absent (None) — refuse "
                   "self-produced anchor (the #54 F1 self-anchoring failure)")
    task_text = str(oracle.get("task_text", "") or "").strip()
    if not task_text:
        return (3, "task_text missing/empty — refuse self-produced anchor "
                   "(the #54 F1 self-anchoring failure)")

    open_items = oracle.get("open_items") or []
    deferrals = oracle.get("deferrals") or []
    comprehensive = bool(_COMPREHENSIVE_RE.search(task_text))

    # --- resolve deferrals; collect unsigned / self-invented ---
    valid_deferred_ids: set[str] = set()
    unsigned_defers: list[dict] = []
    for defer in deferrals:
        if not isinstance(defer, dict):
            continue
        item_id = str(defer.get("item", "") or "").strip()
        if not is_user_authorized(defer):
            unsigned_defers.append(defer)
            continue
        # user-authorized. Under a comprehensive task, a defer reason carrying
        # a self-invented tier term is treated as self-invented (#54 F2).
        if comprehensive and item_id:
            reason_text = str(defer.get("reason", "") or "")
            if _TIER_RE.search(reason_text):
                unsigned_defers.append(defer)
                continue
        if item_id:
            valid_deferred_ids.add(item_id)

    # --- exit 2: unsigned defer (precedence over exit 1 — the diagnostic signal) ---
    if unsigned_defers:
        parts = []
        for d in unsigned_defers:
            item = str(d.get("item", "?"))
            ab = str(d.get("authorized_by", ""))
            parts.append(f"{item} (authorized_by={ab!r})")
        label = ("agent self-signing rejected (the #54 self-defer)"
                 if any(not is_user_authorized(d) for d in unsigned_defers)
                 else "self-invented tier under comprehensive mandate")
        return (2, f"unsigned defer — {label}: " + "; ".join(parts))

    # --- exit 1: unresolved open items ---
    unresolved: list[dict] = []
    for item in open_items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id", "") or "").strip()
        closed_by = str(item.get("closed_by", "") or "").strip()
        if closed_by:
            continue  # resolved by completion
        if item_id and item_id in valid_deferred_ids:
            continue  # resolved by a user-signed defer
        unresolved.append(item)

    if unresolved:
        ids = [str(it.get("id", "?")) for it in unresolved]
        comp_clause = ""
        if comprehensive:
            comp_clause = ("[全面/comprehensive mandate — zero-tolerance: "
                           "task demands exhaustive coverage; no item may be "
                           "re-tiered or deferred without user sign-off] ")
        reason = (comp_clause + f"{len(unresolved)} unresolved open item(s): "
                  + ", ".join(ids))
        # D4: optional #54 fingerprint folding (declaration never changes the code)
        if declaration_text:
            try:
                import premature_termination_detect as pt
                report = pt.detect(declaration_text, task_text=task_text)
                if report.get("fired_count", 0) > 0:
                    fids = ", ".join(report.get("fired_ids", []))
                    reason += f" [declaration fingerprints: {fids}]"
            except Exception:  # noqa: BLE001 — detector optional; reason stays oracle-only
                pass
        return (1, reason)

    # --- exit 0: PASS ---
    n_closed = sum(
        1 for it in open_items
        if isinstance(it, dict) and str(it.get("closed_by", "") or "").strip()
    )
    n_deferred = len(valid_deferred_ids)
    return (0, f"PASS: {len(open_items)} open_item(s) resolved "
              f"({n_closed} closed, {n_deferred} user-deferred)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Code-owned completion gate (#55). Reads a task-oracle.yaml "
                    "and judges completion: 0 pass / 1 incomplete / 2 unsigned "
                    "defer / 3 task_text missing.",
    )
    parser.add_argument("oracle_file", help="path to a UTF-8 YAML task-oracle.yaml")
    parser.add_argument("--declaration-file", dest="declaration_file", default=None,
                        help="optional UTF-8 text of the closing declaration "
                             "(folds #54 fingerprints into the reason)")
    args = parser.parse_args(argv)

    oracle_path = Path(args.oracle_file)
    if not oracle_path.exists():
        msg = (f"oracle file missing: {args.oracle_file} — cannot judge "
               f"completion without a pre-registered anchor")
        print(json.dumps(
            {"exit_code": 3, "reason": msg, "oracle_file": args.oracle_file},
            ensure_ascii=False, indent=2))
        return 3

    try:
        oracle = yaml.safe_load(oracle_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        msg = f"oracle file unreadable: {exc} — refuse self-produced anchor"
        print(json.dumps(
            {"exit_code": 3, "reason": msg, "oracle_file": args.oracle_file},
            ensure_ascii=False, indent=2))
        return 3

    declaration_text = None
    if args.declaration_file:
        try:
            declaration_text = Path(args.declaration_file).read_text(encoding="utf-8")
        except OSError:
            declaration_text = None  # optional — degrade to oracle-only

    code, reason = judge(oracle, declaration_text=declaration_text)
    out = {
        "exit_code": code,
        "reason": reason,
        "verdict": {0: "PASS", 1: "INCOMPLETE", 2: "UNSIGNED_DEFER",
                    3: "NO_ANCHOR"}.get(code, "UNKNOWN"),
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
