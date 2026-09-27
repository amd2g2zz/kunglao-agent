#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_guard.py — issue 304 (satellite D4): fix-as-guard.

THE RULE: a fix is real only as a mechanical guard wired into the tool —
an assert/check (artifact-size check, marker grep, did-suffix check).
Documentation beside the tool is wishful; a "fix" without its guard does
not settle.

Landing point (extends the issue-146 doctrine): the settlement path
requires evidence that a guard exists and is wired (file + check
reference), else the settlement record is rejected.

The seam (T0): the fix record IS the failure-analysis entry
(analyses/failure-<claim>.yaml — ``next_method`` is the fix); the
settlement-forensics beat is the closure-outcome fill in
failure_analysis_gate.record_analysis (its outcome vocabulary is the
settlement verdict vocabulary). A fix settlement is the mechanical
shape: a replaced method (assumption_validity == not-justified, non-empty
next_method) closing on a WIN verdict (PROVEN | VERIFIED). Loss verdicts
(REFUTED / NEGATIVE) believe nothing and stay ungated; a win on a
justified-adequate method replaced nothing and stays ungated.

Guard evidence (the fields every fix record carries):

  guard_type        closed vocabulary: the issue's named mechanical
                    classes — artifact-size | did-suffix | marker-grep
  guard_location    the file the guard is wired into (repo-root- or
                    workspace-relative, or absolute)
  check_reference   the anchor that must greppably exist in that file

Wired evidence is checked mechanically: guard_location resolves to an
existing file (search roots: the workspace, then the repo root) whose
text contains check_reference. Anything less is a named rejection:
GUARD_MISSING (fields absent / outside the vocabulary) or
GUARD_UNRESOLVED (fields present, file or anchor not found).

Guard fire records (the liveness surface): a wired guard emits one
``guard_fired`` event (a registered EMIT_ACTIONS word; detail is the
shared JSON shape from fire_detail()) each time its check actually
fires. GUARD AUTHORS EMIT LIVENESS THEMSELVES — the wired check's own
code path calls kunglao_log.emit(action="guard_fired",
detail=fix_guard.fire_detail(guard)); this module's machinery only
READS fire rows. Until a producer fires, dormancy WARNs are
accurate-but-vacuous — accurate because the guard truly has no fire
evidence, vacuous for the same reason; the exposure is bounded by the
ledger dedup (one WARN per guard, ever). A guard that never fires
across the ledger (one-ever-fire semantics, ledger-deduped) is a
dormant guard: flagged ``guard_dormant`` (WARN-level finding) at the
per-claim settlement transaction
(register_proven_gate.emit_settlements), never a blocker. The same
pattern as the issue-127 detector liveness DORMANT flag, one layer
down: mechanism existence is not mechanism effectiveness.

Usage:
  python scripts/fix_guard.py <workspace> [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The closed guard_type vocabulary — the issue's named mechanical classes.
GUARD_TYPES = ("artifact-size", "did-suffix", "marker-grep")

# The guard-evidence fields every fix record carries (issue 304 b).
GUARD_FIELDS = ("guard_type", "guard_location", "check_reference")

# A fix settlement: replaced method (not-justified + a real next_method)
# closing on a WIN verdict. Loss verdicts believe nothing; a win on an
# adequate method replaced nothing.
FIX_WIN_OUTCOMES = ("PROVEN", "VERIFIED")
FIX_VALIDITY = "not-justified"

# Frozen rejection/flag tokens (the named reasons; callers key on them).
GUARD_MISSING = "GUARD_MISSING"
GUARD_UNRESOLVED = "GUARD_UNRESOLVED"
GUARD_DORMANT = "GUARD_DORMANT"

# The emit words (registered in event_taxonomy.EMIT_ACTIONS, sorted
# position; producers: this module + failure_analysis_gate).
GUARD_FIRED = "guard_fired"
GUARD_DORMANT_WORD = "guard_dormant"

# Guards wire into repo tools (hooks/scripts) or workspace tooling; both
# roots are searched, absolute paths pass through.
REPO_ROOT = Path(__file__).resolve().parents[1]

# Bounded ledger read for the dormancy sweep (the terminal_settlement
# posture: settlements are rare; the ledger is the organ; the scan is
# capped). This constant IS the live bound passed to kunglao_log.tail.
LEDGER_SCAN_LIMIT = 100_000

_WARN_LAST: dict[str, str] = {}


def warn(op: str, reason: str) -> None:
    """Rate-limited stderr WARN (the issue 276 _zof_warn pattern)."""
    if _WARN_LAST.get(op) == reason:
        return
    _WARN_LAST[op] = reason
    print(f"[kunglao-agent] fix_guard WARN (fail-open): {op}: {reason}",
          file=sys.stderr)


# ------------------------------------------------------------ pure faces

def is_fix_settlement(validity: str | None, next_method: str | None,
                      outcome: str | None) -> bool:
    """The mechanical fix-settlement shape (see module docstring)."""
    outcome_norm = str(outcome or "").strip().upper()
    return (outcome_norm in FIX_WIN_OUTCOMES
            and str(validity or "").strip().lower() == FIX_VALIDITY
            and bool(str(next_method or "").strip()))


def normalize_guard(record: dict | None) -> tuple[dict | None, str | None]:
    """Mechanical presence validation over GUARD_FIELDS.

    Returns (guard, None) or (None, GUARD_MISSING-named error). The
    returned guard is a NEW dict of stripped string values — the input is
    never mutated (immutability rule)."""
    if not isinstance(record, dict):
        return None, (f"{GUARD_MISSING}: guard evidence must be a mapping "
                      f"over {', '.join(GUARD_FIELDS)} (issue 304)")
    values = {k: str(record.get(k) or "").strip() for k in GUARD_FIELDS}
    missing = [k for k in GUARD_FIELDS if not values[k]]
    if missing:
        return None, (f"{GUARD_MISSING}: fix settlement carries no wired "
                      f"guard — missing {', '.join(missing)}. A fix is real "
                      f"only as a mechanical guard wired into the tool; "
                      f"documentation beside it does not settle (issue 304)")
    if values["guard_type"] not in GUARD_TYPES:
        return None, (f"{GUARD_MISSING}: guard_type "
                      f"{values['guard_type']!r} is not in the closed "
                      f"vocabulary ({', '.join(GUARD_TYPES)}) (issue 304)")
    return values, None


def resolve_guard(guard: dict, search_roots: tuple | list) -> bool:
    """Mechanical wired-evidence check: guard_location names an existing
    file whose text contains check_reference (marker grep)."""
    loc = Path(str(guard.get("guard_location") or ""))
    check = str(guard.get("check_reference") or "")
    if not loc.name or not check:
        return False
    candidates = ([loc] if loc.is_absolute()
                  else [Path(root) / loc for root in search_roots])
    for p in candidates:
        try:
            if p.is_file() and check in p.read_text(
                    encoding="utf-8", errors="replace"):
                return True
        except OSError:  # unreadable root — keep looking
            continue
    return False


def evaluate_guard(record: dict | None,
                   search_roots: tuple | list) -> tuple[dict | None,
                                                        str | None]:
    """Presence + wired resolution in one beat: the settlement-forensics
    acceptance. Returns (guard, None) or (None, named error)."""
    guard, err = normalize_guard(record)
    if err:
        return None, err
    if not resolve_guard(guard, search_roots):
        return None, (f"{GUARD_UNRESOLVED}: guard evidence does not resolve "
                      f"— {guard['guard_location']} must be an existing file "
                      f"containing {guard['check_reference']!r} (issue 304)")
    return guard, None


def fire_detail(guard: dict) -> str:
    """The shared guard_fired detail shape. A wired guard emits:
    emit(ws, <actor>, "guard_fired", claim=<claim>,
    detail=fix_guard.fire_detail(guard)). Fires are matched by the
    check_reference identity."""
    return json.dumps({k: guard[k] for k in GUARD_FIELDS},
                      ensure_ascii=False, sort_keys=True)


def dormant_guards(guarded: list | None,
                   fire_rows: list | None) -> list[dict]:
    """Pure dormancy: guarded settlements whose check_reference has ZERO
    matching guard_fired rows across the window (the rows given). Returns
    NEW dicts carrying claim + the three guard fields."""
    fired: set[str] = set()
    for r in fire_rows or []:
        if not isinstance(r, dict) \
                or str(r.get("action") or "") != GUARD_FIRED:
            continue
        try:
            d = json.loads(str(r.get("detail") or "{}"))
        except ValueError:
            continue
        if isinstance(d, dict):
            check = str(d.get("check_reference") or "").strip()
            if check:
                fired.add(check)
    out: list[dict] = []
    for g in guarded or []:
        if not isinstance(g, dict):
            continue
        check = str(g.get("check_reference") or "").strip()
        if check and check not in fired:
            out.append({"claim": str(g.get("claim") or ""),
                        **{k: str(g.get(k) or "") for k in GUARD_FIELDS}})
    return out


# ------------------------------------------------- workspace read faces

def guarded_analyses(ws: Path) -> list[dict]:
    """Guarded fix settlements on disk: analyses/failure-*.yaml entries
    carrying all three guard fields. Tolerant read — an unreadable entry
    is not a signal."""
    import yaml
    adir = Path(ws) / "analyses"
    if not adir.is_dir():
        return []
    out: list[dict] = []
    for p in sorted(adir.glob("failure-*.yaml")):
        try:
            entry = yaml.safe_load(
                p.read_text(encoding="utf-8", errors="replace")) or {}
        except Exception:  # noqa: BLE001 — unreadable is not signal
            continue
        if not isinstance(entry, dict):
            continue
        values = {k: str(entry.get(k) or "").strip() for k in GUARD_FIELDS}
        if all(values.values()):
            claim = str(entry.get("claim") or "").strip() \
                or p.stem.removeprefix("failure-")
            out.append({"claim": claim, **values})
    return out


def _already_flagged(ledger_rows: list) -> set[tuple[str, str]]:
    """(claim, check_reference) pairs a prior guard_dormant row already
    named — the persistent one-time WARN (no sentinel files)."""
    seen: set[tuple[str, str]] = set()
    for r in ledger_rows:
        if not isinstance(r, dict) \
                or str(r.get("action") or "") != GUARD_DORMANT_WORD:
            continue
        try:
            d = json.loads(str(r.get("detail") or "{}"))
        except ValueError:
            continue
        if isinstance(d, dict):
            seen.add((str(d.get("claim") or ""),
                      str(d.get("check_reference") or "")))
    return seen


def flag_dormant_guards(ws: Path, rows: list | None = None) -> list[dict]:
    """The settlement-beat face: flag every guarded fix settlement whose
    check has zero fire records across the ledger window. The window is
    the ledger TAIL bounded by LEDGER_SCAN_LIMIT (kunglao_log.tail — the
    terminal_settlement posture; the constant is the live bound, the
    one-ever-fire semantics ride the ledger dedup below). Emits one
    ``guard_dormant`` event per fresh finding (ledger-deduped — a guard
    is nagged once, ever); returns the fresh findings. Fail-open by
    contract: a WARN never blocks the settlement it rides."""
    from kunglao_log import tail
    ledger = list(rows) if rows is not None \
        else tail(Path(ws), LEDGER_SCAN_LIMIT)
    flagged = dormant_guards(guarded_analyses(ws), ledger)
    seen = _already_flagged(ledger)
    fresh = [g for g in flagged
             if (g["claim"], g["check_reference"]) not in seen]
    for g in fresh:
        try:
            from kunglao_log import emit
            emit(Path(ws), "fix_guard", GUARD_DORMANT_WORD,
                 claim=(g["claim"] or None),
                 detail=json.dumps(g, ensure_ascii=False, sort_keys=True))
        except Exception as exc:  # noqa: BLE001 — never block the settlement
            warn("flag_dormant_guards", f"{type(exc).__name__}: {exc}")
    return fresh


# ----------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="issue 304 fix-as-guard: dormancy sweep over guarded "
                    "fix settlements")
    ap.add_argument("workspace", help="workspace root")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    fresh = flag_dormant_guards(Path(a.workspace))
    if a.json:
        print(json.dumps({"flagged": fresh}, ensure_ascii=False))
    else:
        for g in fresh:
            print(f"[DORMANT] {g['claim']}: {g['guard_type']} @ "
                  f"{g['guard_location']} ({g['check_reference']}) — "
                  f"wired but never fired; a wired guard that cannot fire "
                  f"is false confidence (issue 304)")
        print(f"{len(fresh)} dormant guard(s)")
    return 0


if __name__ == "__main__":
    from _boot import force_utf8  # entry UTF-8 boot (_boot)
    force_utf8()
    sys.exit(main())
