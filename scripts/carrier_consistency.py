#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""carrier_consistency.py — #829 cross-carrier consistency gate (L2).

Assertions (fail-closed on CONVERGED only; checker exceptions are treated
as drift by the caller decide() — an unverified CONVERGED never stands):
  (a) register stamped claim (PROVEN/VERIFIED) iff linked fact stamped.
      Carrier-record ABSENCE is not drift (sparse workspaces legitimate);
      fires only on mismatch where the record EXISTS.
  (b) _INDEX row status == fact frontmatter status
  (c) notes verify_status=passes => linked fact verified: true
  (d) fact verified_by_run file exists
  (e) claim-register.yaml duplicate YAML keys (strict loader)

CLI: python carrier_consistency.py <ws> [--json]; exit 0 ok / 1 violations.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

_STAMPED = {"PROVEN", "VERIFIED"}
_OPEN_SET = {"OPEN", "INFERRED", "STAMP"}
_FACT_FILE_RE = re.compile(r"^(F-?\d+)", re.IGNORECASE)
_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n?", re.DOTALL)
_KV_RE = re.compile(r"^(\w[\w-]*):\s*(.*)$", re.M)


class _DuplicateKeyError(yaml.YAMLError):
    pass


class _StrictLoader(yaml.SafeLoader):
    pass


def _no_dupes(loader, node, deep=False):
    loader.flatten_mapping(node)
    out = {}
    for k_node, v_node in node.value:
        key = loader.construct_object(k_node, deep=deep)
        if key in out:
            raise _DuplicateKeyError("duplicate YAML key: " + str(key))
        out[key] = loader.construct_object(v_node, deep=deep)
    return out


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _no_dupes)


def _norm_fid(name):
    m = _FACT_FILE_RE.match(name)
    return ("F" + m.group(1)) if m else None


def _fm(text):
    m = _FRONTMATTER_RE.match(text)
    out = {}
    if not m:
        return out
    for k, v in _KV_RE.findall(m.group(1)):
        if k not in out:
            out[k] = v.strip()
    return out


def _fact_map(ws):
    facts = {}
    fdir = ws / "facts"
    if not fdir.exists():
        return facts
    for p in sorted(fdir.glob("*.md")):
        if p.name == "_INDEX.md":
            continue
        fid = _norm_fid(p.name)
        if fid:
            facts[fid] = _fm(p.read_text(encoding="utf-8", errors="replace"))
    return facts


def _index_rows(ws):
    idx = ws / "facts" / "_INDEX.md"
    rows = []
    if not idx.exists():
        return rows
    for line in idx.read_text(encoding="utf-8", errors="replace").splitlines():
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 3:
            rows.append({"fact": parts[0], "status": parts[1].upper(),
                         "claim": parts[2]})
    return rows


def _notes(ws):
    ndir = ws / "notes"
    out = []
    if not ndir.exists():
        return out
    for p in sorted(ndir.glob("*.md")):
        if not p.is_file():
            continue
        fm = _fm(p.read_text(encoding="utf-8", errors="replace"))
        if fm.get("claim_id") and fm.get("verify_status"):
            out.append(fm)
    return out


def _linked_claims(fm):
    links = [x.strip() for x in (fm.get("claim_id") or "").split(",")
             if x.strip()]
    for x in (fm.get("claim_ids") or "").strip("[]").split(","):
        x = x.strip()
        if x:
            links.append(x)
    return links


def check(workspace):
    ws = Path(workspace)
    violations = []
    reg_path = ws / "claim-register.yaml"
    claims = []
    if reg_path.exists():
        try:
            reg = yaml.load(reg_path.read_text(encoding="utf-8",
                                               errors="replace"),
                            Loader=_StrictLoader) or {}
            claims = reg.get("claims") or []
        except _DuplicateKeyError as exc:
            return {"ok": False, "violations": ["(e) " + str(exc)],
                    "checked": 0}
    facts = _fact_map(ws)
    rows = _index_rows(ws)
    notes = _notes(ws)

    # (b) _INDEX row status vs frontmatter; row cites existing fact
    for row in rows:
        fid = _norm_fid(row["fact"])
        fm = facts.get(fid) if fid else None
        if fm is None:
            violations.append("(b) _INDEX row cites unknown fact "
                              + str(row["fact"]))
            continue
        fm_status = (fm.get("status") or "").upper()
        if fm_status != row["status"]:
            violations.append(
                "(b) _INDEX row " + row["fact"] + " says " + row["status"]
                + " but frontmatter says " + (fm_status or "<none>"))

    # (a) register stamped iff linked fact stamped (bidirectional).
    # Carrier-record ABSENCE is not drift (sparse workspaces stay
    # legitimate); fires only when the record EXISTS unstamped.
    def _linked_stamped(cid):
        for fm in facts.values():
            if cid in _linked_claims(fm):
                return (fm.get("status") or "").upper() in _STAMPED
        for r in rows:
            if r["claim"] == cid:
                return r["status"] in _STAMPED
        return None

    for c in claims:
        cid = str(c.get("id") or "").strip()
        st = (c.get("status") or "").upper()
        if st in _STAMPED and _linked_stamped(cid) is False:
            violations.append("(a) claim " + cid + " is " + st
                              + " but linked fact is not stamped")
        if st in _OPEN_SET and _linked_stamped(cid) is True:
            violations.append("(a) fact for claim " + cid + " is stamped "
                              "but claim is " + st)


    # (c) notes passes => linked fact verified true.
    # Linked-fact ABSENCE is not drift (sparse-workspace axiom, same as (a)):
    # fires only when linked facts EXIST but none carries verified: true.
    for fm in notes:
        if fm.get("verify_status", "").strip().lower() != "passes":
            continue
        cid = fm.get("claim_id", "").strip()
        linked = [f for f, fm2 in facts.items()
                  if cid in _linked_claims(fm2)]
        if not linked:
            continue
        verified = any((facts[f].get("verified") or "").lower() == "true"
                       for f in linked)
        if not verified:
            violations.append("(c) note verify_status=passes for claim "
                              + cid + " but linked fact lacks verified: true")

    # (d) verified_by_run existence
    for fid, fm in facts.items():
        ref = (fm.get("verified_by_run") or "").strip()
        if ref and not (ws / ref).exists():
            violations.append("(d) fact " + fid + " verified_by_run cites "
                              "missing file: " + ref)

    # (f) #634: PARK legality — a suspended claim must carry a non-empty
    # wake_condition; a wake-less PARK is an unbounded wait in disguise.
    for c in claims:
        if str(c.get("status") or "").upper() != "PARK":
            continue
        if not str(c.get("wake_condition") or "").strip():
            violations.append("(f) claim " + str(c.get("id") or "<unknown>")
                              + " is PARK without wake_condition")

    return {"ok": not violations, "violations": violations,
            "checked": len(claims)}


def main():
    ap = argparse.ArgumentParser(description="#829 cross-carrier gate")
    ap.add_argument("workspace", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    r = check(a.workspace)
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        if r["ok"]:
            print("OK: carriers consistent ("
                  + str(r["checked"]) + " claims)")
        else:
            print("\n".join(r["violations"]))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    from utf8_boot import force_utf8  # #811 入口 UTF-8 保险
    force_utf8()
    sys.exit(main())
