# -*- coding: utf-8 -*-
"""Injection admission pins for hooks/recall_inject.py (issue 771).

Owner directives on record: recall must be NEED-DRIVEN (queries derived from
the dispatch's question keywords — no WEB_QUERIES / GO_SIGNALS category
default expansion, no tier fallback), SECTION-LOCATED (every injected item
carries `path:L<start>~L<end>` computed FRESH at query time by anchoring on
headings — never a stale stored offset), BUDGET-CAPPED (<= 3 files, <= 5
items, <= 1200 chars per injection) and DEFAULT-OFF (KUNGLAO_RECALL=1 opt-in;
unset stays silent; the demand gate — a question with extractable keywords —
opens the injection face).
"""
import re
from pathlib import Path

import pytest

import recall_inject
from recall_inject import evaluate, queries_for_question

# ---- helpers (mirror test_recall_inject fixtures) ----


def _kunglao_ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "claim-register.yaml").write_text(
        "claims:\n- id: C-001\n  status: OPEN\n", encoding="utf-8")
    return ws


def _payload(ws: Path, prompt: str) -> dict:
    return {
        "hookEventName": "PreToolUse",
        "tool_name": "Agent",
        "cwd": str(ws),
        "tool_input": {"prompt": prompt},
    }


def _v1(claim: str, tier: int, question: str) -> str:
    return ('{"kunglao_dispatch": {"version": 1, "claim": "%s", "tier": %d, '
            '"tools": ["ghidra"]}}\n%s' % (claim, tier, question))


VM_CLAIM = _v1("C-101", 3, "observe the sample dynamic behavior in the VM "
               "with x64dbg breakpoints and frida injection")


# ---- default OFF (issue 771: the default face honors the H2H receipt) ----


def test_default_off_without_opt_in(tmp_path):
    """KUNGLAO_RECALL unset -> ZERO injection on a claim dispatch (rc 0,
    silent). The default face is OFF until the scorer earns its cost back."""
    ws = _kunglao_ws(tmp_path)
    rc, stderr, ctx = evaluate(_payload(ws, VM_CLAIM),
                               recall_runner=lambda q: (
                                   0, "re-library/a.md | a | b | c"))
    assert rc == 0 and stderr == "" and ctx is None


def test_opt_in_env_arms_recall(tmp_path, monkeypatch):
    """Only the exact "1" arms the face."""
    monkeypatch.setenv(recall_inject.RECALL_DISABLE_ENV, "1")
    ws = _kunglao_ws(tmp_path)
    rc, stderr, ctx = evaluate(_payload(ws, VM_CLAIM),
                               recall_runner=lambda q: (
                                   0, "re-library/a.md | a | b | c"))
    assert rc == 0 and stderr == "" and ctx is not None


def test_legacy_off_value_stays_off(tmp_path, monkeypatch):
    """Under default-off semantics "0" is off too (it is simply not "1")."""
    monkeypatch.setenv(recall_inject.RECALL_DISABLE_ENV, "0")
    ws = _kunglao_ws(tmp_path)
    rc, _, ctx = evaluate(_payload(ws, VM_CLAIM),
                          recall_runner=lambda q: (
                              0, "re-library/a.md | a | b | c"))
    assert rc == 0 and ctx is None


# ---- demand gate: queries derive from the question, nothing else ----


def test_demand_gate_closed_on_keywordless_question(tmp_path, monkeypatch):
    """A question with no extractable keywords closes the demand gate even
    at tier 3 — no "vm"/"dynamic"/"static analysis" category fallback."""
    monkeypatch.setenv(recall_inject.RECALL_DISABLE_ENV, "1")
    ws = _kunglao_ws(tmp_path)
    claim = _v1("C-110", 3, "of the to and")
    rc, _, ctx = evaluate(_payload(ws, claim),
                          recall_runner=lambda q: (
                              0, "re-library/a.md | a | b | c"))
    assert rc == 0 and ctx is None


def test_queries_derived_from_question_keywords_only():
    """The query IS the distilled question: keywords joined, stopwords and
    the v1 envelope stripped, one query — never a category table."""
    q = queries_for_question(VM_CLAIM)
    assert len(q) == 1
    for token in ("dynamic", "behavior", "frida", "injection"):
        assert token in q[0]
    assert "kunglao_dispatch" not in q[0], "envelope must not leak into query"
    assert "ghidra" not in q[0], "tool list is not question content"


def test_no_category_default_expansion():
    """Retired category faces: a go-signal or web-domain question gets the
    tokens it actually contains — and NOTHING for categories it doesn't."""
    go = queries_for_question(_v1("C-102", 2, "recover the symbol table of "
                               "the go binary runtime structures"))
    assert len(go) == 1 and "symbol" in go[0]
    assert not any(q == "go" for q in go), "bare category query retired"
    assert not any("static analysis" in q for q in go)
    plain_t3 = queries_for_question(_v1("C-103", 3, "strings and metadata "
                                    "scan of the sample"))
    assert plain_t3 == ["strings metadata scan sample"], (
        "tier 3 without matching keywords adds nothing")


# ---- section-level locations: fresh `path:L<start>~L<end>` anchors ----


@pytest.fixture
def refs_lib(tmp_path, monkeypatch):
    """A two-section fixture reference library wired in as REFERENCES_DIR."""
    refs = tmp_path / "refs"
    (refs / "re-library").mkdir(parents=True)
    (refs / "re-library" / "probe.md").write_text(
        "# Alpha\n\nunrelated filler about catalogs\nline four filler\n"
        "# Beta frida injection\n\ndynamic breakpoints content here\n",
        encoding="utf-8")
    monkeypatch.setattr(recall_inject, "REFERENCES_DIR", refs, raising=False)
    return refs


def test_every_injected_item_carries_fresh_line_range(
        tmp_path, monkeypatch, refs_lib):
    monkeypatch.setenv(recall_inject.RECALL_DISABLE_ENV, "1")
    ws = _kunglao_ws(tmp_path)
    rc, _, ctx = evaluate(_payload(ws, VM_CLAIM),
                          recall_runner=lambda q: (
                              0, "re-library/probe.md | a | b | c"))
    assert rc == 0 and ctx
    items = re.findall(r"\S+\.md:L\d+~L\d+", ctx)
    assert items, f"each item must carry path:L<start>~L<end>; ctx={ctx!r}"
    assert "re-library/probe.md:L5~L7" in items, (
        "the section matching the question (frida/dynamic/breakpoints) wins, "
        f"got {items}")
    assert "Before dispatching, read:" in ctx


def test_line_range_computed_fresh_not_stale(tmp_path, monkeypatch, refs_lib):
    """Rewriting the file shifts the anchored range on the next dispatch —
    anchors are computed at query time, never stored."""
    monkeypatch.setenv(recall_inject.RECALL_DISABLE_ENV, "1")
    runner = lambda q: (0, "re-library/probe.md | a | b | c")
    _, _, ctx1 = evaluate(_payload(_kunglao_ws(tmp_path), VM_CLAIM),
                          recall_runner=runner)
    probe = refs_lib / "re-library" / "probe.md"
    probe.write_text("# Preamble\n\nten\nlines\nof\npadding\nhere\n"
                     "# Beta frida injection\n\ndynamic content\n",
                     encoding="utf-8")
    # fresh workspace: the per-worker dedup would silence a repeat inject
    _, _, ctx2 = evaluate(_payload(_kunglao_ws(tmp_path / "ws2"), VM_CLAIM),
                          recall_runner=runner)
    first = re.findall(r"probe\.md:L\d+~L\d+", ctx1)[0]
    second = re.findall(r"probe\.md:L\d+~L\d+", ctx2)[0]
    assert first == "probe.md:L5~L7" and second == "probe.md:L8~L10", (
        f"anchor must move with the file: {first} -> {second}")


# ---- injection budget: <=3 files, <=5 items, <=1200 chars ----


def test_budget_files_items_and_chars(tmp_path, monkeypatch, refs_lib):
    monkeypatch.setenv(recall_inject.RECALL_DISABLE_ENV, "1")
    for i in range(8):
        (refs_lib / "re-library" / f"many{i}.md").write_text(
            "# Section\n\ndynamic content filler\n", encoding="utf-8")
    ws = _kunglao_ws(tmp_path)
    rows = "\n".join(f"re-library/many{i}.md | x | y | z" for i in range(8))
    rc, _, ctx = evaluate(_payload(ws, VM_CLAIM),
                          recall_runner=lambda q: (0, "# recall\n" + rows))
    assert rc == 0 and ctx
    items = re.findall(r"\S+\.md:L\d+~L\d+", ctx)
    distinct_files = {i.rsplit(":L", 1)[0] for i in items}
    assert len(distinct_files) <= 3, f"<=3 files, got {distinct_files}"
    assert len(items) <= 5, f"<=5 items, got {items}"
    recall_block = ctx.split("</kunglao-facts>")[0]
    assert len(recall_block) <= 1200, (
        f"recall block must stay <=1200 chars, got {len(recall_block)}")


# ---- redteam rides the same demand gate ----


def test_redteam_demand_gate_needs_keywords(tmp_path, monkeypatch):
    """Redteam prompts derive queries from their own text: keywordless ->
    closed; keyword-bearing -> open (no "failure analysis" default)."""
    monkeypatch.setenv(recall_inject.RECALL_DISABLE_ENV, "1")
    ws = _kunglao_ws(tmp_path)
    bare = "verify-redteam of the and"
    assert queries_for_question(bare) == []
    rc, _, ctx = evaluate(_payload(ws, bare), recall_runner=lambda q: (
        0, "re-library/a.md | a | b | c"))
    assert rc == 0 and ctx is None, "no keywords -> no injection"
    rich = "verify-redteam plan attacks against the license algorithm claim"
    assert queries_for_question(rich), "question tokens open the gate"
