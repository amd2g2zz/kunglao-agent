# -*- coding: utf-8 -*-
"""tests/test_runtime_version_758.py — issue #758 Wave-1 (G1 pin + G4 stamp gate).

Wave-1 scope (user directive 2026-08-27): ONLY
  G1  runtime python pin — .python-version = 3.11 while pyproject keeps the
      >=3.10 tomli-backfill floor; drift detection (WARN, never FAIL) in
      env_check + kunglao_upgrade because CI (UV_PYTHON=python3.11) is the
      blocking authority, local drift is advisory;
  G4  stamp honesty — upgrade must never put a fresh template stamp on a
      stale CLAUDE.md body (the #717 amplifier class). The fix is a frame
      consistency gate; G2/G3 (three-stage CLAUDE.md.base.tmpl rework /
      collect-and-merge during upgrade) stay with #755 Wave-2 and are NOT
      touched here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"

import template_version as tv  # noqa: E402  (pytest.ini pythonpath += scripts)

CUR_VERSION = tv.read_skill_version()


# =============================================================== G1a: pin

class TestG1aPin:
    def test_python_version_file_pins_311(self):
        p = REPO / ".python-version"
        assert p.is_file(), ".python-version must exist at repo root"
        assert p.read_text(encoding="utf-8").strip() == "3.11"

    def test_pyproject_keeps_the_310_floor(self):
        # the floor is the tomli-backfill / supported-install contract
        # (tests/test_python_floor.py owns it) — the pin must NOT raise it
        text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
        assert 'requires-python = ">=3.10"' in text

    def test_ci_and_pin_agree_on_311(self):
        wf = (REPO / ".github" / "workflows" / "release-check.yml").read_text(
            encoding="utf-8")
        assert "UV_PYTHON" in wf and "python3.11" in wf, (
            "CI stays the authoritative 3.11 runner; .python-version converges "
            "local uv onto the same series")


# ============================================================ shared helpers

def _load_upgrade():
    """Fresh importlib instance per test (mirrors test_kunglao_upgrade_726)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "kunglao_upgrade", SCRIPTS / "kunglao_upgrade.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fake_vi(major: int, minor: int, micro: int = 7):
    return (major, minor, micro, "final", 0)


def _mini_ws(tmp_path: Path) -> Path:
    """Minimal stamped-current workspace (fast paths through both CLIs)."""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    stamp = tv.stamp_line(CUR_VERSION)
    (ws / "runs").mkdir()
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(stamp + "\n# facts\n", encoding="utf-8")
    (ws / "CLAUDE.md").write_text(stamp + "\n# body\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        stamp + "\nclaims: []\n# [initialized] state_hash=abc\n", encoding="utf-8")
    (ws / "analysis_state.txt").write_text(
        "state_hash=abc\nproject_type=windows\n", encoding="utf-8")
    return ws


# =============================================================== G1b: drift WARN (advisory)

class TestG1bEnvCheckDrift:
    def test_wrong_minor_python_warns(self, monkeypatch):
        import env_check as ec
        monkeypatch.setattr(sys, "version_info", _fake_vi(3, 13))
        status, detail = ec.check_python_version()
        assert status == "WARN"
        assert "3.13" in detail and "3.11" in detail

    def test_pinned_series_passes(self, monkeypatch):
        import env_check as ec
        monkeypatch.setattr(sys, "version_info", _fake_vi(3, 11))
        status, detail = ec.check_python_version()
        assert status == "PASS"
        assert "3.11" in detail

    def test_row_is_registered_and_never_fails_overall(self, monkeypatch, tmp_path):
        import env_check as ec
        monkeypatch.setattr(sys, "version_info", _fake_vi(2, 7))
        ws = _mini_ws(tmp_path)
        ec.run(ws)  # rc reflects overall; the row verdicts live in the snapshot
        report = json.loads((ws / "runs" / ".env-check.json").read_text(
            encoding="utf-8"))
        row = report["checks"]["python_version"]
        assert row["status"] == "WARN"
        failing = [k for k, v in report["checks"].items() if v["status"] == "FAIL"]
        assert "python_version" not in failing, (
            "drift is advisory — CI pins the blocking authority")


class TestG1bUpgradeEventLine:
    ERR_TOKEN = "[event] name=python_version status=warn"

    def test_drifted_interpreter_emits_stderr_line(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(sys, "version_info", _fake_vi(3, 13))
        up = _load_upgrade()
        assert up.main([str(_mini_ws(tmp_path))]) == 0
        err = capsys.readouterr().err
        assert self.ERR_TOKEN in err
        assert "3.13" in err

    def test_pinned_interpreter_stays_silent(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(sys, "version_info", _fake_vi(3, 11))
        up = _load_upgrade()
        assert up.main([str(_mini_ws(tmp_path))]) == 0
        assert self.ERR_TOKEN not in capsys.readouterr().err


# =============================================================== G4: frame-consistency stamp gate

def _prev_version() -> str:
    maj, mi, pa = (int(x) for x in CUR_VERSION.split("."))
    return ".".join(str(x) for x in (maj, mi, max(pa - 1, 0)))


def _carriers(tmp_path: Path) -> Path:
    """Two data carriers stamped one version behind (CLAUDE.md added per-test)."""
    ws = tmp_path / "ws"
    ws.mkdir(parents=True)
    old = tv.stamp_line(_prev_version())
    (ws / "facts").mkdir()
    (ws / "facts" / "_INDEX.md").write_text(
        old + "\n# facts\nF001 | PROVEN | C-1 | keep me\n", encoding="utf-8")
    (ws / "claim-register.yaml").write_text(
        old + "\nclaims: []\n# [initialized] 2026-08-01\n", encoding="utf-8")
    return ws


SKIP_MARK = "skipped: frame-drift"


class TestG4FrameGate:
    def test_consistent_frame_gets_fresh_stamp(self, tmp_path):
        ws = _carriers(tmp_path)
        lines: list[str] = []
        for i, h in enumerate(tv.expected_frame_headings()):
            lines += [h, "", f"user customization {i} between sections", ""]
        (ws / "CLAUDE.md").write_text(
            tv.stamp_line(_prev_version()) + "\n\n" + "\n".join(lines),
            encoding="utf-8")
        up = _load_upgrade()
        items: list = []
        assert up.upgrade(ws, False, items) == 0
        fresh = tv.stamp_line(CUR_VERSION)
        for rel in ("CLAUDE.md", "facts/_INDEX.md", "claim-register.yaml"):
            text = (ws / rel).read_text(encoding="utf-8")
            assert fresh in text, rel
        assert any(n.startswith("template_stamp_refresh(") and SKIP_MARK not in n
                   for n in [i["name"] for i in items])

    def test_stale_body_keeps_old_stamp_and_warns(self, tmp_path, capsys):
        ws = _carriers(tmp_path)
        old = tv.stamp_line(_prev_version())
        (ws / "CLAUDE.md").write_text(old + "\n\n# old workspace\nlegacy only\n",
                                      encoding="utf-8")
        up = _load_upgrade()
        items: list = []
        assert up.upgrade(ws, False, items) == 0
        err = capsys.readouterr().err
        # Since 0.1.4 the legacy body is handled by migrate_to_0_1_4's
        # _item_claudemd_merge (G3): the merge REFUSES ("current frame does
        # not place in order") and warns — the old-stamp body stays honest.
        assert "CLAUDE.md merge skipped" in err
        assert "does not place in order" in err, (
            "the WARN must point at the G3 merge refusal")
        fresh = tv.stamp_line(CUR_VERSION)
        for rel in ("CLAUDE.md", "facts/_INDEX.md", "claim-register.yaml"):
            text = (ws / rel).read_text(encoding="utf-8")
            assert tv.stamp_line(_prev_version()) in text, (
                f"{rel} keeps its honest old stamp")
            assert fresh not in text, f"{rel} must not carry the new stamp"
        assert "claudemd_merge(skipped" in json.dumps(items)

    def test_belt_and_braces_tail_also_gated(self, tmp_path, capsys):
        """The end-of-flow unconditional re-stamp is the bypass vector: even
        when NO migration item touches stamps, the tail must stay gated."""
        ws = _carriers(tmp_path)
        old = tv.stamp_line(_prev_version())
        (ws / "CLAUDE.md").write_text(old + "\n\n# retro\nno frame\n",
                                      encoding="utf-8")
        up = _load_upgrade()

        def bare(ws: Path, dry: bool):  # a migration with no stamp call
            return ["bare_step"]

        up.MIGRATIONS = [("9.9.9", bare)]
        assert up.upgrade(ws, False, None) == 0
        err = capsys.readouterr().err
        # bare() never warns and skips the item; the tail gate keeps the
        # stamp quiet — stderr has nothing beyond other WARN classes.
        fresh = tv.stamp_line(CUR_VERSION)
        for rel in ("CLAUDE.md", "facts/_INDEX.md", "claim-register.yaml"):
            assert fresh not in (ws / rel).read_text(encoding="utf-8"), rel

    def test_dry_run_plan_shows_the_skip(self, tmp_path, capsys):
        ws = _carriers(tmp_path)
        (ws / "CLAUDE.md").write_text(
            tv.stamp_line(_prev_version()) + "\n\n# retro\nno frame\n",
            encoding="utf-8")
        up = _load_upgrade()
        assert up.main([str(ws), "--dry-run"]) == 0
        assert f"[{CUR_VERSION}] template_stamp_refresh({SKIP_MARK})" \
            in capsys.readouterr().out


def _stale_ws_for_tail(tmp_path: Path) -> Path:
    ws = _carriers(tmp_path)
    (ws / "CLAUDE.md").write_text("# retro\nno frame\n", encoding="utf-8")
    return ws


class TestG4FrameExtractor:
    def test_fenced_block_comments_are_not_headings(self):
        doc = "# Top\n```bash\n# Register\ncamoufox.launch()\n```\n## Next\n"
        assert tv.frame_headings_from_text(doc) == ["# Top", "## Next"]

    def test_placeholders_normalized(self):
        doc = "## Loop {{skill_dir}}\n"
        assert tv.frame_headings_from_text(doc) == ["## Loop <var>"]

    def test_expected_matches_rendered_subsequence(self, tmp_path):
        expected = "# Title\n## One\n## Two\n### Three\n"
        actual = ("# stamp\n\n## User intro\n\n# Title\n\n## One\n"
                  "filler\n\n## User mid\n\n## Two\n\n### Three\n")
        (tmp_path / "CLAUDE.md").write_text(actual, encoding="utf-8")
        assert tv.frame_section_current(tmp_path,
                                        rendered_expected=expected) is True

    def test_renamed_or_dropped_heading_is_stale(self, tmp_path):
        expected = "# Title\n## One\n## Two\n"
        (tmp_path / "CLAUDE.md").write_text(
            "# Title\n## One (renamed)\n## Two\n", encoding="utf-8")
        assert tv.frame_section_current(tmp_path,
                                        rendered_expected=expected) is False

    def test_missing_carrier_is_never_current(self, tmp_path):
        expected = "# Title\n"
        assert tv.frame_section_current(tmp_path,
                                        rendered_expected=expected) is False

    def test_unreadable_template_fails_open(self, monkeypatch, tmp_path):
        monkeypatch.setattr(tv, "_FRAME_TMPL", tmp_path / "absent.tmpl")
        (tmp_path / "CLAUDE.md").write_text("# anything goes\n", encoding="utf-8")
        assert tv.frame_section_current(tmp_path) is True

    def test_real_template_vs_retro_body_is_stale(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# old workspace\npre-template era body\n", encoding="utf-8")
        assert tv.frame_section_current(tmp_path) is False


class TestG1aPinFalloutQualityGatesArgparse:
    """#758 G1a fallout: on the PINNED py3.11, argparse validates an EMPTY
    nargs="*" against `choices`, so the historical `choices=sorted(GATES)`
    killed a bare `python devkit/quality_gates.py` invocation (worked on the
    unpinned local 3.13 — exactly the drift class G1 exists to catch)."""

    @staticmethod
    def _parser():
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "kg_quality_gates", REPO / "devkit" / "quality_gates.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod._build_parser(), mod

    def test_bare_invocation_parses_to_all_gates(self):
        p, mod = self._parser()
        args = p.parse_args([])
        assert args.gates == []
        assert sorted(args.gates or mod.GATES.keys()) == sorted(mod.GATES)

    def test_gate_selection_still_parses(self):
        p, _ = self._parser()
        assert p.parse_args(["2"]).gates == [2]

    def test_out_of_range_gate_rejected_by_main_validation(self):
        _, mod = self._parser()
        assert 99 not in mod.GATES
        with pytest.raises(SystemExit):
            mod.main(["99"])
