# -*- coding: utf-8 -*-
"""tests/test_tool_value_measured_818.py — the #881 tool-value join in
the MEASURED leg (issue #818 coverage climb).

The unit pins live in tests/test_tool_value_881.py (fast tier — not
executed by the CI measured-set coverage leg). This file re-pins the
counting contract on a REAL workspace: the four input faces joined on
claim id, cite/burn/reject accounting (reject never enters the
posterior), the beta utility with the tier prior, zero-use sink rows,
pooled utilities recomputed from pooled counts, and the tolerant table
I/O.
"""
from __future__ import annotations

import json
from pathlib import Path

import tool_value as tv  # noqa: E402  (scripts/ on pytest path)


# ---------- pure functions ----------

def test_normalize_tool_takes_the_cli_head() -> None:
    assert tv.normalize_tool("jadx --classes-to-decompile x") == "jadx"
    assert tv.normalize_tool("R2,") == "r2"
    assert tv.normalize_tool("") == ""
    assert tv.normalize_tool(None) == ""


def test_beta_utility_prior_and_counts() -> None:
    assert tv.beta_utility(0, 0, 0.5) == 0.5          # pure prior
    assert tv.beta_utility(0, 0, 0.5, k=4.0) == 0.5
    # (cite + a0) / (cite + burn + a0 + b0), k=4, p0=0.5 -> a0=b0=2
    assert tv.beta_utility(2, 0, 0.5) == (2 + 2) / (2 + 4)
    assert tv.beta_utility(0, 6, 0.5) == 2 / 10
    # negative counts clamp to zero
    assert tv.beta_utility(-3, -9, 0.5) == 0.5


def test_line_tool_hits_token_rules() -> None:
    names = ("jadx", "strings", "jadx-decompile", "crypto_tool", "r2")
    hits = tv.line_tool_hits("restructuring strings and plain jadx decompile",
                             names)
    assert "strings" in hits          # exact token
    assert "jadx" in hits
    assert "jadx-decompile" not in hits   # word adjacency must NOT hit
    assert "r2" not in hits           # sub-3-char names never match
    hits2 = tv.line_tool_hits("run jadx-decompile, then crypto_tool next",
                              names)
    assert "jadx-decompile" in hits2
    assert "crypto_tool" in hits2
    assert tv.line_tool_hits("", names) == set()


# ---------- aggregate on a real workspace ----------

def _decline_tools() -> tuple[str, str]:
    """Two tools from the LIVE tier universe (the join only counts
    registered tools), one hyphenated one not."""
    priors = tv._tier_priors("generic-binary")
    universe = tv._tool_universe(priors)
    hyphen = next(t for t in universe if ("-" in t or "_" in t)
                  and len(t) >= 3)
    plain = next(t for t in universe if "-" not in t and "_" not in t
                 and len(t) >= 3 and t != hyphen)
    return hyphen, plain


def _seed_join_ws(tmp_path: Path) -> Path:
    """One claim per outcome, driving every bump branch of the join:
    C-1 positive (cite), C-2 negative (burn), C-3 rejected-only."""
    hyphen, plain = _decline_tools()
    ws = tmp_path / "ws"
    (ws / "runs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "  - id: C-1\n    status: PROVEN\n    operation: unpack\n"
        "    operation_tool: jadx\n"
        "  - id: C-2\n    status: OPEN\n    operation: unpack\n"
        "  - id: C-3\n    status: OPEN\n    operation: unpack\n",
        encoding="utf-8")
    # facts steps (keyed by frontmatter claim_id): C-1 selected jadx;
    # C-3's step lines carry DECLINE_MARKERS -> structured rejection
    (ws / "facts" / "F001.md").write_text(
        f"---\nid: F001-fact\ntype: fact\nclaim_id: C-1\n---\n"
        f"steps:\n  - tool: {hyphen}\n    did: the work\n",
        encoding="utf-8")
    (ws / "facts" / "F003.md").write_text(
        f"---\nid: F003-fact\ntype: fact\nclaim_id: C-3\n---\n"
        f"steps:\n  - {hyphen} skipped, wrong lane\n"
        f"  - {plain} not used here either\n",
        encoding="utf-8")
    # settlement rows: C-1 positive, C-2 negative
    from kunglao_log import emit
    emit(ws, actor="t", action="claim_settled", claim="C-1",
         detail=json.dumps({"to": "PROVEN"}))
    emit(ws, actor="t", action="claim_settled", claim="C-2",
         detail=json.dumps({"to": "NEGATIVE"}))
    return ws


def test_aggregate_joins_the_four_faces(tmp_path) -> None:
    hyphen, plain = _decline_tools()
    ws = _seed_join_ws(tmp_path)
    table = tv.aggregate(ws)
    assert table["schema"] == tv.SCHEMA
    rows = {(r["operation"], r["tool"]): r for r in table["rows"]
            if not r["zero_use"]}
    # C-1 selects `hyphen` (attr + facts) -> cite; C-3 declines the same
    # tool -> reject lands in the SAME (operation, tool) cell
    cell = rows[("unpack", hyphen)]
    assert cell["cite"] == 1 and cell["reject"] == 1 and cell["burn"] == 0
    # C-2 never selected any tool, so its negative outcome bumps nothing
    # C-3: the second declined tool is a pure-reject row
    assert rows[("unpack", plain)]["reject"] == 1
    assert rows[("unpack", plain)]["cite"] == 0
    assert rows[("unpack", plain)]["burn"] == 0
    # utilities ride the beta math with the row prior
    r = cell
    assert r["utility"] == tv.beta_utility(r["cite"], r["burn"],
                                           r["prior"])
    # zero-use universe tools sink with explicit all-zero rows
    zero = [r for r in table["rows"] if r["zero_use"]]
    assert zero and all(r["cite"] == 0 and r["burn"] == 0
                        and r["reject"] == 0 for r in zero)


def test_write_and_load_table_roundtrip(tmp_path) -> None:
    ws = _seed_join_ws(tmp_path)
    path = tv.write_table(ws)
    assert path == tv.table_path(ws) and path.is_file()
    table = tv.load_table(ws)
    assert table is not None and table["schema"] == tv.SCHEMA
    # corrupt / wrong-shape / missing tables read as None (fail-open)
    path.write_text("{corrupt", encoding="utf-8")
    assert tv.load_table(ws) is None
    path.write_text(json.dumps({"schema": "other/9", "rows": []}),
                    encoding="utf-8")
    assert tv.load_table(ws) is None
    path.write_text(json.dumps({"schema": tv.SCHEMA, "rows": "nope"}),
                    encoding="utf-8")
    assert tv.load_table(ws) is None
    assert tv.load_table(tmp_path / "void-ws") is None


def test_pooled_utilities_recompute_from_pooled_counts(tmp_path) -> None:
    table = {"rows": [
        {"tool": "jadx", "cite": 1, "burn": 0, "prior": 0.5},
        {"tool": "jadx", "cite": 1, "burn": 1, "prior": 0.5},
        {"tool": "r2", "cite": 0, "burn": 0, "prior": 0.7},
    ]}
    pooled = tv.pooled_utilities(table)
    # cite/burn SUM; the utility is recomputed, never averaged
    assert pooled["jadx"]["cite"] == 2 and pooled["jadx"]["burn"] == 1
    assert pooled["jadx"]["utility"] == tv.beta_utility(2, 1, 0.5)
    assert pooled["r2"]["utility"] == tv.beta_utility(0, 0, 0.7)


def test_report_rows_rank_and_sink_zero_use(tmp_path) -> None:
    ws = _seed_join_ws(tmp_path)
    table = tv.aggregate(ws)
    rows = tv.report_rows(table)
    utils = [r["utility"] for r in rows if not r.get("zero_use")]
    assert utils == sorted(utils, reverse=True)
    zero_positions = [i for i, r in enumerate(rows) if r.get("zero_use")]
    if zero_positions:
        assert zero_positions == list(
            range(len(rows) - len(zero_positions), len(rows)))
