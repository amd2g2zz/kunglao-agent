# -*- coding: utf-8 -*-
"""tests/test_bindiff.py — issue #308: tools/ghidra/ghidra_diff.py binary diff CLI.

Absorbed design (REA DiffSessionManager over Ghidra Version Tracking), re-implemented
for the kunglao CLI contract.  No real Ghidra instance is required: artifact slicing
(diff-summary / diff-list-functions / diff-function) is tested against hand-crafted
bindiff.v1 JSON, and the create/status/cancel/delete lifecycle is exercised with a
fake analyzeHeadless.bat.  The real-VT integration test is skipped (TODO follow-up).

Contract under test:
  - create/status/cancel/delete share the async job protocol (ghidra_job.JobStore)
  - diff-summary: match statistics from a bindiff.v1 artifact
  - diff-list-functions: categories identical/changed/added/removed
  - diff-function <addr>: lenses callees + bodyBytesChanged (always present for
    matched functions — the always-checked lens)
  - --base/--target dual-sample input, --json/--reproduce, exit 0/1/2
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GHIDRA_DIR = ROOT / "tools" / "ghidra"
CLI = GHIDRA_DIR / "ghidra_diff.py"
JOB_CLI = GHIDRA_DIR / "ghidra_job.py"

sys.path.insert(0, str(GHIDRA_DIR))
import ghidra_diff as bd  # noqa: E402

L1_LINE_RE = re.compile(r"^([A-Za-z_][\w.]*)\s*[:=]\s*(.+)$")


def run_cli(*args, env=None, timeout=60):
    e = dict(os.environ) if env is None else env
    e.pop("GHIDRA_HOME", None)
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True, text=True, timeout=timeout, env=e,
    )


def parse_reproduce(stdout):
    return dict(L1_LINE_RE.match(line).groups() for line in stdout.splitlines()
                if L1_LINE_RE.match(line))


def read_record(jobs_dir, job_id, retries=5):
    """Read a record with retries — os.replace + AV interference on Windows
    makes a bare read transiently fail (mirrors JobStore.get)."""
    path = jobs_dir / f"{job_id}.json"
    last = None
    for attempt in range(retries):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            last = exc
            time.sleep(0.1)
    raise last


def wait_terminal(jobs_dir, job_id, timeout=15.0, grace=0.2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = read_record(jobs_dir, job_id)
        if record["state"] in bd.TERMINAL_STATES:
            return record
        time.sleep(grace)
    raise AssertionError(f"job {job_id} never reached a terminal state: {record}")


# ---------------------------------------------------------------------------
# Fixtures: hand-crafted bindiff.v1 artifacts
# ---------------------------------------------------------------------------

def make_artifact() -> dict:
    """Two identical, one changed (body bytes + one callee swap), one added, one
    removed — the issue #308 acceptance scenario shape."""
    return {
        "schema": "bindiff.v1",
        "program": "target.exe",
        "base_program": "base.exe",
        "image_base": "0x140000000",
        "correlators": ["Exact Match Instructions",
                        "Combined Function and Data Reference"],
        "summary": {"identical": 2, "changed": 1, "added": 1, "removed": 1,
                    "matched": 3, "total_base": 4, "total_target": 4},
        "functions": [
            {"category": "identical",
             "base": {"address": "0x401000", "name": "FUN_00401000", "size": 12},
             "target": {"address": "0x501000", "name": "FUN_00501000", "size": 12},
             "similarity": 1.0, "confidence": 1.0,
             "lenses": {"body_bytes_changed": False, "callees_added": [],
                        "callees_removed": [], "callees_common": 1}},
            {"category": "identical",
             "base": {"address": "0x401050", "name": "FUN_00401050", "size": 8},
             "target": {"address": "0x501050", "name": "FUN_00501050", "size": 8},
             "similarity": 1.0, "confidence": 1.0,
             "lenses": {"body_bytes_changed": False, "callees_added": [],
                        "callees_removed": [], "callees_common": 0}},
            {"category": "changed",
             "base": {"address": "0x401100", "name": "FUN_00401100", "size": 40},
             "target": {"address": "0x501100", "name": "FUN_00501100", "size": 48},
             "similarity": 0.75, "confidence": 0.9,
             "lenses": {"body_bytes_changed": True,
                        "callees_added": ["0x501050 FUN_00501050"],
                        "callees_removed": ["0x401000 FUN_00401000"],
                        "callees_common": 1}},
            {"category": "added",
             "base": None,
             "target": {"address": "0x501200", "name": "FUN_00501200", "size": 8},
             "similarity": None, "confidence": None, "lenses": None},
            {"category": "removed",
             "base": {"address": "0x401300", "name": "FUN_00401300", "size": 8},
             "target": None,
             "similarity": None, "confidence": None, "lenses": None},
        ],
    }


def write_artifact(tmp_path, artifact=None, name="bindiff.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(artifact if artifact is not None else make_artifact()),
                 encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Command construction (pure)
# ---------------------------------------------------------------------------

class TestBuildBindiffCommand:
    def test_argv_shape(self, tmp_path):
        cmd = bd.build_bindiff_command(
            ghidra_home="D:/ghidra", base=Path("base.exe"), target=Path("target.exe"),
            out=Path("out.json"), script_path=GHIDRA_DIR,
            project_dir=tmp_path / "proj", project_name="proj",
        )
        assert cmd[0].replace("\\", "/") == "D:/ghidra/support/analyzeHeadless.bat"
        imports = [i for i, tok in enumerate(cmd) if tok == "-import"]
        assert len(imports) == 2
        first, second = imports
        assert cmd[first + 1] == "base.exe"
        assert cmd[second + 1] == "target.exe"
        assert "-overwrite" in cmd
        assert cmd[cmd.index("-postScript") + 1] == "GhidraBindiff.java"
        assert "--base=base.exe" in cmd and "--target=target.exe" in cmd
        assert f"--out={Path('out.json')}" in cmd
        assert cmd[cmd.index("-analysisTimeoutPerFile") + 1] == "300"
        idx = cmd.index("-scriptPath")
        assert Path(cmd[idx + 1]).is_absolute()

    def test_two_imports_present(self, tmp_path):
        cmd = bd.build_bindiff_command(
            ghidra_home="D:/ghidra", base=Path("b.exe"), target=Path("t.exe"),
            out=Path("o.json"), script_path=GHIDRA_DIR,
            project_dir=tmp_path / "proj", project_name="proj",
        )
        assert cmd.count("-import") == 2  # dual-sample input (--base/--target)

    def test_base_target_forward_program_names_not_paths(self, tmp_path):
        """DIFF-2: the Java guard compares currentProgram.getName() (never a
        path) and looks DomainFiles up by name — forwarding full paths makes
        the guard always false and the diff silently never runs."""
        base = Path("C:/samples/old/malware.v1.exe")
        target = Path("D:/captures/new/malware.v2.exe")
        cmd = bd.build_bindiff_command(
            ghidra_home="D:/ghidra", base=base, target=target,
            out=Path("o.json"), script_path=GHIDRA_DIR,
            project_dir=tmp_path / "proj", project_name="proj",
        )
        assert "--base=malware.v1.exe" in cmd
        assert "--target=malware.v2.exe" in cmd
        assert not any(a.startswith("--base=C:") for a in cmd)
        assert not any(a.startswith("--target=D:") for a in cmd)
        # -import keeps the full paths (analyzeHeadless needs them)
        assert str(base) in cmd and str(target) in cmd


# ---------------------------------------------------------------------------
# Artifact loading / validation (pure)
# ---------------------------------------------------------------------------

class TestLoadArtifact:
    def test_valid_artifact_loads(self, tmp_path):
        p = write_artifact(tmp_path)
        artifact = bd.load_artifact(p)
        assert artifact["schema"] == "bindiff.v1"
        assert len(artifact["functions"]) == 5

    def test_wrong_schema_raises_with_guidance(self, tmp_path):
        p = write_artifact(tmp_path, {"schema": "ghidra_recon.v1", "functions": []})
        with pytest.raises(bd.ArtifactError) as excinfo:
            bd.load_artifact(p)
        assert "bindiff.v1" in str(excinfo.value)
        assert "create" in str(excinfo.value)  # guidance points at ghidra-diff create

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(bd.ArtifactError):
            bd.load_artifact(tmp_path / "nope.json")

    def test_invalid_json_raises(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(bd.ArtifactError):
            bd.load_artifact(p)


# ---------------------------------------------------------------------------
# diff-summary
# ---------------------------------------------------------------------------

class TestDiffSummary:
    def test_json_matches_fixture(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-summary", "--artifact", str(p), "--json")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["tool"] == "ghidra-diff"
        assert data["summary"] == make_artifact()["summary"]
        assert data["program"] == "target.exe"
        assert data["base_program"] == "base.exe"

    def test_summary_counts_are_self_consistent(self, tmp_path):
        """M-4 pin: the greedy one-to-one match selection guarantees
        matched + added == total_target and matched + removed == total_base —
        no function may vanish from every category."""
        p = write_artifact(tmp_path)
        r = run_cli("diff-summary", "--artifact", str(p), "--json")
        data = json.loads(r.stdout)
        s = data["summary"]
        assert s["identical"] + s["changed"] == s["matched"]
        assert s["matched"] + s["added"] == s["total_target"]
        assert s["matched"] + s["removed"] == s["total_base"]
        listed = {"identical": 0, "changed": 0, "added": 0, "removed": 0}
        artifact = bd.load_artifact(p)
        for fn in artifact["functions"]:
            listed[fn["category"]] += 1
        assert listed == {k: s[k] for k in listed}

    def test_text_one_line_per_stat(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-summary", "--artifact", str(p))
        assert r.returncode == 0, r.stderr
        assert "identical=2" in r.stdout
        assert "changed=1" in r.stdout
        assert "added=1" in r.stdout
        assert "removed=1" in r.stdout

    def test_reproduce_fields(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-summary", "--artifact", str(p), "--reproduce")
        assert r.returncode == 0, r.stderr
        fields = parse_reproduce(r.stdout)
        assert fields["tool"] == "ghidra-diff"
        assert fields["action"] == "diff-summary"
        assert fields["identical"] == "2"
        assert fields["changed"] == "1"
        assert fields["added"] == "1"
        assert fields["removed"] == "1"
        assert fields["matched"] == "3"

    def test_missing_artifact_exit_2(self, tmp_path):
        r = run_cli("diff-summary", "--artifact", str(tmp_path / "nope.json"))
        assert r.returncode == 2
        err = json.loads(r.stderr)
        assert err["exit_code"] == 2


# ---------------------------------------------------------------------------
# diff-list-functions
# ---------------------------------------------------------------------------

class TestDiffListFunctions:
    def test_all_categories_default(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-list-functions", "--artifact", str(p), "--json")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["count"] == 5
        assert {f["category"] for f in data["functions"]} == \
            {"identical", "changed", "added", "removed"}

    def test_category_filter_changed(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-list-functions", "--artifact", str(p),
                    "--category", "changed", "--json")
        data = json.loads(r.stdout)
        assert data["count"] == 1
        fn = data["functions"][0]
        assert fn["category"] == "changed"
        assert fn["base"]["address"] == "0x401100"
        assert fn["target"]["address"] == "0x501100"
        assert fn["similarity"] == 0.75

    def test_category_filter_removed_has_null_target(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-list-functions", "--artifact", str(p),
                    "--category", "removed", "--json")
        data = json.loads(r.stdout)
        assert data["count"] == 1
        assert data["functions"][0]["base"]["address"] == "0x401300"
        assert data["functions"][0]["target"] is None

    def test_empty_category_exit_1_negative(self, tmp_path):
        artifact = make_artifact()
        artifact["functions"] = [f for f in artifact["functions"]
                                 if f["category"] != "added"]
        p = write_artifact(tmp_path, artifact)
        r = run_cli("diff-list-functions", "--artifact", str(p),
                    "--category", "added", "--json")
        assert r.returncode == 1
        data = json.loads(r.stdout)
        assert data["status"] == "NEGATIVE"
        assert data["count"] == 0

    def test_invalid_category_exit_2(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-list-functions", "--artifact", str(p),
                    "--category", "bogus")
        assert r.returncode == 2


# ---------------------------------------------------------------------------
# diff-function + lenses
# ---------------------------------------------------------------------------

class TestDiffFunction:
    def test_changed_function_lenses(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-function", "0x501100", "--artifact", str(p), "--json")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["query_addr"] == "0x501100"
        assert data["category"] == "changed"
        lenses = data["lenses"]
        assert lenses["body_bytes_changed"] is True   # always-checked lens always present
        assert "FUN_00501050" in lenses["callees_added"][0]
        assert "FUN_00401000" in lenses["callees_removed"][0]
        assert lenses["callees_common"] == 1
        assert data["base"]["address"] == "0x401100"
        assert data["similarity"] == 0.75

    def test_identical_function_body_unchanged(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-function", "0x501000", "--artifact", str(p), "--json")
        data = json.loads(r.stdout)
        assert data["category"] == "identical"
        assert data["lenses"]["body_bytes_changed"] is False
        assert data["lenses"]["callees_added"] == []

    def test_base_side_lookup(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-function", "0x401100", "--side", "base",
                    "--artifact", str(p), "--json")
        data = json.loads(r.stdout)
        assert data["category"] == "changed"

    def test_added_function_lookup(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-function", "0x501200", "--artifact", str(p), "--json")
        data = json.loads(r.stdout)
        assert data["category"] == "added"
        assert data["base"] is None

    def test_unknown_addr_exit_1_negative(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-function", "0xdead", "--artifact", str(p), "--json")
        assert r.returncode == 1
        data = json.loads(r.stdout)
        assert data["status"] == "NEGATIVE"

    def test_bad_addr_exit_2(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-function", "not-an-addr", "--artifact", str(p))
        assert r.returncode == 2
        assert json.loads(r.stderr)["exit_code"] == 2

    def test_reproduce_fields(self, tmp_path):
        p = write_artifact(tmp_path)
        r = run_cli("diff-function", "0x501100", "--artifact", str(p), "--reproduce")
        assert r.returncode == 0
        fields = parse_reproduce(r.stdout)
        assert fields["tool"] == "ghidra-diff"
        assert fields["action"] == "diff-function"
        assert fields["category"] == "changed"
        assert fields["body_bytes_changed"] == "true"
        assert fields["callees_common"] == "1"


# ---------------------------------------------------------------------------
# create/status/cancel/delete lifecycle (fake analyzeHeadless.bat, no real Ghidra)
# ---------------------------------------------------------------------------

FAKE_WRITER_BAT = (
    # cmd splits --key=value at '=' — the batch receives `--out` and the path
    # as TWO args (the real GhidraJsonScript.getArg handles both forms).
    "@echo off\r\n"
    "setlocal enabledelayedexpansion\r\n"
    "set OUT=\r\n"
    ":parse\r\n"
    "if [%~1]==[] goto run\r\n"
    'if [%~1]==[--out] set "OUT=%~2"\r\n'
    "shift\r\n"
    "goto parse\r\n"
    ":run\r\n"
    "if not defined OUT exit /b 0\r\n"
    'echo {}> "!OUT!"\r\n'
    "exit /b 0\r\n"
)

FAKE_WRITER_SH = (
    # POSIX twin of FAKE_WRITER_BAT: parse --out <path>, write {} there.
    # Handles both --out=PATH (POSIX exec passes the token whole) and
    # `--out PATH` two-token form (kept for parity with the batch parser).
    "#!/bin/sh\n"
    "out=\n"
    "while [ $# -gt 0 ]; do\n"
    "  case \"$1\" in\n"
    "    --out=*) out=${1#--out=}; shift ;;\n"
    "    --out) out=$2; shift 2 ;;\n"
    "    *) shift ;;\n"
    "  esac\n"
    "done\n"
    "if [ -n \"$out\" ]; then printf '{}\\n' > \"$out\"; fi\n"
    "exit 0\n"
)

FAKE_LOOP_BAT = (
    "@echo off\r\n"
    ":loop\r\n"
    "timeout /t 1 >nul\r\n"
    "goto loop\r\n"
)

FAKE_LOOP_SH = (
    # POSIX twin of FAKE_LOOP_BAT: sleep forever until cancelled.
    "#!/bin/sh\n"
    "while true; do sleep 1; done\n"
)


def make_fake_ghidra(tmp_path, bat_text=FAKE_WRITER_BAT,
                     sh_text=FAKE_WRITER_SH) -> Path:
    """Fake Ghidra install with a platform-runnable analyzeHeadless.

    analyze_headless_path() prefers analyzeHeadless.bat when present, but a
    .bat cannot execute on POSIX — write the platform-appropriate script
    (extensionless + chmod 0o755 on POSIX) so the job completes (writer) or
    loops (loop) identically on both platforms.
    """
    ghidra = tmp_path / "ghidra"
    (ghidra / "support").mkdir(parents=True)
    if os.name == "nt":
        (ghidra / "support" / "analyzeHeadless.bat").write_text(bat_text, encoding="utf-8")
    else:
        sh = ghidra / "support" / "analyzeHeadless"
        sh.write_text(sh_text, encoding="utf-8")
        sh.chmod(0o755)
    return ghidra


class TestDiffJobLifecycle:
    def test_create_missing_ghidra_home_exit_2(self, tmp_path):
        base = tmp_path / "base.exe"
        target = tmp_path / "target.exe"
        base.write_bytes(b"MZ")
        target.write_bytes(b"MZ")
        r = run_cli("create", "--base", str(base), "--target", str(target),
                    "--jobs-dir", str(tmp_path), "--workspace", str(tmp_path))
        assert r.returncode == 2
        assert "GHIDRA_HOME" in r.stderr

    def test_create_same_filename_exit_2(self, tmp_path):
        ghidra = make_fake_ghidra(tmp_path)
        a = tmp_path / "same.exe"
        a.write_bytes(b"MZ")
        r = run_cli("create", "--base", str(a), "--target", str(a),
                    "--ghidra-home", str(ghidra), "--jobs-dir", str(tmp_path))
        assert r.returncode == 2
        assert "same filename" in r.stderr or "filename" in r.stderr

    def test_create_missing_binary_exit_2(self, tmp_path):
        ghidra = make_fake_ghidra(tmp_path)
        r = run_cli("create", "--base", str(tmp_path / "b.exe"),
                    "--target", str(tmp_path / "t.exe"),
                    "--ghidra-home", str(ghidra), "--jobs-dir", str(tmp_path))
        assert r.returncode == 2

    def test_create_to_completed_then_summary_rejects_bad_artifact(self, tmp_path):
        """End-to-end async flow with a fake headless: create -> poll completed ->
        artifact_exists -> diff-summary --job fails 2 (artifact is {} — not
        bindiff.v1) with structured guidance."""
        ghidra = make_fake_ghidra(tmp_path)
        base = tmp_path / "base.exe"
        target = tmp_path / "target.exe"
        base.write_bytes(b"MZ")
        target.write_bytes(b"MZ")
        r = run_cli("create", "--base", str(base), "--target", str(target),
                    "--ghidra-home", str(ghidra), "--jobs-dir", str(tmp_path),
                    "--json")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        job_id = data["job_id"]
        assert data["kind"] == "ghidra-bindiff"
        record = wait_terminal(tmp_path, job_id)
        assert record["state"] == "completed"
        assert record["exit_code"] == 0
        assert record["artifact"] and Path(record["artifact"]).is_file()

        r2 = run_cli("diff-summary", "--job", job_id, "--jobs-dir", str(tmp_path))
        assert r2.returncode == 2
        err = json.loads(r2.stderr)
        assert "bindiff.v1" in err["error"]

    def test_create_cancel_delete(self, tmp_path):
        ghidra = make_fake_ghidra(tmp_path, FAKE_LOOP_BAT)
        base = tmp_path / "base.exe"
        target = tmp_path / "target.exe"
        base.write_bytes(b"MZ")
        target.write_bytes(b"MZ")
        r = run_cli("create", "--base", str(base), "--target", str(target),
                    "--ghidra-home", str(ghidra), "--jobs-dir", str(tmp_path))
        job_id = r.stdout.strip().split("=", 1)[1]
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if read_record(tmp_path, job_id)["state"] in ("started", "running"):
                break
            time.sleep(0.2)
        c = run_cli("cancel", job_id, "--jobs-dir", str(tmp_path), "--json")
        assert c.returncode == 0, c.stderr
        # contract: terminal state (cancelled, or the rare runner-finished-first
        # interleaving), then idempotent no-op on the second cancel
        assert json.loads(c.stdout)["state"] in bd.TERMINAL_STATES
        c2 = run_cli("cancel", job_id, "--jobs-dir", str(tmp_path))
        assert c2.returncode == 0  # idempotent no-op on terminal jobs
        d = run_cli("delete", job_id, "--jobs-dir", str(tmp_path), "--json")
        assert d.returncode == 0
        assert json.loads(d.stdout)["removed"] == 1
        assert run_cli("status", job_id, "--jobs-dir", str(tmp_path)).returncode == 2

    def test_status_reports_bindiff_kind(self, tmp_path):
        ghidra = make_fake_ghidra(tmp_path, FAKE_LOOP_BAT)
        base = tmp_path / "base.exe"
        target = tmp_path / "target.exe"
        base.write_bytes(b"MZ")
        target.write_bytes(b"MZ")
        r = run_cli("create", "--base", str(base), "--target", str(target),
                    "--ghidra-home", str(ghidra), "--jobs-dir", str(tmp_path))
        job_id = r.stdout.strip().split("=", 1)[1]
        s = run_cli("status", job_id, "--jobs-dir", str(tmp_path), "--json")
        assert s.returncode == 0
        data = json.loads(s.stdout)
        assert data["kind"] == "ghidra-bindiff"
        assert any("GhidraBindiff.java" in tok for tok in data["command"])
        assert run_cli("cancel", job_id,
                       "--jobs-dir", str(tmp_path)).returncode == 0


# ---------------------------------------------------------------------------
# help surface
# ---------------------------------------------------------------------------

class TestHelp:
    @pytest.mark.parametrize("sub", [
        "create", "status", "cancel", "delete",
        "diff-summary", "diff-list-functions", "diff-function",
    ])
    def test_help_exit_zero(self, sub):
        r = run_cli(sub, "--help")
        assert r.returncode == 0, r.stderr
        assert "usage" in r.stdout.lower()


# ---------------------------------------------------------------------------
# Java postScript structural contract (mirrors tests/test_ghidra_tools.py style)
# ---------------------------------------------------------------------------

FORBIDDEN_MARKERS = (
    "browser_host", "mongoose", "mg_", "executecsharp",
    "a20603688b76a7c83918309ab373ca39", "ca.fpe-time.com", "fpe-time",
    "snail007", "271ebfab8606ca68137cb9573c563713e6bf8613736722aabe535ccc06bc8346",
    "22e6f41209a831bc647fbdaa29add029ba493bd2",
    "hvnc_start_process_injected", "0x1403809a0", "0x14031b240",
    "0x140633c40", "0x1405feefc", "0x14060e95d",
    "D:/works", "D:\\works", "C:/x", "_ghidra_workspace",
)


class TestJavaPostScript:
    @pytest.fixture(scope="class")
    def java(self) -> Path:
        p = GHIDRA_DIR / "GhidraBindiff.java"
        assert p.is_file(), "GhidraBindiff.java missing"
        return p

    @pytest.fixture(scope="class")
    def text(self, java) -> str:
        return java.read_text(encoding="utf-8")

    def test_extends_shared_base_and_uses_contract(self, text):
        assert "extends GhidraJsonScript" in text
        assert "getArg(" in text
        assert "writeJson(" in text
        assert 'meta("bindiff.v1"' in text

    def test_uses_version_tracking_api(self, text):
        # Tokens verified against Ghidra 12.1.2 jars via javap (review
        # DIFF-1): correlate() RETURNS the VTMatchSet (no session.getMatchSet),
        # createCorrelator takes (Program, AddressSetView, Program,
        # AddressSetView, VTOptions), programs open via getImmutableDomainObject.
        for token in ("VTSessionDB", "VTProgramCorrelatorFactory",
                      "ExactMatchInstructionsProgramCorrelatorFactory",
                      "createDefaultOptions", "createCorrelator",
                      ".correlate(session, getMonitor())",
                      "getImmutableDomainObject", "getMatches()",
                      "session.release(consumer)"):
            assert token in text, f"missing VT API token {token}"
        # the 7 confirmed-wrong APIs must never come back (call forms — the
        # header comments document them, so bare names would false-positive)
        for wrong in (".getMatchSet(", "new VTProgramCorrelatorInfo(",
                      ".createVTSession(", ".getSourceAddress().getAddress()",
                      "session.dispose()",
                      "new ProgramDB(baseFile"):
            assert wrong not in text, f"known-wrong API reappeared: {wrong}"

    def test_compiles_against_real_ghidra_jars(self, java, tmp_path):
        """Mechanical DIFF-1 gate: compile GhidraBindiff (with its shared
        base) against the real jars under GHIDRA_HOME.  Skips when no Ghidra
        install / javac is available."""
        ghidra_home = os.environ.get("GHIDRA_HOME")
        if not ghidra_home or not Path(ghidra_home).is_dir():
            pytest.skip("GHIDRA_HOME not set — real-jar compile gate skipped")
        javac = shutil.which("javac")
        if javac is None:
            pytest.skip("no javac on PATH — real-jar compile gate skipped")
        jars = [str(p) for p in sorted(Path(ghidra_home).rglob("*.jar"))]
        assert jars, f"no jars under {ghidra_home}"
        cp = os.pathsep.join(jars)
        r = subprocess.run(
            [javac, "-encoding", "UTF-8", "-Xlint:-options,-removal",
             "-d", str(tmp_path), "-cp", cp,
             str(GHIDRA_DIR / "GhidraJsonScript.java"), str(java)],
            capture_output=True, text=True, timeout=300,
        )
        assert r.returncode == 0, f"javac failed:\n{r.stderr[-3000:]}"
        assert (tmp_path / "GhidraBindiff.class").is_file()

    def test_computes_lenses(self, text):
        assert "body_bytes_changed" in text
        assert "callees_added" in text
        assert "callees_removed" in text

    def test_no_forbidden_sample_markers(self, text):
        hits = [m for m in FORBIDDEN_MARKERS if m.lower() in text.lower()]
        assert not hits, f"sample-specific markers: {hits}"

    def test_no_jython_runtime_annotation(self, text):
        assert "@runtime Jython" not in text

    def test_no_hardcoded_absolute_paths(self, text):
        for marker in ("D:/", "D:\\", "C:/Users", "C:\\Users"):
            assert marker not in text, f"hardcoded path marker: {marker}"


# ---------------------------------------------------------------------------
# Real-Ghidra integration (TODO follow-up: needs a live Ghidra install + two
# known-difference sample PEs; run manually or in a VM-backed CI lane)
# ---------------------------------------------------------------------------

class TestRealGhidraIntegration:
    @pytest.mark.skip(reason="TODO(#308): needs real Ghidra install + sample PE "
                             "pair — run manually with GHIDRA_HOME set; verifies "
                             "VT correlator output lands in a valid bindiff.v1 "
                             "artifact")
    def test_full_vt_run_produces_bindiff_artifact(self):
        ghidra_home = os.environ.get("GHIDRA_HOME", "D:/ghidra_12.1.2_PUBLIC")
        if not (Path(ghidra_home) / "support" / "analyzeHeadless.bat").is_file():
            pytest.skip("no real Ghidra install")
        # TODO: build base/target sample PEs with 1 changed function body + 1
        # changed call, then run create + diff-summary + diff-function and
        # assert summary classification and bodyBytesChanged=true.
        raise NotImplementedError("TODO(#308) real-VT acceptance run")
