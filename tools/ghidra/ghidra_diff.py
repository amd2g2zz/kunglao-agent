#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/ghidra/ghidra_diff.py — binary diff CLI over Ghidra Version Tracking (issue #308).

Absorbed design from REA's DiffSessionManager (Ghidra VT VTProgramCorrelatorFactory),
re-implemented for the kunglao CLI contract.  Two halves:

  - Session lifecycle (isomorphic to the async job protocol in ghidra_job.py):
    ``create`` starts a detached analyzeHeadless run of the GhidraBindiff.java
    postScript (both samples imported into one project), ``status`` polls it,
    ``cancel`` kills it, ``delete`` removes it.  The Java script writes a
    ``bindiff.v1`` JSON artifact.
  - Artifact queries (pure slicing of the bindiff.v1 artifact, no Ghidra
    needed):
    ``diff-summary``            match statistics
    ``diff-list-functions``     categories: identical/changed/added/removed
    ``diff-function <addr>``    lenses: callee changes + bodyBytesChanged
                                (bodyBytesChanged is the 恒检 lens — always
                                present for matched functions)

Usage:
  ghidra-diff create --base <base.exe> --target <target.exe> [--out artifact.json]
  ghidra-diff status <job_id>
  ghidra-diff diff-summary --artifact artifact.json   # or --job <job_id>
  ghidra-diff diff-function 0x501100 --artifact artifact.json --side target

Exit codes: 0 = ok, 1 = negative finding (e.g. diff-function address not in the
diff), 2 = error (bad args / missing or invalid artifact) — structured error
JSON on stderr, never a traceback.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(errors="replace")
except (AttributeError, ValueError):
    pass

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

import ghidra_job as gj  # noqa: E402
import run_ghidra_postscript as rp  # noqa: E402

TOOL = "ghidra-diff"
DIFF_SCHEMA = "bindiff.v1"
BINDIFF_JAVA = "GhidraBindiff.java"

EXIT_OK = 0
EXIT_NEGATIVE = 1
EXIT_ERROR = 2

TERMINAL_STATES = gj.TERMINAL_STATES
CATEGORIES = ("identical", "changed", "added", "removed")

error = gj.error  # structured stderr JSON + exit code
emit_json = gj.emit_json
emit_fields = gj.emit_fields


class ArtifactError(ValueError):
    """bindiff.v1 artifact missing/unreadable/wrong schema."""


# ---------------------------------------------------------------------------
# Artifact loading / address parsing (pure)
# ---------------------------------------------------------------------------

def load_artifact(path: Path) -> dict:
    """Load and validate a bindiff.v1 artifact; raises ArtifactError with
    guidance otherwise."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ArtifactError(
            f"artifact not found at {path}: {exc} — run "
            f"`{TOOL} create --base ... --target ...` first") from exc
    try:
        artifact = json.loads(raw)
    except ValueError as exc:
        raise ArtifactError(f"artifact at {path} is not valid JSON: {exc}") \
            from exc
    if not isinstance(artifact, dict) or artifact.get("schema") != DIFF_SCHEMA:
        raise ArtifactError(
            f"artifact at {path} is not a {DIFF_SCHEMA} artifact "
            f"(schema={artifact.get('schema') if isinstance(artifact, dict) else None!r})"
            f" — run `{TOOL} create --base ... --target ...` first")
    return artifact


def parse_addr(value: str) -> int:
    """Hex address (0x-prefixed or bare); raises ValueError on garbage."""
    text = value.strip()
    if text.lower().startswith("0x"):
        text = text[2:]
    if not text or any(c not in "0123456789abcdefABCDEF" for c in text):
        raise ValueError(f"invalid address {value!r}: expected hex (0x-prefixed)")
    return int(text, 16)


def _addr_key(entry: dict | None) -> int | None:
    if not isinstance(entry, dict):
        return None
    try:
        return parse_addr(str(entry.get("address", "")))
    except ValueError:
        return None


def find_functions(artifact: dict, category: str | None = None) -> list[dict]:
    """Filter artifact functions by category (None = all)."""
    functions = artifact.get("functions") or []
    if category is None:
        return list(functions)
    return [f for f in functions if isinstance(f, dict)
            and f.get("category") == category]


def find_function(artifact: dict, addr: str, side: str) -> dict | None:
    """Locate a function entry by its base/target address."""
    want = parse_addr(addr)
    for fn in find_functions(artifact):
        if _addr_key(fn.get(side)) == want:
            return fn
    return None


def summary_rows(artifact: dict) -> dict:
    summary = artifact.get("summary") or {}
    return {str(key): value for key, value in summary.items()}


# ---------------------------------------------------------------------------
# Command construction (pure)
# ---------------------------------------------------------------------------

def build_bindiff_command(*, ghidra_home: str, base: Path, target: Path,
                          out: Path, script_path: Path, project_dir: Path,
                          project_name: str) -> list[str]:
    """analyzeHeadless argv: import BOTH samples into one project, then run the
    GhidraBindiff.java postScript (dual-sample input, --base/--target).

    --base/--target carry the imported program NAMES (basenames), not paths:
    the Java side guards on ``currentProgram.getName()`` (a name, never a
    path) and looks the base DomainFile up by name in the project root — a
    full path would make the guard always false and silently skip the diff
    while the job still reports completed.
    """
    headless = rp.analyze_headless_path(ghidra_home)
    return [
        str(headless),
        str(project_dir),
        project_name,
        "-import", str(base),
        "-import", str(target),
        "-overwrite",
        "-scriptPath", str(script_path),
        "-postScript", BINDIFF_JAVA,
        f"--base={base.name}",
        f"--target={target.name}",
        f"--out={out}",
        "-analysisTimeoutPerFile", "300",
    ]


# ---------------------------------------------------------------------------
# Artifact resolution (--artifact file | --job <id> record)
# ---------------------------------------------------------------------------

def resolve_artifact_path(args) -> Path:
    if args.artifact:
        return Path(args.artifact)
    if args.job:
        jobs_dir = Path(args.jobs_dir).expanduser() if args.jobs_dir \
            else gj.default_jobs_dir(
                Path(args.workspace).resolve() if args.workspace else Path.cwd())
        store = gj.JobStore(jobs_dir)
        record = store.get(args.job)
        if record is None:
            error(f"{args.action}: unknown job {args.job} (--jobs-dir={jobs_dir})")
        artifact = record.get("artifact")
        if not artifact:
            error(f"{args.action}: job {args.job} has no artifact path "
                  f"(kind={record.get('kind')})")
        return Path(artifact)
    error(f"{args.action}: provide --artifact PATH or --job JOB_ID")


# ---------------------------------------------------------------------------
# Subcommands: lifecycle (isomorphic to ghidra-job start/status/cancel/cleanup)
# ---------------------------------------------------------------------------

def cmd_create(args, env: dict[str, str]) -> int:
    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd()
    base = Path(args.base).expanduser()
    target = Path(args.target).expanduser()
    for label, path in (("base", base), ("target", target)):
        if not path.is_file():
            error(f"create: --{label} not found: {path}")
    if base.name == target.name:
        error(f"create: --base and --target share the same filename "
              f"({base.name!r}) — Ghidra imports both into one project "
              f"directory, so names must differ")
    ghidra_home = rp.resolve_ghidra_home(workspace, args.ghidra_home, env)
    if not ghidra_home:
        error(rp.GHIDRA_HOME_MISSING_MSG)
    headless = rp.analyze_headless_path(ghidra_home)
    if not headless.is_file():
        error(f"create: analyzeHeadless not found at {headless} "
              f"(GHIDRA_HOME={ghidra_home!r})")

    jobs_dir = Path(args.jobs_dir).expanduser() if args.jobs_dir \
        else gj.default_jobs_dir(workspace)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    store = gj.JobStore(jobs_dir)
    job_id = store.new_job_id()
    job_dir = jobs_dir / job_id

    if args.out:
        out_path = Path(args.out).expanduser()
        out_path = out_path if out_path.is_absolute() else Path.cwd() / out_path
    else:
        out_path = job_dir / "bindiff.json"
    project_dir = job_dir / "ghidra-project"
    project_name = f"bindiff_{target.stem}"
    argv = build_bindiff_command(
        ghidra_home=ghidra_home, base=base, target=target, out=out_path,
        script_path=_THIS_DIR, project_dir=project_dir,
        project_name=project_name,
    )
    record = store.create(
        kind="ghidra-bindiff", command=argv, timeout=args.timeout,
        artifact=str(out_path), workspace=str(workspace),
        project_dir=str(project_dir), project_name=project_name,
        keep_project=args.keep_project, logs_dir=str(job_dir), job_id=job_id,
    )
    runner_pid = gj.spawn_runner(store, job_id)

    rows = gj.record_rows(record, "create", include_command=True, tool=TOOL)
    rows["jobs_dir"] = str(jobs_dir)
    rows["runner_pid"] = runner_pid
    if args.reproduce:
        emit_fields(rows)
    elif args.json:
        emit_json({**rows, "command": argv, "state": "started"})
    else:
        print(f"job_id={job_id}")
    return EXIT_OK


def cmd_delete(args) -> int:
    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd()
    jobs_dir = Path(args.jobs_dir).expanduser() if args.jobs_dir \
        else gj.default_jobs_dir(workspace)
    store = gj.JobStore(jobs_dir)
    record = store.get(args.job_id)
    if record is not None:
        gj.remove_job(store, record)
        removed = 1
    else:
        removed = 0
    remaining = len(store.list_jobs())
    rows = {"tool": TOOL, "action": "delete", "removed": removed,
            "remaining": remaining, "jobs_dir": str(jobs_dir)}
    if args.reproduce:
        emit_fields(rows)
    elif args.json:
        emit_json(rows)
    else:
        emit_fields(rows)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Subcommands: artifact queries
# ---------------------------------------------------------------------------

def cmd_diff_summary(args) -> int:
    artifact = load_artifact(resolve_artifact_path(args))
    summary = summary_rows(artifact)
    rows = {"tool": TOOL, "action": "diff-summary", **summary}
    if args.reproduce:
        emit_fields(rows)
    elif args.json:
        emit_json({"tool": TOOL, "action": "diff-summary",
                   "program": artifact.get("program"),
                   "base_program": artifact.get("base_program"),
                   "summary": artifact.get("summary") or {}})
    else:
        emit_fields(rows)
    return EXIT_OK


def cmd_diff_list_functions(args) -> int:
    artifact = load_artifact(resolve_artifact_path(args))
    functions = find_functions(artifact, args.category)
    if not functions:
        rows = {"tool": TOOL, "action": "diff-list-functions",
                "status": "NEGATIVE",
                "category": args.category or "all", "count": 0}
        if args.json:
            emit_json(rows)
        else:
            emit_fields(rows)
        return EXIT_NEGATIVE
    if args.reproduce:
        emit_fields({"tool": TOOL, "action": "diff-list-functions",
                     "category": args.category or "all",
                     "count": len(functions)})
    elif args.json:
        emit_json({"tool": TOOL, "action": "diff-list-functions",
                   "category": args.category or "all",
                   "count": len(functions), "functions": functions})
    else:
        for fn in functions:
            base = fn.get("base") or {}
            target = fn.get("target") or {}
            print(f"category={fn.get('category')} "
                  f"base={base.get('address')} target={target.get('address')} "
                  f"name={target.get('name') or base.get('name')}")
    return EXIT_OK


def cmd_diff_function(args) -> int:
    try:
        parse_addr(args.addr)
    except ValueError as exc:
        error(f"diff-function: {exc}")
    artifact = load_artifact(resolve_artifact_path(args))
    fn = find_function(artifact, args.addr, args.side)
    if fn is None:
        rows = {"tool": TOOL, "action": "diff-function", "status": "NEGATIVE",
                "query_addr": args.addr, "side": args.side}
        if args.json:
            emit_json(rows)
        else:
            emit_fields(rows)
        return EXIT_NEGATIVE
    lenses = fn.get("lenses") or {}
    callees_added = lenses.get("callees_added") or []
    callees_removed = lenses.get("callees_removed") or []
    rows = {
        "tool": TOOL, "action": "diff-function", "query_addr": args.addr,
        "side": args.side, "category": fn.get("category"),
        "body_bytes_changed": lenses.get("body_bytes_changed"),
        "callees_common": lenses.get("callees_common"),
        "callees_added_count": len(callees_added),
        "callees_removed_count": len(callees_removed),
    }
    if args.reproduce:
        emit_fields(rows)
    elif args.json:
        emit_json({**rows, "base": fn.get("base"), "target": fn.get("target"),
                   "similarity": fn.get("similarity"),
                   "confidence": fn.get("confidence"), "lenses": lenses})
    else:
        emit_fields(rows)
        for entry in callees_added:
            print(f"callee_added={entry}")
        for entry in callees_removed:
            print(f"callee_removed={entry}")
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
                    help="workspace root (default: cwd)")
    ap.add_argument("--jobs-dir", default=None,
                    help="job record directory (default: "
                         "<workspace>/runs/ghidra-jobs)")


def _add_artifact_flags(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--artifact", default=None,
                    help="path to the bindiff.v1 JSON artifact")
    ap.add_argument("--job", default=None, metavar="JOB_ID",
                    help="read the artifact path from a created job record")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    _add_common_flags(common)

    ap = argparse.ArgumentParser(
        prog=TOOL,
        description="Binary diff over Ghidra Version Tracking: create/status/"
                    "cancel/delete lifecycle + diff-summary/diff-list-functions/"
                    "diff-function artifact queries (issue #308)")
    # Common flags live on the subparsers only (argparse conflicts otherwise).
    sub = ap.add_subparsers(dest="action", required=True)

    sp_create = sub.add_parser("create", parents=[common],
                               help="launch the VT diff job (detached), return "
                                    "the jobId immediately")
    sp_create.add_argument("--base", required=True, help="base sample path")
    sp_create.add_argument("--target", required=True, help="target sample path")
    sp_create.add_argument("--out", default=None,
                           help="artifact path (default: <job dir>/bindiff.json)")
    sp_create.add_argument("--timeout", type=float, default=gj.DEFAULT_TIMEOUT,
                           help="job timeout in seconds "
                                f"(default {gj.DEFAULT_TIMEOUT})")
    sp_create.add_argument("--ghidra-home", default=None,
                           help="override Ghidra install root")
    sp_create.add_argument("--keep-project", action="store_true",
                           help="keep the job's Ghidra project dir after the run")

    sp_status = sub.add_parser("status", parents=[common],
                               help="poll a diff job record")
    sp_status.add_argument("job_id")
    sp_status.add_argument("--grace", type=float, default=gj.DEFAULT_GRACE,
                           help="min job age before crash detection "
                                f"(default {gj.DEFAULT_GRACE}s)")

    sp_cancel = sub.add_parser("cancel", parents=[common],
                               help="kill the job's process tree; no-op on "
                                    "terminal jobs")
    sp_cancel.add_argument("job_id")

    sp_delete = sub.add_parser("delete", parents=[common],
                               help="remove a job record and its files")
    sp_delete.add_argument("job_id")

    sp_summary = sub.add_parser("diff-summary", parents=[common],
                                help="match statistics from a bindiff.v1 "
                                     "artifact")
    _add_artifact_flags(sp_summary)

    sp_list = sub.add_parser("diff-list-functions", parents=[common],
                             help="list functions by diff category")
    _add_artifact_flags(sp_list)
    sp_list.add_argument("--category", choices=CATEGORIES, default=None,
                         help="filter: identical|changed|added|removed "
                              "(default: all)")

    sp_fn = sub.add_parser("diff-function", parents=[common],
                           help="per-function diff with callees + "
                                "bodyBytesChanged lenses")
    _add_artifact_flags(sp_fn)
    sp_fn.add_argument("addr", help="hex function address (0x-prefixed or bare)")
    sp_fn.add_argument("--side", choices=("base", "target"), default="target",
                       help="which side the address belongs to (default: target)")

    return ap.parse_args(argv)


def main(argv: list[str] | None = None, environ: dict[str, str] | None = None) -> int:
    args = parse_args(argv)
    env = dict(environ) if environ is not None else dict(os.environ)
    try:
        if args.action == "create":
            return cmd_create(args, env)
        if args.action == "status":
            return gj.cmd_status(args, tool=TOOL)
        if args.action == "cancel":
            return gj.cmd_cancel(args, tool=TOOL)
        if args.action == "delete":
            return cmd_delete(args)
        if args.action == "diff-summary":
            return cmd_diff_summary(args)
        if args.action == "diff-list-functions":
            return cmd_diff_list_functions(args)
        if args.action == "diff-function":
            return cmd_diff_function(args)
    except ArtifactError as exc:
        error(str(exc))
    except (gj.JobStateError, OSError) as exc:
        error(f"{args.action}: {exc}")
    error(f"unknown action: {args.action}")


if __name__ == "__main__":
    sys.exit(main())
