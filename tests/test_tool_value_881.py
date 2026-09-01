# -*- coding: utf-8 -*-
"""tests/test_tool_value_881.py — #881 工具价值聚合器与消费接线契约测试。

验收三条（issue #881）：
  A1 同一 workspace 可答"哪些工具在该 (scene,operation) 下 utility 最高"（--report）
  A2 档位链排序随运行时计数变化（chain_for/inject_block 消费面）
  A3 零使用工具沉底可见（retirement-candidate 标记，对接 #866-b）
纪律：聚合器与两处接线（tool_tiers / recall_files）同 PR。

计数口径（Recon 声明）：cite=选中∧存活；burn=选中∧负样本；reject=弃用（不入后验）；
utility=(cite+α0)/(cite+burn+α0+β0)，k=4，p0=静态链 rank 先验，链外 0.5。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# pytest.ini pythonpath = . hooks scripts tools ... — no sys.path mutation
# here (tests/test_syspath_hygiene_671.py pins the no-top-level-insert rule).
import tool_tiers as tt  # noqa: E402
import tool_value as tv  # noqa: E402
from recall_inject import recall_files  # noqa: E402

K = tv.PRIOR_STRENGTH

# p0 priors for the android-dex-static chain [full, targeted, structured, text]
P0 = {"full": 0.8, "targeted": 0.6, "structured": 0.4, "text": 0.2}


# ---------------- fixtures ----------------

def _mk_ws(tmp_path: Path) -> Path:
    """Workspace carrying all four input faces (#880 shapes).

    C-1: operation label (input D) + toolfirst_pass row (input A) + facts steps
         selection (input B) + positive outcome (input C)  -> jadx cite=1
    C-2: unlabeled, facts steps select strings, red-team REFUTED -> strings burn=1
    C-3: operation decode, facts steps record a structured rejection of baksmali
         -> baksmali reject=1 (reject never enters the posterior)
    crypto-tool: registered in tools/_INDEX.yaml, never used -> zero-use row.
    """
    ws = tmp_path / "ws"
    (ws / "runs" / "logs").mkdir(parents=True)
    (ws / "facts").mkdir()
    (ws / "task_spec.yaml").write_text(
        "platform: android apk dex\nproject_type: reverse\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        "claims:\n"
        "- id: C-1\n  status: PROVEN\n  operation: decode\n"
        "  operation_tool: jadx\n"
        "- id: C-2\n  status: REFUTED\n"
        "- id: C-3\n  status: OPEN\n  operation: decode\n"
        "  operation_tool: none\n",
        encoding="utf-8")

    def _row(action, claim=None, detail=None):
        return json.dumps({"ts": "2026-09-02T00:00:00Z", "actor": "t",
                           "action": action, "claim": claim, "detail": detail},
                          ensure_ascii=False)

    ledger = ws / "runs" / "logs" / "kunglao-2026-09-02.jsonl"
    ledger.write_text("\n".join([
        _row("toolfirst_pass", "C-1", json.dumps(
            {"mode": "matched", "keywords": ["decode"], "tool": "jadx"})),
        _row("toolfirst_pass", "C-2", json.dumps(
            {"mode": "no_match", "keywords": [], "tool": None})),
        _row("claim_settled", "C-1", json.dumps(
            {"from": "OPEN", "to": "PROVEN", "tools": ["jadx"],
             "outcome": "PROVEN"})),
        _row("claim_settled", "C-2", json.dumps(
            {"from": "OPEN", "to": "REFUTED", "tools": ["strings"],
             "outcome": "REFUTED"})),
    ]) + "\n", encoding="utf-8")

    (ws / "facts" / "F001-decode.md").write_text(
        "---\nclaim_id: C-1\n---\n\n## method\n"
        "steps:\n"
        "- jadx decompile classes.dex -> expected: java sources\n",
        encoding="utf-8")
    (ws / "facts" / "F002-strings.md").write_text(
        "---\nclaim_id: C-2\n---\n\n"
        "steps:\n"
        "- strings on payload.bin -> expected: url strings\n",
        encoding="utf-8")
    (ws / "facts" / "F003-baksmali.md").write_text(
        "---\nclaim_id: C-3\n---\n\n"
        "steps:\n"
        "- candidate baksmali skipped: not used (device unreachable, fallback "
        "static)\n",
        encoding="utf-8")

    (ws / "runs" / "20260902-verify-C-1.md").write_text(
        "---\nclaim_id: C-1\nverify_status: passes\n---\n\n"
        "## Overall verdict\npasses\n", encoding="utf-8")
    (ws / "runs" / "verify-redteam-C-2.md").write_text(
        "target: C-2\n\n## RED-TEAM VERDICT: REFUTED\n", encoding="utf-8")
    return ws


# ---------------- 1. aggregator: three-input join -> counts + utility ----

def test_scene_sniffed_from_task_spec(tmp_path):
    ws = _mk_ws(tmp_path)
    agg = tv.aggregate(ws)
    assert agg["scene"] == "android-dex-static"


def test_join_counts_cite_burn_reject(tmp_path):
    ws = _mk_ws(tmp_path)
    agg = tv.aggregate(ws)

    def row(tool, operation):
        return next(r for r in agg["rows"] if r["tool"] == tool
                    and r["operation"] == operation)

    jadx = row("jadx", "decode")
    assert jadx["cite"] == 1 and jadx["burn"] == 0 and jadx["reject"] == 0
    strings = row("strings", tv.UNLABELED)
    assert strings["cite"] == 0 and strings["burn"] == 1
    bak = row("baksmali", "decode")
    assert bak["reject"] == 1 and bak["cite"] == 0 and bak["burn"] == 0


def test_utility_is_beta_bernoulli_with_tier_prior(tmp_path):
    ws = _mk_ws(tmp_path)
    agg = tv.aggregate(ws)

    def row(tool):
        return next(r for r in agg["rows"] if r["tool"] == tool)

    # jadx: full tier p0=0.8 -> (1 + 4*0.8) / (1 + 0 + 4)
    assert row("jadx")["tier"] == "full"
    assert row("jadx")["utility"] == pytest.approx((1 + K * P0["full"]) / (1 + K))
    # strings: text tier p0=0.2, burn only -> (0 + 4*0.2) / (1 + 4)
    assert row("strings")["tier"] == "text"
    assert row("strings")["utility"] == pytest.approx((0 + K * P0["text"]) / (1 + K))
    # crypto-tool: registered but unlisted in the scene chain -> neutral 0.5
    zc = [r for r in agg["rows"] if r["tool"] == "crypto-tool"][0]
    assert zc["utility"] == pytest.approx(0.5)
    # baksmali: reject never enters the posterior -> pure static prior
    # (structured tier p0=0.4 — reject-only data leaves the prior untouched)
    assert row("baksmali")["utility"] == pytest.approx(P0["structured"])


def test_unsettled_claims_count_nothing(tmp_path):
    ws = _mk_ws(tmp_path)
    # C-3 is OPEN: its frida rejection is counted, but a selection without a
    # settlement must produce neither cite nor burn.
    (ws / "facts" / "F003-baksmali.md").write_text(
        "---\nclaim_id: C-3\n---\n\nsteps:\n- jadx re-decompile prefix\n",
        encoding="utf-8")
    agg = tv.aggregate(ws)
    row = next(r for r in agg["rows"] if r["tool"] == "jadx"
               and r["operation"] == "decode")
    assert row["cite"] == 1 and row["burn"] == 0  # C-1 only; C-3 unsettled


def test_table_roundtrip_and_corrupt_tolerance(tmp_path):
    ws = _mk_ws(tmp_path)
    assert tv.load_table(ws) is None  # nothing written yet
    tv.write_table(ws)
    table = tv.load_table(ws)
    assert table and table["schema"] == tv.SCHEMA
    assert any(r["tool"] == "jadx" for r in table["rows"])
    (ws / "runs" / ".tool-value.json").write_text("{broken", encoding="utf-8")
    assert tv.load_table(ws) is None  # corrupt -> None (fail-open consumers)


# ---------------- 2. wiring 1: chain_for / inject_block ------------------

def test_chain_static_without_workspace_or_table(tmp_path):
    ws = _mk_ws(tmp_path)  # no table written
    assert tt.chain_for("android-dex-static") == \
        ["full", "targeted", "structured", "text"]
    assert tt.chain_for("android-dex-static", ws=ws) == \
        ["full", "targeted", "structured", "text"]
    assert tt.chain_for("android-dex-static", ws=ws / "nope") == \
        ["full", "targeted", "structured", "text"]


def test_chain_reorders_with_runtime_counts(tmp_path):
    ws = _mk_ws(tmp_path)
    tv.write_table(ws)
    # boost the text tier (strings) far above the static full-tier prior
    table = tv.load_table(ws)
    for r in table["rows"]:
        if r["tool"] == "strings":
            r["cite"] = 30
            r["utility"] = tv.beta_utility(30, 0, P0["text"])
    tv.write_table(ws, table=table)
    chain = tt.chain_for("android-dex-static", ws=ws)
    assert chain[0] == "text", chain  # counts moved text above full
    assert set(chain) == {"full", "targeted", "structured", "text"}


def test_inject_block_byte_identical_without_table(tmp_path):
    ws = _mk_ws(tmp_path)
    assert tt.inject_block("android-dex-static", ws=ws) == \
        tt.inject_block("android-dex-static")


def test_inject_block_reorders_chain_and_tools_with_counts(tmp_path):
    ws = _mk_ws(tmp_path)
    table = tv.load_table(ws) or tv.aggregate(ws)
    # boost strings (text tier) far above the static full-tier prior; give
    # grep (same tier) fewer cites so the within-tier order flips too
    for r in table["rows"]:
        if r["tool"] == "strings":
            r["cite"] = 30
        if r["tool"] == "grep":
            r["cite"] = 1
    tv.write_table(ws, table=table)
    block = tt.inject_block("android-dex-static", ws=ws)
    assert "downgrade chain: text -> full -> targeted -> structured" in block
    # within-tier reorder: strings (20 cites) outranks grep (1 cite) in text
    ti = block.index("text:")
    assert block.index("strings", ti) < block.index("grep on baksmali", ti)


def test_dispatch_context_still_carries_block(tmp_path):
    ws = _mk_ws(tmp_path)
    import dispatch_context as dc
    ctx = dc.build_dispatch_context(
        ws=ws, claim_id="C-1", tier=2, tools=["strings"], agent_name="x")
    assert "tool_tiers" in ctx
    dc.validate_context_shape(ctx)


# ---------------- 3. wiring 2: recall_files utility rerank ---------------

def _runner(stdout: str):
    def run(query):
        return 0, stdout
    return run


def test_recall_rerank_puts_high_utility_first(tmp_path):
    ws = _mk_ws(tmp_path)
    tv.write_table(ws)
    table = tv.load_table(ws)
    for r in table["rows"]:
        if r["tool"] == "jadx":
            r["cite"] = 10
    tv.write_table(ws, table=table)
    out = recall_files("q", cwd=ws, recall_runner=_runner(
        "baksmali-notes.md | tools | low\njadx-notes.md | tools | high\n"))
    assert out[0].endswith("jadx-notes.md")
    assert out[1].endswith("baksmali-notes.md")


def test_recall_order_untouched_without_table_or_workspace(tmp_path):
    ws = _mk_ws(tmp_path)
    rows = ("baksmali-notes.md", "jadx-notes.md")
    raw = "\n".join(n + " | tools | x" for n in rows)
    assert recall_files("q", recall_runner=_runner(raw)) == rows
    assert recall_files("q", cwd=ws, recall_runner=_runner(raw)) == rows


def test_recall_rerank_failopen_on_corrupt_table(tmp_path):
    ws = _mk_ws(tmp_path)
    (ws / "runs" / ".tool-value.json").write_text("{broken", encoding="utf-8")
    rows = ("baksmali-notes.md", "jadx-notes.md")
    raw = "\n".join(n + " | tools | x" for n in rows)
    assert recall_files("q", cwd=ws, recall_runner=_runner(raw)) == rows


# ---------------- 4. acceptance: report answers + zero-use sinks --------

def test_report_answers_top_utility_per_operation(tmp_path, capsys):
    ws = _mk_ws(tmp_path)
    rc = tv.main([str(ws), "--report"])
    out = capsys.readouterr().out
    assert rc == 0
    # the decode bucket answers: jadx (cite=1, full-tier prior) tops frida
    assert "jadx" in out and "baksmali" in out
    di = out.index("decode")
    assert out.index("jadx", di) < out.index("baksmali", di)


def test_report_operation_filter(tmp_path, capsys):
    ws = _mk_ws(tmp_path)
    tv.main([str(ws), "--report", "--operation", "decode"])
    out = capsys.readouterr().out
    assert "strings" not in out  # strings lives in the (unlabeled) bucket
    assert "jadx" in out


def test_zero_use_tools_sink_visible(tmp_path):
    ws = _mk_ws(tmp_path)
    ranked = tv.report_rows(tv.aggregate(ws))
    names = [r["tool"] for r in ranked]
    # evidence tools first; zero-use registered tool after every cited one
    assert names.index("crypto-tool") > names.index("strings")
    zc = next(r for r in ranked if r["tool"] == "crypto-tool")
    assert zc["zero_use"] is True
    assert zc["cite"] == zc["burn"] == zc["reject"] == 0


def test_cli_json_writes_table(tmp_path, capsys):
    ws = _mk_ws(tmp_path)
    rc = tv.main([str(ws), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scene"] == "android-dex-static"
    assert tv.load_table(ws) is not None  # default face writes the table
