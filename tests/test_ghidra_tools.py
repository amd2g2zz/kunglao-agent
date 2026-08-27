# -*- coding: utf-8 -*-
"""Tests for issue #293 — tools/ghidra analyzeHeadless wrapper + 5 postScript tools.

Covers:
  - run_ghidra_postscript.py build_command / split_forwarded / resolve_ghidra_home
  - GHIDRA_HOME missing -> CLI exit 2 with guidance; analysis_state.txt resolution
  - analyzeHeadless.bat missing -> exit 2; valid run collects the --out artifact
  - tools/ghidra/*.java parameterization: no hardcoded sample paths / hashes /
    @runtime Jython; shared GhidraJsonScript base; JSON schema/program/image_base
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
GHIDRA_DIR = TOOLS / "ghidra"
WRAPPER = GHIDRA_DIR / "run_ghidra_postscript.py"
JAVA_DIR = GHIDRA_DIR

sys.path.insert(0, str(TOOLS / "ghidra"))
import run_ghidra_postscript as rp  # noqa: E402

TOOL_IDS = ("ghidra-recon", "ghidra-decompile-functions", "ghidra-vtable-struct",
            "ghidra-evidence-annotations", "ghidra-scan-pointer")

# Sample-specific markers that must NOT appear in the parameterized java sources.
FORBIDDEN_MARKERS = (
    "browser_host", "mongoose", "mg_", "executecsharp",
    "a20603688b76a7c83918309ab373ca39", "ca.fpe-time.com", "fpe-time",
    "snail007", "271ebfab8606ca68137cb9573c563713e6bf8613736722aabe535ccc06bc8346",
    "22e6f41209a831bc647fbdaa29add029ba493bd2",
    "hvnc_start_process_injected", "0x1403809a0", "0x14031b240",
    "0x140633c40", "0x1405feefc", "0x14060e95d",
    "D:" + "/works", "D:" + "\\works", "C:" + "/x", "_ghidra_workspace",
)


def _wrapper_text() -> str:
    return WRAPPER.read_text(encoding="utf-8")


def _tool_java_files() -> list[Path]:
    return [GHIDRA_DIR / rp.TOOL_JAVA[t] for t in TOOL_IDS]


# ---------------------------------------------------------------------------
# Wrapper: tool -> java mapping
# ---------------------------------------------------------------------------

class TestToolJavaMapping:
    def test_five_tool_ids_registered(self) -> None:
        assert set(rp.TOOL_JAVA) == set(TOOL_IDS)

    def test_each_tool_maps_to_existing_java(self) -> None:
        for java in _tool_java_files():
            assert java.is_file(), f"missing {java}"

    def test_mapping_class_names_match_files(self) -> None:
        for java in _tool_java_files():
            text = java.read_text(encoding="utf-8")
            class_name = java.stem
            assert f"class {class_name}" in text, f"{java.name} missing class {class_name}"


# ---------------------------------------------------------------------------
# Wrapper: command construction
# ---------------------------------------------------------------------------

class TestBuildCommand:
    def test_script_path_is_absolute_ghidra_dir(self, tmp_path) -> None:
        cmd = rp.build_command(
            ghidra_home=str(tmp_path / "ghidra"), tool="ghidra-recon", binary=Path("s.exe"),
            post_args=[("search-terms", "http"), ("expected-exports", "ExportA")],
            script_path=GHIDRA_DIR, project_dir=Path("proj"), project_name="proj",
        )
        assert "-scriptPath" in cmd
        idx = cmd.index("-scriptPath")
        assert Path(cmd[idx + 1]) == GHIDRA_DIR
        assert Path(cmd[idx + 1]).is_absolute()

    def test_postscript_mapping(self, tmp_path) -> None:
        expected = {
            "ghidra-recon": "GhidraRecon.java",
            "ghidra-decompile-functions": "DecompileFunctions.java",
            "ghidra-vtable-struct": "GhidraExportVtableStruct.java",
            "ghidra-evidence-annotations": "GhidraEvidenceAnnotations.java",
            "ghidra-scan-pointer": "GhidraScanPointer.java",
        }
        for tool, java in expected.items():
            cmd = rp.build_command(
                ghidra_home=str(tmp_path / "ghidra"), tool=tool, binary=Path("s.exe"),
                post_args=[], script_path=GHIDRA_DIR,
                project_dir=Path("proj"), project_name="proj",
            )
            assert "-postScript" in cmd
            assert cmd[cmd.index("-postScript") + 1] == java

    def test_key_value_forwarded_as_dashed(self, tmp_path) -> None:
        cmd = rp.build_command(
            ghidra_home=str(tmp_path / "ghidra"), tool="ghidra-recon", binary=Path("s.exe"),
            post_args=[("search-terms", "http,socket"), ("expected-exports", "ExportA")],
            script_path=GHIDRA_DIR, project_dir=Path("proj"), project_name="proj",
        )
        assert "--search-terms=http,socket" in cmd
        assert "--expected-exports=ExportA" in cmd

    def test_import_overwrite_timeout(self, tmp_path) -> None:
        cmd = rp.build_command(
            ghidra_home=str(tmp_path / "ghidra"), tool="ghidra-recon", binary=Path("s.exe"),
            post_args=[], script_path=GHIDRA_DIR,
            project_dir=Path("proj"), project_name="proj",
        )
        assert "-import" in cmd
        assert "s.exe" in cmd
        assert "-overwrite" in cmd
        assert "-analysisTimeoutPerFile" in cmd
        assert cmd[cmd.index("-analysisTimeoutPerFile") + 1] == "300"

    def test_headless_path_uses_support_dir(self, tmp_path) -> None:
        home = str(tmp_path / "ghidra")
        expected = (Path(home) / "support" / "analyzeHeadless.bat").as_posix()
        assert str(rp.analyze_headless_path(home)).replace("\\", "/") == expected


class TestSplitForwarded:
    def test_dash_space_form(self) -> None:
        assert rp.split_forwarded(["--key", "value"]) == [("key", "value")]

    def test_dash_equals_form(self) -> None:
        assert rp.split_forwarded(["--key=value"]) == [("key", "value")]

    def test_bare_flag(self) -> None:
        assert rp.split_forwarded(["--decompile"]) == [("decompile", "true")]

    def test_mixed(self) -> None:
        assert rp.split_forwarded(["--a", "1", "--b=2", "--c"]) == [
            ("a", "1"), ("b", "2"), ("c", "true"),
        ]


# ---------------------------------------------------------------------------
# Wrapper: GHIDRA_HOME resolution
# ---------------------------------------------------------------------------

class TestResolveGhidraHome:
    def test_cli_wins(self, tmp: Path) -> None:
        cli = str(tmp / "cli-home")
        env = str(tmp / "env-home")
        assert rp.resolve_ghidra_home(tmp, cli, {"GHIDRA_HOME": env}) == cli

    def test_env_when_no_cli(self, tmp: Path) -> None:
        env = str(tmp / "env-home")
        assert rp.resolve_ghidra_home(tmp, None, {"GHIDRA_HOME": env}) == env

    def test_analysis_state_when_no_cli_env(self, tmp: Path) -> None:
        home = str(tmp / "ws-ghidra")
        (tmp / "analysis_state.txt").write_text(
            f"# state\nghidra_home={home}\nvenv=x\n", encoding="utf-8")
        assert rp.resolve_ghidra_home(tmp, None, {}) == home

    def test_none_when_all_missing(self, tmp: Path) -> None:
        assert rp.resolve_ghidra_home(tmp, None, {}) is None

    def test_parse_analysis_state_skips_comments(self, tmp: Path) -> None:
        (tmp / "analysis_state.txt").write_text(
            "# comment\nvenv=x\nghidra_home = spaced  \n", encoding="utf-8")
        state = rp.parse_analysis_state(tmp)
        assert state["ghidra_home"] == "spaced"
        assert state["venv"] == "x"
        assert "comment" not in state


# ---------------------------------------------------------------------------
# Wrapper: CLI exit codes
# ---------------------------------------------------------------------------

class TestCliExitCodes:
    def test_ghidra_home_missing_exit_2(self, tmp: Path, capsys) -> None:
        rc = rp.main(["--tool", "ghidra-recon", "--binary", "s.exe",
                      "--workspace", str(tmp)], environ={})
        assert rc == 2
        err = capsys.readouterr().err
        assert "GHIDRA_HOME" in err
        assert "exit 2" in err or "re-run" in err or "Provide" in err

    def test_analyze_headless_missing_exit_2(self, tmp: Path, capsys) -> None:
        ghidra_home = tmp / "ghidra"
        (ghidra_home / "support").mkdir(parents=True)  # no analyzeHeadless.bat
        rc = rp.main(["--tool", "ghidra-recon", "--binary", "s.exe",
                      "--workspace", str(tmp), "--ghidra-home", str(ghidra_home)],
                     environ={})
        assert rc == 2
        assert "analyzeHeadless" in capsys.readouterr().err

    def test_binary_missing_exit_2(self, tmp: Path, capsys) -> None:
        ghidra_home = tmp / "ghidra"
        (ghidra_home / "support").mkdir(parents=True)
        (ghidra_home / "support" / "analyzeHeadless.bat").write_text(
            "@echo off\n", encoding="utf-8")
        rc = rp.main(["--tool", "ghidra-recon", "--binary", str(tmp / "nope.exe"),
                      "--workspace", str(tmp), "--ghidra-home", str(ghidra_home)],
                     environ={})
        assert rc == 2
        assert "not found" in capsys.readouterr().err

    def test_invalid_tool_exit_2(self, tmp: Path) -> None:
        with pytest.raises(SystemExit) as excinfo:
            rp.main(["--tool", "bogus", "--binary", "s.exe",
                     "--workspace", str(tmp)], environ={})
        assert excinfo.value.code == 2

    def test_analysis_state_resolves_ghidra_home(self, tmp: Path, capsys,
                                                 monkeypatch) -> None:
        ghidra_home = tmp / "ghidra"
        (ghidra_home / "support").mkdir(parents=True)
        (ghidra_home / "support" / "analyzeHeadless.bat").write_text(
            "@echo off\n", encoding="utf-8")
        (tmp / "analysis_state.txt").write_text(
            f"ghidra_home={ghidra_home}\n", encoding="utf-8")
        binary = tmp / "sample.exe"
        binary.write_bytes(b"MZ")

        captured: dict = {}

        def fake_run(cmd, **kwargs):
            captured["cmd"] = list(cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        rc = rp.main(["--tool", "ghidra-recon", "--binary", str(binary),
                      "--workspace", str(tmp)], environ={})
        assert rc == 0
        assert captured["cmd"][0] == str(ghidra_home / "support" / "analyzeHeadless.bat")

    def test_valid_run_collects_out_artifact(self, tmp: Path, capsys,
                                             monkeypatch) -> None:
        ghidra_home = tmp / "ghidra"
        (ghidra_home / "support").mkdir(parents=True)
        (ghidra_home / "support" / "analyzeHeadless.bat").write_text(
            "@echo off\n", encoding="utf-8")
        binary = tmp / "sample.exe"
        binary.write_bytes(b"MZ")
        out = tmp / "deep" / "recon.json"

        def fake_run(cmd, **kwargs):
            for arg in cmd:
                if arg.startswith("--out="):
                    Path(arg[len("--out="):]).write_text("{}", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        monkeypatch.setattr("subprocess.run", fake_run)
        rc = rp.main(["--tool", "ghidra-recon", "--binary", str(binary),
                      "--out", str(out), "--ghidra-home", str(ghidra_home),
                      "--search-terms", "http", "--expected-exports", "ExportA"],
                     environ={})
        assert rc == 0
        assert out.is_file()
        captured = capsys.readouterr()
        assert "artifact:" in captured.out


# ---------------------------------------------------------------------------
# Java sources: parameterization / no hardcoded sample data
# ---------------------------------------------------------------------------

class TestJavaParameterization:
    def test_all_java_files_present(self) -> None:
        base = JAVA_DIR / "GhidraJsonScript.java"
        assert base.is_file()
        for java in _tool_java_files():
            assert java.is_file()

    def test_no_forbidden_sample_markers(self) -> None:
        for java in sorted(JAVA_DIR.glob("*.java")):
            text = java.read_text(encoding="utf-8")
            hits = [m for m in FORBIDDEN_MARKERS if m.lower() in text.lower()]
            assert not hits, f"{java.name} contains sample-specific markers: {hits}"

    def test_no_jython_runtime_annotation(self) -> None:
        for java in sorted(JAVA_DIR.glob("*.java")):
            assert "@runtime Jython" not in java.read_text(encoding="utf-8")

    def test_base_class_is_abstract_and_shared(self) -> None:
        base = (JAVA_DIR / "GhidraJsonScript.java").read_text(encoding="utf-8")
        assert "abstract class GhidraJsonScript extends GhidraScript" in base
        for key in ("\"schema\"", "\"program\"", "\"image_base\""):
            assert key in base, f"GhidraJsonScript missing {key} metadata key"
        for java in _tool_java_files():
            text = java.read_text(encoding="utf-8")
            assert "extends GhidraJsonScript" in text, f"{java.name} not using shared base"

    def test_each_tool_is_parameterized_and_json_output(self) -> None:
        for java in _tool_java_files():
            text = java.read_text(encoding="utf-8")
            assert "getArg(" in text or "startsWith(\"--\"" in text, \
                f"{java.name} missing --key=value parameterization"
            assert "writeJson(" in text, f"{java.name} missing JSON output (writeJson)"
            assert "meta(" in text, f"{java.name} missing schema metadata (meta)"

    def test_wrapper_has_no_hardcoded_install_path(self) -> None:
        text = _wrapper_text()
        assert "D:" + "/works" not in text
        assert "D:" + "\\works" not in text
        assert "ghidra_12" not in text
        # GHIDRA_HOME must be read dynamically, not baked in as a default.
        assert re.search(r"environ\.get\(\"GHIDRA_HOME\"\)", text)

    def test_five_tools_registered_in_index_yaml(self) -> None:
        import yaml
        index = yaml.safe_load((TOOLS / "_INDEX.yaml").read_text(encoding="utf-8"))
        names = [entry["name"] for entry in index["tools"]]
        for tool in TOOL_IDS:
            assert tool in names, f"{tool} not registered in tools/_INDEX.yaml"

    def test_ghidra_index_documents_all_five_tools(self) -> None:
        text = (TOOLS / "_index-ghidra.md").read_text(encoding="utf-8")
        for tool in TOOL_IDS:
            assert tool in text, f"{tool} missing from tools/_index-ghidra.md"
