#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_emit_gate_880.py — EMIT vocabulary double-ended gate (#880).

Issue #880 scope item 1: "EMIT_ACTIONS 双向 CI 门——每个 action 必须有 ≥1 生产
发射者（散文词表死），无发射者的孤儿 action 删除——机械化非文档约定".

Two directions, one gate:
  forward  (vocabulary → code): every EMIT_ACTIONS word must have >= 1
           production emitter — a quoted literal of the word in scripts/*.py
           or hooks/*.py (event_taxonomy.py itself excluded). A word that
           lives only in the vocabulary file (or in prose docstrings) is an
           ORPHAN and turns the gate red.
  reverse  (code → vocabulary): every emit-site action literal must be a
           registered word (mirrors the #459 CI anchor in
           test_event_stream_adoption.py; kept inline here so the gate is
           standalone-runnable without pytest).

Acceptance pins in this file:
  - clean repo is green (the real vocabulary has no orphans);
  - a SYNTHETIC orphan action turns the gate red ("人为制造孤儿 action → 门红");
  - a synthetic unregistered literal turns the gate red (reverse side);
  - `tool_call` has a real emitter and is registered (#880 RC1 fix — the
    gate admits it, the forward scan finds its producer).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import emit_gate  # noqa: E402


# ---------- helpers: synthetic mini-repos -----------------------------------

def _mini_repo(tmp: Path, vocab: list[str], files: dict[str, str]) -> Path:
    """A tmp repo skeleton the gate can scan: scripts/event_taxonomy.py with
    the given EMIT_ACTIONS plus the given extra module files."""
    (tmp / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp / "hooks").mkdir(parents=True, exist_ok=True)
    (tmp / "scripts" / "event_taxonomy.py").write_text(
        "EMIT_ACTIONS = " + repr(sorted(vocab)) + "\n", encoding="utf-8")
    for name, text in files.items():
        p = tmp / "scripts" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp


# ---------- forward side: vocabulary must not contain orphans ---------------

class TestForwardOrphans:
    def test_clean_repo_has_zero_orphans(self):
        """The real vocabulary: every word has >= 1 production emitter."""
        report = emit_gate.scan(REPO_ROOT)
        assert report["orphans"] == {}, (
            f"orphan EMIT_ACTIONS words (word registered but never emitted "
            f"by production code): {report['orphans']}")

    def test_synthetic_orphan_turns_gate_red(self, tmp_path):
        """人为制造孤儿 action → 门红 (#880 acceptance). A word registered in
        EMIT_ACTIONS but emitted nowhere is flagged, with the word named."""
        root = _mini_repo(
            tmp_path, ["real_word", "ghost_action_880"],
            {"producer.py": 'kunglao_log.emit(ws, "orchestrator", "real_word")\n'})
        report = emit_gate.scan(root)
        assert "ghost_action_880" in report["orphans"], report
        assert "real_word" not in report["orphans"], report

    def test_prose_mention_is_not_an_emitter(self, tmp_path):
        """The RC1 hiding shape: a word in an (unquoted) docstring must NOT
        count as a producer — exactly how `tool_call` stayed dead before."""
        root = _mini_repo(
            tmp_path, ["dead_word"],
            {"doc_only.py": '"""the dead_word is mentioned in prose only"""\n'})
        report = emit_gate.scan(root)
        assert "dead_word" in report["orphans"], report

    def test_main_rc_is_1_on_orphan(self, tmp_path):
        root = _mini_repo(tmp_path, ["ghost_action_880"], {})
        assert emit_gate.main([str(root)]) == 1


# ---------- reverse side: code literals must be registered ------------------

class TestReverseUnregistered:
    def test_clean_repo_has_zero_unregistered(self):
        report = emit_gate.scan(REPO_ROOT)
        assert report["unregistered"] == {}, report["unregistered"]

    def test_unregistered_literal_turns_gate_red(self, tmp_path):
        root = _mini_repo(
            tmp_path, ["real_word"],
            {"rogue.py": 'kunglao_log.emit(ws, "orchestrator", "zomg_880")\n'})
        report = emit_gate.scan(root)
        assert report["unregistered"].get("scripts/rogue.py") == {"zomg_880"}, (
            report["unregistered"])

    def test_argparse_action_kwarg_is_excluded(self, tmp_path):
        """argparse's own `action=` kwarg is a different contract — never an
        event-stream literal (same exclusion as the #459 anchor)."""
        root = _mini_repo(
            tmp_path, [],
            {"cli.py": 'parser.add_argument("--x", action="store_true")\n'})
        report = emit_gate.scan(root)
        assert report["unregistered"] == {}, report


# ---------- #880 acceptance: tool_call has a real emitter -------------------
# (word-registration pins live in test_observability_birth_880.py and land in
# the SAME commit as the emitters — same-frame registration discipline, since
# the forward gate above turns red on a word without a producer.)
