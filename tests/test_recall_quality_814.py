# -*- coding: utf-8 -*-
"""tests/test_recall_quality_814.py — #814 recall 去污染 + 注入链留痕 + 度量面。

A. 打分去污染：purpose/when-only 单字段碰撞阻尼（泛文档不再挤进 top-K）
B. demotion 闭环：.recall-stats.json 的 demotion_suggestions 变成打分乘子
C. 注入链留痕 + 度量面：recall_skip/recall_injected 落账 + runs/.recall-metrics.jsonl
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import references_recall as rr  # noqa: E402
import recall_metrics as rm  # noqa: E402

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "recall_inject_814", ROOT / "hooks" / "recall_inject.py")
recall_inject = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(recall_inject)


def _e(path, purpose, when="", domain="", category="", symptoms=()):
    return rr.Entry(path=path, category=category or "methodology",
                    purpose=purpose, when=when, domain=domain,
                    symptoms=tuple(symptoms))


def _rows(ws: Path) -> list[dict]:
    ledgers = sorted((ws / "runs" / "logs").glob("kunglao-*.jsonl"))
    out = []
    for p in ledgers:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
    return out


# ---------- A. 单字段碰撞阻尼 ----------

def test_single_field_collision_damped():
    generic = _e("re-library/tools.md",
                 purpose="static analysis with gdb radare2 ghidra tools",
                 when="choosing static tools")
    android = _e("re-library/android-fingerprint-apis.md",
                 purpose="android fingerprint apis",
                 domain="android-dex-static")
    q = "android dex static"
    s_generic = rr._score_entry(generic, set(rr._tokenize(q)), rr._norm(q))
    s_android = rr._score_entry(android, set(rr._tokenize(q)), rr._norm(q))
    assert s_generic[0] < s_android[0], (s_generic, s_android)
    assert "single-field-collision" in "".join(s_generic[1])
    assert "single-field-collision" not in "".join(s_android[1])


def test_strong_field_hits_not_damped():
    e = _e("android-fingerprint-apis.md", purpose="fingerprint apis",
           domain="android-dex-static")
    score, reasons = rr._score_entry(e, set(rr._tokenize("android")),
                                     rr._norm("android"))
    assert score > 0
    assert "single-field-collision" not in "".join(reasons)


def test_pollution_regression_live_run_sample():
    entries = [
        _e("re-library/tools.md", purpose="static analysis gdb ghidra"),
        _e("re-library/six-phase-methodology.md",
           purpose="static six-phase malware methodology"),
        _e("re-library/sandbox-execution.md",
           purpose="static and dynamic sandbox execution"),
        _e("re-library/android-fingerprint-apis.md",
           purpose="android fingerprint apis",
           domain="android-dex-static"),
    ]
    result = rr.recall(entries, [], "android dex static")
    assert result.kind == "scored"
    top_paths = [se.entry.path for se in result.scored]
    assert top_paths[0] == "re-library/android-fingerprint-apis.md"
    # 阻尼把泛文档压到尾部（硬排除需 demotion 反馈数据，见 B 组用例）：
    # domain 命中的分数必须 ≥ 任意单字段碰撞泛文档的 2 倍
    scores = {se.entry.path: se.score for se in result.scored}
    android_score = scores["re-library/android-fingerprint-apis.md"]
    for generic in ("re-library/tools.md",
                    "re-library/six-phase-methodology.md",
                    "re-library/sandbox-execution.md"):
        assert android_score >= 2 * scores.get(generic, 0), (android_score,
                                                             scores)


# ---------- B. demotion 闭环 ----------

def test_demotion_closes_loop():
    e = _e("re-library/single-hit-doc.md", purpose="static analysis gdb tools")
    qset = set(rr._tokenize("static"))
    qnorm = rr._norm("static")
    base = rr._score_entry(e, qset, qnorm)[0]
    assert base > 0
    demoted_score, demoted_reasons = rr._score_entry(
        e, qset, qnorm, demotions={"static": 0.25})
    assert demoted_score < base
    assert any("demotion" in r for r in demoted_reasons)
    out = rr.recall([e], [], "static", demotions={"static": 0.25})
    assert out.scored == ()


def test_demotion_map_from_ws():
    from references_recall import demotion_map, DEMOTION_W
    tmp = Path(tempfile.mkdtemp()) / "ws"
    (tmp / "runs").mkdir(parents=True)
    (tmp / "runs" / ".recall-stats.json").write_text(
        json.dumps({"version": 1, "terms": {
            "static": {"yes": 0, "no": 1, "misleading": 3, "streak": 3}}}),
        encoding="utf-8")
    assert demotion_map(tmp) == {"static": DEMOTION_W}


# ---------- C. 注入链留痕 + 度量面 ----------

def test_inject_skip_leaves_trace(tmp_path):
    (tmp_path / "claim-register.yaml").write_text("claims: []\n",
                                                  encoding="utf-8")
    rc, err, ctx = recall_inject.evaluate(
        {"cwd": str(tmp_path), "tool_input": {"prompt": "hello world"}})
    assert rc == 0
    rows = _rows(tmp_path)
    assert any(r.get("action") == "recall_skip" for r in rows), \
        [r.get("action") for r in rows]


def test_inject_success_metrics(tmp_path):
    (tmp_path / "claim-register.yaml").write_text("claims: []\n",
                                                  encoding="utf-8")

    def runner(query, cwd=None):
        return (0, "android-fingerprint-apis.md | methodology | apis | when\n")
    rc, err, ctx = recall_inject.evaluate(
        {"cwd": str(tmp_path),
         "tool_input": {"prompt":
                        "[T2 tools=...] claim C-9 android dex static"}},
        recall_runner=runner)
    assert rc == 0
    rows = _rows(tmp_path)
    assert any(r.get("action") == "recall_injected" for r in rows)
    summary = rm.summarize(tmp_path)
    assert summary["injected"] >= 1


def test_metrics_summarize():
    tmp = Path(tempfile.mkdtemp()) / "ws"
    tmp.mkdir()
    rm.record(tmp, kind="injected", query="q1", files=3)
    rm.record(tmp, kind="skipped", query="q2", reason="not_dispatch")
    rm.record(tmp, kind="no_match", query="q3", reason="no files")
    summary = rm.summarize(tmp)
    assert summary["injected"] == 1
    assert summary["skipped"] == 1
    assert summary["no_match"] == 1
    assert summary["total"] == 3
