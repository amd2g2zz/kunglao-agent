#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_ghidra_postscript.py — analyzeHeadless wrapper for tools/ghidra/*.java (issue #293).

Invokes Ghidra's headless analyzer against a sample binary with one of the
parameterized postScript tools in this directory, forwards tool-specific
``--key=value`` arguments verbatim, then reports the ``--out`` artifact the
postScript wrote.

GHIDRA_HOME resolution order (no hardcoded install paths, issue #228):
  1. ``--ghidra-home`` CLI argument
  2. ``GHIDRA_HOME`` environment variable
  3. ``analysis_state.txt`` in the workspace (a ``ghidra_home=...`` /
     ``GHIDRA_HOME=...`` line, case-insensitive)
If none resolves, or ``<GHIDRA_HOME>/support/analyzeHeadless.bat`` does not
exist, exit 2 with guidance. This is the entry point ghidra-light calls for the
headless tier.

Tool -> postScript mapping (the 5 absorbed tools, #293):
  ghidra-recon                 -> GhidraRecon.java
  ghidra-decompile-functions   -> DecompileFunctions.java
  ghidra-vtable-struct         -> GhidraExportVtableStruct.java
  ghidra-evidence-annotations  -> GhidraEvidenceAnnotations.java
  ghidra-scan-pointer          -> GhidraScanPointer.java

--context mode (issue #306): passing ``--context`` with
``--tool ghidra-decompile-functions`` forwards the flag to
DecompileFunctions.java, which additionally collects per-address caller/callee
snippets, xref'd strings and recovered names.  After the run, the wrapper
assembles those fields into one LLM-ready ``ghidra_context.v1`` document
(``build_context_document``) and prints it to stdout.  Runs without
``--context`` behave exactly as before (backward compatible).

Usage:
  python tools/ghidra/run_ghidra_postscript.py \
      --tool ghidra-recon --binary <abs-sample-path> --out <abs-output.json> \
      --search-terms http,socket --expected-exports ExportA,ExportB

  Any unrecognized ``--key value`` / ``--key=value`` pair is forwarded to the
  postScript verbatim as ``--key=value``.

Exit codes: 0 = ok (postScript ran, --out artifact collected); 2 = operational
error (GHIDRA_HOME unresolved / analyzeHeadless missing / unknown tool / binary
missing / analyzeHeadless non-zero).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# UTF-8 stdout contract (#317): non-ASCII output (e.g. U+FFFD from
# decode(errors="replace")) must not crash a GBK console — stdout unified on
# UTF-8 with errors="replace" as belt-and-braces for lone surrogates.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass  # non-TTY / captured stream without reconfigure (e.g. pytest capsys)

# Tool id -> postScript file basename (must match tools/ghidra/<name>.java).
TOOL_JAVA: dict[str, str] = {
    "ghidra-recon": "GhidraRecon.java",
    "ghidra-decompile-functions": "DecompileFunctions.java",
    "ghidra-vtable-struct": "GhidraExportVtableStruct.java",
    "ghidra-evidence-annotations": "GhidraEvidenceAnnotations.java",
    "ghidra-scan-pointer": "GhidraScanPointer.java",
}

GHIDRA_HOME_MISSING_MSG = """\
error: GHIDRA_HOME not resolved — analyzeHeadless cannot be located.
  Provide it one of these ways (no hardcoded install paths are assumed):
    1) environment: set GHIDRA_HOME to your Ghidra install root
    2) analysis_state.txt: add a line `ghidra_home=<path>` in the workspace
    3) CLI: pass --ghidra-home <path>
  Then re-run this wrapper."""


# ---------------------------------------------------------------------------
# GHIDRA_HOME resolution
# ---------------------------------------------------------------------------

def parse_analysis_state(workspace: Path) -> dict[str, str]:
    """Parse a workspace analysis_state.txt into {lowercase_key: value}.

    Comment lines ('#') and non-``key=value`` lines are skipped.
    """
    result: dict[str, str] = {}
    state = Path(workspace) / "analysis_state.txt"
    if not state.is_file():
        return result
    for line in state.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip().lower()] = value.strip()
    return result


def resolve_ghidra_home(workspace: Path, cli: str | None, environ: dict[str, str]) -> str | None:
    """Resolve GHIDRA_HOME from CLI arg, then env, then analysis_state.txt.

    Returns the install root string, or None if unresolved.
    """
    if cli:
        return cli
    env_val = environ.get("GHIDRA_HOME")
    if env_val:
        return env_val
    state = parse_analysis_state(workspace)
    for key in ("ghidra_home",):
        if key in state and state[key]:
            return state[key]
    return None


def analyze_headless_path(ghidra_home: str) -> Path:
    """<GHIDRA_HOME>/support/analyzeHeadless.bat (Windows) with .sh fallback."""
    support = Path(ghidra_home) / "support"
    for name in ("analyzeHeadless.bat", "analyzeHeadless.sh", "analyzeHeadless"):
        candidate = support / name
        if candidate.is_file():
            return candidate
    return support / "analyzeHeadless.bat"  # nominal path for error reporting


# ---------------------------------------------------------------------------
# Command construction (pure — directly testable)
# ---------------------------------------------------------------------------

def build_command(
    *,
    ghidra_home: str,
    tool: str,
    binary: Path,
    post_args: list[tuple[str, str]],
    script_path: Path,
    project_dir: Path,
    project_name: str,
) -> list[str]:
    """Build the analyzeHeadless argv for a tools/ghidra postScript.

    post_args is a list of (key, value) pairs forwarded to the script as
    ``--key=value`` (the unified #293 parameterization style).
    """
    if tool not in TOOL_JAVA:
        raise ValueError(f"unknown ghidra tool: {tool!r}")
    java_file = TOOL_JAVA[tool]
    headless = analyze_headless_path(ghidra_home)
    cmd = [
        str(headless),
        str(project_dir),
        project_name,
        "-import",
        str(binary),
        "-overwrite",
        "-scriptPath",
        str(script_path),
        "-postScript",
        java_file,
    ]
    for key, value in post_args:
        cmd.append(f"--{key}={value}")
    cmd += ["-analysisTimeoutPerFile", "300"]
    return cmd


def split_forwarded(extra: list[str]) -> list[tuple[str, str]]:
    """Convert unknown argv tokens into [(key, value), ...].

    Accepts both ``--key=value`` and ``--key value`` forms. A bare ``--flag``
    (no following value) is forwarded as ``--flag=true``.
    """
    pairs: list[tuple[str, str]] = []
    i = 0
    while i < len(extra):
        tok = extra[i]
        if tok.startswith("--") and "=" in tok:
            key, _, value = tok[2:].partition("=")
            pairs.append((key, value))
            i += 1
        elif tok.startswith("-") and len(tok) > 1:
            key = tok.lstrip("-")
            if i + 1 < len(extra) and not extra[i + 1].startswith("-"):
                pairs.append((key, extra[i + 1]))
                i += 2
            else:
                pairs.append((key, "true"))
                i += 1
        else:
            # stray positional token — skip
            i += 1
    return pairs


# ---------------------------------------------------------------------------
# --context assembly (issue #306, kong analyzer.py:208-348 technique — fresh
# implementation against this tool's ghidra_decompile.v1 JSON output shape)
# ---------------------------------------------------------------------------

CONTEXT_SCHEMA = "ghidra_context.v1"
CONTEXT_SNIPPET_LINES = 10
CONTEXT_RELATIVE_LIMIT = 5

_CONTEXT_FORWARD_TRUE = ("true", "1", "yes")


def context_requested(post_args: list[tuple[str, str]]) -> bool:
    """True when the forwarded args enable --context for the postScript."""
    return dict(post_args).get("context", "").lower() in _CONTEXT_FORWARD_TRUE


def _cap_snippet(snippet: str, limit: int = CONTEXT_SNIPPET_LINES) -> str:
    """Cap a decompiled-C snippet at `limit` lines (defensive; the postScript
    already caps at 10)."""
    if not isinstance(snippet, str):
        return ""
    lines = snippet.splitlines()
    if len(lines) <= limit:
        return snippet
    return "\n".join(lines[:limit])


def _cap_items(items: list[dict], limit: int = CONTEXT_RELATIVE_LIMIT) -> list[dict]:
    out: list[dict] = []
    for item in items or []:
        if len(out) >= limit:
            break
        if not isinstance(item, dict):
            continue
        out.append({**item, "snippet": _cap_snippet(item.get("snippet", ""))})
    return out


def _render_document(entry: dict) -> str:
    """Markdown document for LLM consumption: decompilation + snippets +
    xref'd strings + recovered names (kong analyzer._build_prompt shape)."""
    fn = entry.get("function") or "?"
    addr = entry.get("address") or "?"
    context = entry["context"]
    parts = [f"## Target Function: {fn} ({addr})", "",
             "### Decompilation", "```c", entry.get("decompiled_c") or "",
             "```"]
    strings = context.get("xref_strings") or []
    if strings:
        parts += ["", "### Referenced Strings"]
        for s in strings:
            parts.append(f'- "{s.get("value")}"')
    callees = context.get("callees") or []
    if callees:
        parts += ["", "### Called Functions"]
        for c in callees:
            parts.append(f"#### {c.get('function')} ({c.get('address')})")
            parts += ["```c", c.get("snippet") or "", "```"]
    callers = context.get("callers") or []
    if callers:
        parts += ["", "### Calling Functions"]
        for c in callers:
            parts.append(f"#### {c.get('function')} ({c.get('address')})")
            parts += ["```c", c.get("snippet") or "", "```"]
    names = context.get("recovered_names") or []
    if names:
        parts += ["", "### Recovered Names"]
        for n in names:
            parts.append(f"- {n.get('name')} ({n.get('address')})")
    return "\n".join(parts)


def build_context_document(artifact: dict) -> dict:
    """Assemble the LLM-ready context document from a ghidra_decompile.v1
    artifact (the tool's JSON output shape).  Per address target: decompiled C
    + caller/callee snippets (capped at 10 lines / 5 entries) + xref'd strings
    + recovered names, plus a rendered markdown `document`.  String targets
    pass through unchanged.

    Raises ValueError when `targets` is missing (not a decompile artifact).
    """
    targets = artifact.get("targets")
    if not isinstance(targets, list):
        raise ValueError(
            "artifact has no 'targets' list — not a ghidra_decompile.v1 "
            "artifact (was --context run against a decompile-functions "
            "--out file?)")
    doc_targets: list[dict] = []
    for target in targets:
        if not isinstance(target, dict):
            doc_targets.append(target)
            continue
        if target.get("kind") != "address" or "decompiled_c" not in target:
            doc_targets.append(target)  # string targets: untouched
            continue
        raw = target.get("context") or {}
        context = {
            "callers": _cap_items(raw.get("callers") or []),
            "callees": _cap_items(raw.get("callees") or []),
            "xref_strings": raw.get("xref_strings") or [],
            "recovered_names": raw.get("recovered_names") or [],
        }
        entry = {
            "kind": target.get("kind"),
            "address": target.get("address"),
            "function": target.get("function"),
            "entry": target.get("entry"),
            "decompiled_c": target.get("decompiled_c"),
            "context": context,
        }
        entry["document"] = _render_document(entry)
        doc_targets.append(entry)
    return {
        "schema": CONTEXT_SCHEMA,
        "program": artifact.get("program"),
        "image_base": artifact.get("image_base"),
        "target_count": len(doc_targets),
        "targets": doc_targets,
    }


def emit_context_document(out_path: Path) -> None:
    """Load the decompile artifact and print the assembled context document
    to stdout; warn (do not crash the run) when the artifact is unreadable."""
    try:
        artifact = json.loads(out_path.read_text(encoding="utf-8"))
        document = build_context_document(artifact)
        print(json.dumps(document, ensure_ascii=False))
    except (OSError, ValueError) as exc:
        print(f"warning: --context assembly failed for {out_path}: {exc}",
              file=sys.stderr)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="run_ghidra_postscript.py",
        description="analyzeHeadless wrapper for tools/ghidra/*.java (issue #293)",
    )
    ap.add_argument("--tool", required=True, choices=sorted(TOOL_JAVA),
                    help="ghidra postScript tool id (see module docstring for mapping)")
    ap.add_argument("--binary", required=True, help="absolute path to the sample binary")
    ap.add_argument("--out", default=None,
                    help="absolute path for the postScript JSON artifact (forwarded as --out=...)")
    ap.add_argument("--workspace", default=None,
                    help="workspace root for analysis_state.txt discovery (default: cwd)")
    ap.add_argument("--ghidra-home", default=None,
                    help="override Ghidra install root (else GHIDRA_HOME env / analysis_state.txt)")
    ap.add_argument("--project-dir", default=None,
                    help="Ghidra project directory (default: a temp dir, removed after run)")
    ap.add_argument("--project-name", default=None,
                    help="Ghidra project name (default: <tool>-<binary-stem>)")
    ap.add_argument("--keep-project", action="store_true",
                    help="keep the temp project dir after the run (debugging)")
    args, extra = ap.parse_known_args(argv)
    args.forwarded = split_forwarded(extra)
    return args


def main(argv: list[str] | None = None, environ: dict[str, str] | None = None) -> int:
    args = parse_args(argv)
    env = dict(environ) if environ is not None else dict(os.environ)

    workspace = Path(args.workspace).resolve() if args.workspace else Path.cwd()
    ghidra_home = resolve_ghidra_home(workspace, args.ghidra_home, env)
    if not ghidra_home:
        print(GHIDRA_HOME_MISSING_MSG, file=sys.stderr)
        return 2

    headless = analyze_headless_path(ghidra_home)
    if not headless.is_file():
        print(f"error: analyzeHeadless not found at {headless} "
              f"(check GHIDRA_HOME={ghidra_home!r})", file=sys.stderr)
        return 2

    binary = Path(args.binary).expanduser()
    if not binary.is_file():
        print(f"error: --binary not found: {binary}", file=sys.stderr)
        return 2

    script_path = Path(__file__).resolve().parent  # tools/ghidra (absolute)

    # --out: resolve to absolute and forward to the postScript.
    post_args = list(args.forwarded)
    if args.out:
        out_path = Path(args.out).expanduser()
        out_path = out_path if out_path.is_absolute() else (Path.cwd() / out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        post_args = [(k, v) for (k, v) in post_args if k != "out"]
        post_args.append(("out", str(out_path)))

    project_dir = Path(args.project_dir).expanduser() if args.project_dir else None
    project_name = args.project_name or f"{args.tool.replace('-', '_')}_{binary.stem}"

    cleanup: Path | None = None
    if project_dir is None:
        cleanup = Path(tempfile.mkdtemp(prefix="ghidra_headless_"))
        project_dir = cleanup
    project_dir.mkdir(parents=True, exist_ok=True)

    cmd = build_command(
        ghidra_home=ghidra_home,
        tool=args.tool,
        binary=binary,
        post_args=post_args,
        script_path=script_path,
        project_dir=project_dir,
        project_name=project_name,
    )

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=900, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as exc:
        print(f"error: analyzeHeadless timed out: {exc}", file=sys.stderr)
        if cleanup is not None and not args.keep_project:
            _rmtree(cleanup)
        return 2
    except OSError as exc:
        print(f"error: failed to launch analyzeHeadless {headless}: {exc}", file=sys.stderr)
        if cleanup is not None and not args.keep_project:
            _rmtree(cleanup)
        return 2

    # Surface the Ghidra log (stdout+stderr merged) for the calling agent.
    if proc.stdout:
        print(proc.stdout)
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)

    rc = proc.returncode
    if rc != 0:
        print(f"error: analyzeHeadless exited {rc} (tool={args.tool})", file=sys.stderr)
        if cleanup is not None and not args.keep_project:
            _rmtree(cleanup)
        return 2

    if cleanup is not None and not args.keep_project:
        _rmtree(cleanup)

    # Collect the --out artifact.
    if args.out:
        if out_path.is_file():
            print(f"artifact: {out_path}")
            if context_requested(post_args):
                emit_context_document(out_path)
        else:
            print(f"warning: --out artifact not found after run: {out_path}", file=sys.stderr)
    return 0


def _rmtree(path: Path) -> None:
    import shutil
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:  # noqa: BLE001 - cleanup best-effort only
        pass


if __name__ == "__main__":
    sys.exit(main())
