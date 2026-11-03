#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests/test_rl_v3_playbook_960.py — the Type-2 playbook channel.

scripts/rlvr/family_playbook.py (schema + store + injection block) and
scripts/rlvr/playbook_distill.py (the terminal distillation call) are
the Type-2 transfer channel: a SMALL, STABLE family playbook injected
WHOLE at init — no retrieval layer — updated by ONE fail-closed frozen-
model call per rollout terminal through a mechanical evidence gate.
Pinned here:

  S1  schema: round-trip byte stability (canonical idempotent, tolerant
      parse, canonicalizing serialize), entry shapes, line accounting,
      family-name sanitation, call-time root resolution
  S2  the injection face: labeled whole-file block, absent-file -> "",
      hostile family -> ""
  G1  the mechanical patch gate: shape refusals (unknown op, missing
      section/text, add-duplicate, modify/retire-missing), evidence-ref
      EXISTENCE verification against the ws, entry-over-budget refusal
  G2  capacity culling: lowest-evidence-count first, deterministic
      tie-break, always terminates
  D1  the distillation call: ONE call per terminal (the cost contract),
      the fail-closed matrix (executor crash / garbage output / no
      terminal material / zero gated ops -> playbook file byte-
      unchanged + one loud warn), add/modify/retire end-to-end through
      a stub executor, same-input byte-determinism
  W1  the init-injection seam: KUNGLAO_PLAYBOOK=1 on/off, file-exists
      gating, prompt byte-identity when off, the warm-vs-cold A/B
      prompt pair differing ONLY by the playbook block, redo rides it

stdlib + pytest only (house eval-script rule).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from rlvr import family_playbook as fpb  # noqa: E402
from rlvr import playbook_distill as pd  # noqa: E402

import eval_loop_runner as lr  # noqa: E402


# ---- fixtures --------------------------------------------------------------
@pytest.fixture(autouse=True)
def _playbook_env(monkeypatch, tmp_path):
    """Every test gets an isolated playbook root + the injection OFF
    (the production default — tests opt IN explicitly)."""
    monkeypatch.setenv("KUNGLAO_PLAYBOOK_ROOT", str(tmp_path / "pbooks"))
    monkeypatch.delenv(lr.ENV_PLAYBOOK, raising=False)


def _entry(situation: str, lines: tuple[str, ...] = ("do the thing",),
           evidence: tuple[str, ...] = ("facts/F001.md",)) -> fpb.PlaybookEntry:
    return fpb.PlaybookEntry(situation=situation, lines=lines,
                             evidence=evidence)


def _doc(entries: tuple[fpb.PlaybookEntry, ...], family: str = "tf-snake"
         ) -> fpb.PlaybookDoc:
    return fpb.PlaybookDoc(family=family,
                           title=f"# playbook: {family}",
                           entries=entries)


def _seed_ws(tmp: Path) -> Path:
    """A minimal terminal workspace: one fact, one blocker, one probe
    reading — the citable evidence surface for the gate tests."""
    (tmp / "facts").mkdir(parents=True, exist_ok=True)
    (tmp / "blockers").mkdir(parents=True, exist_ok=True)
    (tmp / "evidence").mkdir(parents=True, exist_ok=True)
    (tmp / "facts" / "F001-headless-cgevent.md").write_text(
        "F001 CGEvent path wastes budget in headless sessions\n",
        encoding="utf-8")
    (tmp / "blockers" / "must-ask-C001.md").write_text(
        "blocker: grader co-located with task material\n", encoding="utf-8")
    (tmp / "evidence" / "probe-001.json").write_text(
        json.dumps({"schema": "kunglao-probe-reading/1", "scalar": 0.5}),
        encoding="utf-8")
    return tmp


def _ws_only(tmp: Path) -> Path:
    """A minimal evidence-bearing ws without blockers/probe extras."""
    (tmp / "facts").mkdir(parents=True, exist_ok=True)
    (tmp / "facts" / "F001-headless-cgevent.md").write_text(
        "evidence text\n", encoding="utf-8")
    return tmp


_CANONICAL = (
    "# playbook: tf-snake\n"
    "<!-- kunglao-playbook/1; injected whole at init; hard line budget -->\n"
    "\n"
    "### in a headless session\n"
    "avoid the CGEvent path — do memory-injection routes first\n"
    "evidence: facts/F001.md\n"
    "\n"
    "### before constructing the candidate\n"
    "the grader is co-located with the task material — construction "
    "hygiene required\n"
    "evidence: blockers/must-ask-C001.md evidence/probe-001.json\n")


def _stub_executor(patch: list[dict] | str, calls: list[str]):
    """The deterministic executor stub (the bench seam convention)."""
    def _exec(prompt: str) -> str:
        calls.append(prompt)
        if isinstance(patch, str):
            return patch
        return json.dumps(patch)
    return _exec


def _task960() -> dict:
    """Minimal task dict for the prompt builders (anchors + scaffold)."""
    return {
        "anchors": {"goal_verbatim": "GOAL-VERBATIM-960",
                    "success_criterion": "SUCCEED-960",
                    "verification_method": "reproduction"},
        "workspace_scaffold": {"files": ["bins/sample.bin"],
                               "candidate_contract": "CONTRACT-960"},
    }


def _tdir() -> Path:
    return ROOT / "tests" / "_playbook960-nonexistent"


# ---- S1: schema round-trip -------------------------------------------------
class TestSchemaRoundTrip:
    def test_canonical_round_trip_is_byte_stable(self):
        assert fpb.serialize(fpb.parse(_CANONICAL)) == _CANONICAL

    def test_round_trip_idempotent(self):
        once = fpb.serialize(fpb.parse(_CANONICAL))
        twice = fpb.serialize(fpb.parse(once))
        assert once == twice == _CANONICAL

    def test_tolerant_parse_canonicalizes(self):
        messy = ("preamble junk that is dropped\n"
                 "<!-- a stray comment -->\n"
                 "# playbook: tf-snake\n"
                 "\n\n"
                 "###  sit   \n"
                 "line one\n"
                 "evidence: a.md, b.md\n"   # the comma form
                 "\n"
                 "### s2\n"
                 "l1\n"
                 "l2\n"
                 "evidence: c.md\n"
                 "evidence: c.md\n"         # duplicate ref dedup
                 "d.md\n")                  # a strategy line AFTER evidence
        doc = fpb.parse(messy, family="tf-snake")
        assert [e.situation for e in doc.entries] == ["sit", "s2"]
        assert doc.entries[0].lines == ("line one",)
        assert doc.entries[0].evidence == ("a.md", "b.md")
        assert doc.entries[1].lines == ("l1", "l2", "d.md")
        assert doc.entries[1].evidence == ("c.md",)
        assert fpb.line_count(doc) == len(fpb.serialize(doc).splitlines())
        assert fpb.serialize(fpb.parse(fpb.serialize(doc))) == \
            fpb.serialize(doc)

    def test_empty_doc_shape(self):
        doc = fpb.PlaybookDoc(family="tf-snake", title="")
        text = fpb.serialize(doc)
        assert text == ("# playbook: tf-snake\n"
                        "<!-- kunglao-playbook/1; injected whole at init; "
                        "hard line budget -->\n")
        assert fpb.line_count(doc) == 2

    def test_family_name_sanitation(self):
        assert fpb.playbook_path("../evil") is None
        assert fpb.playbook_path("a/b") is None
        assert fpb.playbook_path("") is None
        assert fpb.playbook_path("tf-snake") is not None
        assert fpb.playbook_path("tf-snake").name == "tf-snake.md"

    def test_root_resolution_call_time_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("KUNGLAO_PLAYBOOK_ROOT", str(tmp_path))
        assert fpb.playbook_root() == tmp_path
        monkeypatch.delenv("KUNGLAO_PLAYBOOK_ROOT")
        assert fpb.playbook_root() == fpb.ROOT / "experiments" \
            / "blocked-path-units" / "playbooks"

    def test_line_accounting(self):
        doc = _doc((_entry("s", lines=("a", "b"),
                           evidence=("facts/F001.md",)),))
        assert fpb.line_count(doc) == 7  # title + comment + blank + 4
        assert fpb.entry_line_count(_entry("s", lines=("a", "b"))) == 4


# ---- S2: the injection face ------------------------------------------------
class TestInjectionFace:
    def test_block_labeled_whole_file(self, tmp_path):
        root = tmp_path / "pbooks"
        root.mkdir(parents=True)
        fpb.save(_doc((_entry("in a headless session"),)),
                 root / "tf-snake.md")
        block = fpb.session_block("tf-snake", root=root)
        assert block.startswith(fpb.BLOCK_LABEL)
        assert "### in a headless session" in block
        assert "kunglao-playbook/1" in block
        assert "hard line budget -->" in block  # NO retrieval: whole file

    def test_absent_file_empty_block(self):
        assert fpb.session_block("no-such-family") == ""

    def test_hostile_family_empty_block(self):
        assert fpb.session_block("../evil") == ""


# ---- G1: the mechanical patch gate -----------------------------------------
class TestPatchGate:
    def test_drops_entry_without_refs(self, tmp_path):
        ws = _seed_ws(tmp_path / "ws")
        doc = fpb.parse(_CANONICAL)
        gated, dropped = pd.gate_patch(
            [{"op": "add", "section": "new situation",
              "text": "strategy", "evidence_refs": []}], ws, doc)
        assert gated == []
        assert dropped and dropped[0][1] == "no-verified-evidence"

    def test_verifies_refs_against_ws(self, tmp_path):
        ws = _seed_ws(tmp_path / "ws")
        doc = fpb.parse(_CANONICAL)
        gated, dropped = pd.gate_patch(
            [{"op": "add", "section": "s-new",
              "text": "strategy",
              "evidence_refs": ["facts/F001-headless-cgevent.md",
                                "facts/NOT-THERE.md"]}], ws, doc)
        assert len(gated) == 1
        # the unresolvable ref is dropped, the real one kept
        assert gated[0]["evidence_refs"] == \
            ["facts/F001-headless-cgevent.md"]
        assert dropped == []

    def test_absolute_ref_rejected(self, tmp_path):
        """Review round 1 MEDIUM: ws-relative contained refs only — an
        absolute path is not workspace evidence (and a ../ escape must
        not resolve outside)."""
        ws = _ws_only(tmp_path / "ws")
        doc = fpb.parse(_CANONICAL)
        fact = ws / "facts" / "F001-headless-cgevent.md"
        gated, _ = pd.gate_patch(
            [{"op": "add", "section": "s-abs",
              "text": "strategy", "evidence_refs": [str(fact)]}],
            ws, doc)
        assert gated == []

    def test_escape_ref_rejected(self, tmp_path):
        ws = _ws_only(tmp_path / "ws")
        doc = fpb.parse(_CANONICAL)
        gated, _ = pd.gate_patch(
            [{"op": "add", "section": "s-esc",
              "text": "strategy",
              "evidence_refs": ["facts/../../secret.txt"]}],
            ws, doc)
        assert gated == []

    def test_shape_refusals(self, tmp_path):
        ws = _ws_only(tmp_path / "ws")
        doc = fpb.parse(_CANONICAL)
        real = ["facts/F001-headless-cgevent.md"]
        gated, dropped = pd.gate_patch([
            {"op": "amend", "section": "s", "text": "t",
             "evidence_refs": real},                     # unknown op
            {"op": "add", "section": "", "text": "t",
             "evidence_refs": real},                     # empty section
            {"op": "add", "section": "s3", "text": "   ",
             "evidence_refs": real},                     # blank text
            {"op": "add", "section": "in a headless session",
             "text": "t", "evidence_refs": real},        # add-duplicate
            {"op": "modify", "section": "not-there",
             "text": "t", "evidence_refs": real},        # modify-missing
            {"op": "retire", "section": "not-there"},    # retire-missing
            {"op": "retire",
             "section": "in a headless session"},        # the keeper
        ], ws, doc)
        assert [g["op"] for g in gated] == ["retire"]
        assert len(dropped) == 6

    def test_entry_over_budget_refused(self, tmp_path):
        ws = _ws_only(tmp_path / "ws")
        doc = fpb.parse(_CANONICAL)
        gated, dropped = pd.gate_patch(
            [{"op": "add", "section": "huge",
              "text": "\n".join(f"l{i}" for i in range(70)),
              "evidence_refs": ["facts/F001-headless-cgevent.md"]}],
            ws, doc)
        assert gated == []
        assert dropped[0][1] == "entry-exceeds-budget"


# ---- G2: capacity culling ---------------------------------------------------
class TestCapacityCulling:
    def test_lowest_evidence_first(self):
        entries = (_entry("rich", evidence=("a", "b", "c")),
                   _entry("mid", evidence=("a", "b")),
                   _entry("poor", evidence=("a",)))
        fitted, culled = fpb.fit_budget(
            _doc(entries), budget=fpb.line_count(_doc(entries)) - 1)
        assert culled == 1
        assert [e.situation for e in fitted.entries] == ["rich", "mid"]

    def test_tie_break_later_position_first(self):
        a = _entry("a", evidence=("x",))
        b = _entry("b", evidence=("x",))
        fitted, culled = fpb.fit_budget(
            _doc((a, b)), budget=fpb.line_count(_doc((a, b))) - 1)
        assert culled == 1
        assert [e.situation for e in fitted.entries] == ["a"]

    def test_terminates_and_can_go_empty(self):
        entries = tuple(_entry(f"s{i}", evidence=("e",)) for i in range(3))
        fitted, culled = fpb.fit_budget(_doc(entries), budget=2)
        assert culled == 3
        assert fitted.entries == ()
        assert fpb.line_count(fitted) == 2  # header only


# ---- D1: the distillation call ---------------------------------------------
class TestDistillCall:
    def test_happy_path_end_to_end(self, tmp_path, capsys):
        ws = _seed_ws(tmp_path / "ws")
        path = tmp_path / "pbooks" / "tf-snake.md"
        fpb.save(fpb.parse(_CANONICAL), path)
        calls: list[str] = []
        patch = [
            {"op": "add", "section": "when the probe saturates",
             "text": "move to the next arm — the ceiling is real",
             "evidence_refs": ["evidence/probe-001.json"]},
            {"op": "modify",
             "section": "in a headless session",
             "text": "avoid the CGEvent path — memory-injection "
                     "routes first, always",
             "evidence_refs": ["facts/F001-headless-cgevent.md"]},
            {"op": "retire",
             "section": "before constructing the candidate"},
        ]
        out = pd.distill(ws, "tf-snake", path,
                         executor=_stub_executor(patch, calls))
        assert out["applied"] is True
        assert out["calls"] == 1, "ONE call per terminal — the cost contract"
        assert len(out["patch"]) == 3
        new = fpb.parse(path.read_text(encoding="utf-8"))
        assert [e.situation for e in new.entries] == \
            ["in a headless session", "when the probe saturates"]
        assert new.entries[0].lines == (
            "avoid the CGEvent path — memory-injection routes first, "
            "always",)
        # modify UNIONS the evidence refs (old first, new appended)
        assert new.entries[0].evidence == (
            "facts/F001.md", "facts/F001-headless-cgevent.md")
        assert capsys.readouterr().err == ""

    def test_determinism_same_stub_byte_identical(self, tmp_path):
        ws = _seed_ws(tmp_path / "ws")
        patch = [{"op": "add", "section": "s-new", "text": "strat",
                  "evidence_refs": ["facts/F001-headless-cgevent.md"]}]
        files = []
        for i in range(2):
            path = tmp_path / "pbooks" / f"det{i}.md"
            fpb.save(fpb.parse(_CANONICAL), path)
            out = pd.distill(ws, "tf-snake", path,
                             executor=_stub_executor(patch, []))
            assert out["applied"]
            files.append(path.read_text(encoding="utf-8"))
        assert files[0] == files[1]

    def test_fail_closed_executor_crash(self, tmp_path, capsys):
        ws = _seed_ws(tmp_path / "ws")
        path = tmp_path / "pbooks" / "tf-snake.md"
        fpb.save(fpb.parse(_CANONICAL), path)
        before = path.read_bytes()

        def boom(_prompt: str) -> str:
            raise RuntimeError("the model call exploded")

        out = pd.distill(ws, "tf-snake", path, executor=boom)
        assert out["applied"] is False
        assert out["patch"] == []
        # #969 cost-contract restatement: the ATTEMPT is the spend — a
        # faulted call still went out and costs money (pre-call refusals
        # like no-terminal-material stay calls=0)
        assert out["calls"] == 1
        assert path.read_bytes() == before, "file byte-untouched"
        assert "playbook_distill" in capsys.readouterr().err

    def test_fail_closed_garbage_output(self, tmp_path, capsys):
        ws = _seed_ws(tmp_path / "ws")
        path = tmp_path / "pbooks" / "tf-distill-garbage.md"
        fpb.save(fpb.parse(_CANONICAL), path)
        before = path.read_bytes()
        out = pd.distill(ws, "tf-snake", path,
                         executor=_stub_executor("not json at all {", []))
        assert out["applied"] is False
        assert out["reason"].startswith("parse-fault")
        assert path.read_bytes() == before
        assert "playbook_distill" in capsys.readouterr().err

    def test_no_terminal_material_no_call(self, tmp_path):
        ws = tmp_path / "empty-ws"
        ws.mkdir()
        path = tmp_path / "pbooks" / "tf-distill-nomat.md"
        fpb.save(fpb.parse(_CANONICAL), path)
        calls: list[str] = []
        out = pd.distill(ws, "tf-snake", path,
                         executor=_stub_executor([], calls))
        assert out["applied"] is False
        assert out["reason"] == "no-terminal-material"
        assert out["calls"] == 0 and calls == []

    def test_zero_gated_ops_no_write(self, tmp_path):
        ws = _seed_ws(tmp_path / "ws")
        path = tmp_path / "pbooks" / "tf-distill-nogate.md"
        fpb.save(fpb.parse(_CANONICAL), path)
        before = path.read_bytes()
        patch = [{"op": "add", "section": "in a headless session",
                  "text": "dup",
                  "evidence_refs": ["facts/F001-headless-cgevent.md"]}]
        out = pd.distill(ws, "tf-snake", path,
                         executor=_stub_executor(patch, []))
        assert out["applied"] is False
        assert out["reason"] == "no-gated-ops"
        assert path.read_bytes() == before

    def test_material_globs_and_cap(self, tmp_path):
        ws = _seed_ws(tmp_path / "ws")
        rels = [r for r, _t in pd.collect_material(ws)]
        assert rels == ["facts/F001-headless-cgevent.md",
                        "blockers/must-ask-C001.md",
                        "evidence/probe-001.json"]
        big = _seed_ws(tmp_path / "big")
        (big / "facts" / "F999-huge.md").write_text("x" * 200_000,
                                                    encoding="utf-8")
        total = sum(len(t) for _r, t in pd.collect_material(big))
        assert total <= pd.MATERIAL_CAP_CHARS + len(pd.TRUNCATION_MARKER) + 1


# ---- W1: the init-injection seam -------------------------------------------
class TestInitInjection:
    def test_default_off_prompt_no_block(self):
        prompt = lr.build_loop_prompt(_tdir(), _task960(),
                                      "runs/deliverables/c.py")
        assert fpb.BLOCK_LABEL not in prompt
        assert "FAMILY PLAYBOOK" not in prompt

    def test_env_on_file_present_block_in_prompt(self, tmp_path,
                                                 monkeypatch):
        root = tmp_path / "pbooks"
        root.mkdir(parents=True)
        fpb.save(_doc((_entry("in a headless session"),)),
                 root / "tf-snake.md")
        monkeypatch.setenv(lr.ENV_PLAYBOOK, "1")
        block = lr.playbook_injection_block("tf-snake")
        assert block.startswith(fpb.BLOCK_LABEL)
        prompt = lr.build_loop_prompt(_tdir(), _task960(),
                                      "runs/deliverables/c.py",
                                      playbook_block=block)
        assert "### in a headless session" in prompt

    def test_env_off_block_empty_even_with_file(self, tmp_path,
                                                monkeypatch):
        root = tmp_path / "pbooks"
        root.mkdir(parents=True)
        fpb.save(_doc((_entry("s"),)), root / "tf-snake.md")
        monkeypatch.setenv(lr.ENV_PLAYBOOK, "0")
        assert lr.playbook_injection_block("tf-snake") == ""

    def test_env_on_file_missing_cold(self, monkeypatch):
        monkeypatch.setenv(lr.ENV_PLAYBOOK, "1")
        assert lr.playbook_injection_block("no-such-family") == ""

    def test_warm_vs_cold_ab_prompt_pair(self, tmp_path, monkeypatch):
        root = tmp_path / "pbooks"
        root.mkdir(parents=True)
        fpb.save(_doc((_entry("in a headless session"),)),
                 root / "tf-snake.md")
        task, tdir = _task960(), _tdir()
        deliv = "runs/deliverables/c.py"
        monkeypatch.delenv(lr.ENV_PLAYBOOK, raising=False)
        cold = lr.build_loop_prompt(tdir, task, deliv)
        monkeypatch.setenv(lr.ENV_PLAYBOOK, "1")
        warm_block = lr.playbook_injection_block("tf-snake")
        warm = lr.build_loop_prompt(tdir, task, deliv,
                                    playbook_block=warm_block)
        assert warm != cold
        assert warm.replace(f"{warm_block}\n\n", "", 1) == cold, \
            "the A/B pair differs ONLY by the injected playbook block"

    def test_redo_prompt_rides_block(self):
        redo = lr.build_redo_prompt(
            _tdir(), _task960(), "runs/deliverables/c.py",
            "CHECKER GAP\n- CHECK RESULT: FAIL",
            wall_cap_s=600.0, budget_usd=1.0, playbook_block="PB-BLOCK")
        assert "PB-BLOCK" in redo
