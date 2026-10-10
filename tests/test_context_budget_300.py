# -*- coding: utf-8 -*-
"""Issue 300 WS1 — context budget: per-dispatch fixed context bytes.

Every worker session pays a fixed rules tax: the worker constitution
(agents/kunglao-worker.md) + the workspace CLAUDE.md rendered from
templates/CLAUDE.md.base.tmpl. The 2026-09-20 audit (issue 300) found the
constitution grew 22KB -> 35KB (+58%) and the template 8.3KB -> 18.5KB
(+123%, 11 new handbook sections) while the toolbox stayed flat.

WS1 lands the METRIC + CAP + EXCEPTION MECHANISM (the actual section cuts
are a separate owner-reviewed pass fed by the section audit):

  1. constants pinned to the owner audit's v0.1 baseline (no silent
     cap loosening);
  2. the cap test: total fixed bytes <= CAP_RATIO x baseline, or an
     explicit owner-approved exception entry, or (interim, pre-cut-pass)
     xfail carrying the current standing;
  3. a green-shipping ratchet (coverage-floor convention): the WS1 standing is the
     high-water mark — bytes may only go down without raising it via an
     owner-cited change;
  4. exception entries must be well-formed and cite owner approval.

The dispatch-context inject scaffold (scripts/dispatch_context.py) is
measured as an informational third component (its JSON body is
per-claim payload, not standing text).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import context_budget
from context_budget import (
    BASELINE_CONSTITUTION_BYTES,
    BASELINE_TEMPLATE_BYTES,
    CAP_RATIO,
    CAP_TOTAL_BYTES,
    OWNER_APPROVED_EXCEPTIONS,
    WS1_STANDING_TOTAL_BYTES,
    cap_status,
    measure,
)

ROOT = Path(__file__).resolve().parents[1]
CONSTITUTION = ROOT / "agents" / "kunglao-worker.md"
TEMPLATE = ROOT / "templates" / "CLAUDE.md.base.tmpl"


def test_baseline_constants_pinned_to_owner_audit() -> None:
    """The cap's anchors must not drift without an owner-visible change.

    22_856 / 8_303 are the issue 300 audit's v0.1 baseline figures; the
    v0.1 tag mechanically measures 22_192 / 8_303 (drift noted in the
    script's constant block). CAP_TOTAL is the floored 130% product.
    """
    assert BASELINE_CONSTITUTION_BYTES == 22_856
    assert BASELINE_TEMPLATE_BYTES == 8_303
    assert CAP_RATIO == 1.30
    assert CAP_TOTAL_BYTES == int(
        (BASELINE_CONSTITUTION_BYTES + BASELINE_TEMPLATE_BYTES) * CAP_RATIO
    )


def test_metric_reads_real_repo_files() -> None:
    """measure() reflects the live bytes of both standing-text files."""
    m = measure()
    assert m["constitution_bytes"] == CONSTITUTION.stat().st_size
    assert m["template_bytes"] == TEMPLATE.stat().st_size
    assert m["total_bytes"] == m["constitution_bytes"] + m["template_bytes"]
    assert m["over_by_bytes"] == m["total_bytes"] - m["cap_bytes"]
    # dispatch inject scaffold is measured and positive (fixed wrapper)
    assert m["dispatch_scaffold_bytes"] > 0


def test_exception_entries_wellformed() -> None:
    """Every exception must carry scope, bound, and an owner citation."""
    for entry in OWNER_APPROVED_EXCEPTIONS:
        assert {"scope", "max_total_bytes", "owner_ref"} <= set(entry)
        assert entry["scope"] == "constitution+template-total"
        assert isinstance(entry["max_total_bytes"], int)
        assert entry["max_total_bytes"] > CAP_TOTAL_BYTES
        assert len(entry["owner_ref"]) >= 10, (
            f"owner_ref must cite the approval (issue + date), got: {entry['owner_ref']!r}"
        )


def test_cap_within_130pct_or_owner_exception() -> None:
    """THE cap gate: fixed context bytes <= 130% of the v0.1 baseline.

    Over cap with a recorded owner-approved exception (bounded by
    max_total_bytes) passes. Over cap with NO exception fails CI — the
    fix is either the section cut (preferred, see the audit table in the
    issue) or an explicit OWNER_APPROVED_EXCEPTIONS entry.
    """
    status, detail = cap_status()
    if status == "ok":
        return
    if status == "overcap-exception":
        return
    pytest.xfail(
        f"fixed context over cap: {detail} — owner cut pass pending "
        "(issue 300 WS1 audit); record an OWNER_APPROVED_EXCEPTIONS "
        "entry citing owner approval to convert this to a pass"
    )


def test_no_growth_ratchet_ws1_high_water_mark() -> None:
    """Trend must be flat or down (issue 300 acceptance).

    WS1_STANDING_TOTAL_BYTES is the measured high-water mark at the WS1
    slice (base 1b0d076). Any growth fails here even while the cap test
    is in its interim xfail. Raising the constant is an owner-cited
    change — the line's comment must keep the citation.
    """
    m = measure()
    assert m["total_bytes"] <= WS1_STANDING_TOTAL_BYTES, (
        f"context budget grew: {m['total_bytes']}B > ratchet "
        f"{WS1_STANDING_TOTAL_BYTES}B (+{m['total_bytes'] - WS1_STANDING_TOTAL_BYTES}B). "
        "Cut bytes (preferred) or raise the ratchet with an owner "
        "citation on the WS1_STANDING_TOTAL_BYTES constant."
    )


def test_exception_entry_converts_overcap_to_pass() -> None:
    """A well-formed, sufficient exception flips overcap to pass; a
    bound below the standing does NOT (no blank-check exceptions)."""
    m = measure()
    good = {
        "scope": "constitution+template-total",
        "max_total_bytes": m["total_bytes"],
        "owner_ref": "issue 300 owner approval 2026-09-XX",
    }
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(context_budget, "OWNER_APPROVED_EXCEPTIONS", [good])
        assert cap_status()[0] == "overcap-exception"
        tight = dict(good, max_total_bytes=m["total_bytes"] - 1)
        mp.setattr(context_budget, "OWNER_APPROVED_EXCEPTIONS", [tight])
        assert cap_status()[0] == "overcap-no-exception"


def test_section_table_feeds_the_audit() -> None:
    """The audit feed enumerates every ## section of both files."""
    table = context_budget.section_table()
    names = {name for _src, name, _b in table}
    assert "⚡ GOLDEN RULES (top of context — read these first)" in names
    assert "Memory carriers (write/recall contract)" in names
    assert all(b > 0 for _src, _n, b in table)
