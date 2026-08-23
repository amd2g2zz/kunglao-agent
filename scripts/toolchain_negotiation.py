#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""toolchain_negotiation.py — #451 enumerate -> choose negotiation menu.

Splits a FAILING toolchain report into the two #448 taxonomy lanes:

  - negotiable items (WARN-degradable, auto-install plan exists — DERIVED
    from toolchain_install.INSTALL_PLANS, today {pefile, floss, die}) are
    NO LONGER bare-asked, headless-refused, or silently degraded: the disk
    is enumerated FIRST (issue #451 evidence 3: D:\\tools / C:\\tools are
    tool dirs — search before asking), then a three-way-plus-paths menu
    (install / use-path:<candidate> / skip / degrade) pends through the
    #455 channel (stdout pending JSON + exit 8 + --resolve re-entry,
    decision id `install:<item>`).
  - non-negotiable HARD misses (VM channel, decompiler, the android
    chain...) keep the #304 human-event refusal (exit 4) UNCHANGED
    (#448 HUMAN-EVENT-REFUSE -> STOP; init never proxy-repairs).

Constitution alignment (#448/#474/#447): the menu is an ASK surface
(PENDING_DECISIONS); a degrade happens ONLY behind an explicit --resolve
answer — "declined" wording never appears without a real user choice
(#451 伪装 fix). Non-interactive without --assume-yes and without answers
-> structured pending list, never an auto-decline. A supplied path is
recorded as degraded WARN with honest guidance (supplied != usable,
#474); it never fakes a PASS and never writes state (a refused init's
cleanup semantics stay untouched).

The menu pends only when it is the SOLE blocker (see
has_non_negotiable_hard_fail): a mixed miss goes to exit 4 first and the
menu defers to the round after the human fixes the HARD item — one exit
code per round, both contracts byte-stable.

stdlib + sibling modules only; no I/O policy beyond read-only enumeration.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import decision_pending  # noqa: E402  (#455 pending-decision schema)
import toolchain  # noqa: E402  (report types + check re-probe)
import toolchain_install  # noqa: E402  (INSTALL_PLANS + install primitives)

# Negotiable surface is DERIVED, never hand-listed: auto-installable AND
# WARN-degradable. The decompiler (HARD degrade) and ida (mcp_url kind)
# stay on the exit-4 human-event surface.
NEGOTIABLE: frozenset[str] = frozenset(
    name for name, plan in toolchain_install.INSTALL_PLANS.items()
    if plan.kind == "auto" and plan.degrade == "WARN")

# Disk enumeration roots (issue #451 evidence 3). Overridable via
# KUNGLAO_TOOL_DIRS (os.pathsep-separated) — tests and ops inject tmp dirs.
DEFAULT_TOOL_DIRS: tuple[Path, ...] = (Path("C:/tools"), Path("D:/tools"))
_DISK_MAX_DEPTH = 2   # root + two directory levels — triage, not a disk walk
_DISK_MAX_HITS = 4    # bounded menu

_ANSWER_INSTALL = "install"
_ANSWER_SKIP = "skip"
_ANSWER_DEGRADE = "degrade"
_USE_PATH_PREFIX = "use-path:"

_DEGRADE_NOTE = (" — install declined via --resolve (#451 menu); static "
                 "analysis proceeds degraded (WARN)")
_INSTALL_FAILED_NOTE = (" — install failed via --resolve (#451); static "
                        "analysis proceeds degraded (WARN)")


def _tool_dirs() -> tuple[Path, ...]:
    """Configured enumeration roots: KUNGLAO_TOOL_DIRS > DEFAULT_TOOL_DIRS."""
    raw = os.environ.get("KUNGLAO_TOOL_DIRS", "")
    if raw.strip():
        return tuple(Path(p) for p in raw.split(os.pathsep) if p.strip())
    return DEFAULT_TOOL_DIRS


def _exe_names(name: str) -> tuple[str, ...]:
    """Executable file names a `name` tool can answer to on this platform."""
    if os.name == "nt":
        return (name, f"{name}.exe", f"{name}.bat", f"{name}.cmd")
    return (name,)


def _walk_bounded(root: Path, max_depth: int):
    """Yield files under root up to max_depth directory levels deep.
    Permission errors fail open (skipped), never raised."""
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        d, depth = stack.pop()
        try:
            entries = list(d.iterdir())
        except OSError:
            continue
        for e in entries:
            if e.is_file():
                yield e
            elif e.is_dir() and depth < max_depth:
                stack.append((e, depth + 1))


def disk_candidates(name: str,
                    tool_dirs: tuple[Path, ...] | None = None) -> list[str]:
    """Read-only disk enumeration for a missing tool (#451 evidence 3).

    Bounded: depth <= _DISK_MAX_DEPTH, at most _DISK_MAX_HITS, sorted for
    determinism. Missing roots fail open to []."""
    roots = tuple(tool_dirs) if tool_dirs is not None else _tool_dirs()
    wanted = _exe_names(name)
    hits: set[str] = set()
    for root in roots:
        for cand in _walk_bounded(root, _DISK_MAX_DEPTH):
            if cand.name in wanted:
                hits.add(str(cand))
                if len(hits) >= _DISK_MAX_HITS:
                    return sorted(hits)
    return sorted(hits)


def _negotiable_missing(report: "toolchain.ToolchainReport",
                        ) -> list["toolchain.CheckResult"]:
    """FAIL+HARD items that carry a WARN-degradable install plan."""
    return [i for i in report.items
            if i.status == toolchain.Status.FAIL
            and i.tier == toolchain.Tier.HARD
            and i.name in NEGOTIABLE]


def has_non_negotiable_hard_fail(report: "toolchain.ToolchainReport") -> bool:
    """True when any FAIL+HARD item is OUTSIDE the negotiable surface —
    the exit-4 human-event lane owns the round (#448 / #304)."""
    return any(i.status == toolchain.Status.FAIL
               and i.tier == toolchain.Tier.HARD
               and i.name not in NEGOTIABLE
               for i in report.items)


def _install_command(name: str) -> str:
    """Exact platform install command for the menu context (falls back to
    the FIXES text when no platform entry exists)."""
    try:
        return " ".join(toolchain_install.install_commands(name))
    except KeyError:
        return toolchain.FIXES.get(name, "")


def negotiation_decisions(
        report: "toolchain.ToolchainReport",
        answers: dict[str, str] | None = None,
        tool_dirs: tuple[Path, ...] | None = None,
        ) -> list["decision_pending.PendingDecision"]:
    """Build the install/use-path/skip/degrade menu for every unanswered
    negotiable miss (#451 ②: enumerate FIRST, then ask)."""
    answers = answers or {}
    decisions: list[decision_pending.PendingDecision] = []
    for item in _negotiable_missing(report):
        if answers.get(f"install:{item.name}") is not None:
            continue  # answered on a --resolve re-entry — never re-pend
        candidates = disk_candidates(item.name, tool_dirs)
        command = _install_command(item.name)
        options: tuple[str, ...] = (_ANSWER_INSTALL,)
        if candidates:
            options += tuple(f"{_USE_PATH_PREFIX}{p}" for p in candidates)
        options += (_ANSWER_SKIP, _ANSWER_DEGRADE)
        decisions.append(decision_pending.PendingDecision(
            decision_id=f"install:{item.name}",
            question=(f"Toolchain tool {item.name!r} is missing "
                      f"({item.detail}). Install via {command}, use a local "
                      f"path, skip for now, or degrade to WARN and proceed?"),
            kind=decision_pending.KIND_CHOICE,
            options=options,
            default=None,  # never a silent default (#448 must-ask)
            context={
                "install_command": command,
                "disk_candidates": candidates,
                "degrade": toolchain_install.INSTALL_PLANS[item.name].degrade,
            },
        ))
    return decisions


def _with_note(report: "toolchain.ToolchainReport", name: str, note: str,
               ) -> "toolchain.ToolchainReport":
    """Immutable degrade: a NEW report where item `name` (still FAIL+HARD)
    becomes WARN carrying `note` (mirror of toolchain_install.degrade_report,
    preserving probe/fix/next_action)."""
    new_items = []
    for i in report.items:
        if (i.name == name and i.status == toolchain.Status.FAIL
                and i.tier == toolchain.Tier.HARD):
            new_items.append(toolchain.CheckResult(
                name=i.name, status=toolchain.Status.WARN,
                tier=toolchain.Tier.HARD, detail=i.detail + note,
                root_cause=i.root_cause, probe=i.probe,
                fix=i.fix, next_action=i.next_action))
        else:
            new_items.append(i)
    return toolchain.ToolchainReport(project_type=report.project_type,
                                     items=new_items)


def apply_answers(report: "toolchain.ToolchainReport", ws: Path,
                  project_type: str,
                  answers: dict[str, str] | None,
                  task_spec: dict | None = None,
                  ) -> "toolchain.ToolchainReport":
    """Apply --resolve negotiation answers to a report; returns the report
    to continue with (immutable style: new objects, input untouched).

    Fail-closed: ALL answers are validated BEFORE any side effect — a
    malformed value raises ValueError with the decision id (the caller
    maps it to RC_ERROR), never a silent default.

    install  -> the platform plan runs (a consented, per-item form of
                --assume-yes); any successful install re-probes the whole
                toolchain ONCE (task_spec-aware, #449 review M1) and the
                non-install dispositions are re-applied on the fresh report.
    use-path -> the path must exist (else ValueError); the item degrades
                WARN with the operator-supplied location + PATH guidance
                (#474: supplied != usable — never a faked PASS, no state
                write).
    skip     -> the item STAYS FAIL (routes to the exit-4 human event).
    degrade  -> WARN with a "declined via --resolve" note (a real user
                choice — the only place that wording is allowed).
    """
    answers = dict(answers or {})
    # 1. validate everything first (no side effects on a malformed round)
    dispositions: dict[str, str] = {}
    for item in _negotiable_missing(report):
        key = f"install:{item.name}"
        if key not in answers:
            continue
        ans = str(answers[key]).strip()
        valid = ans in (_ANSWER_INSTALL, _ANSWER_SKIP, _ANSWER_DEGRADE)
        if not valid and ans.startswith(_USE_PATH_PREFIX):
            path = ans[len(_USE_PATH_PREFIX):].strip().strip('"')
            if not path or not Path(path).is_file():
                raise ValueError(
                    f"answer for decision 'install:{item.name}' names a "
                    f"path that does not exist: {path!r} (use-path answers "
                    f"must name an executable from the menu's disk "
                    f"enumeration)")
            valid = True
        if not valid:
            raise ValueError(
                f"answer for decision 'install:{item.name}' must be one of "
                f"install/use-path:<path>/skip/degrade, got {ans!r}")
        dispositions[item.name] = ans

    # 2. run consented installs (they change what a re-probe observes)
    installed_ok: list[str] = []
    for name, ans in dispositions.items():
        if ans != _ANSWER_INSTALL:
            continue
        plan = toolchain_install.INSTALL_PLANS[name]
        rc, out, err = toolchain_install._run_install_plan(
            name, plan, True, ws)
        if rc == 0:
            installed_ok.append(name)
            print(f"kunglao-negotiation: install:{name} consented via "
                  f"--resolve — installed, re-probing toolchain",
                  file=sys.stderr)
        else:
            print(f"kunglao-negotiation: install:{name} install FAILED "
                  f"({err or out or 'unknown error'}) — degrading",
                  file=sys.stderr)
            print(f"kunglao-negotiation: official guidance — "
                  f"{toolchain.FIXES.get(name, '')}", file=sys.stderr)

    # 3. base report: a fresh re-probe when an install succeeded (same
    # task_spec as the gate — #449 review M1), the original otherwise.
    if installed_ok:
        if task_spec is None:
            base = toolchain.check(ws, project_type)
        else:
            base = toolchain.check(ws, project_type, task_spec=task_spec)
    else:
        base = report

    # 4. apply the non-install dispositions (re-applied on the fresh base:
    # a degraded/supplied item is still missing in reality)
    result = base
    for name, ans in dispositions.items():
        if ans == _ANSWER_INSTALL:
            if name not in installed_ok:
                result = _with_note(result, name, _INSTALL_FAILED_NOTE)
            continue  # installed: the fresh probe's outcome is the truth
        if ans == _ANSWER_SKIP:
            print(f"kunglao-negotiation: install:{name} skipped via "
                  f"--resolve — stays a human-event FAIL (exit 4 refusal)",
                  file=sys.stderr)
            continue
        if ans == _ANSWER_DEGRADE:
            result = _with_note(result, name, _DEGRADE_NOTE)
            print(f"kunglao-negotiation: install:{name} declined via "
                  f"--resolve — degrading (WARN)", file=sys.stderr)
            continue
        if ans.startswith(_USE_PATH_PREFIX):
            path = ans[len(_USE_PATH_PREFIX):].strip().strip('"')
            result = _with_note(
                result, name,
                f" — operator-supplied path {path} (degraded WARN, #451); "
                f"add its directory to PATH to make this check PASS")
            print(f"kunglao-negotiation: install:{name} path accepted "
                  f"({path}) — item degraded WARN; add the directory to "
                  f"PATH to make the check PASS", file=sys.stderr)
    return result


def negotiate(report: "toolchain.ToolchainReport", ws: Path,
              project_type: str,
              answers: dict[str, str] | None = None,
              task_spec: dict | None = None,
              ) -> tuple["toolchain.ToolchainReport",
                         list["decision_pending.PendingDecision"]]:
    """One negotiation step: unanswered negotiable misses -> (report,
    menu decisions) for the caller to pend; all answered -> (resolved
    report, []). Raises ValueError on malformed answers (apply_answers)."""
    decisions = negotiation_decisions(report, answers=answers)
    if decisions:
        return report, decisions
    return apply_answers(report, ws, project_type, answers,
                         task_spec=task_spec), []
