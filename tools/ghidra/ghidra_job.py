#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/ghidra/ghidra_job.py — Ghidra async job protocol (issue #308).

Absorbed design from REA's analyze-program protocol (``waitSeconds=0`` -> jobId ->
analysis-status long poll), re-implemented for the kunglao CLI contract.  Long
analyzeHeadless runs are started detached and return a jobId immediately, so a
worker can poll ``status`` between other steps instead of blocking inside a tool
call (heartbeat compatible).

Job lifecycle (state machine lives in tools/ghidra/job_store.py)::

    started -> running -> completed | failed | timed_out | cancelled

  - ``start``   writes the job record (started) and spawns a detached runner
                (this same script, hidden ``_run`` subcommand) — returns at once.
  - ``status``  prints the record; detects a dead runner and fails the job.
  - ``cancel``  kills the runner process tree; on terminal jobs it is an
                idempotent no-op (record left byte-identical, exit 0).
  - ``cleanup`` removes terminal jobs (default: finished >24h ago), ``--all``,
                or ``--job <id>``; active jobs are terminated before removal.

Jobs are persisted as ``<jobs-dir>/<job-id>.json`` (atomic tmp+rename) with
per-job logs/project dir under ``<jobs-dir>/<job-id>/``.  Default jobs dir is
``<workspace>/runs/ghidra-jobs`` (workspace defaults to cwd).

Two start modes:
  - ``--command "python -c ..."`` — run any argv (POSIX-style shlex splitting;
    on Windows use forward slashes inside paths).  The child gets GHIDRA_JOB_ID
    and, when an artifact path is set, GHIDRA_JOB_ARTIFACT env vars.
  - ``--tool ghidra-recon --binary <path> ...`` — build the analyzeHeadless
    argv by reusing tools/ghidra/run_ghidra_postscript.py (issue #293), each
    job with its own Ghidra project dir.

Design note (asyncio vs processes): this async is PROCESS-level, not
coroutine-level — the blocking wait is a JVM (analyzeHeadless) that outlives
the CLI invocation, and the caller is a separate worker process that polls via
``status``.  An asyncio event loop cannot keep waiting after its process exits;
a detached runner process can.  One runner handles exactly one child, so
coroutine scheduling adds complexity without throughput; job concurrency comes
from spawning multiple isolated runner processes (crash isolation, cancel via
process-tree kill).

CLI contract (mirrors tools/static/*): --json (single JSON object on stdout),
--reproduce (field=value lines for the kunglao L1 gate), errors are a structured
JSON object on stderr {"error": ..., "exit_code": 2} — never a traceback.
Exit codes: 0 = ok, 2 = error.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NoReturn


_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import run_ghidra_postscript as rp  # noqa: E402

import sys as _sys_io, pathlib as _pathlib_io
_TOOLS_DIR = next(_p for _p in _pathlib_io.Path(__file__).resolve().parents if _p.name == 'tools')
if str(_TOOLS_DIR) not in _sys_io.path:
    _sys_io.path.insert(0, str(_TOOLS_DIR))
from _lib.stdio import ensure_utf8_stdout  # noqa: E402
from job_store import (  # noqa: E402 — shared substrate, re-exported for callers
    ACTIVE_STATES,
    ALLOWED_TRANSITIONS,  # noqa: F401 — re-export: tests read gj.ALLOWED_TRANSITIONS
    JOB_SCHEMA,  # noqa: F401 — re-export: tests read gj.JOB_SCHEMA
    JobStateError,
    JobStore,
    TERMINAL_STATES,
    WRITE_RETRIES,
    WRITE_RETRY_DELAY,
    _parse_ts,
    _pid_alive,
    default_jobs_dir,
    terminate_process_tree,
    wrap_batch_argv,
)

TOOL = "ghidra-job"

EXIT_OK = 0
EXIT_ERROR = 2

DEFAULT_TIMEOUT = 900.0     # seconds — matches run_ghidra_postscript.py
DEFAULT_GRACE = 5.0         # status: min job age before crash detection applies
DEFAULT_OLDER_THAN = 24.0   # cleanup: hours
STALE_CLEANUP_WAIT = 10.0   # runner: seconds to wait for child reaping


# ---------------------------------------------------------------------------
# Output helpers (kunglao CLI contract)
# ---------------------------------------------------------------------------

def error(message: str, code: int = EXIT_ERROR) -> NoReturn:
    """Structured error JSON on stderr; exit 2 — never a traceback."""
    print(json.dumps({"error": message, "exit_code": code}), file=sys.stderr)
    sys.exit(code)


def _wait_dead(pid: int, timeout: float = 3.0) -> None:
    """Poll until the process is gone (kills the cancel/record write race)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.05)


def emit_json(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def emit_fields(rows: dict) -> None:
    for key, value in rows.items():
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        print(f"{key}={value}")


def record_rows(record: dict, action: str, include_command: bool = False,
                tool: str = TOOL) -> dict:
    """Status/cancel field rows: L1-safe field=value keys, None values skipped
    by emit_fields."""
    artifact = record.get("artifact")
    rows = {
        "tool": tool,
        "action": action,
        "job_id": record["job_id"],
        "state": record["state"],
        "kind": record["kind"],
        "timeout": record.get("timeout"),
        "exit_code": record.get("exit_code"),
        "error": record.get("error"),
        "artifact": artifact,
        "artifact_exists": (Path(artifact).is_file() if artifact else False),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "finished_at": record.get("finished_at"),
        "runner_pid": record.get("runner_pid"),
        "child_pid": record.get("child_pid"),
        "logs_dir": record.get("logs_dir"),
    }
    if include_command:
        rows["command"] = record.get("command")
    return rows


# ---------------------------------------------------------------------------
# Runner plumbing
# ---------------------------------------------------------------------------

def spawn_runner(store: JobStore, job_id: str) -> int:
    """Detach the runner subprocess (this script's hidden _run subcommand)."""
    job_dir = store.jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    log_file = (job_dir / "launcher.log").open("ab")
    kwargs: dict = {
        "stdout": log_file,
        "stderr": subprocess.STDOUT,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (subprocess.CREATE_NO_WINDOW
                                   | subprocess.CREATE_NEW_PROCESS_GROUP)
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(
            [sys.executable, str(__file__), "_run",
             "--job-id", job_id, "--jobs-dir", str(store.jobs_dir)],
            **kwargs)
    finally:
        log_file.close()
    return proc.pid


def remove_job(store: JobStore, record: dict) -> None:
    """Delete a record, terminate the tree when still active, drop the job dir."""
    if record["state"] in ACTIVE_STATES:
        for pid in (record.get("runner_pid"), record.get("child_pid")):
            if pid:
                terminate_process_tree(pid)
    store.delete(record["job_id"])
    if store.jobs_dir:
        shutil.rmtree(store.jobs_dir / record["job_id"], ignore_errors=True)


def _update_retry(store: JobStore, job_id: str, **fields) -> dict:
    """update() with OSError retries — the runner's terminal-state writes must
    survive transient AV/indexer interference; JobStateError passes through
    (cancel raced us — its write wins)."""
    last: OSError | None = None
    for attempt in range(WRITE_RETRIES):
        try:
            return store.update(job_id, **fields)
        except JobStateError:
            raise
        except OSError as exc:
            last = exc
            if attempt < WRITE_RETRIES - 1:
                time.sleep(WRITE_RETRY_DELAY)
    raise last  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Command construction (pure — directly testable)
# ---------------------------------------------------------------------------

def build_tool_command(*, ghidra_home: str, tool: str, binary: Path,
                       post_args: list[tuple[str, str]], out: Path,
                       script_path: Path, job_dir: Path,
                       ) -> tuple[list[str], Path]:
    """Build the analyzeHeadless argv for a tools/ghidra postScript, with a
    job-scoped Ghidra project dir.  Reuses run_ghidra_postscript.build_command
    (issue #293) — this is the argv-list subprocess wrapper, extended async."""
    if tool not in rp.TOOL_JAVA:
        raise ValueError(f"unknown ghidra tool: {tool!r}")
    project_dir = Path(job_dir) / "ghidra-project"
    project_name = f"{tool.replace('-', '_')}_{binary.stem}"
    merged = [(k, v) for (k, v) in post_args if k != "out"]
    if out is not None:
        merged.append(("out", str(out)))
    cmd = rp.build_command(
        ghidra_home=ghidra_home, tool=tool, binary=binary, post_args=merged,
        script_path=script_path, project_dir=project_dir,
        project_name=project_name,
    )
    return cmd, project_dir


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_start(args, env: dict[str, str], extra: list[str]) -> int:
    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd()
    jobs_dir = Path(args.jobs_dir).expanduser() if args.jobs_dir \
        else default_jobs_dir(workspace)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    store = JobStore(jobs_dir)
    job_id = store.new_job_id()
    job_dir = jobs_dir / job_id

    project_dir: Path | None = None
    project_name: str | None = None
    artifact: str | None = None
    out_path: Path | None = None

    if args.command:
        if extra:
            error(f"start: --command mode takes no forwarded flags "
                  f"(they belong to --tool mode): {' '.join(extra)}")
        kind = "command"
        # POSIX-style splitting: quotes are stripped (non-posix mode keeps the
        # quote characters, which would corrupt -c "... code ..." arguments).
        # On Windows use forward slashes in paths inside --command.
        argv = shlex.split(args.command)
        if not argv:
            error("start: --command is empty after shell-splitting")
        if args.out:
            out_path = Path(args.out).expanduser()
            out_path = out_path if out_path.is_absolute() else Path.cwd() / out_path
        else:
            out_path = job_dir / "artifact.json"
        artifact = str(out_path)
    else:
        if not (args.tool and args.binary):
            error("start: requires --command \"...\" or --tool/--binary "
                  "(long analyzeHeadless run)")
        binary = Path(args.binary).expanduser()
        if not binary.is_file():
            error(f"start: --binary not found: {binary}")
        ghidra_home = rp.resolve_ghidra_home(workspace, args.ghidra_home, env)
        if not ghidra_home:
            error(rp.GHIDRA_HOME_MISSING_MSG)
        headless = rp.analyze_headless_path(ghidra_home)
        if not headless.is_file():
            error(f"start: analyzeHeadless not found at {headless} "
                  f"(GHIDRA_HOME={ghidra_home!r})")
        if args.out:
            out_path = Path(args.out).expanduser()
            out_path = out_path if out_path.is_absolute() else Path.cwd() / out_path
        else:
            out_path = job_dir / "artifact.json"
        artifact = str(out_path)
        post_args = [(k, v) for (k, v) in rp.split_forwarded(extra) if k != "out"]
        argv, project_dir = build_tool_command(
            ghidra_home=ghidra_home, tool=args.tool, binary=binary,
            post_args=post_args, out=out_path, script_path=_THIS_DIR,
            job_dir=job_dir,
        )
        kind = args.tool
        project_name = f"{args.tool.replace('-', '_')}_{binary.stem}"

    record = store.create(
        kind=kind, command=argv, timeout=args.timeout, artifact=artifact,
        workspace=str(workspace),
        project_dir=str(project_dir) if project_dir else None,
        project_name=project_name, keep_project=args.keep_project,
        logs_dir=str(job_dir), job_id=job_id,
    )
    runner_pid = spawn_runner(store, job_id)

    rows = record_rows(record, "start", include_command=True)
    rows["jobs_dir"] = str(jobs_dir)
    rows["runner_pid"] = runner_pid
    if args.reproduce:
        emit_fields(rows)
    elif args.json:
        emit_json({**rows, "command": argv, "state": "started"})
    else:
        print(f"job_id={job_id}")
    return EXIT_OK


def cmd_status(args, tool: str = TOOL) -> int:
    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd()
    jobs_dir = Path(args.jobs_dir).expanduser() if args.jobs_dir \
        else default_jobs_dir(workspace)
    store = JobStore(jobs_dir)
    if not store.is_valid_job_id(args.job_id):
        error(f"status: invalid job id {args.job_id!r}")
    record = store.get(args.job_id)
    if record is None:
        error(f"status: unknown job {args.job_id} (--jobs-dir={jobs_dir})")
    if store.detect_crash(args.job_id, grace_seconds=args.grace):
        runner_pid = record.get("runner_pid")
        detail = (f"runner pid {runner_pid} exited without a terminal state"
                  if runner_pid is not None
                  else "runner never reported in")
        try:
            record = store.update(
                args.job_id, state="failed",
                error=f"{detail} (crash detected)",
            )
        except JobStateError:
            # raced: the runner reached a terminal state between the crash
            # check and this write — its write wins
            record = store.get(args.job_id) or record
    rows = record_rows(record, "status", include_command=True, tool=tool)
    if args.reproduce:
        emit_fields(rows)
    elif args.json:
        emit_json(rows)
    else:
        emit_fields(rows)
    return EXIT_OK


def cmd_cancel(args, tool: str = TOOL) -> int:
    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd()
    jobs_dir = Path(args.jobs_dir).expanduser() if args.jobs_dir \
        else default_jobs_dir(workspace)
    store = JobStore(jobs_dir)
    if not store.is_valid_job_id(args.job_id):
        error(f"cancel: invalid job id {args.job_id!r}")
    record = store.get(args.job_id)
    if record is None:
        error(f"cancel: unknown job {args.job_id} (--jobs-dir={jobs_dir})")
    already_terminal = record["state"] in TERMINAL_STATES
    if not already_terminal:
        runner_pid = record.get("runner_pid")
        for pid in (runner_pid, record.get("child_pid")):
            if pid:
                terminate_process_tree(pid)
        if runner_pid:
            _wait_dead(runner_pid)  # no post-cancel record writes can race us
        try:
            record = store.update(args.job_id, state="cancelled")
        except JobStateError:
            # raced: the runner finished between our read and the kill — its
            # terminal write wins; cancel degrades to a no-op
            record = store.get(args.job_id) or record
    already_terminal = record["state"] in TERMINAL_STATES
    rows = record_rows(record, "cancel", include_command=True, tool=tool)
    rows["already_terminal"] = already_terminal
    if args.reproduce:
        emit_fields(rows)
    elif args.json:
        emit_json(rows)
    else:
        emit_fields(rows)
    return EXIT_OK


def cmd_cleanup(args, tool: str = TOOL) -> int:
    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd()
    jobs_dir = Path(args.jobs_dir).expanduser() if args.jobs_dir \
        else default_jobs_dir(workspace)
    store = JobStore(jobs_dir)
    if args.all:
        targets = store.list_jobs()
    elif args.job:
        record = store.get(args.job)
        targets = [record] if record else []
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=args.older_than)
        targets = [
            r for r in store.list_jobs()
            if r["state"] in TERMINAL_STATES
            and (_parse_ts(r.get("finished_at")) or cutoff) < cutoff
        ]
    removed = 0
    for record in targets:
        remove_job(store, record)
        removed += 1
    remaining = len(store.list_jobs())
    rows = {"tool": tool, "action": "cleanup", "removed": removed,
            "remaining": remaining, "jobs_dir": str(jobs_dir)}
    if args.reproduce:
        emit_fields(rows)
    elif args.json:
        emit_json(rows)
    else:
        emit_fields(rows)
    return EXIT_OK


def cmd_run(args) -> int:
    """Hidden runner: executes the recorded command and writes the terminal
    state.  Spawned detached by `start`; runs until completion/cancel."""
    store = JobStore(Path(args.jobs_dir))
    job_id = args.job_id
    record = store.get(job_id)
    if record is None:
        return EXIT_OK  # cleaned up while waiting — nothing to run
    try:
        store.update(job_id, state="running", runner_pid=os.getpid())
    except JobStateError:
        return EXIT_OK  # cancelled before we got going
    except OSError:
        # record write blocked (AV/indexer) — leave the job started; status
        # crash detection fails it after the grace period instead of hanging
        return EXIT_OK
    record = store.get(job_id)
    if record is None:
        return EXIT_OK
    logs_dir = Path(record["logs_dir"]) if record.get("logs_dir") else None
    child: subprocess.Popen | None = None
    try:
        if logs_dir:
            logs_dir.mkdir(parents=True, exist_ok=True)
        stdout_f = (logs_dir / "stdout.log").open("wb") if logs_dir else None
        stderr_f = (logs_dir / "stderr.log").open("wb") if logs_dir else None
        argv = wrap_batch_argv(record["command"], is_windows=(os.name == "nt"))
        env = dict(os.environ)
        env["GHIDRA_JOB_ID"] = job_id
        if record.get("artifact"):
            env["GHIDRA_JOB_ARTIFACT"] = record["artifact"]
        child = None
        for spawn_attempt in range(2):
            try:
                child = subprocess.Popen(
                    argv, stdout=stdout_f, stderr=stderr_f, env=env)
                break
            except OSError:
                if spawn_attempt == 0:
                    time.sleep(0.5)  # transient (AV scanner): retry once
                else:
                    raise
        try:
            store.update(job_id, child_pid=child.pid)
        except JobStateError:
            terminate_process_tree(child.pid)
            return EXIT_OK
        try:
            returncode = child.wait(timeout=record["timeout"])
        except subprocess.TimeoutExpired:
            terminate_process_tree(child.pid)
            try:
                child.wait(timeout=STALE_CLEANUP_WAIT)
            except subprocess.TimeoutExpired:
                pass
            _update_retry(store, job_id, state="timed_out",
                          error=f"timeout after {record['timeout']}s")
            return EXIT_OK
        if returncode == 0:
            _update_retry(store, job_id, state="completed", exit_code=0)
        else:
            _update_retry(store, job_id, state="failed", exit_code=returncode,
                          error=f"command exited {returncode}")
    except JobStateError:
        pass  # cancel raced us to a terminal state — its write wins
    except Exception as exc:  # noqa: BLE001 - runner must always report failure
        try:
            _update_retry(store, job_id, state="failed",
                          error=f"runner error: {exc}")
        except JobStateError:
            pass
    finally:
        for f in (f for f in (locals().get("stdout_f"), locals().get("stderr_f"))
                  if f is not None):
            try:
                f.close()
            except OSError:
                pass
        if record.get("project_dir") and not record.get("keep_project"):
            shutil.rmtree(record["project_dir"], ignore_errors=True)
    return EXIT_OK


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _add_common_flags(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--json", action="store_true",
                    help="emit a single JSON object on stdout")
    ap.add_argument("--reproduce", action="store_true",
                    help="print field=value lines for the kunglao L1 gate")
    ap.add_argument("--workspace", default=None,
                    help="workspace root (default: cwd) — jobs dir default is "
                         "<workspace>/runs/ghidra-jobs")
    ap.add_argument("--jobs-dir", default=None,
                    help="override the job record directory")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    _add_common_flags(common)

    ap = argparse.ArgumentParser(
        prog=TOOL,
        description="Ghidra async job protocol: start/status/cancel/cleanup "
                    "(issue #308 — REA analyze-program protocol absorbed)")
    # NOTE: --json/--reproduce/--workspace/--jobs-dir live on the SUBparsers
    # only (usage: ghidra-job status <id> --json) — putting them on the main
    # parser too would collide (argparse conflicting-option-string error).
    sub = ap.add_subparsers(dest="action", required=True)

    sp_start = sub.add_parser(
        "start", parents=[common],
        help="launch a detached job, return its jobId immediately")
    sp_start.add_argument("--command", default=None,
                          help="run this argv instead of analyzeHeadless "
                               "(shell-style quoting; forward slashes on "
                               "Windows)")
    sp_start.add_argument("--tool", choices=sorted(rp.TOOL_JAVA), default=None,
                          help="ghidra postScript tool id (with --binary)")
    sp_start.add_argument("--binary", default=None,
                          help="absolute path to the sample binary (--tool mode)")
    sp_start.add_argument("--out", default=None,
                          help="artifact path (default: <job dir>/artifact.json)")
    sp_start.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                          help=f"job timeout in seconds (default {DEFAULT_TIMEOUT})")
    sp_start.add_argument("--ghidra-home", default=None,
                          help="override Ghidra install root (--tool mode)")
    sp_start.add_argument("--keep-project", action="store_true",
                          help="keep the job's Ghidra project dir after the run")

    sp_status = sub.add_parser("status", parents=[common],
                               help="print a job record (poll)")
    sp_status.add_argument("job_id")
    sp_status.add_argument("--grace", type=float, default=DEFAULT_GRACE,
                           help=f"min job age before crash detection "
                                f"(default {DEFAULT_GRACE}s)")

    sp_cancel = sub.add_parser("cancel", parents=[common],
                               help="kill the job's process tree; no-op on "
                                    "terminal jobs (idempotent)")
    sp_cancel.add_argument("job_id")

    sp_cleanup = sub.add_parser("cleanup", parents=[common],
                                help="remove terminal jobs (default: finished "
                                     ">24h ago); --all removes everything")
    sp_cleanup.add_argument("--all", action="store_true",
                            help="remove every job (terminating active ones)")
    sp_cleanup.add_argument("--job", default=None, metavar="JOB_ID",
                            help="remove one specific job")
    sp_cleanup.add_argument("--older-than", type=float, default=DEFAULT_OLDER_THAN,
                            help="hours (terminal jobs only; "
                                 f"default {DEFAULT_OLDER_THAN})")

    sp_run = sub.add_parser("_run", help=argparse.SUPPRESS)
    sp_run.add_argument("--job-id", required=True)
    sp_run.add_argument("--jobs-dir", required=True)

    args, extra = ap.parse_known_args(argv)
    args.forwarded = extra
    return args


def main(argv: list[str] | None = None, environ: dict[str, str] | None = None) -> int:
    args = parse_args(argv)
    env = dict(environ) if environ is not None else dict(os.environ)
    # Unknown flags: `start` forwards its extras to the postScript (--key
    # value, by design); every other subcommand rejects them — a silently
    # swallowed misspelled flag is worse than a hard error (review L-7).
    if args.action not in ("start",) and args.forwarded:
        error(f"unknown flag(s) for {args.action}: "
              f"{' '.join(args.forwarded)} (see {TOOL} {args.action} --help)")
    try:
        if args.action == "start":
            return cmd_start(args, env, args.forwarded)
        if args.action == "status":
            return cmd_status(args)
        if args.action == "cancel":
            return cmd_cancel(args)
        if args.action == "cleanup":
            return cmd_cleanup(args)
        if args.action == "_run":
            return cmd_run(args)
    except (JobStateError, OSError) as exc:
        error(f"{args.action}: {exc}")
    error(f"unknown action: {args.action}")


if __name__ == "__main__":
    ensure_utf8_stdout()
    sys.exit(main())
