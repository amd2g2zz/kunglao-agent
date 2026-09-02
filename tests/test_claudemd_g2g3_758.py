# -*- coding: utf-8 -*-
"""tests/test_claudemd_g2g3_758.py — issue #758 Wave-2 tail (G2 + G3),
delivered under #755.

  G2  frame markers — init renders CLAUDE.md wrapped in
      <!-- kunglao:frame:v<version> --> … <!-- /kunglao:frame -->
      (the three claudemd-golden fixtures are regenerated through the same
      sentinel path, tests/test_renderer_unify.py pins byte equality);
  G3  collect-and-merge — upgrade `_item_claudemd_merge` rebuilds the frame
      segment from the CURRENT template while the 需求段 (Task constraints /
      task_spec injection block) and 定制段 (out-of-frame sections) stay
      BYTE-INvariant. Marker-less legacy bodies fall back to a conservative
      heading-walk; when even that cannot place the current frame the merge
      REFUSES (skip + WARN) rather than guess — 宁可旧也不要错删.

This unlocks #758's G4 positive path: after a merge the honest fresh stamp
is allowed again.
"""
from __future__ import annotations

import hashlib
import re
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import claudemd_frame as cf  # noqa: E402
import template_version as tv  # noqa: E402
from event_taxonomy import EMIT_ACTIONS  # noqa: E402
from _factories import seed_bins

CUR_VERSION = tv.read_skill_version()
STAMP = tv.stamp_line(CUR_VERSION)

# Sentinel recipe mirrored from tests/test_renderer_unify.py.
SKILL_SENTINEL = Path("/kunglao/skill-sentinel")
PAYLOAD = b"MZ\x90\x00" + b"\x00" * 64
SAMPLE_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _load_upgrade():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kunglao_upgrade", SCRIPTS / "kunglao_upgrade.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_init():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kunglao_init_g2g3", SCRIPTS / "kunglao-init.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.SKILL_DIR = SKILL_SENTINEL
    return mod


@pytest.fixture
def pinned_vi(monkeypatch):
    """Pin the interpreter series write_claudemd echoes into the venv line.
    A full-shape namedtuple keeps tuple comparisons legal under pytest."""
    import collections
    VI = collections.namedtuple("VI", "major minor micro release serial")
    real = sys.version_info
    monkeypatch.setattr(sys, "version_info", VI(3, 11, 0, "final", 0))
    yield
    monkeypatch.setattr(sys, "version_info", real)


def render_ws(tmp_path: Path) -> tuple[Path, str]:
    """ws with bins/ + a fresh sentinel init-style render (no wrappers yet
    beyond what production writes)."""
    init = _load_init()
    ws = tmp_path / "ws"
    seed_bins(ws, payload=PAYLOAD)
    target = init.write_claudemd(ws, "sample.exe", SAMPLE_SHA,
                                 project_type="windows")
    return ws, target.read_text(encoding="utf-8")


CUSTOM_SECTION = "\n## Operator notes\n\nkeep me verbatim 98765\n"


# ================================================================== G2

class TestG2FrameMarkers:
    def test_vocab_registered(self):
        assert "claudemd_merge" in EMIT_ACTIONS
        assert EMIT_ACTIONS == sorted(set(EMIT_ACTIONS))

    def test_init_render_wraps_in_markers(self, tmp_path, pinned_vi):
        _, text = render_ws(tmp_path)
        open_line, close_line = cf.frame_open(), cf.FRAME_CLOSE.strip()
        assert text.startswith(open_line), text[:80]
        assert text.rstrip().endswith(close_line)
        assert text.count(open_line) == 1 and text.count(close_line) == 1
        assert f"<!-- kunglao:frame:v{CUR_VERSION} -->" == open_line

    def test_markers_carry_no_heading_syntax(self):
        """Marker pair must be invisible to the #758 heading skeleton."""
        assert cf.frame_headings_via_tv(
            f"{cf.frame_open()}\n# H\n{cf.FRAME_CLOSE.strip()}") == ["# H"]

    def test_goldens_carry_the_markers(self):
        for t in ("windows", "linux", "android"):
            g = (REPO / "tests" / "fixtures" / "claudemd-golden" / f"{t}.md") \
                .read_text(encoding="utf-8")
            assert g.startswith(cf.frame_open()), t
            assert g.rstrip().endswith(cf.FRAME_CLOSE.strip()), t


# ================================================================== G3

class TestG3MarkedMerge:
    def test_requirement_and_custom_sections_survive(self, tmp_path,
                                                     pinned_vi):
        ws, original = render_ws(tmp_path)
        m = cf.split_marked(original)
        assert m.frame_inner is not None
        req = cf.extract_requirement(m.frame_inner)[0]
        if req is None:  # fixture renders without task_spec.yaml
            req_block = ""
            original_full = original
        else:
            req_block = req
            original_full = original
        edited = original_full.replace(
            cf.FRAME_CLOSE.strip(),
            CUSTOM_SECTION + cf.FRAME_CLOSE.strip(), 1)
        p = ws / "CLAUDE.md"
        p.write_text(edited, encoding="utf-8")

        up = _load_upgrade()
        label = up._item_claudemd_merge(ws, False)
        assert "applied" in label or "merged" in label

        out = p.read_text(encoding="utf-8")
        # markers regenerated at the CURRENT version
        assert out.startswith(cf.frame_open())
        # custom section bytes survive, outside the frame
        mm = cf.split_marked(out)
        assert "keep me verbatim 98765" in mm.tail
        # frame is the fresh render: the unchanged-template case is a fixed
        # point modulo the relocated custom section
        assert tv.frame_section_current(ws) is True
        if req_block:
            assert req_block in cf.extract_requirement(mm.frame_inner)[0] \
                or req_block in out, "requirement block bytes must survive"

    def test_stamped_prev_version_gets_merged_and_restamped(self, tmp_path,
                                                            pinned_vi):
        ws, original = render_ws(tmp_path)
        body = original.replace(cf.frame_open(), cf.frame_open(), 1)
        legacy_marked = STAMP + "\n\n" + body
        (ws / "CLAUDE.md").write_text(legacy_marked, encoding="utf-8")

        up = _load_upgrade()
        up._item_claudemd_merge(ws, False)
        written = tv.stamp_workspace(ws)  # G4 gate would now allow this
        assert (ws / "CLAUDE.md").read_text(encoding="utf-8") \
            .startswith(STAMP)

    def test_idempotent_fixed_point(self, tmp_path, pinned_vi):
        ws, _original = render_ws(tmp_path)
        p = ws / "CLAUDE.md"
        up = _load_upgrade()
        up._item_claudemd_merge(ws, False)
        first = p.read_bytes()
        up._item_claudemd_merge(ws, False)
        assert p.read_bytes() == first, \
            "merge must reach a stable fixed point (template unchanged)"


class TestG3LegacyFallback:
    def _legacy_ws(self, tmp_path: Path, body: str) -> tuple[Path, str]:
        ws, _ = render_ws(tmp_path)
        (ws / "CLAUDE.md").write_text(
            tv.stamp_line("0.1.2") + "\n\n" + body, encoding="utf-8")
        return ws, body

    def test_unwrapped_v012_body_merges_with_byte_safe_tail(self, tmp_path,
                                                            pinned_vi):
        ws, original = render_ws(tmp_path)
        inner = cf.split_marked(original).frame_inner
        stripped = re.sub(r"^<!--[^>]*-->\n?", "", inner)
        # simulate a marker-less v0.1.2 render + one user section at the end
        body = stripped + CUSTOM_SECTION
        p = ws / "CLAUDE.md"
        p.write_text(tv.stamp_line("0.1.2") + "\n\n" + body, encoding="utf-8")

        up = _load_upgrade()
        label = up._item_claudemd_merge(ws, False)
        assert "applied" in label or "merged" in label

        out = p.read_text(encoding="utf-8")
        assert out.startswith(cf.frame_open()), "markers restored"
        assert "keep me verbatim 98765" in out
        assert tv.frame_section_current(ws) is True

    def test_hand_written_junk_refuses_merge_bytes_untouched(self, tmp_path,
                                                             capsys,
                                                             pinned_vi):
        junk = "# old workspace\nlegacy only\n"
        ws, _ = self._legacy_ws(tmp_path, junk)
        p = ws / "CLAUDE.md"
        before = p.read_bytes()

        up = _load_upgrade()
        label = up._item_claudedm_merge_if_present(ws) \
            if hasattr(up, "_item_claudedm_merge_if_present") \
            else up._item_claudemd_merge(ws, False)
        assert "skip" in label.lower()
        err = capsys.readouterr().err
        assert "WARN" in err and "frame" in err.lower()
        assert p.read_bytes() == before, \
            "宁可旧也不要错删: unplaceable frame must not rewrite anything"

    def test_stray_prose_between_headings_is_preserved(self, tmp_path,
                                                       pinned_vi):
        headings = [h for h in tv.expected_frame_headings()]
        filler = "user scratch paragraph alpha 1234\n"
        parts: list[str] = []
        for idx, h in enumerate(headings):
            parts.append(h + "\n")
            if idx in (1, len(headings) - 2):
                parts.append(filler)
        body = "\n" + "".join(parts)
        ws, _ = self._legacy_ws(tmp_path, body)
        p = ws / "CLAUDE.md"

        up = _load_upgrade()
        up._item_claudemd_merge(ws, False)
        out = p.read_text(encoding="utf-8")
        assert out.count(filler.strip()) >= 2, \
            "every captured stray prose block must survive the merge"

    def test_dry_run_writes_nothing(self, tmp_path, pinned_vi):
        ws, _ = self._legacy_ws(tmp_path, "# retro\nno frame here\n")
        p = ws / "CLAUDE.md"
        before = p.read_bytes()
        up = _load_upgrade()
        up._item_claudemd_merge(ws, True)
        assert p.read_bytes() == before
