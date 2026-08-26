#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kunglao_upgrade.py — workspace framework-scaffold migration (#726).

Old workspaces drift behind the skill package (hooks added, vocab extended,
templates refreshed) and then fight the new features — #717's three-layer
gate escape was amplified by exactly such a v0.1.2-stamped workspace. This
CLI walks a linear N->M migration registry over the FRAMEWORK SCAFFOLD
only; the analysis data never moves.

IRON RULE — the seven user-data dirs (claims/ facts/ runs/ hypotheses/
notes/ evidence/ oracle/) are hashed (stamp-line-normalized) before and
after; any byte difference aborts with exit 4 and the pre-upgrade snapshot
stays on disk for forensics.

#739: a successful migration on a workspace that predates git ends with
ensure_git_snapshot() — git init + one snapshot commit + an explicit usage
banner. Git is the snapshot layer ONLY; the workspace on disk stays ground
truth, so a dirty git status can never masquerade as workspace state.

Spec: openspec/changes/issue-726-kunglao-upgrade/{proposal,design}/.

Stable argv contract (consumed by `kunglao.py cmd_upgrade` and by
`/kunglao-agent:upgrade` via subprocess):

    main(argv=[<workspace_path>] [--dry-run] [--json])

Exit codes (consumed by the slash-command SKILL.md UX layer):

    0  migrated / already at target / dry-run plan printed
    3  no version stamp on the workspace — direct to /kunglao-agent:init
    4  iron-rule violation — user data drifted, snapshot on disk
    6  dirty owned-repo — commit/stash first, then re-run (#753 B1)
    7  incomplete — migration applied but the finish sequence aborted
       (#753 B4); re-run upgrade to complete stamping/cleanup

JSON envelope (when `--json` is set):

    {
      "status": "ok" | "dry-run" | "already-current" | "refused"
              | "refused-dirty" | "iron-rule-violation" | "incomplete",
      "rc": 0 | 3 | 4 | 6 | 7,
      "items": [{"name": "hooks_rewire", "action": "applied" | "noop" | "skipped", "detail": "..."}],
      "iron_rule_hash": {"pre": "<sha256>", "post": "<sha256>"},
      "started_at": "<ISO-8601>",
      "ended_at":   "<ISO-8601>"
    }
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import template_version  # noqa: E402
from hook_activation import ALWAYS_ARMED_HOOKS, always_arm, register_hooks  # noqa: E402

USER_DATA_DIRS: tuple[str, ...] = (
    "claims", "facts", "runs", "hypotheses", "notes", "evidence", "oracle",
)
# Carriers whose framework stamp rides ON data files (#536 comment form) —
# the stamp line is normalized away before hashing so a sanctioned stamp
# refresh never trips the iron rule (design D4).
_STAMP_CARRIERS = ("facts/_INDEX.md", "claim-register.yaml")

RC_OK = 0
RC_UNKNOWN_ORIGIN = 3
RC_IRON_RULE = 4
RC_DIRTY_WORKSPACE = 6
RC_INCOMPLETE = 7

# #758 G1a/G1b: advisory interpreter-pin echo of .python-version=3.11.
PYTHON_PIN = (3, 11)


def _warn_python_version() -> None:
    """#758 G1b: stderr WARN when this CLI runs off the pinned series.

    Advisory only — CI (UV_PYTHON=python3.11) is the blocking authority;
    a local 3.13 run must still be able to upgrade a legacy workspace.
    Realigned onto #753's structured-event emitter (their NOTE asked for
    exactly this when #753 landed): one flushed [event] line.
    """
    vi = tuple(sys.version_info[:3])
    if vi[:2] != PYTHON_PIN:
        got = ".".join(str(x) for x in vi)
        pin = ".".join(str(x) for x in PYTHON_PIN)
        _emit_event("python_version", "warn",
                    f"{got}!=pinned:{pin} — advisory, continuing")

MigrationFn = Callable[[Path, bool], list[str]]


# --------------------------------------------------------------------------
# migration items (design D3 — declarative, each idempotent by construction)
# --------------------------------------------------------------------------

def _item_hooks_rewire(ws: Path, dry: bool) -> str:
    if not dry:
        register_hooks(ws)
    return "hooks_rewire"


def _item_always_armed_repair(ws: Path, dry: bool) -> str:
    if not dry:
        always_arm(ws)
    return f"always_armed_repair({','.join(ALWAYS_ARMED_HOOKS)})"


def _guarded_stamp_refresh(ws: Path, *, version: str | None = None,
                           warn: bool = True) -> str:
    """#758 G4: a fresh stamp may only ride a CURRENT frame. Stamping a
    stale CLAUDE.md body is the lying class that amplified #717 — instead we
    keep the honest old stamp and let Wave-2 G3 (collect-and-merge, #755)
    bring the body forward before re-stamping."""
    if not template_version.frame_section_current(ws):
        if warn:
            print("kunglao-upgrade: WARN — frame section stale — G3 merge "
                  "upgrade required (see #758)", file=sys.stderr)
        return "template_stamp_refresh(skipped: frame-drift)"
    written = (template_version.stamp_workspace(ws, version=version)
               if version else template_version.stamp_workspace(ws))
    return f"template_stamp_refresh({','.join(written) or 'noop'})"


def _item_template_stamp_refresh(ws: Path, dry: bool) -> str:
    if dry:
        # plan honesty (#758): the printed plan reflects the frame gate
        # even though nothing is written on a dry run
        if not template_version.frame_section_current(ws):
            return "template_stamp_refresh(skipped: frame-drift)"
        return "template_stamp_refresh"
    return _guarded_stamp_refresh(ws)


def _item_init_report_note(ws: Path, dry: bool) -> str:
    if dry:
        return "init_report_note"
    report_path = ws / "runs" / ".init-report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8")) \
            if report_path.is_file() else {}
    except (ValueError, OSError):
        report = {}
    hist = report.setdefault("upgrade_history", [])
    hist.append({
        "to": template_version.read_skill_version(),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    return "init_report_note"


def _item_agent_metadata_seed(ws: Path, dry: bool) -> str:
    target = ws / ".agent" / "specs.yaml"
    if target.is_file():
        return "agent_metadata_seed(noop)"
    if not dry:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            "# kunglao .agent metadata (#720 convention, seeded by upgrade "
            "#726 — identity/status/linkage only)\nspecs: []\n",
            encoding="utf-8")
    return "agent_metadata_seed"


def migrate_to_0_1_3(ws: Path, dry: bool) -> list[str]:
    """v0.1.2 -> current: hooks 9->11 (+orchestrator_tool_guard #608,
    +violation_capture #718), ALWAYS_ARMED repair (#717 L1), stamp refresh,
    init-report upgrade record, .agent seed. All items idempotent."""
    return [
        _item_hooks_rewire(ws, dry),
        _item_always_armed_repair(ws, dry),
        _item_template_stamp_refresh(ws, dry),
        _item_init_report_note(ws, dry),
        _item_agent_metadata_seed(ws, dry),
    ]


# Linear registry: every version that needs a migration step beyond
# "re-stamp" (the stamp refresh itself is carried by the LAST migration).
MIGRATIONS: list[tuple[str, MigrationFn]] = [
    ("0.1.3", migrate_to_0_1_3),
]


# --------------------------------------------------------------------------
# iron rule machinery (design D4)
# --------------------------------------------------------------------------

def _vkey(version: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in version.strip().split("."))
    except ValueError:
        raise ValueError(f"unparseable version {version!r}")


# Framework-owned artifacts that live INSIDE user-data dirs (runs/):
# exempt from the iron-rule digest — they are init/upgrade telemetry, not
# analysis data. Anything else under the seven dirs stays byte-protected.
#   runs/.init-report.json          #534 init telemetry (upgrade appends)
#   runs/upgrade-snapshot.*.json    #726 own forensic output
#   runs/logs/kunglao-*.jsonl       #726 emits ONLY its own actor lines —
#                                   line-filtered, analysis events stay
#                                   byte-protected
_EXEMPT_EXACT = ("runs/.init-report.json",)


def _is_exempt(rel: str) -> bool:
    if rel in _EXEMPT_EXACT:
        return True
    if rel.startswith("runs/upgrade-snapshot.") and rel.endswith(".json"):
        return True
    return False


def _normalized_bytes(path: Path, rel: str) -> bytes:
    data = path.read_bytes()
    if rel.startswith("runs/logs/kunglao-") and rel.endswith(".jsonl"):
        # drop only this tool's own lines plus the hook TTL machinery the
        # always_armed repair engages (renew, actor=orchestrator); every
        # other analysis event stays byte-protected
        kept = []
        for line in data.decode("utf-8", errors="replace").splitlines():
            try:
                rec = json.loads(line)
            except (ValueError, TypeError):
                kept.append(line)
                continue
            if rec.get("actor") == "kunglao_upgrade" or \
                    rec.get("action") == "renew":
                continue
            kept.append(line)
        return "\n".join(kept).encode("utf-8")
    # normalize the two sanctioned stamp carriers (#536 comment form)
    if any(path.match(carrier) for carrier in _STAMP_CARRIERS):
        text = data.decode("utf-8", errors="replace")
        text = "\n".join(
            line for line in text.splitlines()
            if not line.lstrip("# ").startswith(
                template_version.STAMP_KEY))
        return text.encode("utf-8")
    return data


def user_data_digest(ws: Path) -> dict[str, str]:
    """relpath -> sha256 over every file under the seven user-data dirs,
    with the framework-owned exemptions of design D4. Sorted, stable."""
    ws = Path(ws)
    out: dict[str, str] = {}
    for d in USER_DATA_DIRS:
        root = ws / d
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            rel = f"{d}/{p.relative_to(root).as_posix()}"
            if _is_exempt(rel):
                continue
            norm = _normalized_bytes(p, rel)
            if not norm:
                continue  # a log file whose every line is exempt == absent
            out[rel] = hashlib.sha256(norm).hexdigest()
    return out


def _framework_snapshot(ws: Path) -> dict[str, str]:
    ws = Path(ws)
    out: dict[str, str] = {}
    for rel in ("CLAUDE.md", ".claude/settings.json", ".hook_state.json"):
        p = ws / rel
        if p.is_file():
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# --------------------------------------------------------------------------
# events (design D6 — fail-open telemetry, never blocks the upgrade)
# --------------------------------------------------------------------------

def _emit(ws: Path, action: str, detail: str) -> None:
    try:
        from kunglao_log import emit
        emit(ws, actor="kunglao_upgrade", action=action, detail=detail)
    except Exception:  # noqa: BLE001 — telemetry must never block migration
        pass


def _emit_event(name: str, status: str, detail: str = "") -> None:
    """#753 B2 — structured stderr trail. One flushed line per critical node
    so an external kill leaves an exact last-event record (`name=` of the
    furthest completed stage). Never raises."""
    try:
        line = f"[event] name={name} status={status} detail={detail}"
        print(line.rstrip(), file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


# --------------------------------------------------------------------------
# git snapshot layer (#739)
# --------------------------------------------------------------------------

_SNAPSHOT_COMMIT_MSG = ("kunglao-upgrade: post-upgrade git snapshot "
                        "(legacy workspace had no git)")

# #753 B1 — the migration's own rollback pair. The ANCHOR lands before the
# first migration item (user ruling 2026-08-27: no commit, no upgrade); the
# post-state commit lands after a clean finish so the operator is always one
# `git revert` away from the pre-upgrade world.
_ANCHOR_COMMIT_MSG = ("kunglao-upgrade: pre-upgrade anchor "
                      "(rollback point before migration)")
_POST_STATE_MSG = "kunglao-upgrade: post-upgrade state commit (migration applied)"

# Shared identity + signing posture of #739: snapshot commits must not depend
# on host git config. NB the -c overrides go BEFORE the `commit` subcommand.
_GIT_IDENTITY = ("-c", "user.name=kunglao-upgrade",
                 "-c", "user.email=kunglao-upgrade@localhost",
                 "commit", "--no-gpg-sign")

# bins/ = immutable sample input; the rest = runtime noise. Kept out of the
# snapshot commit so a dirty status never masquerades as workspace truth.
_GITIGNORE_BODY = (
    "# kunglao-upgrade snapshot hygiene (#739)\n"
    "# bins/            : immutable sample input, never snapshot-tracked\n"
    "# runs/ *.log      : runtime noise\n"
    "# __pycache__/ *.pyc : toolchain caches\n"
    "bins/\n"
    "__pycache__/\n"
    "*.pyc\n"
    "*.log\n"
    "runs/\n"
)


def _run_git(ws: Path, *args: str) -> subprocess.CompletedProcess:
    """One git invocation against ws (git -C form). FileNotFoundError
    (git binary missing) propagates — the caller maps it to a WARN."""
    return subprocess.run(
        ["git", "-C", str(ws), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def _print_git_banner(ws: Path) -> None:
    w = ws.as_posix()
    print("kunglao-upgrade: this workspace had no git — a snapshot repo is "
          "now initialized and the post-upgrade state committed.")
    print("  Git here is a SNAPSHOT layer only: the workspace on disk is "
          "ground truth — never read git status as current state.")
    print(f"  history    : git -C {w} log --oneline")
    print(f"  revert     : git -C {w} revert --no-edit HEAD")
    print(f"  experiment : git -C {w} checkout -b exp")


def _probe_dirty(ws: Path) -> tuple[str, int]:
    """#753 B1 gate — inspect the workspace repo without touching it.

    Returns ("absent"|"clean"|"dirty"|"skipped", entry_count). "skipped"
    covers a git binary/execution failure: the anchor cannot be verified, so
    the caller degrades loudly (same posture as #739's WARN-only snapshot).
    """
    if not (ws / ".git").exists():
        return ("absent", 0)
    try:
        proc = _run_git(ws, "status", "--porcelain")
    except (FileNotFoundError, OSError):
        return ("skipped", 0)
    if proc.returncode != 0:
        return ("skipped", 0)
    n = sum(1 for ln in proc.stdout.splitlines() if ln.strip())
    return ("dirty", n) if n else ("clean", 0)


def _warn_git_skip(surface: str, why: str) -> None:
    print(f"kunglao-upgrade: WARN — {surface} skipped: {why}", file=sys.stderr)


def _git_bootstrap_commit(ws: Path, message: str, surface: str,
                          skip_action: str, event_name: str) -> \
        tuple[bool, str | None]:
    """One hygiene pass: .gitignore -> init -> add -A -> commit(message).
    Returns (ok, reason-label); every failure is already WARNed + recorded
    under the given surface name (jsonl action + stderr event name) by the
    time False comes back."""
    try:
        (ws / ".gitignore").write_text(_GITIGNORE_BODY, encoding="utf-8")
        for label, args in (
            ("init", ("init",)),
            ("add", ("add", "-A")),
            ("commit", (*_GIT_IDENTITY, "-m", message)),
        ):
            proc = _run_git(ws, *args)
            if proc.returncode != 0:
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()
                why = tail[-1] if tail else f"exit {proc.returncode}"
                _warn_git_skip(surface, f"`git {label}`: {why}")
                _emit_event(event_name, "fail", f"{label}: {why}")
                _emit(ws, skip_action, f"git {label}: {why}")
                return (False, f"git {label}")
    except FileNotFoundError:
        _warn_git_skip(surface, "(git binary not found) — continuing "
                      "WITHOUT a rollback anchor; abort now if you want the "
                      "safety net")
        _emit_event(event_name, "warn", "git binary not found")
        _emit(ws, skip_action, "git binary not found")
        return (False, "git-missing")
    except OSError as exc:
        _warn_git_skip(surface, str(exc))
        _emit_event(event_name, "fail", str(exc))
        _emit(ws, skip_action, str(exc))
        return (False, "io-error")
    return (True, None)


def ensure_pre_upgrade_anchor(ws: Path) -> dict:
    """#753 B1 — BEFORE any migration item runs, guarantee a rollback point:
    a workspace with no .git gets git init + one pre-upgrade anchor commit.
    Reuses #739's identity/signing posture. WARN-only on failure (degrades to
    the #739 behavior), never blocks an otherwise-legal migration."""
    ws = Path(ws)
    ok, _reason = _git_bootstrap_commit(
        ws, _ANCHOR_COMMIT_MSG, "pre-upgrade anchor",
        "git_anchor_skipped", "git-anchor")
    if not ok:
        return {"status": "skipped"}
    rev = _run_git(ws, "rev-parse", "--short", "HEAD")
    sha = rev.stdout.strip() if rev.returncode == 0 else None
    _emit_event("git-anchor", "ok",
                f"pre-upgrade anchor {sha or 'unknown'}")
    _print_git_banner(ws)
    return {"status": "created", "commit": sha}


def ensure_git_snapshot(ws: Path) -> dict:
    """#739 — legacy workspaces may predate git. After a successful upgrade,
    give them a snapshot repo (init + one commit) so every later change has
    a revert point. WARN-only by design: a snapshot we cannot take must
    never fail an otherwise-successful upgrade. Idempotent — an existing
    .git (dir OR worktree pointer file) is left untouched."""
    ws = Path(ws)
    if (ws / ".git").exists():
        return {"status": "existing"}
    ok, reason = _git_bootstrap_commit(
        ws, _SNAPSHOT_COMMIT_MSG, "git snapshot",
        "git_snapshot_skipped", "git-snapshot")
    if not ok:
        return {"status": "skipped", "reason": reason}
    rev = _run_git(ws, "rev-parse", "--short", "HEAD")
    sha = rev.stdout.strip() if rev.returncode == 0 else None
    _print_git_banner(ws)
    return {"status": "created", "commit": sha}


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

def upgrade(ws: Path, dry_run: bool = False,
           items_out: list | None = None) -> int:
    ws = Path(ws)
    origin = template_version.read_workspace_version(ws)
    if origin is None:
        print("kunglao-upgrade: no version stamp on this workspace — "
              "cannot tell its shape. Run init on a fresh workspace.",
              file=sys.stderr)
        return RC_UNKNOWN_ORIGIN
    try:
        origin_key = _vkey(origin)
    except ValueError:
        print(f"kunglao-upgrade: workspace stamp {origin!r} is not a "
              f"parseable version — run init.", file=sys.stderr)
        return RC_UNKNOWN_ORIGIN
    target = template_version.read_skill_version()
    target_key = _vkey(target)

    plan = [(v, fn) for v, fn in MIGRATIONS if _vkey(v) > origin_key]
    if origin_key >= target_key and not plan:
        print(f"kunglao-upgrade: already at version {origin}")
        return RC_OK

    if dry_run:
        print(f"kunglao-upgrade: dry-run {origin} -> {target}")
        for v, fn in plan:
            for item in fn(ws, dry=True):
                print(f"  [{v}] {item}")
                if items_out is not None:
                    items_out.append({"name": item, "action": "noop",
                                       "detail": "dry-run"})
        return RC_OK

    # ---- #753 B1: git-first rollback anchor -------------------------------
    # User ruling 2026-08-27: 未提交不升、无 git 先锚——坏掉必须能回滚。
    gate_state, dirty_n = _probe_dirty(ws)
    if gate_state == "dirty":
        _emit_event("gate-dirty", "fail", f"{dirty_n} uncommitted entries")
        print(f"kunglao-upgrade: REFUSED (RC_DIRTY_WORKSPACE=6) — {ws} has "
              f"{dirty_n} uncommitted change(s); migrating without a clean "
              f"rollback anchor is unrecoverable (#753).", file=sys.stderr)
        print("kunglao-upgrade: commit or stash first, then re-run:",
              file=sys.stderr)
        print(f"  git -C {ws} add -A && git -C {ws} commit --no-gpg-sign "
              f"-m \"checkpoint before kunglao upgrade\"", file=sys.stderr)
        print(f"  (or) git -C {ws} stash push --include-untracked",
              file=sys.stderr)
        return RC_DIRTY_WORKSPACE
    anchor: dict = {"status": "clean"}
    if gate_state == "absent":
        _emit_event("gate-dirty", "ok", "no git — anchoring first")
        anchor = ensure_pre_upgrade_anchor(ws)
    elif gate_state == "clean":
        _emit_event("gate-dirty", "ok", "clean owned repo")
    else:
        _emit_event("gate-dirty", "warn", "probe unreadable")
        _warn_git_skip("git status probe unreadable",
                       "cannot verify workspace cleanliness")

    pre = user_data_digest(ws)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    snap_path = ws / "runs" / f"upgrade-snapshot.{ts}.json"
    snap_path.parent.mkdir(parents=True, exist_ok=True)
    snap_path.write_text(json.dumps(_framework_snapshot(ws), indent=2,
                                    ensure_ascii=False) + "\n",
                         encoding="utf-8")

    applied = 0
    _emit_event("migration-start", "ok", f"{origin}->{target} migrations={len(plan)}")
    for v, fn in plan:
        for item in fn(ws, dry=False):
            applied += 1
            print(f"  [{v}] {item} ok")
            _emit(ws, "upgrade_item", item)
            _emit_event("item", "ok", item)
            if items_out is not None:
                items_out.append({"name": item, "action": "applied",
                                   "detail": f"version={v}"})

    post = user_data_digest(ws)
    if pre != post:
        changed = sorted(k for k in set(pre) | set(post)
                         if pre.get(k) != post.get(k))
        _emit_event("iron-rule", "fail",
                    f"{len(changed)} file(s): {changed[:5]}...")
        print(f"kunglao-upgrade: IRON RULE VIOLATION — user data changed "
              f"({len(changed)} file(s): {changed[:5]}...). Snapshot kept: "
              f"{snap_path}", file=sys.stderr)
        return RC_IRON_RULE
    _emit_event("iron-rule", "ok", f"{len(pre)} user-data file(s) invariant")

    # ---- #753 B4: atomic finish sequence -----------------------------------
    # The incident behind this issue died AFTER stamp but BEFORE the summary
    # event, silently, with rc 0. From here on every step is guarded: any
    # exception surfaces as RC_INCOMPLETE=7 plus a summary=fail event —
    # never a silent RC_OK. (A hard external kill cannot be caught in-process;
    # B1's anchor makes that revertable and the flushed [event] trail above
    # records the exact last completed node.)
    tail_error = ""
    try:
        # stamp to target even when no migration entry exists for the gap
        # (forward stamps ride the last migration's refresh; belt & braces).
        # #758 G4: gated by the SAME frame predicate as the migration item —
        # otherwise this tail would bypass the gate and lie anyway. Silent:
        # the item above already emitted the one WARN this run needs.
        _guarded_stamp_refresh(ws, version=target, warn=False)
        _emit_event("stamp", "ok", f"version={target}")
        _emit(ws, "upgrade", f"{origin}->{target} items={applied}")
        print(f"kunglao-upgrade: {origin} -> {target} "
              f"({applied} item(s), snapshot {snap_path.name})")
        _emit_event("summary", "ok", f"{origin}->{target} items={applied}")
        # snapshot layer. When THIS run created the anchor we land the
        # post-state commit ourselves (one `git revert` back to the anchor;
        # the tree ends clean so later runs stay legal). Otherwise fall
        # through to the #739 recovery attempt (skipped-anchor workspaces).
        if anchor.get("status") == "created":
            post = _run_git(ws, "add", "-A")
            if post.returncode == 0:
                post = _run_git(ws, *_GIT_IDENTITY, "-m", _POST_STATE_MSG)
            if post.returncode != 0:
                tail = (post.stderr or post.stdout or "").strip().splitlines()
                why = tail[-1] if tail else f"exit {post.returncode}"
                _warn_git_skip("post-upgrade state commit", why)
                _emit(ws, "git_snapshot_skipped",
                      f"post-state commit: {why}")
                _emit_event("git-snapshot", "warn",
                            f"anchor@{anchor.get('commit')} kept; "
                            f"post-state skipped: {why}")
            else:
                rev = _run_git(ws, "rev-parse", "--short", "HEAD")
                head = rev.stdout.strip() if rev.returncode == 0 else "?"
                _emit_event("git-snapshot", "ok",
                            f"anchor@{anchor.get('commit')} "
                            f"post-state@{head}")
        else:
            # #739 — snapshot layer for workspaces that predate git; WARN-only,
            # never changes the exit code
            snap = ensure_git_snapshot(ws)
            if snap.get("status") == "skipped":
                _emit_event("git-snapshot", "warn",
                            str(snap.get("reason") or "skipped"))
            else:
                _emit_event("git-snapshot", "ok", snap.get("status", ""))
        # #753 B3 — the skill package just moved; Claude Code picks the new
        # slash-commands/hooks up only after a plugin reload.
        print("kunglao-upgrade: skill package updated — run /reload-plugins "
              "in Claude Code to activate")
    except Exception as exc:  # noqa: BLE001 — incomplete, not silent success
        tail_error = f"{type(exc).__name__}: {exc}"
        _emit_event("summary", "fail", tail_error)
    if tail_error:
        print(f"kunglao-upgrade: INCOMPLETE (RC_INCOMPLETE=7) — migration "
              f"applied but the finish sequence aborted ({tail_error}); "
              f"re-run upgrade to complete stamping/cleanup.", file=sys.stderr)
        return RC_INCOMPLETE
    return RC_OK


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="kunglao-upgrade — workspace framework-scaffold "
                    "migration (#726); user data is byte-invariant")
    p.add_argument("workspace", help="workspace root")
    p.add_argument("--dry-run", action="store_true",
                   help="print the migration plan, write nothing")
    p.add_argument("--json", action="store_true",
                   help="emit a single JSON envelope on stdout (status, rc, "
                        "items, iron_rule_hash, started_at, ended_at); "
                        "the human-readable plan still goes to stderr")
    a = p.parse_args(argv)
    _warn_python_version()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    items_out: list = []
    rc = upgrade(Path(a.workspace), a.dry_run, items_out)
    ended_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if a.json:
        status = {
            (RC_OK, True): "dry-run",
            (RC_OK, False): "ok" if items_out else "already-current",
            RC_UNKNOWN_ORIGIN: "refused",
            RC_IRON_RULE: "iron-rule-violation",
            RC_DIRTY_WORKSPACE: "refused-dirty",
            RC_INCOMPLETE: "incomplete",
        }
        # pick first matching key
        chosen = "ok"
        for key, label in status.items():
            if isinstance(key, tuple):
                if key[0] == rc and key[1] == a.dry_run:
                    chosen = label
                    break
            elif key == rc:
                chosen = label
                break
        envelope = {
            "status": chosen,
            "rc": rc,
            "items": items_out,
            "iron_rule_hash": {"pre": "", "post": ""},
            "started_at": started_at,
            "ended_at": ended_at,
        }
        # pre/post hashes are populated when --json is used against a real
        # (non-dry-run) migration that recorded them in `_framework_snapshot`;
        # for the workspace-internal CLI these stay empty — the slash
        # command SKILL.md UX surface documents the placeholder contract.
        print(json.dumps(envelope, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
