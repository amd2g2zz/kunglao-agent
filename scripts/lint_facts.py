#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""lint_facts.py — kunglao facts × malware-veri-notes frontmatter schema, aligned lint (#336).

Strict schema validation for workspace facts (facts/F*.md). Enforces the FULL
schema documented in malware-veri-notes/references/frontmatter-schema.md —
including the checks the external lint-notes.py does NOT cover (title/created/
last_reviewed/source enum/status×source×confidence matrix/provenance
content_sha256/credibility/alternatives). lint-notes.py remains the
cross-project gate for notes; this wrapper is the kunglao gate for facts.

Exit 0 = clean, 1 = errors found, 2 = usage error.

Usage:
    python scripts/lint_facts.py <WORKSPACE> [--json]

Design notes
------------
- Parses frontmatter with PyYAML first, falls back to a tolerant key/value
  parser (semantics ported from malware-veri-notes parse_fm.py — tolerant of
  the loose YAML-ish subset that pre-migration kunglao facts used).
- kunglao extension layer (claim/reproduce/expected/verified) is validated for
  key presence only — value semantics stay with scripts/kunglao_verify.py (#332).
- Two-layer state mapping (claim-register workflow state ↔ status+verify_status)
  lives in references/state-mapping.md; drift between layers is a WARNING here,
  never an error — the claim register is authoritative for workflow state.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover
    yaml = None

# ---------- schema constants (mirror frontmatter-schema.md) ----------

VALID_STATUS = {"PROVEN", "INFERRED", "NEGATIVE", "REFUTED", "OPEN", "DEFERRED", "VERIFIED"}
VALID_SOURCE = {
    "static-decompile", "dynamic-trace", "frida-capture", "qiling-emu",
    "vt-pivot", "public-osint", "inference", "analyst-judgment",
}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_BOUNDARY_TYPE = {
    "confirmed", "capability_not_executed", "link_not_closed", "source_derived",
    "observation", "coordinate", "pure_negative", "contradiction", "numeric",
}
OPEN_BOUNDARY_TYPES = {"capability_not_executed", "link_not_closed",
                       "source_derived", "observation", "numeric"}
EMPTY_GATE_TYPES = {"confirmed", "pure_negative", "contradiction", "coordinate"}
VALID_VERIFY_STATUS = {"pending", "passes", "partial", "fails", "stale"}
VALID_CONFIDENCE_ZH = {"可确认", "表明", "倾向于", "可关联", "不支持"}
VALID_PROVENANCE_ROLES = {"sample_raw", "decompiled_c", "disassembled_s",
                          "recompute_script", "hex_bytes_inline", "capture_log",
                          "screenshot", "public_doc", "other"}
CODE_SOURCE_VALUES = {"static-decompile", "dynamic-trace", "qiling-emu"}
NEGATIVE_SOURCE_VALUES = {"static-decompile", "dynamic-trace", "qiling-emu",
                          "vt-pivot", "public-osint"}

ID_RE = re.compile(r"^F\d{3,}-[a-z0-9]+(?:-[a-z0-9]+)*$")
CLAIM_ID_RE = re.compile(r"^C-\d{3,}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CREDIBILITY_RE = re.compile(r"^[A-F][1-6]$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

STALENESS_WARN_DAYS = 30

# status → (legal sources, legal confidence). OPEN/DEFERRED omit both.
LEGAL_COMBOS = {
    "PROVEN": (VALID_SOURCE - {"inference", "analyst-judgment"}, {"high"}),
    "INFERRED": (VALID_SOURCE, {"medium"}),
    "NEGATIVE": (NEGATIVE_SOURCE_VALUES, {"high"}),
    "REFUTED": (VALID_SOURCE - {"inference", "analyst-judgment"}, {"high"}),
    "OPEN": (set(), set()),
    "DEFERRED": (set(), set()),
    "VERIFIED": (VALID_SOURCE - {"inference", "analyst-judgment"}, {"high"}),
}

# confidence_zh 5-verb mapping (frontmatter-schema.md §confidence_zh mapping)
CONFIDENCE_ZH_RULES = [
    ("可确认", {"high"}, {"PROVEN", "VERIFIED", "REFUTED"}),
    ("表明", {"high"}, {"INFERRED"}),
    ("倾向于", {"medium"}, {"INFERRED"}),
    ("可关联", {"low"}, {"INFERRED"}, {"public-osint", "vt-pivot"}),
    ("不支持", {"high"}, {"NEGATIVE"}, NEGATIVE_SOURCE_VALUES),
]

# two-layer state mapping (references/state-mapping.md) — WARNING-only drift check
WORKFLOW_TO_GATE = {
    "PROVEN": {"passes"}, "VERIFIED": {"passes"}, "REFUTED": {"passes"},
    "NEGATIVE": {"passes", "partial"},
    "INFERRED": {"pending", "partial"},
    "OPEN": {"pending"}, "DEFERRED": {"pending"},
}

EXTENSION_FIELDS = ("claim", "reproduce", "expected", "verified")


# ---------- frontmatter parsing ----------

def _coerce_yaml_scalars(obj):
    if isinstance(obj, datetime.datetime):
        return obj.date().isoformat()
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _coerce_yaml_scalars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_coerce_yaml_scalars(v) for v in obj]
    return obj


def parse_frontmatter(text: str):
    """Return (fm, body, error). fm={} when no fence; error set when unparseable.

    Tolerant parser fallback semantics ported from malware-veri-notes
    scripts/parse_fm.py (kv + list-block subset), credited upstream."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text, "no-frontmatter"
    end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            end = i
            break
    if end is None:
        return {}, text, "no-closing-fence"
    fm_text = "\n".join(lines[1:end])
    body = "\n".join(lines[end + 1:])
    if yaml is not None:
        try:
            fm = yaml.safe_load(fm_text)
            if isinstance(fm, dict):
                return _coerce_yaml_scalars(fm), body, None
        except yaml.YAMLError:
            pass
    fm = _parse_kv_block(lines[1:end])
    return fm, body, "yaml-unparseable"


def _parse_kv_block(lines):
    """Tolerant key/value + list-of-dicts block parser (parse_fm.py semantics)."""
    fm: dict = {}
    i = 0
    while i < len(lines):
        raw = lines[i]
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        if not raw[:1].isspace() and ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val in ("", "|", ">"):
                j = i + 1
                block = []
                while j < len(lines) and (lines[j].startswith(" ") or lines[j].startswith("\t")):
                    block.append(lines[j])
                    j += 1
                fm[key] = _parse_block(block)
                i = j
                continue
            if val.startswith("[") and val.endswith("]"):
                fm[key] = _parse_inline_list(val)
                i += 1
                continue
            fm[key] = _parse_scalar(val)
        i += 1
    return fm


def _parse_block(block):
    if not block:
        return []
    if all(b.lstrip().startswith("- ") or not b.strip() for b in block):
        items = []
        groups = []
        cur = []
        for b in block:
            s = b.lstrip()
            if s.startswith("- "):
                if cur:
                    groups.append(cur)
                cur = [s[2:]]
            else:
                cur.append(s)
        if cur:
            groups.append(cur)
        for g in groups:
            if not g:
                continue
            first = g[0].strip()
            if first.startswith("{") and first.endswith("}"):
                items.append(_parse_inline_dict(first))
            elif ":" in first and not (first.startswith('"') or first.startswith("'")):
                item = {}
                k, _, v = first.partition(":")
                item[k.strip()] = _parse_scalar(v.strip())
                for extra in g[1:]:
                    if ":" in extra and not extra.lstrip().startswith("- "):
                        k2, _, v2 = extra.partition(":")
                        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", k2.strip()):
                            item[k2.strip()] = _parse_scalar(v2.strip())
                items.append(item)
            else:
                items.append(_parse_scalar(first))
        return items
    d = {}
    for b in block:
        s = b.strip()
        if ":" in s and not s.startswith("-"):
            k, _, v = s.partition(":")
            d[k.strip()] = _parse_scalar(v.strip())
    return d


def _parse_inline_dict(s):
    inner = s.strip()[1:-1].strip()
    d = {}
    depth = 0
    in_str = None
    cur = ""
    for ch in inner:
        if in_str:
            cur += ch
            if ch == in_str:
                in_str = None
        elif ch in '"\'':
            in_str = ch
            cur += ch
        elif ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            _add_kv(d, cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        _add_kv(d, cur.strip())
    return d


def _add_kv(d, pair):
    if ":" not in pair:
        return
    k, _, v = pair.partition(":")
    d[k.strip()] = _parse_scalar(v.strip())


def _parse_inline_list(s):
    inner = s.strip()[1:-1].strip()
    if not inner:
        return []
    out = []
    depth = 0
    cur = ""
    in_str = None
    for ch in inner:
        if in_str:
            cur += ch
            if ch == in_str:
                in_str = None
        elif ch in "\"'":
            in_str = ch
            cur += ch
        elif ch in "([{":
            depth += 1
            cur += ch
        elif ch in ")]}":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            out.append(_parse_item(cur.strip()))
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(_parse_item(cur.strip()))
    return out


def _parse_item(s):
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        return _parse_inline_dict(s)
    return _parse_scalar(s)


def _parse_scalar(s):
    s = s.strip()
    if not s:
        return ""
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    if s in ("null", "~"):
        return None
    if s.lower() in ("true", "yes"):
        return True
    if s.lower() in ("false", "no"):
        return False
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    if s.startswith("[") and s.endswith("]"):
        return s  # raw bracketed scalar — caller handles inline lists
    return s


def _load_fact(path: Path):
    """Return parsed frontmatter dict ({} if unparseable/no fence)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, _body, _err = parse_frontmatter(text)
    return fm or {}


# ---------- lint rules ----------

def _issue(sev, code, fact_id, msg):
    return (sev, code, f"fact {fact_id}: {msg}")


def lint_fact(fid: str, fm: dict, fact_ids: set, body: str = "") -> list:
    issues = []
    t = fm.get("type")
    if t != "fact":
        issues.append(_issue("error", "BAD_TYPE", fid,
                             f"type must be 'fact' (got {t!r})"))
    # Layer 1 + 1b mandatory — one code per field so drift reports are specific
    FIELD_CODES = {
        "id": "MISSING_ID", "title": "MISSING_TITLE", "status": "MISSING_STATUS",
        "created": "MISSING_CREATED", "last_reviewed": "MISSING_LAST_REVIEWED",
        "claim_id": "MISSING_CLAIM_ID", "boundary_type": "MISSING_BOUNDARY_TYPE",
        "promotion_gate": "MISSING_PROMOTION_GATE", "provenance": "MISSING_PROVENANCE",
        "source": "MISSING_SOURCE", "confidence": "MISSING_CONFIDENCE",
    }
    for f, code in FIELD_CODES.items():
        if f not in fm:
            issues.append(_issue("error", code, fid, f"missing mandatory field {f}"))
    # Layer 2 — omitted only for OPEN/DEFERRED (matrix default)
    if fm.get("status") in ("OPEN", "DEFERRED"):
        issues[:] = [i for i in issues if not (i[0] == "error" and i[1] in ("MISSING_SOURCE", "MISSING_CONFIDENCE"))]
    # kunglao extension layer (lint-notes.py parity: claim/reproduce/expected/verified)
    for f in EXTENSION_FIELDS:
        if f not in fm:
            issues.append(_issue("error", "MISSING_EXTENSION_FIELD", fid,
                                 f"kunglao extension layer requires {f}"))
    fid_raw = str(fm.get("id", ""))
    if fm.get("id") and not fid_raw.startswith("F"):
        issues.append(_issue("error", "BAD_FACT_ID", fid, f"id must start with 'F' (got {fid_raw!r})"))
    elif fm.get("id") and not ID_RE.fullmatch(fid_raw):
        issues.append(_issue("error", "BAD_ID_NO_SLUG", fid,
                             f"id must be <FNNN>-<slug> (got {fid_raw!r})"))
    st = fm.get("status")
    if st is not None and st not in VALID_STATUS:
        issues.append(_issue("error", "BAD_STATUS", fid,
                             f"status {st!r} not in {sorted(VALID_STATUS)} — "
                             "workflow states (PARTIALLY-VERIFIED/STAMP) belong to "
                             "claim-register, not frontmatter (see references/state-mapping.md)"))
    for date_field in ("created", "last_reviewed"):
        dv = fm.get(date_field)
        if dv is None:
            continue
        if isinstance(dv, datetime.date):
            dv = dv.isoformat()
        dv = str(dv)
        if not DATE_RE.fullmatch(dv):
            issues.append(_issue("error", "BAD_DATE", fid,
                                 f"{date_field} must be ISO-8601 YYYY-MM-DD (got {dv!r})"))
    created = str(fm.get("created", ""))
    reviewed = str(fm.get("last_reviewed", ""))
    if DATE_RE.fullmatch(created) and DATE_RE.fullmatch(reviewed):
        if reviewed < created:
            issues.append(_issue("error", "BACKDATED", fid,
                                 f"last_reviewed {reviewed} precedes created {created} — never backdate"))
        else:
            days = (datetime.date.today() - datetime.date.fromisoformat(reviewed)).days
            if days > STALENESS_WARN_DAYS:
                issues.append(_issue("warning", "STALE_LAST_REVIEWED", fid,
                                     f"last_reviewed is {days} days old (>{STALENESS_WARN_DAYS})"))
    src = fm.get("source")
    if src is not None and src not in VALID_SOURCE:
        issues.append(_issue("error", "BAD_SOURCE_ENUM", fid,
                             f"source {src!r} not in {sorted(VALID_SOURCE)}"))
    conf = fm.get("confidence")
    if conf is not None and conf not in VALID_CONFIDENCE:
        issues.append(_issue("error", "BAD_CONFIDENCE", fid,
                             f"confidence {conf!r} not in {sorted(VALID_CONFIDENCE)}"))
    # status × source × confidence matrix
    if st in LEGAL_COMBOS and src and conf:
        legal_src, legal_conf = LEGAL_COMBOS[st]
        if src not in legal_src:
            issues.append(_issue("error", "ILLEGAL_SOURCE_FOR_STATUS", fid,
                                 f"status={st} does not allow source={src!r}"))
        if conf not in legal_conf:
            issues.append(_issue("error", "ILLEGAL_CONFIDENCE_FOR_STATUS", fid,
                                 f"status={st} does not allow confidence={conf!r}"))
    cid = fm.get("claim_id")
    if cid is not None and not CLAIM_ID_RE.fullmatch(str(cid)):
        issues.append(_issue("error", "BAD_CLAIM_ID", fid,
                             f"claim_id must match C-NNN (got {cid!r})"))
    bt = fm.get("boundary_type")
    if bt is not None and bt not in VALID_BOUNDARY_TYPE:
        issues.append(_issue("error", "BAD_BOUNDARY_TYPE", fid,
                             f"boundary_type {bt!r} not in {sorted(VALID_BOUNDARY_TYPE)}"))
    gate = fm.get("promotion_gate")
    gate_text = str(gate).strip() if gate is not None else ""
    if bt in OPEN_BOUNDARY_TYPES and not gate_text:
        issues.append(_issue("error", "EMPTY_PROMOTION_GATE", fid,
                             f"boundary_type={bt!r} requires a non-empty promotion_gate "
                             "(the promotion condition, NOT a verification command)"))
    if bt in EMPTY_GATE_TYPES and gate_text:
        issues.append(_issue("error", "NONEMPTY_PROMOTION_GATE", fid,
                             f"boundary_type={bt!r} requires an empty promotion_gate (got {gate!r})"))
    if bt == "pure_negative" and st != "NEGATIVE":
        issues.append(_issue("warning", "PURE_NEG_STATUS", fid,
                             f"boundary_type=pure_negative usually pairs with status=NEGATIVE (got {st!r})"))
    # confidence_zh 5-verb consistency
    czh = fm.get("confidence_zh")
    if czh is not None and czh not in VALID_CONFIDENCE_ZH:
        issues.append(_issue("error", "BAD_CONFIDENCE_ZH", fid,
                             f"confidence_zh {czh!r} not in {sorted(VALID_CONFIDENCE_ZH)}"))
    elif czh is not None:
        for verb, confs, statuses, *rest in CONFIDENCE_ZH_RULES:
            if czh == verb:
                srcs = rest[0] if rest else None
                if conf not in confs or st not in statuses or (srcs and src not in srcs):
                    issues.append(_issue("error", "CONFIDENCE_ZH_MISMATCH", fid,
                                         f"confidence_zh={czh!r} requires confidence in {sorted(confs)}, "
                                         f"status in {sorted(statuses)}"
                                         + (f", source in {sorted(srcs)}" if srcs else "")
                                         + f" (got conf={conf!r} status={st!r} source={src!r})"))
    if bt == "pure_negative" and czh and czh != "不支持":
        issues.append(_issue("error", "PURE_NEG_CONFIDENCE", fid,
                             f"boundary_type=pure_negative requires confidence_zh='不支持' (got {czh!r})"))
    # provenance
    prov = fm.get("provenance")
    if not prov:
        issues.append(_issue("error", "MISSING_PROVENANCE", fid,
                             "provenance must be a non-empty list — every artifact the fact depends on"))
    elif isinstance(prov, list):
        for j, p in enumerate(prov):
            if not isinstance(p, dict) or "role" not in p:
                issues.append(_issue("error", "BAD_PROVENANCE", fid,
                                     f"provenance[{j}] must be a dict with a 'role' key"))
                continue
            role = str(p.get("role", ""))
            if role not in VALID_PROVENANCE_ROLES:
                issues.append(_issue("warning", "UNKNOWN_PROVENANCE_ROLE", fid,
                                     f"provenance[{j}].role={role!r} not in {sorted(VALID_PROVENANCE_ROLES)}"))
            if not any(k in p for k in ("path", "url", "bytes")):
                issues.append(_issue("error", "BAD_PROVENANCE", fid,
                                     f"provenance[{j}] needs path/url/bytes"))
            sha = str(p.get("content_sha256", ""))
            if not sha:
                issues.append(_issue("error", "PROVENANCE_NO_CONTENT_SHA256", fid,
                                     f"provenance[{j}] ({role}) missing content_sha256 — "
                                     "required for byte-exact verifier replay (ICD-203 #1)"))
            elif not SHA256_RE.fullmatch(sha):
                issues.append(_issue("error", "BAD_CONTENT_SHA256", fid,
                                     f"provenance[{j}] content_sha256 {sha!r} is not a 64-hex sha256"))
            cred = str(p.get("credibility", ""))
            if not cred:
                issues.append(_issue("error", "PROVENANCE_NO_CREDIBILITY", fid,
                                     f"provenance[{j}] ({role}) missing credibility — "
                                     "Admiralty A1-F6 source rating required (ICD-203 #1)"))
            elif not CREDIBILITY_RE.fullmatch(cred):
                issues.append(_issue("error", "BAD_CREDIBILITY", fid,
                                     f"provenance[{j}] credibility {cred!r} must match [A-F][1-6] "
                                     "(Admiralty source-reliability × information-credibility)"))
            if role == "recompute_script" and "path" in p and not str(p["path"]).startswith("tools/"):
                issues.append(_issue("warning", "RECOMPUTE_NOT_UNDER_TOOLS", fid,
                                     f"provenance[{j}] recompute_script path {p['path']!r} — "
                                     "kunglao keeps verify scripts under runs/ (documented deviation)"))
    else:
        issues.append(_issue("error", "BAD_PROVENANCE", fid,
                             "provenance must be a list of {role, path, content_sha256, credibility} dicts"))
    # code-source visibility (mirrors lint-notes.py NO_CODE_SOURCE)
    if src in CODE_SOURCE_VALUES:
        has_excerpt = "## Code excerpt" in body or "## code excerpt" in body.lower()
        has_prov_c = any(isinstance(p, dict) and p.get("role") == "decompiled_c"
                         for p in (prov if isinstance(prov, list) else []))
        if not has_excerpt and not has_prov_c:
            issues.append(_issue("error", "NO_CODE_SOURCE", fid,
                                 f"source={src!r} needs a '## Code excerpt' body section or a "
                                 "decompiled_c provenance entry — verifier cannot reproduce"))
    # verify_status (verifier gate layer)
    vs = fm.get("verify_status")
    if vs is not None and vs not in VALID_VERIFY_STATUS:
        issues.append(_issue("error", "BAD_VERIFY_STATUS", fid,
                             f"verify_status={vs!r} not in {sorted(VALID_VERIFY_STATUS)}"))
    if vs is None:
        issues.append(_issue("warning", "VERIFY_STATUS_ABSENT", fid,
                             "verify_status missing — two-layer mapping prefers an explicit verifier gate"))
    elif st in WORKFLOW_TO_GATE and vs not in WORKFLOW_TO_GATE[st]:
        issues.append(_issue("warning", "VERIFY_STATUS_STATUS_DRIFT", fid,
                             f"status={st} expects verify_status in {sorted(WORKFLOW_TO_GATE[st])} "
                             f"(got {vs!r}) — see references/state-mapping.md"))
    # edges
    for d in (fm.get("depends_on") or []):
        if d not in fact_ids:
            issues.append(_issue("error", "MISSING_DEPENDENCY", fid,
                                 f"depends_on references {d!r} but no such fact id"))
    # alternatives (ICD-203 #4 ACH trace)
    alts = fm.get("alternatives")
    if alts is not None:
        if not isinstance(alts, list) or not all(
                isinstance(a, dict) and a.get("hypothesis") and a.get("rejected_because")
                for a in alts):
            issues.append(_issue("error", "BAD_ALTERNATIVES", fid,
                                 "alternatives must be a list of {hypothesis, rejected_because} dicts"))
    return issues


def lint_workspace(ws: Path):
    """Lint every fact in <ws>/facts/ + fact-reference cross-links in notes/.

    Returns (errors, warnings); each item = (severity, code, message)."""
    facts_dir = ws / "facts"
    errors: list = []
    warnings: list = []
    if not facts_dir.is_dir():
        return [("error", "NO_FACTS_DIR", f"{facts_dir} not a directory")], []
    fact_ids: set = set()
    parsed: dict = {}
    for p in sorted(facts_dir.glob("F*.md")):
        if p.name == "_INDEX.md" or not p.name.upper().startswith("F"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        fm, body, perr = parse_frontmatter(text)
        if perr == "no-frontmatter":
            errors.append(("error", "NO_FRONTMATTER",
                           f"{p.name}: fact has no YAML frontmatter fence — cannot validate"))
            continue
        if perr and not fm:
            errors.append(("error", "UNPARSEABLE_FRONTMATTER",
                           f"{p.name}: frontmatter unparseable"))
            continue
        fid = str(fm.get("id") or "")
        if fid and fid in fact_ids:
            errors.append(("error", "DUPLICATE_ID", f"{p.name}: duplicate fact id {fid!r}"))
        if fid:
            fact_ids.add(fid)
        parsed[p] = (fm, body, perr)
    for p, (fm, body, _perr) in sorted(parsed.items()):
        fid = str(fm.get("id") or "")
        for sev, code, msg in lint_fact(fid or p.stem, fm, fact_ids, body):
            if sev == "error":
                errors.append((sev, code, f"{p.name}: {msg}"))
            else:
                warnings.append((sev, code, f"{p.name}: {msg}"))
    # notes' fact references must point at existing (slugged) fact ids
    notes_dir = ws / "notes"
    if notes_dir.is_dir():
        for p in sorted(notes_dir.glob("*.md")):
            text = p.read_text(encoding="utf-8", errors="replace")
            fm, _body, _perr = parse_frontmatter(text)
            for f in (fm.get("facts_used") or []):
                if f not in fact_ids:
                    errors.append(("error", "MISSING_FACT",
                                   f"notes/{p.name}: facts_used references {f!r} but no such fact id"))
            for d in (fm.get("depends_on") or []):
                if d not in fact_ids:
                    errors.append(("error", "MISSING_DEPENDENCY",
                                   f"notes/{p.name}: depends_on references {d!r} but no such fact id"))
    return errors, warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description="lint kunglao facts against the aligned schema (#336)")
    ap.add_argument("ws", type=Path, help="workspace root (contains facts/)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)
    errors, warnings = lint_workspace(args.ws)
    if args.json:
        print(json.dumps({"errors": errors, "warnings": warnings}, ensure_ascii=False, indent=2))
    else:
        for sev, code, msg in errors:
            print(f"  ERR   [{code}]  {msg}")
        for sev, code, msg in warnings:
            print(f"  warn  [{code}]  {msg}")
        print()
        print(f"Summary: {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
