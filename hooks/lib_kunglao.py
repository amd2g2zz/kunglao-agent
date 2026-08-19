#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lib_kunglao.py — kunglao-agent shared library (Phase 2 E2.4).

Consolidates duplicated implementations across hooks:
  - workspace resolution (dispatch_gate._resolve_workspace / worker_pulse._resolve_workspace / worker_budget._resolve_paths)
  - DISPATCH_RE (dispatch_gate + worker_pulse)
  - activation check (dispatch_gate hand-written JSON+expiry vs worker_pulse is_active_strict)

E2.4 criteria: lib singleton behavior-equivalent to each original
implementation — same fixture output, byte-identical diff.

Design: single module imported by all hooks; pure functions, no state.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---- dispatch prefix regex (single source) ----
# v0 protocol (legacy, still supported): "[T<N> tools=a,b] claim C-NN ..."
DISPATCH_RE = re.compile(
    r"\[T(\d)\s+tools=([^\]]+)\]\s+claim\s+(C-\d+)"
)
# v1 protocol marker — find the JSON object containing the
# "kunglao_dispatch" key. We grab the surrounding braces by scanning
# forward for balanced `{`/`}` rather than relying on a non-greedy
# capture (which fails on nested dicts/lists in v1 payloads).
DISPATCH_JSON_START_RE = re.compile(
    r"\{\s*\"kunglao_dispatch\"\s*:",
)

DISPATCH_PROTOCOL_VERSION = 1


def _balanced_json_at(text: str, start: int) -> int:
    """Return the index just past the balanced JSON object that starts at
    `start` (must point at '{'). Tracks strings + escaped chars so braces
    inside strings don't fool the counter."""
    depth = 0
    in_str = False
    escape = False
    i = start
    while i < len(text):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return -1  # unbalanced


def parse_dispatch_json(text: str) -> tuple[int, list[str], str | None, dict | None]:
    """Parse v1 protocol JSON prefix.

    Returns (tier, tools, claim_id, raw_metadata). (0, [], None, None) on
    failure — caller falls back to v0 regex.
    """
    m = DISPATCH_JSON_START_RE.search(text)
    if not m:
        return (0, [], None, None)
    end = _balanced_json_at(text, m.start())
    if end < 0:
        return (0, [], None, None)
    try:
        payload_obj = json.loads(text[m.start():end])
    except (json.JSONDecodeError, ValueError):
        return (0, [], None, None)
    payload = payload_obj.get("kunglao_dispatch")
    if not isinstance(payload, dict):
        return (0, [], None, None)
    if int(payload.get("version", 0)) != DISPATCH_PROTOCOL_VERSION:
        return (0, [], None, None)
    claim_id = payload.get("claim")
    tier = int(payload.get("tier", 0))
    if not isinstance(claim_id, str) or not re.fullmatch(r"C-\d+", claim_id):
        return (0, [], None, None)
    if tier not in (1, 2, 3):
        return (0, [], None, None)
    raw_tools = payload.get("tools") or []
    if not isinstance(raw_tools, list):
        raw_tools = []
    tools = [str(t).strip() for t in raw_tools if str(t).strip()]
    meta = {k: v for k, v in payload.items()
            if k not in ("version", "claim", "tier", "tools")}
    return (tier, tools, claim_id, meta)


def parse_dispatch(text: str) -> tuple[int, list[str], str | None]:
    """Parse '[T<N> tools=a,b] claim C-NN' -> (tier, tools, claim_id).

    (0, [], None) if absent. v1 (JSON) takes precedence over v0 (regex)."""
    v1 = parse_dispatch_json(text)
    if v1[2] is not None:
        return (v1[0], v1[1], v1[2])
    m = DISPATCH_RE.search(text)
    if not m:
        return (0, [], None)
    tier = int(m.group(1))
    tools = [t.strip() for t in m.group(2).split(",") if t.strip()]
    return (tier, tools, m.group(3))


# ---- workspace resolution (single source) ----
def resolve_workspace(payload: dict) -> Path | None:
    """Resolve the kunglao-agent workspace from a hook payload.

    Candidates (first match wins):
      1. payload['workspace'] if it has analysis_state.txt
      2. payload['cwd'] (and its child 'malware-analysis-workspace')
      3. cwd if it has analysis_state.txt
    Returns None if no candidate resolves.
    """
    def _is_ws(p: Path) -> bool:
        return (p / "analysis_state.txt").exists()

    cands: list[Path] = []
    for key in ("workspace", "cwd"):
        v = payload.get(key)
        if v:
            p = Path(v)
            cands.extend([p, p / "malware-analysis-workspace"])
    cands.append(Path.cwd())
    for c in cands:
        if _is_ws(c):
            return c
    return None


# ---- activation check (single source) ----
def is_active(ws: Path, hook_name: str, ttl_minutes: int = 30) -> bool:
    """Check kunglao-agent activation with ONE semantic (strict).

    Returns True only if: .hook_state.json exists AND expires_at is in the
    future AND hook_name is in the active set (or set is empty = all active).
    Missing state file = NOT active (strict default; legacy permissive
    default is removed).
    """
    state_file = ws / ".hook_state.json"
    if not state_file.exists():
        return False
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return False
    expires = state.get("expires_at", "")
    try:
        exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    if datetime.now(timezone.utc) >= exp:
        return False
    active = state.get("active", {})
    if isinstance(active, dict):
        hook_set = active.get("hooks", [])
    else:
        hook_set = active
    return hook_name in hook_set or not hook_set


# ---- worker-status protocol — THE single parse point (issue #37 → #444) ----
# Wire format (agents/kunglao-worker.md rule #4; append-only log):
#   "[ts] step: ... | status: in-progress"   (pipe-embedded)
#   "status: done"                            (dedicated line)
# Rule: the LAST `status:` token in the file wins. This module is the ONLY
# place in the repo that implements this parse (#444 AC-1, enforced by
# tests/test_worker_liveness_protocol.py). Every other module —
# convergence_check, worker_pulse, scripts/lib_kunglao, external_kicker,
# event_taxonomy, kunglao_status, reconcile_workers — is a CONSUMER via
# parse_worker_status(_tokens) / scan_active_workers / iter_worker_states.
# Pre-#444 these were byte-for-byte mirrors of
# scripts/convergence_check.py:_scan_active_workers (the #37 approach); a
# mirror is still two copies — #444 made this the one implementation and the
# scripts side delegate (importlib by path, unique name lib_kunglao_hooks,
# the external_kicker.should_kick precedent: bare `import lib_kunglao` is
# ambiguous under pytest because scripts/lib_kunglao.py shares the name).

STUCK_MINUTES = 20

WORKER_STATUS_RE = re.compile(r"status:\s*(\S+)")

# W-15 artifact declarations (#444): workers list deliverable paths on
# `artifacts:` lines (dedicated line OR pipe-embedded, both shapes legal —
# same duality as the status token). `artifacts: none` is the explicit
# zero-file declaration (a W-15 failure: files are the deliverable).
ARTIFACTS_RE = re.compile(
    r"(?:^|\|)\s*artifacts?\s*:\s*([^|\n]+)", re.IGNORECASE | re.MULTILINE)
_NO_ARTIFACTS_MARKERS = frozenset({"none", "-", "(none)"})


def parse_worker_status_tokens(text: str) -> list[str]:
    """All ``status:`` tokens in file order, lowercased.

    Empty list = the file has no status line (not active, not delivered).
    Consumers needing first-vs-last semantics (event_taxonomy worker_started)
    read tokens[0]/tokens[-1]; liveness is always the LAST token.
    """
    out = []
    for line in text.splitlines():
        m = WORKER_STATUS_RE.search(line)
        if m:
            out.append(m.group(1).lower())
    return out


def parse_worker_status(text: str) -> str | None:
    """The liveness token: the LAST ``status:`` line wins (append-only log)."""
    tokens = parse_worker_status_tokens(text)
    return tokens[-1] if tokens else None


def parse_declared_artifacts(text: str) -> list[str]:
    """Declared deliverable paths from ``artifacts:`` lines
    (comma/semicolon/whitespace separated, order preserved, deduped).
    [] = legacy file without declarations (W-15-exempt, #444 migration compat).
    """
    out: list[str] = []
    for m in ARTIFACTS_RE.finditer(text):
        for tok in re.split(r"[,;\s]+", m.group(1).strip()):
            if tok and tok not in out:
                out.append(tok)
    return out


def iter_worker_states(workspace: Path) -> list[dict]:
    """One row per worker-status file (single read each), across the canonical
    scan targets: workspace ``runs/`` PLUS every ``.wt-*/`` (with
    ``.kunglao-worktree`` marker) worktree ``runs/`` (v1.9.13 worktree
    isolation: worker state lives in each worker's own worktree). OSError on
    glob/read/stat skips that file. ``root`` is the workspace the file's
    declared artifacts resolve against (main root, or that worktree's
    malware-analysis-workspace root).
    """
    ws = Path(workspace)
    roots = [ws]
    try:
        for wt in ws.parent.glob(".wt-*/.kunglao-worktree"):
            root = wt.parent / "malware-analysis-workspace"
            if (root / "runs").exists():
                roots.append(root)
    except OSError:
        pass
    states = []
    for root in roots:
        runs = root / "runs"
        if not runs.exists():
            continue
        for p in runs.glob("worker-status-*.md"):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            tokens = parse_worker_status_tokens(text)
            states.append({
                "file": p,
                "root": root,
                "status": tokens[-1] if tokens else None,
                "mtime": mtime,
                "artifacts": parse_declared_artifacts(text),
            })
    return states


def scan_active_workers(workspace: Path, states: list | None = None) -> tuple[int, list]:
    """Count active + stuck workers from runs/worker-status-*.md.

    Active = a worker whose LAST ``status:`` line is ``in-progress``. Stuck =
    active files older than STUCK_MINUTES (mtime). ``states`` lets a caller
    that already ran iter_worker_states reuse the single read.

    Output shape is FROZEN (#37 consumers): ``(active, stuck)`` where each
    stuck entry is ``{"worker": <file stem>, "age_min": int}`` —
    worker_budget.check_workers_lt_3, worker_pulse flags and kunglao-decide's
    ``stale`` derivation all read exactly this.
    """
    if states is None:
        states = iter_worker_states(workspace)
    active = 0
    stuck = []
    cutoff = timedelta(minutes=STUCK_MINUTES)
    now = datetime.now(timezone.utc)
    for s in states:
        if s["status"] != "in-progress":
            continue
        active += 1
        if (now - s["mtime"]) > cutoff:
            stuck.append({"worker": s["file"].stem,
                          "age_min": int((now - s["mtime"]).total_seconds() // 60)})
    return active, stuck


def scan_done_artifact_violations(workspace: Path, states: list | None = None) -> list:
    """W-15 (#444): a worker that reports ``done`` must have its declared files.

    Opt-in: only files carrying ``artifacts:`` declarations are checked — a
    legacy done file without declarations stays readable and exempt (migration
    compat; liveness semantics unchanged for every file age). ``artifacts:
    none`` = explicit zero-file completion = W-15 failure ("a worker that
    reports 'done' without files has FAILED" — the W-15 lesson, machine path
    instead of prose). Relative paths resolve against the file's owning
    workspace root (main workspace, or the .wt-* worktree's own workspace);
    absolute paths are checked as-is.
    """
    if states is None:
        states = iter_worker_states(workspace)
    violations = []
    for s in states:
        if s["status"] != "done":
            continue
        declared = s["artifacts"]
        if not declared:
            continue  # legacy format — no declarations, W-15-exempt
        if all(t.lower() in _NO_ARTIFACTS_MARKERS for t in declared):
            violations.append({"worker": s["file"].stem,
                               "kind": "done-no-files", "missing": []})
            continue
        missing = [t for t in declared
                   if t.lower() not in _NO_ARTIFACTS_MARKERS
                   and not (Path(t) if Path(t).is_absolute() else s["root"] / t).exists()]
        if missing:
            violations.append({"worker": s["file"].stem,
                               "kind": "declared-missing", "missing": missing})
    return violations
