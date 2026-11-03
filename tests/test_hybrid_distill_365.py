# -*- coding: utf-8 -*-
"""tests/test_hybrid_distill_365.py — the hybrid research-loop kernel
(issue 365, rulings 1-2 + the conflict face).

The search action is INJECTED (a mock in every test — the module performs
no network IO of its own, grep-pinned). The self strategy rides the SAME
downstream pipeline. Conflicts are flagged, never silently resolved; an
external-derived item never supersedes an evidence-derived one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import rlvr.episode_pool as pool  # noqa: E402
import distill_schema as ds  # noqa: E402
from rlvr import distill_dgate as dg  # noqa: E402
import hybrid_distill as hd  # noqa: E402


# ------------------------------------------------------------- fixtures

def _ws(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    (ws / "runs").mkdir()
    (ws / "notes").mkdir()
    return ws


_GOOD_NOTE = (
    "---\nclaim_id: C-9\nverify_status: passes\n---\n\n"
    "# note: the frida-first plan\n\n"
    "## why this plan order\n\n"
    "unpack runs before hooking because the loader re-encrypts its\n"
    "sections on the first execution pass.\n\n"
    "## situation to next action branches\n\n"
    "- if attach succeeds then dump the module table\n"
    "- if attach fails then repack the gadget and retry once\n"
    "pass := replay matches the anchored bytes\n"
    "verify_dump()\n\n"
    "## hidden reasoning\n\n"
    "the timing check poisons outputs only while a debugger is\n"
    "attached, so the poison is a decoy rather than a real path.\n")

_LOW_NOTE = (
    "# note: thin\n\n"
    "## why this plan order\n\n"
    "on claim C-7 dump sha256 into runs/blob.json first.\n\n"
    "## situation to next action branches\n\n"
    "- on claim C-8 read evidence/die.json\n\n"
    "## hidden reasoning\n\n"
    "the case files named above carry the whole story here.\n")


def _lesson(tmp_path: Path) -> Path:
    lib = tmp_path / "lessons"
    lib.mkdir()
    (lib / "lesson-replay-first.md").write_text(
        "---\nslug: replay-first\ndeprecated: false\n"
        "next_method: replay the anchored bytes before trusting any "
        "decoded output\n---\n\nbody\n", encoding="utf-8")
    (lib / "lesson-thin.md").write_text(
        "---\nslug: thin\ndeprecated: false\n"
        "next_method: on claim C-9 dump sha256 from evidence/blob.bin\n"
        "---\n\nbody\n", encoding="utf-8")
    return lib


def _scripted_search(script: list[list[str]]):
    """A mock search action: pops one scripted result page per call."""
    calls = {"n": 0}

    def search(hypothesis: str) -> list[str]:
        calls["n"] += 1
        return list(script[calls["n"] - 1]) \
            if calls["n"] <= len(script) else []

    search.calls = calls  # type: ignore[attr-defined]
    return search


class TestNoNetworkIO:
    def test_module_source_names_no_network_imports(self):
        src = Path(hd.__file__).read_text(encoding="utf-8")
        for banned in ("import urllib", "import requests",
                       "import http.client", "import socket",
                       "urlopen", "import subprocess"):
            assert banned not in src, banned


class TestResearchLoop:
    def test_fertile_rounds_converge(self):
        search = _scripted_search([
            ["novel-signing-trick one", "novel-signing-trick two"]])
        def next_hyp(results, corpus, hyp):
            return None  # the model converges after one fertile round
        out = hd.run_research("h0: how do they sign", search,
                              next_hypothesis=next_hyp)
        assert out["status"] == "converged"
        assert out["rounds"][0]["fertile"] is True
        assert out["corpus"]

    def test_two_barren_rounds_abandon_with_reason(self):
        search = _scripted_search([["known token only"],
                                   ["known token only"]])
        out = hd.run_research(
            "h0", search, known_corpus=["known token only"],
            next_hypothesis=lambda r, c, h: "h1")
        assert out["status"] == "abandoned"
        assert out["reason"] == "barren"
        assert search.calls["n"] == 2

    def test_budget_cap_stops_the_loop(self):
        words = ["alpha", "bravo", "charlie", "delta"]
        script = [[f"fresh page {words[i]} tokens"]
                  for i in range(hd.MAX_RESEARCH_ROUNDS)]
        search = _scripted_search(script)
        out = hd.run_research(
            "h0", search,
            next_hypothesis=lambda r, c, h: f"next-{len(c)}")
        assert out["status"] == "budget"
        assert search.calls["n"] == hd.MAX_RESEARCH_ROUNDS

    def test_convergence_without_signal_is_abandon(self):
        search = _scripted_search([[]])
        out = hd.run_research("h0", search,
                              next_hypothesis=lambda r, c, h: None)
        assert out["status"] == "abandoned"
        assert out["reason"] == "no-signal"

    def test_results_capped_per_round(self):
        search = _scripted_search([
            [f"brand new result number {i}" for i in range(50)]])
        def next_hyp(results, corpus, hyp):
            assert len(results) <= hd.RESULTS_PER_ROUND_CAP
            return None
        hd.run_research("h0", search, next_hypothesis=next_hyp)


# ------------------------------------------------- the shared pipeline

def _run_self(tmp_path: Path, assessor=None) -> dict:
    ws = _ws(tmp_path)
    (ws / "notes" / "note-good.md").write_text(_GOOD_NOTE, encoding="utf-8")
    (ws / "notes" / "note-low.md").write_text(_LOW_NOTE, encoding="utf-8")
    lib = _lesson(tmp_path)
    (ws / "runs" / "env-state.json").write_text(
        '{"android": {"usb": true}}', encoding="utf-8")
    out = hd.run_collection(ws, strategy="self", lessons_library=lib,
                            assessor=assessor)
    return out


class TestSelfPipeline:
    def test_items_from_synthetic_workspace(self, tmp_path):
        out = _run_self(tmp_path)
        assert out["strategy"] == "self"
        ids = [r["item"] for r in out["attempts"]]
        assert len(ids) >= 2  # the good note AND the lesson produce items
        assert all(r["score"] is not None for r in out["attempts"])

    def test_good_note_admits_into_pool_with_rollout_row(self, tmp_path):
        out = _run_self(tmp_path)
        landed = [r for r in out["attempts"]
                  if r["product"] != "abandoned"]
        assert landed, out
        for row in landed:
            assert pool.episode_path(tmp_path / "ws",
                                     row["item"]).is_file()
            assert (tmp_path / "ws" / row["product"]).is_file()
        rows = out["rollout_rows"]
        assert any(r["reward"] == pytest.approx(1.0) for r in rows)

    def test_low_note_abandons_with_reason(self, tmp_path):
        out = _run_self(tmp_path)
        dropped = [r for r in out["attempts"]
                   if r["product"] == "abandoned"]
        assert dropped, out
        assert all(r["reason"].startswith("below-threshold")
                   for r in dropped)
        assert all(r["reward"] == pytest.approx(0.01)
                   for r in dropped)

    def test_dgate_gate_keeps_bad_notes_out(self, tmp_path):
        ws = _ws(tmp_path)
        (ws / "notes" / "only-bad.md").write_text(_LOW_NOTE,
                                                  encoding="utf-8")
        lib = _lesson(tmp_path)
        out = hd.run_collection(ws, strategy="self", lessons_library=lib)
        # the low note is not even a SOURCE (D-gate); the lesson item is
        assert not any("only-bad" in str(r.get("source_refs", ""))
                       for r in out["attempts"])
        assert dg.lint_note(_LOW_NOTE)["ok"] is False


class TestConflictFace:
    def _seed_item(self, tmp_path: Path, claim: str) -> None:
        ws = tmp_path / "ws"
        (ws / "runs" / f"verification-{claim}.md").write_text(
            f"# verification {claim}\n\nverdict: verified\n",
            encoding="utf-8")
        doc = {
            "schema": "episode/1", "id": f"E-{claim}", "claim": claim,
            "created": "2026-10-27T00:00:00Z",
            "updated": "2026-10-27T00:00:00Z",
            "context_features": ["android"],
            "commits": [{"seq": 1, "action": "deliver",
                         "summary": "seed"}],
            "outcome": {"status": "completed", "verified": True,
                        "evidence_ref":
                            f"runs/verification-{claim}.md"},
            "cost": {"tokens": 0.0, "seconds": 0.0},
            "utility": {"retrievals": 0, "citations": 0, "utility": 0.0},
            "reusable_fragments": [
                "repack the gadget before attach, then verify by replay"],
            "milestones": [],
            "distill": ds.lint_block({
                "schema": "distill-item/1", "source_strategy": "self",
                "source_refs": ["notes/seed.md"],
                "collection_ts": "2026-10-27T00:00:00Z",
                "content": {"branch_table": ["repack then verify"],
                            "verdict_algebra": ["pass := replay"],
                            "pseudocode_groups": ["step()"]},
                "scoring": {"generality": 0.9, "self_inspiring": 0.9,
                            "methodology": 0.9, "novelty": 0.9,
                            "total": 0.9,
                            "assessor": "assessor-dispatch/1"},
                "epistemic_class": "evidence-derived",
                "lineage": {"supersedes": "", "superseded_by": ""},
                "optimization_rounds": 0,
            }),
        }
        pool.write_episode(ws, doc)

    def _new_block(self, supersedes: str = "",
                   epistemic_class: str = "evidence-derived") -> dict:
        return ds.lint_block({
            "schema": "distill-item/1", "source_strategy": "self",
            "source_refs": ["notes/n2.md"],
            "collection_ts": "2026-10-27T00:00:00Z",
            "content": {"branch_table": [
                "repack the gadget before attach, then verify by replay"],
                "verdict_algebra": ["pass := replay"],
                "pseudocode_groups": [
                    "step()",
                    "verify_supersession()",
                    "rotate_the_seed_material()"]},
            "scoring": {"generality": 0.9, "self_inspiring": 0.9,
                        "methodology": 0.9, "novelty": 0.0,
                        "total": 0.9, "assessor": "assessor-dispatch/1"},
            "epistemic_class": epistemic_class,
            "lineage": {"supersedes": supersedes, "superseded_by": ""},
            "optimization_rounds": 0,
        })

    def test_near_duplicate_without_supersedes_is_refused(self, tmp_path):
        ws = _ws(tmp_path)
        self._seed_item(tmp_path, "D-seed")
        out = hd.land_item(ws, "D-dup", self._new_block())
        assert out["landed"] is False
        assert out["reason"] == "conflict"
        assert out["conflicts"]
        assert not pool.episode_path(ws, "D-dup").exists()

    def test_declared_supersedes_lands(self, tmp_path):
        ws = _ws(tmp_path)
        self._seed_item(tmp_path, "D-seed")
        out = hd.land_item(ws, "D-next",
                           self._new_block(supersedes="D-seed"))
        assert out["landed"] is True
        assert pool.episode_path(ws, "D-next").is_file()

    def test_external_derived_never_supersedes_evidence(self, tmp_path):
        ws = _ws(tmp_path)
        self._seed_item(tmp_path, "D-seed")
        out = hd.land_item(ws, "D-web",
                           self._new_block(supersedes="D-seed",
                                           epistemic_class=
                                           "external-derived"))
        assert out["landed"] is False
        assert out["reason"] == "lineage-wall"
        assert not pool.episode_path(ws, "D-web").exists()

    def test_conflicts_flag_similarity_topk(self, tmp_path):
        ws = _ws(tmp_path)
        self._seed_item(tmp_path, "D-seed")
        flags = hd.flag_conflicts(ws, [
            "repack the gadget before attach, then verify by replay"])
        assert flags and flags[0]["claim"] == "D-seed"
        assert flags[0]["similarity"] == pytest.approx(1.0)
