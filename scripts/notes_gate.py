#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""notes_gate.py — verified-entry + ICD-203 notes governance (#58 S4).

Live evidence (issue #58): workers wrote `notes/C-600.md` themselves, stamped
`verify_status: pending`, with no verification event anywhere — owner ruling:
"self-written = however they like". This gate is the CHECK side of the fix:

  1. NN-slug naming   `NN-slug.md` ordinal names (01-sample-identity.md);
                      legacy claim-id carriers (C-202.md) and free-form names
                      (F300-progress-q4.md) are flagged — claim_id belongs in
                      frontmatter.
  2. ICD-203 landing  the landing fields state-mapping.md §4 maps from the
     fields           nine rules: id / title / type / status / confidence /
                      claim_id / provenance (presence-checked; value
                      semantics stay with the schema lints).
  3. Verified entry   a note whose verify_status is pending/absent — or a
                      self-stamped `passes` — is an UNVERIFIED SELF-WRITE
                      unless the claim carries verification evidence: a
                      verify event on the mission ledger (kunglao_log rows,
                      action=verify) or a terminal register status.
  4. Evidence         a note must reference >=1 fact id (facts_used) or a
     linkage          provenance artifact — unlinked notes warn (first-
                      release posture per #58: warning, then hard).

The WRITE-side interception (write_guard notes leg rejecting the write at
PreToolUse time) is the #57 sibling wiring — this tool is what the completion
path / the guard call. Gate value = interception − friction: the verification
contract must arrive at DISPATCH time (the dispatch prompt names the claim's
verification state), otherwise the first rejection a worker sees is this one.

Exit 0 = clean, 1 = errors found, 2 = usage error.

Usage:
    python scripts/notes_gate.py <WORKSPACE> [--json]

Output carries a `provenance_completeness` field (#58 MISSING_PROVENANCE
ruling: the lint must SHOW the completeness ratio, not just the per-note
error) in both text and --json modes.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from lint_facts import parse_frontmatter  # shared tolerant FM parser (#336)

RC_OK = 0
RC_ERRORS = 1
RC_USAGE = 2

# NN-slug.md: two-digit ordinal + lowercase slug (01-sample-identity.md).
NOTES_NAME_RE = re.compile(r"^\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")
CLAIM_ID_RE = re.compile(r"^C-\d{3,}$")

# ICD-203 landing fields (#58 S4; state-mapping.md §4 mapping):
#   provenance  -> rule 1 (source quality/credibility)
#   confidence  -> rule 2 (uncertainty expression)
#   type/status -> rule 3 (information vs judgment separation)
#   claim_id    -> rule 5 (customer relevance / claim linkage)
#   id/title    -> the note's identity in the result layer
REQUIRED_NOTE_FIELDS = ("id", "title", "type", "status", "confidence",
                        "claim_id", "provenance")

# register statuses that count as verification evidence for the claim
# (state-mapping.md §1: PROVEN/REFUTED/VERIFIED/NEGATIVE all sit behind the
# verifier gate — verify_status passes/partial on the fact layer).
TERMINAL_REGISTER_STATUSES = {"PROVEN", "VERIFIED", "REFUTED", "NEGATIVE"}

# note verify_status values that CLAIM verification (need backing evidence)
CLAIMED_VERIFY_STATUSES = {"passes", "partial", "fails"}

_INDEX_SKIP_NAMES = {"README.md", "_INDEX.md", "index.md"}


def note_name_violation(name: str) -> str | None:
    """The #58 naming contract for one notes/*.md filename, or None."""
    stem = Path(name).stem
    if name in _INDEX_SKIP_NAMES:
        return None
    if NOTES_NAME_RE.fullmatch(stem):
        return None
    if CLAIM_ID_RE.fullmatch(stem):
        return (f"legacy claim-id carrier name {name!r} — rename to "
                f"NN-slug.md and move the linkage into frontmatter claim_id")
    return (f"name {name!r} is not NN-slug.md (two-digit ordinal + lowercase "
            f"slug, e.g. 01-sample-identity.md)")


def read_verified_claims(ws: Path) -> set:
    """Claims with ledger verification evidence: any kunglao_log row with
    action=verify naming the claim (the kunglao_verify mirror face). Same
    tolerant read as rho_verifier.pairs_from_ledger (public iter_jsonl)."""
    from kunglao_log import iter_jsonl
    out: set = set()
    logs = Path(ws) / "runs" / "logs"
    if not logs.is_dir():
        return out
    for p in sorted(logs.glob("kunglao-*.jsonl")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for row in iter_jsonl(text.splitlines()):
            if isinstance(row, dict) and row.get("action") == "verify" \
                    and row.get("claim"):
                out.add(str(row["claim"]))
    return out


def read_terminal_claims(ws: Path) -> set:
    """Claims whose register status is terminal (verifier-gated layer)."""
    reg = Path(ws) / "claim-register.yaml"
    if not reg.is_file():
        return set()
    try:
        import yaml
        data = yaml.safe_load(reg.read_text(encoding="utf-8")) or {}
    except Exception:  # noqa: BLE001 — tolerant read (lint_facts posture)
        return set()
    claims = data.get("claims") if isinstance(data, dict) else None
    if not isinstance(claims, list):
        return set()
    return {str(c.get("id")) for c in claims
            if isinstance(c, dict) and
            str(c.get("status") or "").upper() in TERMINAL_REGISTER_STATUSES}


def _lint_one_note(p: Path, fm: dict, verified: set, terminal: set,
                   errors: list, warnings: list, with_prov_box: list) -> None:
    """One note's checks: naming-adjacent field validation + verified-entry
    + evidence linkage. Appends into errors/warnings; with_prov_box is a
    1-element list used as the provenance-present accumulator."""
    bad_name = note_name_violation(p.name)
    if bad_name:
        errors.append(("error", "NONCONFORMING_NAME",
                       f"notes/{p.name}: {bad_name}"))
    if not fm:
        errors.append(("error", "NO_FRONTMATTER",
                       f"notes/{p.name}: no frontmatter — the ICD-203 "
                       "landing fields cannot be validated"))
        return
    for f in REQUIRED_NOTE_FIELDS:
        if f not in fm or fm.get(f) in ("", None, [], {}):
            errors.append(("error", f"MISSING_{f.upper()}",
                           f"notes/{p.name}: missing mandatory "
                           f"ICD-203 landing field {f} "
                           "(state-mapping.md §4)"))
    cid = fm.get("claim_id")
    if cid is not None and str(cid) and not CLAIM_ID_RE.fullmatch(str(cid)):
        errors.append(("error", "BAD_CLAIM_ID",
                       f"notes/{p.name}: claim_id {cid!r} is not a "
                       "C-NNN id"))
    prov = fm.get("provenance")
    if isinstance(prov, list) and prov:
        with_prov_box[0] += 1
    # verified-entry check (#58 S4 ruling 2): notes enter through the
    # verified path, not the writer's discretion.
    vs = str(fm.get("verify_status") or "pending").strip().lower()
    claim = str(cid or "")
    if claim not in verified and claim not in terminal:
        if vs in CLAIMED_VERIFY_STATUSES:
            errors.append(("error", "SELF_WRITE_UNVERIFIED",
                           f"notes/{p.name}: stamps verify_status="
                           f"{vs} but claim {claim or '(none)'} has NO "
                           "verify event on the ledger and no "
                           "terminal register status — an unbacked "
                           "verification stamp"))
        else:
            errors.append(("error", "SELF_WRITE_UNVERIFIED",
                           f"notes/{p.name}: verify_status={vs} with "
                           f"no verify event for claim "
                           f"{claim or '(none)'} and no terminal "
                           "register status — unverified self-write; "
                           "run the verifier pass or link the verify "
                           "event first"))
    # evidence linkage (first-release warning per #58)
    facts_used = fm.get("facts_used")
    has_fact_ref = isinstance(facts_used, list) and bool(facts_used)
    if not has_fact_ref and not (isinstance(prov, list) and prov):
        warnings.append(("warn", "NO_EVIDENCE_LINKAGE",
                         f"notes/{p.name}: references no fact id "
                         "(facts_used) and no provenance artifact — "
                         "a note must anchor to evidence"))


def check_note(ws: Path, name: str, text: str) -> list:
    """One PENDING note's issues (public single-note face for the #57
    write-guard wiring: call this at PreToolUse time with the note text the
    writer is about to land). Returns (severity, code, message) tuples; the
    note has no filename on disk yet, so naming is checked against `name`
    and the ledger/register evidence is read live from `ws`."""
    fm, _body, _perr = parse_frontmatter(text or "")
    errors: list = []
    warnings: list = []
    _lint_one_note(Path(name), fm or {}, read_verified_claims(ws),
                   read_terminal_claims(ws), errors, warnings, [0])
    return errors + warnings


def lint_notes(ws: Path) -> dict:
    """Lint every note in <ws>/notes/. Returns {errors, warnings,
    provenance_completeness}; items are (severity, code, message) tuples."""
    ws = Path(ws)
    errors: list = []
    warnings: list = []
    notes_dir = ws / "notes"
    total = 0
    with_prov_box = [0]
    if notes_dir.is_dir():
        verified = read_verified_claims(ws)
        terminal = read_terminal_claims(ws)
        for p in sorted(notes_dir.glob("*.md")):
            total += 1
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                errors.append(("error", "UNREADABLE_NOTE",
                               f"notes/{p.name}: {exc}"))
                continue
            fm, _body, _perr = parse_frontmatter(text)
            _lint_one_note(p, fm or {}, verified, terminal, errors, warnings,
                           with_prov_box)
    return {"errors": errors, "warnings": warnings,
            "provenance_completeness": {
                "notes_total": total,
                "notes_with_provenance": with_prov_box[0],
                "ratio": round(with_prov_box[0] / total, 4) if total else 0.0,
            }}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="notes governance gate: NN-slug naming + ICD-203 landing "
                    "fields + verified-entry check (#58 S4)")
    ap.add_argument("ws", type=Path, help="workspace root (contains notes/)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    if not args.ws.is_dir():
        print(f"FAIL: workspace not found: {args.ws}", file=sys.stderr)
        return RC_USAGE
    report = lint_notes(args.ws)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for sev, code, msg in report["errors"]:
            print(f"  ERR   [{code}]  {msg}")
        for sev, code, msg in report["warnings"]:
            print(f"  warn  [{code}]  {msg}")
        pc = report["provenance_completeness"]
        print()
        print(f"provenance_completeness: {pc['notes_with_provenance']}/"
              f"{pc['notes_total']} (ratio {pc['ratio']})")
        print(f"Summary: {len(report['errors'])} errors, "
              f"{len(report['warnings'])} warnings")
    return RC_ERRORS if report["errors"] else RC_OK


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
