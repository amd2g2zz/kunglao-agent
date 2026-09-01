# -*- coding: utf-8 -*-
"""retract_claim.py - RETRACTED terminal state + dependency blast-radius reopening (#331).

A claim that was settled (PROVEN / VERIFIED / ...) can later be withdrawn —
refuted by new evidence, or superseded by a replacement verdict. Before this
script that withdrawal had no mechanical home: the orchestrator edited the
register by hand, and the claim's DOWNSTREAM dependents stayed PROVEN while
the loop kept dispatching on poisoned ground (the C-020 class of failure:
downstream trusts a dead premise).

This script is the explicit writer for the retraction transaction:

  1. Set the claim to RETRACTED (terminal) carrying
       retract_reason: refuted | superseded
       retract_by:     evidence pointer (facts/F0NN.md#L.. / verify-run / ...)
       retracted_ts:   UTC ISO-8601
  2. Walk claim_deps.yaml depends_on in reverse (transitive closure — the
     "blast radius") and re-open every dependent whose verdict is settled:
     status=OPEN, reopened_by=<retracted claim id>, promotion_attempts=0
     (so priority.py ranks them again — reopened claims dispatch normally).
     OPEN dependents are left untouched; IN_PROGRESS dependents are SKIPPED
     and reported (skipped_in_progress) — resetting an in-flight claim would
     double-dispatch it while its worker still runs; DEAD (DLQ-quarantined)
     dependents are NOT reopened — they were killed for execution exhaustion,
     not for premise; RETRACTED dependents are already withdrawn and owned by
     their own retraction event.
  3. Append an operator_action row to .convergence_ledger.jsonl
     (action=retract). Retraction is premise death, NOT execution failure:
     the failure-registry / analyses/ are never touched (issue item 6).
  4. Idempotent: re-retracting the same claim is a no-op — no re-propagation,
     no register rewrite, no extra ledger row.

Report citation gate (issue item 5): check_retracted_references() scans a
report anchors file (fact_anchors.md, or any explicit path) for fact IDs
(F0NN) whose owning claim (per facts/_INDEX.md claim_id column) is RETRACTED.
Referencing a retracted fact is a FAIL — the report input must be reworked.

Consumers: convergence_check.py and priority.py import RETRACTED /
TERMINAL_WITH_RETRACTED from here (retraction domain owner), because
status_defs.py is frozen for this change (#331). Do NOT redefine the status
sets in consumer scripts — the grep guard in tests/test_retract_claim.py
(test_retract_module_exports_single_retracted_source) pins that.

Usage:
  python retract_claim.py <workspace> <claim-id> \
      --reason refuted|superseded --by <evidence-pointer> [--dry-run]
  python retract_claim.py <workspace> --check-anchors [FILE]

Exit codes:
  0 = OK: retraction applied with no dependents reopened, idempotent no-op,
      or anchors gate clean
  1 = retraction applied with >=1 dependent reopened (informational)
  2 = error: unknown claim / invalid reason / missing register
  3 = anchors gate FAIL: the anchors file references retracted facts
"""
from __future__ import annotations

# #534: observability lifeline — module-level emit on load.
import kunglao_log  # noqa: E402

# #534: observability lifeline — module-level emit on load.
try:
    kunglao_log.emit(ws, actor="retract_claim", action="claim_migrate",
                            detail="module wired")
except NameError:
    pass

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from status_defs import TERMINAL, LedgerLineType

RETRACTED = "RETRACTED"
RETRACT_REASONS = ("refuted", "superseded")

# Terminal including the retraction state. status_defs.TERMINAL stays the
# canonical 8-value set; RETRACTED is appended here so both convergence_check
# and priority pick it up from ONE place (retraction domain owner).
TERMINAL_WITH_RETRACTED = TERMINAL | {RETRACTED}

# Dependents whose status is in this set are NOT reopened by the blast radius.
#   OPEN       — already awaiting work, nothing to reset
#   IN_PROGRESS — an in-flight worker owns it: resetting to OPEN+attempts=0
#                would let the loop dispatch the SAME claim a second time
#                while the original worker still runs (#331 review DIFF-2);
#                the skip is reported instead (skipped_in_progress)
#   RETRACTED  — already withdrawn; owned by its own retraction event
#   DEAD       — DLQ-killed for execution exhaustion, not premise
_NO_REOPEN_STATUSES = {"OPEN", "IN_PROGRESS", RETRACTED, "DEAD"}

LEDGER_NAME = ".convergence_ledger.jsonl"

# Exit codes (documented in the module docstring)
EXIT_OK = 0        # applied with no reopenings / idempotent no-op / anchors clean
EXIT_REOPENED = 1  # applied with >=1 dependent reopened (informational)
EXIT_ERROR = 2     # unknown claim / invalid reason / missing register / missing --by
EXIT_GATE_FAIL = 3  # anchors gate: report references retracted facts

_FACT_INDEX_LINE = re.compile(r"^\s*F0*(\d+)\s*\|")
_FACT_REF = re.compile(r"\bF(\d+)\b", re.IGNORECASE)


def utc_now_iso() -> str:
    """ISO-8601 UTC with a trailing Z (matches dead_letter/claim_expiry stamps)."""
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_yaml(p: Path) -> dict:
    return (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}


def _write_reg(p: Path, reg: dict) -> None:
    p.write_text(
        yaml.safe_dump(reg, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _load_reg(workspace: Path) -> tuple[list, dict, Path]:
    """Return (claims, full_register, path). Empty register if file missing."""
    p = workspace / "claim-register.yaml"
    if not p.exists():
        return [], {}, p
    reg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return reg.get("claims") or [], reg, p


def _append_ledger(workspace: Path, entry: dict) -> None:
    """Append one operator_action row. Silent on OSError (ledger is a side channel)."""
    try:
        with open(workspace / LEDGER_NAME, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def find_dependents_transitive(deps: dict, retracted_id: str) -> set:
    """Transitive closure of claims that (directly or indirectly) depend on retracted_id.

    claim_deps.yaml shape: depends_on: {child: [parents]} — the VALUE list
    holds the dependencies of the KEY claim. Reverse-walk: start from the
    retracted id, follow every claim whose parent list contains it, then
    their downstream, etc. The retracted id itself is never included.
    """
    depends_on = (deps or {}).get("depends_on", {}) or {}
    rev: dict[str, list] = {}
    for child, parents in depends_on.items():
        for parent in (parents or []):
            rev.setdefault(parent, []).append(child)
    seen: set = set()
    stack = list(rev.get(retracted_id, []) or [])
    while stack:
        cur = stack.pop()
        if cur in seen or cur == retracted_id:
            continue
        seen.add(cur)
        stack.extend(rev.get(cur, []) or [])
    return seen


def retract_claim(workspace: Path, claim_id: str, reason: str = "refuted",
                  by: str = "", dry_run: bool = False) -> dict:
    """The retraction transaction (issue #331 item 2). See module docstring.

    Returns:
      - {"ok": False, "reason": ...}          unknown claim / invalid reason
      - {"ok": True, "retracted": False, "already_retracted": True, "reopened": []}
                                              idempotent no-op (no writes)
      - {"ok": True, "retracted": True, "claim_id", "before", "reason", "by",
         "reopened": [ids]}                    applied (dry_run: reported only)
    """
    if reason not in RETRACT_REASONS:
        return {"ok": False,
                "reason": f"invalid retract_reason {reason!r} — must be one of {list(RETRACT_REASONS)}"}

    claims, reg, reg_path = _load_reg(workspace)
    claim = next((c for c in claims if c.get("id") == claim_id), None)
    if claim is None:
        return {"ok": False, "reason": f"claim {claim_id} not found"}

    before = (claim.get("status") or "").upper()
    if before == RETRACTED:
        # Idempotent: already withdrawn — no re-propagation, no rewrite, no ledger row.
        return {"ok": True, "retracted": False, "already_retracted": True, "reopened": []}

    if not by:
        # retract_by is the verification evidence pointer — a bare retraction
        # is an unsupported assertion (maker-checker: no self-stamped verdicts).
        return {"ok": False, "reason": "retract_by (evidence pointer) is required"}

    deps = _load_yaml(workspace / "claim_deps.yaml")
    dependents = find_dependents_transitive(deps, claim_id)

    reopened = []
    skipped_in_progress = []
    for c in claims:
        cid = c.get("id")
        if cid not in dependents:
            continue
        status = (c.get("status") or "UNKNOWN").upper()
        if status in _NO_REOPEN_STATUSES:
            if status == "IN_PROGRESS":
                skipped_in_progress.append(cid)
            continue
        if not dry_run:
            c["status"] = "OPEN"
            c["reopened_by"] = claim_id
            c["promotion_attempts"] = 0
        reopened.append(cid)

    if not dry_run:
        claim["status"] = RETRACTED
        claim["retract_reason"] = reason
        claim["retract_by"] = by
        claim["retracted_ts"] = utc_now_iso()
        _write_reg(reg_path, reg)
        _append_ledger(workspace, {
            "type": LedgerLineType.OPERATOR_ACTION,
            "action": "retract",
            "actor": "orchestrator",
            "claim_id": claim_id,
            "reason": reason,
            "by": by,
            "before": before,
            "after": RETRACTED,
            "reopened": sorted(reopened),
            "skipped_in_progress": sorted(skipped_in_progress),
            "ts": utc_now_iso(),
        })

    return {"ok": True, "retracted": True, "claim_id": claim_id, "before": before,
            "reason": reason, "by": by, "reopened": sorted(reopened),
            "skipped_in_progress": sorted(skipped_in_progress)}


# ---------- report citation gate (issue item 5) ----------

def retracted_claim_ids(reg: dict) -> set:
    """Claim ids currently in RETRACTED status."""
    out = set()
    for c in (reg or {}).get("claims", []) or []:
        if (c.get("status") or "").upper() == RETRACTED and c.get("id"):
            out.add(c.get("id"))
    return out


def fact_claim_map(workspace: Path) -> dict:
    """Map fact number -> owning claim id from facts/_INDEX.md.

    Index line format: F<id> | <status> | <claim_id> | <conclusion>.
    Keys are ints (F01 and F001 normalize to the same fact) so numeric
    references cannot be dodged by zero-padding tricks.
    """
    idx = workspace / "facts" / "_INDEX.md"
    if not idx.exists():
        return {}
    out = {}
    for line in idx.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _FACT_INDEX_LINE.match(line)
        if not m:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3 and parts[2]:
            out[int(m.group(1))] = parts[2]
    return out


def check_retracted_references(workspace: Path, anchors_file: Path | None = None) -> list:
    """Scan a report anchors file for references to facts owned by RETRACTED claims.

    Default anchors file: <workspace>/fact_anchors.md. A missing anchors file
    is clean (nothing to check). Returns one violation dict per offending
    reference: {"fact": "F010", "claim_id": "C-1", "ref": "the matched line"}.
    """
    anchors = anchors_file if anchors_file is not None else workspace / "fact_anchors.md"
    if not anchors.exists():
        return []
    reg = _load_yaml(workspace / "claim-register.yaml")
    retracted = retracted_claim_ids(reg)
    if not retracted:
        return []
    fact_claim = fact_claim_map(workspace)
    violations = []
    for line in anchors.read_text(encoding="utf-8", errors="replace").splitlines():
        for m in _FACT_REF.finditer(line):
            num = int(m.group(1))
            cid = fact_claim.get(num)
            if cid in retracted:
                # label = the cited token as written (F010), lookup = normalized int
                violations.append({"fact": m.group(0), "claim_id": cid, "ref": line.strip()})
    return violations


# ---------- CLI ----------

def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="retract_claim.py",
        description="Retract a claim (RETRACTED + blast-radius reopening) or gate report anchors",
    )
    parser.add_argument("workspace", help="workspace root (contains claim-register.yaml)")
    parser.add_argument("claim_id", nargs="?", help="claim id to retract (e.g. C-001)")
    parser.add_argument("--reason", choices=RETRACT_REASONS, default="refuted",
                        help="why the claim is withdrawn (default: refuted)")
    parser.add_argument("--by", default="", help="evidence pointer (facts/F0NN.md#L.., verify-run, ...)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report the blast radius without writing anything")
    parser.add_argument("--check-anchors", nargs="?", const="", metavar="FILE",
                        help="gate: FAIL when FILE (default fact_anchors.md) references retracted facts")
    args = parser.parse_args(argv)

    ws = Path(args.workspace)

    if args.check_anchors is not None:
        anchors = Path(args.check_anchors) if args.check_anchors else ws / "fact_anchors.md"
        violations = check_retracted_references(ws, anchors)
        if violations:
            for v in violations:
                print(f"ANCHORS FAIL: {v['fact']} (claim {v['claim_id']} RETRACTED) cited: {v['ref']}")
            return EXIT_GATE_FAIL
        print(f"anchors gate: clean ({anchors})")
        return EXIT_OK

    if not args.claim_id:
        parser.error("claim_id is required unless --check-anchors is given")

    if not args.by:
        parser.error("--by <evidence-pointer> is required for a retraction")

    if not (ws / "claim-register.yaml").exists():
        print(f"FAIL: no claim-register.yaml under {ws}", file=sys.stderr)
        return EXIT_ERROR

    r = retract_claim(ws, args.claim_id, reason=args.reason, by=args.by, dry_run=args.dry_run)
    if not r["ok"]:
        print(f"REJECTED: {r['reason']}", file=sys.stderr)
        return EXIT_ERROR
    if r.get("already_retracted"):
        print(f"retract {args.claim_id}: already RETRACTED — idempotent no-op")
        return EXIT_OK
    mode = "dry-run" if args.dry_run else "applied"
    print(f"retract {args.claim_id} ({mode}): {r['before']} -> RETRACTED "
          f"[reason={args.reason}, by={args.by or '-'}]")
    if r["reopened"]:
        print(f"  blast radius: reopened {r['reopened']} (reopened_by={args.claim_id})")
        if r.get("skipped_in_progress"):
            print(f"  skipped in-flight (kept IN_PROGRESS, worker still running): "
                  f"{r['skipped_in_progress']}")
        return EXIT_REOPENED
    if r.get("skipped_in_progress"):
        print(f"  skipped in-flight (kept IN_PROGRESS, worker still running): "
              f"{r['skipped_in_progress']}")
    return EXIT_OK


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
