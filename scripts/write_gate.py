#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""write_gate — write-side gate auditor (issue #236).

The 2026-08-12 combined fault chain (self-synthesis + self-stamping +
fake blocker) exposed that every kunglao mechanical gate was read-side
(dispatch discipline / verify anchors / convergence decisions); the
write side — how state comes to exist: verify_status stamping, expected
anchor provenance, defer reasons — was bare. This module adds the
write-side mechanical constraints, symmetric with the read-side gates.
Audit targets follow the repo's real schemas (references/schema.md,
references/guardrails.md §1b):

- R1 maker-checker stamp re-verification:
  * a notes/*.md note with verify_status=passes must have an independent
    verifier record — a runs/*-verify-*.md citing the note id with a
    positive verdict in its content (passes/CONFIRMED)
    (guardrails §1b: only an independent verifier subagent may write
    verify_status; on 2026-08-12 create-runs.py stamped notes' pending
    directly to passes with no verification record — this rule catches
    that shape).
  * a facts/*.md fact with status ∈ {PROVEN, VERIFIED} must carry
    independent-verifier evidence: verifier_sign_off (verifier_id ≠
    producer: register worker_id / provenance recompute_script), or
    verified_by_run whose named record actually exists, or a verify
    record under runs/ (verify-redteam-*.md containing CONFIRMED and
    citing the fact / verify-<fid>-*.json overall=VERIFIED or
    l2=CONFIRMED, matching the kunglao_verify.py L603-610 output shape).
- R2 independent expected anchor: a fact carrying an expected/output
  hash whose verified_by_run resolves to the same script as its
  provenance recompute_script → producer self-anchoring (the
  adapt-final.py pattern — a script self-computing expected is
  tautological verification) → violation.
- R3 defer_reason traceability: a decision-rights row number cited by a
  defer_reason in claim-register.yaml must hit a row that actually
  exists in references/decision-rights.md (parsed from the file, no
  hardcoded row counts); citing a nonexistent row = fake-blocker vector.
  Only decision-reference shapes are recognized ("decision-rights row N"
  / "治理行 N" / "决策矩阵 N" / a bare trailing "row N"), avoiding
  false positives on non-decision references like "row 5 of PE header
  table".

Stdlib only, deterministic. Output: machine-readable violation list +
human text; --json mode.
exit 0 clean / 1 violations / 2 usage error.
"""
from __future__ import annotations

import argparse
import json
import verifier_identity
import re
import sys
from pathlib import Path

from plan_drift_detector import credible_redteam_files  # #827 反模板筛选层

# fact statuses counting as "stamped" (terminal subset of references/schema.md fact.status)
FACT_VERIFIED_STATUSES = ("PROVEN", "VERIFIED")
# W-2 (#532): a fact does not escape the R1 verification requirement by
# inventing a status word. The 2026-08-20 external dump used
# VERIFIED-BY-EXTRACTION — a non-standard status carrying verified/proven
# SEMANTICS — and the FACT_VERIFIED_STATUSES membership test let it through
# untouched. Any status CLAIMING verification (standard word or invented
# one) is adjudicated as a STAMP.
_VERIFIED_SEMANTIC_RE = re.compile(r"(?:PROVEN|VERIFIED|CONFIRMED)", re.IGNORECASE)


def is_verified_semantics(status: str) -> bool:
    """True when `status` CLAIMS verification — standard word or invented one.

    W-2 (#532): the membership test on FACT_VERIFIED_STATUSES is necessary
    but not sufficient; an invented status word carrying the semantics of a
    stamp must be held to the same R1 requirement."""
    return bool(_VERIFIED_SEMANTIC_RE.search(str(status or "")))


# fields carrying a "produced anchor" (R2 applicability condition)
EXPECTED_FIELDS = ("expected", "expected_sha256", "output", "output_sha256")
# positive-verdict tokens in verification records (content-aware — "F-1: FAILED" is not independent verification)
POSITIVE_VERDICT_RE = re.compile(r"\b(?:CONFIRMED|passes)\b", re.IGNORECASE)
_SCRIPT_EXTENSIONS = (".py", ".sh", ".ps1", ".rb", ".js")

# verifier_sign_off block (same shape as blind_gate.py: yaml fence or bare block, takes verifier_id/verdict)
_SIGNOFF_BLOCK_RE = re.compile(
    r"verifier_sign_off:\s*\n(.*?)(?:\n\n|\n```|\Z)", re.DOTALL)
_SIGNOFF_FIELD_RE = re.compile(
    r"^\s*(verifier_id|verdict)\s*:\s*['\"]?([^'\"\n]+)", re.MULTILINE)
# provenance inline entries (same shape as the kunglao_verify.py F3 gate)
_INLINE_PROV_ENTRY_RE = re.compile(r"\{([^{}]*)\}")

# "row N" references — decision-reference shapes only (R3; avoids "row 5 of PE header" false positives)
_CONTEXT_ROW_RE = re.compile(
    r"decision[- ]?(?:rights|matrix)\s+row\s+#?(\d+)"
    r"|治理行\s*[:：]?\s*#?(\d+)"
    r"|决策矩阵\s*[:：]?\s*(?:row\s*)?#?(\d+)",
    re.IGNORECASE)
# bare trailing "row N" (no descriptive text around it); (?<![-\w]) excludes "arrow 5"
_STANDALONE_ROW_RE = re.compile(
    r"(?<![-\w])row\s+#?(\d+)\s*$", re.IGNORECASE | re.MULTILINE)

_CLAIM_BLOCK_RE = re.compile(r"- id:\s*(\S+)\b(.*?)(?=\n-\s*id:|\Z)", re.DOTALL)
_DEFER_REASON_LINE_RE = re.compile(r"^\s*defer_reason:\s*(.+)$", re.MULTILINE)


# ===========================================================================
# frontmatter / actor parsing
# ===========================================================================

def _parse_frontmatter(text: str) -> dict:
    """Minimal frontmatter: line-by-line 'key: value' inside a '---' fence (quotes stripped). Returns {} on failure."""
    out: dict[str, str] = {}
    if not text.startswith("---"):
        return out
    body = text.split("---", 2)
    if len(body) < 3:
        return out
    for line in body[1].splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _path_of(value: str, ws: Path) -> Path | None:
    """Extract a script path from a value (bare path or command string), resolved relative to ws; no path shape → None."""
    for tok in value.split():
        t = tok.strip().strip("\"'")
        if not t:
            continue
        if "/" in t or "\\" in t or t.endswith(_SCRIPT_EXTENSIONS):
            p = Path(t)
            return (p if p.is_absolute() else ws / p).resolve()
    return None


def _same_actor(a: str, b: str, ws: Path) -> bool:
    """Whether two actors are the same entity: exact string equality or resolution to the same script path.

    Script-shaped values (with extension/path separators) are additionally
    compared by basename — covering "adapt_final.py" vs
    "scripts/re/adapt_final.py" bare-name/prefixed spellings.
    """
    na, nb = a.strip().strip("\"'").lower(), b.strip().strip("\"'").lower()
    if na == nb:
        return True
    pa, pb = _path_of(a, ws), _path_of(b, ws)
    if pa is not None and pa == pb:
        return True
    if pa is not None and pb is not None and pa.name == pb.name:
        return True
    return False


def _parse_signoff(text: str) -> dict:
    """Extract the verifier_sign_off block's {verifier_id, verdict} from the raw fact text."""
    m = _SIGNOFF_BLOCK_RE.search(text)
    if not m:
        return {}
    out: dict[str, str] = {}
    for fm in _SIGNOFF_FIELD_RE.finditer(m.group(1)):
        out[fm.group(1).strip()] = fm.group(2).strip().strip("\"'")
    return out


def _prov_recompute_paths(text: str) -> list[str]:
    """The fact's producing-script path list (provenance role=recompute_script, same shape as F3)."""
    fm = text.split("---", 2)[1] if text.startswith("---") else text
    paths: list[str] = []
    for entry in _INLINE_PROV_ENTRY_RE.findall(fm):
        if re.search(r"role\s*:\s*recompute_script", entry, re.IGNORECASE):
            m = re.search(r"(?:path|url)\s*:\s*['\"]?([^,'\"}]+)", entry)
            if m:
                paths.append(m.group(1).strip())
    return paths


def _register_worker_id(ws: Path, claim_id: str) -> str | None:
    """The claim's worker_id / last_dispatched_worker from claim-register.yaml."""
    reg = ws / "claim-register.yaml"
    if not reg.exists() or not claim_id:
        return None
    try:
        text = reg.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for m in _CLAIM_BLOCK_RE.finditer(text):
        if m.group(1).strip().strip("\"'") == claim_id:
            block = m.group(2)
            for key in ("worker_id", "last_dispatched_worker"):
                wm = re.search(rf"\b{key}:\s*(\S+)", block)
                if wm:
                    val = wm.group(1).strip().strip("\"'")
                    if val and val.lower() not in ("null", "none", "~", ""):
                        return val
            return None
    return None


# ===========================================================================
# verification records (notes / facts each have their own shapes)
# ===========================================================================

def _note_verify_record(ws: Path, note_id: str) -> tuple[bool, str]:
    """The note's independent verification record: a runs/*-verify-*.md citing the note with a positive verdict."""
    runs = ws / "runs"
    if not runs.is_dir():
        return False, "no runs/ directory"
    for f in sorted(runs.glob("*verify*.md")):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if note_id in f.name or note_id in text:
            if POSITIVE_VERDICT_RE.search(text):
                return True, (f"verify record {f.name} cites {note_id} "
                              f"with positive verdict")
            return False, (f"verify record {f.name} cites {note_id} but "
                           f"lacks a positive verdict (passes/CONFIRMED)")
    return False, f"no runs/*-verify-*.md record citing note {note_id}"


def _fact_runs_records(fid: str, ws: Path) -> tuple[bool, str]:
    """The fact's runs/ verification record (#825 semantics).

    redteam md: needs CONFIRMED citing the fact AND a verifier-identity
    header - an unattributed verdict is not independent (#825).
    verify-<fid>-*.json: ONLY l2.verdict == CONFIRMED with
    l2.verifier_identity counts. overall=VERIFIED (L1) is the maker's own
    mechanical re-run and is NO LONGER accepted - that was the incident
    backdoor (89 L1 jsons passed R1 in the live-run sample workspace).
    """
    runs = ws / "runs"
    if not runs.is_dir():
        return False, "no runs/ directory"
    last_reason = ("no independent verifier record under runs/ (verify-"
                   "redteam-*.md CONFIRMED + verifier-identity citing the "
                   "fact, or verify-<fid>-*.json l2 CONFIRMED + "
                   "l2.verifier_identity)")
    # #827: redteam md 走 credible 筛选（存在性≠验证发生；模板簇/无 marker
    # 文件不作验证记录）；#825: 循环体内仍要求 verifier-identity——两层正交。
    for f in credible_redteam_files(runs):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if fid in text and POSITIVE_VERDICT_RE.search(text):
            ident = verifier_identity.extract_from_md(text)
            if ident:
                return True, (f"redteam record {f.name} (CONFIRMED, "
                              f"identity {ident}) cites {fid}")
            last_reason = (f"redteam record {f.name} cites {fid} with a "
                           f"positive verdict but lacks verifier-identity "
                           f"(#825)")
    for f in sorted(runs.glob(f"verify-{fid}-*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if (data.get("l2") or {}).get("verdict") == "CONFIRMED":
            ident = verifier_identity.extract_from_json(data)
            if ident:
                return True, (f"L2 CONFIRMED with identity {ident} "
                              f"in {f.name}")
            last_reason = (f"L2 CONFIRMED in {f.name} but "
                           f"l2.verifier_identity missing (#825)")
    return False, last_reason
def _verified_by_run_evidence(vbr: str, fid: str, ws: Path) -> tuple[bool, str]:
    """verified_by_run must point to a record that actually exists (MEDIUM#2: a bare string does not count).

    vbr in path/filename shape → the named record must exist in runs/ with
    a positive verdict; vbr as a verifier identity → that identity must
    have a runs/ record citing the fact.
    """
    runs = ws / "runs"
    if not runs.is_dir():
        return False, "runs/ directory missing"
    if "/" in vbr or vbr.endswith((".md", ".json")):
        cands = [ws / vbr] if "/" in vbr else []
        cands.extend(sorted(runs.glob(f"*{vbr}*")))
        for cand in cands:
            if not cand.exists():
                continue
            try:
                text = cand.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if fid in text and POSITIVE_VERDICT_RE.search(text):
                return True, (f"verified_by_run={vbr} names existing record "
                              f"{cand.name} with positive verdict")
        return False, (f"names no runs record with a positive verdict "
                       f"citing {fid}")
    return _fact_runs_records(fid, ws)


# ===========================================================================
# R1: maker-checker — stamping requires an independent verifier (notes + facts)
# ===========================================================================

def _check_note(ws: Path, p: Path) -> list[dict]:
    """A note with verify_status=passes must have an independent verification record (guardrails §1b)."""
    text = p.read_text(encoding="utf-8", errors="replace")
    fm = _parse_frontmatter(text)
    if str(fm.get("verify_status", "")).strip().lower() != "passes":
        return []
    note_id = str(fm.get("id", "")).strip() or p.stem
    ok, why = _note_verify_record(ws, note_id)
    if ok:
        return []
    return [{"rule": "R1", "file": f"notes/{p.name}",
             "detail": (f"verify_status=passes but {why} — passes must come "
                        f"from an independent verifier record (guardrails "
                        f"§1b; create-runs.py self-stamp shape)")}]


def _check_fact(ws: Path, p: Path) -> list[dict]:
    """A fact with verification-claiming status must carry independent-verifier evidence (R1+R2).

    W-2 (#532): a NON-STANDARD status carrying verified/proven semantics
    (VERIFIED-BY-EXTRACTION, proven-by-hand, ...) is adjudicated as a STAMP
    too — fail-closed, same R1 requirement as PROVEN/VERIFIED."""
    text = p.read_text(encoding="utf-8", errors="replace")
    fm = _parse_frontmatter(text)
    status = str(fm.get("status", "")).strip()
    standard = status.upper() in FACT_VERIFIED_STATUSES
    semantic = is_verified_semantics(status)
    if not standard and semantic:
        return [{"rule": "W2", "file": f"facts/{p.name}", "detail": (
            f"non-standard status {status!r} carries verified/proven semantics "
            f"— treated as a STAMP and held to the same R1 requirement; use a "
            f"status from {list(FACT_VERIFIED_STATUSES)} or downgrade to "
            f"STAMP (state that belongs in claim-register, not frontmatter)")}]
    if not semantic:
        return []
    fid = str(fm.get("id", "")).strip() or p.stem
    claim_id = str(fm.get("claim_id", "")).strip()
    worker_id = _register_worker_id(ws, claim_id)
    recompute = _prov_recompute_paths(text)
    signoff = _parse_signoff(text)
    vbr = str(fm.get("verified_by_run", "")).strip()
    rel = f"facts/{p.name}"
    violations: list[dict] = []
    evidence: str | None = None

    if signoff:
        vid = signoff.get("verifier_id", "")
        verdict = str(signoff.get("verdict", "")).upper()  # #53: no CONFIRMED default — verdict-less sign-off fails R1 evidence
        if vid and verdict == "CONFIRMED":
            if worker_id and _same_actor(vid, worker_id, ws):
                violations.append({"rule": "R1", "file": rel, "detail": (
                    f"self-stamp: verifier_sign_off verifier_id={vid} equals "
                    f"worker_id {worker_id} (maker-checker §1b)")})
            elif recompute and any(_same_actor(vid, s, ws) for s in recompute):
                violations.append({"rule": "R1", "file": rel, "detail": (
                    f"verifier_sign_off verifier_id={vid} resolves to the "
                    f"producing script {recompute} — not independent")})
            else:
                evidence = f"verifier_sign_off verifier_id={vid} independent"
    if vbr:
        if any(str(fm.get(k, "")).strip() for k in EXPECTED_FIELDS):
            for s in recompute:
                if _same_actor(vbr, s, ws):
                    violations.append({"rule": "R2", "file": rel, "detail": (
                        f"self-verify: verified_by_run={vbr} resolves to "
                        f"producing script {s} — producer self-anchors its "
                        f"own expected (adapt-final.py pattern)")})
        ok, why = _verified_by_run_evidence(vbr, fid, ws)
        if ok:
            if evidence is None:
                evidence = why
        else:
            violations.append({"rule": "R1", "file": rel,
                               "detail": f"verified_by_run={vbr} but {why}"})
    if evidence is None:
        ok, why = _fact_runs_records(fid, ws)
        if ok:
            evidence = why
        else:
            violations.append({"rule": "R1", "file": rel, "detail": (
                f"status={status} but {why} (require verifier_sign_off from "
                f"a non-producer / verified_by_run with a real record / "
                f"runs verify record)")})
    return violations


# ===========================================================================
# R3: defer_reason traceability — "row N" references must hit decision-rights.md
# ===========================================================================

def decision_rows_from_text(text: str) -> set[int]:
    """Parse the row numbers actually present in the decision-rights.md table ('| n | ...' rows whose first column is numeric)."""
    rows: set[int] = set()
    for line in text.splitlines():
        m = re.match(r"^\|\s*(\d+)\s*\|", line.strip())
        if m:
            rows.add(int(m.group(1)))
    return rows


def parse_decision_rights(path: Path) -> set[int]:
    """Read the file → the set of row numbers; missing file → empty set (workspaces without a governance layer are not audited)."""
    try:
        return decision_rows_from_text(
            path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return set()


def extract_row_references(text: str) -> list[int]:
    """Extract decision-rights row references — decision-reference shapes only, avoiding false positives.

    Two shapes: (1) decision-context references "decision-rights row N" /
    "治理行 N" / "决策矩阵 N"; (2) a bare trailing "row N" (no descriptive
    text after it, e.g. "blocked on row 99"). "row 5 of PE header table"
    does not match (descriptive text follows the number and there is no
    decision context).
    """
    out: list[int] = []
    for m in _CONTEXT_ROW_RE.finditer(text):
        out.append(int(m.group(1) or m.group(2) or m.group(3)))
    for m in _STANDALONE_ROW_RE.finditer(text):
        out.append(int(m.group(1)))
    return sorted(set(out))


def _defer_reason_of_block(block: str) -> str | None:
    """The defer_reason value inside a claim block (single line, quotes stripped); absent → None."""
    dm = _DEFER_REASON_LINE_RE.search(block)
    if not dm:
        return None
    return dm.group(1).strip().strip("\"'")


def extract_claim_defer_reason(register_text: str, claim_id: str) -> str | None:
    """Extract the given claim's defer_reason from the raw claim-register.yaml text."""
    for m in _CLAIM_BLOCK_RE.finditer(register_text):
        if m.group(1).strip().strip("\"'") == claim_id:
            return _defer_reason_of_block(m.group(2))
    return None


def _fmt_rows(rows: set[int]) -> str:
    return ", ".join(str(n) for n in sorted(rows))


def defer_reason_violations(claim_id: str, reason: str,
                            rows: set[int]) -> list[dict]:
    """Reference check for one defer_reason: citing a nonexistent row → violation record list."""
    bad = [n for n in extract_row_references(reason) if n not in rows]
    return [{"rule": "R3", "file": "claim-register.yaml", "claim_id": claim_id,
             "row": n,
             "detail": (f"defer_reason cites decision-rights row {n} which "
                        f"does not exist (rows: {_fmt_rows(rows) or '(none)'})")}
            for n in bad]


def check_workspace_defer_reasons(ws: Path) -> list[dict]:
    """Scan claim-register.yaml for all claims carrying a defer_reason (R3)."""
    reg_path = ws / "claim-register.yaml"
    if not reg_path.exists():
        return []
    rows = parse_decision_rights(ws / "references" / "decision-rights.md")
    text = reg_path.read_text(encoding="utf-8", errors="replace")
    out: list[dict] = []
    for m in _CLAIM_BLOCK_RE.finditer(text):
        claim_id = m.group(1).strip().strip("\"'")
        reason = _defer_reason_of_block(m.group(2))
        if reason:
            out.extend(defer_reason_violations(claim_id, reason, rows))
    return out


# ===========================================================================
# audit entry + CLI
# ===========================================================================

def audit_workspace(ws: Path) -> list[dict]:
    """Whole-workspace write-side audit: R1+R2 (notes/ + facts/) + R3 (claim-register.yaml)."""
    violations: list[dict] = []
    notes_dir = ws / "notes"
    if notes_dir.is_dir():
        for p in sorted(notes_dir.glob("*.md")):
            if p.name == "_INDEX.md":
                continue
            violations.extend(_check_note(ws, p))
    facts_dir = ws / "facts"
    if facts_dir.is_dir():
        for p in sorted(facts_dir.glob("*.md")):
            if p.name == "_INDEX.md":
                continue
            violations.extend(_check_fact(ws, p))
    violations.extend(check_workspace_defer_reasons(ws))
    return violations


def main(argv: list[str] | None = None) -> int:
    """CLI: write_gate.py <ws> [--json]. 0 clean / 1 violations / 2 usage error."""
    ap = argparse.ArgumentParser(description="write_gate — write-side gate auditor")
    ap.add_argument("ws", nargs="?", type=Path, help="workspace root")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable JSON output")
    args = ap.parse_args(argv)
    if args.ws is None:
        ap.print_help()
        return 2
    violations = audit_workspace(args.ws)
    if args.json:
        print(json.dumps({"ok": not violations, "violations": violations},
                         indent=2, ensure_ascii=False))
    else:
        for v in violations:
            print(f"[{v['rule']}] {v['file']}: {v['detail']}")
        if violations:
            print(f"write-gate: {len(violations)} violation(s) in "
                  f"workspace {args.ws}")
        else:
            print(f"write-gate: clean ({args.ws})")
    return 0 if not violations else 1


if __name__ == "__main__":
    from utf8_boot import force_utf8  # 811 entry UTF-8 boot (utf8_boot)
    force_utf8()
    sys.exit(main())
