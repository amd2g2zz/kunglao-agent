#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/ghidra/job_store.py — dir-backed async job store + process helpers (issue #308).

Shared substrate for the Ghidra async job protocol (ghidra_job.py) and the
binary-diff session lifecycle (ghidra_diff.py).  Not a tool itself — not
registered in tools/_INDEX.yaml.

Absorbed design (REA analyze-program: jobId + status polling): one JSON record
per job at ``<jobs_dir>/<job_id>.json``, atomic writes (tmp + os.replace), a
lifecycle state machine, and the process primitives the detached runner needs.

Lifecycle::

    started -> running -> completed | failed | timed_out | cancelled

  - writes are atomic: readers never see a torn record
  - update() is a read-modify-write serialized by a sidecar ``<record>.lock``
    file (the record file itself is replaced, so inode locks would not work)
  - reads retry briefly across the os.replace delete/rename window (Windows
    MoveFileEx) so a concurrent status poll never misreports a live job
  - Windows transient PermissionError (AV/indexer) on os.replace is retried

Process helpers:
  - terminate_process_tree: taskkill /T /F (Windows) / killpg (POSIX)
  - wrap_batch_argv: .bat/.cmd argv must run via cmd /c (WinError 193);
    cmd splits ``--key=value`` at ``=`` — GhidraJsonScript.getArg accepts
    both forms (its third branch), matching run_ghidra_postscript.py behavior
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

JOB_SCHEMA = "ghidra_job.v1"

ACTIVE_STATES = ("started", "running")
TERMINAL_STATES = ("completed", "failed", "timed_out", "cancelled")

# Lifecycle state machine: state -> set of legal next states.
# ``started -> failed`` is legal ONLY for the crash-detection path: a runner
# that dies (or loses its writes to transient AV/indexer interference) before
# ever reporting ``running`` must still be fail-able by status, otherwise the
# job hangs in ``started`` forever (review DIFF-3).
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "started": {"running", "failed", "cancelled"},
    "running": {"completed", "failed", "timed_out", "cancelled"},
}

WRITE_RETRIES = 5           # transient os.replace PermissionError (AV/indexer)
WRITE_RETRY_DELAY = 0.2     # seconds between write retries
READ_RETRIES = 3            # read attempts across the os.replace delete window
READ_RETRY_DELAY = 0.05     # seconds between read retries
JOB_ID_ATTEMPTS = 5         # create(): fresh-id reservation attempts (O_EXCL)

_JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_JOB_ID_FORMAT_RE = re.compile(r"^gj-\d{8}-\d{6}-[0-9a-f]{4}$")


class JobStateError(ValueError):
    """Illegal lifecycle transition (e.g. terminal -> running)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _pid_alive(pid: int) -> bool:
    """True when a process with this pid exists.

    Windows: os.kill(pid, 0) reports EINVAL (not ESRCH) for dead pids, so use
    an OpenProcess handle check there.  POSIX: sig-0 probe.
    """
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ERROR_ACCESS_DENIED = 5
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False,
                                      int(pid))
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # exists but not killable from here
    return True


def terminate_process_tree(pid: int) -> None:
    """Kill a process and its descendants (best effort, never raises)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=60)
            return
        try:
            os.killpg(os.getpgid(pid), 15)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        os.kill(pid, 15)
    except (subprocess.TimeoutExpired, OSError):
        pass  # best effort: a stuck kill must not crash cancel/cleanup


def wrap_batch_argv(argv: list[str], is_windows: bool) -> list[str]:
    """Windows: a .bat/.cmd argv must be run via cmd /c (WinError 193
    otherwise).  Note: cmd's tokenizer splits ``--key=value`` at ``=`` — the
    batch receives ``--key`` and the value as two args.  This matches how
    tools/ghidra/run_ghidra_postscript.py already invokes analyzeHeadless.bat,
    and GhidraJsonScript.getArg accepts both the ``--key=value`` and the
    split ``--key value`` forms (its third branch).  Quoting is deliberately
    avoided: cmd escapes quoted args as ``\\"...\\"`` inside the batch, which
    would corrupt the forwarding instead."""
    if is_windows and argv and argv[0].lower().endswith((".bat", ".cmd")):
        return ["cmd", "/c", *argv]
    return argv


def default_jobs_dir(workspace: Path) -> Path:
    """<workspace>/runs/ghidra-jobs — state lives with the workspace runs/."""
    return Path(workspace) / "runs" / "ghidra-jobs"


# Record-file lock: update() is a read-modify-write; cancel and the runner can
# race it.  The record file itself is replaced atomically (tmp + os.replace),
# which would break inode-based locking — so mutual exclusion lives on a
# dedicated, never-replaced sidecar `<record>.lock` file.
if os.name == "nt":
    import msvcrt  # noqa: E402

    @contextlib.contextmanager
    def _record_lock(path: Path):
        lock_path = Path(str(path) + ".lock")
        handle = open(lock_path, "a+b")
        try:
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"\0")  # byte 0 must exist for the range lock
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            yield
        finally:
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            handle.close()

else:
    import fcntl  # noqa: E402

    @contextlib.contextmanager
    def _record_lock(path: Path):
        lock_path = Path(str(path) + ".lock")
        handle = open(lock_path, "a+b")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX)
            yield
        finally:
            handle.close()


class JobStore:
    """Dir-backed job record store with lifecycle enforcement.

    One JSON file per job at ``<jobs_dir>/<job_id>.json``; writes are atomic
    (tmp + os.replace) so concurrent readers never see a torn record.
    """

    def __init__(self, jobs_dir: Path):
        self.jobs_dir = Path(jobs_dir)

    # -- record IO ----------------------------------------------------------

    def record_path(self, job_id: str) -> Path:
        return self.jobs_dir / f"{job_id}.json"

    @staticmethod
    def is_valid_job_id(job_id: str) -> bool:
        """Path-traversal guard: job ids are single [A-Za-z0-9_-]+ tokens."""
        return bool(job_id) and bool(_JOB_ID_RE.fullmatch(job_id))

    def new_job_id(self) -> str:
        """gj-YYYYMMDD-HHMMSS-<4 hex>, collision-checked against the dir."""
        while True:
            job_id = (f"gj-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
                      f"-{int.from_bytes(os.urandom(2), 'big'):04x}")
            if not self.record_path(job_id).exists():
                return job_id

    def create(self, *, kind: str, command: list[str], timeout: float,
               artifact: str | None, workspace: str,
               project_dir: str | None = None, project_name: str | None = None,
               keep_project: bool = False, logs_dir: str | None = None,
               job_id: str | None = None) -> dict:
        """Create a fresh record.  The job id is RESERVED with an O_EXCL
        create on the record path itself (a tmp-file reservation would
        evaporate at the atomic rename), so two concurrent creators can never
        silently share one id; a same-second collision retries the next fresh
        id (TOCTOU guard, review L-6)."""
        last: FileExistsError | None = None
        for _ in range(JOB_ID_ATTEMPTS):
            fresh_id = job_id if job_id is not None else self.new_job_id()
            path = self.record_path(fresh_id)
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
                os.close(fd)  # reservation marker; real content below
            except FileExistsError as exc:
                last = exc
                if job_id is not None:
                    # caller-supplied id is taken — do not silently swap it
                    raise JobStateError(
                        f"job id already reserved: {job_id}") from exc
                continue  # rare collision: retry with the next fresh id
            record = self._new_record(
                kind=kind, command=command, timeout=timeout, artifact=artifact,
                workspace=workspace, project_dir=project_dir,
                project_name=project_name, keep_project=keep_project,
                logs_dir=logs_dir, job_id=fresh_id)
            self._write(record)
            return record
        raise JobStateError(f"could not reserve a fresh job id: {last}")

    def _new_record(self, *, kind: str, command: list[str], timeout: float,
                    artifact: str | None, workspace: str,
                    project_dir: str | None, project_name: str | None,
                    keep_project: bool, logs_dir: str | None,
                    job_id: str) -> dict:
        return {
            "schema": JOB_SCHEMA,
            "job_id": job_id,
            "kind": kind,
            "command": list(command),
            "timeout": timeout,
            "artifact": artifact,
            "workspace": workspace,
            "project_dir": project_dir,
            "project_name": project_name,
            "keep_project": keep_project,
            "logs_dir": logs_dir,
            "created_at": _now(),
            "updated_at": _now(),
            "state": "started",
            "runner_pid": None,
            "child_pid": None,
            "exit_code": None,
            "error": None,
            "finished_at": None,
        }

    def get(self, job_id: str) -> dict | None:
        """Read a record; None when missing/unreadable.  Retries briefly
        across the os.replace delete/rename window (Windows MoveFileEx) so a
        concurrent status poll never misreports a live job as unknown."""
        if not self.is_valid_job_id(job_id):
            return None
        path = self.record_path(job_id)
        for _ in range(READ_RETRIES):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                return record if isinstance(record, dict) else None
            except (OSError, ValueError):
                time.sleep(READ_RETRY_DELAY)
        return None

    def update(self, job_id: str, **fields) -> dict:
        """Merge fields into the record, enforcing the state machine.

        The read-modify-write runs under a per-record file lock so concurrent
        writers (runner vs cancel vs status crash-fail) serialize instead of
        overwriting each other.
        """
        path = self.record_path(job_id)
        if self.get(job_id) is None:  # retry-tolerant existence pre-check
            raise JobStateError(f"unknown job: {job_id}")
        with _record_lock(path):
            current = self.get(job_id)
            if current is None:
                raise JobStateError(f"unknown job: {job_id}")
            if "state" in fields:
                new_state = fields["state"]
                if new_state == current["state"]:
                    raise JobStateError(
                        f"job {job_id}: no self-transition {new_state} -> {new_state}")
                legal = ALLOWED_TRANSITIONS.get(current["state"], set())
                if new_state not in legal:
                    raise JobStateError(
                        f"job {job_id}: illegal transition "
                        f"{current['state']} -> {new_state} (legal: {sorted(legal)})")
            record = {**current, **fields, "updated_at": _now()}
            if record["state"] in TERMINAL_STATES and record.get("finished_at") is None:
                record["finished_at"] = record["updated_at"]
            self._write(record)
        return record

    def list_jobs(self) -> list[dict]:
        jobs = []
        for path in sorted(self.jobs_dir.glob("*.json")):
            job_id = path.stem
            if not _JOB_ID_FORMAT_RE.fullmatch(job_id):
                continue  # foreign file — not ours
            record = self.get(job_id)
            if record is not None:
                jobs.append(record)
        return jobs

    def delete(self, job_id: str) -> bool:
        path = self.record_path(job_id)
        if not self.is_valid_job_id(job_id) or not path.is_file():
            return False
        try:
            path.unlink()
        except OSError:
            return False
        return True

    def detect_crash(self, job_id: str, grace_seconds: float) -> bool:
        """True when an active job's runner is gone past the grace period."""
        record = self.get(job_id)
        if record is None or record["state"] not in ACTIVE_STATES:
            return False
        updated = _parse_ts(record.get("updated_at"))
        if updated is None:
            return False
        age = (datetime.now(timezone.utc) - updated).total_seconds()
        if age < grace_seconds:
            return False
        runner_pid = record.get("runner_pid")
        if runner_pid is None:
            return True  # runner never reported in
        return not _pid_alive(runner_pid)

    def _write(self, record: dict) -> None:
        """Atomically write a record (tmp + os.replace), retrying transient
        PermissionError (AV scanner / search indexer on Windows)."""
        path = self.record_path(record["job_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        for attempt in range(WRITE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == WRITE_RETRIES - 1:
                    raise
                # transient (AV scanner / search indexer holding the target)
                time.sleep(WRITE_RETRY_DELAY)
