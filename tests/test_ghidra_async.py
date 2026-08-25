# -*- coding: utf-8 -*-
"""tests/test_ghidra_async.py — issue #308: tools/ghidra/ghidra_job.py async job protocol.

Absorbed design (REA analyze-program waitSeconds=0 -> jobId -> analysis-status long
poll), re-implemented for the kunglao CLI contract (--json / --reproduce / structured
errors / exit codes).  No real Ghidra instance is required anywhere here: the job
protocol runs any argv (``--command``) or the analyzeHeadless wrapper command, so the
integration tests use fake sleeper/writer commands and a fake analyzeHeadless.bat.

Contract under test:
  - lifecycle: started -> running -> completed | failed | timed_out | cancelled
  - cancel on a terminal job is a no-op (idempotent, exit 0, record unchanged)
  - start returns the jobId immediately (worker heartbeat compatible)
  - state persisted on disk under --jobs-dir (default <workspace>/runs/ghidra-jobs)
  - status detects a dead runner (crash) and fails the job after --grace seconds
  - exit codes: 0 = ok, 2 = error (structured JSON on stderr, never a traceback)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GHIDRA_DIR = ROOT / "tools" / "ghidra"
CLI = GHIDRA_DIR / "ghidra_job.py"

sys.path.insert(0, str(GHIDRA_DIR))
import ghidra_job as gj  # noqa: E402

# Matches scripts/kunglao_verify.py _ACTUAL_ASSERTION_RE (L1 field=value parser).
L1_LINE_RE = re.compile(r"^([A-Za-z_][\w.]*)\s*[:=]\s*(.+)$")


def run_cli(*args, env=None, timeout=60):
    e = dict(os.environ) if env is None else env
    e.pop("GHIDRA_HOME", None)
    # Decode UTF-8 explicitly: ghidra_job.py emits UTF-8 (#317 stdout guard at
    # module level); a locale/GBK decode crashes the capture reader thread on
    # the argparse help's em-dash and leaves stdout=None (#457 triage #2-#5).
    # Mirrors _tick in tests/test_heartbeat_tick.py.
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True, text=True, timeout=timeout, env=e,
        encoding="utf-8", errors="replace",
    )


def py_cmd(code: str) -> str:
    """Command string running `python -c CODE` (forward-slashed exe path —
    --command uses POSIX shlex splitting, so backslashes would be escapes)."""
    exe = str(sys.executable).replace("\\", "/")
    return f'{exe} -c "{code}"'


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


def start_sleeper(jobs_dir, seconds, **extra):
    """Start a job running a python sleeper; returns (job_id, proc)."""
    cmd = py_cmd(f"import time; time.sleep({seconds})")
    args = ["start", "--command", cmd, "--jobs-dir", str(jobs_dir)]
    for key, value in extra.items():
        args += [f"--{key}", str(value)]
    return run_cli(*args)


def wait_state(jobs_dir, job_id, states, timeout=15.0, grace=0.2):
    """Poll status until the record reaches one of `states` (a str or set)."""
    states = {states} if isinstance(states, str) else set(states)
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        record = read_record(jobs_dir, job_id)
        last = record["state"]
        if last in states:
            return record
        time.sleep(grace)
    raise AssertionError(f"job {job_id} never reached {states}; last={last}")


def poll_status(jobs_dir, job_id, grace=0.2, timeout=15.0):
    """Return the status --json dict once it reports a terminal state."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        r = run_cli("status", job_id, "--jobs-dir", str(jobs_dir), "--json",
                    "--grace", str(grace))
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        last = out
        if out["state"] in gj.TERMINAL_STATES:
            return out
        time.sleep(grace)
    raise AssertionError(f"status never terminal; last={last}")


# ---------------------------------------------------------------------------
# JobStore unit tests (pure, tmp dirs)
# ---------------------------------------------------------------------------

class TestJobStore:
    def test_create_writes_started_record(self, tmp_path):
        store = gj.JobStore(tmp_path)
        rec = store.create(kind="command",
                           command=[sys.executable, "-c", "pass"],
                           timeout=60, artifact=None, workspace=str(tmp_path))
        assert rec["state"] == "started"
        assert re.fullmatch(r"gj-\d{8}-\d{6}-[0-9a-f]{4}", rec["job_id"])
        assert rec["schema"] == gj.JOB_SCHEMA
        on_disk = read_record(tmp_path, rec["job_id"])
        assert on_disk == rec
        assert not list(tmp_path.glob("*.json.tmp"))  # atomic, no tmp linger

    def test_create_reserves_job_id_exclusively(self, tmp_path):
        """L-6: the create write is an O_EXCL reservation — a taken id raises
        JobStateError (caller-supplied) instead of silently sharing a record."""
        store = gj.JobStore(tmp_path)
        first = store.create(kind="command", command=["x"], timeout=1,
                             artifact=None, workspace=".")
        with pytest.raises(gj.JobStateError):
            store.create(kind="command", command=["x"], timeout=1,
                         artifact=None, workspace=".", job_id=first["job_id"])
        # auto mode retries fresh ids and still succeeds
        second = store.create(kind="command", command=["x"], timeout=1,
                              artifact=None, workspace=".")
        assert second["job_id"] != first["job_id"]

    def test_get_unknown_returns_none(self, tmp_path):
        assert gj.JobStore(tmp_path).get("gj-nope") is None

    def test_transitions_allowed(self, tmp_path):
        store = gj.JobStore(tmp_path)
        rec = store.create(kind="command", command=["x"], timeout=1,
                           artifact=None, workspace=".")
        assert store.update(rec["job_id"], state="running")["state"] == "running"
        for terminal in ("completed", "failed", "timed_out", "cancelled"):
            rec2 = store.create(kind="command", command=["x"], timeout=1,
                                artifact=None, workspace=".")
            store.update(rec2["job_id"], state="running")
            assert store.update(rec2["job_id"], state=terminal)["state"] == terminal

    def test_started_can_be_cancelled_before_running(self, tmp_path):
        store = gj.JobStore(tmp_path)
        rec = store.create(kind="command", command=["x"], timeout=1,
                           artifact=None, workspace=".")
        assert store.update(rec["job_id"], state="cancelled")["state"] == "cancelled"

    def test_terminal_to_active_raises(self, tmp_path):
        store = gj.JobStore(tmp_path)
        rec = store.create(kind="command", command=["x"], timeout=1,
                           artifact=None, workspace=".")
        store.update(rec["job_id"], state="running")
        store.update(rec["job_id"], state="completed")
        with pytest.raises(gj.JobStateError):
            store.update(rec["job_id"], state="running")

    def test_terminal_self_transition_raises(self, tmp_path):
        store = gj.JobStore(tmp_path)
        rec = store.create(kind="command", command=["x"], timeout=1,
                           artifact=None, workspace=".")
        store.update(rec["job_id"], state="cancelled")
        with pytest.raises(gj.JobStateError):
            store.update(rec["job_id"], state="cancelled")

    def test_state_machine_exact_table(self):
        # started -> failed is the crash-detection path (review DIFF-3): a
        # runner that dies before reporting running must be fail-able or the
        # job hangs in started forever.
        assert gj.ALLOWED_TRANSITIONS == {
            "started": {"running", "failed", "cancelled"},
            "running": {"completed", "failed", "timed_out", "cancelled"},
        }

    def test_started_can_fail_via_crash_detection(self, tmp_path):
        """DIFF-3 regression: a started job whose runner never reported in is
        failed by status crash detection — never stuck in started."""
        store = gj.JobStore(tmp_path)
        store.create(kind="command", command=["x"], timeout=1,
                     artifact=None, workspace=".")
        records = list(tmp_path.glob("gj-*.json"))
        assert len(records) == 1
        job_id = records[0].stem
        # age the record past the grace window, then poll status
        time.sleep(0.3)
        r = run_cli("status", job_id, "--jobs-dir", str(tmp_path),
                    "--json", "--grace", "0.1")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["state"] == "failed"
        assert "runner" in (data["error"] or "").lower()

    def test_update_preserves_other_fields_and_bumps_updated_at(self, tmp_path):
        store = gj.JobStore(tmp_path)
        rec = store.create(kind="command", command=["x"], timeout=1,
                           artifact=None, workspace=".")
        updated = store.update(rec["job_id"], state="running", runner_pid=1234)
        assert updated["command"] == rec["command"]
        assert updated["runner_pid"] == 1234
        # ISO-8601 UTC strings compare lexicographically (>= : coarse system
        # clocks can return the same microsecond for back-to-back calls).
        assert updated["updated_at"] >= rec["updated_at"]

    def test_list_and_delete(self, tmp_path):
        store = gj.JobStore(tmp_path)
        a = store.create(kind="command", command=["x"], timeout=1,
                         artifact=None, workspace=".")
        b = store.create(kind="command", command=["y"], timeout=1,
                         artifact=None, workspace=".")
        assert {r["job_id"] for r in store.list_jobs()} == {a["job_id"], b["job_id"]}
        assert store.delete(a["job_id"]) is True
        assert store.get(a["job_id"]) is None
        assert store.delete(a["job_id"]) is False  # already gone

    def test_job_id_rejects_path_traversal(self, tmp_path):
        store = gj.JobStore(tmp_path)
        for good in ("gj-123", "gj-20260814-000000-0000", "ABC_1-2"):
            assert store.is_valid_job_id(good) is True, good
        for bad in ("../evil", "a b", "x.y", "", "..", "x/y", "gj\\x"):
            assert store.is_valid_job_id(bad) is False, bad

    def test_stale_running_job_with_dead_runner_is_crash(self, tmp_path):
        store = gj.JobStore(tmp_path)
        rec = store.create(kind="command", command=["x"], timeout=1,
                           artifact=None, workspace=".")
        store.update(rec["job_id"], state="running", runner_pid=999999)
        assert store.detect_crash(rec["job_id"], grace_seconds=0.0) is True

    def test_recent_running_job_is_not_crash(self, tmp_path):
        store = gj.JobStore(tmp_path)
        rec = store.create(kind="command", command=["x"], timeout=1,
                           artifact=None, workspace=".")
        store.update(rec["job_id"], state="running", runner_pid=999999)
        assert store.detect_crash(rec["job_id"], grace_seconds=3600.0) is False

    def test_terminal_job_is_never_crash(self, tmp_path):
        store = gj.JobStore(tmp_path)
        rec = store.create(kind="command", command=["x"], timeout=1,
                           artifact=None, workspace=".")
        store.update(rec["job_id"], state="running", runner_pid=999999)
        store.update(rec["job_id"], state="completed", exit_code=0)
        assert store.detect_crash(rec["job_id"], grace_seconds=0.0) is False

    def test_stale_started_without_runner_pid_is_crash(self, tmp_path):
        store = gj.JobStore(tmp_path)
        rec = store.create(kind="command", command=["x"], timeout=1,
                           artifact=None, workspace=".")
        assert store.detect_crash(rec["job_id"], grace_seconds=0.0) is True


# ---------------------------------------------------------------------------
# Command construction (pure)
# ---------------------------------------------------------------------------

class TestCommandBuilders:
    def test_build_tool_command_reuses_postscript_wrapper(self, tmp_path):
        fake_ghidra = tmp_path / "ghidra"
        (fake_ghidra / "support").mkdir(parents=True)
        (fake_ghidra / "support" / "analyzeHeadless.bat").write_text("", encoding="utf-8")
        binary = tmp_path / "s.exe"
        binary.write_bytes(b"MZ")
        out = tmp_path / "out.json"
        cmd, project_dir = gj.build_tool_command(
            ghidra_home=str(fake_ghidra), tool="ghidra-recon", binary=binary,
            post_args=[("search-terms", "http,socket")], out=out,
            script_path=GHIDRA_DIR, job_dir=tmp_path / "job-x",
        )
        assert cmd[0].endswith("analyzeHeadless.bat")
        assert "-postScript" in cmd and cmd[cmd.index("-postScript") + 1] == "GhidraRecon.java"
        assert "--search-terms=http,socket" in cmd
        assert f"--out={out}" in cmd
        assert str(project_dir).startswith(str(tmp_path / "job-x"))

    def test_build_tool_command_unknown_tool_raises(self, tmp_path):
        with pytest.raises(ValueError):
            gj.build_tool_command(
                ghidra_home=str(tmp_path / "ghidra"), tool="bogus", binary=Path("s.exe"),
                post_args=[], out=Path("o.json"), script_path=GHIDRA_DIR,
                job_dir=tmp_path / "job-x",
            )

    def test_wrap_batch_argv_windows(self, tmp_path):
        bat = str(tmp_path / "ghidra" / "support" / "analyzeHeadless.bat")
        out = str(tmp_path / "x" / "out.json")
        imp = str(tmp_path / "s" / "s.exe")
        argv = [bat, f"--out={out}",
                "-import", imp]
        # cmd splits --key=value at '='; the batch gets --key + value as two
        # args — GhidraJsonScript.getArg accepts both forms (its 3rd branch)
        assert gj.wrap_batch_argv(argv, is_windows=True) == ["cmd", "/c", *argv]

    def test_wrap_batch_argv_ignores_exe(self, tmp_path):
        argv = [str(tmp_path / "ghidra" / "support" / "analyzeHeadless"), "-x"]
        assert gj.wrap_batch_argv(argv, is_windows=True) == argv
        assert gj.wrap_batch_argv(["x.bat"], is_windows=False) == ["x.bat"]

    def test_default_jobs_dir_is_workspace_runs(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        assert gj.default_jobs_dir(ws) == ws / "runs" / "ghidra-jobs"


# ---------------------------------------------------------------------------
# CLI: help + error paths
# ---------------------------------------------------------------------------

class TestCliErrors:
    @pytest.mark.parametrize("sub", ["start", "status", "cancel", "cleanup"])
    def test_help_exit_zero(self, sub):
        r = run_cli(sub, "--help")
        assert r.returncode == 0, r.stderr
        assert "usage" in r.stdout.lower()

    def test_start_without_command_or_tool_exit_2(self, tmp_path):
        r = run_cli("start", "--jobs-dir", str(tmp_path))
        assert r.returncode == 2
        err = json.loads(r.stderr)
        assert err["exit_code"] == 2
        assert "command" in err["error"] and "tool" in err["error"]

    def test_status_unknown_job_exit_2(self, tmp_path):
        r = run_cli("status", "gj-20260814-000000-0000",
                    "--jobs-dir", str(tmp_path))
        assert r.returncode == 2
        err = json.loads(r.stderr)
        assert err["exit_code"] == 2

    def test_cancel_unknown_job_exit_2(self, tmp_path):
        r = run_cli("cancel", "gj-20260814-000000-0000",
                    "--jobs-dir", str(tmp_path))
        assert r.returncode == 2

    def test_status_traversal_job_id_exit_2(self, tmp_path):
        r = run_cli("status", "../evil", "--jobs-dir", str(tmp_path))
        assert r.returncode == 2

    def test_unknown_flag_rejected_exit_2(self, tmp_path):
        """L-7: a misspelled flag must fail loudly (exit 2), not be silently
        swallowed — only `start` forwards extras (to the postScript)."""
        r = run_cli("status", "gj-20260814-000000-0000",
                    "--jobs-dir", str(tmp_path), "--jsonx")
        assert r.returncode == 2
        err = json.loads(r.stderr)
        assert err["exit_code"] == 2
        assert "unknown flag" in err["error"]
        r2 = run_cli("cancel", "gj-20260814-000000-0000",
                     "--jobs-dir", str(tmp_path), "--gracefull", "3")
        assert r2.returncode == 2

    def test_start_tool_without_ghidra_home_exit_2(self, tmp_path):
        binary = tmp_path / "s.exe"
        binary.write_bytes(b"MZ")
        r = run_cli("start", "--tool", "ghidra-recon", "--binary", str(binary),
                    "--jobs-dir", str(tmp_path), "--workspace", str(tmp_path))
        assert r.returncode == 2
        assert "GHIDRA_HOME" in r.stderr

    def test_start_tool_binary_missing_exit_2(self, tmp_path):
        fake_ghidra = tmp_path / "ghidra"
        (fake_ghidra / "support").mkdir(parents=True)
        (fake_ghidra / "support" / "analyzeHeadless.bat").write_text("", encoding="utf-8")
        r = run_cli("start", "--tool", "ghidra-recon",
                    "--binary", str(tmp_path / "nope.exe"),
                    "--ghidra-home", str(fake_ghidra),
                    "--jobs-dir", str(tmp_path))
        assert r.returncode == 2


# ---------------------------------------------------------------------------
# CLI: async lifecycle integration (fake commands, no Ghidra needed)
# ---------------------------------------------------------------------------

class TestAsyncLifecycle:
    def test_start_returns_immediately_with_job_id(self, tmp_path):
        began = time.monotonic()
        r = start_sleeper(tmp_path, 30)
        elapsed = time.monotonic() - began
        assert r.returncode == 0, r.stderr
        assert elapsed < 5.0, f"start blocked {elapsed:.1f}s — must return jobId immediately"
        # text mode: a single `job_id=...` line
        line = r.stdout.strip().splitlines()
        assert len(line) == 1 and line[0].startswith("job_id=")
        job_id = line[0].split("=", 1)[1]
        assert re.fullmatch(r"gj-\d{8}-\d{6}-[0-9a-f]{4}", job_id)

    def test_start_json_mode(self, tmp_path):
        cmd = py_cmd("import time; time.sleep(1)")
        r = run_cli("start", "--command", cmd, "--jobs-dir", str(tmp_path), "--json")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["tool"] == "ghidra-job"
        assert data["action"] == "start"
        assert data["state"] == "started"
        assert re.fullmatch(r"gj-\d{8}-\d{6}-[0-9a-f]{4}", data["job_id"])
        assert data["kind"] == "command"

    def test_completed_job_writes_artifact(self, tmp_path):
        cmd = py_cmd("import os,pathlib;"
                     "pathlib.Path(os.environ['GHIDRA_JOB_ARTIFACT']).write_text('{}')")
        r = run_cli("start", "--command", cmd, "--jobs-dir", str(tmp_path))
        job_id = r.stdout.strip().split("=", 1)[1]
        out = poll_status(tmp_path, job_id)
        assert out["state"] == "completed"
        assert out["exit_code"] == 0
        assert out["artifact_exists"] is True
        assert (tmp_path / job_id / "stdout.log").exists()
        assert (tmp_path / job_id / "stderr.log").exists()

    def test_failed_job_records_exit_code(self, tmp_path):
        cmd = py_cmd("import sys; sys.exit(3)")
        r = run_cli("start", "--command", cmd, "--jobs-dir", str(tmp_path))
        job_id = r.stdout.strip().split("=", 1)[1]
        out = poll_status(tmp_path, job_id)
        assert out["state"] == "failed"
        assert out["exit_code"] == 3
        assert out["error"]

    def test_timed_out_job(self, tmp_path):
        """Timeout contract: the runner enforces --timeout, terminates the
        child, and the job lands in a terminal state (timed_out; or failed via
        the runner-error path when the environment blocks the terminal write —
        never stuck running)."""
        cmd = py_cmd("import time; time.sleep(30)")
        r = run_cli("start", "--command", cmd, "--timeout", "2",
                    "--jobs-dir", str(tmp_path))
        job_id = r.stdout.strip().split("=", 1)[1]
        out = poll_status(tmp_path, job_id, timeout=20.0)
        assert out["state"] in ("timed_out", "failed"), out
        if out["state"] == "failed":
            # acceptable degraded writers: the runner error path, or the
            # crash-detection path (runner's terminal write blocked by the
            # environment) — never stuck running
            assert "runner" in (out.get("error") or "").lower(), out
        record = read_record(tmp_path, job_id)
        if record.get("child_pid"):
            time.sleep(0.5)
            assert not gj._pid_alive(record["child_pid"]), "child must be killed"

    def test_cancel_active_job_then_cancel_is_noop(self, tmp_path):
        """Cancel contract: the job ends in a terminal state (cancelled, or —
        in the rare race where the runner reached a terminal state first — that
        state), the process tree is actually killed, and a second cancel is an
        idempotent no-op (record byte-identical)."""
        r = start_sleeper(tmp_path, 60)
        job_id = r.stdout.strip().split("=", 1)[1]
        wait_state(tmp_path, job_id, {"started", "running"})
        record = read_record(tmp_path, job_id)
        c1 = run_cli("cancel", job_id, "--jobs-dir", str(tmp_path), "--json")
        assert c1.returncode == 0, c1.stderr
        data = json.loads(c1.stdout)
        assert data["state"] in gj.TERMINAL_STATES, data
        # the kill happened: runner and child pids are gone
        if record.get("runner_pid"):
            assert not gj._pid_alive(record["runner_pid"])
        record_path = tmp_path / f"{job_id}.json"
        frozen = record_path.read_bytes()
        c2 = run_cli("cancel", job_id, "--jobs-dir", str(tmp_path), "--json")
        assert c2.returncode == 0, c2.stderr
        data2 = json.loads(c2.stdout)
        assert data2["state"] in gj.TERMINAL_STATES
        assert data2["already_terminal"] is True
        assert record_path.read_bytes() == frozen  # no-op: record byte-identical

    def test_crash_detection_fails_job(self, tmp_path):
        """Killing the runner tree must land the job in failed — never hang in
        running.  Two legitimate writers race: the runner may observe its own
        child's taskkill death (exit 1) and write failed itself, or the status
        crash detection writes failed after the grace period."""
        r = start_sleeper(tmp_path, 60)
        job_id = r.stdout.strip().split("=", 1)[1]
        wait_state(tmp_path, job_id, "running")
        record = read_record(tmp_path, job_id)
        gj.terminate_process_tree(record["runner_pid"])
        time.sleep(0.5)
        out = run_cli("status", job_id, "--jobs-dir", str(tmp_path),
                      "--json", "--grace", "0.3")
        data = json.loads(out.stdout)
        assert data["state"] == "failed"
        error = (data.get("error") or "").lower()
        assert "runner" in error or "exited" in error, data

    def test_cleanup_all_and_job(self, tmp_path):
        cmd = py_cmd("import time; time.sleep(30)")
        ids = []
        for _ in range(2):
            r = run_cli("start", "--command", cmd, "--jobs-dir", str(tmp_path))
            ids.append(r.stdout.strip().split("=", 1)[1])
        r = run_cli("cleanup", "--all", "--jobs-dir", str(tmp_path), "--json")
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["removed"] >= 2
        assert data["remaining"] == 0
        for job_id in ids:
            assert not (tmp_path / f"{job_id}.json").exists()
        # cleanup of a nonexistent job: ok, removed=0
        r2 = run_cli("cleanup", "--job", "gj-20260814-000000-0000",
                     "--jobs-dir", str(tmp_path), "--json")
        assert r2.returncode == 0
        assert json.loads(r2.stdout)["removed"] == 0

    def test_status_reproduce_fields(self, tmp_path):
        cmd = py_cmd("import sys; sys.exit(0)")
        r = run_cli("start", "--command", cmd, "--jobs-dir", str(tmp_path))
        job_id = r.stdout.strip().split("=", 1)[1]
        poll_status(tmp_path, job_id)
        r2 = run_cli("status", job_id, "--jobs-dir", str(tmp_path), "--reproduce")
        assert r2.returncode == 0
        fields = parse_reproduce(r2.stdout)
        assert fields["tool"] == "ghidra-job"
        assert fields["job_id"] == job_id
        assert fields["state"] == "completed"
        assert fields["exit_code"] == "0"
        assert fields["artifact_exists"] == "false"  # command never wrote it

    def test_start_tool_mode_builds_headless_command(self, tmp_path):
        fake_ghidra = tmp_path / "ghidra"
        (fake_ghidra / "support").mkdir(parents=True)
        # Execution-type fixture: the picked analyzeHeadless must actually
        # run on this platform. analyze_headless_path() tries .bat first, so
        # on POSIX write an extensionless executable script (behavior
        # equivalent to the batch: dump argv, exit 0); on Windows keep .bat.
        if os.name == "nt":
            bat = fake_ghidra / "support" / "analyzeHeadless.bat"
            bat.write_text("@echo off\n"
                           "echo %* > \"%~dp0..\\args.txt\"\nexit /b 0\n",
                           encoding="utf-8")
        else:
            sh = fake_ghidra / "support" / "analyzeHeadless"
            sh.write_text(
                "#!/bin/sh\n"
                f'echo "$@" > "{fake_ghidra}/args.txt"\n'
                "exit 0\n",
                encoding="utf-8",
            )
            sh.chmod(0o755)
        binary = tmp_path / "s.exe"
        binary.write_bytes(b"MZ")
        r = run_cli("start", "--tool", "ghidra-recon", "--binary", str(binary),
                    "--ghidra-home", str(fake_ghidra), "--jobs-dir", str(tmp_path),
                    "--search-terms", "http")
        assert r.returncode == 0, r.stderr
        job_id = r.stdout.strip().split("=", 1)[1]
        out = poll_status(tmp_path, job_id)
        assert out["state"] == "completed", out
        args_txt = (fake_ghidra / "args.txt").read_text(encoding="utf-8")
        assert "GhidraRecon.java" in args_txt
        # cmd splits --search-terms=http at '='; the batch sees the pair as
        # two tokens — the Java getArg accepts both forms (its 3rd branch)
        assert "--search-terms" in args_txt and "http" in args_txt


# ---------------------------------------------------------------------------
# Runner subprocess contract
# ---------------------------------------------------------------------------

class TestRunnerContract:
    def test_runner_internal_subcommand_exists(self, tmp_path):
        r = run_cli("_run", "--help")
        assert r.returncode == 0

    def test_runner_missing_record_exits_zero(self, tmp_path):
        r = run_cli("_run", "--job-id", "gj-20260814-000000-0000",
                    "--jobs-dir", str(tmp_path))
        assert r.returncode == 0
