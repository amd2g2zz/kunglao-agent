#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""context_budget.py — issue 300 WS1: per-dispatch fixed context bytes.

Every worker session pays a FIXED rules tax before any task content:
the worker constitution (agents/kunglao-worker.md) plus the workspace
handbook rendered from templates/CLAUDE.md.base.tmpl. The 2026-09-20
audit (issue 300) measured that tax growing 22KB -> 35KB (+58%) and
8.3KB -> 18.5KB (+123%) while the toolbox stood still — the model was
diluted by a rulebook that doubles.

THE BUDGET RULE
    fixed context bytes (constitution + template) must stay
    <= CAP_RATIO x (v0.1 baseline bytes)

THE AUDIT PROCEDURE FOR FUTURE SECTIONS (rule-12 gate)
    Before adding any section (constitution or template), answer BOTH:
      1. CONSUMER   — which role reads it, at which moment?
      2. BEHAVIOR DELTA — what will the agent DO differently because of
         this line, compared to not having it?
    A section that cannot name both is a CUT candidate. Run
    `python scripts/context_budget.py` to see the per-section table and
    the budget standing; the table feeds the owner-reviewed cut pass.

THE EXCEPTION PATH
    Over-cap states require an OWNER_APPROVED_EXCEPTIONS entry naming
    scope, an explicit byte bound, and the owner approval (issue+date).
    The list ships EMPTY: an over-cap budget without an entry fails the
    cap test (tests/test_context_budget_300.py, fast tier).

CLI
    python scripts/context_budget.py           # table + standing
    python scripts/context_budget.py --json    # machine-readable metric
    Exit 0 = within cap or a valid exception; exit 2 = over cap.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONSTITUTION_PATH = REPO_ROOT / "agents" / "kunglao-worker.md"
TEMPLATE_PATH = REPO_ROOT / "templates" / "CLAUDE.md.base.tmpl"

# ---- cap constants (owner audit, issue 300, 2026-09-20) -----------------
#
# T0 drift note: the audit cites constitution 22,856B; the v0.1 tag blob
# mechanically measures 22,192B (the audit figure is the pinned anchor —
# 664B of slack we do NOT spend). The template figure is the exact v0.1
# tag measurement. Changing either constant is an owner-visible edit.
BASELINE_CONSTITUTION_BYTES = 22_856
BASELINE_TEMPLATE_BYTES = 8_303
CAP_RATIO = 1.30
CAP_TOTAL_BYTES = int((BASELINE_CONSTITUTION_BYTES + BASELINE_TEMPLATE_BYTES) * CAP_RATIO)

# ---- WS1 high-water ratchet (the 520 coverage-floor ships-green pattern) -
#
# Measured at the WS1 slice (worktree base 1b0d076): the budget is OVER
# cap today (53,751B vs 40,506B cap). The cap test xfails with the
# standing until the owner-reviewed cut pass lands; THIS constant is the
# live teeth — any growth fails tests/test_context_budget_300.py.
# Raising it requires an owner citation here.
WS1_STANDING_TOTAL_BYTES = 53_751  # owner anchor: issue 300 WS1 audit

# ---- owner-approved exceptions (EMPTY by default) ------------------------
#
# Shape (all keys required, validated by the test tier):
#   {
#     "scope": "constitution+template-total",
#     "max_total_bytes": 54000,            # hard bound, > CAP_TOTAL_BYTES
#     "owner_ref": "issue 300 comment N, owner approval 2026-09-XX",
#   }
# An over-cap budget with no matching entry FAILS the cap test.
OWNER_APPROVED_EXCEPTIONS: list[dict] = []


def dispatch_scaffold_bytes() -> int:
    """Fixed bytes of the per-dispatch context inject WRAPPER.

    Informational component: the JSON body is per-claim payload, not
    standing text, so only the marker/fence scaffold counts here.
    Fail-open: a missing sibling module measures as 0 rather than
    breaking the metric.
    """
    try:
        import dispatch_context

        return len(dispatch_context.dispatch_inject({}).encode("utf-8"))
    except Exception:
        return 0


def measure() -> dict:
    """Compute the fixed context budget standing (pure file reads)."""
    constitution_bytes = CONSTITUTION_PATH.stat().st_size
    template_bytes = TEMPLATE_PATH.stat().st_size
    total = constitution_bytes + template_bytes
    return {
        "constitution_bytes": constitution_bytes,
        "template_bytes": template_bytes,
        "total_bytes": total,
        "cap_bytes": CAP_TOTAL_BYTES,
        "over_by_bytes": total - CAP_TOTAL_BYTES,
        "dispatch_scaffold_bytes": dispatch_scaffold_bytes(),
        "ratchet_bytes": WS1_STANDING_TOTAL_BYTES,
    }


def _valid_exception(total: int) -> dict | None:
    for entry in OWNER_APPROVED_EXCEPTIONS:
        if (
            entry.get("scope") == "constitution+template-total"
            and isinstance(entry.get("max_total_bytes"), int)
            and entry["max_total_bytes"] >= total
            and len(str(entry.get("owner_ref", ""))) >= 10
        ):
            return entry
    return None


def cap_status() -> tuple[str, str]:
    """'ok' | 'overcap-exception' | 'overcap-no-exception' + detail."""
    m = measure()
    total, cap = m["total_bytes"], m["cap_bytes"]
    detail = (
        f"total {total}B / cap {cap}B "
        f"(constitution {m['constitution_bytes']}B + template "
        f"{m['template_bytes']}B, over by {m['over_by_bytes']}B)"
    )
    if total <= cap:
        return "ok", detail
    if _valid_exception(total) is not None:
        return "overcap-exception", detail
    return "overcap-no-exception", detail


def section_table() -> list[tuple[str, str, int]]:
    """Per-## -section byte table for both standing files (audit feed)."""
    rows: list[tuple[str, str, int]] = []
    for source, path in (("constitution", CONSTITUTION_PATH), ("template", TEMPLATE_PATH)):
        lines = path.read_text(encoding="utf-8").split("\n")
        marks = [i for i, ln in enumerate(lines) if ln.startswith("## ")]
        for j, i in enumerate(marks):
            end = marks[j + 1] if j + 1 < len(marks) else len(lines)
            rows.append((source, lines[i][3:].strip(), len("\n".join(lines[i:end]).encode())))
    return rows


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    m = measure()
    status, detail = cap_status()
    if "--json" in argv:
        print(json.dumps({"status": status, **m}, indent=2))
    else:
        print(f"status: {status}")
        print(detail)
        print(f"dispatch inject scaffold (informational): {m['dispatch_scaffold_bytes']}B")
        print(f"WS1 ratchet (high-water): {m['ratchet_bytes']}B")
        print()
        print(f"{'source':<14} {'bytes':>7}  section")
        for source, name, size in section_table():
            print(f"{source:<14} {size:>7}  {name}")
    return 0 if status in ("ok", "overcap-exception") else 2


if __name__ == "__main__":
    raise SystemExit(main())
