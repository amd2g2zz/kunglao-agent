# -*- coding: utf-8 -*-
"""refutation_propagate.py — propagate refutation along claim deps (#241).

SKILL.md contract: "refutation propagates along deps (not a full re-plan)".
Before this script that propagation was pure convention: nothing scanned the
register for REFUTED/NEGATIVE claims and re-flagged their dependents, so a
refuted dependency left dependents standing PROVEN while the loop kept
dispatching on poisoned ground.

Mechanics:
  - scan claim-register.yaml for claims with status REFUTED | NEGATIVE
  - reverse-walk claim_deps.yaml depends_on: every claim whose parent list
    contains a refuted claim gets `needs_re-eval: true` on its register entry
  - NEVER changes statuses — marking only, no cascade avalanche; the
    convergence loop re-ranks claims carrying needs_re-eval

Usage:
  python refutation_propagate.py <workspace> [--dry-run]
Exit codes:
  0 = nothing to mark (no REFUTED/NEGATIVE claims, or no new dependents)
  1 = at least one dependent marked
"""
from __future__ import annotations

# #534: observability lifeline — module-level emit on load.
import kunglao_log  # noqa: E402

# #534: observability lifeline — module-level emit on load.
try:
    kunglao_log.emit(ws, actor="refutation_propagate", action="claim_migrate",
                                    detail="module wired")
except NameError:
    pass

import argparse
import sys
from pathlib import Path

import yaml

# The two "this claim's verdict is wrong" closures. TERMINAL (status_defs)
# also contains DEFERRED/STALE/SUPERSEDED/DEAD — those are dead-ends, not
# poison: a dependents' position is only invalidated when the parent verdict
# itself was refuted. REFUTED/NEGATIVE follow status_defs semantics.
TRIGGER_STATUSES = frozenset({"REFUTED", "NEGATIVE"})


def load_yaml(p: Path) -> dict:
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def write_yaml(p: Path, data: dict) -> None:
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def find_refuted_claims(reg: dict) -> set:
    """Ids of claims whose verdict is refuted/negative (the poison sources)."""
    out = set()
    for c in (reg or {}).get("claims", []) or []:
        if (c.get("status") or "").upper() in TRIGGER_STATUSES and c.get("id"):
            out.add(c.get("id"))
    return out


def find_dependents(deps: dict, refuted_ids: set) -> set:
    """Reverse walk: claims whose depends_on list contains a refuted id.

    claim_deps.yaml shape: depends_on: {C-201: [C-007, C-008]} — the VALUE
    list holds the parents (dependencies) of the KEY claim. So a claim whose
    value list intersects the refuted ids is a direct dependent.
    """
    out = set()
    depends_on = (deps or {}).get("depends_on", {}) or {}
    for child, parents in depends_on.items():
        if refuted_ids & set(parents or []):
            out.add(child)
    return out


def mark_dependents(ws: Path, dry_run: bool = False) -> list:
    """Mark dependents of REFUTED/NEGATIVE claims with needs_re-eval: true.

    Returns the list of claim ids newly marked. Idempotent: claims already
    carrying needs_re-eval are skipped, so repeated runs stop rewriting the
    register (no churn). Claim statuses are NEVER changed. Dependents that
    exist in claim_deps.yaml but not in the register are reported on stdout
    (they cannot be marked).
    """
    reg_path = ws / "claim-register.yaml"
    reg = load_yaml(reg_path)
    deps = load_yaml(ws / "claim_deps.yaml")

    refuted = find_refuted_claims(reg)
    dependents = find_dependents(deps, refuted)
    registered = {c.get("id") for c in (reg or {}).get("claims", []) or []}

    for missing in sorted(dependents - registered):
        print(f"  ! dependent {missing} exists in claim_deps.yaml but not in claim-register (cannot mark)")

    marked = []
    for c in (reg or {}).get("claims", []) or []:
        if c.get("id") in dependents and not c.get("needs_re-eval"):
            c["needs_re-eval"] = True
            marked.append(c.get("id"))

    if marked and not dry_run and reg_path.exists():
        write_yaml(reg_path, reg)
    return marked


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="Propagate refutation along claim deps (#241)")
    parser.add_argument("workspace", help="workspace root")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be marked without writing")
    args = parser.parse_args(argv)

    ws = Path(args.workspace)
    reg = load_yaml(ws / "claim-register.yaml")
    refuted = sorted(find_refuted_claims(reg))
    if not refuted:
        print("refutation_propagate: no REFUTED/NEGATIVE claims — nothing to propagate")
        return 0

    marked = mark_dependents(ws, dry_run=args.dry_run)
    mode = "dry-run" if args.dry_run else "marked"
    print(f"refutation_propagate ({mode}): refuted={refuted}")
    if marked:
        print(f"  needs_re-eval -> {sorted(marked)}")
        return 1
    print("  no new dependents to mark (already flagged or none registered)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
